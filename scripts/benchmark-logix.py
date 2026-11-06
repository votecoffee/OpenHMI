"""Measure the Logix scheduler with a synthetic adapter that cannot use a network."""

import argparse
import json
from pathlib import Path
import platform
import time
from types import SimpleNamespace

from openhmi.logix import RuntimeDriver, ScanTimings
from openhmi.projects import Project, default_project


DELAYS = {'primary': 0.003, 'secondary': 0.080}
TICK_SECONDS = 0.05
STEADY_SECONDS = 8
RECOVERY_SECONDS = 4


def fixture(routes):
    project = default_project().model_dump()
    for key in ('controls', 'tags', 'alarms'):
        project[key] = []
    project['screens'] = [
        {'id': 'summary', 'title': 'Overview', 'update_ms': 500, 'controls': []},
        {'id': 'detail', 'title': 'Detail', 'update_ms': 100, 'controls': []},
    ]
    values, probes = {}, {}
    for route in routes:
        project['connections'].append({'id': route, 'name': route, 'path': route, 'enabled': True})
        values[route] = {}

        def tag(name, address, kind, value, **settings):
            name = f'{route}_{name}'
            project['tags'].append({'name': name, 'connection': route, 'address': address,
                                    'type': kind, **settings})
            values[route][address] = value
            return name

        def display(screen, alias, kind='numeric'):
            controls = project['screens'][screen]['controls']
            controls.append({'id': f'control-{len(controls)}', 'label': alias, 'kind': kind, 'tag': alias})

        for index in range(24):
            level = tag(f'Level{index}', f'Level{index}', 'number', float(index))
            display(0, level)
        level_alias = tag('DetailLevel', 'Level0', 'number', 0.0)
        motor = tag('Motor', 'Motor', 'struct', {'Speed': 42.0, 'Running': True},
                    members={'Speed': 'number', 'Running': 'boolean'})
        item = tag('IndexedLevel', 'Samples[3]', 'number', 18.0)
        alarm = tag('Alarm', 'Alarm', 'boolean', False)
        history = tag('History', 'History', 'number', 21.0)
        project['alarms'].append({'id': f'{route}-alarm', 'tag': alarm, 'message': 'Synthetic alarm'})
        project['historian']['tags'].append({'tag': history, 'sample_ms': 400})
        display(0, motor + '.Running', 'indicator')
        for alias in (level_alias, motor + '.Speed', item):
            display(1, alias)
        probes[route] = [level_alias, f'{route}_Level23', motor + '.Speed', item, alarm, history]

    return Project.model_validate(project).model_dump(), values, probes


class SyntheticAdapter:
    def __init__(self, route, values, metrics, disconnect):
        self.route, self.values = route, values
        self.metrics, self.disconnect = metrics, disconnect
        self.tags = {}

    def open(self):
        return True

    def close(self):
        pass

    def read(self, *addresses):
        if len(addresses) != len(set(addresses)):
            raise AssertionError('Duplicate address in an adapter read')
        started = time.monotonic()
        try:
            time.sleep(DELAYS[self.route])
            if self.route in self.disconnect:
                self.disconnect.remove(self.route)
                raise ConnectionError('Injected adapter disconnect')
            results = [SimpleNamespace(value=self.values[address], error=None) for address in addresses]
            return results[0] if len(results) == 1 else results
        finally:
            self.metrics.record('adapter_read', time.monotonic() - started)


def phase(driver, probes, seconds):
    timings = {route: ScanTimings() for route in probes}
    scheduler = ScanTimings()
    quality = {alias: {} for aliases in probes.values() for alias in aliases}
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        started = time.monotonic()
        driver.poll(wait=False)
        scheduler.record('poll_dispatch', time.monotonic() - started)
        samples = driver.sample_snapshot()
        for route, aliases in probes.items():
            for alias in aliases:
                sample = samples[alias]
                state = sample['quality']
                counts = quality[alias]
                counts[state] = counts.get(state, 0) + 1
                if state == 'good':
                    timings[route].record(alias, sample['age_seconds'])
        time.sleep(max(0, TICK_SECONDS - (time.monotonic() - started)))
    return {'good_sample_age': {route: timing.snapshot() for route, timing in timings.items()},
            'quality_observations': quality, 'scheduler': scheduler.snapshot()}


def scenario(routes):
    project, values, probes = fixture(routes)
    adapter_metrics = {route: ScanTimings() for route in routes}
    disconnect = set()

    def client(path, **_):
        return SyntheticAdapter(path, values[path], adapter_metrics[path], disconnect)

    driver = RuntimeDriver(client)
    try:
        driver.configure(project)
        driver.lease('overview-viewer', ['summary'])
        driver.lease('detail-viewer', ['detail'])
        driver.poll()  # Warm connection metadata and the first samples.
        steady = phase(driver, probes, STEADY_SECONDS)
        steady_routes = driver.status(include_timing=True)
        expected_groups = {100: {'Level0', 'Motor', 'Samples[3]'}, 250: {'Alarm'},
                           400: {'History'}, 500: {f'Level{i}' for i in range(1, 24)}}
        for route in steady_routes:
            groups = {group['rate_ms']: set(group['addresses']) for group in route['groups']}
            if groups != expected_groups or route['route_failures']:
                raise RuntimeError(f"Unexpected steady scan groups or errors on {route['id']}")
        if any(set(counts) != {'good'} for counts in steady['quality_observations'].values()):
            raise RuntimeError('Steady scan did not retain good quality')
        result = {'steady': steady, 'steady_routes': steady_routes,
                  'steady_adapter_timing': {route: timing.snapshot() for route, timing in adapter_metrics.items()}}
        if 'secondary' in routes:
            disconnect.add('secondary')
            result['disconnect'] = phase(driver, probes, RECOVERY_SECONDS)
            result['after_disconnect_routes'] = driver.status(include_timing=True)
            primary, secondary = result['after_disconnect_routes']
            if (primary['route_failures'] or secondary['route_failures'] != 1
                    or not secondary['connected'] or 'recovery' not in secondary['timings']):
                raise RuntimeError('Expected one secondary route loss followed by recovery')
            observed = result['disconnect']['quality_observations']
            if any(set(observed[alias]) != {'good'} for alias in probes['primary']):
                raise RuntimeError('Secondary route loss affected primary sample quality')
            if any('bad' not in observed[alias] for alias in probes['secondary']):
                raise RuntimeError('Did not observe bad quality during secondary route loss')
        return result
    finally:
        driver.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New path for the JSON report')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Choose a new report path')
    result = {
        'scope': 'Synthetic adapter calls and requested addresses, with zero PLC wire traffic',
        'python': platform.python_version(), 'platform': platform.platform(),
        'tick_seconds': TICK_SECONDS, 'steady_seconds': STEADY_SECONDS,
        'recovery_seconds': RECOVERY_SECONDS, 'adapter_delay_seconds': DELAYS,
        'single_route': scenario(('primary',)),
        'two_routes': scenario(('primary', 'secondary')),
    }
    with args.output.open('x', encoding='utf-8') as report:
        json.dump(result, report, indent=2)
        report.write('\n')
    print(f'Wrote {args.output}')


if __name__ == '__main__':
    main()
