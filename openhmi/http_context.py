"""Shared project-instance guards and HTTP operation receipt headers."""

from fastapi import HTTPException
from fastapi.responses import JSONResponse


def require_project_instance(request, instance):
    """Keep writes from a previously opened project out of the current runtime."""
    expected = request.headers.get('x-openhmi-project')
    if request.method not in ('GET', 'HEAD', 'OPTIONS') and expected and expected != instance:
        raise HTTPException(409, 'A different project was opened. Reload before making changes.')


def set_response_context(request, response, instance):
    """Describe the request's project and any durable operation, without replay."""
    response.headers['X-OpenHMI-Project'] = instance
    if hasattr(request.state, 'activity_operation'):
        response.headers['X-OpenHMI-Operation-ID'] = request.state.activity_operation
        response.headers['X-OpenHMI-Audit-Status'] = getattr(request.state, 'activity_status', 'pending')
    return response


def add_project_context_middleware(app, instance):
    @app.middleware('http')
    async def project_identity(request, call_next):
        try:
            require_project_instance(request, instance)
        except HTTPException as error:
            response = JSONResponse({'detail': error.detail}, status_code=error.status_code)
        else:
            response = await call_next(request)
        return set_response_context(request, response, instance)
