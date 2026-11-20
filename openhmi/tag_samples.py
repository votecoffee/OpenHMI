"""Cached sample values and quality projection; caller holds the runtime state lock.

Transport generations, demand refresh fences and clocks are supplied by the
coordinator. This cache never acquires a route lock or schedules controller I/O.
"""

from copy import deepcopy
import math
from .tag_values import freshness_seconds, member_value, type_ok, overlapping_addresses


class SampleCache:
    def __init__(self):
        self.samples = {}

    def timing(self, alias):
        sample = self.samples.get(alias)
        return None if sample is None else (sample['rate_ms'], sample['monotonic'])

    def tighten_rate(self, alias, rate):
        sample = self.samples.get(alias)
        if sample is not None:
            sample['rate_ms'] = min(sample['rate_ms'], rate)

    def publish(self, alias, sample, timestamp, acquired, rate, generation):
        self.samples[alias] = {
            **sample, 'timestamp': timestamp, 'monotonic': acquired, 'rate_ms': rate,
            'failure_generation': generation,
        }

    def invalidate_write(self, physical_address, scan_address, aliases, error):
        for alias, _, scan_member in aliases:
            alias_address = scan_address + ('.' + scan_member if scan_member else '')
            if alias in self.samples and overlapping_addresses(physical_address, alias_address):
                self.samples[alias].update(value=None, quality='bad', error=str(error))

    @staticmethod
    def decode(result, tag, member):
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
        return sample

    def snapshot(self, now, *, local_values, definitions, sources, connections,
                 project, plc_hold, refresh_after, include_values, timestamp):
        result = {}
        for name, value in local_values.items():
            sample = {'quality': 'good', 'timestamp': timestamp(), 'error': None}
            if include_values:
                sample['value'] = deepcopy(value)
            elif name not in definitions:
                sample['value_type'] = type(value).__name__
            result[name] = sample
        for name, tag in definitions.items():
            if not tag['connection']:
                for member in tag['members']:
                    try:
                        value = member_value(local_values[name], member)
                        sample = result[name].copy()
                    except (KeyError, TypeError, IndexError):
                        value = None
                        sample = {'quality': 'bad', 'timestamp': timestamp(), 'error': 'Missing UDT member'}
                    if include_values:
                        sample['value'] = value
                    result[f'{name}.{member}'] = sample
        held = {config['id'] for config in (project or {}).get('connections', [])
                if plc_hold and config['enabled']}
        for alias, (root, _) in sources.items():
            tag = definitions[root]
            if not tag['connection']:
                continue
            cached = self.samples.get(alias)
            sample = cached.copy() if cached is not None else {
                'value': None, 'quality': 'pending', 'timestamp': None, 'error': 'Waiting for PLC sample',
            }
            connection = connections.get(tag['connection'])
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
            elif (tag['connection'], tag['address']) in refresh_after:
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


    def has_usable_data(self, identifier, generation, now, demanded_aliases, refresh_after):
        for alias, key in demanded_aliases.get(identifier, {}).items():
            sample = self.samples.get(alias)
            if (sample is not None and sample['quality'] == 'good' and key not in refresh_after
                    and sample.get('failure_generation', 0) == generation
                    and now - sample['monotonic'] <= freshness_seconds(sample['rate_ms'])):
                return True
        return False
