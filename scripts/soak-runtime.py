"""Run a repeatable offline fault and operator-load rehearsal on a new project."""

import argparse
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
import math
from pathlib import Path
import platform
from threading import Lock
import time
import tracemalloc
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from openhmi.logix import RuntimeDriver
from openhmi.projects import Project, ProjectStore, default_project
from openhmi.server import create_app

ROUTES = {'healthy': 'offline-healthy/0', 'fault': 'offline-fault/0'}
MEMBERS = {name: 'integer' for name in ('RequestSequence', 'AcceptedSequence', 'CompletedSequence', 'ResultCode')}
MEMBERS['Permit'] = 'boolean'


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def project_fixture():
    project = default_project().model_dump()
    project.update(title='OpenHMI offline reliability fixture', update_ms=100)
    for route, path in ROUTES.items():
        tag = route.title() + 'Level'
        project['connections'].append({'id': route, 'name': tag, 'path': path, 'enabled': True})
        project['tags'].append({'name': tag, 'type': 'number', 'connection': route, 'address': 'Level'})
        project['controls'].append({'id': route, 'kind': 'numeric', 'label': tag, 'tag': tag})
    project['historian']['tags'] = [{'tag': 'HealthyLevel', 'sample_ms': 100, 'deadband': 0}]
    project['tags'].append({'name': 'SoakCommand', 'type': 'struct', 'connection': 'healthy',
                            'address': 'Cycle', 'writable': True, 'members': MEMBERS})
    project['commands'].append({'id': 'soak', 'name': 'Synthetic command', 'root_tag': 'SoakCommand',
                                'permit_member': 'Permit', 'update_ms': 100, 'timeout_seconds': 15.0})
    project['controls'].append({'id': 'soak', 'kind': 'button', 'label': 'Synthetic command',
                                'mode': 'command', 'command': 'soak'})
    return Project.model_validate(project)


class OfflinePlant:
    def __init__(self):
        self.lock = Lock()
        self.fault = None
        self.writes = 0
        self.cycle = {name: True if kind == 'boolean' else 0 for name, kind in MEMBERS.items()}
        self.levels = dict.fromkeys(ROUTES, 0)

    def client(self, path, **_):
        route = next((route for route, allowed in ROUTES.items() if path == allowed), None)
        require(route is not None, 'Offline fixture rejected an unknown route')
        return OfflineClient(self, route)

    def finish_command(self, sequence):
        with self.lock:
            self.cycle.update(AcceptedSequence=sequence, CompletedSequence=sequence)


class OfflineClient:
    def __init__(self, plant, route):
        self.plant, self.route = plant, route
        self.tags = {'Level': {'data_type': 'REAL', 'external_access': 'Read Only'}}
        if route == 'healthy':
            self.tags['Cycle'] = {'external_access': 'Read/Write', 'data_type': {
                'name': 'Command', 'attributes': list(MEMBERS),
                'internal_tags': {name: {'data_type': 'BOOL' if kind == 'boolean' else 'DINT'}
                                  for name, kind in MEMBERS.items()},
            }}

    def open(self):
        return True

    def close(self):
        pass

    def read(self, *addresses):
        with self.plant.lock:
            fault = self.plant.fault if self.route == 'fault' else None
            self.plant.levels[self.route] += 1
            level = self.plant.levels[self.route] % 100
            cycle = dict(self.plant.cycle)
        if fault:
            time.sleep(0.3)
            if fault == 'disconnect':
                raise ConnectionError('Injected PLC route loss')
            return []  # Malformed short batch.
        values = {'Level': float(level), 'Cycle': cycle, 'Cycle.RequestSequence': cycle['RequestSequence']}
        results = [SimpleNamespace(value=values[address], error=None) for address in addresses]
        return results[0] if len(results) == 1 else results

    def write(self, pair):
        address, sequence = pair
        require(self.route == 'healthy' and address == 'Cycle.RequestSequence', 'Unexpected synthetic write target')
        with self.plant.lock:
            self.plant.writes += 1
            self.plant.cycle['RequestSequence'] = sequence
        return SimpleNamespace(error=None)


class RequestTiming:
    def __init__(self, limit_ms):
        self.limit_ms = limit_ms
        self.recent = deque(maxlen=4096)
        self.count = self.over_limit = 0
        self.max_ms = 0

    def record(self, elapsed):
        self.recent.append(elapsed)
        self.count += 1
        self.over_limit += elapsed > self.limit_ms
        self.max_ms = max(self.max_ms, elapsed)

    def snapshot(self):
        ordered = sorted(self.recent)
        return {'count': self.count, 'over_limit': self.over_limit, 'limit_ms': self.limit_ms,
                'max_ms': round(self.max_ms, 3), 'recent_count': len(ordered),
                'recent_p95_ms': round(ordered[math.ceil(len(ordered) * .95) - 1], 3),
                'p95_within_limit': self.count - self.over_limit >= math.ceil(self.count * .95)}


class Load:
    def __init__(self, client, pool, viewers, latencies):
        self.client, self.pool, self.viewers, self.latencies = client, pool, viewers, latencies
        self.next_lease = 0
        self.enforce_healthy = False

    def lease(self, index):
        self.client.post('/api/subscriptions', json={'client': f'soak-{index}', 'screens': ['overview']}).raise_for_status()

    def read(self, _):
        started = time.perf_counter()
        response = self.client.get('/api/tags')
        elapsed = (time.perf_counter() - started) * 1000
        response.raise_for_status()
        return response.json(), elapsed

    def tick(self):
        now = time.monotonic()
        if now >= self.next_lease:
            list(self.pool.map(self.lease, range(self.viewers)))
            self.next_lease = now + 5
        snapshots = []
        for snapshot, elapsed in self.pool.map(self.read, range(self.viewers)):
            if self.enforce_healthy:
                require(healthy(snapshot), 'The healthy route lost good data during operator load')
            snapshots.append(snapshot)
            self.latencies.record(elapsed)
        return snapshots[0]

    def until(self, predicate, label, timeout):
        started = time.monotonic()
        while time.monotonic() - started < timeout:
            if predicate(self.tick()):
                return round(time.monotonic() - started, 3)
            time.sleep(0.05)
        raise RuntimeError(f'Timed out waiting for {label}')


def quality(snapshot, tag):
    return snapshot['samples'][tag]['quality']


def healthy(snapshot):
    return quality(snapshot, 'HealthyLevel') == 'good'


def open_runtime(db, plant):
    with patch('openhmi.server.RuntimeDriver', return_value=RuntimeDriver(plant.client)):
        return create_app(db)


def append_evidence(work, event, **fields):
    record = {'utc': datetime.now(timezone.utc).isoformat(), 'event': event, **fields}
    with (work / 'events.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(record, allow_nan=False) + '\n')


def exercise_cycle(app, load, plant, fault, timeout):
    client = load.client
    before = load.tick()['samples']['HealthyLevel']['timestamp']
    plant.fault = fault
    try:
        degraded = load.until(lambda data: quality(data, 'FaultLevel') == 'bad' and healthy(data)
                              and data['samples']['HealthyLevel']['timestamp'] != before, 'partial PLC outage', timeout)
        operated = client.post('/api/controls/toggle/activate', json={})
        operated.raise_for_status()
        operation = operated.headers['x-openhmi-operation-id']
        writes = plant.writes
        with app.state.store._lock:
            app.state.store._db.execute('PRAGMA query_only=ON')
        try:
            denied = client.post('/api/controls/soak/activate', json={})
            require(denied.status_code == 503 and plant.writes == writes, 'Read-only storage allowed command dispatch')

            def historian_retrying(data):
                if not healthy(data):
                    return False
                diagnostics = client.get('/api/diagnostics')
                diagnostics.raise_for_status()
                return any(item['id'] == 'historian' and item['state'] == 'retrying'
                           for item in diagnostics.json()['workers'])

            storage = load.until(historian_retrying, 'historian retry on read-only storage', timeout)
        finally:
            with app.state.store._lock:
                app.state.store._db.execute('PRAGMA query_only=OFF')
                writable_at = time.time()
    finally:
        plant.fault = None

    def restored(data):
        if not healthy(data) or quality(data, 'FaultLevel') != 'good':
            return False
        diagnostics = client.get('/api/diagnostics')
        diagnostics.raise_for_status()
        workers = diagnostics.json()['workers']
        if any(item['state'] != 'healthy' for item in workers if item['id'] in ('historian', 'alarms')):
            return False
        history = client.get('/api/history', params={'tags': 'HealthyLevel', 'seconds': timeout + 1, 'limit': 20})
        history.raise_for_status()
        return any(sample['epoch'] >= writable_at and sample['quality'] == 'good' for sample in history.json()['samples'])

    recovery = load.until(restored, 'PLC and historian recovery', timeout)
    return {'fault': fault, 'degraded_seconds': degraded, 'storage_detection_seconds': storage,
            'recovery_seconds': recovery, 'local_operation_id': operation, 'read_only_dispatch_status': denied.status_code}


def resource_snapshot(db, cpu_start, wall_start):
    current, peak = tracemalloc.get_traced_memory()
    size = 0
    for path in db.parent.glob(db.name + '*'):
        try:
            size += path.stat().st_size
        except FileNotFoundError:
            pass  # SQLite may finish a transaction and remove a sidecar.
    return {'elapsed_seconds': round(time.monotonic() - wall_start, 3),
            'process_cpu_seconds': round(time.process_time() - cpu_start, 3),
            'python_heap_bytes': {'current': current, 'peak': peak}, 'database_bytes': size}


def rehearse(args, report):
    db = args.work / 'Soak.openhmi.sqlite3'
    store = ProjectStore(db, initial_project=project_fixture())
    store.close()
    plant = OfflinePlant()
    latencies = RequestTiming(args.max_p95_ms)
    max_recovery = 0
    cpu_start, wall_start = time.process_time(), time.monotonic()
    tracemalloc.start(1)
    # Even a future fixture regression must never fall back to a real PLC driver.
    with patch('pycomm3.LogixDriver', side_effect=AssertionError('Physical PLC access is disabled for the soak')), \
            ThreadPoolExecutor(max_workers=args.viewers) as pool:
        app = open_runtime(db, plant)
        with TestClient(app) as client:
            load = Load(client, pool, args.viewers, latencies)
            load.until(lambda data: healthy(data) and quality(data, 'FaultLevel') == 'good',
                       'initial simulated samples', args.recovery_timeout)
            load.enforce_healthy = True
            start = time.monotonic()
            while True:
                cycle = report['cycles'] + 1
                fault = 'disconnect' if cycle % 2 else 'malformed'
                append_evidence(args.work, 'fault-started', cycle=cycle, fault=fault)
                evidence = exercise_cycle(app, load, plant, fault, args.recovery_timeout)
                max_recovery = max(max_recovery, evidence['recovery_seconds'])
                report['cycles'] = cycle
                append_evidence(args.work, 'cycle-complete', cycle=cycle, **evidence,
                                resources=resource_snapshot(db, cpu_start, wall_start))
                next_cycle = min(start + args.seconds, start + cycle * args.fault_every)
                while time.monotonic() < next_cycle:
                    load.tick()
                    time.sleep(0.1)
                if time.monotonic() >= start + args.seconds:
                    break
            active = client.get('/api/project/active')
            active.raise_for_status()
            applied = active.json()
            response = client.post('/api/controls/soak/activate', json={})
            response.raise_for_status()
            command = response.json()['transaction']
            require(command['state'] == 'requested' and plant.writes == 1, 'Synthetic dispatch count or state differed')
            append_evidence(args.work, 'restart-started', transaction=command['id'], operation_id=command['operation_id'])

        with TestClient(open_runtime(db, plant)) as client:
            load = Load(client, pool, args.viewers, latencies)
            load.until(lambda data: healthy(data) and quality(data, 'FaultLevel') == 'good',
                       'fresh PLC data after reopen', args.recovery_timeout)
            active = client.get('/api/project/active')
            active.raise_for_status()
            reopened = active.json()
            require(reopened['project_instance'] != applied['project_instance']
                    and reopened['revision'] == applied['revision'] and reopened['project'] == applied['project'],
                    'Applied project changed during reopen')
            transaction = f"/api/commands/{command['id']}"
            result = client.get(transaction)
            result.raise_for_status()
            require(result.json()['state'] == 'uncertain' and plant.writes == 1, 'Pending command was lost or replayed')
            duplicate = client.post('/api/controls/soak/activate', json={})
            require(duplicate.status_code == 409 and plant.writes == 1, 'Unresolved command accepted a duplicate')
            activity = client.get('/api/activity', params={'search': command['operation_id']})
            activity.raise_for_status()
            require(any(item['operation_id'] == command['operation_id'] for item in activity.json()['items']),
                    'Durable activity record was missing after reopen')
            plant.finish_command(command['sequence'])

            def reconciled(_):
                observed = client.get(transaction)
                observed.raise_for_status()
                return observed.json()['state'] == 'completed'

            load.until(reconciled, 'PLC-owned command reconciliation', args.recovery_timeout)
            require(plant.writes == 1, 'Reconciliation replayed the command')
            append_evidence(args.work, 'restart-complete', transaction=command['id'], synthetic_writes=plant.writes)

    report.update(resource_snapshot(db, cpu_start, wall_start), max_cycle_recovery_seconds=max_recovery,
                  tag_request_timing=latencies.snapshot(), synthetic_writes=plant.writes,
                  applied_revision_preserved=True, restart_reconciled_without_replay=True)
    require(report['tag_request_timing']['p95_within_limit'], 'Tag request p95 exceeded the rehearsal limit')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True, help='New evidence folder')
    parser.add_argument('--seconds', type=int, default=30)
    parser.add_argument('--fault-every', type=int, default=10, help='Seconds between cycle starts')
    parser.add_argument('--viewers', type=int, default=3)
    parser.add_argument('--recovery-timeout', type=int, default=10)
    parser.add_argument('--max-p95-ms', type=int, default=1000)
    args = parser.parse_args()
    if not (1 <= args.seconds <= 86400 and 1 <= args.fault_every <= 3600 and 1 <= args.viewers <= 16
            and 2 <= args.recovery_timeout <= 60 and args.max_p95_ms > 0):
        parser.error('Use 1–86400 seconds, 1–3600 fault interval, 1–16 viewers, 2–60 seconds timeout and positive p95 limit.')
    try:
        args.work.mkdir(parents=True, exist_ok=False)
    except OSError as error:
        parser.exit(1, f'Cannot create new rehearsal folder: {error}\n')
    report = {'status': 'failed', 'scope': 'offline ASGI lifecycle and synthetic PLCs',
              'platform': platform.platform(), 'python': platform.python_version(), 'cycles': 0,
              'started_utc': datetime.now(timezone.utc).isoformat(),
              'profile': {key: value for key, value in vars(args).items() if key != 'work'}}
    handler = RotatingFileHandler(args.work / 'runtime.log', maxBytes=2 * 1024 * 1024, backupCount=2, encoding='utf-8')
    logging.basicConfig(handlers=[handler], level=logging.WARNING, format='%(asctime)s %(levelname)s %(message)s')
    try:
        rehearse(args, report)
        report['status'] = 'passed'
    except (Exception, KeyboardInterrupt) as error:
        report['error'] = f'{type(error).__name__}: {error}'
    finally:
        tracemalloc.stop()
        handler.close()
        logging.getLogger().removeHandler(handler)
        (args.work / 'report.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
