"""Recipe-local sessions and HMI-account delegation; no recipe/driver ownership."""

from fastapi import HTTPException, Request, Response
from .security import COOKIE as APP_COOKIE
from .security_routes import set_session

COOKIE = 'openhmi_recipe_session'


def require_recipe_user(request, auth, security=None):
    origin = request.headers.get('origin')
    if origin and origin != f'{request.url.scheme}://{request.url.netloc}':
        raise HTTPException(403, 'Recipe changes require a same-origin request')
    current = security.user(request.cookies.get(APP_COOKIE)) if security and security.configured() else auth.user(request.cookies.get(COOKIE))
    if not current:
        raise HTTPException(401, 'Sign in to perform a recipe operation')
    return current


def add_recipe_auth_routes(app, auth, security, login_model, empty_model):
    """Register sessions using the caller's stable public request-model types."""
    @app.get('/api/recipe-auth/session')
    def session(request: Request):
        if security and security.configured():
            current = security.user(request.cookies.get(APP_COOKIE))
            return {'configured': True, 'user': current.public() if current else None}
        current = auth.user(request.cookies.get(COOKIE))
        return {'configured': bool(auth.users), 'user': {'name': current.name, 'roles': sorted(current.roles)} if current else None}

    @app.post('/api/recipe-auth/login')
    def login(body: login_model, request: Request, response: Response):
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
    def logout(body: empty_model, request: Request, response: Response):
        if security and security.configured():
            security.origin(request)
            security.logout(request.cookies.get(APP_COOKIE))
            response.delete_cookie(APP_COOKIE)
            return {'ok': True}
        require_recipe_user(request, auth, security)
        auth.logout(request.cookies.get(COOKIE))
        response.delete_cookie(COOKIE)
        return {'ok': True}
