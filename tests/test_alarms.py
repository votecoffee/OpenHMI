from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest

from fastapi.testclient import TestClient
from openhmi.alarms import AlarmMonitor, trigger_condition
from openhmi.projects import AlarmDefinition, Project, ProjectStore, RevisionRequest, SaveRequest
from openhmi.server import create_app


class AlarmTests(unittest.TestCase):
    def setup_monitor(self, path=None):
        store = ProjectStore(path)
        self.addCleanup(store.close)
        values = {'ProcessAlarm': False}
        monitor = AlarmMonitor(store, lambda: values.copy())
        monitor.sample()
        return store, values, monitor

    def test_acknowledgement_does_not_clear_condition_and_retrigger_is_distinct(self):
        _, values, monitor = self.setup_monitor()
        values['ProcessAlarm'] = True
        monitor.sample()
        first = monitor.snapshot()['outstanding'][0]['occurrence_id']
        for _ in range(3): monitor.sample()
        self.assertEqual(len(monitor.snapshot()['occurrences']), 1)
        monitor.acknowledge(first)
        monitor.acknowledge(first)
        self.assertTrue(values['ProcessAlarm'])
        self.assertEqual(monitor.snapshot()['active_count'], 1)
        self.assertEqual(monitor.snapshot()['unacknowledged_count'], 0)
        values['ProcessAlarm'] = False
        monitor.sample()
        self.assertFalse(monitor.snapshot()['outstanding'])
        values['ProcessAlarm'] = True
        monitor.sample()
        values['ProcessAlarm'] = False
        monitor.sample()
        values['ProcessAlarm'] = True
        monitor.sample()
        state = monitor.snapshot()
        self.assertEqual(state['active_count'], 1)
        self.assertEqual(state['unacknowledged_count'], 2)
        self.assertEqual(len(state['occurrences']), 3)
        self.assertEqual(sum(event['event'] == 'acknowledged' for event in state['history']), 1)

    def test_bit_positions_signed_word_and_lsbit(self):
        def definition(mode, value):
            return AlarmDefinition(id='test', tag='word', trigger_type=mode, trigger_value=value, message='test')
        self.assertTrue(trigger_condition(definition('bit', 1), 1))
        self.assertFalse(trigger_condition(definition('bit', 1), 2))
        self.assertTrue(trigger_condition(definition('bit', 32), -2147483648))
        self.assertTrue(trigger_condition(definition('lsbit', 2), 6))
        self.assertFalse(trigger_condition(definition('lsbit', 3), 6))
        self.assertTrue(trigger_condition(definition('lsbit', 3), 4))
        self.assertIsNone(trigger_condition(definition('bit', 1), True))
        self.assertIsNone(trigger_condition(definition('lsbit', 1), 1.0))
        self.assertIsNone(trigger_condition(definition('value', 1), float('nan')))
        self.assertTrue(trigger_condition(definition('value', -2), -2))

    def test_bad_quality_never_invents_a_return_and_config_removal_is_explicit(self):
        store, values, monitor = self.setup_monitor()
        values['ProcessAlarm'] = True
        monitor.sample()
        values['ProcessAlarm'] = None
        monitor.sample()
        state = monitor.snapshot()
        self.assertEqual(state['states']['process_alarm']['quality'], 'bad')
        self.assertEqual(state['active_count'], 1)
        self.assertIsNone(state['outstanding'][0]['returned_at'])
        project = Project.model_validate(store.snapshot()['active'])
        project.alarms = []
        saved = store.save(SaveRequest(expected_revision=1, project=project))
        store.apply(RevisionRequest(expected_revision=saved['draft_revision']))
        monitor.sample()
        retired = monitor.snapshot()['outstanding'][0]
        self.assertIsNotNone(retired['retired_at'])
        self.assertIsNone(retired['returned_at'])
        self.assertEqual(monitor.snapshot()['unacknowledged_count'], 1)
        monitor.acknowledge(retired['occurrence_id'])
        self.assertFalse(monitor.snapshot()['outstanding'])

    def test_pending_history_survives_retention_and_restart(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'alarms.sqlite3'
            store = ProjectStore(path)
            values = {'ProcessAlarm': False}
            monitor = AlarmMonitor(store, lambda: values)
            project = Project.model_validate(store.snapshot()['active'])
            project.alarm_history_limit = 50
            saved = store.save(SaveRequest(expected_revision=1, project=project))
            store.apply(RevisionRequest(expected_revision=saved['draft_revision']))
            for _ in range(55):
                values['ProcessAlarm'] = True
                monitor.sample()
                values['ProcessAlarm'] = False
                monitor.sample()
            self.assertEqual(len(monitor.snapshot()['history']), 50)
            self.assertEqual(len(monitor.snapshot()['outstanding']), 55)
            store.close()
            restored, _, next_monitor = self.setup_monitor(path)
            self.assertEqual(next_monitor.snapshot()['unacknowledged_count'], 55)
            next_monitor.acknowledge()
            next_monitor.sample()
            self.assertEqual(len(next_monitor.snapshot()['occurrences']), 50)
            self.assertFalse(next_monitor.snapshot()['outstanding'])
            restored.close()

    def test_background_monitor_and_api_work_without_runtime_views(self):
        app = create_app()
        with TestClient(app) as client:
            app.state.driver.write('ProcessAlarm', [True])
            deadline = time.monotonic() + 3
            while not app.state.alarms.snapshot()['active_count'] and time.monotonic() < deadline:
                time.sleep(.02)
            snapshot = client.get('/api/alarms').json()
            self.assertEqual(snapshot['active_count'], 1)
            identifier = snapshot['outstanding'][0]['occurrence_id']
            self.assertEqual(client.post(f'/api/alarms/{identifier}/acknowledge', json={}).status_code, 200)
            self.assertTrue(app.state.driver.read('ProcessAlarm')[0])
            self.assertEqual(client.post('/api/alarms/999999/acknowledge', json={}).status_code, 404)
            self.assertEqual(client.post('/api/alarms/acknowledge-all').status_code, 422)

    def test_message_translations_are_snapshotted_and_trigger_edits_retire(self):
        store, values, monitor = self.setup_monitor()
        project = Project.model_validate(store.snapshot()['active'])
        from openhmi.projects import Language
        project.languages.append(Language(code='es', name='Español', flag='mx', translations={'alarm.process_alarm.message': 'Fallo'}))
        saved = store.save(SaveRequest(expected_revision=1, project=project))
        store.apply(RevisionRequest(expected_revision=saved['draft_revision']))
        values['ProcessAlarm'] = True
        monitor.sample()
        first = monitor.snapshot()['outstanding'][0]
        self.assertEqual(first['messages']['es'], 'Fallo')
        project.alarms[0].message = 'Changed source'
        project.languages[1].translations['alarm.process_alarm.message'] = 'Nuevo'
        saved = store.save(SaveRequest(expected_revision=saved['draft_revision'], project=project))
        store.apply(RevisionRequest(expected_revision=saved['draft_revision']))
        monitor.sample()
        self.assertEqual(len(monitor.snapshot()['occurrences']), 1)
        self.assertEqual(monitor.snapshot()['outstanding'][0]['messages']['es'], 'Fallo')
        project.alarms[0].trigger_value = 2
        saved = store.save(SaveRequest(expected_revision=saved['draft_revision'], project=project))
        store.apply(RevisionRequest(expected_revision=saved['draft_revision']))
        monitor.sample()
        retired = monitor.snapshot()['outstanding'][0]
        self.assertIsNotNone(retired['retired_at'])
        self.assertEqual(retired['quality'], 'retired')
        values['ProcessAlarm'] = 2
        monitor.sample()
        self.assertEqual(len(monitor.snapshot()['occurrences']), 2)
        self.assertEqual(monitor.snapshot()['outstanding'][0]['messages']['es'], 'Nuevo')


if __name__ == '__main__': unittest.main()
