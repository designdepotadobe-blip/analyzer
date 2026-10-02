"""
The line layer — his bands, cups, channels and Fib targets (2026-09-27 rework).

Each test pins one rule measured against his charts; the numbers in the comments are
from tools/lines.py and the as-of reads of the named posts.
"""

from __future__ import annotations

import numpy as np

from geometry import Geometry
from levels import LevelEngine
from setups import SetupScanner


# ── fresh-break protection ───────────────────────────────────────────────────

def test_a_line_broken_upward_is_kept_as_the_breakout_line():
    # 30 closes under 100, then two above it: the level now sits under price and
    # "65% of recent closes are below it" — but it was JUST broken, so it stays
    recent = np.array([95.0] * 28 + [101.0, 102.0])
    assert LevelEngine._just_broken(recent, 100.0, 'support')


def test_a_support_that_failed_is_not_protected():
    recent = np.array([105.0] * 20 + [99.0] * 10)
    assert not LevelEngine._just_broken(recent, 100.0, 'support')


# ── pivots are touches, bars are tests; flipped means tested from both sides ─

def test_touches_are_pivots_and_flipped_needs_other_side_tests():
    lv = {'price': 100.0, 'top': 100.2, 'bottom': 99.8, 'spread': 0.4, 'touches': 2}
    n = 60
    closes = np.full(n, 95.0)
    highs, lows, opens = closes + 5.2, closes - 1.0, closes.copy()
    vols = np.ones(n)
    LevelEngine._recount_touches([lv], highs, lows, opens, closes, vols, 2.0, 'resistance')
    LevelEngine._recount_touches([lv], highs, lows, opens, closes, vols, 2.0, 'support')
    LevelEngine._assign_role([lv], 95.0)
    assert lv['touches'] == 2                 # the two pivots, not the bar count
    assert lv['tests'] > 2                    # bars that reached the level
    assert lv['flipped'] is False             # never tested from above


# ── cup: the rim is the band, the target comes off its top ───────────────────

def _cup_series():
    # left rim 100, a rounded 30-point cup, right-side highs back at 99.6 / 100.4
    down = np.linspace(100, 70, 40)
    base = np.full(30, 70.0)
    up = np.linspace(70, 100, 40)
    side = np.array([98, 99.6, 97, 96, 100.4, 97, 96, 95, 96, 97])
    rise = np.linspace(88, 99, 12)          # a swing high needs bars on its left
    closes = np.concatenate([rise, [100.0], down, base, up, side])
    return closes


def test_cup_rim_is_the_band_top_and_target_is_measured_from_it():
    closes = _cup_series()
    highs, lows = closes + 0.3, closes - 0.3
    M = len(closes)
    sh, sl = Geometry.swings(highs, lows, 1.0)
    cup = SetupScanner._detect_cup_handle(highs, lows, closes, float(closes[-1]), 1.0, M, sh, sl)
    assert cup is not None
    assert abs(cup['rim'] - 100.7) < 0.35          # the band top, not a single spike
    assert abs(cup['target_big'] - (cup['rim'] + (cup['rim'] - cup['trough']))) < 1e-6


# ── channel: anchored at the current leg ─────────────────────────────────────

def test_leg_channel_finds_a_rising_channel_with_both_rails_touched():
    # a zigzag with sharp turns, like real swing pivots: lows +0.3/bar, highs 6 above
    pts_x = [0, 12, 24, 36, 48, 60, 72, 84, 96, 108, 119]
    pts_y = [100, 106 + 3.6, 100 + 7.2, 106 + 10.8, 100 + 14.4, 106 + 18,
             100 + 21.6, 106 + 25.2, 100 + 28.8, 106 + 32.4, 100 + 35.7]
    x = np.arange(120)
    closes = np.interp(x, pts_x, pts_y)
    highs, lows = closes + 0.3, closes - 0.3
    sh, sl = Geometry.swings(highs, lows, 1.0)
    ch = Geometry.leg_channel(sh, sl, highs, lows, 1.0, len(x), float(np.mean(closes)),
                              40, 1.5, 10)
    assert ch is not None and ch['kind'] == 'rising'
    assert ch['upper_i'] > ch['lower_i']


# ── Fib: the bounce targets of a fresh decline (AEHR 147.40 → 74.23) ─────────

def test_fib_bounce_levels_are_the_retracements_of_the_drop():
    highs = np.concatenate([np.linspace(120, 147.4, 30), np.linspace(140, 76, 25), [80, 84, 86.3]])
    lows = highs - 2.0
    lows[54] = 74.23
    fb = SetupScanner._detect_fib_bounce(highs, lows, 86.26, 5.0, len(highs))
    assert fb is not None
    got = {lv['ratio']: lv['price'] for lv in fb['levels']}
    assert abs(got[0.5] - 110.815) < 0.01 and abs(got[0.618] - 119.449) < 0.01


# ── HIS line: the strongest nearby reversal, not the nearest bump ────────────

def _lvl(lo, hi, sig, dom, side='resistance'):
    return {'type': side, 'price': (lo + hi) / 2, 'top': hi, 'bottom': lo,
            'pivot_lo': lo, 'pivot_hi': hi, 'sig': sig, 'dom': dom}


def test_his_line_skips_a_minor_bump_under_a_major_high():
    # META 2026-09-20: price 665.75, ATR ~22. A 1.5-ATR bump at 672-683 sits under
    # the 7.1-ATR reversal at 686-692 — he named 692, the engine named 677.
    bump = _lvl(672.2, 683.3, 1.5, 40)
    major = _lvl(686.1, 691.7, 7.1, 150)
    got = LevelEngine.his_line([bump, major], 665.75, 22.0, 'resistance')
    assert got is major


def test_his_line_skips_the_band_price_is_inside():
    # KEEL / CLSK / UBER: price trades inside the nearest band — he names the next
    inside = _lvl(3.15, 3.28, 7.3, 200)
    nxt = _lvl(3.56, 3.60, 6.7, 200)
    assert LevelEngine.his_line([inside, nxt], 3.24, 0.22, 'resistance') is nxt


def test_his_line_prefers_the_nearer_of_two_equal_lines():
    a, b = _lvl(101, 101.5, 3.0, 100), _lvl(104, 104.5, 3.0, 100)
    assert LevelEngine.his_line([a, b], 100.0, 2.0, 'resistance') is a


def test_his_line_mirrors_for_support():
    near_minor = _lvl(98.8, 99.0, 0.8, 10, 'support')
    major = _lvl(96.5, 97.0, 6.0, 300, 'support')
    assert LevelEngine.his_line([near_minor, major], 100.0, 2.0, 'support') is major


def test_a_single_major_pivot_is_a_level_a_single_minor_one_is_not():
    # DLTR's 142.40 was one 11.6-ATR high and never became a level (needed 2 pivots)
    lv = LevelEngine._cluster([(142.4, 11.6, 400), (120.0, 0.7, 5)], 4.0)
    assert [round(l['price'], 1) for l in lv] == [142.4]
    assert lv[0]['touches'] == 1 and lv[0]['sig'] == 11.6


def test_pivot_strength_prominence_and_dominance():
    highs = np.array([10, 11, 12, 20, 12, 11, 10, 11, 15, 11, 10, 9], float)
    lows = highs - 1
    ph, _ = Geometry.pivot_strength(highs, lows, np.array([3, 8]), np.array([], int), 1.0, 252)
    assert ph[3][1] == 3 + 252               # the highest high: never exceeded
    assert ph[8][1] == 5                     # stood as the extreme back to bar 3
    assert ph[3][0] > ph[8][0]               # the bigger reversal


def test_support_his_line_counts_the_band_price_is_sitting_on():
    # LITE 2026-09-16: "נכנסים קונים על ממוצע 150" with price inside its just-broken
    # 897-937 band — the support he means is the one price is ON, not 1.5 ATR lower
    on = _lvl(897.0, 937.0, 2.6, 60, 'support')
    lower = _lvl(776.0, 817.0, 2.2, 300, 'support')
    assert LevelEngine.his_line([on, lower], 919.4, 68.6, 'support') is on
