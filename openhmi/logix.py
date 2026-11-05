"""pycomm3 explicit-message adapter; shared batched polling, never CIP I/O subscriptions."""

from copy import deepcopy
import math
import json
import re
from threading import RLock
import time

from .drivers import SimulatorDriver
from .screens import screen_map, expanded_controls, referenced_tags
from .alarms import utc_now


def member_value(value, path):
    for part in re.findall(r'[^.\[\]]+', path):
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def type_ok(value, kind):
    if type(value) not in {'boolean': (bool,), 'number': (int, float), 'integer': (int,), 'string': (str,), 'struct': (dict,)}[kind]:
        return False
    if type(value) is float and not math.isfinite(value) or type(value) is int and abs(value) > 9007199254740991:
        return False
    if kind == 'struct':
        try:
            json.dumps(value, allow_nan=False)
        except (ValueError, TypeError, OverflowError):
            return False
    return True


class LogixConnection:
    def __init__(self, config, factory=None):
        self.config, self.factory = config, factory
        self.lock = RLock()
        self.client = None
        self.connected = False
        self.error = None
        self.retry_at, self.failures = 0, 0
        self.metadata = {}
        self.read_calls = self.tags_read = 0

    def close(self):
        with self.lock:
            if self.client:
                try:
                    self.client.close()
                except Exception:
                    pass
                self.client = None
            self.connected = False

    def connect(self, now):
        if self.client:
            return
        if now < self.retry_at:
            raise ConnectionError('Waiting for reconnect backoff')
        if self.factory is None:
            from pycomm3 import LogixDriver
            factory = LogixDriver
        else:
            factory = self.factory
        # Use public tag initialization. Do not request an empty metadata namespace filter.
        client = factory(self.config['path'], init_tags=True, init_program_tags=self.config['program_tags'])
        client.socket_timeout = self.config['timeout_seconds']
        self.client = client
        try:
            if not client.open():
                raise ConnectionError('PLC connection did not open')
            self.metadata = {name: self._metadata(name, info) for name, info in client.tags.items()}
            self.connected = True
        except Exception:
            self.close()
            raise

    @staticmethod
    def _metadata(name, info):
        datatype = info.get('data_type', '')
        if isinstance(datatype, dict):
            if datatype.get('string'):
                return {'address': name, 'type': 'string', 'udt_type': '', 'members': {}, 'external_access': info.get('external_access', 'Unknown')}
            members = {}
            def visit(data, prefix=''):
                for key in data.get('attributes', []):
                    detail = data.get('internal_tags', {}).get(key, {})
                    field = detail.get('data_type', '')
                    path = prefix + key
                    if isinstance(field, dict):
                        visit(field, path + '.')
                    elif detail.get('array', 0) == 0:
                        members[path] = LogixConnection.kind(field)
            visit(datatype)
            return {'address': name, 'type': 'struct', 'udt_type': datatype.get('name', ''), 'members': members,
                    'external_access': info.get('external_access', 'Unknown')}
        return {'address': name, 'type': LogixConnection.kind(datatype), 'udt_type': '', 'members': {},
                'dimensions': info.get('dimensions', []), 'external_access': info.get('external_access', 'Unknown')}

    @staticmethod
    def kind(datatype):
        if datatype == 'BOOL':
            return 'boolean'
        if datatype in ('SINT', 'INT', 'DINT', 'LINT', 'USINT', 'UINT', 'UDINT', 'ULINT'):
            return 'integer'
        if datatype in ('REAL', 'LREAL'):
            return 'number'
        return 'string'

    def tag_metadata(self, address):
        if address in self.metadata:
            return self.metadata[address]
        candidates = [name for name in self.metadata if address.startswith(name + '.') or address.startswith(name + '[')]
        return self.metadata[max(candidates, key=len)] if candidates else {}

    def failed(self, error, now):
        self.error = str(error)
        self.failures += 1
        self.retry_at = now + min(30, 2 ** min(self.failures - 1, 5))
        self.close()

    def read(self, addresses, now):
        with self.lock:
            if self.client is None and now < self.retry_at:
                raise ConnectionError(self.error or 'Waiting for reconnect backoff')
            try:
                self.connect(now)
                results = []
                for start in range(0, len(addresses), 200):
                    batch = addresses[start:start + 200]
                    returned = self.client.read(*batch)
                    returned = returned if isinstance(returned, list) else [returned]
                    if len(returned) != len(batch):
                        raise ConnectionError('PLC returned an incomplete tag batch')
                    results.extend(returned)
                    self.read_calls += 1
                    self.tags_read += len(batch)
                self.error, self.failures = None, 0
                return results
            except Exception as error:
                self.failed(error, now)
                raise

    def write(self, address, value):
        with self.lock:
            if not self.client:
                raise ConnectionError('PLC is disconnected')
            try:
                result = self.client.write((address, value))
                if result.error:
                    raise ValueError(f'PLC rejected write: {result.error}')
                actual = self.client.read(address)
                matches = math.isclose(actual.value, value, rel_tol=1e-6, abs_tol=1e-7) if type(actual.value) is float and type(value) in (int, float) else actual.value == value
                if actual.error or not matches:
                    raise ValueError('PLC write readback did not match; command was not retried')
                return actual.value
            except Exception as error:
                # Never replay a write during reconnection.
                self.failed(error, time.monotonic())
                raise


class RuntimeDriver(SimulatorDriver):
    def __init__(self, factory=None):
        super().__init__()
        self.lock = RLock()
        self.io_lock = RLock()
        self.factory = factory
        self.connections, self.definitions, self.sources, self.samples = {}, {}, {}, {}
        self.project = None
        self.leases, self.deadlines, self.last_rates = {}, {}, {}
        self.local_names = set()
        self.plc_hold = False

    def configure(self, project):
        with self.io_lock, self.lock:
            configs = {config['id']: config for config in project.get('connections', []) if config['enabled'] and not self.plc_hold}
            changed_connections = {identifier for identifier, connection in self.connections.items() if configs.get(identifier) != connection.config}
            for identifier, connection in list(self.connections.items()):
                if configs.get(identifier) != connection.config:
                    connection.close()
                    del self.connections[identifier]
            for identifier, config in configs.items():
                if identifier not in self.connections:
                    changed_connections.add(identifier)
                    self.connections[identifier] = LogixConnection(config, self.factory)
            old = self.definitions
            self.definitions = {tag['name']: deepcopy(tag) for tag in project.get('tags', [])}
            for name in self.local_names - self.definitions.keys():
                self._tags.pop(name, None)
            self.local_names = {name for name, tag in self.definitions.items() if not tag['connection']}
            self.sources = {}
            for name, tag in self.definitions.items():
                self.sources[name] = (name, '')
                for member in tag['members']:
                    self.sources[f'{name}.{member}'] = (name, member)
                if old.get(name) != tag or tag['connection'] in changed_connections:
                    for alias, (root, _) in self.sources.items():
                        if root == name:
                            self.samples.pop(alias, None)
                    if not tag['connection']:
                        self._tags[name] = float(tag['initial']) if tag['type'] == 'number' else deepcopy(tag['initial'])
                    else:
                        self._tags.pop(name, None)
            self.project = deepcopy(project)
            self.deadlines.clear()

    def lease(self, client, screens, now=None, preview_root=''):
        now = time.monotonic() if now is None else now
        with self.lock:
            known = screen_map(self.project)
            if any(screen not in known for screen in screens):
                raise ValueError('Unknown subscription screen')
            if preview_root and (preview_root not in self.definitions or self.definitions[preview_root]['type'] != 'struct'):
                raise ValueError('Faceplate preview requires a configured UDT tag')
            self.leases[client] = (set(screens), now + 15, preview_root)
            self.leases = {key: value for key, value in self.leases.items() if value[1] > now}
            if len(self.leases) > 1000:
                self.leases.pop(next(iter(self.leases)))

    def demands(self, now):
        rates = {}
        def demand(tag, rate):
            rates[tag] = min(rate, rates.get(tag, rate))
        project = self.project
        if not project:
            return rates
        screens = screen_map(project)
        wanted = set().union(*(value[0] for value in self.leases.values() if value[1] > now)) if self.leases else set()
        for lease in self.leases.values():
            if lease[1] > now and lease[2]:
                demand(lease[2], 500)
        for identifier in wanted & screens.keys():
            for control in expanded_controls(project, identifier):
                for tag in referenced_tags(control):
                    demand(tag, screens[identifier].get('update_ms', 500))
        for alarm in project.get('alarms', []):
            if alarm['enabled']:
                demand(alarm['tag'], 250)
        for history in project.get('historian', {}).get('tags', []):
            demand(history['tag'], history['sample_ms'])
        for command in project.get('commands', []):
            demand(command['root_tag'], command['update_ms'])
        return rates

    def poll(self, now=None):
        real_clock = now is None
        now = time.monotonic() if now is None else now
        with self.io_lock:
            with self.lock:
                demands = self.demands(now)
                grouped = {}
                for alias, rate in demands.items():
                    root, _ = self.sources.get(alias, (None, ''))
                    tag = self.definitions.get(root)
                    if tag and tag['connection']:
                        key = (tag['connection'], tag['address'])
                        grouped[key] = min(rate, grouped.get(key, rate))
                for key, rate in grouped.items():
                    if rate < self.last_rates.get(key, rate):
                        self.deadlines[key] = now
                self.last_rates = grouped
            for identifier, connection in list(self.connections.items()):
                due = [address for (conn, address), rate in grouped.items() if conn == identifier and now >= self.deadlines.get((conn, address), 0)]
                if not due and not connection.client and now >= connection.retry_at:
                    # Metadata browsing is available even before a screen leases tags.
                    try:
                        with connection.lock:
                            connection.connect(now)
                    except Exception as error:
                        connection.failed(error, now)
                if not due:
                    continue
                try:
                    results = connection.read(due, now)
                except Exception:
                    results = [None] * len(due)
                acquired = time.monotonic() if real_clock else now
                with self.lock:
                    for address, result in zip(due, results):
                        rate = grouped[(identifier, address)]
                        self.deadlines[(identifier, address)] = acquired + rate / 1000
                        for root, tag in self.definitions.items():
                            if tag['connection'] != identifier or tag['address'] != address:
                                continue
                            for alias, (source, member) in self.sources.items():
                                if source != root:
                                    continue
                                error = connection.error if result is None else result.error
                                try:
                                    if error or result is None:
                                        raise ValueError(error or 'PLC read failed')
                                    value = member_value(result.value, member) if member else result.value
                                    kind = tag['members'][member] if member else tag['type']
                                    if not type_ok(value, kind):
                                        raise ValueError('PLC value does not match configured type')
                                    if not member and kind in ('number', 'integer'):
                                        if tag['scale'] != 1 or tag['offset'] != 0:
                                            value = value * tag['scale'] + tag['offset']
                                        elif kind == 'number':
                                            value = float(value)
                                        if not math.isfinite(value):
                                            raise ValueError('Scaled PLC value is not finite')
                                    self.samples[alias] = {'value': value, 'quality': 'good', 'timestamp': utc_now(), 'monotonic': acquired, 'rate_ms': rate, 'error': None}
                                except (ValueError, KeyError, TypeError, IndexError) as failure:
                                    self.samples[alias] = {'value': None, 'quality': 'bad', 'timestamp': utc_now(), 'monotonic': acquired, 'rate_ms': rate, 'error': str(failure)}

    def sample_snapshot(self, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            result = {name: {'value': deepcopy(value), 'quality': 'good', 'timestamp': utc_now(), 'error': None} for name, value in self._tags.items()}
            for name, tag in self.definitions.items():
                if not tag['connection']:
                    for member in tag['members']:
                        try:
                            result[f'{name}.{member}'] = {**result[name], 'value': member_value(self._tags[name], member)}
                        except (KeyError, TypeError, IndexError):
                            result[f'{name}.{member}'] = {'value': None, 'quality': 'bad', 'timestamp': utc_now(), 'error': 'Missing UDT member'}
            for alias, (root, _) in self.sources.items():
                tag = self.definitions[root]
                if not tag['connection']:
                    continue
                sample = deepcopy(self.samples.get(alias, {'value': None, 'quality': 'pending', 'timestamp': None, 'error': 'Waiting for PLC sample'}))
                if sample.get('quality') == 'good' and now - sample['monotonic'] > max(1.0, 3 * sample['rate_ms'] / 1000):
                    sample.update(quality='stale', error='PLC sample is stale')
                if tag['connection'] not in self.connections:
                    sample.update(quality='bad', error='PLC acquisition is held' if self.plc_hold else 'Connection is disabled')
                sample.pop('monotonic', None)
                if alias in self.samples:
                    sample['age_seconds'] = max(0, now - self.samples[alias]['monotonic'])
                result[alias] = sample
            return result

    def snapshot(self):
        return {name: sample['value'] for name, sample in self.sample_snapshot().items() if sample['quality'] == 'good'}

    def read(self, address, count=1):
        if count != 1:
            raise ValueError('Read one logical tag at a time')
        return [self.snapshot()[address]]

    def write(self, address, values):
        publication = (self.project or {}).get('identity_publication', {})
        if publication.get('enabled'):
            root, member = self.sources.get(address, (None, ''))
            target = self.definitions.get(root)
            for field in ('username_tag', 'privileges_tag', 'heartbeat_tag'):
                reserved = self.definitions.get(publication.get(field))
                aliases = target and reserved and target['connection'] and target['connection'] == reserved['connection'] and target['address'] + ('.' + member if member else '') == reserved['address']
                if address == publication.get(field) or aliases:
                    raise ValueError('Identity publication tags are runtime-owned')
        root, _ = self.sources.get(address, (None, ''))
        if any(item['root_tag'] == root for item in (self.project or {}).get('commands', [])):
            raise ValueError('Command UDT is protocol-owned; use a command button')
        return self._write(address, values)

    def write_command_request(self, identifier, sequence):
        definition = next(item for item in self.project['commands'] if item['id'] == identifier)
        return self._write(definition['root_tag'] + '.' + definition['request_member'], [sequence])

    def write_recipe_member(self, profile, member, value):
        from .recipe_transfers import META_TYPES
        allowed = {profile['staging_prefix'] + '.' + path for path in [*META_TYPES, *profile['parameters'].values()]}
        if member not in allowed:
            raise ValueError('Recipe writes are limited to declared staging members')
        command = next(item for item in self.project['commands'] if item['id'] == profile['command_id'])
        return self._write(command['root_tag'] + '.' + member, [value])

    def read_command_root(self, definition):
        """Explicit verification read; it does not replace normal displayed samples."""
        with self.io_lock:
            tag = self.definitions[definition['root_tag']]
            if not tag['connection']:
                with self.lock:
                    return deepcopy(self._tags[tag['name']])
            connection = self.connections.get(tag['connection'])
            if not connection:
                raise ConnectionError('PLC connection is disabled')
            result = connection.read([tag['address']], time.monotonic())[0]
            if result.error or not isinstance(result.value, dict):
                raise ValueError('Recipe verification root read failed')
            return result.value

    def _write(self, address, values):
        with self.io_lock:
            root, member = self.sources.get(address, (None, ''))
            tag = self.definitions.get(root)
            if tag is None:
                with self.lock:
                    return super().write(address, values)
            kind = tag['members'][member] if member else tag['type']
            write_kind = 'number' if kind == 'integer' and not member and (tag['scale'] != 1 or tag['offset'] != 0) else kind
            if not tag['writable'] or len(values) != 1 or not type_ok(values[0], write_kind) or kind == 'struct':
                raise ValueError('Tag is read-only or write type is incompatible')
            value = values[0]
            if tag['connection']:
                connection = self.connections.get(tag['connection'])
                if not connection:
                    raise ConnectionError('PLC connection is disabled')
                metadata = connection.tag_metadata(tag['address'])
                if metadata.get('external_access') != 'Read/Write':
                    raise ValueError('PLC metadata does not permit writes')
                raw = value if member else (value - tag['offset']) / tag['scale'] if kind in ('number', 'integer') else value
                if kind == 'integer':
                    if int(raw) != raw:
                        raise ValueError('Scaled integer writes must resolve to an integer')
                    raw = int(raw)
                connection.write(tag['address'] + ('.' + member if member else ''), raw)
                # A write readback verifies the transaction; normal polling owns displayed samples.
                self.deadlines.pop((tag['connection'], tag['address']), None)
            else:
                with self.lock:
                    if member:
                        parts = re.findall(r'[^.\[\]]+', member)
                        parent = self._tags[root]
                        for part in parts[:-1]:
                            parent = parent[int(part)] if isinstance(parent, list) else parent[part]
                        parent[int(parts[-1]) if isinstance(parent, list) else parts[-1]] = value
                    else:
                        self._tags[root] = float(value) if kind == 'number' else value

    def coerce_number(self, address, value):
        root, member = self.sources.get(address, (None, ''))
        tag = self.definitions.get(root)
        kind = tag['members'][member] if tag and member else tag['type'] if tag else 'number' if type(self._tags.get(address)) is float else 'integer' if type(self._tags.get(address)) is int else ''
        if tag and not member and kind == 'integer' and (tag['scale'] != 1 or tag['offset'] != 0):
            kind = 'number'
        if kind == 'number' and type(value) is int:
            return float(value)
        if kind == 'integer' and type(value) is float and value.is_integer():
            return int(value)
        return value

    def status(self):
        with self.lock:
            return [{'id': identifier, 'connected': connection.connected, 'error': connection.error,
                     'read_calls': connection.read_calls, 'tags_read': connection.tags_read,
                     'groups': [{'rate_ms': rate, 'addresses': sorted(address for (conn, address), interval in self.last_rates.items() if conn == identifier and interval == rate)}
                                for rate in sorted({interval for (conn, _), interval in self.last_rates.items() if conn == identifier})]}
                    for identifier, connection in self.connections.items()]

    def close(self):
        with self.io_lock:
            for connection in self.connections.values():
                connection.close()
