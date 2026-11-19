"""Runtime behavior across subscription and sample-cache ownership boundaries."""
import unittest

from openhmi.logix import RuntimeDriver
from openhmi.projects import Project
from tests.test_logix_history import FakePLC, logix_project


class TagStateTests(unittest.TestCase):
    def driver(self, project=None):
        driver = RuntimeDriver(FakePLC)
        self.addCleanup(driver.close)
        driver.configure(Project.model_validate(project or logix_project()).model_dump())
        return driver

    def test_shared_demand_survives_viewer_expiry_and_ordered_release(self):
        project = logix_project()
        project['alarms'].append({'id': 'speed_alarm', 'tag': 'MotorA.Speed', 'message': 'Speed alarm'})
        project['historian']['tags'] = [{'tag': 'MotorA.Speed', 'sample_ms': 1000, 'deadband': 0}]
        driver = self.driver(project)
        driver.trend_demands = {'MotorA.Speed': 180}
        driver.lease('viewer', ['fast'], 1, sequence=1)
        self.assertEqual(driver.demands(1)['MotorA.Speed'], 100)
        self.assertEqual(driver.demands(16)['MotorA.Speed'], 180)
        driver.trend_demands = {}
        self.assertEqual(driver.demands(16)['MotorA.Speed'], 250)
        project['alarms'] = [alarm for alarm in project['alarms'] if alarm['id'] != 'speed_alarm']
        driver.configure(Project.model_validate(project).model_dump())
        self.assertEqual(driver.demands(16)['MotorA.Speed'], 1000)
        driver.lease('viewer', ['fast'], 16, sequence=2)
        self.assertEqual(driver.demands(16)['MotorA.Speed'], 100)
        driver.lease('viewer', [], 16, sequence=3)
        driver.lease('viewer', ['fast'], 16, sequence=2)
        self.assertEqual(driver.demands(16)['MotorA.Speed'], 1000)

    def test_snapshot_isolation_and_legacy_dictionary_replacement(self):
        first, second = self.driver(), self.driver()
        first.lease('viewer', ['fast'], 1)
        first.poll(1)
        view = first.sample_snapshot(1)
        self.assertEqual(view['MotorA.Speed']['value'], 42.0)
        view['MotorA']['value']['Speed'] = -999
        self.assertEqual(first.sample_snapshot(1)['MotorA']['value']['Speed'], 42.0)
        self.assertEqual(second.sample_snapshot(1)['MotorA.Speed']['quality'], 'pending')
        self.assertNotIn('MotorA.Speed', second.demands(1))
        # Extensions historically inspect and sometimes replace these mappings.
        cache = dict(first.samples)
        first.samples = cache
        cache['MotorA.Speed'] = {**cache['MotorA.Speed'], 'value': 55.0}
        self.assertEqual(first.sample_snapshot(1)['MotorA.Speed']['value'], 55.0)
        self.assertEqual(first.sample_snapshot(4)['MotorA.Speed']['quality'], 'stale')
        self.assertEqual(second.sample_snapshot(1)['MotorA.Speed']['quality'], 'pending')
        metadata = first.sample_snapshot(1, include_values=False)
        self.assertTrue(all('value' not in sample for sample in metadata.values()))
        first.leases = {}
        self.assertNotIn('MotorA.Speed', first.demands(1))
        first.close()
        self.assertEqual(cache, {})


if __name__ == '__main__':
    unittest.main()
