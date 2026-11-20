"""Offline catalog reconciliation and route diagnostics regression checks."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from openhmi.logix import RuntimeDriver
from openhmi.projects import Project
from tests.test_logix_history import FakePLC, logix_project


class DriverConfigurationTests(unittest.TestCase):
    def driver(self, project):
        driver = RuntimeDriver(FakePLC)
        self.addCleanup(driver.close)
        driver.configure(Project.model_validate(project).model_dump())
        return driver

    def test_unchanged_local_edits_survive_apply_and_changed_initials_reset(self):
        project = logix_project()
        project['tags'].extend([
            {'name': 'Setpoint', 'type': 'number', 'initial': 10, 'writable': True},
            {'name': 'LocalUnit', 'type': 'struct', 'writable': True,
             'initial': {'Run': False, 'Speed': 2.0},
             'members': {'Run': 'boolean', 'Speed': 'number'}},
        ])
        driver = self.driver(project)
        driver.lease('viewer', ['fast', 'slow'], 1)
        driver.poll(1)
        cached = driver.samples['MotorA.Speed']
        route = driver.connections['plc']
        driver.write('Setpoint', [25.0])
        driver.write('LocalUnit.Run', [True])
        candidate = deepcopy(driver.project)
        candidate['screens'][0]['title'] = 'Renamed screen'
        driver.configure(candidate)
        self.assertIs(driver.connections['plc'], route)
        self.assertIs(driver.samples['MotorA.Speed'], cached)
        self.assertEqual(driver.read('Setpoint'), [25.0])
        self.assertEqual(driver.read('LocalUnit.Run'), [True])
        self.assertIs(type(driver.read('Setpoint')[0]), float)
        candidate['tags'][-1]['initial']['Speed'] = 99.0
        self.assertEqual(driver.read('LocalUnit.Speed'), [2.0])
        driver.configure(candidate)
        self.assertEqual(driver.read('LocalUnit.Run'), [False])
        self.assertEqual(driver.read('LocalUnit.Speed'), [99.0])
        candidate['tags'] = [tag for tag in candidate['tags'] if tag['name'] != 'Setpoint']
        driver.configure(candidate)
        self.assertNotIn('Setpoint', driver.snapshot())
        self.assertNotIn('Setpoint', driver.local_names)

    def test_route_replacement_discards_its_samples_and_closes_outside_state_lock(self):
        project = logix_project()
        project['connections'].append({**project['connections'][0], 'id': 'other', 'path': 'other-offline/0'})
        project['tags'].append({'name': 'OtherLevel', 'connection': 'other', 'address': 'Level', 'type': 'number'})
        project['screens'][1]['controls'].append(
            {'id': 'other-level', 'kind': 'numeric', 'label': 'Other', 'tag': 'OtherLevel'})
        driver = self.driver(project)
        driver.lease('viewer', ['fast', 'slow'], 1)
        driver.poll(1)
        retired = driver.connections['plc']
        old_client = retired.client
        other = driver.connections['other']
        other_sample = driver.samples['OtherLevel']
        replacement = deepcopy(driver.project)
        replacement['connections'][0]['path'] = 'replacement-offline/0'
        original_close = retired.close
        def close_retired():
            self.assertFalse(driver.lock._is_owned())
            self.assertTrue(driver.io_lock._is_owned())
            original_close()
        with patch.object(retired, 'close', side_effect=close_retired) as close:
            driver.configure(replacement)
            close.assert_called_once_with()
        self.assertTrue(old_client.closed)
        self.assertIsNot(driver.connections['plc'], retired)
        self.assertIs(driver.connections['other'], other)
        self.assertIs(driver.samples['OtherLevel'], other_sample)
        self.assertNotIn('MotorA.Speed', driver.samples)
        self.assertEqual(driver.sample_snapshot(1)['MotorA.Speed']['quality'], 'pending')
        driver.poll(1.1)
        self.assertEqual(driver.sample_snapshot(1.1)['MotorA.Speed']['quality'], 'good')
        driver.plc_hold = True
        driver.configure(replacement)
        self.assertEqual(driver.connections, {})
        self.assertEqual(driver.sample_snapshot(1.1)['OtherLevel']['quality_reason'], 'held')

    def test_legacy_catalog_maps_remain_live_after_replacement(self):
        driver = self.driver(logix_project())
        for name in ('definitions', 'sources', 'address_aliases'):
            replacement = dict(getattr(driver, name))
            setattr(driver, name, replacement)
            self.assertIs(getattr(driver.tag_catalog, name), replacement)
            self.assertIs(getattr(driver, name), replacement)
        local_names = set(driver.local_names)
        driver.local_names = local_names
        self.assertIs(driver.tag_catalog.local_names, local_names)
        driver.address_aliases[('plc', 'Motor')].append(
            ('ExtraSpeed', driver.definitions['MotorA'], 'Speed'))
        driver.sources['ExtraSpeed'] = ('MotorA', 'Speed')
        driver.lease('viewer', ['fast'], 1)
        driver.poll(1)
        self.assertEqual(driver.sample_snapshot(1)['ExtraSpeed']['value'], 42.0)
        second = self.driver(logix_project())
        self.assertNotIn('ExtraSpeed', second.sources)

    def test_route_status_options_are_independent_and_skip_unrequested_work(self):
        driver = self.driver(logix_project())
        connection = driver.connections['plc']
        with patch.object(connection.timings, 'snapshot') as timing, \
                patch.object(driver, '_has_usable_data') as usable:
            initial = driver.status(now=1, include_groups=False)
            timing.assert_not_called()
            usable.assert_not_called()
        self.assertNotIn('groups', initial[0])
        self.assertNotIn('timings', initial[0])
        driver.lease('viewer', ['fast', 'slow'], 1)
        driver.poll(1)
        connection.timings.record('catalog_test', 0.125)
        first = driver.status(now=1, include_timing=True)
        self.assertEqual(first[0]['groups'], [
            {'rate_ms': 100, 'addresses': ['Motor']},
            {'rate_ms': 1000, 'addresses': ['Level']},
        ])
        self.assertFalse(first[0]['data_unavailable'])
        first[0]['groups'][0]['addresses'].append('invented')
        first[0]['timings']['catalog_test']['last_ms'] = -1
        second = driver.status(now=5, include_timing=True)
        self.assertNotIn('invented', second[0]['groups'][0]['addresses'])
        self.assertEqual(second[0]['timings']['catalog_test']['last_ms'], 125)
        self.assertTrue(second[0]['data_unavailable'])
        self.assertFalse(second[0]['recovering'])
        connection.outage_started = 1
        with patch.object(driver, '_has_usable_data') as usable:
            recovering = driver.status(now=5)
            usable.assert_not_called()
        self.assertTrue(recovering[0]['recovering'])
        self.assertFalse(recovering[0]['data_unavailable'])


if __name__ == '__main__':
    unittest.main()
