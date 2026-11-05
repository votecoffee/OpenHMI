"""Recipe HTTP adapter. Identity and policy checks stay on the server."""

from fastapi import HTTPException, Request, Response, Query, Path
from fastapi.responses import JSONResponse
from types import SimpleNamespace
from pydantic import Field
from .alarms import utc_now
from .projects import StrictModel
from .recipe_auth import RecipeAuth
from .recipe_models import ChangeReason, RecipeCreate, RecipeSave, RecipeTransition, RecipeSelect, RecipeTransfer, PolicyChange, SimulationPermit
from .recipe_transfers import RecipeTransfers
from .recipes import RecipeService, RecipeError
from .security import COOKIE as APP_COOKIE
from .security_routes import set_session

COOKIE = 'openhmi_recipe_session'


class Login(StrictModel):
    name: str = Field(min_length=1, max_length=60)
    password: str = Field(min_length=1, max_length=256)


class Empty(StrictModel):
    pass


def add_recipe_routes(app, store, application, users=None, security=None, commands=None, activity=None):
    auth = RecipeAuth(users)
    service = RecipeService(store, application)
    app.state.recipes = application.recipes = service
    app.state.recipe_auth = auth
    transfers = app.state.recipe_transfers = RecipeTransfers(store, application, service, commands)

    def user(request):
        origin = request.headers.get('origin')
        if origin and origin != f'{request.url.scheme}://{request.url.netloc}':
            raise HTTPException(403, 'Recipe changes require a same-origin request')
        current = security.user(request.cookies.get(APP_COOKIE)) if security and security.configured() else auth.user(request.cookies.get(COOKIE))
        if not current:
            raise HTTPException(401, 'Sign in to perform a recipe operation')
        return current

    def invoke(method, *args):
        try:
            return method(*args)
        except RecipeError as error:
            raise HTTPException(error.status, str(error)) from error

    @app.get('/api/recipe-auth/session')
    def session(request: Request):
        if security and security.configured():
            current = security.user(request.cookies.get(APP_COOKIE))
            return {'configured': True, 'user': current.public() if current else None}
        current = auth.user(request.cookies.get(COOKIE))
        return {'configured': bool(auth.users), 'user': {'name': current.name, 'roles': sorted(current.roles)} if current else None}

    @app.post('/api/recipe-auth/login')
    def login(body: Login, request: Request, response: Response):
        origin = request.headers.get('origin')
        if origin and origin != f'{request.url.scheme}://{request.url.netloc}':
            raise HTTPException(403, 'Sign-in requires a same-origin request')
        if security and security.configured():
            token, current = security.login(body.name, body.password, request.client.host if request.client else 'local')
            security.logout(request.cookies.get(APP_COOKIE))
            set_session(response, request, token)
            return {'user': current.public()}
        try:
            token = auth.login(body.name, body.password, request.client.host if request.client else 'local')
        except ValueError as error:
            raise HTTPException(429, str(error)) from error
        if not token:
            raise HTTPException(401, 'Invalid recipe credentials')
        auth.logout(request.cookies.get(COOKIE))
        response.set_cookie(COOKIE, token, httponly=True, samesite='strict', secure=request.url.scheme == 'https', max_age=3600)
        current = auth.user(token)
        return {'user': {'name': current.name, 'roles': sorted(current.roles)}}

    @app.post('/api/recipe-auth/logout')
    def logout(body: Empty, request: Request, response: Response):
        if security and security.configured():
            security.origin(request)
            security.logout(request.cookies.get(APP_COOKIE))
            response.delete_cookie(APP_COOKIE)
            return {'ok': True}
        user(request)
        auth.logout(request.cookies.get(COOKIE))
        response.delete_cookie(COOKIE)
        return {'ok': True}

    @app.get('/api/recipes')
    def recipes():
        return service.snapshot()

    @app.get('/api/recipes/selected')
    def selected():
        return service.selected()

    @app.get('/api/recipe-transfers')
    def transfer_history(request: Request, limit: int = Query(default=25, ge=1, le=100),
                         before_id: int | None = Query(default=None, ge=1, le=9223372036854775807)):
        current = user(request)
        if not current.roles:
            raise HTTPException(403, 'Recipe permission is required')
        return transfers.recent(limit, before_id)

    @app.get('/api/recipe-transfers/{identifier}')
    def transfer_record(request: Request, identifier: int = Path(ge=1, le=9223372036854775807), download: bool = False):
        current = user(request)
        if not current.roles:
            raise HTTPException(403, 'Recipe permission is required')
        record = transfers.get(identifier)
        if not download:
            return record
        return JSONResponse({
            'format': 'openhmi.recipe-transfer',
            'version': 1,
            'project_id': store.snapshot()['project_id'],
            'exported_at': utc_now(),
            'transfer': record,
        }, headers={'Content-Disposition': f'attachment; filename="openhmi-recipe-transfer-{identifier}.json"',
                    'Cache-Control': 'no-store'})

    @app.post('/api/recipe-transfers/{profile_id}/dispatch')
    def transfer(profile_id: str, body: RecipeTransfer, request: Request):
        if not security.configured():
            current = auth.user(request.cookies.get(COOKIE))
            if current:
                request.state.activity_principal = SimpleNamespace(name=current.name, provider='recipe-local', groups=['recipe:' + role for role in current.roles])
        def execute(ticket):
            current = user(request)
            def authorize(definition):
                if security.configured() or definition['security_groups']:
                    security.require(request, 'runtime.operate', definition['security_groups'])
            return invoke(transfers.submit, profile_id, body, current, ticket, authorize)
        return activity.run(request, 'recipe_transfer', profile_id,
                            {'revision_id': body.revision_id, 'reason': body.reason,
                             'expected_project_revision': body.expected_project_revision}, execute)

    @app.post('/api/recipes')
    def create(body: RecipeCreate, request: Request):
        return invoke(service.create, body, user(request))

    @app.post('/api/recipes/{recipe_id}/revisions')
    def save(recipe_id: int, body: RecipeSave, request: Request):
        return invoke(service.save, recipe_id, body, user(request))

    @app.post('/api/recipe-revisions/{revision_id}/transition')
    def transition(revision_id: int, body: RecipeTransition, request: Request):
        return invoke(service.transition, revision_id, body, user(request))

    @app.post('/api/recipes/select')
    def select(body: RecipeSelect, request: Request):
        return invoke(service.select, body, user(request))

    @app.put('/api/recipes/policy')
    def policy(body: PolicyChange, request: Request):
        return invoke(service.update_policy, body, user(request))

    @app.post('/api/recipes/simulator-permit')
    def permit(body: SimulationPermit, request: Request):
        return invoke(service.simulator_permit, body, user(request))

    @app.get('/api/recipe-images/{image_id}')
    def image(image_id: str):
        return Response(invoke(service.image, image_id), media_type='image/png', headers={'Cache-Control': 'public,max-age=31536000,immutable', 'X-Content-Type-Options': 'nosniff'})

    @app.post('/api/recipe-images')
    async def upload_image(request: Request, reason: str = Query(min_length=1, max_length=1000)):
        current = user(request)
        if not current.permits('engineer'):
            raise HTTPException(403, 'Recipe engineer role is required')
        if request.headers.get('content-type', '').split(';')[0] not in ('image/png', 'image/jpeg'):
            raise HTTPException(415, 'Upload a PNG or JPEG image')
        if not reason.strip():
            raise HTTPException(422, 'A meaningful image change reason is required')
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 5 * 1024 * 1024:
                raise HTTPException(413, 'Recipe image upload exceeds 5 MiB')
        return invoke(service.add_image, bytes(data), reason, current)
