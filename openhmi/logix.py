"""Coordinate subscriptions, route scan workers, writes and sample publication."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from copy import deepcopy
import logging
import re
from threading import RLock
import time

from .drivers import SimulatorDriver
from .runtime_models import MAX_PLC_CONNECTIONS
from .tag_subscriptions import (TagSubscriptions, build_screen_demands,
                                 MAX_VIEWER_LEASES, MAX_SUBSCRIPTION_SEQUENCES)
from .tag_samples import SampleCache
from .tag_scheduling import ScanSchedule, BAD_TAG_RETRY_SECONDS
from .scan_publication import publish_scan_receipts
from .tag_writes import validate_logical_write, prepare_physical_write
from .alarms import utc_now


# Retain these imports as compatibility exports for existing driver consumers.
from .tag_values import MAX_SAFE_INTEGER, freshness_seconds, member_value, browser_value_ok, type_ok
from .scan_timings import ScanTimings
from .logix_transport import (LogixConnection, TagWriteError, REAL_MAX, PLC_INTEGER_LIMITS,
                              overlapping_addresses, verify_result_address)

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
        self.connections, self.definitions, self.sources = {}, {}, {}
        self.subscriptions = TagSubscriptions()
        self.sample_cache = SampleCache()
        self.schedule = ScanSchedule()
        self.address_aliases = {}
        self.project = None
        self.local_names = set()
        self.plc_hold = False

    # Compatibility views are live component-owned dictionaries, not copies.
    @property
    def samples(self):
        return self.sample_cache.samples

    @samples.setter
    def samples(self, value):
        self.sample_cache.samples = value

    @property
    def leases(self):
        return self.subscriptions.leases

    @leases.setter
    def leases(self, value):
        self.subscriptions.leases = value

    @property
    def trend_demands(self):
        return self.subscriptions.trend_demands

    @trend_demands.setter
    def trend_demands(self, value):
        self.subscriptions.trend_demands = value

    @property
    def _screen_demands(self):
        return self.subscriptions.screen_demands

    @_screen_demands.setter
    def _screen_demands(self, value):
        self.subscriptions.screen_demands = value

    @property
    def _lease_sequences(self):
        return self.subscriptions.sequences

    @_lease_sequences.setter
    def _lease_sequences(self, value):
        self.subscriptions.sequences = value

    @property
    def deadlines(self):
        return self.schedule.deadlines

    @deadlines.setter
    def deadlines(self, value):
        self.schedule.deadlines = value

    @property
    def last_rates(self):
        return self.schedule.rates

    @last_rates.setter
    def last_rates(self, value):
        self.schedule.rates = value

    @property
    def _refresh_after(self):
        return self.schedule.refresh_after

    @_refresh_after.setter
    def _refresh_after(self, value):
        self.schedule.refresh_after = value

    @property
    def _bad_tag_retry_at(self):
        return self.schedule.bad_retry_at

    @_bad_tag_retry_at.setter
    def _bad_tag_retry_at(self, value):
        self.schedule.bad_retry_at = value

    @property
    def _demanded_aliases(self):
        return self.schedule.demanded_aliases

    @_demanded_aliases.setter
    def _demanded_aliases(self, value):
        self.schedule.demanded_aliases = value

    def configure(self, project):
        with self.io_lock:
            project = deepcopy(project)
            screen_demands = build_screen_demands(project)
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
            return self.subscriptions.lease(client, screens, self.definitions, now,
                                             preview_root, sequence=sequence)

    def demands(self, now):
        # Poll holds self.lock; standalone callers retain the existing contract.
        return self.subscriptions.demands(now, self.project)

    def _due_addresses(self, identifier, now):
        return self.schedule.due_addresses(identifier, now, lambda: self._has_usable_data(
            identifier, self.connections[identifier].failure_generation, now))

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

            self.schedule.reconcile(self.demands(now), now, self.sources, self.definitions,
                                    self.address_aliases, self.sample_cache)

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
                    self.schedule.reset_route(identifier)
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
                publish_scan_receipts(identifier, connection, due, results, scan_finished,
                    schedule=self.schedule, sample_cache=self.sample_cache, address_aliases=self.address_aliases)

    def sample_snapshot(self, now=None, *, include_values=True):
        now = time.monotonic() if now is None else now
        with self.lock:
            return self.sample_cache.snapshot(
                now, local_values=self._tags, definitions=self.definitions, sources=self.sources,
                connections=self.connections, project=self.project, plc_hold=self.plc_hold,
                refresh_after=self._refresh_after, include_values=include_values, timestamp=utc_now,
            )

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
            kind, value = validate_logical_write(tag, member, values)
            if tag['connection']:
                connection = self.connections.get(tag['connection'])
                if not connection:
                    raise ConnectionError('PLC connection is disabled')
                with connection.lock:
                    physical_address, raw = prepare_physical_write(tag, member, kind, value)
                    connection.validate_write(physical_address, raw)
                    try:
                        connection.write(physical_address, raw)
                    except TagWriteError as error:
                        with self.lock:
                            self.schedule.write_failed(tag['connection'], physical_address, error,
                                                       self.address_aliases, self.sample_cache)
                        raise
                    # A write readback verifies the transaction; normal polling owns displayed samples.
                    with self.lock:
                        self.schedule.write_verified((tag['connection'], tag['address']))
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
        return self.sample_cache.has_usable_data(identifier, generation, now,
                                                 self._demanded_aliases, self._refresh_after)

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
