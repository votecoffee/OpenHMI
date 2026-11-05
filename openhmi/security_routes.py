"""Session and HMI security administration HTTP routes."""

from typing import Literal
from fastapi import HTTPException, Request, Response
from pydantic import Field, model_validator
from .projects import StrictModel
from .security import COOKIE


class Login(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=256)
    provider: Literal['local', 'windows'] = 'local'


class SecurityChange(StrictModel):
    operation: Literal['group', 'user', 'binding', 'unbind', 'windows']
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)
    name: str = Field(default='', max_length=60, pattern=r'^[A-Za-z0-9_. -]*$')
    permissions: list[str] = Field(default_factory=list, max_length=30)
    color: str | None = Field(default=None, pattern=r'^#[A-Fa-f0-9]{6}$')
    groups: list[str] = Field(default_factory=list, max_length=100)
    password: str | None = Field(default=None, min_length=12, max_length=256)
    enabled: bool = True
    account: str = Field(default='', max_length=200)
    kind: Literal['user', 'group'] = 'group'
    group: str = Field(default='', max_length=60)
    sid: str = Field(default='', max_length=200)

    @model_validator(mode='after')
    def meaningful_change(self):
        if not self.reason.strip():
            raise ValueError('A meaningful security change reason is required')
        if self.operation in ('group', 'user') and (not self.name.strip() or self.name != self.name.strip()):
            raise ValueError('Use a nonempty name without surrounding spaces')
        if self.operation == 'binding' and (not self.account.strip() or '\x00' in self.account):
            raise ValueError('A Windows account/group name is required')
        if self.operation == 'unbind' and not self.sid.startswith('S-'):
            raise ValueError('A Windows SID is required')
        return self


def set_session(response, request, token):
    response.set_cookie(COOKIE, token, httponly=True, samesite='strict', secure=request.url.scheme == 'https', max_age=3600)


def add_security_routes(app, security):
    @app.get('/api/security/session')
    def session(request: Request):
        user = security.user(request.cookies.get(COOKIE))
        with security.store._lock:
            enabled = security.store._db.execute('SELECT windows_enabled FROM security_settings').fetchone()[0]
        return {'configured': security.configured(), 'windows_enabled': bool(enabled),
                'windows_available': security.windows.available, 'user': user.public() if user else None, 'groups': security.legend()}

    @app.post('/api/security/login')
    def login(body: Login, request: Request, response: Response):
        security.origin(request)
        token, principal = security.login(body.name, body.password, request.client.host if request.client else 'local', body.provider)
        if hasattr(app.state, 'identity_publisher'):
            app.state.identity_publisher.replace_login(request.cookies.get(COOKIE), token)
        security.logout(request.cookies.get(COOKIE))
        set_session(response, request, token)
        return {'user': principal.public()}

    @app.post('/api/security/logout')
    def logout(request: Request, response: Response):
        security.origin(request)
        if hasattr(app.state, 'identity_publisher'):
            app.state.identity_publisher.replace_login(request.cookies.get(COOKIE), None)
        security.logout(request.cookies.get(COOKIE))
        response.delete_cookie(COOKIE)
        return {'ok': True}

    def administrator(request):
        user = security.require(request, 'security.manage')
        if not user:
            raise HTTPException(401, 'Bootstrap a local administrator with openhmi-security first')
        return user

    @app.get('/api/security')
    def configuration(request: Request):
        administrator(request)
        return security.snapshot()

    @app.put('/api/security')
    def update(body: SecurityChange, request: Request):
        with security.lock:
            user = administrator(request)
            if not body.reason.strip() or (body.operation in ('group', 'user') and not body.name.strip()):
                raise HTTPException(422, 'A name and meaningful change reason are required')
            try:
                return security.change(body, user.name)
            except (ValueError, OSError) as error:
                raise HTTPException(422, str(error)) from error
