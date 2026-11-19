"""Runtime tag scheduling, shared scan demand and cached sample management."""

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from copy import deepcopy
import logging
import math
import re
from threading import RLock
import time

from .drivers import SimulatorDriver
from .runtime_models import MAX_PLC_CONNECTIONS
from .screens import screen_map, expanded_controls, referenced_tags
from .alarms import utc_now


# Retain these imports as compatibility exports for existing driver consumers.
from .tag_values import MAX_SAFE_INTEGER, freshness_seconds, member_value, browser_value_ok, type_ok
from .scan_timings import ScanTimings
from .logix_transport import (LogixConnection, TagWriteError, REAL_MAX, PLC_INTEGER_LIMITS,
                              overlapping_addresses, verify_result_address)

MAX_VIEWER_LEASES = 1000
MAX_SUBSCRIPTION_SEQUENCES = 2 * MAX_VIEWER_LEASES
BAD_TAG_RETRY_SECONDS = 30


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
        self._bad_tag_retry_at = {}
        self._demanded_aliases = {}
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
                self._bad_tag_retry_at.clear()
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
        due = {address: self.deadlines.get((route, address), 0) for route, address in self.last_rates
               if route == identifier and now >= self.deadlines.get((route, address), 0)}
        if not self._bad_tag_retry_at or not any((identifier, address) in self._bad_tag_retry_at for address in due):
            return due
        connection = self.connections[identifier]
        if not self._has_usable_data(identifier, connection.failure_generation, now):
            return due
        effective = {address: max(deadline, self._bad_tag_retry_at.get((identifier, address), 0))
                     for address, deadline in due.items()}
        return {address: deadline for address, deadline in effective.items() if now >= deadline}

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
            demanded_aliases = defaultdict(dict)
            for alias, rate in self.demands(now).items():
                root, _ = self.sources.get(alias, (None, ''))
                tag = self.definitions.get(root)
                if tag and tag['connection']:
                    key = (tag['connection'], tag['address'])
                    grouped[key] = min(rate, grouped.get(key, rate))
                    demanded_aliases[tag['connection']][alias] = key
                    if alias not in self._demanded_aliases.get(tag['connection'], {}):
                        self._bad_tag_retry_at.pop(key, None)
            for key, previous_rate in self.last_rates.items():
                rate = grouped.get(key)
                if rate is None:
                    self.deadlines.pop(key, None)
                    self._refresh_after.pop(key, None)
                    self._bad_tag_retry_at.pop(key, None)
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
            self._demanded_aliases = demanded_aliases

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
                    for schedule in (self.deadlines, self._bad_tag_retry_at):
                        for key in list(schedule):
                            if key[0] == identifier:
                                del schedule[key]
                    connection.scan_generation = connection.failure_generation
                # Demand can change while this scan waits for a writer or a worker slot.
                due = self._due_addresses(identifier, scan_start)
                deadline = min((deadline for address, deadline in due.items()
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
                results = connection.read(list(due), now, with_receipts=True)
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
                demanded_aliases = self._demanded_aliases.get(identifier, {})
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
                    usable_address = False
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
                        if alias in demanded_aliases and sample['quality'] == 'good':
                            usable_address = True
                            if awaiting_usable and scan_finished - acquired <= freshness_seconds(rate):
                                connection.has_usable_sample = True
                                awaiting_usable = False
                                if connection.outage_started is not None:
                                    connection.timings.record('recovery', scan_finished - connection.outage_started)
                                    connection.outage_started = None
                    if usable_address:
                        self._bad_tag_retry_at.pop(key, None)
                    else:
                        self._bad_tag_retry_at[key] = scan_finished + BAD_TAG_RETRY_SECONDS

    def sample_snapshot(self, now=None, *, include_values=True):
        now = time.monotonic() if now is None else now
        with self.lock:
            result = {}
            for name, value in self._tags.items():
                sample = {'quality': 'good', 'timestamp': utc_now(), 'error': None}
                if include_values:
                    sample['value'] = deepcopy(value)
                elif name not in self.definitions:
                    sample['value_type'] = type(value).__name__
                result[name] = sample
            for name, tag in self.definitions.items():
                if not tag['connection']:
                    for member in tag['members']:
                        try:
                            value = member_value(self._tags[name], member)
                            sample = result[name].copy()
                        except (KeyError, TypeError, IndexError):
                            value = None
                            sample = {'quality': 'bad', 'timestamp': utc_now(), 'error': 'Missing UDT member'}
                        if include_values:
                            sample['value'] = value
                        result[f'{name}.{member}'] = sample
            held = {config['id'] for config in (self.project or {}).get('connections', [])
                    if self.plc_hold and config['enabled']}
            for alias, (root, _) in self.sources.items():
                tag = self.definitions[root]
                if not tag['connection']:
                    continue
                cached = self.samples.get(alias)
                sample = cached.copy() if cached is not None else {
                    'value': None, 'quality': 'pending', 'timestamp': None, 'error': 'Waiting for PLC sample',
                }
                connection = self.connections.get(tag['connection'])
                generation = sample.pop('failure_generation', 0)
                if connection is None:
                    reason = 'held' if tag['connection'] in held else 'disabled'
                    error = 'PLC acquisition is held' if reason == 'held' else 'Connection is disabled'
                    sample.update(value=None, quality='bad', quality_reason=reason, error=error)
                elif not connection.connected and connection.error is not None:
                    sample.update(value=None, quality='bad', quality_reason='disconnected', error=connection.error)
                elif cached is not None and generation != connection.failure_generation:
                    sample.update(value=None, quality='bad', quality_reason='recovering',
                                  error='Waiting for a fresh PLC sample after connection loss')
                elif (tag['connection'], tag['address']) in self._refresh_after:
                    sample.update(value=None, quality='pending', error='Waiting for a PLC sample for renewed demand')
                elif sample['quality'] == 'good' and now - sample['monotonic'] > freshness_seconds(sample['rate_ms']):
                    sample.update(quality='stale', error='PLC sample is stale')
                sample.pop('monotonic', None)
                if cached is not None:
                    sample['age_seconds'] = max(0, now - cached['monotonic'])
                if include_values:
                    sample['value'] = deepcopy(sample['value'])
                else:
                    sample.pop('value', None)
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
                        key = (tag['connection'], tag['address'])
                        self.deadlines.pop(key, None)
                        self._bad_tag_retry_at.pop(key, None)
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

    def _has_usable_data(self, identifier, generation, now):
        for alias, key in self._demanded_aliases.get(identifier, {}).items():
            sample = self.samples.get(alias)
            if (sample is not None and sample['quality'] == 'good' and key not in self._refresh_after
                    and sample.get('failure_generation', 0) == generation
                    and now - sample['monotonic'] <= freshness_seconds(sample['rate_ms'])):
                return True
        return False

    def status(self, *, include_timing=False, include_groups=True, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            routes = []
            for identifier, connection in self.connections.items():
                scan = self._scans.get(identifier)
                age = max(0, now - self._scan_started[identifier]) if scan and not scan.done() else None
                groups = {}
                if include_groups:
                    for (route, address), rate in self.last_rates.items():
                        if route == identifier:
                            groups.setdefault(rate, []).append(address)
                active = connection.connected and bool(self._demanded_aliases.get(identifier))
                recovering = active and connection.outage_started is not None
                routes.append({'id': identifier, 'connected': connection.connected, 'error': connection.error,
                               'connection_instance': connection.instance,
                               'scan_age_seconds': age,
                               'recovering': recovering,
                               'awaiting_data': active and not recovering and not connection.has_usable_sample,
                               'data_unavailable': (active and not recovering and connection.has_usable_sample
                                                    and not self._has_usable_data(identifier, connection.failure_generation, now)),
                               'scan_overdue': age is not None and age >= max(5, connection.config['timeout_seconds']),
                               'read_calls': connection.read_calls, 'tags_read': connection.tags_read,
                               **({'groups': [{'rate_ms': rate, 'addresses': sorted(addresses)}
                                              for rate, addresses in sorted(groups.items())]} if include_groups else {}),
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
                    self._bad_tag_retry_at.clear()
                    self._scan_pool = None
                    self._closing = False
