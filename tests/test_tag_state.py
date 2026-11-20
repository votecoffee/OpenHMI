"""Runtime behavior across subscription and sample-cache ownership boundaries."""
import unittest
from threading import Event

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

    def test_legacy_deadline_mapping_controls_the_next_physical_read(self):
        driver = self.driver()
        driver.lease('viewer', ['fast'], 1)
        driver.poll(1)
        plc = driver.connections['plc'].client
        deadlines = {('plc', 'Motor'): 100}
        driver.deadlines = deadlines
        driver.poll(2)
        self.assertEqual(plc.reads, [('Motor',)])
        self.assertEqual(driver.last_rates[('plc', 'Motor')], 100)
        plc.values['Motor']['Speed'] = 66.0
        driver.deadlines.clear()
        driver.poll(2.1)
        self.assertEqual(plc.reads, [('Motor',), ('Motor',)])
        self.assertEqual(driver.sample_snapshot(2.1)['MotorA.Speed']['value'], 66.0)
        self.assertGreater(deadlines[('plc', 'Motor')], 2.1)
        driver.close()
        self.assertEqual(deadlines, {})

    def test_publication_uses_current_requested_members_after_screen_change(self):
        entered, release = Event(), Event()

        class BlockingPLC(FakePLC):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.values['Motor']['Speed'] = 'bad numeric member'

            def read(self, *addresses):
                entered.set()
                if not release.wait(5):
                    raise TimeoutError('Test did not release the read')
                return super().read(*addresses)

        driver = RuntimeDriver(BlockingPLC)
        self.addCleanup(driver.close)
        self.addCleanup(release.set)
        driver.configure(logix_project())
        driver.lease('viewer', ['fast'], 1)
        driver.poll(1, wait=False)
        self.assertTrue(entered.wait(5))
        scan = driver._scans['plc']
        driver.lease('viewer', ['slow'], 1.1)
        driver.poll(1.1, wait=False)
        release.set()
        scan.result(timeout=5)
        samples = driver.sample_snapshot(1.1)
        self.assertEqual(samples['MotorA.Running']['quality'], 'good')
        self.assertEqual(samples['MotorA.Speed']['quality'], 'bad')
        self.assertFalse(driver.status(now=1.1)[0]['awaiting_data'])
        self.assertFalse(driver.status(now=1.1)[0]['data_unavailable'])
        driver.poll(2)
        reads = driver.connections['plc'].client.reads
        self.assertEqual(sum('Motor' in batch for batch in reads), 2)


if __name__ == '__main__':
    unittest.main()
