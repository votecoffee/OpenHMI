"""Compare two OpenHMI diagnostic exports from a steady read-only bench run."""

import argparse
import json
import math
from pathlib import Path

COUNTERS = {'read_calls': 'pycomm3_read_calls', 'tags_read': 'requested_addresses'}


def compare(before, after, identifier):
    first, last = before['capture'], after['capture']
    if not first['project_instance'] or first['project_instance'] != last['project_instance']:
        raise ValueError('Use exports from the same open project and runtime session.')
    elapsed = last['monotonic_seconds'] - first['monotonic_seconds']
    if not math.isfinite(elapsed) or elapsed <= 0:
        raise ValueError('The second export must be later than the first.')

    def connection(data):
        matches = [item for item in data['connections'] if item['id'] == identifier]
        if len(matches) != 1:
            raise ValueError(f'Connection {identifier!r} must appear once in each export.')
        item = matches[0]
        if item['state'] != 'connected' or not item['connection_instance']:
            raise ValueError(f'Connection {identifier!r} must be connected at both endpoints.')
        return item

    start, finish = connection(before), connection(after)
    if start['connection_instance'] != finish['connection_instance'] or start['path'] != finish['path']:
        raise ValueError('The connection was replaced between exports. Start a new measurement.')
    if 'route_failures' in start and 'route_failures' in finish and start['route_failures'] != finish['route_failures']:
        raise ValueError('The route reported a failure between exports. Start a new steady measurement.')
    if start['groups'] != finish['groups']:
        raise ValueError('Scan groups differ. Keep screen demand and configuration fixed for the measurement.')

    totals = {}
    for key, label in COUNTERS.items():
        earlier, later = start[key], finish[key]
        if type(earlier) is not int or type(later) is not int or not 0 <= earlier <= later:
            raise ValueError(f'Invalid or reset counter: {key}')
        totals[label] = {'delta': later - earlier, 'per_second': round((later - earlier) / elapsed, 3)}

    return {'connection': identifier, 'started_utc': first['utc'], 'finished_utc': last['utc'],
            'elapsed_seconds': round(elapsed, 3), 'scan_groups': finish['groups'], 'counters': totals,
            'scope': 'HMI pycomm3 calls and requested addresses; controller load and wire packets are separate measurements.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('before', type=Path)
    parser.add_argument('after', type=Path)
    parser.add_argument('--connection', required=True, help='Connection ID from Diagnostics')
    parser.add_argument('--output', type=Path, help='New JSON report path; defaults to stdout')
    args = parser.parse_args()
    try:
        before, after = (json.loads(path.read_text(encoding='utf-8-sig')) for path in (args.before, args.after))
        result = json.dumps(compare(before, after, args.connection), indent=2, allow_nan=False)
        if args.output:
            with args.output.open('x', encoding='utf-8') as output:
                output.write(result + '\n')
        else:
            print(result)
    except (OSError, KeyError, TypeError, ValueError) as error:
        parser.exit(1, f'OpenHMI diagnostics: {error}\n')


if __name__ == '__main__':
    main()
