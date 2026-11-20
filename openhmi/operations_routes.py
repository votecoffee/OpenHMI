"""Protected operator activity and read-only runtime diagnostics."""

import csv
from datetime import datetime, timezone
from io import StringIO
import json
import time
from typing import Literal
from fastapi import HTTPException, Query, Request
from fastapi.responses import Response
from .activity import STATUSES
from .diagnostics import runtime_diagnostics
from .security import COOKIE


DiagnosticQuality = Literal['all', 'non-good', 'bad', 'stale', 'pending', 'good']


def can_view(security, request, permission):
    principal = security.user(request.cookies.get(COOKIE))
    # Existing security administrators can inspect new journals without rewriting their groups.
    return security.require(request, 'security.manage' if principal and 'security.manage' in principal.permissions else permission)


def csv_text(value):
    text = '' if value is None else str(value)
    return "'" + text if text.lstrip().startswith(('=', '+', '-', '@')) or text.startswith(('\t', '\r')) else text


def add_operations_routes(app, journal, security, driver, workers):
    def activity_result(request, limit, before_id, actor, status, search, start, end):
        can_view(security, request, 'activity.view')
        if status and status not in STATUSES:
            raise HTTPException(422, 'Unknown activity outcome')
        try:
            return journal.query(limit, before_id, actor, status, search, start, end)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @app.get('/api/activity')
    def activity(request: Request, limit: int = Query(default=100, ge=1, le=1000), before_id: int | None = Query(default=None, ge=1, le=9223372036854775807),
                 actor: str = Query(default='', max_length=200), status: str = Query(default='', max_length=30),
                 search: str = Query(default='', max_length=100), start: str | None = Query(default=None, max_length=50), end: str | None = Query(default=None, max_length=50)):
        return activity_result(request, limit, before_id, actor, status, search, start, end)

    @app.get('/api/activity.csv')
    def activity_csv(request: Request, actor: str = Query(default='', max_length=200), status: str = Query(default='', max_length=30),
                     search: str = Query(default='', max_length=100), start: str | None = Query(default=None, max_length=50), end: str | None = Query(default=None, max_length=50)):
        data = activity_result(request, 20000, None, actor, status, search, start, end)
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(['operation_id', 'started_at', 'finished_at', 'actor', 'provider', 'groups', 'operation', 'entity', 'phase', 'status', 'context', 'outcome', 'error'])
        for item in data['items']:
            writer.writerow([csv_text(json.dumps(item[key], ensure_ascii=False) if isinstance(item[key], (dict, list)) else item[key]) for key in
                             ['operation_id', 'started_at', 'finished_at', 'actor', 'provider', 'groups', 'operation', 'entity', 'phase', 'status', 'context', 'outcome', 'error']])
        return Response(output.getvalue(), media_type='text/csv', headers={'Content-Disposition': 'attachment; filename="operator-activity.csv"', 'X-OpenHMI-Truncated': str(data['has_more']).lower()})

    def diagnostic_data(request, search, quality, connection_filter, offset, limit):
        can_view(security, request, 'diagnostics.view')
        return runtime_diagnostics(driver, workers, search, quality, connection_filter, offset, limit)

    @app.get('/api/diagnostics')
    def diagnostics(request: Request, search: str = Query(default='', max_length=100),
                    offset: int = Query(default=0, ge=0, le=100000), limit: int = Query(default=100, ge=1, le=1000),
                    quality: DiagnosticQuality = 'all', connection: str = Query(default='', max_length=60)):
        return diagnostic_data(request, search, quality, connection, offset, limit)

    @app.get('/api/diagnostics.json')
    def export_diagnostics(request: Request, search: str = Query(default='', max_length=100),
                           quality: DiagnosticQuality = 'all', connection: str = Query(default='', max_length=60)):
        capture = {'project_instance': app.state.project_instance, 'monotonic_seconds': time.monotonic(),
                   'utc': datetime.now(timezone.utc).isoformat()}
        data = diagnostic_data(request, search, quality, connection, 0, 5000)
        data['capture'] = capture
        return Response(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False), media_type='application/json',
                        headers={'Content-Disposition': 'attachment; filename="runtime-diagnostics.json"'})
