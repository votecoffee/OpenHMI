"""Bounded operator alarm queries; source sampling and PLC writes stay outside these reads."""

from datetime import datetime, timezone
import json

STATES = {'outstanding', 'active', 'returned', 'retired', 'unacknowledged', 'acknowledged', 'all'}
EVENTS = {'active', 'returned', 'acknowledged', 'quality_bad', 'quality_recovered', 'configuration_changed', 'operator_note'}
JOIN = ''' FROM alarm_occurrence o LEFT JOIN alarm_state s ON s.alarm_id=o.alarm_id
           LEFT JOIN alarm_acknowledgement a ON a.occurrence_id=o.id'''
SELECT = '''SELECT o.id,o.alarm_id,o.definition,o.raised_at,o.returned_at,o.acknowledged_at,o.retired_at,
            s.quality,a.actor,a.provider,a.operation_id,a.comment'''


def occurrence(row):
    identifier, alarm_id, encoded, raised, returned, acknowledged, retired, quality, actor, provider, operation_id, comment = row
    return {**json.loads(encoded), 'occurrence_id': identifier, 'alarm_id': alarm_id, 'raised_at': raised,
            'returned_at': returned, 'acknowledged_at': acknowledged, 'retired_at': retired,
            'active': returned is None and retired is None, 'quality': 'retired' if retired else quality or 'unavailable',
            'acknowledged_by': actor, 'acknowledged_provider': provider, 'acknowledgement_operation_id': operation_id,
            'acknowledgement_comment': comment}


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Alarm timestamps require a UTC offset')
    return parsed.astimezone(timezone.utc).isoformat(timespec='milliseconds')


def filters(priority=0, search='', state='all', start=None, end=None, event='', clock='o.raised_at'):
    if state not in STATES or event and event not in EVENTS:
        raise ValueError('Unknown alarm state or event filter')
    clauses, arguments = [], []
    if priority:
        clauses.append("json_extract(o.definition,'$.priority')=?"); arguments.append(priority)
    if search:
        term = '%' + search.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        alarm_id = 'e.alarm_id' if clock == 'e.timestamp' else 'o.alarm_id'
        clauses.append(f"({alarm_id} LIKE ? ESCAPE '\\' OR json_extract(o.definition,'$.message') LIKE ? ESCAPE '\\' OR json_extract(o.definition,'$.tag') LIKE ? ESCAPE '\\' OR EXISTS(SELECT 1 FROM json_each(o.definition,'$.messages') WHERE value LIKE ? ESCAPE '\\'))")
        arguments.extend([term] * 4)
    conditions = {'active': 'o.returned_at IS NULL AND o.retired_at IS NULL', 'returned': 'o.returned_at IS NOT NULL',
                  'retired': 'o.retired_at IS NOT NULL', 'unacknowledged': 'o.acknowledged_at IS NULL',
                  'acknowledged': 'o.acknowledged_at IS NOT NULL',
                  'outstanding': '(o.returned_at IS NULL AND o.retired_at IS NULL) OR o.acknowledged_at IS NULL'}
    if state != 'all':
        clauses.append('(o.id IS NOT NULL AND (' + conditions[state] + '))')
    start, end = timestamp(start) if start else None, timestamp(end) if end else None
    if start and end and start > end:
        raise ValueError('Alarm start must not be after end')
    for operator, value in [('>=', start), ('<=', end)]:
        if value:
            clauses.append(f'{clock} {operator} ?'); arguments.append(value)
    if event:
        clauses.append('e.event=?'); arguments.append(event)
    return clauses, arguments


class AlarmQueries:
    def __init__(self, monitor):
        self.monitor, self.store = monitor, monitor.store

    def occurrences(self, limit=50, before_id=None, priority=0, search='', state='outstanding', start=None, end=None):
        clauses, arguments = filters(priority, search, state, start, end)
        if before_id is not None:
            clauses.append('o.id < ?'); arguments.append(before_id)
        where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
        with self.store._lock:
            rows = self.store._db.execute(SELECT + JOIN + where + ' ORDER BY o.id DESC LIMIT ?', (*arguments, limit + 1)).fetchall()
        return {'items': [occurrence(row) for row in rows[:limit]], 'has_more': len(rows) > limit,
                'next_before_id': rows[limit - 1][0] if len(rows) > limit else None}

    def notes(self, identifier, limit=50, before_id=None):
        with self.store._lock:
            db = self.store._db
            if not db.execute('SELECT 1 FROM alarm_occurrence WHERE id=?', (identifier,)).fetchone():
                raise KeyError('Alarm occurrence not found')
            rows = db.execute('SELECT id,timestamp,actor,provider,operation_id,comment FROM alarm_note WHERE occurrence_id=? AND id < ? ORDER BY id DESC LIMIT ?',
                              (identifier, before_id or 9223372036854775807, limit + 1)).fetchall()
        return {'items': [dict(zip(('id', 'timestamp', 'actor', 'provider', 'operation_id', 'comment'), row)) for row in rows[:limit]],
                'has_more': len(rows) > limit, 'next_before_id': rows[limit - 1][0] if len(rows) > limit else None}

    def detail(self, identifier):
        with self.store._lock:
            row = self.store._db.execute(SELECT + JOIN + ' WHERE o.id=?', (identifier,)).fetchone()
            if not row:
                raise KeyError('Alarm occurrence not found')
            item = occurrence(row)
            notes = self.notes(identifier)
        return {'occurrence': item, 'notes': notes}

    def history(self, limit=50, before_id=None, priority=0, search='', state='all', start=None, end=None, event='', occurrence_id=None):
        clauses, arguments = filters(priority, search, state, start, end, event, 'e.timestamp')
        if before_id is not None:
            clauses.append('e.id < ?'); arguments.append(before_id)
        if occurrence_id is not None:
            clauses.append('e.occurrence_id=?'); arguments.append(occurrence_id)
        where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
        with self.store._lock:
            rows = self.store._db.execute('''SELECT e.id,e.occurrence_id,e.alarm_id,e.event,e.timestamp,o.definition,
                c.actor,c.provider,c.operation_id,c.comment FROM alarm_event e
                LEFT JOIN alarm_occurrence o ON o.id=e.occurrence_id LEFT JOIN alarm_event_context c ON c.event_id=e.id'''
                + where + ' ORDER BY e.id DESC LIMIT ?', (*arguments, limit + 1)).fetchall()
        items = []
        for row in rows[:limit]:
            item = dict(zip(('id', 'occurrence_id', 'alarm_id', 'event', 'timestamp', 'definition', 'actor', 'provider', 'operation_id', 'comment'), row))
            item['definition'] = json.loads(item['definition']) if item['definition'] else None
            items.append(item)
        return {'items': items, 'has_more': len(rows) > limit, 'next_before_id': rows[limit - 1][0] if len(rows) > limit else None}
