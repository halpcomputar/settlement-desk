import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]


class DashboardTests(unittest.TestCase):
    def setUp(self):
        base = ROOT / '.test-data'
        base.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.assertTrue(Path(self.temp.name).resolve().is_relative_to(base.resolve()))
        self.env = patch.dict(os.environ, {
            'SETTLEMENT_DB': str(Path(self.temp.name) / 'test.sqlite3'),
            'SETTLEMENT_LOAD_SAMPLE': 'true',
            'PARSE_API_KEY': 'test-only-not-a-real-key',
            'PARSE_SCRAPER_ID': '00000000-0000-0000-0000-000000000000',
        })
        self.env.start()
        spec = importlib.util.spec_from_file_location('test_desk_server', ROOT / 'server.py')
        self.server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.server)
        self.client = TestClient(self.server.app)
        self.headers = {'X-Desk-Token': self.server.TOKEN}

    def tearDown(self):
        self.client.close()
        self.env.stop()
        self.temp.cleanup()

    def snapshot(self):
        return self.client.get('/api/settlements').json()

    def test_initial_state_and_secret_isolation(self):
        data = self.snapshot()
        self.assertEqual(len(data['settlements']), 3)
        self.assertNotIn('credits_remaining', data['metadata'])
        self.assertNotIn('dashboard_credits_used', data['metadata'])
        self.assertNotIn(os.environ['PARSE_API_KEY'], self.client.get('/').text)
        self.assertNotIn(os.environ['PARSE_API_KEY'], json.dumps(data))

    def test_reviews_persist_and_csv_is_safe(self):
        response = self.client.put('/api/reviews/114725000', headers=self.headers,
                                   json={'status': 'maybe', 'notes': '=private note'})
        self.assertEqual(response.status_code, 200)
        self.server.initialize()
        row = next(r for r in self.snapshot()['settlements'] if r['object_id'] == '114725000')
        self.assertEqual(row['notes'], '=private note')
        self.assertEqual(row['review_status'], 'maybe')
        self.assertIn("'=private note", self.client.get('/api/export').text)

    def test_request_guards_and_input_validation(self):
        self.assertEqual(self.client.post('/api/refresh').status_code, 403)
        self.assertEqual(self.client.post('/api/refresh', headers={**self.headers, 'Origin': 'https://example.com'}).status_code, 403)
        self.assertEqual(self.client.get('/', headers={'host': 'example.com'}).status_code, 400)
        self.assertEqual(self.client.put('/api/reviews/114725000', headers=self.headers, json={'status': 'bad'}).status_code, 422)
        self.assertEqual(self.client.put('/api/reviews/missing', headers=self.headers, json={'status': 'maybe'}).status_code, 404)
        self.assertEqual(self.server.safe_url('javascript:alert(1)'), '')

    def test_one_refresh_preserves_reviews(self):
        self.client.put('/api/reviews/114725000', headers=self.headers, json={'status': 'maybe', 'notes': 'private note'})
        public = json.loads((ROOT / 'sample/settlements.json').read_text())['settlements'][1]
        public['payout_amount'] = 'Updated public terms'
        with patch.object(self.server.httpx, 'Client') as factory:
            remote = factory.return_value.__enter__.return_value
            response = remote.get.return_value
            response.status_code = 200
            response.headers = {'x-credits-charged': '1', 'x-credits-remaining': '297'}
            response.json.return_value = {'data': {'settlements': [public]}}
            result = self.client.post('/api/refresh', headers=self.headers)
            self.assertEqual(result.status_code, 200, result.text)
            remote.get.assert_called_once_with(self.server.API_URL, params={'page': 0, 'limit': 50}, headers={'X-API-Key': 'test-only-not-a-real-key'})
        data = self.snapshot()
        row = next(r for r in data['settlements'] if r['object_id'] == '114725000')
        self.assertEqual(row['notes'], 'private note')
        self.assertEqual(row['review_status'], 'maybe')
        self.assertEqual(row['payout_amount'], 'Updated public terms')
        self.assertEqual(len(data['settlements']), 3)
        self.assertEqual(result.json(), {'updated': 1})
        self.assertNotIn('credits_remaining', data['metadata'])
        self.assertNotIn('dashboard_credits_used', data['metadata'])

    def test_legacy_credit_metadata_is_not_exposed(self):
        with self.server.connect() as db:
            for key, value in {'credits_remaining': 199,
                               'credit_source': 'Last reported by Parse',
                               'dashboard_credits_used': 1}.items():
                self.server.meta_set(db, key, value)
        self.server.initialize()
        data = self.snapshot()
        self.assertEqual(len(data['settlements']), 3)
        self.assertEqual(set(data['metadata']), {'initialized', 'sample_only', 'last_refresh'})

    def test_failed_refresh_keeps_cache(self):
        original = self.snapshot()
        with patch.object(self.server.httpx, 'Client') as factory:
            response = factory.return_value.__enter__.return_value.get.return_value
            response.status_code = 200
            response.json.return_value = {'data': None}
            self.assertEqual(self.client.post('/api/refresh', headers=self.headers).status_code, 502)
        self.assertEqual(self.snapshot(), original)

    def fetch_fixture(self, rows, path='/api/find-more', status=200):
        with patch.object(self.server.httpx, 'Client') as factory:
            remote = factory.return_value.__enter__.return_value
            remote.get.return_value.status_code = status
            remote.get.return_value.json.return_value = {'data': {'settlements': rows}}
            result = self.client.post(path, headers=self.headers)
            params = remote.get.call_args.kwargs['params'] if remote.get.called else None
        return result, params

    def test_more_starts_at_zero_for_sample_and_preserves_reviews(self):
        public = json.loads((ROOT / 'sample/settlements.json').read_text())['settlements'][1]
        self.client.put('/api/reviews/114725000', headers=self.headers,
                        json={'status': 'maybe', 'notes': 'private note'})
        new = {**public, 'object_id': 'new-case', 'name': 'New case'}
        result, params = self.fetch_fixture([public, new, new])
        self.assertEqual(params, {'page': 0, 'limit': 50})
        self.assertEqual(result.json(), {'added': 1, 'existing': 1, 'checked': 2, 'page': 0, 'stop_reason': None})
        self.server.initialize()
        self.assertEqual(self.snapshot()['discovery']['next_page'], 1)
        saved = next(r for r in self.snapshot()['settlements'] if r['object_id'] == '114725000')
        self.assertEqual((saved['review_status'], saved['notes']), ('maybe', 'private note'))
        result, params = self.fetch_fixture([{**new, 'object_id': 'another-case'}])
        self.assertEqual(params['page'], 1)
        self.assertEqual(result.json()['added'], 1)
        self.assertEqual(self.snapshot()['discovery']['next_page'], 2)

    def test_existing_install_starts_after_first_page(self):
        with self.server.connect() as db:
            self.server.meta_set(db, 'sample_only', False)
        public = json.loads((ROOT / 'sample/settlements.json').read_text())['settlements']
        result, params = self.fetch_fixture(public)
        self.assertEqual(params['page'], 1)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['stop_reason'], 'repeated')

    def test_empty_page_stops_without_more_paid_requests_and_refresh_restarts(self):
        before = self.snapshot()['settlements']
        result, _ = self.fetch_fixture([])
        self.assertEqual(result.json()['stop_reason'], 'empty')
        self.assertEqual(result.json()['added'], 0)
        self.assertEqual(self.snapshot()['settlements'], before)
        result, params = self.fetch_fixture([])
        self.assertEqual(result.status_code, 409)
        self.assertIsNone(params)
        public = json.loads((ROOT / 'sample/settlements.json').read_text())['settlements']
        self.fetch_fixture(public, '/api/refresh')
        self.assertEqual(self.snapshot()['discovery'], {'next_page': 1, 'stop_reason': None})

    def test_repeated_page_stops_but_partial_overlap_can_continue(self):
        public = json.loads((ROOT / 'sample/settlements.json').read_text())['settlements']
        self.fetch_fixture(public, '/api/refresh')
        result, _ = self.fetch_fixture(public[:1])
        self.assertEqual(result.json()['added'], 0)
        self.assertIsNone(result.json()['stop_reason'])
        result, _ = self.fetch_fixture(list(reversed(public)))
        self.assertEqual(result.json()['stop_reason'], 'repeated')
        result, params = self.fetch_fixture(public)
        self.assertEqual(result.status_code, 409)
        self.assertIsNone(params)

    def test_more_failures_do_not_advance_or_change_saved_data(self):
        before = self.snapshot()
        for rows, status in [(None, 200), ([{'name': 'missing ID'}], 200), ([], 402), ([], 429)]:
            result, _ = self.fetch_fixture(rows, status=status)
            self.assertEqual(result.status_code, 502)
            self.assertEqual(self.snapshot(), before)
        with patch.object(self.server.httpx, 'Client') as factory:
            factory.return_value.__enter__.return_value.get.side_effect = self.server.httpx.TimeoutException('timeout')
            self.assertEqual(self.client.post('/api/find-more', headers=self.headers).status_code, 502)
        self.assertEqual(self.snapshot(), before)

    def test_more_request_guards_and_shared_lock(self):
        self.assertEqual(self.client.post('/api/find-more').status_code, 403)
        self.server.REFRESH_LOCK.acquire()
        try:
            with patch.object(self.server.httpx, 'Client') as factory:
                for path in ['/api/find-more', '/api/refresh']:
                    self.assertEqual(self.client.post(path, headers=self.headers).status_code, 409)
                factory.assert_not_called()
        finally:
            self.server.REFRESH_LOCK.release()

    def test_empty_database_and_missing_credentials(self):
        self.server.DB = Path(self.temp.name) / 'empty.sqlite3'
        self.server.LOAD_SAMPLE = False
        self.server.initialize()
        self.assertEqual(self.snapshot()['settlements'], [])
        with patch.dict(os.environ, {'PARSE_API_KEY': ''}):
            self.assertFalse(self.snapshot()['api_configured'])
            self.assertEqual(self.client.post('/api/refresh', headers=self.headers).status_code, 503)


if __name__ == '__main__':
    unittest.main()
