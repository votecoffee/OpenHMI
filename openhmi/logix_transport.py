"""pycomm3 connection, metadata, batched requests and verified writes.

This layer owns session recovery and transport receipts. It does not select
screen demand, schedule tags, publish sample quality or replay failed writes.
"""

import math
import re
from threading import RLock
import time
from uuid import uuid4

from .alarms import utc_now
from .scan_timings import ScanTimings


REAL_MAX = float.fromhex('0x1.fffffep+127')
PLC_INTEGER_LIMITS = {
    'SINT': (-2 ** 7, 2 ** 7 - 1), 'USINT': (0, 2 ** 8 - 1),
    'INT': (-2 ** 15, 2 ** 15 - 1), 'UINT': (0, 2 ** 16 - 1),
    'DINT': (-2 ** 31, 2 ** 31 - 1), 'UDINT': (0, 2 ** 32 - 1),
    'LINT': (-2 ** 63, 2 ** 63 - 1), 'ULINT': (0, 2 ** 64 - 1),
}


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
