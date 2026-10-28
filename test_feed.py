import importlib, os
from datetime import datetime, timedelta
import pytest, requests

def iso(d): return d.strftime('%Y-%m-%dT%H:%M:%S')
NOW = datetime.now()

def ev(i, start, **kw):
    d = {'event_id': f'e{i}', 'name': f'Game {i}', 'start_at': iso(start), 'end_at': iso(start + timedelta(hours=1))}
    d.update(kw); return d

class R:
    def __init__(self, code, js): self.status_code, self._js, self.text = code, js, str(js)
    def json(self): return self._js

@pytest.fixture
def mod(monkeypatch):
    monkeypatch.setenv('GROUPME_API_KEY', 'tok'); monkeypatch.setenv('GROUPME_GROUP_ID', 'A,B')
    import utils, groupme_cal
    importlib.reload(utils); importlib.reload(groupme_cal)
    return groupme_cal

def fake(events, fail=(), token_ok=True):
    def get(url, headers=None, timeout=None):
        gid = url.rstrip('/').split('/')[-3 if url.endswith('/list') else -1]
        if not token_ok or gid in fail: return R(401, {'meta': {'code': 401}})
        if url.endswith('/list'): return R(200, {'response': {'events': events[gid]}})
        return R(200, {'response': {'name': f'Team {gid}'}})
    return get

def ics(c): return c.get('/calendar.ics')

def test_success_window_deleted_alarm(mod, monkeypatch):
    events = {'A': [ev(1, NOW + timedelta(days=2)), ev(2, NOW - timedelta(days=60)),
                    ev(3, NOW + timedelta(days=3), deleted_at='2026-01-01'), ev(4, NOW + timedelta(days=4), updated_at='2026-10-01T12:00:00Z')],
              'B': []}
    monkeypatch.setattr('utils.requests.get', fake(events))
    r = ics(mod.app.test_client()); body = r.get_data(as_text=True)
    assert r.status_code == 200
    assert body.count('BEGIN:VEVENT') == 2          # old + deleted dropped
    assert body.count('BEGIN:VALARM') == 2          # one alarm per event, none stray
    assert 'UID:e1' in body and 'UID:e2' not in body and 'UID:e3' not in body
    assert 'LAST-MODIFIED;VALUE=DATE-TIME:20261001T120000Z' in body  # proper iCal format
    assert body.count('DTSTAMP') == 2
    assert 'SUMMARY:[Team A] Game 1' in body
    print(body[:400])

def test_bad_token_no_cache_is_503_not_empty(mod, monkeypatch):
    monkeypatch.setattr('utils.requests.get', fake({}, token_ok=False))
    r = ics(mod.app.test_client())
    assert r.status_code == 503 and 'BEGIN:VCALENDAR' not in r.get_data(as_text=True)

def test_failure_after_success_serves_last_good(mod, monkeypatch):
    monkeypatch.setenv('CACHE_DURATION', '0')
    events = {'A': [ev(1, NOW + timedelta(days=2))], 'B': [ev(2, NOW + timedelta(days=2))]}
    c = mod.app.test_client()
    monkeypatch.setattr('utils.requests.get', fake(events)); assert ics(c).get_data(as_text=True).count('BEGIN:VEVENT') == 2
    # token dies
    monkeypatch.setattr('utils.requests.get', fake(events, token_ok=False)); mod.app.retry_at = None
    r = ics(c); assert r.status_code == 200 and r.get_data(as_text=True).count('BEGIN:VEVENT') == 2

def test_one_group_fails_keeps_its_old_events(mod, monkeypatch):
    monkeypatch.setenv('CACHE_DURATION', '0')
    events = {'A': [ev(1, NOW + timedelta(days=2))], 'B': [ev(2, NOW + timedelta(days=2))]}
    c = mod.app.test_client()
    monkeypatch.setattr('utils.requests.get', fake(events)); ics(c)
    monkeypatch.setattr('utils.requests.get', fake(events, fail=('B',))); mod.app.retry_at = None
    body = ics(c).get_data(as_text=True)
    assert 'UID:e1' in body and 'UID:e2' in body
    assert mod.app.group_status == {'A': 'ok', 'B': 'stale'}
    h = c.get('/healthz').get_json(); assert h['groups_stale'] == 1

def test_all_seasons_over_is_valid_empty_calendar(mod, monkeypatch):
    events = {'A': [ev(1, NOW - timedelta(days=90))], 'B': []}
    monkeypatch.setattr('utils.requests.get', fake(events))
    r = ics(mod.app.test_client())
    assert r.status_code == 200 and 'BEGIN:VCALENDAR' in r.get_data(as_text=True) and 'BEGIN:VEVENT' not in r.get_data(as_text=True)

def test_removed_group_drops_events(mod, monkeypatch):
    monkeypatch.setenv('CACHE_DURATION', '0')
    events = {'A': [ev(1, NOW + timedelta(days=2))], 'B': [ev(2, NOW + timedelta(days=2))]}
    monkeypatch.setattr('utils.requests.get', fake(events)); c = mod.app.test_client(); ics(c)
    monkeypatch.setenv('GROUPME_GROUP_ID', 'A')
    body = ics(c).get_data(as_text=True); assert 'UID:e1' in body and 'UID:e2' not in body

def test_secret_key(mod, monkeypatch):
    monkeypatch.setenv('CALENDAR_SECRET', 's3'); monkeypatch.setattr('utils.requests.get', fake({'A': [], 'B': []}))
    c = mod.app.test_client()
    assert c.get('/calendar.ics').status_code == 404 and c.get('/calendar.ics?key=s3').status_code == 200
    assert c.get('/healthz').status_code == 200

def test_network_error_handled(mod, monkeypatch):
    def boom(*a, **k): raise requests.ConnectionError('down')
    monkeypatch.setattr('utils.requests.get', boom)
    assert ics(mod.app.test_client()).status_code == 503

def test_index_renders(mod, monkeypatch):
    monkeypatch.setattr('utils.requests.get', fake({'A': [ev(1, NOW + timedelta(days=1))], 'B': []}))
    r = mod.app.test_client().get('/', headers={'X-Forwarded-Proto': 'https', 'X-Forwarded-Host': 'x.onrender.com'})
    assert r.status_code == 200 and 'webcal://x.onrender.com/calendar.ics' in r.get_data(as_text=True)
