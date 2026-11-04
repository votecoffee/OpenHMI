"""Offline PLC ownership, persistence and failure boundaries; never contacts a controller."""

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import time
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from openhmi.server import create_app
from tests.test_security import bootstrap, PASSWORD
from tests.test_logix_history import FakePLC


def command_project(project, remote=False):
    project = deepcopy(project)
    project['tags'].append({'name': 'CycleCommand', 'type': 'struct', 'writable': True,
        'connection': 'bench' if remote else '', 'address': 'Cycle' if remote else '',
        'initial': {'RequestSequence': 0, 'AcceptedSequence': 0, 'CompletedSequence': 0, 'ResultCode': 0, 'Permit': True},
        'members': {'RequestSequence': 'integer', 'AcceptedSequence': 'integer', 'CompletedSequence': 'integer', 'ResultCode': 'integer', 'Permit': 'boolean'}})
    if remote:
        project['connections'].append({'id': 'bench', 'name': 'Offline fake', 'path': 'offline-only/0', 'enabled': True})
    project['commands'] = [{'id': 'cycle', 'name': 'Cycle request', 'root_tag': 'CycleCommand', 'permit_member': 'Permit', 'timeout_seconds': 2.0}]
    project['controls'].append({'kind': 'button', 'id': 'cycle', 'label': 'Request cycle', 'mode': 'command', 'command': 'cycle'})
    return project


def install(client, project):
    revision = client.get('/api/project').json()['draft_revision']
    response = client.put('/api/project/draft', json={'expected_revision': revision, 'project': project})
    response.raise_for_status()
    client.post('/api/project/apply', json={'expected_revision': response.json()['draft_revision']}).raise_for_status()


class CommandTests(unittest.TestCase):
    def setup_app(self, path=None, remote=False):
        app = create_app(path)
        self.addCleanup(app.state.store.close)
        self.addCleanup(app.state.driver.close)
        client = TestClient(app)  # Explicit deterministic polls, without background lifespan threads.
        self.addCleanup(client.close)
        if remote:
            class CommandPLC(FakePLC):
                def __init__(self, *args, **kwargs):
                    super().__init__(*args, **kwargs)
                    self.values['Cycle'] = {'RequestSequence': 0, 'AcceptedSequence': 0, 'CompletedSequence': 0, 'ResultCode': 0, 'Permit': True}
                    self.tags['Cycle'] = {'external_access': 'Read/Write', 'data_type': {'name': 'Command', 'attributes': list(self.values['Cycle']),
                        'internal_tags': {name: {'data_type': 'BOOL' if name == 'Permit' else 'DINT'} for name in self.values['Cycle']}}}
            app.state.driver.factory = CommandPLC
        install(client, command_project(client.get('/api/project').json()['draft'], remote))
        app.state.driver.poll()
        return app, client

    def dispatch(self, client):
        response = client.post('/api/controls/cycle/activate', json={})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['transaction']

    def observe(self, app, accepted=None, completed=None, result=0):
        values = app.state.driver._tags['CycleCommand']
        if accepted is not None:
            values['AcceptedSequence'] = accepted
        if completed is not None:
            values['CompletedSequence'] = completed
            values['ResultCode'] = result
        time.sleep(0.003)  # Advance past the acquisition/dispatch timestamp precision.
        app.state.commands.poll()

    def test_requested_accepted_completed_failed_and_durable_sequence(self):
        app, client = self.setup_app()
        first = self.dispatch(client)
        self.assertEqual((first['state'], first['sequence']), ('requested', 1))
        journal = app.state.activity.query()['items'][0]
        self.assertEqual(journal['outcome']['verification'], 'request_tag_readback')
        self.assertFalse(journal['outcome']['equipment_complete'])
        self.assertEqual(first['operation_id'], journal['operation_id'])
        self.assertEqual(client.post('/api/controls/cycle/activate', json={}).status_code, 409)
        self.observe(app, accepted=1)
        self.assertEqual(app.state.commands.get(first['id'])['state'], 'accepted')
        self.observe(app, completed=1)
        result = client.get(f"/api/commands/{first['id']}").json()
        self.assertEqual((result['state'], result['result_code']), ('completed', 0))
        self.assertEqual([item['state'] for item in result['events']], ['prepared', 'requested', 'accepted', 'completed'])
        app.state.driver._tags['CycleCommand'].update(RequestSequence=0, AcceptedSequence=0, CompletedSequence=0)
        second = self.dispatch(client)
        self.assertEqual(second['sequence'], 2)  # A PLC reset never reuses a sequence.
        self.observe(app, accepted=2, completed=2, result=17)
        self.assertEqual(app.state.commands.get(second['id'])['state'], 'failed')
        self.assertEqual(client.get('/api/commands?limit=1').json()['next_before_id'], second['id'])
        self.assertEqual(client.get('/api/commands?command_id=unknown').json()['items'], [])
        self.assertEqual(client.get('/api/commands?before_id=999999999999999999999').status_code, 422)
        self.assertEqual(client.get('/api/commands/999999999999999999999').status_code, 422)

    def test_timeout_late_acceptance_does_not_complete_but_matching_completion_reconciles(self):
        app, client = self.setup_app()
        transaction = self.dispatch(client)
        app.state.commands.poll('9999-01-01T00:00:00+00:00')
        self.assertEqual(app.state.commands.get(transaction['id'])['state'], 'uncertain')
        self.observe(app, accepted=transaction['sequence'])
        self.assertEqual(app.state.commands.get(transaction['id'])['state'], 'uncertain')
        self.assertEqual(client.post('/api/controls/cycle/activate', json={}).status_code, 409)
        self.observe(app, completed=transaction['sequence'])
        self.assertEqual(app.state.commands.get(transaction['id'])['state'], 'completed')

    def test_completion_requires_the_matching_request_and_acceptance(self):
        app, client = self.setup_app()
        transaction = self.dispatch(client)
        self.observe(app, completed=transaction['sequence'])
        self.assertEqual(app.state.commands.get(transaction['id'])['state'], 'uncertain')
        self.observe(app, accepted=transaction['sequence'])
        self.assertEqual(app.state.commands.get(transaction['id'])['state'], 'completed')

    def test_permit_binding_and_server_group_authorization(self):
        app, client = self.setup_app()
        app.state.driver._tags['CycleCommand']['Permit'] = False
        self.assertEqual(client.post('/api/controls/cycle/activate', json={}).status_code, 423)
        self.assertEqual(app.state.commands.recent()['items'], [])
        app.state.driver._tags['CycleCommand']['Permit'] = True
        bootstrap(app)
        self.assertEqual(client.get('/api/commands').status_code, 401)
        self.assertEqual(client.post('/api/controls/cycle/activate', json={}).status_code, 401)
        client.post('/api/security/login', json={'name': 'admin', 'password': PASSWORD, 'provider': 'local'}).raise_for_status()
        project = client.get('/api/project').json()['draft']
        project['commands'][0]['security_groups'] = ['Approvers']
        install(client, project)
        # A normal operator cannot bypass the contract group via the API.
        from openhmi.security import Principal
        operator = Principal('operator', 'local', frozenset({'Operators'}), frozenset({'runtime.operate'}))
        with patch.object(app.state.security, 'user', return_value=operator):
            self.assertEqual(client.post('/api/controls/cycle/activate', json={}).status_code, 403)
        self.assertEqual(app.state.commands.recent()['items'], [])
        self.dispatch(client)  # Administrator override is the existing HMI group policy.

    def test_uncertain_write_is_not_replayed_and_contract_cannot_be_remapped(self):
        app, client = self.setup_app()
        original = app.state.driver.write_command_request
        def lost_reply(*args):
            original(*args)
            raise ConnectionError('Synthetic lost reply')
        with patch.object(app.state.driver, 'write_command_request', side_effect=lost_reply) as writer:
            response = client.post('/api/controls/cycle/activate', json={})
            self.assertEqual(response.status_code, 409, response.text)
            self.assertEqual(writer.call_count, 1)
        transaction = app.state.commands.recent()['items'][0]
        self.assertEqual(transaction['state'], 'uncertain')
        self.assertEqual(app.state.activity.query()['items'][0]['status'], 'uncertain')
        project = client.get('/api/project').json()['draft']
        project['commands'][0]['timeout_seconds'] = 10.0
        saved = client.put('/api/project/draft', json={'expected_revision': client.get('/api/project').json()['draft_revision'], 'project': project})
        saved.raise_for_status()
        self.assertEqual(client.post('/api/project/apply', json={'expected_revision': saved.json()['draft_revision']}).status_code, 409)
        self.observe(app, accepted=1, completed=1)
        self.assertEqual(app.state.commands.get(transaction['id'])['state'], 'completed')

    def test_sql_reservation_and_dispatch_marker_failures_never_write(self):
        for trigger in ["BEFORE INSERT ON command_transaction", "BEFORE UPDATE OF state ON command_transaction WHEN NEW.state='requested'"]:
            with self.subTest(trigger=trigger):
                app, client = self.setup_app()
                with app.state.store.transaction() as db:
                    db.execute(f"CREATE TRIGGER fail_command {trigger} BEGIN SELECT RAISE(ABORT,'synthetic SQL outage'); END")
                with patch.object(app.state.driver, 'write_command_request') as writer:
                    self.assertEqual(client.post('/api/controls/cycle/activate', json={}).status_code, 500)
                    writer.assert_not_called()
                self.assertEqual(app.state.driver._tags['CycleCommand']['RequestSequence'], 0)

    def test_activity_marker_failure_interrupts_reservation_without_dispatch(self):
        app, client = self.setup_app()
        with patch.object(app.state.activity, 'mark_dispatch', side_effect=sqlite3.OperationalError('offline')):
            self.assertEqual(client.post('/api/controls/cycle/activate', json={}).status_code, 503)
        self.assertEqual(app.state.commands.recent()['items'][0]['state'], 'interrupted')
        self.assertEqual(app.state.driver._tags['CycleCommand']['RequestSequence'], 0)

    def test_restart_never_dispatches_and_keeps_channel_reserved(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'commands.sqlite3'
            app, client = self.setup_app(path)
            transaction = self.dispatch(client)
            reopened = create_app(path)
            try:
                service = reopened.state.commands
                self.assertEqual(service.get(transaction['id'])['state'], 'uncertain')
                self.assertEqual(reopened.state.driver._tags['CycleCommand']['RequestSequence'], 0)
                with TestClient(reopened) as second:
                    self.assertEqual(second.post('/api/controls/cycle/activate', json={}).status_code, 409)
                with app.state.store.transaction() as db:
                    db.execute("UPDATE command_transaction SET state='prepared' WHERE id=?", (transaction['id'],))
                from openhmi.commands import CommandService
                self.assertEqual(CommandService(app.state.store, app.state.driver).get(transaction['id'])['state'], 'interrupted')
            finally:
                reopened.state.driver.close()
                reopened.state.store.close()
                app.state.store.close()

    def test_protocol_members_are_reserved_and_bad_contracts_are_rejected(self):
        app, client = self.setup_app(remote=True)
        for address in ['CycleCommand', 'CycleCommand.RequestSequence', 'CycleCommand.CompletedSequence']:
            with self.assertRaises(ValueError):
                app.state.driver.write(address, [1])
        project = client.get('/api/project').json()['draft']
        for mutate in [lambda p: p['commands'][0].update(result_member='Permit'),
                       lambda p: p['commands'][0].update(accepted_member='RequestSequence'),
                       lambda p: p['commands'].append({**p['commands'][0], 'id': 'another'}),
                       lambda p: p['tags'].append({'name': 'Bypass', 'type': 'integer', 'connection': 'bench', 'address': 'Cycle.RequestSequence', 'writable': True}),
                       lambda p: p['commands'][0].update(security_groups=['UnknownGroup'])]:
            candidate = deepcopy(project); mutate(candidate)
            response = client.put('/api/project/draft', json={'expected_revision': client.get('/api/project').json()['draft_revision'], 'project': candidate})
            self.assertEqual(response.status_code, 422, response.text)

    def test_remote_protocol_polling_quality_no_extra_screen_lease_and_no_replay(self):
        app, client = self.setup_app(remote=True)
        driver = app.state.driver
        plc = driver.connections['bench'].client
        self.assertEqual(driver.leases, {})
        self.assertEqual(driver.last_rates[('bench', 'Cycle')], 250)
        transaction = self.dispatch(client)
        self.assertEqual(plc.writes, [('Cycle.RequestSequence', 1)])
        app.state.commands.poll()  # Predispatch cached data is not acceptance/failure evidence.
        self.assertEqual(app.state.commands.get(transaction['id'])['state'], 'requested')
        plc.values['Cycle'].update(AcceptedSequence=1)
        driver.samples['CycleCommand']['monotonic'] -= 100
        app.state.commands.poll()
        self.assertEqual(app.state.commands.get(transaction['id'])['state'], 'requested')
        time.sleep(0.003); driver.poll(); app.state.commands.poll()
        self.assertEqual(app.state.commands.get(transaction['id'])['state'], 'accepted')
        plc.fail = True
        driver.deadlines.clear(); driver.poll()
        app.state.commands.poll('9999-01-01T00:00:00+00:00')
        self.assertEqual(app.state.commands.get(transaction['id'])['state'], 'uncertain')
        self.assertEqual(len(plc.writes), 1)
        self.assertEqual(client.post('/api/controls/cycle/activate', json={}).status_code, 409)

    def test_sequence_exhaustion_and_disabled_connection_prevent_dispatch(self):
        app, client = self.setup_app()
        app.state.driver._tags['CycleCommand'].update(RequestSequence=2147483647, AcceptedSequence=2147483647, CompletedSequence=2147483647)
        self.assertEqual(client.post('/api/controls/cycle/activate', json={}).status_code, 409)
        self.assertEqual(app.state.commands.recent()['items'], [])
        remote, second = self.setup_app(remote=True)
        project = second.get('/api/project').json()['draft']
        project['connections'][0]['enabled'] = False
        install(second, project)
        self.assertEqual(second.post('/api/controls/cycle/activate', json={}).status_code, 409)
        self.assertEqual(remote.state.commands.recent()['items'], [])

    def test_concurrent_clients_reserve_one_channel_once(self):
        app, client = self.setup_app()
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda _: client.post('/api/controls/cycle/activate', json={}), range(2)))
        self.assertEqual(sorted(response.status_code for response in responses), [200, 409])
        self.assertEqual(len(app.state.commands.recent()['items']), 1)
        self.assertEqual(app.state.driver._tags['CycleCommand']['RequestSequence'], 1)
