"""Timed, attributed alarm-definition shelving; monitoring remains independent."""
from datetime import datetime, timedelta
import json

from .alarms import utc_now
from .projects import Project


class ShelfConflict(ValueError):
    pass


class AlarmShelves:
    @staticmethod
    def signature(definition):
        return json.dumps([definition.tag, definition.trigger_type, definition.trigger_value, definition.ack_required, definition.priority])

    def __init__(self, monitor):
        self.monitor, self.store = monitor, monitor.store
        with self.store.transaction() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS alarm_shelf(
                alarm_id TEXT PRIMARY KEY,signature TEXT NOT NULL,occurrence_id INTEGER NOT NULL,
                definition TEXT NOT NULL,started_at TEXT NOT NULL,expires_at TEXT NOT NULL,
                actor TEXT NOT NULL,provider TEXT NOT NULL,operation_id TEXT NOT NULL,reason TEXT NOT NULL)''')

    def active(self, now=None):
        now = now or utc_now()
        with self.store._lock:
            project = Project.model_validate(self.store._read()['active'])
            definitions = {item.id: item for item in project.alarms if item.enabled}
            result = {}
            for row in self.store._db.execute('SELECT * FROM alarm_shelf WHERE expires_at>? ORDER BY alarm_id', (now,)):
                item = dict(zip(('alarm_id', 'signature', 'occurrence_id', 'definition', 'started_at', 'expires_at', 'actor', 'provider', 'operation_id', 'reason'), row))
                definition = definitions.get(item['alarm_id'])
                if definition and self.signature(definition) == item['signature']:
                    item['definition'] = json.loads(item['definition'])
                    result[item['alarm_id']] = item
            return result

    @staticmethod
    def for_occurrence(item, active):
        shelf = active.get(item['alarm_id'])
        signature = json.dumps([item['tag'], item['trigger_type'], item['trigger_value'], item['ack_required'], item['priority']])
        return shelf if shelf and not item['retired_at'] and shelf['signature'] == signature else None

    def check(self, identifier):
        with self.store._lock:
            row = self.store._db.execute('SELECT alarm_id,definition,returned_at,acknowledged_at,retired_at FROM alarm_occurrence WHERE id=?', (identifier,)).fetchone()
            if not row:
                raise KeyError('Alarm occurrence not found')
            definition = next((item for item in Project.model_validate(self.store._read()['active']).alarms if item.id == row[0] and item.enabled), None)
            captured = json.loads(row[1])
            signature = json.dumps([captured['tag'], captured['trigger_type'], captured['trigger_value'], captured['ack_required'], captured['priority']])
            if not definition or self.signature(definition) != signature or row[4] or row[2] and row[3]:
                raise ShelfConflict('Only outstanding occurrences of an enabled, unchanged alarm may be shelved')
            if row[0] in self.active():
                raise ShelfConflict('Alarm is already shelved; restore it before starting another interval')
            return row[0], signature, row[1]

    def begin(self, identifier, seconds, reason, identity, operation_id):
        with self.monitor.lock, self.store.transaction() as db:
            alarm_id, signature, definition = self.check(identifier)
            now = utc_now()
            project = Project.model_validate(self.store._read()['active'])
            self.reconcile(db, {item.id: item for item in project.alarms if item.enabled}, now)
            expires = (datetime.fromisoformat(now) + timedelta(seconds=seconds)).isoformat(timespec='milliseconds')
            db.execute('INSERT INTO alarm_shelf VALUES(?,?,?,?,?,?,?,?,?,?)', (alarm_id, signature, identifier, definition, now, expires, *identity, operation_id, reason))
            self.monitor._event(db, alarm_id, identifier, 'shelved', now, identity, operation_id, f'{reason}\nExpires: {expires}')
            return {'alarm_id': alarm_id, 'expires_at': expires, 'shelf_operation_id': operation_id}

    def check_restore(self, alarm_id, expected):
        shelf = self.active().get(alarm_id)
        if not shelf:
            raise KeyError('Active alarm shelf not found')
        if shelf['operation_id'] != expected:
            raise ShelfConflict('Shelf changed; review its current interval before restoring')
        return shelf

    def restore(self, alarm_id, expected, reason, identity, operation_id):
        with self.monitor.lock, self.store.transaction() as db:
            shelf = self.check_restore(alarm_id, expected)
            db.execute('DELETE FROM alarm_shelf WHERE alarm_id=?', (alarm_id,))
            self.monitor._event(db, alarm_id, shelf['occurrence_id'], 'shelf_restored', utc_now(), identity, operation_id, reason)
            return {'alarm_id': alarm_id, 'restored': True}

    def reconcile(self, db, definitions, now):
        for alarm_id, signature, identifier, expires in db.execute('SELECT alarm_id,signature,occurrence_id,expires_at FROM alarm_shelf').fetchall():
            definition = definitions.get(alarm_id)
            event = 'shelf_expired' if expires <= now else 'shelf_invalidated' if not definition or self.signature(definition) != signature else None
            if event:
                db.execute('DELETE FROM alarm_shelf WHERE alarm_id=?', (alarm_id,))
                self.monitor._event(db, alarm_id, identifier, event, now, comment=f'Original expiry: {expires}')
