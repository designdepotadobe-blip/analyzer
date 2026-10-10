import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'backend'))

from board import ET, compute_changes, last_session, radar_rows  # noqa: E402


def _h(action='wait_trigger', price=100.0, trigger=None, stop=None, alert=None, rating=7):
    return {'action': action, 'price': price, 'trigger': trigger, 'stop': stop, 'alert': alert,
            'rating': rating, 'sector': 'Technology', 'call_he': 'כניסה סביב 100'}


def test_last_session_waits_for_the_settled_close():
    assert last_session(datetime(2026, 10, 9, 15, 0, tzinfo=ET)) == '2026-10-08'   # Fri, in session
    assert last_session(datetime(2026, 10, 9, 16, 41, tzinfo=ET)) == '2026-10-09'  # Fri, after build time
    assert last_session(datetime(2026, 10, 11, 12, 0, tzinfo=ET)) == '2026-10-09'  # Sunday → Friday
    assert last_session(datetime(2026, 10, 12, 8, 0, tzinfo=ET)) == '2026-10-09'   # Monday pre-market


def test_changes_cover_the_four_events():
    prev = {
        'NEW': _h(),
        'BRK': _h(price=98.0, trigger=100.0),
        'NEAR': _h(),
        'END': _h(stop=95.0),
        'SAME': _h(action='enter'),
    }
    cur = {
        'NEW': _h(action='enter'),
        'BRK': _h(price=101.0),
        'NEAR': _h(alert={'tier': 'imminent', 'distance_atr': 0.3, 'price': 101.0}),
        'END': _h(price=94.0),
        'SAME': _h(action='enter'),
    }
    kinds = {c['ticker']: c['kind'] for c in compute_changes(cur, prev)}
    assert kinds == {'NEW': 'new_enter', 'BRK': 'broke_out', 'NEAR': 'near_trigger', 'END': 'setup_over'}


def test_radar_rows_keep_entries_alerts_and_presets_only():
    hits = {'A': {**_h(action='enter'), 'headline_action': 'ENTER'},
            'B': {**_h(alert={'tier': 'close'}), 'state': 'at_trigger'}, 'C': {**_h(), 'presets': ['reversal']},
            'D': {**_h(), 'presets': []}}
    rows = radar_rows(hits)
    assert sorted(k for k, h in hits.items() if any(r is h for r in rows)) == ['A', 'B', 'C']


def test_build_retries_names_the_provider_dropped(tmp_path, monkeypatch):
    import board
    monkeypatch.setattr(board, 'BOARD_DIR', str(tmp_path))
    monkeypatch.setattr(board, 'RETRY_PASSES', ((0, 2), (0, 1)))
    monkeypatch.setattr(board, 'PACE_S', 0)
    calls = {}

    def analyze(tk):
        calls[tk] = calls.get(tk, 0) + 1
        if tk == 'FLAKY' and calls[tk] == 1:
            raise RuntimeError('429')          # throttled on the first, parallel pass
        return None if tk == 'DEAD' else {'ok': True}

    b = board.Board(lambda: ['A', 'FLAKY', 'DEAD'], analyze,
                    lambda tk, r: {**_h(), 'ticker': tk, 'decided_on': '2026-10-09'}, lambda tk: None)
    out = b.build()
    assert sorted(out['hits']) == ['A', 'FLAKY']
    assert out['failed'] == 1 and calls['DEAD'] == 3   # retried twice, then counted
