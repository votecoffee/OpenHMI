"""pycomm3 explicit-message adapter; shared batched polling, never CIP I/O subscriptions."""

from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from copy import deepcopy
import logging
import math
import re
from threading import Lock, RLock
import time
from uuid import uuid4

from .drivers import SimulatorDriver
from .runtime_models import MAX_PLC_CONNECTIONS
from .screens import screen_map, expanded_controls, referenced_tags
from .alarms import utc_now


MAX_SAFE_INTEGER = 2 ** 53 - 1
MAX_VIEWER_LEASES = 1000
MAX_SUBSCRIPTION_SEQUENCES = 2 * MAX_VIEWER_LEASES
REAL_MAX = float.fromhex('0x1.fffffep+127')
PLC_INTEGER_LIMITS = {
    'SINT': (-2 ** 7, 2 ** 7 - 1), 'USINT': (0, 2 ** 8 - 1),
    'INT': (-2 ** 15, 2 ** 15 - 1), 'UINT': (0, 2 ** 16 - 1),
    'DINT': (-2 ** 31, 2 ** 31 - 1), 'UDINT': (0, 2 ** 32 - 1),
    'LINT': (-2 ** 63, 2 ** 63 - 1), 'ULINT': (0, 2 ** 64 - 1),
}


def freshness_seconds(rate_ms):
    return max(1.0, 3 * rate_ms / 1000)


def member_value(value, path):
    for part in re.findall(r'[^.\[\]]+', path):
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def browser_value_ok(value):
    if isinstance(value, int):
        return abs(value) <= MAX_SAFE_INTEGER
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and browser_value_ok(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return all(browser_value_ok(item) for item in value)
    return value is None or isinstance(value, str)


def type_ok(value, kind):
    if type(value) not in {'boolean': (bool,), 'number': (int, float), 'integer': (int,), 'string': (str,), 'struct': (dict,)}[kind]:
        return False
    try:
        return browser_value_ok(value)
    except RecursionError:
        return False


def overlapping_addresses(first, second):
    first, second = first.casefold(), second.casefold()
    return (first == second or first.startswith((second + '.', second + '['))
            or second.startswith((first + '.', first + '[')))


def verify_result_address(address, result):
    returned_address = getattr(result, 'tag', address)
    # pycomm3 may omit the element count from the returned tag name.
    if returned_address != address and returned_address != re.sub(r'\{\d+\}$', '', address):
        raise ConnectionError('PLC returned a result for an unexpected tag address')


class TagWriteError(ValueError):
    """A PLC tag response could not confirm the requested write."""


class ScanTimings:
    """Bounded, in-memory timing samples for one configured route."""

    def __init__(self):
        self.lock = Lock()
        self.series = defaultdict(lambda: deque(maxlen=256))

    def record(self, metric, seconds):
        with self.lock:
            self.series[metric].append(max(0, seconds) * 1000)

    def snapshot(self):
        with self.lock:
            series = {name: list(samples) for name, samples in self.series.items()}
        result = {}
        for name, samples in series.items():
            ordered = sorted(samples)
            result[name] = {
                'count': len(samples), 'last_ms': round(samples[-1], 3),
                **{f'p{percentile}_ms': round(ordered[math.ceil(len(samples) * percentile / 100) - 1], 3)
                   for percentile in (50, 95, 99)},
            }
        return result


class LogixConnection:
    def __init__(self, config, factory=None):
        self.config, self.factory = config, factory
        self.instance = uuid4().hex
        self.lock = RLock()
        self.client = None
        self.connected = False
        self.error = None
        self.retry_at, self.failures = 0, 0
        self.failure_generation = self.scan_generation = 0
        self.outage_started = None
        self.has_usable_sample = False
        self.timings = ScanTimings()
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
        started = time.monotonic()
        # Use public tag initialization. Do not request an empty metadata namespace filter.
        client = factory(self.config['path'], init_tags=True, init_program_tags=self.config['program_tags'])
        client.socket_timeout = self.config['timeout_seconds']
        self.client = client
        try:
            if not client.open():
                raise ConnectionError('PLC connection did not open')
            self.metadata = {name: self._metadata(name, info) for name, info in client.tags.items()}
            self.connected = True
            metric = 'cold_open' if self.outage_started is None else 'reconnect_open'
            self.timings.record(metric, time.monotonic() - started)
        except Exception:
            self.close()
            raise

    @staticmethod
    def _metadata(name, info):
        datatype = info.get('data_type', '')
        metadata = {
            'address': name, 'udt_type': '', 'members': {},
            'dimensions': info.get('dimensions', []),
            'external_access': info.get('external_access', 'Unknown'),
        }
        if isinstance(datatype, dict):
            capacity = datatype.get('string')
            metadata['plc_type'] = datatype.get('name') or ('STRING' if capacity else '')
            if capacity:
                return {**metadata, 'type': 'string', 'string_capacity_bytes': capacity}

            members = metadata['members']

            def visit(data, prefix=''):
                for key in data.get('attributes', []):
                    detail = data.get('internal_tags', {}).get(key, {})
                    if detail.get('array'):
                        continue
                    field = detail.get('data_type', '')
                    path = prefix + key
                    if isinstance(field, dict) and field.get('string'):
                        members[path] = 'string'
                    elif isinstance(field, dict):
                        visit(field, path + '.')
                    else:
                        members[path] = LogixConnection.kind(field)

            visit(datatype)
            return {**metadata, 'type': 'struct', 'udt_type': metadata['plc_type']}

        metadata.update(type=LogixConnection.kind(datatype), plc_type=datatype)
        limits = PLC_INTEGER_LIMITS.get(datatype) if isinstance(datatype, str) else None
        if datatype == 'REAL':
            limits = (-REAL_MAX, REAL_MAX)
        if limits:
            # Decimal text preserves native 64-bit limits in JSON and the browser.
            metadata['numeric_range'] = [str(limit) for limit in limits]
        return metadata

    @staticmethod
    def kind(datatype):
        if datatype == 'BOOL':
            return 'boolean'
        if isinstance(datatype, str) and datatype in PLC_INTEGER_LIMITS:
            return 'integer'
        if datatype in ('REAL', 'LREAL'):
            return 'number'
        return 'string'

    def tag_metadata(self, address):
        if address in self.metadata:
            return self.metadata[address]
        candidates = [name for name in self.metadata if address.startswith(name + '.') or address.startswith(name + '[')]
        return self.metadata[max(candidates, key=len)] if candidates else {}

    def validate_write(self, address, value):
        if self.client is None:
            raise ConnectionError('PLC is disconnected')
        metadata = self.tag_metadata(address)
        if metadata.get('external_access') != 'Read/Write':
            raise ValueError('PLC metadata does not permit writes')
        root = metadata['address']
        datatype = self.client.tags.get(root, {}).get('data_type')
        suffix = re.sub(r'\[[^\]]*\]', '', address[len(root):])
        for member in suffix.split('.')[1:]:
            if not isinstance(datatype, dict):
                # Leave atomic bit suffixes and unresolved paths to the adapter.
                return
            datatype = datatype.get('internal_tags', {}).get(member, {}).get('data_type')
        if isinstance(datatype, str):
            limits = PLC_INTEGER_LIMITS.get(datatype)
            if limits and (type(value) is not int or not limits[0] <= value <= limits[1]):
                raise ValueError(f'Value must be an integer within the PLC {datatype} range [{limits[0]}, {limits[1]}]')
            if datatype == 'REAL' and type(value) in (int, float) and abs(value) > REAL_MAX:
                raise ValueError('Value exceeds the PLC REAL range')
        elif isinstance(datatype, dict) and type(value) is str:
            capacity = datatype.get('string')
            if type(capacity) is int and capacity > 0:
                # pycomm3 FixedSizeString uses ISO-8859-1 and reports the DATA array length.
                try:
                    encoded = value.encode('iso-8859-1')
                except UnicodeEncodeError as error:
                    raise ValueError('PLC STRING requires ISO-8859-1 text') from error
                if len(encoded) > capacity:
                    raise ValueError(f'Value exceeds the PLC STRING capacity of {capacity} bytes')

    def failed(self, error, now):
        self.error = str(error)
        self.failure_generation += 1
        if self.outage_started is None:
            self.outage_started = now
        self.failures += 1
        self.retry_at = now + min(30, 2 ** min(self.failures - 1, 5))
        self.close()

    def read(self, addresses, now=None, *, with_receipts=False):
        real_clock = now is None
        with self.lock:
            now = time.monotonic() if real_clock else now
            if self.client is None and now < self.retry_at:
                raise ConnectionError(self.error or 'Waiting for reconnect backoff')
            try:
                self.connect(now)
                results = []
                for start in range(0, len(addresses), 200):
                    batch = addresses[start:start + 200]
                    started = time.monotonic()
                    try:
                        returned = self.client.read(*batch)
                    finally:
                        received = time.monotonic()
                        self.timings.record('adapter_read', received - started)
                    acquired = received if real_clock else now
                    timestamp = utc_now() if with_receipts else None
                    returned = returned if isinstance(returned, list) else [returned]
                    if len(returned) != len(batch):
                        raise ConnectionError('PLC returned an incomplete tag batch')
                    for address, result in zip(batch, returned):
                        verify_result_address(address, result)
                        # A malformed slot still leaves the other batch positions intact.
                        value = result if hasattr(result, 'error') and hasattr(result, 'value') else None
                        results.append((value, acquired, timestamp) if with_receipts else value)
                    self.read_calls += 1
                    self.tags_read += len(batch)
                self.error, self.failures = None, 0
                return results
            except Exception as error:
                self.failed(error, time.monotonic() if real_clock else now)
                raise

    def write(self, address, value):
        with self.lock:
            if not self.client:
                raise ConnectionError('PLC is disconnected')
            try:
                result = self.client.write((address, value))
                verify_result_address(address, result)
                if result.error:
                    raise TagWriteError(f'PLC rejected write: {result.error}')
                actual = self.client.read(address)
                verify_result_address(address, actual)
                if type(value) is bool or type(actual.value) is bool:
                    matches = actual.value is value
                elif type(actual.value) is float and type(value) in (int, float):
                    matches = math.isclose(actual.value, value, rel_tol=1e-6, abs_tol=1e-7)
                else:
                    matches = actual.value == value
                if actual.error or not matches:
                    raise TagWriteError('PLC write readback did not match; command was not retried')
                return actual.value
            except TagWriteError:
                raise
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
        self._scan_pool = None
        self._scans = {}
        self._scan_started = {}
        self._closing = False
        self.connections, self.definitions, self.sources, self.samples = {}, {}, {}, {}
        self.address_aliases = {}
        self.project = None
        self._screen_demands = {}
        self.trend_demands = {}
        self.leases, self.deadlines, self.last_rates = {}, {}, {}
        self._refresh_after = {}
        self._demanded_aliases = set()
        self._lease_sequences = {}
        self.local_names = set()
        self.plc_hold = False

    def configure(self, project):
        with self.io_lock:
            project = deepcopy(project)
            screens = screen_map(project)
            screen_tags = {identifier: {} for identifier in screens}
            for control in expanded_controls(project):
                screen_tags[control['_screen']].update(dict.fromkeys(referenced_tags(control)))
            screen_demands = {identifier: (screen.get('update_ms', 500), tuple(screen_tags[identifier]))
                              for identifier, screen in screens.items()}
            retired = []
            with self.lock:
                configs = {config['id']: config for config in project.get('connections', []) if config['enabled'] and not self.plc_hold}
                changed_connections = {identifier for identifier, connection in self.connections.items() if configs.get(identifier) != connection.config}
                for identifier, connection in list(self.connections.items()):
                    if configs.get(identifier) != connection.config:
                        retired.append(connection)
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
                self.address_aliases = {}
                for alias, (root, member) in self.sources.items():
                    tag = self.definitions[root]
                    if tag['connection']:
                        key = (tag['connection'], tag['address'])
                        self.address_aliases.setdefault(key, []).append((alias, tag, member))
                self.project = project
                self._screen_demands = screen_demands
                self.deadlines.clear()
            for connection in retired:
                connection.close()

    def lease(self, client, screens, now=None, preview_root='', *, sequence=None):
        now = time.monotonic() if now is None else now
        screens = set(screens)
        with self.lock:
            if sequence is not None and sequence <= self._lease_sequences.get(client, 0):
                return
            if any(screen not in self._screen_demands for screen in screens):
                raise ValueError('Unknown subscription screen')
            if preview_root and (preview_root not in self.definitions or self.definitions[preview_root]['type'] != 'struct'):
                raise ValueError('Faceplate preview requires a configured UDT tag')
            self.leases.pop(client, None)
            self.leases = {key: value for key, value in self.leases.items() if value[1] > now}
            if screens or preview_root:
                self.leases[client] = (screens, now + 15, preview_root)
            if len(self.leases) > MAX_VIEWER_LEASES:
                self.leases.pop(next(iter(self.leases)))
            if sequence is not None:
                # Retain the latest sequence even after a viewer releases its lease.
                self._lease_sequences.pop(client, None)
                self._lease_sequences[client] = sequence
                if len(self._lease_sequences) > MAX_SUBSCRIPTION_SEQUENCES:
                    self._lease_sequences.pop(next(iter(self._lease_sequences)))

    def demands(self, now):
        rates = {}
        def demand(tag, rate):
            rates[tag] = min(rate, rates.get(tag, rate))
        project = self.project
        if not project:
            return rates
        wanted = set()
        for screens, expires_at, preview_root in self.leases.values():
            if expires_at > now:
                wanted.update(screens)
                if preview_root:
                    demand(preview_root, 500)
        for identifier in wanted & self._screen_demands.keys():
            rate, tags = self._screen_demands[identifier]
            for tag in tags:
                demand(tag, rate)
        for alarm in project.get('alarms', []):
            if alarm['enabled']:
                demand(alarm['tag'], 250)
        for tag, rate in self.trend_demands.items():
            demand(tag, rate)
        for history in project.get('historian', {}).get('tags', []):
            demand(history['tag'], history['sample_ms'])
        for command in project.get('commands', []):
            demand(command['root_tag'], command['update_ms'])
        return rates

    def _due_addresses(self, identifier, now):
        return [address for route, address in self.last_rates
                if route == identifier and now >= self.deadlines.get((route, address), 0)]

    def poll(self, now=None, *, wait=True):
        """Schedule at most one scan per route. Explicit callers can wait for completion."""
        real_clock = now is None
        now = time.monotonic() if real_clock else now
        with self.lock:
            if self._closing:
                return
            for identifier, future in list(self._scans.items()):
                if future.done():
                    del self._scans[identifier]
                    del self._scan_started[identifier]
                    try:
                        future.result()
                    except Exception:
                        logging.exception('PLC scan failed for route %s', identifier)

            grouped = {}
            demands = self.demands(now)
            self._demanded_aliases = set(demands)
            for alias, rate in demands.items():
                root, _ = self.sources.get(alias, (None, ''))
                tag = self.definitions.get(root)
                if tag and tag['connection']:
                    key = (tag['connection'], tag['address'])
                    grouped[key] = min(rate, grouped.get(key, rate))
            for key, previous_rate in self.last_rates.items():
                rate = grouped.get(key)
                if rate is None:
                    self.deadlines.pop(key, None)
                    self._refresh_after.pop(key, None)
                elif rate < previous_rate:
                    self.deadlines[key] = now
                    # Tighten the existing samples without letting slower demand revive them.
                    for alias, _, _ in self.address_aliases[key]:
                        sample = self.samples.get(alias)
                        if sample is not None:
                            sample['rate_ms'] = min(sample['rate_ms'], rate)
                elif rate > previous_rate and self.deadlines.get(key, now) > now:
                    # Only defer a scheduled read. Leave already-due refreshes intact.
                    alias = self.address_aliases[key][0][0]
                    sample = self.samples.get(alias)
                    if sample is not None:
                        interval = min(rate / 1000, freshness_seconds(sample['rate_ms']))
                        self.deadlines[key] = max(self.deadlines[key], sample['monotonic'] + interval)
            for key in grouped.keys() - self.last_rates.keys():
                self._refresh_after[key] = now
            self.last_rates = grouped

            for identifier, connection in self.connections.items():
                if identifier in self._scans:
                    continue
                reconnect = not connection.connected
                if reconnect and now < connection.retry_at:
                    continue
                if (not reconnect and connection.scan_generation == connection.failure_generation
                        and not self._due_addresses(identifier, now)):
                    continue
                if self._scan_pool is None:
                    self._scan_pool = ThreadPoolExecutor(max_workers=MAX_PLC_CONNECTIONS, thread_name_prefix='openhmi-plc')
                self._scans[identifier] = self._scan_pool.submit(
                    self._scan, identifier, connection, self.project,
                    None if real_clock else now, time.monotonic()
                )
                self._scan_started[identifier] = now
            scheduled = tuple(self._scans.values()) if wait else ()
        for future in scheduled:
            future.result()

    def _scan(self, identifier, connection, project, now, submitted_at):
        # Serialize reads, writes and publication for this route. Never hold the
        # runtime state lock across socket operations.
        worker_started = time.monotonic()
        with connection.lock:
            route_acquired = time.monotonic()
            with self.lock:
                if self._closing or self.project is not project:
                    return
                started = time.monotonic()
                scan_start = started if now is None else now
                if scan_start < connection.retry_at and not connection.connected:
                    return
                if not connection.connected or connection.scan_generation != connection.failure_generation:
                    # A disconnect may occur while queued, and an explicit read may reopen the route.
                    for key in list(self.deadlines):
                        if key[0] == identifier:
                            del self.deadlines[key]
                    connection.scan_generation = connection.failure_generation
                # Demand can change while this scan waits for a writer or a worker slot.
                due = self._due_addresses(identifier, scan_start)
                deadline = min((self.deadlines[(identifier, address)] for address in due
                                if (identifier, address) in self.deadlines), default=None)
            if not due:
                if connection.connected:
                    return
                # Metadata browsing is available even before a screen leases tags.
                try:
                    connection.connect(scan_start)
                except Exception as error:
                    connection.failed(error, time.monotonic() if now is None else now)
                return
            connection.timings.record('scan_queue', worker_started - submitted_at)
            connection.timings.record('route_lock_wait', route_acquired - worker_started)
            if deadline is not None:
                connection.timings.record('scan_lateness', scan_start - deadline)
            try:
                results = connection.read(due, now, with_receipts=True)
            except Exception:
                # A route failure invalidates its entire cache in sample_snapshot.
                return
            finally:
                finished = time.monotonic()
                connection.timings.record('scan', finished - started)
            scan_finished = finished if now is None else now
            with self.lock:
                if self._closing or self.project is not project:
                    return
                awaiting_usable = not connection.has_usable_sample or connection.outage_started is not None
                for address, (result, acquired, timestamp) in zip(due, results):
                    key = (identifier, address)
                    rate = self.last_rates.get(key)
                    if rate is None:
                        continue
                    refresh_after = self._refresh_after.get(key)
                    if refresh_after is not None:
                        # Discard a reply received before this address came back into demand.
                        if acquired < refresh_after:
                            continue
                        del self._refresh_after[key]
                    pending_deadline = self.deadlines.get(key)
                    # A sample received before a faster demand arrived cannot satisfy its refresh.
                    if pending_deadline is None or pending_deadline <= acquired:
                        self.deadlines[key] = scan_finished + rate / 1000
                    for alias, tag, member in self.address_aliases[key]:
                        try:
                            if result is None or result.error:
                                raise ValueError(result.error if result is not None else 'PLC adapter returned a malformed tag result')
                            value = member_value(result.value, member) if member else result.value
                            kind = tag['members'][member] if member else tag['type']
                            if not type_ok(value, kind):
                                raise ValueError('PLC value does not match configured type or browser numeric limits')
                            if not member and kind in ('number', 'integer'):
                                if tag['scale'] != 1 or tag['offset'] != 0:
                                    value = value * tag['scale'] + tag['offset']
                                elif kind == 'number':
                                    value = float(value)
                                if not math.isfinite(value):
                                    raise ValueError('Scaled PLC value is not finite')
                            sample = {'value': value, 'quality': 'good', 'error': None}
                        except (ValueError, KeyError, TypeError, IndexError) as failure:
                            sample = {'value': None, 'quality': 'bad', 'error': str(failure)}
                        self.samples[alias] = {
                            **sample, 'timestamp': timestamp, 'monotonic': acquired, 'rate_ms': rate,
                            'failure_generation': connection.failure_generation,
                        }
                        # One physical UDT read can populate aliases no consumer requested.
                        if (awaiting_usable and alias in self._demanded_aliases and sample['quality'] == 'good'
                                and scan_finished - acquired <= freshness_seconds(rate)):
                            connection.has_usable_sample = True
                            awaiting_usable = False
                            if connection.outage_started is not None:
                                connection.timings.record('recovery', scan_finished - connection.outage_started)
                                connection.outage_started = None

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
            held = {config['id'] for config in (self.project or {}).get('connections', [])
                    if self.plc_hold and config['enabled']}
            for alias, (root, _) in self.sources.items():
                tag = self.definitions[root]
                if not tag['connection']:
                    continue
                sample = deepcopy(self.samples.get(alias, {'value': None, 'quality': 'pending', 'timestamp': None, 'error': 'Waiting for PLC sample'}))
                connection = self.connections.get(tag['connection'])
                generation = sample.pop('failure_generation', 0)
                if connection is None:
                    reason = 'held' if tag['connection'] in held else 'disabled'
                    error = 'PLC acquisition is held' if reason == 'held' else 'Connection is disabled'
                    sample.update(value=None, quality='bad', quality_reason=reason, error=error)
                elif not connection.connected and connection.error is not None:
                    sample.update(value=None, quality='bad', quality_reason='disconnected', error=connection.error)
                elif alias in self.samples and generation != connection.failure_generation:
                    sample.update(value=None, quality='bad', quality_reason='recovering',
                                  error='Waiting for a fresh PLC sample after connection loss')
                elif (tag['connection'], tag['address']) in self._refresh_after:
                    sample.update(value=None, quality='pending', error='Waiting for a PLC sample for renewed demand')
                elif sample['quality'] == 'good' and now - sample['monotonic'] > freshness_seconds(sample['rate_ms']):
                    sample.update(quality='stale', error='PLC sample is stale')
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

    @contextmanager
    def write_scope(self, roots):
        """Keep scans out of the routes touched by a multi-step write."""
        with self.io_lock, ExitStack() as stack:
            routes = {self.definitions.get(root, {}).get('connection') for root in roots}
            for identifier in sorted(routes & self.connections.keys()):
                stack.enter_context(self.connections[identifier].lock)
            yield

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
            result = connection.read([tag['address']])[0]
            if result is None or result.error or not isinstance(result.value, dict):
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
                with connection.lock:
                    raw = value if member else (value - tag['offset']) / tag['scale'] if kind in ('number', 'integer') else value
                    if kind in ('number', 'integer') and not math.isfinite(raw):
                        raise ValueError('Inverse PLC scaling must produce a finite value')
                    if kind == 'integer':
                        if abs(raw) > MAX_SAFE_INTEGER:
                            raise ValueError('Inverse PLC scaling exceeds the browser-safe integer range')
                        if int(raw) != raw:
                            raise ValueError('Scaled integer writes must resolve to an integer')
                        raw = int(raw)
                    physical_address = tag['address'] + ('.' + member if member else '')
                    connection.validate_write(physical_address, raw)
                    try:
                        connection.write(physical_address, raw)
                    except TagWriteError as error:
                        with self.lock:
                            for key, aliases in self.address_aliases.items():
                                route, scan_address = key
                                if route != tag['connection'] or not overlapping_addresses(physical_address, scan_address):
                                    continue
                                self.deadlines.pop(key, None)
                                for alias, _, scan_member in aliases:
                                    alias_address = scan_address + ('.' + scan_member if scan_member else '')
                                    if alias in self.samples and overlapping_addresses(physical_address, alias_address):
                                        self.samples[alias].update(value=None, quality='bad', error=str(error))
                        raise
                    # A write readback verifies the transaction; normal polling owns displayed samples.
                    with self.lock:
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

    def status(self, *, include_timing=False, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            routes = []
            for identifier, connection in self.connections.items():
                scan = self._scans.get(identifier)
                age = max(0, now - self._scan_started[identifier]) if scan and not scan.done() else None
                groups = {}
                for (route, address), rate in self.last_rates.items():
                    if route == identifier:
                        groups.setdefault(rate, []).append(address)
                active = connection.connected and bool(groups)
                recovering = active and connection.outage_started is not None
                routes.append({'id': identifier, 'connected': connection.connected, 'error': connection.error,
                               'connection_instance': connection.instance,
                               'scan_age_seconds': age,
                               'recovering': recovering,
                               'awaiting_data': active and not recovering and not connection.has_usable_sample,
                               'scan_overdue': age is not None and age >= max(5, connection.config['timeout_seconds']),
                               'read_calls': connection.read_calls, 'tags_read': connection.tags_read,
                               'groups': [{'rate_ms': rate, 'addresses': sorted(addresses)} for rate, addresses in sorted(groups.items())],
                               **({'timings': connection.timings.snapshot(), 'route_failures': connection.failure_generation} if include_timing else {})})
            return routes

    def close(self):
        with self.io_lock:
            with self.lock:
                self._closing = True
                pool = self._scan_pool
            try:
                if pool is not None:
                    pool.shutdown(wait=True, cancel_futures=True)
                for connection in self.connections.values():
                    connection.close()
            finally:
                with self.lock:
                    self._scans.clear()
                    self._scan_started.clear()
                    self.samples.clear()
                    self.deadlines.clear()
                    self._refresh_after.clear()
                    self._scan_pool = None
                    self._closing = False
