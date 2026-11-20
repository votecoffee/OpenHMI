"""Project schemas remain usable independently of SQLite revision persistence."""
import inspect
import importlib
from typing import get_args
import json
from pathlib import Path
import subprocess
import sys
import unittest

from pydantic import BaseModel
from openhmi import project_models as models
from openhmi import projects as legacy


class ProjectModelTests(unittest.TestCase):
    def test_schema_validation_in_a_fresh_process_does_not_load_the_store(self):
        result = subprocess.run([sys.executable, '-c', """
import json, sys, importlib
from openhmi.canvas_models import CanvasLayout
from openhmi.identity_models import IdentityPublication
for family in ('readouts', 'images', 'inputs', 'process', 'machine', 'base'):
    importlib.import_module('openhmi.control_models_' + family)
family_loaded_project = 'openhmi.project_models' in sys.modules
from openhmi.project_models import Project, default_project
project = Project.model_validate(default_project().model_dump())
print(json.dumps({'title': project.title, 'store_loaded': 'openhmi.projects' in sys.modules,
                  'sqlite_loaded': 'sqlite3' in sys.modules, 'family_loaded_project': family_loaded_project,
                  'service_dependencies': [name for name in ('openhmi.canvas', 'openhmi.identity_publish',
                      'openhmi.canvas_routes', 'openhmi.identity_routes', 'PIL', 'fastapi', 'starlette') if name in sys.modules]}))
"""], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30, check=True)
        state = json.loads(result.stdout)
        self.assertEqual(state['title'], models.default_project().title)
        self.assertFalse(state['store_loaded'])
        self.assertFalse(state['sqlite_loaded'])
        self.assertFalse(state['family_loaded_project'])
        self.assertEqual(state['service_dependencies'], [])

    def test_layout_and_identity_models_keep_legacy_identity_and_project_roundtrips(self):
        from openhmi import canvas_models, canvas, identity_models, identity_publish
        for name in ('CanvasBox', 'CanvasContainer', 'CanvasDecoration', 'CanvasLayout'):
            self.assertIs(getattr(canvas, name), getattr(canvas_models, name))
        for name in ('PrivilegeBit', 'IdentityPublication'):
            self.assertIs(getattr(identity_publish, name), getattr(identity_models, name))
        self.assertIs(models.CanvasLayout, canvas_models.CanvasLayout)
        self.assertIs(legacy.CanvasLayout, canvas_models.CanvasLayout)
        self.assertIs(models.IdentityPublication, identity_models.IdentityPublication)
        self.assertIs(legacy.IdentityPublication, identity_models.IdentityPublication)
        candidate = models.default_project().model_dump()
        ids = [control['id'] for control in candidate['controls']]
        candidate['layout'] = {
            'boxes': {identifier: {'x': 8, 'y': 8 + index * 40, 'width': 120, 'height': 32}
                      for index, identifier in enumerate(ids)},
            'containers': {'grid_panel': {'x': 0, 'y': 0, 'width': 400, 'height': 400,
                                          'mode': 'grid', 'members': [ids[0]]}},
            'decorations': {'machine': {'x': 0, 'y': 0, 'width': 400, 'height': 400,
                                         'kind': 'rectangle', 'label': '机器', 'locked': True}},
        }
        candidate['identity_publication'] = {
            'enabled': True, 'username_tag': 'LoginName', 'privileges_tag': 'LoginBits',
            'bits': [{'bit': 0, 'source': 'group', 'name': 'Operators'},
                     {'bit': 31, 'source': 'permission', 'name': 'project.edit'}],
        }
        project = models.Project.model_validate(candidate)
        serialized = project.model_dump()
        self.assertEqual(legacy.Project.model_validate(serialized).model_dump(), serialized)
        self.assertEqual(canvas.CanvasLayout.model_validate(serialized['layout']), project.layout)
        self.assertEqual(identity_publish.IdentityPublication.model_validate(serialized['identity_publication']),
                         project.identity_publication)
        self.assertTrue(serialized['layout']['decorations']['machine']['locked'])
        self.assertEqual(serialized['layout']['containers']['grid_panel']['members'], [ids[0]])
        self.assertEqual(serialized['identity_publication']['bits'][1]['bit'], 31)

    def test_control_family_exports_share_the_canonical_union(self):
        family_models = set()
        for family in ('base', 'machine', 'inputs', 'images', 'process', 'readouts'):
            module = importlib.import_module('openhmi.control_models_' + family)
            owned = {name: item for name, item in vars(module).items()
                     if inspect.isclass(item) and issubclass(item, BaseModel)
                     and item.__module__ == module.__name__}
            self.assertTrue(owned, family)
            for name, item in owned.items():
                with self.subTest(family=family, model=name):
                    self.assertIs(getattr(models, name), item)
                    self.assertIs(getattr(legacy, name), item)
            self.assertFalse(family_models & set(owned.values()))
            family_models.update(owned.values())
        union_models = get_args(get_args(models.Control)[0])
        self.assertTrue(union_models)
        self.assertTrue(set(union_models) <= family_models)
        self.assertIs(models.StateCode, importlib.import_module('openhmi.control_models_base').StateCode)

    def test_legacy_exports_and_canonical_requests_share_the_same_store_contract(self):
        exported = {name: item for name, item in vars(models).items()
                    if inspect.isclass(item) and issubclass(item, BaseModel)
                    and item.__module__.startswith('openhmi.')}
        exported.update({name: getattr(models, name) for name in ('Control', 'StateCode', 'default_project')})
        self.assertTrue(exported)
        for name, item in exported.items():
            with self.subTest(name=name):
                self.assertIs(getattr(legacy, name), item)
        initial = models.default_project()
        store = legacy.ProjectStore(initial_project=initial)
        self.addCleanup(store.close)
        candidate = initial.model_copy(deep=True)
        candidate.title = '设备 - revised'
        saved = store.save(models.SaveRequest(expected_revision=1, project=candidate))
        self.assertEqual(saved['draft_revision'], 2)
        self.assertEqual(saved['active']['title'], initial.title)
        applied = store.apply(legacy.ApplyRequest(expected_revision=2, reason='Schema/store boundary'))
        self.assertEqual(applied['active_revision'], 2)
        self.assertEqual(applied['active']['title'], candidate.title)
        self.assertEqual(store.revision(2)['project'], candidate.model_dump())
        self.assertEqual(store.revision(2)['reason'], 'Schema/store boundary')


if __name__ == '__main__':
    unittest.main()
