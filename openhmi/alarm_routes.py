"""Read-only alarm review/export and protected append-only operator notes."""

import csv
from io import StringIO
from fastapi import HTTPException, Path, Query, Request, Response
from pydantic import Field
from .projects import StrictModel
from .alarm_queries import AlarmQueries
from .operations_routes import csv_text
from .screens import screen_map


class OperatorNote(StrictModel):
    comment: str = Field(min_length=1, max_length=1000, pattern=r'\S')


def add_alarm_routes(app, monitor, security, activity, driver, store):
    queries = app.state.alarm_queries = AlarmQueries(monitor)

    def invoke(callback):
        try:
            return callback()
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        except KeyError as error:
            raise HTTPException(404, str(error).strip("'")) from error

    @app.get('/api/alarms/occurrences')
    def occurrences(limit: int = Query(default=50, ge=1, le=200), before_id: int | None = Query(default=None, ge=1, le=9223372036854775807),
                    priority: int = Query(default=0, ge=0, le=4), search: str = Query(default='', max_length=200), state: str = Query(default='outstanding', max_length=30),
                    start: str | None = Query(default=None, max_length=50), end: str | None = Query(default=None, max_length=50)):
        return invoke(lambda: queries.occurrences(limit, before_id, priority, search, state, start, end))

    @app.get('/api/alarms/events')
    def events(limit: int = Query(default=50, ge=1, le=200), before_id: int | None = Query(default=None, ge=1, le=9223372036854775807),
               priority: int = Query(default=0, ge=0, le=4), search: str = Query(default='', max_length=200), state: str = Query(default='all', max_length=30),
               start: str | None = Query(default=None, max_length=50), end: str | None = Query(default=None, max_length=50), event: str = Query(default='', max_length=30),
               occurrence_id: int | None = Query(default=None, ge=1, le=9223372036854775807)):
        return invoke(lambda: queries.history(limit, before_id, priority, search, state, start, end, event, occurrence_id))

    @app.get('/api/alarms/events.csv')
    def export_events(priority: int = Query(default=0, ge=0, le=4), search: str = Query(default='', max_length=200), state: str = Query(default='all', max_length=30),
                      start: str | None = Query(default=None, max_length=50), end: str | None = Query(default=None, max_length=50), event: str = Query(default='', max_length=30),
                      occurrence_id: int | None = Query(default=None, ge=1, le=9223372036854775807)):
        result = invoke(lambda: queries.history(20000, None, priority, search, state, start, end, event, occurrence_id))
        output = StringIO(); writer = csv.writer(output)
        writer.writerow(['event_id', 'occurrence_id', 'alarm_id', 'event', 'timestamp', 'priority', 'message', 'actor', 'provider', 'operation_id', 'comment'])
        for item in result['items']:
            definition = item['definition'] or {}
            writer.writerow([csv_text(value) for value in [item['id'], item['occurrence_id'], item['alarm_id'], item['event'], item['timestamp'], definition.get('priority'),
                             definition.get('message', item['alarm_id']), item['actor'], item['provider'], item['operation_id'], item['comment']]])
        return Response(output.getvalue(), media_type='text/csv', headers={'Content-Disposition': 'attachment; filename="alarm-events.csv"', 'X-OpenHMI-Truncated': str(result['has_more']).lower()})

    @app.get('/api/alarms/occurrences/{identifier}')
    def detail(identifier: int = Path(ge=1, le=9223372036854775807)):
        def inspect():
            result = queries.detail(identifier)
            item = result['occurrence']
            # Cached quality/time only: viewing alarm details creates no scan lease or equipment read/write.
            sample = driver.sample_snapshot().get(item['tag'])
            result['trigger'] = {key: sample.get(key) for key in ('quality', 'timestamp', 'age_seconds', 'error')} if sample else {'quality': 'unavailable', 'timestamp': None}
            target = screen_map(store.snapshot()['active']).get(item.get('related_screen'))
            result['related_screen'] = {'id': target['id'], 'title': target['title'], 'popup': target.get('popup', False)} if target else None
            return result
        return invoke(inspect)

    @app.get('/api/alarms/occurrences/{identifier}/notes')
    def notes(identifier: int = Path(ge=1, le=9223372036854775807), limit: int = Query(default=50, ge=1, le=100), before_id: int | None = Query(default=None, ge=1, le=9223372036854775807)):
        return invoke(lambda: queries.notes(identifier, limit, before_id))

    @app.post('/api/alarms/occurrences/{identifier}/notes')
    def note(body: OperatorNote, request: Request, identifier: int = Path(ge=1, le=9223372036854775807)):
        def execute(ticket):
            principal = security.require(request, 'alarms.comment')
            identity = (principal.name, principal.provider) if principal else ('unsecured-simulation', 'simulation')
            with monitor.lock:
                invoke(lambda: queries.detail(identifier))
                ticket.dispatch()
                result = monitor.note(identifier, body.comment, identity, ticket.id)
                ticket.confirm(verification='alarm_note_saved', note_id=result['note_id'])
                return result
        return activity.run(request, 'alarm_note', str(identifier), {'occurrence_id': identifier, 'comment': body.comment}, execute)
