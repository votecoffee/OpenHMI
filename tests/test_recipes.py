from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError
from openhmi.recipe_auth import hash_password
from openhmi.recipe_models import RecipeParameter
from openhmi.server import create_app

# Deliberately synthetic accounts for tests only. The application has no default users.
PASSWORD = 'RecipeTestOnly-2026!'
ENCODED = hash_password(PASSWORD)
USERS = {'users': [
    {'name': 'engineer', 'roles': ['engineer', 'approver', 'operator'], 'password_hash': ENCODED},
    {'name': 'operator', 'roles': ['operator'], 'password_hash': ENCODED},
    {'name': 'manager', 'roles': ['administrator'], 'password_hash': ENCODED},
]}


def recipe_content(value=45.0):
    return {'title': 'Product A', 'description': 'Synthetic test recipe', 'image_id': None,
            'parameters': [{'name': 'speed', 'label': 'Speed', 'type': 'number', 'value': value, 'unit': 'rpm', 'minimum': 0.0, 'maximum': 100.0}]}


class RecipeTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(recipe_users=USERS)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def login(self, name='engineer'):
        response = self.client.post('/api/recipe-auth/login', json={'name': name, 'password': PASSWORD})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('HttpOnly', response.headers['set-cookie'])
        self.assertIn('SameSite=strict', response.headers['set-cookie'])

    def create(self, code='A', content=None):
        response = self.client.post('/api/recipes', json={'code': code, 'content': content or recipe_content(), 'reason': 'Initial setup'})
        response.raise_for_status()
        return response.json()

    def transition(self, revision, action):
        response = self.client.post(f'/api/recipe-revisions/{revision["id"]}/transition', json={'action': action, 'expected_version': revision['version'], 'reason': f'{action} for test'})
        response.raise_for_status()
        return response.json()

    def load(self, revision):
        selected = self.client.get('/api/recipes/selected').json()
        response = self.client.post('/api/recipes/select', json={'revision_id': revision['id'], 'expected_revision_version': revision['version'],
                                                                'expected_selection_version': selected['version'], 'reason': 'Load test copy'})
        response.raise_for_status()
        return response.json()

    def test_identity_roles_self_approval_and_unapproved_loading_while_running(self):
        anonymous = self.client.post('/api/recipes', json={'code': 'X', 'content': recipe_content(), 'reason': 'test'})
        self.assertEqual(anonymous.status_code, 401)
        self.assertEqual(self.client.post('/api/recipe-auth/login', json={'name': 'engineer', 'password': 'wrong'}).status_code, 401)
        self.login()
        revision = self.create()
        self.assertTrue(self.app.state.driver.read('MotorRunning')[0])
        self.assertFalse(self.load(revision)['snapshot']['production_approved'])
        self.assertFalse(self.app.state.driver.read('RecipeProductionApproved')[0])
        revision = self.transition(revision, 'submit')
        approved = self.transition(revision, 'approve')
        self.assertEqual(approved['approved_by'], 'engineer')
        self.assertIsNotNone(approved['approved_at'])
        self.assertFalse(self.app.state.driver.read('RecipeProductionApproved')[0], 'Approval must not mutate a copy already loaded for testing')
        self.assertTrue(self.load(approved)['snapshot']['production_approved'])
        self.login('operator')
        denied = self.client.post('/api/recipe-revisions/%d/transition' % approved['id'], json={'action': 'withdraw', 'expected_version': approved['version'], 'reason': 'No authority'})
        self.assertEqual(denied.status_code, 403)
        denied = self.client.put('/api/recipes/policy', json={'expected_version': 1, 'policy': {}, 'reason': 'No authority'})
        self.assertEqual(denied.status_code, 403)
        self.client.post('/api/recipe-auth/logout', json={}).raise_for_status()
        self.assertIsNone(self.client.get('/api/recipe-auth/session').json()['user'])

    def test_new_revision_withdrawal_and_load_clear_preserve_independent_copy(self):
        self.login()
        original = self.transition(self.transition(self.create(), 'submit'), 'approve')
        self.load(original)
        response = self.client.post(f'/api/recipes/{original["recipe_id"]}/revisions', json={'expected_latest_revision': original['id'], 'parent_revision': original['id'], 'content': recipe_content(80.0), 'reason': 'Increase speed'})
        response.raise_for_status()
        draft = response.json()
        self.assertEqual(draft['status'], 'draft')
        self.assertIsNone(draft['approved_by'])
        self.assertNotEqual(draft['content_hash'], original['content_hash'])
        copy = self.app.state.driver.recipe_copy()
        self.assertEqual(copy['content']['parameters'][0]['value'], 45.0)
        self.assertTrue(copy['production_approved'])
        self.transition(original, 'withdraw')
        self.assertTrue(self.app.state.driver.recipe_copy()['production_approved'])
        self.load(draft)
        self.assertEqual(self.app.state.driver.recipe_copy()['content']['parameters'][0]['value'], 80.0)
        self.assertFalse(self.app.state.driver.read('RecipeProductionApproved')[0])
        selected = self.client.get('/api/recipes/selected').json()
        self.client.post('/api/recipes/select', json={'revision_id': None, 'expected_selection_version': selected['version'], 'reason': 'Clear copy'}).raise_for_status()
        self.assertIsNone(self.app.state.driver.recipe_copy())
        audit = self.client.get('/api/recipes').json()['audit']
        change = next(event for event in audit if event['operation'] == 'content_saved')
        self.assertIn({'field': 'parameters.speed.value', 'before': 45.0, 'after': 80.0}, change['details']['changes'])

    def test_stale_requests_review_freeze_and_content_integrity(self):
        self.login()
        draft = self.create()
        review = self.transition(draft, 'submit')
        payload = {'expected_latest_revision': draft['id'], 'parent_revision': draft['id'], 'content': recipe_content(50.0), 'reason': 'During review'}
        self.assertEqual(self.client.post(f'/api/recipes/{draft["recipe_id"]}/revisions', json=payload).status_code, 409)
        self.assertEqual(self.client.post(f'/api/recipe-revisions/{draft["id"]}/transition', json={'action': 'approve', 'expected_version': draft['version'], 'reason': 'Stale review'}).status_code, 409)
        self.transition(review, 'reject')
        new = self.client.post(f'/api/recipes/{draft["recipe_id"]}/revisions', json=payload).json()
        self.assertEqual(self.client.post(f'/api/recipes/{draft["recipe_id"]}/revisions', json=payload).status_code, 409)
        loaded = self.load(new)
        self.assertEqual(self.client.post('/api/recipes/select', json={'revision_id': new['id'], 'expected_revision_version': new['version'], 'expected_selection_version': loaded['version'] - 1, 'reason': 'Stale load'}).status_code, 409)
        with self.app.state.store.transaction() as db:
            db.execute("UPDATE recipe_revision SET content_hash='bad' WHERE id=?", (new['id'],))
        self.assertEqual(self.client.post('/api/recipes/select', json={'revision_id': new['id'], 'expected_revision_version': new['version'], 'expected_selection_version': loaded['version'], 'reason': 'Corrupt content'}).status_code, 409)

    def test_change_policy_and_optional_permit_are_server_enforced(self):
        self.login()
        draft = self.create()
        self.login('manager')
        state = self.client.get('/api/recipes').json()
        policy = state['change_policy']['policy']
        policy['editing_enabled'] = False
        self.client.put('/api/recipes/policy', json={'expected_version': 1, 'policy': policy, 'reason': 'Freeze engineering changes'}).raise_for_status()
        self.login()
        self.assertEqual(self.client.post('/api/recipes', json={'code': 'B', 'content': recipe_content(), 'reason': 'Attempt during freeze'}).status_code, 423)
        self.load(draft)  # Editing freeze does not freeze loading or protect the running PLC copy.
        self.login('manager')
        policy['editing_enabled'] = True
        policy['loading_permit_tag'] = 'RecipeChangeAllowed'
        self.client.put('/api/recipes/policy', json={'expected_version': 2, 'policy': policy, 'reason': 'Add application permit'}).raise_for_status()
        selected = self.client.get('/api/recipes/selected').json()
        self.assertEqual(self.client.post('/api/recipes/select', json={'revision_id': draft['id'], 'expected_revision_version': draft['version'], 'expected_selection_version': selected['version'], 'reason': 'Blocked permit'}).status_code, 423)
        self.client.post('/api/recipes/simulator-permit', json={'allowed': True, 'reason': 'Enable test permit'}).raise_for_status()
        self.load(draft)
        self.assertEqual(self.client.put('/api/recipes/policy', json={'expected_version': 1, 'policy': policy, 'reason': 'Stale policy'}).status_code, 409)

    def test_images_are_normalized_bound_to_revision_and_inputs_are_validated(self):
        self.login()
        image = BytesIO()
        Image.new('RGB', (64, 48), '#999999').save(image, format='PNG')
        upload = self.client.post('/api/recipe-images?reason=Product%20reference', content=image.getvalue(), headers={'content-type': 'image/png'})
        upload.raise_for_status()
        content = recipe_content()
        content['image_id'] = upload.json()['image_id']
        draft = self.create(content=content)
        self.assertEqual(draft['content']['image_id'], content['image_id'])
        self.assertEqual(self.client.get('/api/recipe-images/' + content['image_id']).headers['content-type'], 'image/png')
        self.assertEqual(self.client.post('/api/recipe-images?reason=bad', content=b'not an image', headers={'content-type': 'image/png'}).status_code, 422)
        self.assertEqual(self.client.post('/api/recipe-images?reason=bad', content=b'<svg/>', headers={'content-type': 'image/svg+xml'}).status_code, 415)
        self.assertEqual(self.client.post('/api/recipe-images?reason=%20', content=image.getvalue(), headers={'content-type': 'image/png'}).status_code, 422)
        for invalid in [True, '45']:
            invalid_content = recipe_content()
            invalid_content['parameters'][0]['value'] = invalid
            self.assertEqual(self.client.post('/api/recipes', json={'code': 'bad', 'content': invalid_content, 'reason': 'Invalid value'}).status_code, 422)
        for invalid in [float('inf'), float('nan')]:
            with self.assertRaises(ValidationError):
                RecipeParameter(name='bad', label='Bad', type='number', value=invalid)
        with self.assertRaises(ValidationError):
            RecipeParameter(name='bad', label='Bad', type='integer', value=2**60)
        too_high = recipe_content(101.0)
        self.assertEqual(self.client.post('/api/recipes', json={'code': 'bad', 'content': too_high, 'reason': 'Outside limits'}).status_code, 422)
        self.assertEqual(self.client.post('/api/recipes', json={'code': 'A', 'content': content, 'reason': ' '}).status_code, 422)
        self.assertEqual(self.client.post('/api/recipes', json={'code': 'A', 'content': content, 'reason': 'Spoof', 'approved_by': 'manager'}).status_code, 422)
        self.assertEqual(self.client.post('/api/recipes', json={'code': 'C', 'content': content, 'reason': 'Cross site'}, headers={'origin': 'https://example.invalid'}).status_code, 403)

    def test_revision_image_and_loaded_copy_survive_restart(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'recipe.sqlite3'
            first = create_app(path, recipe_users=USERS)
            with TestClient(first) as client:
                client.post('/api/recipe-auth/login', json={'name': 'engineer', 'password': PASSWORD}).raise_for_status()
                image = BytesIO()
                Image.new('RGB', (30, 20), 'gray').save(image, 'PNG')
                image_id = client.post('/api/recipe-images?reason=Reference', content=image.getvalue(), headers={'content-type': 'image/png'}).json()['image_id']
                content = recipe_content()
                content['image_id'] = image_id
                revision = client.post('/api/recipes', json={'code': 'PERSIST', 'content': content, 'reason': 'Persistence test'}).json()
                client.post('/api/recipes/select', json={'revision_id': revision['id'], 'expected_revision_version': 1, 'expected_selection_version': 1, 'reason': 'Copy test recipe'}).raise_for_status()
            second = create_app(path, recipe_users=USERS)
            with TestClient(second) as client:
                state = client.get('/api/recipes').json()
                self.assertEqual(state['selection']['snapshot']['code'], 'PERSIST')
                self.assertEqual(state['selection']['snapshot']['content']['image_id'], image_id)
                self.assertEqual(second.state.driver.recipe_copy()['content']['parameters'][0]['value'], 45.0)
                self.assertEqual(client.get('/api/recipe-images/' + image_id).status_code, 200)
                self.assertIsNone(client.get('/api/recipe-auth/session').json()['user'])


if __name__ == '__main__': unittest.main()
