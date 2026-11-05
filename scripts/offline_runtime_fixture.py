"""Synthetic PLC/project shared by the source-only runtime drills."""

from threading import Lock
import time
from types import SimpleNamespace
from unittest.mock import patch

from openhmi.logix import RuntimeDriver
from openhmi.projects import Project, default_project
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

    def record_write(self, sequence):
        with self.lock:
            self.writes += 1
            self.cycle['RequestSequence'] = sequence

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
        self.plant.record_write(sequence)
        return SimpleNamespace(error=None)


def open_runtime(db, plant):
    with patch('openhmi.server.RuntimeDriver', return_value=RuntimeDriver(plant.client)):
        return create_app(db)
