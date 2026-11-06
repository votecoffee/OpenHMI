"""Protected operator activity and read-only runtime diagnostics."""

import csv
from datetime import datetime, timezone
from io import StringIO
import json
import time
from fastapi import HTTPException, Query, Request
from fastapi.responses import Response
from .activity import STATUSES
from .security import COOKIE


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

    def diagnostic_data(request, search, offset, limit):
        can_view(security, request, 'diagnostics.view')
        now = time.monotonic()
        samples = driver.sample_snapshot(now)
        query = search.casefold()
        names = sorted(name for name in samples if query in name.casefold())
        tags = []
        for name in names[offset:offset + limit]:
            root, member = driver.sources.get(name, (None, ''))
            definition = driver.definitions.get(root)
            sample = samples[name]
            tags.append({'name': name, 'connection': definition['connection'] if definition else '',
                         'address': definition['address'] + ('.' + member if member else '') if definition and definition['connection'] else 'Local HMI',
                         'type': definition['members'][member] if definition and member else definition['type'] if definition else type(sample.get('value')).__name__,
                         'quality': sample['quality'], 'timestamp': sample.get('timestamp'), 'age_seconds': sample.get('age_seconds', 0 if sample['quality'] == 'good' else None),
                         'error': sample.get('error')})
        live = {connection['id']: connection for connection in driver.status(include_timing=True)}
        connections = []
        for config in (driver.project or {}).get('connections', []):
            status = live.get(config['id'], {})
            state = (
                'disabled' if not config['enabled'] else
                'held' if driver.plc_hold else
                'scan overdue' if status.get('scan_overdue') else
                'recovering' if status.get('recovering') else
                'waiting for first good data' if status.get('awaiting_data') else
                'no usable data' if status.get('data_unavailable') else
                'connected' if status.get('connected') else 'disconnected'
            )
            connections.append({'id': config['id'], 'name': config['name'], 'path': config['path'], 'state': state,
                                'connection_instance': status.get('connection_instance'),
                                'scan_age_seconds': status.get('scan_age_seconds'),
                                'error': status.get('error'), 'read_calls': status.get('read_calls', 0), 'tags_read': status.get('tags_read', 0), 'groups': status.get('groups', []),
                                'timings': status.get('timings', {}), 'route_failures': status.get('route_failures', 0)})
        return {'workers': workers.snapshot(), 'connections': connections, 'tags': tags, 'total_tags': len(names), 'offset': offset,
                'next_offset': offset + limit if offset + limit < len(names) else None, 'truncated': offset + limit < len(names),
                'plc_hold': driver.plc_hold, 'counter_scope': 'pycomm3 read calls and requested addresses; not wire-packet measurements', 'scan_timing': 'best effort'}

    @app.get('/api/diagnostics')
    def diagnostics(request: Request, search: str = Query(default='', max_length=100), offset: int = Query(default=0, ge=0, le=100000), limit: int = Query(default=100, ge=1, le=1000)):
        return diagnostic_data(request, search, offset, limit)

    @app.get('/api/diagnostics.json')
    def export_diagnostics(request: Request, search: str = Query(default='', max_length=100)):
        capture = {'project_instance': app.state.project_instance, 'monotonic_seconds': time.monotonic(),
                   'utc': datetime.now(timezone.utc).isoformat()}
        data = diagnostic_data(request, search, 0, 5000)
        data['capture'] = capture
        return Response(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False), media_type='application/json',
                        headers={'Content-Disposition': 'attachment; filename="runtime-diagnostics.json"'})
