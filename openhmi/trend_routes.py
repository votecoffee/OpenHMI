"""HTTP registration for saved trend recording and capture export."""

from fastapi import HTTPException, Query, Request
from .trend_contracts import CaptureCommand


def add_trend_routes(app, recorder, security):
    @app.get('/api/trends/{control_id}')
    def list_captures(control_id: str):
        return recorder.listing(control_id)

    @app.post('/api/trends/{control_id}')
    def command(control_id: str, request: Request, body: CaptureCommand):
        security.require(request, 'runtime.operate' if body.action != 'delete' else 'project.edit')
        try:
            if body.action == 'start':
                return {'id': recorder.start(control_id)}
            if body.action == 'stop':
                recorder.stop(control_id, body.capture_id)
            else:
                recorder.delete(control_id, body.capture_id)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        return {'id': body.capture_id}

    @app.get('/api/trend-captures/{identifier}')
    def capture_history(identifier: int, seconds: int = Query(default=60, ge=1, le=604800),
                        end: float | None = Query(default=None, ge=0, le=32503680000)):
        if not 1 <= identifier <= 9223372036854775807:
            raise HTTPException(422, 'Invalid capture ID')
        return recorder.history(identifier, seconds, end)

    @app.get('/api/trend-captures/{identifier}/csv')
    def capture_csv(identifier: int):
        if not 1 <= identifier <= 9223372036854775807:
            raise HTTPException(422, 'Invalid capture ID')
        return recorder.csv(identifier)
