"""Project-local HMI groups and local/Windows identity authorization."""

import argparse
from dataclasses import dataclass
import getpass
import hashlib
import json
from pathlib import Path
import re
import secrets
from threading import RLock
import time

from fastapi import HTTPException
from .alarms import utc_now
from .projects import ProjectStore
from .recipe_auth import hash_password, verify_password
from .windows_identity import WindowsIdentity

COOKIE = 'openhmi_session'
PERMISSIONS = {'project.edit', 'runtime.operate', 'runtime.write', 'alarms.acknowledge', 'alarms.comment', 'alarms.shelve', 'security.manage', 'activity.view', 'diagnostics.view',
               'recipes.engineer', 'recipes.approver', 'recipes.operator', 'recipes.administrator'}
DEFAULT_GROUPS = {
    'Administrators': sorted(PERMISSIONS),
    'Engineers': ['project.edit', 'runtime.operate', 'runtime.write', 'alarms.acknowledge', 'alarms.comment', 'recipes.engineer', 'activity.view', 'diagnostics.view'],
    'Operators': ['runtime.operate', 'alarms.acknowledge', 'alarms.comment', 'recipes.operator'],
    'Approvers': ['recipes.approver'],
}


@dataclass(frozen=True)
class Principal:
    name: str
    provider: str
    groups: frozenset[str]
    permissions: frozenset[str]

    @property
    def roles(self):
        return frozenset(value.split('.', 1)[1] for value in self.permissions if value.startswith('recipes.'))

    def permits(self, role):
        return f'recipes.{role}' in self.permissions or 'recipes.administrator' in self.permissions

    def public(self):
        return {'name': self.name, 'provider': self.provider, 'groups': sorted(self.groups),
                'permissions': sorted(self.permissions), 'roles': sorted(self.roles)}


class Security:
    def __init__(self, store, windows=None):
        self.store, self.windows = store, windows or WindowsIdentity()
        self.lock = RLock()
        self.sessions, self.failures = {}, {}
        self.dummy_hash = hash_password(secrets.token_urlsafe(24))
        with store.transaction() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS security_settings(id INTEGER PRIMARY KEY CHECK(id=1),version INTEGER NOT NULL,windows_enabled INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS security_group(name TEXT PRIMARY KEY,permissions TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS security_user(name TEXT PRIMARY KEY,password_hash TEXT NOT NULL,groups_json TEXT NOT NULL,enabled INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS security_windows(sid TEXT NOT NULL,kind TEXT NOT NULL,label TEXT NOT NULL,hmi_group TEXT NOT NULL,PRIMARY KEY(sid,kind,hmi_group));
                CREATE TABLE IF NOT EXISTS security_audit(id INTEGER PRIMARY KEY,timestamp TEXT NOT NULL,actor TEXT NOT NULL,operation TEXT NOT NULL,details TEXT NOT NULL);
                INSERT OR IGNORE INTO security_settings VALUES(1,1,0);
            ''')
            for name, permissions in DEFAULT_GROUPS.items():
                db.execute('INSERT OR IGNORE INTO security_group VALUES(?,?)', (name, json.dumps(permissions)))

    def configured(self):
        with self.store._lock:
            db = self.store._db
            return bool(db.execute('SELECT COUNT(*) FROM security_user').fetchone()[0] or db.execute('SELECT windows_enabled FROM security_settings').fetchone()[0])

    def _principal(self, identity):
        with self.store._lock:
            db = self.store._db
            if identity['provider'] == 'local':
                row = db.execute('SELECT groups_json,enabled FROM security_user WHERE name=?', (identity['key'],)).fetchone()
                if not row or not row[1]:
                    return None
                groups = set(json.loads(row[0]))
            else:
                if not db.execute('SELECT windows_enabled FROM security_settings').fetchone()[0]:
                    return None
                groups = {group for sid, kind, group in db.execute('SELECT sid,kind,hmi_group FROM security_windows')
                          if (kind == 'user' and sid == identity['key']) or (kind == 'group' and sid in identity['token_groups'])}
                if not groups:
                    return None
            permissions = set()
            for name, granted in db.execute('SELECT name,permissions FROM security_group'):
                if name in groups:
                    permissions.update(json.loads(granted))
            return Principal(identity['name'], identity['provider'], frozenset(groups), frozenset(permissions))

    def login(self, name, password, peer, provider='local'):
        now = time.monotonic()
        with self.lock:
            self.failures = {key: [when for when in values if when > now - 60] for key, values in self.failures.items() if values and values[-1] > now - 60}
            key = peer  # One limit across names and providers, including unknown users.
            if len(self.failures.get(key, [])) >= 10:
                raise HTTPException(429, 'Too many sign-in attempts; try again later')
            self.failures.setdefault(key, []).append(now)
            identity = None
            if provider == 'local':
                with self.store._lock:
                    row = self.store._db.execute('SELECT password_hash,enabled FROM security_user WHERE name=?', (name,)).fetchone()
                if verify_password(password, row[0] if row else self.dummy_hash) and row and row[1]:
                    identity = {'provider': 'local', 'key': name, 'name': name}
            elif provider == 'windows':
                with self.store._lock:
                    enabled = self.store._db.execute('SELECT windows_enabled FROM security_settings').fetchone()[0]
                if enabled and self.windows.available:
                    try:
                        result = self.windows.authenticate(name, password)
                    except OSError:
                        result = None
                    if result:
                        identity = {'provider': 'windows', 'key': result['sid'], 'name': result['name'], 'token_groups': result['groups']}
            principal = self._principal(identity) if identity else None
            if not principal:
                raise HTTPException(401, 'Invalid credentials or no HMI group assignment')
            self.failures.pop(key, None)
            self.sessions = {key: value for key, value in self.sessions.items() if value[1] > now}
            token = secrets.token_urlsafe(32)
            self.sessions[hashlib.sha256(token.encode()).digest()] = (identity, now + 3600)
            with self.store.transaction() as db:
                self.audit(db, principal.name, 'login', provider=provider)
            return token, principal

    def user(self, token):
        with self.lock:
            key = hashlib.sha256((token or '').encode()).digest()
            value = self.sessions.get(key)
            if not value or value[1] <= time.monotonic():
                self.sessions.pop(key, None)
                return None
            return self._principal(value[0])

    def logout(self, token):
        with self.lock:
            self.sessions.pop(hashlib.sha256((token or '').encode()).digest(), None)

    @staticmethod
    def origin(request):
        origin = request.headers.get('origin')
        if origin and origin != f'{request.url.scheme}://{request.url.netloc}':
            raise HTTPException(403, 'Changes require a same-origin request')

    def require(self, request, permission, groups=()):
        self.origin(request)
        user = self.user(request.cookies.get(COOKIE))
        if not self.configured() and not groups:
            return None  # Explicitly reported simulation mode; no accounts configured.
        if not user:
            raise HTTPException(401, 'Sign in to perform this operation')
        if permission not in user.permissions or (groups and not user.groups.intersection(groups) and 'security.manage' not in user.permissions):
            raise HTTPException(403, 'Your HMI groups do not allow this operation')
        return user

    @staticmethod
    def audit(db, actor, operation, **details):
        db.execute('INSERT INTO security_audit(timestamp,actor,operation,details) VALUES(?,?,?,?)',
                   (utc_now(), actor, operation, json.dumps(details)))

    def snapshot(self):
        with self.store._lock:
            db = self.store._db
            version, enabled = db.execute('SELECT version,windows_enabled FROM security_settings').fetchone()
            return {'version': version, 'windows_enabled': bool(enabled), 'windows_available': self.windows.available,
                    'permissions': sorted(PERMISSIONS), 'groups': [{'name': name, 'permissions': json.loads(grants)} for name, grants in db.execute('SELECT name,permissions FROM security_group ORDER BY name')],
                    'users': [{'name': name, 'groups': json.loads(groups), 'enabled': bool(enabled)} for name, groups, enabled in db.execute('SELECT name,groups_json,enabled FROM security_user ORDER BY name')],
                    'bindings': [{'sid': sid, 'kind': kind, 'label': label, 'group': group} for sid, kind, label, group in db.execute('SELECT sid,kind,label,hmi_group FROM security_windows ORDER BY label')],
                    'audit': [{'timestamp': stamp, 'actor': actor, 'operation': operation, 'details': json.loads(details)} for stamp, actor, operation, details in db.execute('SELECT timestamp,actor,operation,details FROM security_audit ORDER BY id DESC LIMIT 200')]}

    def change(self, body, actor):
        # Password hashing and Windows resolution happen before holding the SQL transaction.
        encoded = hash_password(body.password) if body.operation == 'user' and body.password else None
        sid = self.windows.resolve(body.account, body.kind) if body.operation == 'binding' else None
        with self.store.transaction() as db:
            if db.execute('SELECT version FROM security_settings').fetchone()[0] != body.expected_version:
                raise HTTPException(409, 'Security changed; refresh before saving')
            names = {row[0] for row in db.execute('SELECT name FROM security_group')}
            if body.operation == 'group':
                if not set(body.permissions) <= PERMISSIONS:
                    raise HTTPException(422, 'Unknown permission')
                db.execute('INSERT INTO security_group VALUES(?,?) ON CONFLICT(name) DO UPDATE SET permissions=excluded.permissions', (body.name, json.dumps(body.permissions)))
            elif body.operation == 'user':
                if not set(body.groups) <= names:
                    raise HTTPException(422, 'Unknown HMI group')
                old = db.execute('SELECT password_hash FROM security_user WHERE name=?', (body.name,)).fetchone()
                if not encoded and not old:
                    raise HTTPException(422, 'A new local user requires a password')
                db.execute('INSERT INTO security_user VALUES(?,?,?,?) ON CONFLICT(name) DO UPDATE SET password_hash=excluded.password_hash,groups_json=excluded.groups_json,enabled=excluded.enabled',
                           (body.name, encoded or old[0], json.dumps(body.groups), body.enabled))
            elif body.operation in ('binding', 'unbind'):
                if body.group not in names:
                    raise HTTPException(422, 'Unknown HMI group')
                if body.operation == 'binding':
                    db.execute('INSERT OR REPLACE INTO security_windows VALUES(?,?,?,?)', (sid, body.kind, body.account, body.group))
                else:
                    db.execute('DELETE FROM security_windows WHERE sid=? AND kind=? AND hmi_group=?', (body.sid, body.kind, body.group))
            else:
                if body.enabled and not self.windows.available:
                    raise HTTPException(422, 'Windows login requires a Windows server')
                db.execute('UPDATE security_settings SET windows_enabled=?', (body.enabled,))
            admin_groups = {name for name, grants in db.execute('SELECT name,permissions FROM security_group') if 'security.manage' in json.loads(grants)}
            if not any(set(json.loads(groups)) & admin_groups for groups, in db.execute('SELECT groups_json FROM security_user WHERE enabled=1')):
                raise HTTPException(409, 'Retain at least one enabled local security administrator')
            db.execute('UPDATE security_settings SET version=version+1')
            self.audit(db, actor, body.operation, reason=body.reason, name=body.name, groups=body.groups,
                       permissions=body.permissions, account=body.account, group=body.group, enabled=body.enabled)
        if body.operation == 'user':
            with self.lock:
                self.sessions = {key: value for key, value in self.sessions.items() if not (value[0]['provider'] == 'local' and value[0]['key'] == body.name)}
        return self.snapshot()


def main(argv=None):
    parser = argparse.ArgumentParser(description='Bootstrap a local OpenHMI administrator; password is prompted')
    parser.add_argument('--project', type=Path, default=Path('.local/project.sqlite3'))
    parser.add_argument('--user', required=True)
    args = parser.parse_args(argv)
    if not re.fullmatch(r'[A-Za-z0-9_. -]{1,60}', args.user) or args.user != args.user.strip():
        parser.error('Use a user name of 1–60 letters, numbers, spaces, dots, underscores or hyphens, without surrounding spaces')
    from .security_routes import SecurityChange
    password = getpass.getpass('Password: ')
    if not 12 <= len(password) <= 256:
        parser.error('Use a password between 12 and 256 characters')
    if password != getpass.getpass('Confirm password: '):
        parser.error('Passwords do not match')
    store = ProjectStore(args.project)
    try:
        security = Security(store)
        if any(user['name'] == args.user for user in security.snapshot()['users']):
            parser.error('Account exists; use Security administration to change it')
        body = SecurityChange(operation='user', expected_version=security.snapshot()['version'], name=args.user,
                              groups=['Administrators'], password=password, reason='Local administrator bootstrap')
        security.change(body, 'local-console')
    finally:
        store.close()
    print('Administrator created. Open Security in OpenHMI to manage groups and assignments.')
