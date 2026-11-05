"""Offline recipe-copy publication, failure and ownership checks; no network PLCs."""

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import sqlite3
import time
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from openhmi.recipe_transfers import META_TYPES, matches
from openhmi.server import create_app
from tests.test_commands import command_project, install
from tests.test_logix_history import FakePLC
from tests.test_recipes import USERS, PASSWORD, recipe_content


def transfer_project(project, remote=False):
    project = command_project(project, remote)
    project['controls'] = [control for control in project['controls'] if control['id'] != 'cycle']
    root = project['tags'][-1]
    members = {**META_TYPES, 'Speed': 'number', 'Count': 'integer', 'Enabled': 'boolean', 'Batch': 'string'}
    for prefix in ('Staging', 'Running'):
        root['initial'][prefix] = {name: {'string': '', 'integer': 0, 'number': 0.0, 'boolean': False}[kind] for name, kind in members.items()}
        root['members'].update({prefix + '.' + name: kind for name, kind in members.items()})
    project['commands'][0]['timeout_seconds'] = 30.0
    project['recipe_transfers'] = [{'id': 'product', 'name': 'Product recipe', 'command_id': 'cycle',
                                   'parameters': {'speed': 'Speed', 'count': 'Count', 'enabled': 'Enabled', 'batch': 'Batch'}}]
    return project


def content():
    result = recipe_content(45.5)
    result['parameters'] += [
        {'name': 'count', 'label': 'Count', 'type': 'integer', 'value': 7},
        {'name': 'enabled', 'label': 'Enabled', 'type': 'boolean', 'value': True},
        {'name': 'batch', 'label': 'Batch', 'type': 'text', 'value': 'Test batch'},
    ]
    return result


class RecipeTransferTests(unittest.TestCase):
    def setup_app(self, path=None, remote=False):
        app = create_app(path, recipe_users=USERS)
        self.addCleanup(app.state.store.close)
        self.addCleanup(app.state.driver.close)
        client = TestClient(app)
        self.addCleanup(client.close)
        project = transfer_project(client.get('/api/project').json()['draft'], remote)
        if remote:
            initial = deepcopy(project['tags'][-1]['initial'])
            class RecipePLC(FakePLC):
                def __init__(self, *args, **kwargs):
                    super().__init__(*args, **kwargs)
                    self.values['Cycle'] = deepcopy(initial)
                    self.tags['Cycle'] = {'external_access': 'Read/Write', 'data_type': {'name': 'RecipeChannel', 'attributes': [], 'internal_tags': {}}}
                def write(self, pair):
                    self.writes.append(pair)
                    address, value = pair
                    parts = address.split('.')
                    parent = self.values
                    for part in parts[:-1]:
                        parent = parent[part]
                    parent[parts[-1]] = value
                    return SimpleNamespace(error=None)
            app.state.driver.factory = RecipePLC
        install(client, project)
        app.state.driver.poll()
        client.post('/api/recipe-auth/login', json={'name': 'engineer', 'password': PASSWORD}).raise_for_status()
        return app, client

    def create(self, client, payload=None, code='A'):
        response = client.post('/api/recipes', json={'code': code, 'content': payload or content(), 'reason': 'Synthetic transfer fixture'})
        response.raise_for_status()
        return response.json()

    def dispatch(self, client, revision, expected=200):
        response = client.post('/api/recipe-transfers/product/dispatch', json={
            'revision_id': revision['id'], 'expected_revision_version': revision['version'], 'reason': 'Transfer test copy'})
        self.assertEqual(response.status_code, expected, response.text)
        return response.json()

    def values(self, app):
        driver = app.state.driver
        return driver.connections['bench'].client.values['Cycle'] if 'bench' in driver.connections else driver._tags['CycleCommand']

    def test_stale_project_revision_rejects_transfer_before_staging(self):
        app, client = self.setup_app()
        recipe = self.create(client)
        displayed = client.get('/api/recipe-transfers').json()
        project = client.get('/api/project').json()['active']
        project['recipe_transfers'][0]['name'] = 'Updated target'
        install(client, project)
        current = client.get('/api/recipe-transfers').json()
        self.assertGreater(current['active_revision'], displayed['active_revision'])
        self.assertEqual(current['profiles'][0]['name'], 'Updated target')
        with patch.object(app.state.driver, 'write_recipe_member') as stage:
            rejected = client.post('/api/recipe-transfers/product/dispatch', json={
                'revision_id': recipe['id'], 'expected_revision_version': recipe['version'],
                'expected_project_revision': displayed['active_revision'], 'reason': 'Old target fixture',
            })
            self.assertEqual(rejected.status_code, 409, rejected.text)
            self.assertEqual(rejected.headers['X-OpenHMI-Audit-Status'], 'rejected')
            stage.assert_not_called()
        self.assertEqual(client.get('/api/recipe-transfers').json()['items'], [])
        self.assertEqual(self.values(app)['RequestSequence'], 0)

    def publish(self, app, code=0, copy=True):
        value = self.values(app)
        value['AcceptedSequence'] = value['RequestSequence']
        if copy:
            value['Running'] = deepcopy(value['Staging'])
        value['ResultCode'] = code
        value['CompletedSequence'] = value['RequestSequence']
        time.sleep(0.003)
        app.state.driver.deadlines.clear()
        app.state.driver.poll()
        app.state.commands.poll()

    def test_staging_is_verified_commit_is_last_and_plc_copy_is_independent(self):
        app, client = self.setup_app(remote=True)
        revision = self.create(client)
        before = deepcopy(self.values(app)['Running'])
        app.state.driver.poll()  # This fixture has no background acquisition loop; obtain a fresh sample after login/setup.
        result = self.dispatch(client, revision)
        identifier = result['transfer']['id']
        self.assertEqual(result['transaction']['state'], 'requested')
        self.assertFalse(result['transfer']['snapshot']['production_approved'])
        self.assertTrue(app.state.driver.read('MotorRunning')[0])
        self.assertEqual(self.values(app)['Running'], before)
        writes = app.state.driver.connections['bench'].client.writes
        self.assertEqual(writes[-1], ('Cycle.RequestSequence', 1))
        self.assertTrue(all(address.startswith('Cycle.Staging.') for address, _ in writes[:-1]))
        self.assertEqual(len(writes), 11)
        journal = app.state.activity.query()['items'][0]
        self.assertEqual((journal['actor'], journal['provider']), ('engineer', 'recipe-local'))
        self.assertEqual(journal['outcome']['transaction_id'], identifier)
        self.publish(app)
        verified = client.get(f'/api/recipe-transfers/{identifier}').json()
        self.assertEqual(verified['transaction']['state'], 'completed')
        self.assertEqual(self.values(app)['Running']['Speed'], 45.5)
        self.assertFalse(self.values(app)['Running']['RecipeProductionApproved'])
        self.assertEqual(self.values(app)['Running']['ContentHash'], revision['content_hash'])
        self.assertEqual(self.values(app)['Running']['TransferHash'], verified['transfer_hash'])
        self.assertIsNone(app.state.recipes.selected()['snapshot'])  # PLC transfer does not change HMI selection.
        self.assertEqual(client.get('/api/recipe-transfers?limit=1').json()['items'][0]['id'], identifier)

    def test_self_approval_withdrawal_and_next_test_transfer_preserve_running_copy(self):
        app, client = self.setup_app()
        revision = self.create(client)
        for action in ('submit', 'approve'):
            response = client.post(f"/api/recipe-revisions/{revision['id']}/transition", json={'expected_version': revision['version'], 'action': action, 'reason': action})
            response.raise_for_status(); revision = response.json()
        first = self.dispatch(client, revision)['transfer']
        self.assertTrue(first['snapshot']['production_approved'])
        self.assertEqual(first['snapshot']['approved_by'], 'engineer')
        response = client.post(f"/api/recipe-revisions/{revision['id']}/transition", json={'expected_version': revision['version'], 'action': 'withdraw', 'reason': 'Library changed after dispatch'})
        response.raise_for_status(); withdrawn = response.json()
        self.publish(app)
        running = deepcopy(self.values(app)['Running'])
        self.assertTrue(running['RecipeProductionApproved'])
        self.assertTrue(app.state.recipe_transfers.get(first['id'])['snapshot']['production_approved'])
        endpoint = f"/api/recipe-transfers/{first['id']}"
        anonymous = TestClient(app)
        self.addCleanup(anonymous.close)
        self.assertEqual(anonymous.get(endpoint, params={'download': True}).status_code, 401)
        with patch.object(app.state.driver, 'read_command_root') as read:
            export = client.get(endpoint, params={'download': True})
            read.assert_not_called()
        self.assertEqual(export.status_code, 200, export.text)
        self.assertEqual(export.headers['Content-Disposition'], f'attachment; filename="openhmi-recipe-transfer-{first["id"]}.json"')
        evidence = export.json()
        self.assertEqual((evidence['format'], evidence['version']), ('openhmi.recipe-transfer', 1))
        self.assertEqual(evidence['project_id'], client.get('/api/project').json()['project_id'])
        self.assertEqual(evidence['transfer'], client.get(endpoint).json())
        self.assertTrue(evidence['transfer']['envelope']['values']['RecipeProductionApproved'])
        self.assertEqual(evidence['transfer']['transaction']['state'], 'completed')
        second = self.dispatch(client, withdrawn)['transfer']
        self.assertFalse(second['snapshot']['production_approved'])
        self.assertNotEqual(first['transfer_hash'], second['transfer_hash'])
        self.assertEqual(self.values(app)['Running'], running)
        self.publish(app)
        self.assertFalse(self.values(app)['Running']['RecipeProductionApproved'])

    def test_matching_ack_with_wrong_running_payload_stays_uncertain_until_verified(self):
        app, client = self.setup_app()
        result = self.dispatch(client, self.create(client))
        identifier = result['transfer']['id']
        self.publish(app, copy=False)
        self.assertEqual(app.state.commands.get(identifier)['state'], 'uncertain')
        self.values(app)['Running'] = deepcopy(self.values(app)['Staging'])
        self.values(app)['Running']['RecipeProductionApproved'] = True
        app.state.commands.poll()
        self.assertEqual(app.state.commands.get(identifier)['state'], 'uncertain')
        self.values(app)['Running']['RecipeProductionApproved'] = False
        self.values(app)['Running']['ContentHash'] = 'wrong-hash'
        app.state.commands.poll()
        self.assertEqual(app.state.commands.get(identifier)['state'], 'uncertain')
        self.dispatch(client, self.create(client, code='B'), expected=409)
        self.publish(app)
        self.assertEqual(app.state.commands.get(identifier)['state'], 'completed')
        self.assertIn('production BOOL verified', app.state.commands.get(identifier)['events'][-1]['detail'])

    def test_plc_rejection_finishes_without_claiming_a_running_copy(self):
        app, client = self.setup_app()
        identifier = self.dispatch(client, self.create(client))['transfer']['id']
        self.publish(app, code=17, copy=False)
        transaction = app.state.commands.get(identifier)
        self.assertEqual((transaction['state'], transaction['result_code']), ('failed', 17))
        self.assertEqual(self.values(app)['Running']['RevisionId'], 0)

    def test_partial_staging_and_lost_commit_reply_are_uncertain_and_never_replayed(self):
        for phase in ('staging', 'commit'):
            with self.subTest(phase=phase):
                app, client = self.setup_app()
                revision = self.create(client)
                before = deepcopy(self.values(app)['Running'])
                method = 'write_recipe_member' if phase == 'staging' else 'write_command_request'
                original = getattr(app.state.driver, method)
                def lose(*args):
                    original(*args)
                    raise ConnectionError('Synthetic lost reply')
                with patch.object(app.state.driver, method, side_effect=lose) as writer:
                    self.dispatch(client, revision, expected=409)
                    self.assertEqual(writer.call_count, 1)
                transaction = app.state.commands.recent()['items'][0]
                self.assertEqual(transaction['state'], 'uncertain')
                self.assertEqual(self.values(app)['Running'], before)
                self.assertEqual(self.values(app)['RequestSequence'], 0 if phase == 'staging' else 1)
                with patch.object(app.state.driver, 'write_command_request') as writer:
                    self.dispatch(client, revision, expected=409)
                    app.state.commands.poll('9999-01-01T00:00:00+00:00')
                    writer.assert_not_called()

    def test_full_staging_readback_and_changed_permit_prevent_commit(self):
        for change in ('mismatch', 'permit'):
            app, client = self.setup_app()
            revision = self.create(client)
            original = app.state.driver.read_command_root
            def changed(definition):
                actual = original(definition)
                if change == 'mismatch': actual['Staging']['Speed'] = 0.0
                else: actual['Permit'] = False
                return actual
            with patch.object(app.state.driver, 'read_command_root', side_effect=changed), patch.object(app.state.driver, 'write_command_request') as writer:
                self.dispatch(client, revision, expected=409)
                writer.assert_not_called()
            self.assertEqual(self.values(app)['Running']['RevisionId'], 0)

    def test_stale_review_mapping_types_limits_and_permissions_reject_before_writes(self):
        app, client = self.setup_app()
        revision = self.create(client)
        self.dispatch(client, {**revision, 'version': 99}, expected=409)
        for mutate in [lambda value: value['parameters'].pop(),
                       lambda value: value['parameters'][1].update(value=2147483648),
                       lambda value: value['parameters'][1].update(type='number', value=7.0),
                       lambda value: value['parameters'][3].update(value='X' * 83),
                       lambda value: value['parameters'][3].update(value='测试')]:
            value = content(); mutate(value)
            candidate = self.create(client, value, code='C' + str(len(app.state.recipes.snapshot()['revisions'])))
            self.dispatch(client, candidate, expected=422)
        self.values(app)['Permit'] = False
        self.dispatch(client, revision, expected=423)
        self.values(app)['Permit'] = True
        client.post('/api/recipe-auth/logout', json={}).raise_for_status()
        self.dispatch(client, revision, expected=401)
        self.assertEqual(app.state.commands.recent()['items'], [])

    def test_policy_and_hmi_group_checks_are_enforced_on_server(self):
        app, client = self.setup_app()
        revision = self.create(client)
        from openhmi.recipes import canonical
        with app.state.store.transaction() as db:
            policy = app.state.recipes._policy(db)['policy']; policy['loading_enabled'] = False
            db.execute('UPDATE recipe_policy SET content=?', (canonical(policy),))
        self.dispatch(client, revision, expected=423)
        with app.state.store.transaction() as db:
            policy['loading_enabled'] = True; db.execute('UPDATE recipe_policy SET content=?', (canonical(policy),))
        from tests.test_security import bootstrap, PASSWORD as HMI_PASSWORD
        from openhmi.security import Principal
        bootstrap(app)
        client.post('/api/security/login', json={'name': 'admin', 'password': HMI_PASSWORD, 'provider': 'local'}).raise_for_status()
        for permissions in ({'recipes.operator'}, {'runtime.operate'}):
            principal = Principal('operator', 'local', frozenset({'Operators'}), frozenset(permissions))
            with patch.object(app.state.security, 'user', return_value=principal):
                self.dispatch(client, revision, expected=403)
        self.assertEqual(app.state.commands.recent()['items'], [])
        result = self.dispatch(client, revision)
        self.assertEqual(result['transfer']['snapshot']['transferred_by'], 'admin')
        self.assertEqual(app.state.activity.query()['items'][0]['provider'], 'local')

    def test_reservation_sql_failure_prevents_all_staging_and_commit_writes(self):
        app, client = self.setup_app()
        revision = self.create(client)
        with app.state.store.transaction() as db:
            db.execute("CREATE TRIGGER fail_transfer BEFORE INSERT ON recipe_transfer BEGIN SELECT RAISE(ABORT,'synthetic outage'); END")
        with patch.object(app.state.driver, 'write_recipe_member') as stage, patch.object(app.state.driver, 'write_command_request') as commit:
            with self.assertLogs(level='ERROR'):
                self.dispatch(client, revision, expected=500)
            stage.assert_not_called(); commit.assert_not_called()
        self.assertEqual(app.state.commands.recent()['items'], [])

    def test_restart_staging_and_requested_never_commit_or_replay(self):
        with TemporaryDirectory() as directory:
            app, client = self.setup_app(Path(directory) / 'recipe.sqlite3')
            identifier = self.dispatch(client, self.create(client))['transfer']['id']
            with app.state.store.transaction() as db:
                db.execute("UPDATE command_transaction SET state='staging' WHERE id=?", (identifier,))
            reopened = create_app(Path(directory) / 'recipe.sqlite3', recipe_users=USERS)
            try:
                self.assertEqual(reopened.state.commands.get(identifier)['state'], 'uncertain')
                self.assertEqual(reopened.state.recipe_transfers.get(identifier)['snapshot']['content']['title'], 'Product A')
                self.assertEqual(reopened.state.driver._tags['CycleCommand']['RequestSequence'], 0)
                with patch.object(reopened.state.driver, 'write_command_request') as writer:
                    reopened.state.commands.poll()
                    writer.assert_not_called()
            finally:
                reopened.state.driver.close(); reopened.state.store.close(); app.state.store.close()

    def test_protocol_bypass_bad_profiles_and_remapping_are_rejected(self):
        app, client = self.setup_app()
        driver = app.state.driver
        with self.assertRaises(ValueError): driver.write('CycleCommand.Staging.Speed', [1.0])
        with self.assertRaises(ValueError): driver.write_recipe_member(driver.project['recipe_transfers'][0], 'Running.Speed', 1.0)
        with self.assertRaises(HTTPException): app.state.commands.submit(driver.project['commands'][0], None)
        project = client.get('/api/project').json()['draft']
        for mutate in [lambda value: value['recipe_transfers'][0].update(running_prefix='Staging'),
                       lambda value: value['recipe_transfers'][0]['parameters'].update(speed='ContentHash'),
                       lambda value: value['recipe_transfers'][0].update(command_id='missing'),
                       lambda value: value['recipe_transfers'].append({**value['recipe_transfers'][0], 'id': 'other'}),
                       lambda value: value['controls'].append({'id': 'bypass', 'kind': 'button', 'label': 'Bypass', 'mode': 'command', 'command': 'cycle'})]:
            candidate = deepcopy(project); mutate(candidate)
            response = client.put('/api/project/draft', json={'expected_revision': client.get('/api/project').json()['draft_revision'], 'project': candidate})
            self.assertEqual(response.status_code, 422, response.text)
        self.dispatch(client, self.create(client))
        project['recipe_transfers'][0]['max_string_length'] = 100
        response = client.put('/api/project/draft', json={'expected_revision': client.get('/api/project').json()['draft_revision'], 'project': project})
        response.raise_for_status()
        self.assertEqual(client.post('/api/project/apply', json={'expected_revision': response.json()['draft_revision']}).status_code, 409)

    def test_numeric_copy_verification_accepts_real_round_trip_without_absolute_tolerance(self):
        import struct
        self.assertTrue(matches(struct.unpack('!f', struct.pack('!f', 0.1))[0], 0.1))
        self.assertFalse(matches(0.0, 1e-9))
        self.assertFalse(matches(True, 1))

    def test_complete_backup_restores_pending_transfer_without_replay(self):
        from openhmi.workspace import ProjectWorkspace
        with TemporaryDirectory() as directory:
            workspace = ProjectWorkspace(Path(directory) / 'Original.openhmi.sqlite3', recipe_users=USERS)
            with TestClient(workspace) as client:
                install(client, transfer_project(client.get('/api/project').json()['draft']))
                client.post('/api/recipe-auth/login', json={'name': 'engineer', 'password': PASSWORD}).raise_for_status()
                identifier = self.dispatch(client, self.create(client))['transfer']['id']
                client.post('/api/recipe-auth/login', json={'name': 'manager', 'password': PASSWORD}).raise_for_status()
                backup = client.get('/api/workspace/backup'); backup.raise_for_status()
                imported = client.post('/api/workspace/import?name=RestoredRecipe', content=backup.content)
                self.assertEqual(imported.status_code, 200, imported.text)
                opened = client.post('/api/workspace/open', json={'file': 'RestoredRecipe.openhmi.sqlite3'})
                self.assertEqual(opened.status_code, 200, opened.text)
                record = workspace.current.state.recipe_transfers.get(identifier)
                self.assertEqual(record['transaction']['state'], 'uncertain')
                self.assertEqual(record['snapshot']['transferred_by'], 'engineer')
                self.assertTrue(workspace.current.state.driver.plc_hold)
                self.assertEqual(workspace.current.state.driver._tags['CycleCommand']['RequestSequence'], 0)

    def test_concurrent_transfers_stage_and_commit_only_once(self):
        app, client = self.setup_app()
        revision = self.create(client)
        body = {'revision_id': revision['id'], 'expected_revision_version': revision['version'], 'reason': 'Concurrent transfer'}
        with patch.object(app.state.driver, 'write_command_request', wraps=app.state.driver.write_command_request) as writer:
            with ThreadPoolExecutor(max_workers=2) as pool:
                responses = list(pool.map(lambda _: client.post('/api/recipe-transfers/product/dispatch', json=body), range(2)))
            self.assertEqual(sorted(response.status_code for response in responses), [200, 409])
            self.assertEqual(writer.call_count, 1)
        self.assertEqual(len(app.state.recipe_transfers.recent()['items']), 1)
