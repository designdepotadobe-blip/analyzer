"""
Shared fixtures. The whole point of this file is DETERMINISM.

`StockAnalyzer.analyze()` is ~100% network-bound and live prices move between
runs, so a test that calls it against Yahoo cannot assert anything stable — the
same ticker legitimately changes state and grade between two runs minutes apart.
SKILL.md states the fix outright: freeze the inputs, stub `StockAnalyzer.data`
with an object exposing the same surface, and run the real pipeline against a
pickled frame.

That is what `frozen_analyzer` does. Everything downstream of the fetch — the
real LevelEngine, the real SetupScanner, the real MichaAnalyzer, the real
Judgement — runs untouched, so these tests measure the engine that ships rather
than a reimplementation of it.

Fixtures are recorded once by `tests/record_fixtures.py` and committed, so the
suite runs offline and identically on any machine.
"""

from __future__ import annotations

import os
import pickle
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(ROOT, 'backend'), ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

FIXTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures')


class FrozenMarketData:
    """
    Stands in for `MarketData` with the same surface `StockAnalyzer` calls.

    Deliberately mirrors the real class's METHOD SET rather than subclassing it:
    subclassing would inherit the network paths and a missing override would
    silently reach Yahoo mid-test, which is exactly the non-determinism this
    exists to remove. A missing key raises instead of returning None, so a
    fixture gap fails loudly rather than quietly changing what is under test.
    """

    def __init__(self, payloads: dict):
        self._p = payloads

    def _get(self, ticker: str) -> dict:
        if ticker not in self._p:
            raise KeyError(
                f"no frozen fixture for {ticker!r} — record one with "
                f"tests/record_fixtures.py, do not let the test reach the network")
        return self._p[ticker]

    # ── the surface StockAnalyzer.analyze() actually uses ────────────────────
    def prime(self, ticker: str) -> None:
        return None

    def fetch(self, ticker: str):
        return self._get(ticker)['raw'].copy()

    def market_cap(self, ticker: str):
        return self._get(ticker)['market_cap']

    def earnings_days(self, ticker: str):
        return self._get(ticker)['earnings_days']

    def profile(self, ticker: str) -> dict:
        return dict(self._get(ticker)['profile'] or {})

    def benchmark(self, symbol: str = 'SPY'):
        b = self._p.get(symbol, {}).get('bench')
        return b.copy() if b is not None else None

    def add_indicators(self, df):
        # the real implementation — pure maths over the frame handed in, no I/O,
        # so freezing it would only risk drifting from what ships
        from market_data import MarketData
        return MarketData.add_indicators(self, df)

    @staticmethod
    def atr(df, period: int = 14):
        from market_data import MarketData
        return MarketData.atr(df, period)


def _load_payloads() -> dict:
    path = os.path.join(FIXTURE_DIR, 'frozen.pkl')
    if not os.path.exists(path):
        pytest.skip(
            'no recorded fixtures — run: '
            './venv/Scripts/python.exe tests/record_fixtures.py',
            allow_module_level=True)
    with open(path, 'rb') as fh:
        return pickle.load(fh)


@pytest.fixture(scope='session')
def payloads() -> dict:
    return _load_payloads()


@pytest.fixture(scope='session')
def frozen_analyzer(payloads):
    """The real pipeline, with only the fetch layer frozen."""
    from analyzer import StockAnalyzer
    an = StockAnalyzer()
    an.data = FrozenMarketData(payloads)
    return an


@pytest.fixture(scope='session')
def analyses(frozen_analyzer, payloads) -> dict:
    """
    {ticker: full analyze() payload}, computed once for the whole session.

    Session-scoped because the pipeline is ~40ms of real compute per ticker and
    every regression test reads the same result; per-test recomputation would
    make the suite slower for no added coverage.
    """
    out = {}
    for tk in sorted(payloads):
        if tk == 'SPY':
            continue
        r = frozen_analyzer.analyze(tk)
        if r is not None:
            out[tk] = r
    return out
