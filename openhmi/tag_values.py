"""Pure value/type/freshness rules shared by acquisition and sample consumers."""

import math
import re

MAX_SAFE_INTEGER = 2 ** 53 - 1


def overlapping_addresses(first, second):
    first, second = first.casefold(), second.casefold()
    return (first == second or first.startswith((second + '.', second + '['))
            or second.startswith((first + '.', first + '[')))


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
