"""Real draft catalog and binding checks against the production browser pickers."""
import copy
import unittest

from fastapi.testclient import TestClient
from openhmi.server import create_app
from tests.test_frontend_contract import frontend


class EngineeringContractTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(hold_connections=True)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.state = self.client.get('/api/project').json()
        project = copy.deepcopy(self.state['draft'])
        project['connections'] = [{'id': 'catalogplc', 'name': 'Disabled fixture',
                                   'path': 'offline-only/0', 'enabled': False}]
        project['tags'] += [
            {'name': 'CatalogInt', 'type': 'integer', 'initial': 7, 'writable': True},
            {'name': 'CatalogScaled', 'type': 'integer', 'initial': 3, 'writable': True,
             'scale': 2.0, 'connection': 'catalogplc', 'address': 'Scaled'},
            {'name': 'CatalogReadOnly', 'type': 'integer', 'initial': 8},
            {'name': 'CatalogText', 'type': 'string', 'initial': 'part', 'writable': True},
            {'name': 'CatalogUnit', 'type': 'struct', 'writable': True, 'udt_type': 'CatalogUDT',
             'initial': {'Ready': True, 'Count': 4, 'Speed': 2.5, 'Name': 'part'},
             'members': {'Ready': 'boolean', 'Count': 'integer', 'Speed': 'number', 'Name': 'string'}},
        ]
        saved = self.client.put('/api/project/draft', json={
            'expected_revision': self.state['draft_revision'], 'project': project})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.state = saved.json()

    def test_draft_catalog_normalization_and_template_picker_types(self):
        catalog = self.client.get('/api/catalog').json()
        raw = {tag['name']: tag for tag in catalog['tags']}
        self.assertEqual(raw['CatalogUnit.Count']['type'], 'number')
        self.assertNotIn('CatalogInt', {tag['name'] for tag in self.client.get('/api/project/active').json()['project']['tags']})
        self.assertNotIn('CatalogInt', self.client.get('/api/tags').json()['values'])
        result = frontend('engineering', catalog=catalog, project=self.state['draft'])
        tags = {tag['name']: tag for tag in result['catalog']['tags']}
        self.assertEqual(len(tags), len(result['catalog']['tags']))
        self.assertTrue(tags['CatalogInt']['integer'])
        self.assertTrue(tags['CatalogInt']['writable'])
        self.assertTrue(tags['CatalogInt']['unscaled'])
        self.assertFalse(tags['CatalogScaled']['unscaled'])
        self.assertTrue(tags['CatalogUnit.Count']['integer'])
        self.assertTrue(tags['CatalogUnit.Count']['writable'])
        self.assertEqual(tags['CatalogUnit.Name']['type'], 'string')
        modes = {option['value'] for option in result['modeTags']}
        sliders = {option['value'] for option in result['sliderTags']}
        self.assertTrue({'CatalogInt', 'CatalogUnit.Count'} <= modes)
        self.assertFalse({'CatalogScaled', 'CatalogReadOnly', 'CatalogText'} & modes)
        self.assertTrue({'CatalogInt', 'CatalogUnit.Speed'} <= sliders)
        self.assertFalse({'CatalogScaled', 'CatalogReadOnly', 'CatalogText'} & sliders)
        template = {'id': 'unit', 'name': 'Unit', 'members': {'Count': 'integer', 'Ready': 'boolean'}}
        preview = frontend('engineering', catalog=catalog, project=self.state['draft'], template=template)
        self.assertIn('$.Count', {option['value'] for option in preview['modeTags']})
        self.assertNotIn('$.Ready', {option['value'] for option in preview['modeTags']})
        self.assertNotIn('Faceplate', preview['components'])

    def test_picker_compatible_bindings_save_and_invalid_edits_preserve_draft(self):
        project = copy.deepcopy(self.state['draft'])
        project['controls'].append({'id': 'catalog_time', 'kind': 'date_time', 'label': 'Catalog time',
                                    'tag': 'CatalogInt'})
        result = self.client.put('/api/project/draft', json={
            'expected_revision': self.state['draft_revision'], 'project': project})
        result.raise_for_status()
        expected = result.json()
        for invalid in ('CatalogScaled', 'CatalogReadOnly', 'CatalogText', 'MissingMember'):
            candidate = copy.deepcopy(expected['draft'])
            candidate['controls'][-1]['tag'] = invalid
            rejected = self.client.put('/api/project/draft', json={
                'expected_revision': expected['draft_revision'], 'project': candidate})
            with self.subTest(tag=invalid):
                self.assertEqual(rejected.status_code, 422, rejected.text)
                self.assertEqual(self.client.get('/api/project').json()['draft'], expected['draft'])
                self.assertEqual(self.client.get('/api/project').json()['draft_revision'], expected['draft_revision'])


if __name__ == '__main__':
    unittest.main()
