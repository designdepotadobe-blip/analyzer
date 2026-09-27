"""
The by-the-book grade (backend/book.py) and the method rules it leans on.

Two layers: unit tests of the run-up / falling-150 rules against synthetic
inputs, and invariants over the frozen fixtures that must hold for ANY stock —
the letter's strictness rules are the owner's selection policy, so they are
asserted directly rather than trusted to a snapshot.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

import book as bk
from micha import MichaAnalyzer
from verdict import Judgement, Signals


# ── the run-up rule ──────────────────────────────────────────────────────────

def _ctx_from_closes(closes, atr_pct=2.0):
    closes = np.asarray(closes, float)
    return SimpleNamespace(closes=closes, price=float(closes[-1]), atr_pct=atr_pct,
                           sma20=None, sma150=float(closes[-1]), sma200=None, atr=1.0)


class TestRanHot:
    def test_four_up_days_is_hot(self):
        # four small up closes: "ארבעה ימים רצופים" on its own
        ext = MichaAnalyzer()._ext20(_ctx_from_closes([100, 99, 99.2, 99.4, 99.6, 99.8]))
        assert ext['run_days'] == 4 and ext['ran_hot']

    def test_three_quiet_up_days_is_not_hot(self):
        ext = MichaAnalyzer()._ext20(_ctx_from_closes([100, 99, 99.1, 99.2, 99.3]))
        assert ext['run_days'] == 3 and not ext['ran_hot']

    def test_three_big_up_days_is_hot(self):
        # +6% over three days on a 2%-ATR name is 3 ATR of ground
        ext = MichaAnalyzer()._ext20(_ctx_from_closes([100, 99, 101, 103, 105]))
        assert ext['run_days'] == 3 and ext['ran_hot']


# ── the falling 150 ──────────────────────────────────────────────────────────

class TestFalling150:
    def _ctx(self, ma_dir):
        return SimpleNamespace(price=100.0, atr=2.0, sma150=99.5, ma150_dir=ma_dir)

    def test_falling_150_alone_is_not_a_floor(self):
        s = Signals(nearest_sup=None, ma150_reclaim=None)
        assert Judgement._only_floor_is_falling_150(self._ctx('falling'), s)

    def test_rising_lows_line_underneath_is_a_floor(self):
        s = Signals(nearest_sup=None, ma150_reclaim=None, overlays={'trendlines': [
            {'kind': 'rising_lows', 'broke': False, 'p2': {'price': 99.2}}]})
        assert not Judgement._only_floor_is_falling_150(self._ctx('falling'), s)

    def test_rising_150_is_a_floor(self):
        s = Signals(nearest_sup=None, ma150_reclaim=None)
        assert not Judgement._only_floor_is_falling_150(self._ctx('rising'), s)

    def test_fresh_reclaim_is_exempt(self):
        s = Signals(nearest_sup=None, ma150_reclaim={'bars': 5, 'price': 99.5})
        assert not Judgement._only_floor_is_falling_150(self._ctx('falling'), s)

    def test_real_support_underneath_is_still_a_floor(self):
        s = Signals(nearest_sup={'price': 99.0}, ma150_reclaim=None)
        assert not Judgement._only_floor_is_falling_150(self._ctx('falling'), s)


# ── invariants over every frozen stock ───────────────────────────────────────

def _all(analyses):
    return [(tk, r['micha']) for tk, r in sorted(analyses.items())]


def test_grade_is_the_book(analyses):
    for tk, m in _all(analyses):
        b = m['book']
        assert m['grade'] == b['letter'], tk
        assert m['rating'] == b['rating'], tk
        assert m['grade_score'] == b['score'], tk


def test_points_add_up(analyses):
    for tk, m in _all(analyses):
        b = m['book']
        assert sum(i['max'] for i in b['items']) == 100, tk
        raw = sum(i['points'] for i in b['items']) + sum(x['points'] for x in b['minus'])
        assert b['raw'] == pytest.approx(raw, abs=0.01), tk
        assert b['score'] <= max(0.0, min(100.0, raw)) + 1e-6, tk


def test_a_only_for_an_entry(analyses):
    for tk, m in _all(analyses):
        if m['book']['letter'] == 'A':
            assert m['action'] == 'enter', tk


def test_nothing_under_the_150_reaches_b(analyses):
    for tk, m in _all(analyses):
        if m['d150_pct'] is not None and m['d150_pct'] < 0:
            assert m['book']['score'] < 65, tk


def test_every_bound_cap_is_respected(analyses):
    for tk, m in _all(analyses):
        for c in m['book']['caps']:
            assert m['book']['score'] <= c['ceiling'] + 1e-6, (tk, c['key'])


def test_book_target_is_never_a_fibonacci_when_a_real_price_exists():
    s = Signals(targets=[
        {'price': 110.0, 'source': 'resistance', 'label_he': 'התנגדות'},
        {'price': 160.0, 'source': 'fib_extension', 'label_he': 'פיבו'},
    ], overlays={})
    t = bk.book_target(SimpleNamespace(), s, 100.0)
    assert t['price'] == 110.0


# ── the 150-method entry: a pullback ONTO the floor, not a run into the ceiling ──

class TestCameDownToIt:
    def _ctx(self, highs, closes, atr=1.0, atr_pct=1.0):
        closes = np.asarray(closes, float)
        return SimpleNamespace(highs=np.asarray(highs, float), closes=closes,
                               price=float(closes[-1]), atr=atr, atr_pct=atr_pct,
                               M=len(closes))

    def test_pullback_from_the_recent_high(self):
        # 2 ATR under the 10-day high: "תיקנה ישירות לממוצע"
        c = [100] * 10 + [98.0]
        assert Judgement._came_down_to_it(self._ctx([101] * 11, c))

    def test_running_up_into_the_ceiling_is_not(self):
        # rising every day into the level: "תנועה לכיוון ההתנגדות"
        c = [95, 96, 97, 98, 99, 100, 100.5, 101, 101.5, 102, 102.3]
        h = [x + 0.2 for x in c]
        assert not Judgement._came_down_to_it(self._ctx(h, c))


def test_floor_includes_the_rising_lows_line_and_channel_bottom():
    ctx = SimpleNamespace(price=100.0, atr=2.0, sma150=80.0)
    s = Signals(nearest_sup=None, channel={'kind': 'rising', 'lower': 99.0},
                overlays={'trendlines': [{'kind': 'rising_lows', 'broke': False,
                                          'p2': {'price': 99.5}}]})
    assert Judgement._floor(ctx, s) == (99.5, 'rising_lows')


def test_run_phrase_matches_how_the_run_happened():
    # a streak is said as a streak; a fast week is said as a move, never "1 days in a row"
    assert bk.run_phrase({'run_days': 4, 'run_pct': 6})[1].startswith('רצה 4 ימים ברצף')
    assert 'בשבוע האחרון' in bk.run_phrase({'run_days': 1, 'run_pct': 17})[1]
