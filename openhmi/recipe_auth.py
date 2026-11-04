"""Server-configured recipe identities; no browser-supplied approval names."""

import argparse
from dataclasses import dataclass
import getpass
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets
from threading import RLock
import time

ROLES = {'engineer', 'approver', 'operator', 'administrator'}
ITERATIONS = 600_000


def hash_password(password):
    if not 12 <= len(password) <= 256:
        raise ValueError('Use a password between 12 and 256 characters')
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), bytes.fromhex(salt), ITERATIONS).hex()
    return f'pbkdf2_sha256${ITERATIONS}${salt}${digest}'


def verify_password(password, encoded):
    try:
        algorithm, rounds, salt, expected = encoded.split('$')
        if algorithm != 'pbkdf2_sha256' or not 600_000 <= int(rounds) <= 2_000_000 or len(password) > 256:
            return False
        actual = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), bytes.fromhex(salt), int(rounds)).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


@dataclass(frozen=True)
class RecipeUser:
    name: str
    roles: frozenset[str]

    def permits(self, role):
        return role in self.roles or 'administrator' in self.roles


class RecipeAuth:
    def __init__(self, source=None):
        self.lock = RLock()
        config = json.loads(source.read_text(encoding='utf-8')) if isinstance(source, Path) and source.exists() else source if isinstance(source, dict) else {'users': []}
        self.users = {}
        for entry in config['users']:
            name = entry['name']
            if not re.fullmatch(r'[A-Za-z0-9_.-]{1,60}', name) or name in self.users or not entry['roles'] or not set(entry['roles']) <= ROLES:
                raise ValueError('Invalid recipe user configuration')
            if not re.fullmatch(r'pbkdf2_sha256\$(?:[6-9]\d{5}|1\d{6}|2000000)\$[a-f0-9]{32}\$[a-f0-9]{64}', entry['password_hash']):
                raise ValueError('Recipe users require a supported password hash')
            self.users[name] = entry
        self.sessions = {}
        self.failures = {}
        self.dummy_hash = hash_password(secrets.token_urlsafe(24))

    def login(self, name, password, peer):
        now = time.monotonic()
        key = (peer, name)
        with self.lock:
            self.failures = {key: [when for when in times if when > now - 60] for key, times in self.failures.items() if times and times[-1] > now - 60}
            if len(self.failures.get(key, [])) >= 10:
                raise ValueError('Too many sign-in attempts; try again later')
            entry = self.users.get(name)
            if not verify_password(password, entry['password_hash'] if entry else self.dummy_hash):
                self.failures.setdefault(key, []).append(now)
                return None
            self.failures.pop(key, None)
            self.sessions = {key: value for key, value in self.sessions.items() if value[1] > now}
            token = secrets.token_urlsafe(32)
            self.sessions[hashlib.sha256(token.encode()).digest()] = (name, now + 3600)
            return token

    def user(self, token):
        with self.lock:
            key = hashlib.sha256((token or '').encode()).digest()
            session = self.sessions.get(key)
            if not session or session[1] <= time.monotonic():
                self.sessions.pop(key, None)
                return None
            entry = self.users.get(session[0])
            return RecipeUser(entry['name'], frozenset(entry['roles'])) if entry else None

    def logout(self, token):
        with self.lock:
            self.sessions.pop(hashlib.sha256((token or '').encode()).digest(), None)


def main():
    parser = argparse.ArgumentParser(description='Create a local OpenHMI recipe account; passwords are prompted, never passed on the command line')
    parser.add_argument('--file', type=Path, default=Path('.local/recipe-users.json'))
    parser.add_argument('--user', required=True)
    parser.add_argument('--roles', nargs='+', choices=sorted(ROLES), required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,60}', args.user):
        parser.error('Invalid user name')
    config = json.loads(args.file.read_text(encoding='utf-8')) if args.file.exists() else {'users': []}
    if any(entry['name'] == args.user for entry in config['users']):
        parser.error('That account already exists; existing accounts are preserved')
    password = getpass.getpass('Password: ')
    if password != getpass.getpass('Confirm password: '):
        parser.error('Passwords do not match')
    try:
        encoded = hash_password(password)
    except ValueError as error:
        parser.error(str(error))
    config['users'].append({'name': args.user, 'roles': args.roles, 'password_hash': encoded})
    args.file.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.file.with_name(args.file.name + '.new')
    with temporary.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(config, stream, indent=2)
        stream.write('\n')
    temporary.replace(args.file)
    print('Recipe account added. Restart OpenHMI to load account changes.')


if __name__ == '__main__':
    main()
