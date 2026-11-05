"""Opt-in single-station identity/status publication; never an authorization source."""
import hashlib
import re
from copy import deepcopy
import time
from threading import RLock
from typing import Literal
from fastapi import HTTPException, Request
from pydantic import Field, model_validator
from .runtime_models import Model


class PrivilegeBit(Model):
    bit: int = Field(ge=0, le=31)
    source: Literal['permission', 'group'] = 'permission'
    name: str = Field(min_length=1, max_length=100)


class IdentityPublication(Model):
    enabled: bool = False
    username_tag: str = Field(default='', max_length=200)
    privileges_tag: str = Field(default='', max_length=200)
    heartbeat_tag: str = Field(default='', max_length=200)
    username_bytes: int = Field(default=82, ge=1, le=4096)
    bits: list[PrivilegeBit] = Field(default_factory=list, max_length=32)

    @model_validator(mode='after')
    def unique(self):
        if len({item.bit for item in self.bits}) != len(self.bits):
            raise ValueError('Privilege bit positions must be unique')
        if self.enabled and (not self.username_tag or not self.privileges_tag or self.username_tag == self.privileges_tag):
            raise ValueError('Identity publication requires separate STRING and DINT tags')
        if self.heartbeat_tag and self.heartbeat_tag in (self.username_tag, self.privileges_tag):
            raise ValueError('Heartbeat must use its own DINT tag')
        return self


class StationClaim(Model):
    client: str = Field(min_length=1, max_length=100)


class IdentityPublisher:
    def __init__(self, driver, security):
        self.driver, self.security = driver, security
        self.lock = RLock()
        self.owner = None
        self.deadline = 0
        self.applied = None
        self.last_config = None
        self.retry_at = 0
        self.last_write = 0
        self.sequence = 0
        self.state = {'status': 'disabled', 'error': None, 'owner': None}

    @staticmethod
    def key(token):
        return hashlib.sha256((token or '').encode()).digest()

    def claim(self, request, client):
        principal = self.security.require(request, 'identity.publish')
        if not principal:
            raise HTTPException(401, 'A signed-in HMI user is required to claim publication')
        from .security import COOKIE
        key = self.key(request.cookies.get(COOKIE))
        if not (self.driver.project or {}).get('identity_publication', {}).get('enabled'):
            raise HTTPException(409, 'Identity publication is disabled in the active project')
        with self.lock:
            if self.owner and self.deadline > time.monotonic() and self.owner != (key, client):
                raise HTTPException(409, 'Another station owns PLC identity publication')
            if self.owner != (key, client) or self.deadline <= time.monotonic():
                self.state = {'status': 'pending', 'error': None}
            self.owner = (key, client)
            self.deadline = time.monotonic() + 15
        return self.snapshot()

    def release(self, request, client):
        self.security.origin(request)
        from .security import COOKIE
        with self.lock:
            if self.owner == (self.key(request.cookies.get(COOKIE)), client):
                self.owner = None
                self.state = {'status': 'clearing', 'error': None}
        return self.snapshot()

    def replace_login(self, old, new):
        with self.lock:
            if self.owner and self.owner[0] == self.key(old):
                self.owner = (self.key(new), self.owner[1]) if new else None
                self.state = {'status': 'pending' if new else 'clearing', 'error': None}

    def snapshot(self):
        with self.lock:
            return {**self.state, 'owner': self.owner[1] if self.owner and self.deadline > time.monotonic() else None,
                    'lease_seconds': 15, 'configured': bool((self.driver.project or {}).get('identity_publication', {}).get('enabled'))}

    def poll(self):
        with self.lock:
            principal = None
            if self.owner and self.deadline > time.monotonic():
                with self.security.lock:
                    session = self.security.sessions.get(self.owner[0])
                    if session and session[1] > time.monotonic():
                        principal = self.security._principal(session[0])
                if not principal or 'identity.publish' not in principal.permissions:
                    self.owner = None
                    principal = None
            else:
                self.owner = None
            config = (self.driver.project or {}).get('identity_publication', {})
            if self.driver.plc_hold:
                self.state = {'status': 'held', 'error': None}
                self.applied = None
                return
            if time.monotonic() < self.retry_at:
                return
            try:
                with self.driver.io_lock:
                    config = deepcopy((self.driver.project or {}).get('identity_publication', {}))
                    if self.last_config and self.last_config != config:
                        self._write(self.last_config, '', 0)
                        self.last_config, self.applied = None, None
                    if not config.get('enabled'):
                        self.state = {'status': 'disabled', 'error': None}
                        return
                    name = principal.name if principal else ''
                    mask = sum(1 << item['bit'] for item in config['bits'] if principal and item['name'] in (principal.permissions if item['source'] == 'permission' else principal.groups))
                    if len(name.encode('utf-8')) > config['username_bytes']:
                        self._write(config, '', 0)
                        raise ValueError('Username exceeds configured PLC STRING byte capacity')
                    desired = (config, name, mask)
                    if self.applied != desired or time.monotonic() - self.last_write >= 1:
                        self._write(config, name, mask)
                        self.applied = desired
                        self.last_write = time.monotonic()
                    self.last_config = config
                    self.state = {'status': 'published', 'error': None, 'username': name, 'privileges': mask}
            except (ValueError, KeyError, ConnectionError, OSError):
                self.applied = None
                self.retry_at = time.monotonic() + 1
                self.state = {'status': 'error', 'error': 'Identity publication failed; verify connection, STRING capacity and DINT metadata'}

    def _write(self, config, name, mask):
        # The mask is invalidated first and granted last. These status tags are not an atomic pair.
        for tag in (config['username_tag'], config['privileges_tag'], *([config['heartbeat_tag']] if config.get('heartbeat_tag') else [])):
            definition = self.driver.definitions.get(tag)
            if not definition:
                raise ValueError('Publication requires root logical tags')
            if definition['connection']:
                connection = self.driver.connections.get(definition['connection'])
                tags = connection.client.tags if connection and connection.client else {}
                address = definition['address']
                roots = [root for root in tags if address == root or address.startswith(root + '.') or address.startswith(root + '[')]
                root = max(roots, key=len) if roots else ''
                datatype = tags.get(root, {}).get('data_type')
                for member in re.findall(r'[^.\[\]]+', address[len(root):]):
                    if not member.isdigit():
                        datatype = datatype.get('internal_tags', {}).get(member, {}).get('data_type') if isinstance(datatype, dict) else None
                if tag != config['username_tag'] and datatype != 'DINT':
                    raise ValueError('Privilege target must be a PLC DINT')
                if tag == config['username_tag'] and not (isinstance(datatype, dict) and datatype.get('string')):
                    raise ValueError('Username target must be a PLC STRING')
        self.last_config = deepcopy(config)
        self.driver._write(config['privileges_tag'], [0])
        self.driver._write(config['username_tag'], [name])
        self.driver._write(config['privileges_tag'], [mask if mask < 2**31 else mask - 2**32])
        if config.get('heartbeat_tag'):
            self.sequence = (self.sequence + 1) & 0x7fffffff
            self.driver._write(config['heartbeat_tag'], [self.sequence])

    def shutdown(self):
        with self.lock:
            self.owner = None
        self.applied = None
        self.retry_at = 0
        self.poll()


def add_identity_routes(app, publisher):
    @app.get('/api/security/publication')
    def status():
        return publisher.snapshot()

    @app.post('/api/security/publication/claim')
    def claim(body: StationClaim, request: Request):
        return publisher.claim(request, body.client)

    @app.post('/api/security/publication/release')
    def release(body: StationClaim, request: Request):
        return publisher.release(request, body.client)
