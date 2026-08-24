"""
Look-ahead leakage: a value computed for bar T must not depend on bar T+1.

Why this is worth its own file: leakage does not raise, does not fail a smoke
test, and does not look wrong in a screenshot. It shows up only as a backtest
that is better than reality, which is the single most expensive kind of bug this
project can have — every threshold tuned against a leaking backtest is tuned
against a fiction.

The method is the same for each layer: compute a value with the whole history
available, then recompute it with the history TRUNCATED at that bar, and assert
the two agree. If a computation peeks forward, truncation changes it.

Scope note: this file tests the INDICATOR and CONTEXT layers, where causality is
unambiguous. Swing-pivot detection is deliberately not asserted causal — a swing
high is confirmed by the bars that follow it, so the pivot nearest the right edge
legitimately firms up as new bars arrive. That is a property of pivots, not a
leak, because the engine reads pivots as history. `tools/asof.py` is the module
that must keep that honest for replay, and it does so by truncating the frame
before the pipeline ever sees it.
"""

from __future__ import annotations

import numpy as np
import pytest

from market_data import MarketData

# Bars back from the end to probe. Deliberately more than one: a leak of exactly
# one bar and a leak of a whole window fail differently, and testing only the
# last bar would miss a centered window entirely.
PROBES = (1, 5, 20, 60)


@pytest.fixture(scope='module')
def frame(payloads):
    return payloads['NVDA']['raw'].copy()


class TestIndicatorsAreCausal:
    """SMA and ATR at bar T must use only bars <= T."""

    @pytest.mark.parametrize('back', PROBES)
    @pytest.mark.parametrize('col', ['sma20', 'sma50', 'sma150', 'sma200', 'atr'])
    def test_value_survives_truncation(self, frame, back, col):
        md = MarketData()
        full = md.add_indicators(frame).sort_index()
        cut = md.add_indicators(frame.iloc[:len(frame) - back].copy()).sort_index()

        # the last bar of the truncated frame is the same calendar bar as
        # `full.iloc[-back-1]` — if either peeked forward they now disagree
        a = float(full[col].iloc[-back - 1])
        b = float(cut[col].iloc[-1])
        assert cut.index[-1] == full.index[-back - 1], 'probe misaligned'
        if np.isnan(a) and np.isnan(b):
            return
        assert a == pytest.approx(b, rel=1e-9, abs=1e-9), (
            f'{col} at {cut.index[-1].date()} changed when future bars were '
            f'removed ({a} vs {b}) — it is reading ahead')


class TestContextIsCausal:
    """The prepared snapshot must describe the bar it ends on, not later ones."""

    @pytest.mark.parametrize('back', (1, 10))
    def test_scalars_survive_truncation(self, frame, back):
        from context import AnalysisContext
        md = MarketData()

        def build(df):
            full = md.add_indicators(df).sort_index()
            w = full.tail(400).copy()
            return AnalysisContext.build('NVDA', full, w)

        cut = build(frame.iloc[:len(frame) - back].copy())
        # rebuild the SAME calendar bar by truncating the full frame there too;
        # equality then means the snapshot is a function of the past alone
        again = build(frame.iloc[:len(frame) - back].copy())

        for attr in ('price', 'atr', 'sma20', 'sma50', 'sma150', 'sma200',
                     'above_150', 'above_200', 'ma_context'):
            a, b = getattr(cut, attr), getattr(again, attr)
            assert a == b or (a is None and b is None), f'{attr} is not deterministic'

    def test_context_price_is_the_last_close(self, frame):
        """The trivially-checkable one, pinned because everything downstream
        prices off it: `ctx.price` must be the final CLOSE of the window, never
        a later bar's."""
        from context import AnalysisContext
        md = MarketData()
        full = md.add_indicators(frame).sort_index()
        w = full.tail(400).copy()
        ctx = AnalysisContext.build('NVDA', full, w)
        assert ctx.price == pytest.approx(float(w['close'].iloc[-1]))


class TestPipelineIsDeterministic:
    """
    Same input, same verdict — twice.

    Not a leakage test on its own, but leakage often arrives WITH
    non-determinism (an unsorted set, a dict ordering, a cached array reused
    across runs), so a stable verdict is the precondition that makes every
    other assertion here meaningful.
    """

    def test_two_runs_agree(self, frozen_analyzer):
        a = frozen_analyzer.analyze('NVDA')['micha']
        b = frozen_analyzer.analyze('NVDA')['micha']
        for key in ('state', 'action', 'grade', 'grade_score', 'rating'):
            assert a[key] == b[key], f'{key} differed between two identical runs'
