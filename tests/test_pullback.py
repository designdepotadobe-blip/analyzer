"""
His pullback entry read as a pattern (micha._pullback_entry, 2026-10-02).

"תיקנה משמעותית ישירות לממוצע 150 + קו תמיכה + לשפלים עולים. כניסת קונים" (ABNB):
a real dip, that TOUCHED one or more of his floors and is still sitting on them. The
measurements behind each threshold are in config (PULLBACK_*).
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from micha import MichaAnalyzer
from verdict import Judgement, Signals


def _ctx(closes, lows=None, highs=None, sma150=None, atr=2.0):
    closes = np.asarray(closes, float)
    lows = closes - 1.0 if lows is None else np.asarray(lows, float)
    highs = closes + 1.0 if highs is None else np.asarray(highs, float)
    price = float(closes[-1])
    return SimpleNamespace(atr=atr, price=price, M=len(closes), closes=closes,
                           lows=lows, highs=highs, sma150=sma150,
                           atr_pct=atr / price * 100)


def _dip(last=(108, 106, 104, 102, 100.5)):
    # a rally to 112, then five lower closes into ~100
    return [90 + i * 0.8 for i in range(25)] + [110, 112] + list(last)


def _read(ctx, **kw):
    args = dict(nearest_sup=None, fib=None, overlays={}, break_level=None, channel=None)
    args.update(kw)
    return MichaAnalyzer()._pullback_entry(ctx, **args)


def test_a_deep_dip_onto_the_150_is_the_pattern():
    ctx = _ctx(_dip(), sma150=100.0)
    pb = _read(ctx)
    assert [f['kind'] for f in pb['floors']] == ['ma150']
    assert pb['deep'] and pb['ok']
    assert 'ממוצע 150' in pb['he']


def test_floors_stack_into_a_confluence():
    ctx = _ctx(_dip(), sma150=100.0)
    sup = {'price': 100.2, 'zone_top': 100.6, 'zone_bottom': 99.8}
    fib = {'peak': 113.0, 'base': 87.0}               # 50% = 100.0
    pb = _read(ctx, nearest_sup=sup, fib=fib)
    assert {f['kind'] for f in pb['floors']} == {'ma150', 'support', 'fib'}
    assert pb['confluence'] == 3 and pb['ok']


def test_a_floor_within_reach_but_not_touched_is_not_a_floor():
    # the 150 sits 1.2 ATR under the dip's low: "near a support" is true on most
    # random days, "stopped ON it" is the pattern
    ctx = _ctx(_dip(), sma150=97.0)
    pb = _read(ctx)
    assert pb['floors'] == [] and not pb['ok']


def test_the_line_it_just_broke_is_not_a_floor_on_its_own():
    ctx = _ctx(_dip(), sma150=80.0)
    pb = _read(ctx, break_level=100.0)
    assert [f['kind'] for f in pb['floors']] == ['broken_line']
    assert not pb['ok']


def test_a_shallow_dip_is_not_the_pattern():
    # one soft day off the high onto the 150: not ≥1.5 ATR, not 8%, not 5 red closes
    closes = [90 + i * 0.4 for i in range(30)] + [102.0, 101.4]
    ctx = _ctx(closes, sma150=100.8)
    pb = _read(ctx)
    assert pb['floors'] and not pb['deep'] and not pb['ok']


def test_a_dip_that_already_bounced_is_climbing_to_the_ceiling():
    # touched the 150 two bars ago and is already 0.9 ATR up on the week
    closes = [90 + i * 0.8 for i in range(25)] + [112, 108, 104, 100, 99.6, 99.4,
                                                  99.8, 102.5, 104.5]
    ctx = _ctx(closes, sma150=99.5, atr=4.0)
    pb = _read(ctx)
    assert pb['floors'] and pb['deep']
    assert pb['ret5_atr'] > 0.5 and not pb['ok']


def test_the_state_machine_reads_the_pattern_flag():
    assert Judgement._pullback_pattern(Signals(pullback={'ok': True}))
    assert not Judgement._pullback_pattern(Signals(pullback={'ok': False, 'floors': [1]}))
    assert not Judgement._pullback_pattern(Signals())
