"""Stage a complete CSV before exposing it as a browser download."""

import csv
from datetime import datetime, timezone
from io import StringIO
import json
import sqlite3
from tempfile import TemporaryFile

from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from .historian import HistoryChanged
from .operations_routes import csv_text

CSV_COLUMNS = ['tag', 'timestamp', 'value', 'quality', 'source_timestamp']
MAX_EXPORT_BYTES = 1024 ** 3


def csv_row(tag, timestamp, value, quality, source):
    return [tag, timestamp, csv_text(value) if isinstance(value, str) else value, quality, source]


class HistoryDownload(StreamingResponse):
    def __init__(self, file, slot):
        self.file, self.slot = file, slot
        super().__init__(iter(lambda: file.read(64 * 1024), b''), media_type='text/csv',
                         headers={'Content-Disposition': 'attachment; filename="tag-history.csv"'})

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            try:
                self.file.close()
            finally:
                self.slot.release()


def complete_history_csv(historian, tags, start, end):
    if not historian.export_slot.acquire(blocking=False):
        raise HTTPException(429, 'A complete history export is already running for this project')
    file = None
    try:
        file = TemporaryFile()
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(CSV_COLUMNS)
        for tag, rows in historian.export_batches(tags, start, end):
            for stamp, _, value, quality, source in rows:
                writer.writerow(csv_row(tag, datetime.fromtimestamp(stamp, timezone.utc).isoformat(),
                                        json.loads(value) if value else None, quality, source))
            payload = output.getvalue().encode('utf-8')
            if file.tell() + len(payload) > MAX_EXPORT_BYTES:
                raise HTTPException(413, 'Complete CSV exceeds 1 GiB. Choose a shorter range.')
            file.write(payload)
            output.seek(0)
            output.truncate(0)
        file.write(output.getvalue().encode('utf-8'))
        file.seek(0)
        response = HistoryDownload(file, historian.export_slot)
    except BaseException as error:
        try:
            if file is not None:
                file.close()
        finally:
            historian.export_slot.release()
        if isinstance(error, HistoryChanged):
            raise HTTPException(409, str(error)) from error
        if isinstance(error, sqlite3.ProgrammingError) and 'closed database' in str(error):
            raise HTTPException(409, 'The project was closed during export. Reopen it to retry.') from error
        if isinstance(error, OSError):
            raise HTTPException(507, 'Could not stage the CSV in temporary storage.') from error
        raise
    return response
