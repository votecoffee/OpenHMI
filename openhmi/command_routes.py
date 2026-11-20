"""HTTP registration for command history and transaction export."""

from fastapi import Path, Query, Request
from fastapi.responses import JSONResponse
from .alarms import utc_now
from .command_contracts import CommandHistoryState


def add_command_routes(app, service, security):
    @app.get('/api/commands')
    def recent(request: Request, limit: int = Query(default=100, ge=1, le=200),
               before_id: int | None = Query(default=None, ge=1, le=9223372036854775807),
               command_id: str = Query(default='', max_length=60), state: CommandHistoryState = ''):
        security.require(request, 'runtime.operate')
        return service.recent(limit, before_id, command_id, state)

    @app.get('/api/commands/{identifier}')
    def transaction(request: Request, identifier: int = Path(ge=1, le=9223372036854775807), download: bool = False):
        security.require(request, 'runtime.operate')
        record = service.get(identifier)
        if not download:
            return record
        return JSONResponse({
            'format': 'openhmi.command-transaction',
            'version': 1,
            'project_id': service.store.snapshot()['project_id'],
            'exported_at': utc_now(),
            'transaction': record,
        }, headers={'Content-Disposition': f'attachment; filename="openhmi-command-{identifier}.json"',
                    'Cache-Control': 'no-store'})
