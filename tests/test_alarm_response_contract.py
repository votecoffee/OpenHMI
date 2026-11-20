"""Actual alarm query responses accepted by the production browser validators."""
from copy import deepcopy
import unittest

from openhmi.alarms import utc_now
from tests.test_alarm_query_contract import alarm_query_fixture
from tests.test_frontend_contract import frontend


class AlarmResponseContractTests(unittest.TestCase):
    def validate(self, occurrences=(), events=(), notes=(), details=()):
        return frontend('alarm_responses', occurrences=list(occurrences), events=list(events),
                        notes=list(notes), details=list(details))

    def test_real_query_pages_detail_cache_and_legacy_null_attribution(self):
        client, queries, driver, source, first = alarm_query_fixture(self)
        monitor = queries.monitor
        source.side_effect = lambda: {'ProcessAlarm': False}
        monitor.sample()
        source.side_effect = lambda: {'ProcessAlarm': True}
        monitor.sample()
        second = monitor.snapshot()['outstanding'][0]['occurrence_id']
        monitor.acknowledge(first, identity=('Fixture Operator', 'local'))
        monitor.shelves.begin(second, 60, 'Offline investigation', ('Fixture Operator', 'local'), '3' * 32)
        monitor.note(first, 'Third note Δ', ('Fixture Operator', 'local'), '4' * 32)
        with queries.store.transaction() as db:
            # Model a legacy event whose retained occurrence/context no longer exists.
            db.execute('INSERT INTO alarm_event(occurrence_id,alarm_id,event,timestamp) VALUES(NULL,?,?,?)',
                       ('legacy_missing', 'quality_bad', utc_now()))
        calls = source.call_count
        def pages(path, **params):
            result, before = [], None
            while True:
                response = client.get(path, params={**params, **({'before_id': before} if before else {})})
                self.assertEqual(response.status_code, 200, response.text)
                page = response.json()
                result.append(page)
                if not page['has_more']: return result
                before = page['next_before_id']
        with client:
            occurrences = pages('/api/alarms/occurrences', state='all', limit=1)
            events = pages('/api/alarms/events', limit=2)
            notes = pages(f'/api/alarms/occurrences/{first}/notes', limit=1)
            occurrences.append(client.get('/api/alarms/occurrences?search=missing-record').json())
            events.append(client.get('/api/alarms/events?search=missing-record').json())
            details = []
            for identifier in (first, second):
                response = client.get(f'/api/alarms/occurrences/{identifier}')
                self.assertEqual(response.status_code, 200, response.text)
                details.append({'data': response.json(), 'identifier': identifier})
            self.assertIsNotNone(details[0]['data']['occurrence']['acknowledged_by'])
            self.assertIsNotNone(details[1]['data']['occurrence']['shelf'])
            self.assertEqual(details[0]['data']['related_screen']['id'], 'overview')
            driver.sample_snapshot.return_value = {}
            unavailable = client.get(f'/api/alarms/occurrences/{second}').json()
            self.assertEqual(unavailable['trigger']['quality'], 'unavailable')
            details.append({'data': unavailable, 'identifier': second})
        rows = [row for page in events for row in page['items']]
        legacy = next(row for row in rows if row['alarm_id'] == 'legacy_missing')
        self.assertIsNone(legacy['definition'])
        self.assertIsNone(legacy['actor'])
        self.assertIsNone(legacy['provider'])
        self.assertEqual(sum(len(page['items']) for page in notes), 3)
        outcome = self.validate(occurrences, events, notes, details)
        for key, values in (('occurrences', occurrences), ('events', events), ('notes', notes), ('details', details)):
            self.assertEqual(outcome[key], [True] * len(values))
        self.assertEqual(source.call_count, calls, 'Read contracts cannot sample alarm sources')

    def test_malformed_rows_paging_bounds_and_nullable_detail_metadata(self):
        client, _, _, _, identifier = alarm_query_fixture(self)
        with client:
            occurrence = client.get('/api/alarms/occurrences').json()['items'][0]
            event = client.get('/api/alarms/events').json()['items'][0]
            note = client.get(f'/api/alarms/occurrences/{identifier}/notes').json()['items'][0]
            detail = client.get(f'/api/alarms/occurrences/{identifier}').json()
        inputs, expected = {}, {}
        for family, row, key, maximum in (('occurrences', occurrence, 'occurrence_id', 200),
                                         ('events', event, 'id', 200), ('notes', note, 'id', 100)):
            low, high = {**deepcopy(row), key: 10}, {**deepcopy(row), key: 11}
            def page(items, more=False, cursor=None):
                return {'items': items, 'has_more': more, 'next_before_id': cursor}
            valid = [page([]), page([high, low]), page([high, low], True, 10),
                     page([{**deepcopy(row), key: 2**53 - 1}])]
            invalid = [None, {}, page([None]), page([], True, 1), page([high, low], True, 11),
                page([high, high]), page([low, high]), page([high], False, 11),
                page([{**deepcopy(row), key: 0}]), page([{**deepcopy(row), key: 2**53}]),
                page([{**deepcopy(row), key: value} for value in range(maximum + 1, 0, -1)])]
            bad_row = deepcopy(row)
            bad_row.update({'priority': 0} if family == 'occurrences' else
                           {'definition': {}} if family == 'events' else {'comment': None})
            invalid.append(page([bad_row]))
            inputs[family], expected[family] = valid + invalid, [True] * len(valid) + [False] * len(invalid)
        nullable = deepcopy(detail)
        nullable['occurrence'].update(causes=None, responses=None, messages=None, acknowledged_by=None)
        nullable['related_screen'] = None
        nullable['trigger'] = {'quality': 'unavailable', 'timestamp': None}
        details = [{'data': detail, 'identifier': identifier}, {'data': nullable, 'identifier': identifier}]
        invalid_details = [None, {}, {**deepcopy(detail), 'trigger': None},
                           {**deepcopy(detail), 'related_screen': {'id': 'overview', 'title': None}}]
        for key, value in (('cause', {}), ('response', []), ('causes', {'en': None}), ('messages', {'en': None})):
            item = deepcopy(detail)
            item['occurrence'][key] = value
            invalid_details.append(item)
        for key, value in (('quality', None), ('timestamp', {}), ('error', {})):
            item = deepcopy(detail)
            item['trigger'][key] = value
            invalid_details.append(item)
        details.extend({'data': item, 'identifier': identifier} for item in invalid_details)
        details.append({'data': detail, 'identifier': identifier + 1})
        details.append({'data': detail, 'identifier': str(identifier)})
        inputs['details'], expected['details'] = details, [True, True] + [False] * (len(details) - 2)
        self.assertEqual(self.validate(**inputs), expected)


if __name__ == '__main__':
    unittest.main()
