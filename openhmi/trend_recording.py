"""Saved rolling trend captures, independent of the continuous tag historian."""

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from io import StringIO
import json
from threading import RLock
import time
from typing import Literal

from fastapi import HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from .drivers import SimulatorDriver
from .logix import type_ok
from .screens import expanded_controls

MAX_CAPTURES = 100
MAX_RESERVED_SAMPLES = 100000


def stamp(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


@dataclass
class Running:
    identifier: int
    sequence: int = 0
    deadline: float = 0


class TrendRecorder:
    def __init__(self, store, driver):
        self.store, self.driver = store, driver
        self.lock = RLock()
        self.plans, self.running, self.previous, self.errors = {}, {}, {}, {}
        with store.transaction() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS trend_capture (
                id INTEGER PRIMARY KEY AUTOINCREMENT, control_id TEXT NOT NULL, title TEXT NOT NULL,
                series TEXT NOT NULL, started REAL NOT NULL, stopped REAL, reason TEXT,
                capacity INTEGER NOT NULL, sample_ms INTEGER NOT NULL, frames_written INTEGER NOT NULL DEFAULT 0
            )''')
            db.execute('CREATE INDEX IF NOT EXISTS trend_capture_control ON trend_capture(control_id, id)')
            db.execute('''CREATE TABLE IF NOT EXISTS trend_frame (
                capture_id INTEGER NOT NULL REFERENCES trend_capture(id) ON DELETE CASCADE,
                sequence INTEGER NOT NULL, epoch REAL NOT NULL, samples TEXT NOT NULL,
                PRIMARY KEY (capture_id, sequence)
            ) WITHOUT ROWID''')
            db.execute('CREATE INDEX IF NOT EXISTS trend_frame_time ON trend_frame(capture_id, epoch, sequence)')
            db.execute("UPDATE trend_capture SET stopped = MAX(started, ?), reason = 'interrupted' WHERE stopped IS NULL", (time.time(),))

    def configure(self, project):
        kinds = {tag: 'boolean' if type(value) is bool else 'number' for tag, value in SimulatorDriver().snapshot().items()}
        definitions = {tag['name']: tag for tag in project['tags']}
        connections = {conn['id']: conn for conn in project['connections']}
        for tag, definition in definitions.items():
            kinds[tag] = 'boolean' if definition['type'] == 'boolean' else 'number'
            kinds.update({f'{tag}.{member}': 'boolean' if kind == 'boolean' else 'number'
                          for member, kind in definition['members'].items()})
        plans = {}
        for control in expanded_controls(project):
            if control['kind'] != 'trend' or not control.get('recording'):
                continue
            settings = control['recording']
            tags = list(dict.fromkeys(control['tags']))
            series = [{'tag': tag, 'type': kinds[tag], **control.get('series', {}).get(tag, {})} for tag in tags]
            monitored = [*tags, settings['start_tag'], settings['stop_tag']]
            sources = []
            for tag in monitored:
                root, _ = self.driver.sources.get(tag, ('', ''))
                definition = definitions.get(root, {})
                sources.append((definition, connections.get(definition.get('connection'))))
            plans[control['id']] = {'title': control['label'], 'series': series, 'settings': settings,
                                    'contract': (tags, settings, sources)}
        with self.lock:
            for control_id, old in self.plans.items():
                if control_id not in plans or old['contract'] != plans[control_id]['contract']:
                    if control_id in self.running:
                        self._stop(control_id, time.time(), 'configuration changed')
                    self.previous.pop(control_id, None)
                    self.errors.pop(control_id, None)
            self.plans = plans
            self._update_demands()

    def _update_demands(self):
        demands = {}
        for control_id, plan in self.plans.items():
            settings = plan['settings']
            tags = [settings['start_tag'], settings['stop_tag']]
            if control_id in self.running:
                tags.extend(item['tag'] for item in plan['series'])
            for tag in filter(None, tags):
                rate = min(settings['sample_ms'], 250) if tag in (settings['start_tag'], settings['stop_tag']) else settings['sample_ms']
                demands[tag] = min(rate, demands.get(tag, rate))
        with self.driver.lock:
            self.driver.trend_demands = demands

    def _start(self, control_id, wall):
        if control_id in self.running:
            return self.running[control_id].identifier
        if control_id not in self.plans:
            raise ValueError('Enable and apply recording for this Trend first')
        if self.driver.plc_hold:
            raise ValueError('Apply live to release the imported project before recording')
        plan = self.plans[control_id]
        settings = plan['settings']
        with self.store.transaction() as db:
            count, reserved = db.execute('SELECT COUNT(*), COALESCE(SUM(capacity), 0) FROM trend_capture').fetchone()
            if count >= MAX_CAPTURES or reserved + settings['max_samples'] > MAX_RESERVED_SAMPLES:
                raise ValueError('Project capture storage is full. Export and delete a saved capture to free space.')
            identifier = db.execute('''INSERT INTO trend_capture
                (control_id, title, series, started, capacity, sample_ms) VALUES (?, ?, ?, ?, ?, ?)''',
                (control_id, plan['title'], json.dumps(plan['series']), wall, settings['max_samples'], settings['sample_ms'])).lastrowid
        self.running[control_id] = Running(identifier)
        self.errors.pop(control_id, None)
        self._update_demands()
        return identifier

    def _stop(self, control_id, wall, reason):
        running = self.running[control_id]
        with self.store.transaction() as db:
            db.execute('UPDATE trend_capture SET stopped = MAX(started, ?), reason = ? WHERE id = ?',
                       (wall, reason, running.identifier))
        del self.running[control_id]
        self._update_demands()

    def start(self, control_id):
        with self.lock:
            return self._start(control_id, time.time())

    def stop(self, control_id, identifier):
        with self.lock:
            running = self.running.get(control_id)
            if not running or running.identifier != identifier:
                raise ValueError('The running capture changed. Refresh and try again.')
            self._stop(control_id, time.time(), 'manual stop')

    def shutdown(self):
        with self.lock:
            for control_id in list(self.running):
                self._stop(control_id, time.time(), 'runtime stopped')

    def sample(self, now=None, wall=None):
        with self.lock:
            if self.driver.plc_hold or not self.driver.trend_demands:
                return
            now = time.monotonic() if now is None else now
            wall = time.time() if wall is None else wall
            values = self.driver.sample_snapshot(now)
            for control_id, plan in self.plans.items():
                settings = plan['settings']
                start_tag, stop_tag = settings['start_tag'], settings['stop_tag']

                def signal(tag):
                    sample = values.get(tag, {})
                    value = sample.get('value')
                    return value if sample.get('quality') == 'good' and type(value) is bool else None

                start, stop = signal(start_tag), signal(stop_tag)
                old_start, old_stop = self.previous.get(control_id, (None, None))
                self.previous[control_id] = (start, stop)
                if stop is True and old_stop is False and control_id in self.running:
                    self._stop(control_id, wall, 'stop trigger')
                elif start is True and old_start is False and (not stop_tag or stop is False) and control_id not in self.running:
                    try:
                        self._start(control_id, wall)
                    except ValueError as error:
                        self.errors[control_id] = str(error)
                running = self.running.get(control_id)
                if running and now >= running.deadline:
                    self._record(plan, running, values, now, wall)

    def _record(self, plan, running, values, now, wall):
        frame = []
        for item in plan['series']:
            sample = values.get(item['tag'], {})
            quality, value = sample.get('quality', 'pending'), sample.get('value')
            if quality == 'good' and not type_ok(value, item['type']):
                quality = 'bad'
            frame.append([value if quality == 'good' else None, quality, sample.get('timestamp')])
        sequence = running.sequence + 1
        settings = plan['settings']
        with self.store.transaction() as db:
            db.execute('INSERT INTO trend_frame VALUES (?, ?, ?, ?)',
                       (running.identifier, sequence, wall, json.dumps(frame, separators=(',', ':'), allow_nan=False)))
            db.execute('DELETE FROM trend_frame WHERE capture_id = ? AND sequence <= ?',
                       (running.identifier, sequence - settings['max_samples']))
            db.execute('UPDATE trend_capture SET frames_written = ? WHERE id = ?', (sequence, running.identifier))
        running.sequence = sequence
        running.deadline = now + settings['sample_ms'] / 1000

    def listing(self, control_id):
        with self.lock, self.store._lock:
            rows = self.store._db.execute('''SELECT id, title, series, started, stopped, reason, capacity, sample_ms,
                                            frames_written,
                                            (SELECT epoch FROM trend_frame WHERE capture_id = c.id ORDER BY epoch LIMIT 1),
                                            (SELECT epoch FROM trend_frame WHERE capture_id = c.id ORDER BY epoch DESC LIMIT 1)
                                            FROM trend_capture c WHERE control_id = ? ORDER BY id DESC''',
                                          (control_id,)).fetchall()
            captures = [{'id': row[0], 'title': row[1], 'series': json.loads(row[2]), 'started': row[3],
                         'stopped': row[4], 'reason': row[5], 'max_samples': row[6], 'sample_ms': row[7],
                         'retained': min(row[6], row[8]), 'rolled_off': max(0, row[8] - row[6]),
                         'first': row[9], 'last': row[10]} for row in rows]
            return {'enabled': control_id in self.plans, 'error': self.errors.get(control_id), 'captures': captures}

    def delete(self, control_id, identifier):
        with self.lock, self.store.transaction() as db:
            row = db.execute('SELECT stopped FROM trend_capture WHERE id = ? AND control_id = ?', (identifier, control_id)).fetchone()
            if not row or row[0] is None:
                raise ValueError('Only a stopped capture for this trend can be deleted')
            db.execute('DELETE FROM trend_frame WHERE capture_id = ?', (identifier,))
            db.execute('DELETE FROM trend_capture WHERE id = ?', (identifier,))
            self.errors.clear()

    def _capture(self, identifier):
        row = self.store._db.execute('SELECT series, stopped FROM trend_capture WHERE id = ?', (identifier,)).fetchone()
        if not row:
            raise HTTPException(404, 'Saved trend capture not found')
        return json.loads(row[0]), row[1]

    def history(self, identifier, seconds, end):
        limit = 2000
        with self.store._lock:
            series, stopped = self._capture(identifier)
            if end is None:
                if stopped is None:
                    end = time.time()
                else:
                    latest = self.store._db.execute('SELECT MAX(epoch) FROM trend_frame WHERE capture_id = ?',
                                                     (identifier,)).fetchone()[0]
                    end = latest if latest is not None else stopped
            start = end - seconds
            rows = self.store._db.execute('''SELECT epoch, samples FROM trend_frame
                WHERE capture_id = ? AND epoch BETWEEN ? AND ?
                ORDER BY epoch DESC, sequence DESC LIMIT ?''', (identifier, start, end, limit + 1)).fetchall()
        samples = [{'epoch': epoch, 'tag': item['tag'], 'value': value, 'quality': quality, 'source_timestamp': source}
                   for epoch, payload in reversed(rows[:limit])
                   for item, (value, quality, source) in zip(series, json.loads(payload), strict=True)]
        return {'samples': samples, 'truncated': len(rows) > limit, 'start': start, 'end': end}

    def csv(self, identifier):
        with self.store._lock:
            series, _ = self._capture(identifier)
            rows = self.store._db.execute('SELECT epoch, samples FROM trend_frame WHERE capture_id = ? ORDER BY sequence',
                                          (identifier,)).fetchall()

        def chunks():
            output = StringIO()
            writer = csv.writer(output)
            writer.writerow(['timestamp_utc', 'tag', 'value', 'quality', 'source_timestamp'])
            for index, (epoch, payload) in enumerate(rows, 1):
                recorded = stamp(epoch)
                for item, (value, quality, source) in zip(series, json.loads(payload), strict=True):
                    writer.writerow([recorded, item['tag'], json.dumps(value) if value is not None else '', quality, source])
                if index % 256 == 0:
                    yield output.getvalue()
                    output.seek(0)
                    output.truncate(0)
            yield output.getvalue()

        return StreamingResponse(chunks(), media_type='text/csv',
                                 headers={'Content-Disposition': f'attachment; filename="trend-capture-{identifier}.csv"'})


class CaptureCommand(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    action: Literal['start', 'stop', 'delete']
    capture_id: int = Field(default=0, ge=0, le=9223372036854775807)


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
