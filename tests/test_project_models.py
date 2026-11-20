"""Project schemas remain usable independently of SQLite revision persistence."""
import inspect
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
import json, sys
from openhmi.project_models import Project, default_project
project = Project.model_validate(default_project().model_dump())
print(json.dumps({'title': project.title, 'store_loaded': 'openhmi.projects' in sys.modules,
                  'sqlite_loaded': 'sqlite3' in sys.modules}))
"""], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30, check=True)
        state = json.loads(result.stdout)
        self.assertEqual(state['title'], models.default_project().title)
        self.assertFalse(state['store_loaded'])
        self.assertFalse(state['sqlite_loaded'])

    def test_legacy_exports_and_canonical_requests_share_the_same_store_contract(self):
        exported = {name: item for name, item in vars(models).items()
                    if inspect.isclass(item) and issubclass(item, BaseModel)
                    and item.__module__ == models.__name__}
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
