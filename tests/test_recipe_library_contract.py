"""Consumed recipe-library fields match real SQL/HTTP lifecycle responses."""
from copy import deepcopy
import unittest

from openhmi.recipes import canonical
from tests.test_frontend_contract import frontend
from tests.test_recipe_mutation_contract import recipe_route_fixture
from tests.test_recipe_selection_contract import content


class RecipeLibraryContractTests(unittest.TestCase):
    def validate(self, libraries):
        return frontend('recipe_libraries', libraries=libraries)

    def post(self, client, path, **body):
        response = client.post(path, json={'reason': 'Offline library contract', **body})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_actual_revision_lifecycle_audit_and_typed_values_pass_without_source_reads(self):
        client, _, _, driver = recipe_route_fixture(self)
        libraries = [client.get('/api/recipes').json()]
        revision = self.post(client, '/api/recipes', code='FIXTURE', content=content())
        def capture(): libraries.append(client.get('/api/recipes').json())
        capture()
        for action in ('submit', 'approve', 'withdraw'):
            revision = self.post(client, f"/api/recipe-revisions/{revision['id']}/transition", action=action, expected_version=revision['version'])
            capture()
        for number in (2, 3):
            revision = self.post(client, f"/api/recipes/{revision['recipe_id']}/revisions", expected_latest_revision=revision['id'],
                                 parent_revision=revision['id'], content={**content(), 'title': f'Revision {number}'})
            capture()
        for action in ('submit', 'reject'):
            revision = self.post(client, f"/api/recipe-revisions/{revision['id']}/transition", action=action, expected_version=revision['version'])
            capture()
        self.assertEqual({item['status'] for library in libraries for item in library['revisions']},
                         {'draft', 'in_review', 'approved', 'withdrawn', 'superseded', 'rejected'})
        self.assertTrue(any(event['details'].get('changes') for library in libraries for event in library['audit']))
        self.assertEqual(self.validate(libraries), [True] * len(libraries))
        driver.read.assert_not_called()
        driver.load_recipe.assert_not_called()

    def test_historical_optional_fields_independent_selection_and_malformed_consumed_shapes(self):
        client, _, _, _ = recipe_route_fixture(self)
        for code in ('A', 'B'): self.post(client, '/api/recipes', code=code, content=content())
        library = client.get('/api/recipes').json()
        legacy = deepcopy(library)
        for revision in legacy['revisions']:
            for key in ('author', 'approved_by', 'approved_at'): revision.pop(key, None)
            for key in ('description', 'image_id'): revision['content'].pop(key, None)
            for parameter in revision['content']['parameters']: parameter.pop('unit', None)
        for event in legacy['audit']:
            event['actor'] = None
            event['details']['changes'] = None
        legacy['selection'] = {'not_consumed_by_workspace': True}
        legacy['gates']['editing']['permit_value'] = {'bad_sample': True}
        valid = [library, legacy]
        invalid = [None, {}, {**deepcopy(library), 'revisions': None},
                   {**deepcopy(library), 'revisions': list(reversed(library['revisions']))},
                   {**deepcopy(library), 'revisions': [library['revisions'][0]] * 2}]
        for path, value in [(('revisions', 0, 'id'), 2**53), (('revisions', 0, 'version'), 0),
            (('revisions', 0, 'status'), 'unknown'), (('revisions', 0, 'content', 'parameters'), None),
            (('revisions', 0, 'content', 'parameters', 0, 'value'), '12'),
            (('revisions', 0, 'approved_by'), {}), (('change_policy', 'policy', 'editing_enabled'), 'true'),
            (('gates', 'loading', 'allowed'), 'false'), (('gates', 'approval'), None),
            (('audit', 0, 'details', 'reason'), {}), (('audit', 0, 'details', 'changes'), [None])]:
            data = deepcopy(library)
            parent = data
            for key in path[:-1]: parent = parent[key]
            parent[path[-1]] = value
            invalid.append(data)
        self.assertEqual(self.validate(valid + invalid), [True] * len(valid) + [False] * len(invalid))

    def test_unavailable_or_non_boolean_permit_disables_gate_without_rejecting_library(self):
        client, service, _, driver = recipe_route_fixture(self)
        policy = client.get('/api/recipes').json()['change_policy']['policy']
        policy['editing_permit_tag'] = 'FixturePermit'
        with service.store.transaction() as db:
            db.execute('UPDATE recipe_policy SET content=? WHERE id=1', (canonical(policy),))
        libraries = [client.get('/api/recipes').json()]  # Mock read raises; snapshot records an unavailable permit.
        driver.read.side_effect = None
        for value in (12.0, False, True):
            driver.read.return_value = [value]
            libraries.append(client.get('/api/recipes').json())
        self.assertEqual([library['gates']['editing']['allowed'] for library in libraries], [False, False, False, True])
        self.assertEqual(self.validate(libraries), [True] * 4)
        driver.load_recipe.assert_not_called()


if __name__ == '__main__':
    unittest.main()
