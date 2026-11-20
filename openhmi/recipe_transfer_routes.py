"""Recipe transfer HTTP adapters; services and journal retain execution ownership."""

from types import SimpleNamespace
from fastapi import HTTPException, Request, Query, Path
from fastapi.responses import JSONResponse
from .alarms import utc_now
from .recipe_auth_routes import COOKIE
from .recipe_models import RecipeTransfer


def add_recipe_transfer_routes(app, transfers, store, auth, security, activity, user, invoke):
    """Register history, export and journaled dispatch using existing services."""
    @app.get('/api/recipe-transfers')
    def transfer_history(request: Request, limit: int = Query(default=25, ge=1, le=100),
                         before_id: int | None = Query(default=None, ge=1, le=9223372036854775807),
                         profile_id: str = Query(default='', max_length=60), production_approved: bool | None = None,
                         verified_profile: str = Query(default='', max_length=60)):
        current = user(request)
        if not current.roles:
            raise HTTPException(403, 'Recipe permission is required')
        return transfers.recent(limit, before_id, profile_id, production_approved, verified_profile)

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
