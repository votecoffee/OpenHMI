"""Durable runtime operation journal; recovery never repeats an equipment action."""

from datetime import datetime, timedelta, timezone
import json
import logging
import math
import sqlite3
from threading import RLock
import time
import uuid

from fastapi import HTTPException
from .alarms import utc_now
from .security import COOKIE

STATUSES = {'pending', 'succeeded', 'denied', 'rejected', 'uncertain', 'interrupted'}
RETENTION_DAYS = 365
MAX_RESOLVED_ROWS = 100000


def bounded(value, depth=0):
    if depth > 6:
        return '[depth limited]'
    if isinstance(value, str):
        return value if len(value) <= 1000 else value[:1000] + ' [truncated]'
    if type(value) is float and not math.isfinite(value):
        return '[non-finite number]'
    if isinstance(value, dict):
        return {str(key)[:100]: bounded(item, depth + 1) for key, item in list(value.items())[:100]}
    if isinstance(value, (tuple, list)):
        return [bounded(item, depth + 1) for item in value[:100]]
    return value if value is None or type(value) in (bool, int, float) else str(value)[:1000]


def encoded(value):
    return json.dumps(bounded(value), ensure_ascii=False, allow_nan=False)


class Operation:
    def __init__(self, journal, identifier, context):
        self.journal, self.id = journal, identifier
        self.context = context
        self.dispatched = False
        self.outcome = {}

    def dispatch(self, **context):
        self.context.update(context)
        try:
            self.journal.mark_dispatch(self.id, self.context)
        except sqlite3.Error as error:
            raise HTTPException(503, 'Activity journal unavailable; operation was not dispatched') from error
        self.dispatched = True

    def confirm(self, **outcome):
        self.outcome.update(outcome)


class ActivityJournal:
    def __init__(self, store, security):
        self.store, self.security = store, security
        self.lock = RLock()
        self.pending_finalizations = {}
        self.last_maintenance = 0
        with store.transaction() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS operator_activity(
                  id INTEGER PRIMARY KEY AUTOINCREMENT,operation_id TEXT UNIQUE NOT NULL,
                  started_at TEXT NOT NULL,finished_at TEXT,actor TEXT NOT NULL,provider TEXT NOT NULL,
                  groups_json TEXT NOT NULL,peer TEXT NOT NULL,operation TEXT NOT NULL,entity TEXT NOT NULL,
                  phase TEXT NOT NULL,status TEXT NOT NULL,context TEXT NOT NULL,outcome TEXT,error TEXT);
                CREATE INDEX IF NOT EXISTS operator_activity_time ON operator_activity(started_at);
                CREATE INDEX IF NOT EXISTS operator_activity_status ON operator_activity(status,id);
            ''')
            db.execute("""UPDATE operator_activity SET finished_at=?,
                       status=CASE WHEN phase='dispatch_started' THEN 'uncertain' ELSE 'interrupted' END,
                       error='Application restarted before a final outcome was durably recorded; operation was not replayed'
                       WHERE status='pending'""", (utc_now(),))

    def start(self, request, operation, entity, context):
        principal = self.security.user(request.cookies.get(COOKIE)) or getattr(getattr(request, 'state', None), 'activity_principal', None)
        configured = self.security.configured()
        actor = principal.name if principal else 'anonymous' if configured else 'unsecured-simulation'
        provider = principal.provider if principal else 'none' if configured else 'simulation'
        groups = sorted(principal.groups) if principal else []
        identifier = uuid.uuid4().hex
        with self.store.transaction() as db:
            db.execute("""INSERT INTO operator_activity(operation_id,started_at,actor,provider,groups_json,peer,
                          operation,entity,phase,status,context) VALUES(?,?,?,?,?,?,?,?,'prepared','pending',?)""",
                       (identifier, utc_now(), actor, provider, encoded(groups), request.client.host[:128] if request.client else '',
                        operation[:60], entity[:200], encoded(context)))
        return Operation(self, identifier, context)

    def mark_dispatch(self, identifier, context):
        with self.store.transaction() as db:
            cursor = db.execute("UPDATE operator_activity SET phase='dispatch_started',context=? WHERE operation_id=? AND status='pending'",
                                (encoded(context), identifier))
            if cursor.rowcount != 1:
                raise sqlite3.OperationalError('Activity dispatch marker was not recorded')

    def finish(self, identifier, status, outcome, error=None):
        with self.store.transaction() as db:
            db.execute("UPDATE operator_activity SET finished_at=?,status=?,outcome=?,error=? WHERE operation_id=? AND status='pending'",
                       (utc_now(), status, encoded(outcome), str(error)[:1000] if error else None, identifier))

    def finalize(self, operation, status, error=None):
        operation.outcome.setdefault('observed_at', utc_now())
        try:
            self.finish(operation.id, status, operation.outcome, error)
            return status
        except sqlite3.Error:
            logging.exception('Activity finalization pending for operation %s; action will not be replayed', operation.id)
            with self.lock:
                if len(self.pending_finalizations) < 1000:
                    self.pending_finalizations[operation.id] = (status, bounded(operation.outcome), str(error)[:1000] if error else None)
            return 'pending'

    def run(self, request, operation, entity, context, callback):
        try:
            ticket = self.start(request, operation, entity, bounded(context))
        except sqlite3.Error as error:
            raise HTTPException(503, 'Activity journal unavailable; operation was not dispatched') from error
        request.state.activity_operation = ticket.id
        try:
            result = callback(ticket)
        except HTTPException as error:
            status = 'uncertain' if ticket.dispatched else 'denied' if error.status_code in (401, 403, 423) else 'rejected'
            request.state.activity_status = self.finalize(ticket, status, error.detail)
            if ticket.dispatched:
                raise HTTPException(error.status_code, f'{error.detail}. Outcome may be uncertain; verify before retrying. Operation {ticket.id}') from error
            raise
        except Exception as error:
            logging.exception('Runtime operation %s failed', ticket.id)
            status = 'uncertain' if ticket.dispatched else 'rejected'
            request.state.activity_status = self.finalize(ticket, status, 'Runtime operation failed; see server log')
            raise HTTPException(500, f'Runtime operation failed; verify its outcome before retrying. Operation {ticket.id}') from error
        request.state.activity_status = self.finalize(ticket, 'succeeded')
        return result

    def maintenance(self, force=False):
        now = time.monotonic()
        if not force and now - self.last_maintenance < 60:
            return
        self.last_maintenance = now
        with self.lock:
            pending = dict(self.pending_finalizations)
        for identifier, arguments in pending.items():
            try:
                self.finish(identifier, *arguments)
            except sqlite3.Error:
                break
            else:
                with self.lock:
                    self.pending_finalizations.pop(identifier, None)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).isoformat()
        with self.store.transaction() as db:
            # Unresolved pending/uncertain records are never pruned automatically.
            db.execute("""DELETE FROM operator_activity WHERE status NOT IN ('pending','uncertain') AND
                       (started_at < ? OR id < COALESCE((SELECT id FROM operator_activity
                        WHERE status NOT IN ('pending','uncertain') ORDER BY id DESC LIMIT 1 OFFSET ?),0))""",
                       (cutoff, MAX_RESOLVED_ROWS - 1))

    def query(self, limit=100, before_id=None, actor='', status='', search='', start=None, end=None):
        clauses, arguments = [], []
        if before_id is not None:
            clauses.append('id < ?'); arguments.append(before_id)
        if actor:
            clauses.append('actor=?'); arguments.append(actor)
        if status:
            clauses.append('status=?'); arguments.append(status)
        if search:
            clauses.append('(entity LIKE ? OR context LIKE ? OR operation_id LIKE ?)'); arguments.extend([f'%{search}%'] * 3)
        for operator, stamp in [('>=', start), ('<=', end)]:
            if stamp:
                parsed = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
                if parsed.tzinfo is None:
                    raise ValueError('Activity timestamps require a UTC offset')
                clauses.append(f'started_at {operator} ?'); arguments.append(parsed.astimezone(timezone.utc).isoformat())
        where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
        with self.store._lock:
            cursor = self.store._db.execute('SELECT * FROM operator_activity' + where + ' ORDER BY id DESC LIMIT ?', (*arguments, limit + 1))
            names = [column[0] for column in cursor.description]
            rows = [dict(zip(names, row)) for row in cursor.fetchall()]
        more = len(rows) > limit
        rows = rows[:limit]
        for row in rows:
            row['groups'] = json.loads(row.pop('groups_json'))
            row['context'] = json.loads(row['context'])
            row['outcome'] = json.loads(row['outcome']) if row['outcome'] else None
        with self.lock:
            queued = len(self.pending_finalizations)
        return {'items': rows, 'has_more': more, 'next_before_id': rows[-1]['id'] if rows and more else None,
                'pending_finalizations': queued, 'retention_days': RETENTION_DAYS, 'max_resolved_rows': MAX_RESOLVED_ROWS}
