"""Pure logical write checks, inverse scaling and readback comparison.

Transport owns metadata limits and socket operations. These rules neither mutate
cached samples nor perform I/O, acquire locks or retry a write.
"""
import math
from .tag_values import MAX_SAFE_INTEGER, type_ok


def validate_logical_write(tag, member, values):
    kind = tag['members'][member] if member else tag['type']
    write_kind = 'number' if kind == 'integer' and not member and (tag['scale'] != 1 or tag['offset'] != 0) else kind
    if not tag['writable'] or len(values) != 1 or not type_ok(values[0], write_kind) or kind == 'struct':
        raise ValueError('Tag is read-only or write type is incompatible')
    return kind, values[0]


def prepare_physical_write(tag, member, kind, value):
    raw = value if member else (value - tag['offset']) / tag['scale'] if kind in ('number', 'integer') else value
    if kind in ('number', 'integer') and not math.isfinite(raw):
        raise ValueError('Inverse PLC scaling must produce a finite value')
    if kind == 'integer':
        if abs(raw) > MAX_SAFE_INTEGER:
            raise ValueError('Inverse PLC scaling exceeds the browser-safe integer range')
        if int(raw) != raw:
            raise ValueError('Scaled integer writes must resolve to an integer')
        raw = int(raw)
    return tag['address'] + ('.' + member if member else ''), raw


def readback_matches(value, actual):
    if type(value) is bool or type(actual) is bool:
        return actual is value
    if type(actual) is float and type(value) in (int, float):
        return math.isclose(actual, value, rel_tol=1e-6, abs_tol=1e-7)
    return actual == value
