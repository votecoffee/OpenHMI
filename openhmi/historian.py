"""Bounded SQL tag history: values, sample quality and acquisition timestamps."""

from datetime import datetime, timezone
import json
from threading import RLock
import time

HEARTBEAT_SECONDS = 60


class Historian:
    def __init__(self, store, driver):
        self.store, self.driver = store, driver
        self.lock = RLock()
        self.deadlines, self.previous = {}, {}
        self.settings = {'tags': [], 'retention_days': 30, 'max_rows': 1000000}
        self.last_prune = 0
        with store.transaction() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS tag_history(id INTEGER PRIMARY KEY AUTOINCREMENT,tag TEXT NOT NULL,
                  timestamp REAL NOT NULL,value TEXT,quality TEXT NOT NULL,source_timestamp TEXT);
                CREATE INDEX IF NOT EXISTS tag_history_tag_time ON tag_history(tag,timestamp);
            ''')

    def configure(self, settings):
        with self.lock:
            self.settings = settings
            self.deadlines.clear()
            self.previous.clear()

    def sample(self, now=None, wall=None):
        with self.lock:
            self._sample(now, wall)

    def _sample(self, now, wall):
        now = time.monotonic() if now is None else now
        wall = time.time() if wall is None else wall
        samples = self.driver.sample_snapshot(now)
        inserts = []
        recorded = {}
        for config in self.settings['tags']:
            tag = config['tag']
            if now < self.deadlines.get(tag, 0):
                continue
            self.deadlines[tag] = now + config['sample_ms'] / 1000
            sample = samples.get(tag, {'value': None, 'quality': 'bad', 'timestamp': None})
            value = sample['value'] if sample['quality'] == 'good' else None
            quality = sample['quality']
            previous = self.previous.get(tag)
            if previous and previous[1] == quality and now - previous[2] < HEARTBEAT_SECONDS:
                if quality != 'good':
                    continue
                if config['deadband'] > 0 and type(value) in (float, int) and type(previous[0]) in (float, int):
                    if abs(value - previous[0]) < config['deadband']:
                        continue
                elif config.get('mode') == 'change' and value == previous[0]:
                    continue
            inserts.append((tag, wall, json.dumps(value, allow_nan=False) if value is not None else None, quality, sample.get('timestamp')))
            recorded[tag] = (value, quality, now)
        prune = now - self.last_prune >= 60
        if inserts or prune:
            with self.store.transaction() as db:
                db.executemany('INSERT INTO tag_history(tag,timestamp,value,quality,source_timestamp) VALUES(?,?,?,?,?)', inserts)
                db.execute('DELETE FROM tag_history WHERE id <= (SELECT COALESCE(MAX(id),0)-? FROM tag_history)', (self.settings['max_rows'],))
                if prune:
                    db.execute('DELETE FROM tag_history WHERE timestamp < ?', (wall - self.settings['retention_days'] * 86400,))
            self.previous.update(recorded)
            if prune:
                self.last_prune = now

    def query(self, tags, start, end, limit=2000, trend_context=False):
        result = []
        truncated = False
        context = {}
        with self.lock, self.store._lock:
            change_intervals = {
                item['tag']: item['sample_ms'] / 1000 for item in self.settings['tags']
                if trend_context and item.get('mode') == 'change'
            }
            for tag in tags:
                rows = self.store._db.execute('SELECT timestamp,value,quality,source_timestamp FROM tag_history WHERE tag=? AND timestamp BETWEEN ? AND ? ORDER BY timestamp DESC,id DESC LIMIT ?', (tag, start, end, limit + 1)).fetchall()
                truncated = truncated or len(rows) > limit
                for stamp, value, quality, source in reversed(rows[:limit]):
                    result.append({'tag': tag, 'timestamp': datetime.fromtimestamp(stamp, timezone.utc).isoformat(), 'epoch': stamp,
                                   'value': json.loads(value) if value else None, 'quality': quality, 'source_timestamp': source})
                if tag in change_intervals:
                    interval = change_intervals[tag]
                    # The heartbeat can wait up to one sample interval.
                    hold_seconds = HEARTBEAT_SECONDS + interval
                    previous = None
                    if len(rows) <= limit:
                        row = self.store._db.execute(
                            'SELECT timestamp,value,quality FROM tag_history WHERE tag=? AND timestamp>=? AND timestamp<? ORDER BY timestamp DESC,id DESC LIMIT 1',
                            (tag, start - hold_seconds, start),
                        ).fetchone()
                        if row:
                            stamp, value, quality = row
                            previous = {'epoch': stamp, 'value': json.loads(value) if value else None, 'quality': quality}
                    context[tag] = {'hold_seconds': hold_seconds, 'previous': previous}
        data = {'samples': result, 'truncated': truncated, 'start': start, 'end': end}
        if trend_context:
            data['change_context'] = context
        return data
