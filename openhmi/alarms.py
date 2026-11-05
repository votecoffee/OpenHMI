"""Project-wide alarm sampling, occurrence lifecycle and persistent history."""

from datetime import datetime, timezone
import json
import math
from threading import RLock

from .projects import Project, ProjectStore


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def trigger_condition(definition, value):
    if definition.trigger_type == "value":
        if type(value) not in (bool, int, float) or (type(value) is float and not math.isfinite(value)):
            return None
        return value == definition.trigger_value
    if type(value) is not int or not -2147483648 <= value <= 4294967295:
        return None
    word = value & 0xFFFFFFFF
    if definition.trigger_type == "bit":
        return bool(word & (1 << (definition.trigger_value - 1)))
    return bool(word) and (word & -word).bit_length() == definition.trigger_value


class AlarmMonitor:
    def __init__(self, store: ProjectStore, sample_values):
        self.store, self.sample_values = store, sample_values
        self.lock = RLock()
        self.last_sample_at = None
        self.error = None
        with store.transaction() as db:
            db.execute("CREATE TABLE IF NOT EXISTS alarm_state (alarm_id TEXT PRIMARY KEY, signature TEXT, occurrence_id INTEGER, condition INTEGER, quality TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS alarm_occurrence (id INTEGER PRIMARY KEY AUTOINCREMENT, alarm_id TEXT, definition TEXT, raised_at TEXT, returned_at TEXT, acknowledged_at TEXT, retired_at TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS alarm_event (id INTEGER PRIMARY KEY AUTOINCREMENT, occurrence_id INTEGER, alarm_id TEXT, event TEXT, timestamp TEXT)")
            db.execute('CREATE TABLE IF NOT EXISTS alarm_acknowledgement(occurrence_id INTEGER PRIMARY KEY,timestamp TEXT NOT NULL,actor TEXT NOT NULL,provider TEXT NOT NULL,operation_id TEXT,comment TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS alarm_event_context(event_id INTEGER PRIMARY KEY,actor TEXT NOT NULL,provider TEXT NOT NULL,operation_id TEXT,comment TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS alarm_note(id INTEGER PRIMARY KEY AUTOINCREMENT,occurrence_id INTEGER NOT NULL,timestamp TEXT NOT NULL,actor TEXT NOT NULL,provider TEXT NOT NULL,operation_id TEXT,comment TEXT NOT NULL)')
            db.execute('CREATE INDEX IF NOT EXISTS alarm_note_occurrence ON alarm_note(occurrence_id,id)')
            db.execute('CREATE INDEX IF NOT EXISTS alarm_event_occurrence ON alarm_event(occurrence_id,id)')
        from .alarm_shelves import AlarmShelves
        self.shelves = AlarmShelves(self)

    @staticmethod
    def _event(db, alarm_id, occurrence, event, now, identity=('system', 'monitor'), operation_id=None, comment=''):
        identifier = db.execute("INSERT INTO alarm_event (occurrence_id, alarm_id, event, timestamp) VALUES (?, ?, ?, ?)", (occurrence, alarm_id, event, now)).lastrowid
        db.execute('INSERT INTO alarm_event_context VALUES(?,?,?,?,?)', (identifier, *identity, operation_id, comment))
        return identifier

    def sample(self):
        with self.lock:
            # Copy driver data before acquiring the database lock (fixed lock order).
            values = self.sample_values()
            with self.store.transaction() as db:
                project = Project.model_validate(self.store._read()["active"])
                definitions = {definition.id: definition for definition in project.alarms if definition.enabled}
                now = utc_now()
                self.shelves.reconcile(db, definitions, now)
                states = {row[0]: row for row in db.execute("SELECT * FROM alarm_state")}
                for alarm_id, state in states.items():
                    definition = definitions.get(alarm_id)
                    signature = self._signature(definition) if definition else None
                    if state[1] != signature:
                        if state[2]:
                            db.execute("UPDATE alarm_occurrence SET retired_at=COALESCE(retired_at, ?) WHERE id=?", (now, state[2]))
                            self._event(db, alarm_id, state[2], "configuration_changed", now)
                        db.execute("DELETE FROM alarm_state WHERE alarm_id=?", (alarm_id,))
                for alarm_id, definition in definitions.items():
                    state = db.execute("SELECT * FROM alarm_state WHERE alarm_id=?", (alarm_id,)).fetchone()
                    previous = state[3] if state else None
                    occurrence = state[2] if state else None
                    condition = trigger_condition(definition, values.get(definition.tag))
                    quality = "good" if condition is not None else "bad"
                    if condition is None:
                        if not state or state[4] != "bad":
                            self._event(db, alarm_id, occurrence, "quality_bad", now)
                    else:
                        if state and state[4] == "bad":
                            self._event(db, alarm_id, occurrence, "quality_recovered", now)
                        if condition and previous != 1:
                            payload = definition.model_dump()
                            payload["messages"] = {language.code: language.translations.get(f"alarm.{alarm_id}.message") or definition.message for language in project.languages}
                            payload['causes'] = {language.code: language.translations.get(f'alarm.{alarm_id}.cause') or definition.cause for language in project.languages}
                            payload['responses'] = {language.code: language.translations.get(f'alarm.{alarm_id}.response') or definition.response for language in project.languages}
                            result = db.execute("INSERT INTO alarm_occurrence (alarm_id,definition,raised_at,acknowledged_at) VALUES (?,?,?,?)",
                                                (alarm_id, json.dumps(payload), now, None if definition.ack_required else now))
                            occurrence = result.lastrowid
                            self._event(db, alarm_id, occurrence, "active", now)
                            if not definition.ack_required:
                                db.execute('INSERT INTO alarm_acknowledgement VALUES(?,?,?,?,?,?)', (occurrence, now, 'system', 'automatic', None, 'Acknowledgement not required'))
                        elif not condition and previous == 1 and occurrence:
                            db.execute("UPDATE alarm_occurrence SET returned_at=? WHERE id=?", (now, occurrence))
                            self._event(db, alarm_id, occurrence, "returned", now)
                        previous = int(condition)
                    db.execute("INSERT OR REPLACE INTO alarm_state VALUES (?,?,?,?,?)", (alarm_id, self._signature(definition), occurrence, previous, quality))
                limit = project.alarm_history_limit
                db.execute("DELETE FROM alarm_event WHERE id NOT IN (SELECT id FROM alarm_event ORDER BY id DESC LIMIT ?)", (limit,))
                db.execute("DELETE FROM alarm_occurrence WHERE (returned_at IS NOT NULL OR retired_at IS NOT NULL) AND acknowledged_at IS NOT NULL AND id NOT IN (SELECT id FROM alarm_occurrence ORDER BY id DESC LIMIT ?)", (limit,))
                db.execute('DELETE FROM alarm_acknowledgement WHERE occurrence_id NOT IN (SELECT id FROM alarm_occurrence)')
                db.execute('DELETE FROM alarm_note WHERE occurrence_id NOT IN (SELECT id FROM alarm_occurrence)')
                db.execute('DELETE FROM alarm_event_context WHERE event_id NOT IN (SELECT id FROM alarm_event)')
            self.last_sample_at, self.error = now, None

    @staticmethod
    def _signature(definition):
        if definition is None:
            return None
        return json.dumps([definition.tag, definition.trigger_type, definition.trigger_value, definition.ack_required])

    def acknowledge(self, occurrence_id=None, *, occurrence_ids=None, identity=('unknown', 'legacy'), operation_id=None, comment=''):
        with self.lock, self.store.transaction() as db:
            if occurrence_id is not None and not db.execute("SELECT 1 FROM alarm_occurrence WHERE id=?", (occurrence_id,)).fetchone():
                raise KeyError(occurrence_id)
            query = "SELECT id,alarm_id FROM alarm_occurrence WHERE acknowledged_at IS NULL"
            identifiers = occurrence_ids if occurrence_ids is not None else [occurrence_id] if occurrence_id is not None else None
            if identifiers is not None:
                placeholders = ','.join('?' for _ in identifiers)
                if not identifiers or len(set(identifiers)) != len(identifiers) or len(identifiers) > 200:
                    raise ValueError('Select 1–200 unique alarm occurrences')
                if db.execute(f'SELECT COUNT(*) FROM alarm_occurrence WHERE id IN ({placeholders})', identifiers).fetchone()[0] != len(identifiers):
                    raise KeyError('Alarm occurrence not found')
                query += f' AND id IN ({placeholders})'
            rows = db.execute(query, identifiers or ()).fetchall()
            now = utc_now()
            for identifier, alarm_id in rows:
                db.execute("UPDATE alarm_occurrence SET acknowledged_at=? WHERE id=?", (now, identifier))
                db.execute('INSERT INTO alarm_acknowledgement VALUES(?,?,?,?,?,?)', (identifier, now, *identity, operation_id, comment))
                self._event(db, alarm_id, identifier, "acknowledged", now, identity, operation_id, comment)
            return {"acknowledged": [row[0] for row in rows]}

    def note(self, identifier, comment, identity, operation_id):
        with self.lock, self.store.transaction() as db:
            row = db.execute('SELECT alarm_id FROM alarm_occurrence WHERE id=?', (identifier,)).fetchone()
            if not row:
                raise KeyError('Alarm occurrence not found')
            now = utc_now()
            identifier_note = db.execute('INSERT INTO alarm_note(occurrence_id,timestamp,actor,provider,operation_id,comment) VALUES(?,?,?,?,?,?)',
                                         (identifier, now, *identity, operation_id, comment)).lastrowid
            self._event(db, row[0], identifier, 'operator_note', now, identity, operation_id, comment)
            return {'note_id': identifier_note, 'occurrence_id': identifier, 'timestamp': now, 'actor': identity[0], 'provider': identity[1], 'comment': comment}

    def snapshot(self):
        with self.lock, self.store._lock:
            db = self.store._db
            states = {row[0]: {"quality": row[4], "condition": row[3]} for row in db.execute("SELECT * FROM alarm_state")}
            occurrences = []
            for identifier, alarm_id, definition, raised, returned, acknowledged, retired in db.execute("SELECT * FROM alarm_occurrence ORDER BY id DESC"):
                payload = json.loads(definition)
                occurrences.append({**payload, "occurrence_id": identifier, "alarm_id": alarm_id, "raised_at": raised,
                                    "returned_at": returned, "acknowledged_at": acknowledged, "retired_at": retired,
                                    "active": returned is None and retired is None, "quality": "retired" if retired else states.get(alarm_id, {}).get("quality", "retired")})
            outstanding = [row for row in occurrences if row["active"] or row["acknowledged_at"] is None]
            shelves = self.shelves.active()
            for row in occurrences:
                row['shelf'] = self.shelves.for_occurrence(row, shelves)
            annunciated = [row for row in outstanding if not row['shelf']]
            history = [{"id": row[0], "occurrence_id": row[1], "alarm_id": row[2], "event": row[3], "timestamp": row[4]} for row in db.execute("SELECT * FROM alarm_event ORDER BY id DESC")]
            return {"last_sample_at": self.last_sample_at, "error": self.error, "states": states,
                    "active_count": sum(row["active"] for row in outstanding),
                    "unacknowledged_count": sum(row["acknowledged_at"] is None for row in outstanding),
                    'shelved_count': len(shelves), 'shelved_occurrence_count': len(outstanding) - len(annunciated),
                    'annunciated_outstanding': annunciated,
                    'annunciated_active_count': sum(row['active'] for row in annunciated),
                    'annunciated_unacknowledged_count': sum(row['acknowledged_at'] is None for row in annunciated),
                    "outstanding": outstanding, "occurrences": occurrences, "history": history}
