"""Production alarm read URLs bound through the real SQL-backed registrar."""
import csv
from io import StringIO
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

from fastapi import FastAPI
from fastapi.testclient import TestClient
from openhmi.alarm_queries import STATES, EVENTS
from openhmi.alarm_routes import add_alarm_routes
from openhmi.alarms import AlarmMonitor
from openhmi.project_models import Project, SaveRequest, RevisionRequest
from openhmi.projects import ProjectStore
from tests.test_frontend_contract import frontend


FILTERS = dict(priority='0', search='', state='outstanding', shelving='unshelved', start='', end='')


def alarm_query_fixture(test_case):
    store = ProjectStore()
    test_case.addCleanup(store.close)
    project = Project.model_validate(store.snapshot()['active'])
    project.alarms[0].message = '=设备 A,+%_ =x'
    project.alarms[0].related_screen = 'overview'
    saved = store.save(SaveRequest(expected_revision=1, project=project))
    store.apply(RevisionRequest(expected_revision=saved['draft_revision']))
    values = {'ProcessAlarm': False}
    source = Mock(side_effect=lambda: values.copy())
    monitor = AlarmMonitor(store, source)
    monitor.sample()
    values['ProcessAlarm'] = True
    monitor.sample()
    identifier = monitor.snapshot()['outstanding'][0]['occurrence_id']
    monitor.note(identifier, '@Review,设备\nStep 2', ('Fixture Operator', 'local'), '1' * 32)
    monitor.note(identifier, 'Second note', ('Fixture Operator', 'local'), '2' * 32)
    driver = Mock(spec=['sample_snapshot'])
    driver.sample_snapshot.return_value = {'ProcessAlarm': {'quality': 'good', 'timestamp': None,
                                                            'value': 'must not be exposed'}}
    app = FastAPI()
    add_alarm_routes(app, monitor, Mock(), Mock(), driver, store)
    queries = app.state.alarm_queries
    for name in ('occurrences', 'history', 'detail', 'notes'):
        setattr(queries, name, Mock(wraps=getattr(queries, name)))
    return TestClient(app), queries, driver, source, identifier


class AlarmQueryContractTests(unittest.TestCase):
    def browser(self, occurrences=(), history=(), details=(), notes=()):
        def complete(items):
            return [{**item, 'filters': {**FILTERS, **item.get('filters', {})}} for item in items]
        return frontend('alarm_queries', occurrences=complete(occurrences), history=complete(history),
                        details=list(details), notes=list(notes))

    def fixture(self):
        return alarm_query_fixture(self)

    def test_actual_browser_filters_cursors_detail_notes_and_csv_bind_to_routes(self):
        special = dict(priority='2', search='设备 A,+%_', start='2026-01-01T05:30:00+05:30', end='2026-12-31T23:59:59Z')
        payload = self.browser(
            occurrences=[{}, {'filters': special, 'before': '9223372036854775807', 'options': {'limit': 1}},
                {'options': {'limit': 200}}, *[{'filters': {'state': state}} for state in sorted(STATES)],
                *[{'filters': {'shelving': value}} for value in ('all', 'shelved', 'unshelved')]],
            history=[{}, {'filters': special, 'before': '9223372036854775807', 'event': 'operator_note', 'options': {'limit': 1}},
                {'options': {'limit': 200}}, *[{'event': value} for value in sorted(EVENTS)]],
            details=['1'], notes=[{'identifier': '1'}, {'identifier': '1', 'before': '9223372036854775807', 'options': {'limit': 100}},
                                 {'identifier': '1', 'options': {'limit': 1}}])
        self.assertEqual(set(payload['states']), STATES)
        self.assertEqual(set(payload['events']), EVENTS)
        self.assertEqual(set(payload['shelving']), {'all', 'shelved', 'unshelved'})
        self.assertEqual(payload['occurrences'][0], '/api/alarms/occurrences?priority=0&search=&state=outstanding&shelving=unshelved')
        self.assertEqual(payload['notes'][0], '/api/alarms/occurrences/1/notes')
        self.assertIn('start=2026-01-01T00%3A00%3A00.000Z', payload['occurrences'][1])
        client, queries, driver, source, identifier = self.fixture()
        self.assertEqual(identifier, 1)
        calls = source.call_count
        with client:
            for key, method, default_limit in (('occurrences', 'occurrences', 50), ('history', 'history', 50)):
                for path in payload[key]:
                    response = client.get(path)
                    self.assertEqual(response.status_code, 200, response.text)
                    params = parse_qs(urlsplit(path).query, keep_blank_values=True)
                    expected = (int(params.get('limit', [default_limit])[0]),
                        int(params['before_id'][0]) if 'before_id' in params else None,
                        int(params['priority'][0]), params['search'][0], params['state'][0],
                        params.get('start', [None])[0], params.get('end', [None])[0],
                        params.get('shelving', ['all'])[0] if key == 'occurrences' else params.get('event', [''])[0])
                    actual = getattr(queries, method).call_args.args
                    self.assertEqual(actual, expected if key == 'occurrences' else (*expected, None))
            detail = client.get(payload['details'][0])
            self.assertEqual(detail.status_code, 200, detail.text)
            self.assertEqual(detail.json()['related_screen']['id'], 'overview')
            self.assertEqual(detail.json()['trigger']['quality'], 'good')
            self.assertNotIn('value', detail.json()['trigger'])
            for path in payload['notes']:
                reply = client.get(path)
                self.assertEqual(reply.status_code, 200, reply.text)
                params = parse_qs(urlsplit(path).query)
                queries.notes.assert_called_with(1, int(params.get('limit', ['50'])[0]),
                    int(params['before_id'][0]) if 'before_id' in params else None)
            for path in payload['csv']:
                params = parse_qs(urlsplit(path).query, keep_blank_values=True)
                self.assertEqual(params['state'], ['all'])
                self.assertFalse({'limit', 'before_id', 'shelving'} & params.keys())
                reply = client.get(path)
                self.assertEqual(reply.status_code, 200, reply.text)
                self.assertEqual(queries.history.call_args.args[:2], (20000, None))
                self.assertIn('alarm-events.csv', reply.headers['content-disposition'])
                self.assertEqual(reply.headers['x-openhmi-truncated'], 'false')
            rows = list(csv.DictReader(StringIO(client.get(payload['csv'][0]).text)))
            self.assertIn("'@Review,设备\nStep 2", {row['comment'] for row in rows})
            self.assertTrue(all(row['message'].startswith("'=设备") for row in rows))
        self.assertEqual(source.call_count, calls)
        driver.sample_snapshot.assert_called_once_with()

    def test_invalid_generated_bounds_fail_before_queries_or_cached_detail_reads(self):
        payload = self.browser(
            occurrences=[{'options': {'limit': value}} for value in (0, 201)] +
                [{'before': value} for value in ('0', '-1', '9223372036854775808')] +
                [{'filters': {key: value}} for key, value in (('priority', 5), ('search', 'x' * 201))],
            history=[{'options': {'limit': value}} for value in (0, 201)] + [{'before': '9223372036854775808'}],
            details=['0', '-1', '1.5', '9223372036854775808'],
            notes=[{'identifier': '0'}, {'identifier': '9223372036854775808'},
                {'identifier': '1', 'options': {'limit': 0}}, {'identifier': '1', 'options': {'limit': 101}},
                {'identifier': '1', 'before': '0'}])
        client, queries, driver, source, _ = self.fixture()
        calls = source.call_count
        with client:
            for key in ('occurrences', 'history', 'details', 'notes'):
                for path in payload[key]:
                    with self.subTest(path=path): self.assertEqual(client.get(path).status_code, 422)
        for name in ('occurrences', 'history', 'detail', 'notes'): getattr(queries, name).assert_not_called()
        driver.sample_snapshot.assert_not_called()
        self.assertEqual(source.call_count, calls)

    def test_domain_filters_and_missing_ids_return_errors_without_source_sampling(self):
        payload = self.browser(occurrences=[{'filters': {'state': 'unknown'}}, {'filters': {'shelving': 'unknown'}}],
                               history=[{'event': 'unknown'}], details=['9223372036854775807'],
                               notes=[{'identifier': '9223372036854775807'}])
        client, _, driver, source, _ = self.fixture()
        calls = source.call_count
        with client:
            for path in [*payload['occurrences'], *payload['history'], *payload['csv']]:
                self.assertEqual(client.get(path).status_code, 422)
            for path in [*payload['details'], *payload['notes']]: self.assertEqual(client.get(path).status_code, 404)
            for path in ('/api/alarms/occurrences?start=not-a-date', '/api/alarms/events?start=2026-01-01T00:00:00',
                         '/api/alarms/events.csv?start=2026-02-01T00:00:00Z&end=2026-01-01T00:00:00Z'):
                self.assertEqual(client.get(path).status_code, 422)
        driver.sample_snapshot.assert_not_called()
        self.assertEqual(source.call_count, calls)


if __name__ == '__main__':
    unittest.main()
