"""Durable request/accepted/completed PLC contracts. Observation never replays writes."""

from datetime import datetime, timedelta, timezone
import hashlib
import json
from threading import RLock

from fastapi import HTTPException
from .alarms import utc_now
from .logix import member_value


def contract(project, definition):
    root = next((tag for tag in project['tags'] if tag['name'] == definition['root_tag']), None)
    if not root or root['type'] != 'struct' or not root['writable']:
        raise ValueError('Command requires a writable UDT root')
    for field in ('request_member', 'accepted_member', 'completed_member', 'result_member'):
        if root['members'].get(definition[field]) != 'integer':
            raise ValueError('Command sequence/result members require declared integers')
    if definition['permit_member'] and root['members'].get(definition['permit_member']) != 'boolean':
        raise ValueError('Command permit requires a declared Boolean member')
    connection = next((item for item in project['connections'] if item['id'] == root['connection']), None)
    # A physical channel keeps sequence ownership even if a logical name is changed.
    channel = json.dumps([connection['path'].casefold(), root['address'].casefold()] if connection else ['local', root['name']], sort_keys=True)
    signature = hashlib.sha256(json.dumps([definition, root, connection], sort_keys=True).encode()).hexdigest()
    return root, channel, signature


def validate_commands(project, groups):
    channels = set()
    for definition in project.get('commands', []):
        root, channel, _ = contract(project, definition)
        if channel in channels:
            raise ValueError('Only one command may own a physical UDT channel')
        channels.add(channel)
        if root['connection']:
            route = next(item['path'].casefold() for item in project['connections'] if item['id'] == root['connection'])
            for tag in project['tags']:
                if tag['name'] == root['name'] or not tag['connection']:
                    continue
                other_route = next(item['path'].casefold() for item in project['connections'] if item['id'] == tag['connection'])
                first, second = root['address'].casefold(), tag['address'].casefold()
                if route == other_route and (first == second or any(first.startswith(second + separator) or second.startswith(first + separator) for separator in ('.', '['))):
                    raise ValueError('Command UDT cannot overlap another PLC tag alias')
        if not set(definition['security_groups']) <= groups:
            raise ValueError('Command references an unknown HMI group')


class CommandService:
    def __init__(self, store, driver):
        self.store, self.driver = store, driver
        self.lock = RLock()
        with store.transaction() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS command_transaction(
                  id INTEGER PRIMARY KEY AUTOINCREMENT,operation_id TEXT UNIQUE NOT NULL,
                  command_id TEXT NOT NULL,channel TEXT NOT NULL,signature TEXT NOT NULL,
                  definition_json TEXT NOT NULL,sequence INTEGER NOT NULL,state TEXT NOT NULL,
                  created_at TEXT NOT NULL,updated_at TEXT NOT NULL,deadline TEXT NOT NULL,
                  result_code INTEGER,error TEXT);
                CREATE INDEX IF NOT EXISTS command_channel ON command_transaction(channel,state);
                CREATE TABLE IF NOT EXISTS command_event(
                  id INTEGER PRIMARY KEY AUTOINCREMENT,transaction_id INTEGER NOT NULL,
                  timestamp TEXT NOT NULL,state TEXT NOT NULL,detail TEXT NOT NULL);
            ''')
            for identifier, state in db.execute("SELECT id,state FROM command_transaction WHERE state IN ('prepared','requested','accepted')").fetchall():
                self._update(db, identifier, 'interrupted' if state == 'prepared' else 'uncertain',
                             'Server restarted; request was not replayed')

    @staticmethod
    def _update(db, identifier, state, detail='', result=None):
        stamp = utc_now()
        db.execute('UPDATE command_transaction SET state=?,updated_at=?,result_code=?,error=? WHERE id=?',
                   (state, stamp, result, detail or None, identifier))
        db.execute('INSERT INTO command_event(transaction_id,timestamp,state,detail) VALUES(?,?,?,?)',
                   (identifier, stamp, state, detail))

    def get(self, identifier):
        with self.store._lock:
            cursor = self.store._db.execute('SELECT * FROM command_transaction WHERE id=?', (identifier,))
            row = cursor.fetchone()
            if row is None:
                raise HTTPException(404, 'Command transaction not found')
            item = dict(zip([column[0] for column in cursor.description], row))
            for key in ('definition_json', 'signature', 'channel'):
                item.pop(key)
            item['events'] = [dict(zip(('timestamp', 'state', 'detail'), row)) for row in self.store._db.execute(
                'SELECT timestamp,state,detail FROM command_event WHERE transaction_id=? ORDER BY id', (identifier,))]
            return item

    def recent(self, limit=100, before_id=None, command_id=''):
        with self.store._lock:
            ids = [row[0] for row in self.store._db.execute(
                'SELECT id FROM command_transaction WHERE id < ? AND (? = \'\' OR command_id=?) ORDER BY id DESC LIMIT ?',
                (before_id or 9223372036854775807, command_id, command_id, limit + 1))]
        return {'items': [self.get(identifier) for identifier in ids[:limit]], 'has_more': len(ids) > limit,
                'next_before_id': ids[limit - 1] if len(ids) > limit else None}

    def validate_apply(self, project):
        definitions = {item['id']: item for item in project.get('commands', [])}
        with self.store._lock:
            rows = self.store._db.execute("SELECT command_id,signature FROM command_transaction WHERE state IN ('prepared','requested','accepted','uncertain')").fetchall()
        for name, signature in rows:
            definition = definitions.get(name)
            if not definition or contract(project, definition)[2] != signature:
                raise HTTPException(409, 'Resolve the outstanding command before changing its contract, UDT or connection')

    def observation(self, definition, after=None):
        sample = self.driver.sample_snapshot().get(definition['root_tag'], {})
        if sample.get('quality') != 'good':
            raise ValueError('Command UDT has no fresh good-quality sample')
        if after and sample.get('timestamp', '') <= after:
            raise ValueError('Waiting for a sample acquired after dispatch')
        value = sample['value']
        values = [member_value(value, definition[field]) for field in
                  ('request_member', 'accepted_member', 'completed_member', 'result_member')]
        if any(type(item) is not int or not -2147483648 <= item <= 2147483647 for item in values):
            raise ValueError('Command protocol requires signed 32-bit integers')
        if any(item < 0 for item in values[:3]):
            raise ValueError('Command sequences must be nonnegative')
        permit = not definition['permit_member'] or member_value(value, definition['permit_member']) is True
        return values, permit

    def submit(self, definition, ticket):
        with self.lock, self.driver.io_lock:
            project = self.driver.project
            root, channel, signature = contract(project, definition)
            try:
                values, permit = self.observation(definition)
            except (ValueError, KeyError, TypeError, IndexError) as error:
                raise HTTPException(409, str(error)) from error
            if not permit:
                raise HTTPException(423, 'PLC command permit is false')
            if not values[0] == values[1] == values[2]:
                raise HTTPException(409, 'PLC channel is busy or requires PLC-owned recovery')
            with self.store.transaction() as db:
                if db.execute("SELECT 1 FROM command_transaction WHERE channel=? AND state IN ('prepared','requested','accepted','uncertain')", (channel,)).fetchone():
                    raise HTTPException(409, 'Command channel has an unresolved transaction; do not retry')
                last = db.execute('SELECT MAX(sequence) FROM command_transaction WHERE channel=?', (channel,)).fetchone()[0] or 0
                sequence = max(last, *values[:3]) + 1
                if sequence > 2147483647:
                    raise HTTPException(409, 'Sequence space exhausted; engineer a new PLC channel, never wrap or replay')
                stamp = utc_now()
                deadline = (datetime.now(timezone.utc) + timedelta(seconds=definition['timeout_seconds'])).isoformat()
                cursor = db.execute('''INSERT INTO command_transaction(operation_id,command_id,channel,signature,definition_json,
                    sequence,state,created_at,updated_at,deadline) VALUES(?,?,?,?,?,?,'prepared',?,?,?)''',
                    (ticket.id, definition['id'], channel, signature, json.dumps(definition), sequence, stamp, stamp, deadline))
                identifier = cursor.lastrowid
                self._update(db, identifier, 'prepared')
            ticket.confirm(transaction_id=identifier, sequence=sequence)
            try:
                ticket.dispatch(command=definition['id'], sequence=sequence, transaction_id=identifier)
            except Exception:
                with self.store.transaction() as db:
                    self._update(db, identifier, 'interrupted', 'Activity dispatch unavailable; request was not written')
                raise
            with self.store.transaction() as db:
                self._update(db, identifier, 'requested', 'Dispatch started; awaiting PLC acceptance')
            try:
                self.driver.write_command_request(definition['id'], sequence)
            except Exception as error:
                with self.store.transaction() as db:
                    self._update(db, identifier, 'uncertain', 'Request write/readback failed; verify PLC outcome before retrying')
                raise HTTPException(409, f'Command transaction {identifier} is uncertain; request was not retried') from error
            ticket.confirm(verification='request_tag_readback', equipment_complete=False)
            return {'ok': True, 'transaction': self.get(identifier)}

    def poll(self, now=None):
        now = now or utc_now()
        with self.lock:
            with self.store._lock:
                rows = self.store._db.execute("SELECT id,definition_json,sequence,state,deadline,signature,created_at FROM command_transaction WHERE state IN ('requested','accepted','uncertain')").fetchall()
            for identifier, encoded, sequence, state, deadline, signature, created in rows:
                definition = json.loads(encoded)
                new_state, detail, result = state, '', None
                try:
                    if contract(self.driver.project, definition)[2] != signature:
                        raise ValueError('Active contract differs from the dispatched contract')
                    values, _ = self.observation(definition, created)
                    request, accepted, completed, code = values
                    if request == accepted == completed == sequence:
                        new_state, result = ('completed' if code == 0 else 'failed'), code
                        detail = 'PLC published matching accepted/completed sequence and result'
                    elif accepted == sequence and request == sequence and state == 'requested':
                        new_state, detail = 'accepted', 'PLC accepted this sequence; equipment completion is still pending'
                    elif request != sequence or completed == sequence:
                        new_state, detail = 'uncertain', 'PLC protocol changed or completion was not associated with this accepted request'
                except (ValueError, KeyError, TypeError, IndexError):
                    pass  # No good observation does not establish success or failure.
                if new_state not in ('completed', 'failed') and now >= deadline:
                    new_state, detail = 'uncertain', 'Deadline elapsed; PLC outcome unknown. No cancellation, reset or replay was sent'
                if new_state != state:
                    with self.store.transaction() as db:
                        self._update(db, identifier, new_state, detail, result)


def add_command_routes(app, service, security):
    from fastapi import Path, Query, Request

    @app.get('/api/commands')
    def recent(request: Request, limit: int = Query(default=100, ge=1, le=200),
               before_id: int | None = Query(default=None, ge=1, le=9223372036854775807), command_id: str = Query(default='', max_length=60)):
        security.require(request, 'runtime.operate')
        return service.recent(limit, before_id, command_id)

    @app.get('/api/commands/{identifier}')
    def transaction(request: Request, identifier: int = Path(ge=1, le=9223372036854775807)):
        security.require(request, 'runtime.operate')
        return service.get(identifier)
