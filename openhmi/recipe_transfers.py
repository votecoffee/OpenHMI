"""Recipe staging and verified PLC-owned copy publication, above command handshakes."""

import json
import math
import re
import struct

from fastapi import HTTPException
from .alarms import utc_now
from .commands import contract
from .logix import member_value
from .recipes import canonical, content_hash, RecipeError

META_TYPES = {'RecipeCode': 'string', 'RevisionId': 'integer', 'RevisionNumber': 'integer',
              'ContentHash': 'string', 'TransferHash': 'string', 'RecipeProductionApproved': 'boolean'}


def overlap(first, second):
    first, second = first.casefold(), second.casefold()
    return first == second or any(first.startswith(second + part) or second.startswith(first + part) for part in ('.', '['))


def validate_transfers(project):
    commands = {item['id']: item for item in project.get('commands', [])}
    used = set()
    for profile in project.get('recipe_transfers', []):
        command = commands.get(profile['command_id'])
        if not command or command['id'] in used:
            raise ValueError('Recipe transfers require a dedicated, unique command channel')
        used.add(command['id'])
        root, _, _ = contract(project, command)
        reserved = [command[field] for field in ('request_member', 'accepted_member', 'completed_member', 'result_member', 'permit_member') if command[field]]
        staging, running = profile['staging_prefix'], profile['running_prefix']
        if overlap(staging, running) or any(overlap(prefix, member) for prefix in (staging, running) for member in reserved):
            raise ValueError('Recipe staging, running and handshake members must be separate')
        if any(not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,59}', name) for name in profile['parameters']):
            raise ValueError('Recipe parameter names must match the recipe schema')
        paths = [*META_TYPES, *profile['parameters'].values()]
        if any(overlap(first, second) for i, first in enumerate(paths) for second in paths[i + 1:]):
            raise ValueError('Recipe parameter and metadata members must not overlap')
        for path in paths:
            first, second = root['members'].get(staging + '.' + path), root['members'].get(running + '.' + path)
            if first is None or first != second or (path in META_TYPES and first != META_TYPES[path]):
                raise ValueError('Recipe staging/running members must exist with matching declared types')


def matches(actual, expected):
    if type(expected) is float:
        if type(actual) not in (int, float) or not math.isfinite(actual):
            return False
        # Accept the exact Python value or its IEEE REAL round trip, with no broad absolute tolerance.
        return actual == expected or actual == struct.unpack('!f', struct.pack('!f', expected))[0]
    return type(actual) is type(expected) and actual == expected


class RecipeTransfers:
    def __init__(self, store, application, recipes, commands):
        self.store, self.application, self.recipes, self.commands = store, application, recipes, commands
        with store.transaction() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS recipe_transfer(
                id INTEGER PRIMARY KEY,profile_id TEXT NOT NULL,definition_json TEXT NOT NULL,
                snapshot_json TEXT NOT NULL,envelope_json TEXT NOT NULL,transfer_hash TEXT NOT NULL)''')
            db.execute('CREATE INDEX IF NOT EXISTS recipe_transfer_profile ON recipe_transfer(profile_id,id)')
        commands.completion_verifier = self.verify_completion

    def _read(self, identifier):
        with self.store._lock:
            row = self.store._db.execute('SELECT profile_id,definition_json,snapshot_json,envelope_json,transfer_hash FROM recipe_transfer WHERE id=?', (identifier,)).fetchone()
        if not row:
            return None
        profile, snapshot, envelope = (json.loads(item) for item in row[1:4])
        if content_hash(envelope) != row[4] or content_hash(snapshot['content']) != snapshot['content_hash']:
            raise ValueError('Recipe transfer integrity check failed')
        identity = {'RecipeCode': snapshot['code'], 'RevisionId': snapshot['id'], 'RevisionNumber': snapshot['number'],
                    'ContentHash': snapshot['content_hash'], 'RecipeProductionApproved': snapshot['production_approved']}
        if any(not matches(envelope['values'].get(key), value) for key, value in identity.items()):
            raise ValueError('Recipe transfer metadata integrity check failed')
        return {'id': identifier, 'profile_id': row[0], 'profile': profile, 'snapshot': snapshot,
                'envelope': envelope, 'transfer_hash': row[4]}

    def get(self, identifier):
        record = self._read(identifier)
        if record is None:
            raise HTTPException(404, 'Recipe transfer not found')
        return {**record, 'transaction': self.commands.get(identifier)}

    def recent(self, limit=25, before_id=None, profile_id='', production_approved=None, verified_profile=''):
        state = self.store.snapshot()
        conditions, values = [], []
        if before_id is not None:
            conditions.append('id < ?')
            values.append(before_id)
        if profile_id:
            conditions.append('profile_id = ?')
            values.append(profile_id)
        if production_approved is not None:
            conditions.append("json_extract(snapshot_json, '$.production_approved') = ?")
            values.append(int(production_approved))
        where = ' WHERE ' + ' AND '.join(conditions) if conditions else ''
        with self.store._lock:
            db = self.store._db
            ids = [row[0] for row in db.execute(
                'SELECT id FROM recipe_transfer' + where + ' ORDER BY id DESC LIMIT ?', (*values, limit + 1))]
            unresolved = [row[0] for row in self.store._db.execute("SELECT DISTINCT r.profile_id FROM recipe_transfer r JOIN command_transaction c ON c.id=r.id WHERE c.state IN ('prepared','staging','requested','accepted','uncertain')")]
            verified = db.execute("""SELECT r.id FROM recipe_transfer r JOIN command_transaction c ON c.id=r.id
                                     WHERE r.profile_id=? AND c.state='completed' ORDER BY r.id DESC LIMIT 1""",
                                  (verified_profile,)).fetchone() if verified_profile else None
            items = [self.get(identifier) for identifier in ids[:limit]]
            latest = next((item for item in items if verified and item['id'] == verified[0]), None)
            return {'items': items, 'has_more': len(ids) > limit,
                    'has_history': bool(ids) or bool(db.execute('SELECT 1 FROM recipe_transfer LIMIT 1').fetchone()),
                    'next_before_id': ids[limit - 1] if len(ids) > limit else None,
                    'profiles': state['active'].get('recipe_transfers', []), 'active_revision': state['active_revision'],
                    'unresolved_profiles': unresolved, 'verified': latest or (self.get(verified[0]) if verified else None)}

    @staticmethod
    def expected(record):
        return {**record['envelope']['values'], 'TransferHash': record['transfer_hash']}

    def verify_completion(self, identifier, root_value):
        try:
            record = self._read(identifier)
            if record is None:
                with self.store._lock:
                    row = self.store._db.execute('SELECT command_id FROM command_transaction WHERE id=?', (identifier,)).fetchone()
                if row and any(item['command_id'] == row[0] for item in self.application.driver.project.get('recipe_transfers', [])):
                    return False, 'Recipe transfer record is missing; PLC copy cannot be verified'
                return True, ''  # Ordinary commands have no recipe payload.
            prefix = record['profile']['running_prefix']
            if not all(matches(member_value(root_value, prefix + '.' + path), value) for path, value in self.expected(record).items()):
                return False, 'PLC acknowledged completion, but its running recipe copy does not match; outcome remains uncertain'
            return True, 'PLC completion and running recipe parameters, revision/hash and production BOOL verified'
        except (ValueError, KeyError, TypeError, IndexError, OverflowError):
            return False, 'Running recipe verification unavailable or transfer integrity check failed'

    def submit(self, profile_id, request, user, ticket, authorize):
        driver = self.application.driver
        with self.commands.lock, self.application.lock, driver.io_lock:
            if request.expected_project_revision is not None and request.expected_project_revision != self.store.snapshot()['active_revision']:
                raise HTTPException(409, 'The applied project changed. Review and reselect the PLC transfer target.')
            project = driver.project
            profile = next((item for item in project.get('recipe_transfers', []) if item['id'] == profile_id), None)
            if not profile:
                raise HTTPException(404, 'Recipe transfer profile not found')
            definition = next(item for item in project['commands'] if item['id'] == profile['command_id'])
            authorize(definition)
            with self.store._lock:
                self.recipes._gate(self.store._db, user, 'loading')
                revision = self.recipes._revision(self.store._db, request.revision_id)
            if request.expected_revision_version != revision['version']:
                raise RecipeError('Recipe review state changed; reload before transferring')
            parameters = {item['name']: item for item in revision['content']['parameters']}
            if parameters.keys() != profile['parameters'].keys():
                raise RecipeError('Recipe parameters must match the complete transfer mapping exactly', 422)
            root, _, _ = contract(project, definition)
            values = {'RecipeCode': revision['code'], 'RevisionId': revision['id'], 'RevisionNumber': revision['number'],
                      'ContentHash': revision['content_hash'], 'RecipeProductionApproved': revision['status'] == 'approved'}
            if any(values[key] > 2147483647 for key in ('RevisionId', 'RevisionNumber')):
                raise RecipeError('Recipe identifiers exceed the DINT transfer contract', 422)
            for name, path in profile['parameters'].items():
                parameter = parameters[name]
                kind = root['members'][profile['staging_prefix'] + '.' + path]
                if kind != {'text': 'string'}.get(parameter['type'], parameter['type']):
                    raise RecipeError(f'Incompatible recipe parameter type: {name}', 422)
                value = float(parameter['value']) if kind == 'number' else parameter['value']
                if kind == 'integer' and not -2147483648 <= value <= 2147483647:
                    raise RecipeError(f'Recipe parameter exceeds DINT range: {name}', 422)
                if kind == 'number' and abs(value) > 3.4028234663852886e38:
                    raise RecipeError(f'Recipe parameter exceeds REAL range: {name}', 422)
                if kind == 'string' and len(value) > profile['max_string_length']:
                    raise RecipeError(f'Recipe text exceeds the configured PLC string length: {name}', 422)
                if kind == 'string':
                    try:
                        value.encode('iso-8859-1')  # Pinned pycomm3 FixedSizeString encoding.
                    except UnicodeEncodeError as error:
                        raise RecipeError(f'PLC string parameter requires ISO-8859-1 text with this driver: {name}', 422) from error
                values[path] = value
            snapshot = {**revision, 'production_approved': values['RecipeProductionApproved'],
                        'transferred_by': user.name, 'transfer_reason': request.reason, 'captured_at': utc_now()}

            def reserve(db, identifier, sequence):
                envelope = {'sequence': sequence, 'values': values}
                db.execute('INSERT INTO recipe_transfer VALUES(?,?,?,?,?,?)',
                           (identifier, profile_id, canonical(profile), canonical(snapshot), canonical(envelope), content_hash(envelope)))
                self.recipes._audit(db, user, 'transfer_requested', revision['recipe_id'], revision['id'],
                                   reason=request.reason, transaction_id=identifier, production_approved=snapshot['production_approved'],
                                   content_hash=revision['content_hash'], transfer_hash=content_hash(envelope))

            def prepare(identifier, idle):
                record = self._read(identifier)
                deadline = self.commands.get(identifier)['deadline']
                prefix = profile['staging_prefix']
                for path, value in self.expected(record).items():
                    if utc_now() >= deadline:
                        raise ValueError('Recipe staging deadline elapsed; no commit sent')
                    driver.write_recipe_member(profile, prefix + '.' + path, value)
                actual = driver.read_command_root(definition)
                if not all(matches(member_value(actual, prefix + '.' + path), value) for path, value in self.expected(record).items()):
                    raise ValueError('Complete staged recipe readback mismatch; no commit sent')
                observed, permit = self.commands.observation(definition, value=actual)
                if observed != idle or not permit or utc_now() >= deadline:
                    raise ValueError('PLC channel/permit changed while staging, or deadline elapsed; no commit sent')

            ticket.confirm(recipe_revision=revision['id'], content_hash=revision['content_hash'],
                           production_approved=snapshot['production_approved'], approved_by=revision['approved_by'])
            result = self.commands.submit(definition, ticket, reservation=reserve, prepare=prepare)
            return {**result, 'transfer': self.get(result['transaction']['id'])}
