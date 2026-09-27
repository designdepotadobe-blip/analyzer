"""
The public-internet hardening (backend/security.py + api.py wiring).

The analyzer itself is stubbed out — these tests are about who may call what,
not about the analysis.
"""

from __future__ import annotations

import pytest

try:
    from fastapi.testclient import TestClient
except Exception:                 # starlette's client needs an extra package
    TestClient = None

import api

pytestmark = pytest.mark.skipif(TestClient is None, reason='starlette TestClient unavailable')


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(api, 'NOTES_PATH', str(tmp_path / 'notes.jsonl'))
    monkeypatch.setattr(api.analyzer, 'analyze', lambda tk: {'ticker': tk})
    api.sec.limiter._hits.clear()
    return TestClient(api.app)


def test_security_headers_on_every_response(client):
    r = client.get('/api/health')
    for h in ('x-content-type-options', 'x-frame-options', 'referrer-policy',
              'strict-transport-security', 'permissions-policy'):
        assert h in r.headers


def test_cors_refuses_an_unknown_site_and_allows_the_app(client):
    bad = client.get('/api/health', headers={'Origin': 'https://evil.example'})
    assert 'access-control-allow-origin' not in bad.headers
    ok = client.get('/api/health', headers={'Origin': 'https://analyzer-front.up.railway.app'})
    assert ok.headers.get('access-control-allow-origin') == 'https://analyzer-front.up.railway.app'


def test_docs_are_off_by_default(client):
    assert client.get('/docs').status_code == 404
    assert client.get('/openapi.json').status_code == 404


def test_invalid_ticker_is_refused(client):
    assert client.get('/api/analyze/..%2F..%2Fetc').status_code in (400, 404)
    assert client.get('/api/analyze/AAPL;DROP').status_code == 400
    assert client.get('/api/analyze/brk.b').status_code == 200


def test_errors_do_not_leak_internals(client, monkeypatch):
    def boom(tk):
        raise RuntimeError('secret path /home/app/db')
    monkeypatch.setattr(api.analyzer, 'analyze', boom)
    r = client.get('/api/analyze/AAPL')
    assert r.status_code == 502 and 'secret' not in r.text


def test_notes_are_not_publicly_readable(client, monkeypatch):
    client.post('/api/notes', json={'ticker': 'AAPL', 'note': 'x'})
    assert client.get('/api/notes').status_code == 403
    monkeypatch.setenv('NOTES_ADMIN_TOKEN', 's3cret')
    assert client.get('/api/notes', headers={'X-Admin-Token': 'wrong'}).status_code == 403
    r = client.get('/api/notes', headers={'X-Admin-Token': 's3cret'})
    assert r.status_code == 200 and r.json()['count'] == 1


def test_notes_are_size_and_rate_limited(client):
    assert client.post('/api/notes', json={'ticker': 'AAPL', 'note': 'x' * 5000}).status_code == 413
    codes = [client.post('/api/notes', json={'ticker': 'AAPL', 'note': 'n'}).status_code
             for _ in range(8)]
    assert 429 in codes


def test_rate_limit_on_analyze(client, monkeypatch):
    monkeypatch.setattr(api.sec.limiter, 'per_min', 3)
    codes = [client.get('/api/analyze/AAPL').status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200] and codes[-1] == 429
