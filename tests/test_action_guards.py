"""
The entering-state guards, and the order they fire in.

These are unit tests against `Judgement._action` with synthetic inputs rather
than fixture-driven ones, for a specific reason: the recorded fixtures all carry
`earnings_days = None`, so the earnings guard is unreachable from them. A guard
that no test can reach is a guard that can regress silently, and the earnings
one is the highest-consequence of the three (it blocks an entry into a binary
event).

Guard order is itself under test. The spec's conceptual order is hard
invalidation → event blocker → risk/reward → chase/stretch → state → action, and
the order matters for the EXPLANATION even where two guards would produce the
same action: reporting "wait for the pullback" on a chart that is actually
deferred for earnings tells the reader to watch the wrong thing.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from config import CHASE_PAST_TRIGGER_ATR
from verdict import Judgement, Signals

ENTERING = ('breakout_now', 'buyers_at_level', 'value_pullback')


def ctx(price=100.0, atr=2.0):
    return SimpleNamespace(price=price, atr=atr)


def sig(**kw):
    """A Signals carrying only what `_action` reads, everything else default."""
    base = dict(ext={}, break_level=None)
    base.update(kw)
    return Signals(**base)


class TestEarningsGuard:
    @pytest.mark.parametrize('state', ENTERING)
    def test_earnings_tomorrow_defers(self, state):
        assert Judgement._action(ctx(), state, sig(), 1, []) == 'wait_event'

    @pytest.mark.parametrize('state', ENTERING)
    def test_earnings_today_defers(self, state):
        assert Judgement._action(ctx(), state, sig(), 0, []) == 'wait_event'

    def test_earnings_further_out_does_not_defer(self):
        # 2 days is outside the guard — it is a caveat the grade caps for,
        # not a reason to change the instruction
        assert Judgement._action(ctx(), 'breakout_now', sig(), 2, []) == 'enter'

    def test_unknown_earnings_does_not_block(self):
        # None means "we could not fetch it", which must never be treated as
        # "a report is imminent" — see the fixtures, where it is None for every
        # symbol. Failing closed here would silently mute every entry.
        assert Judgement._action(ctx(), 'breakout_now', sig(), None, []) == 'enter'

    def test_earnings_does_not_block_a_non_entering_state(self):
        # the guard blocks OPENING a position, not holding one
        assert Judgement._action(ctx(), 'holding', sig(), 1, []) == 'hold'


class TestStretchedGuard:
    def test_stretched_becomes_wait_pullback(self):
        s = sig(ext={'stretched': True})
        assert Judgement._action(ctx(), 'breakout_now', s, None, []) == 'wait_pullback'

    def test_stretched_never_blocks_holding(self):
        """'Stretched is a modifier, not a veto' — it blocks chasing, and a
        position already held is not a chase."""
        s = sig(ext={'stretched': True})
        assert Judgement._action(ctx(), 'holding', s, None, []) == 'hold'

    def test_earnings_outranks_stretched(self):
        # both would fire; the reader must be told the real reason
        s = sig(ext={'stretched': True})
        assert Judgement._action(ctx(), 'breakout_now', s, 1, []) == 'wait_event'


class TestChaseGuard:
    def test_price_far_past_break_level_defers(self):
        # 3 ATR past the level it broke — well beyond CHASE_PAST_TRIGGER_ATR
        s = sig(break_level=94.0)
        assert Judgement._action(ctx(price=100, atr=2), 'breakout_now', s,
                                 None, []) == 'wait_pullback'

    def test_price_at_the_break_level_still_enters(self):
        s = sig(break_level=99.5)
        assert Judgement._action(ctx(price=100, atr=2), 'breakout_now', s,
                                 None, []) == 'enter'

    def test_threshold_boundary_is_exclusive(self):
        """Exactly at the threshold is still an entry; the guard fires only
        BEYOND it. Pinned because an off-by-one here silently mutes a band of
        legitimate entries."""
        atr = 2.0
        price = 100.0
        at_threshold = price - CHASE_PAST_TRIGGER_ATR * atr
        s = sig(break_level=at_threshold)
        assert Judgement._action(ctx(price, atr), 'breakout_now', s, None, []) == 'enter'

    def test_no_break_level_means_no_chase_check(self):
        """A buyers-at-level or value-pullback entry is not chasing a break, so
        the guard must not fire on it — there is no break to be past."""
        s = sig(break_level=None)
        assert Judgement._action(ctx(), 'buyers_at_level', s, None, []) == 'enter'

    def test_zero_atr_does_not_crash(self):
        # a degenerate ATR must not raise ZeroDivisionError mid-verdict
        s = sig(break_level=90.0)
        assert Judgement._action(ctx(price=100, atr=0), 'breakout_now', s,
                                 None, []) == 'enter'


class TestNonEnteringStatesUnchanged:
    @pytest.mark.parametrize('state,expected', [
        ('turning', 'wait_trigger'),
        ('at_trigger', 'wait_trigger'),
        ('needs_buyers', 'wait_buyers'),
        ('holding', 'hold'),
        ('nothing_yet', 'watch'),
        ('broken', 'out'),
        ('avoid', 'avoid'),
    ])
    def test_state_maps_to_action(self, state, expected):
        """The state->action map is a published contract the UI and Radar both
        key off; pin it so a refactor cannot quietly re-point one."""
        assert Judgement._action(ctx(), state, sig(), None, []) == expected
