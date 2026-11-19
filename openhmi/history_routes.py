"""Historian queries and bounded CSV downloads for one project instance."""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from .history_export import CSV_COLUMNS, complete_history_csv, csv_row


def history_window(tags, seconds, end, start=None):
    import time
    import math
    names = list(dict.fromkeys(tags.split(',')))
    if len(names) > 12 or any(len(name) > 200 for name in names):
        raise HTTPException(422, 'History tag limits exceeded')
    finish = end if end is not None else time.time()
    if not math.isfinite(finish) or not 0 <= finish <= 32503680000:
        raise HTTPException(422, 'Invalid history end timestamp')
    if start is not None and (not math.isfinite(start) or not 0 <= start < finish or finish - start > 31536000):
        raise HTTPException(422, 'History start must be before the end and within 365 days')
    return names, finish - seconds if start is None else start, finish


def add_history_routes(app, historian, instance):
    router = APIRouter()

    @router.get('/api/history')
    def history(tags: str, seconds: int = Query(default=300, ge=1, le=31536000), limit: int = Query(default=2000, ge=1, le=20000), end: float | None = None, trend_context: bool = False):
        return historian.query(*history_window(tags, seconds, end), limit, trend_context)

    def require_history_project(project_instance):
        if project_instance is not None and project_instance != instance:
            raise HTTPException(409, 'A different project was opened. Reload before exporting history.')

    @router.get('/api/history/tags')
    def history_tags(prefix: str = Query(default='', max_length=200), after: str | None = Query(default=None, max_length=200),
                     limit: int = Query(default=50, ge=1, le=100),
                     project_instance: str | None = Query(default=None, max_length=32)):
        require_history_project(project_instance)
        if after is not None and not after.startswith(prefix):
            raise HTTPException(422, 'History tag cursor must match the search prefix')
        return historian.recorded_tags(prefix, after, limit)

    @router.get('/api/history.csv')
    def history_csv(tags: str, seconds: int = Query(default=3600, ge=1, le=31536000),
                    end: float | None = None, start: float | None = None):
        import csv
        from io import StringIO
        data = historian.query(*history_window(tags, seconds, end, start), 20000)
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(CSV_COLUMNS)
        for row in data['samples']:
            writer.writerow(csv_row(row['tag'], row['timestamp'], row['value'], row['quality'], row['source_timestamp']))
        return Response(output.getvalue(), media_type='text/csv', headers={'Content-Disposition': 'attachment; filename="tag-history.csv"', 'X-OpenHMI-Truncated': str(data['truncated']).lower()})

    @router.get('/api/history/full.csv')
    def history_full_csv(tags: str, seconds: int = Query(default=3600, ge=1, le=31536000),
                         end: float | None = None, start: float | None = None,
                         project_instance: str | None = Query(default=None, max_length=32)):
        require_history_project(project_instance)
        return complete_history_csv(historian, *history_window(tags, seconds, end, start))

    app.include_router(router)
