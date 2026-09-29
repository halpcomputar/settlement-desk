"""CI-only HTTP smoke test against a fresh sample-seeded Docker instance.

Usage: python tests/smoke_docker.py create|verify
Never calls Parse; use only with disposable test data.
"""
import json
import re
import sys
import urllib.request

BASE = 'http://127.0.0.1:8765'
NOTE = 'Docker CI persistence check (not a personal review)'


def request(path, data=None, headers=None):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(data).encode() if data is not None else None,
        headers=headers or {},
        method='PUT' if data is not None else 'GET',
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        return response.read().decode()


def main():
    mode = sys.argv[1]
    assert mode in ('create', 'verify')
    assert json.loads(request('/api/health'))['status'] == 'ok'
    snapshot = json.loads(request('/api/settlements'))
    assert len(snapshot['settlements']) == 3
    assert 'credits_remaining' not in snapshot['metadata']
    assert 'dashboard_credits_used' not in snapshot['metadata']
    assert not snapshot['api_configured']
    if mode == 'create':
        page = request('/')
        token = re.search(r'name="desk-token" content="([^"]+)"', page)[1]
        assert request('/static/app.js')
        result = json.loads(request('/api/reviews/114725000',
            {'status': 'maybe', 'notes': NOTE},
            {'Content-Type': 'application/json', 'X-Desk-Token': token, 'Origin': BASE}))
        assert result['saved']
    else:
        row = next(row for row in snapshot['settlements'] if row['object_id'] == '114725000')
        assert row['notes'] == NOTE and row['review_status'] == 'maybe'
        assert NOTE in request('/api/export')
    print(f'Docker smoke check ({mode}) passed; no Parse requests.')


if __name__ == '__main__':
    main()
