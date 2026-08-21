"""
asof.py — run the PRODUCTION analysis pipeline as of a past date.

The whole point of this module is that it changes nothing about the analysis. It
rebuilds exactly what `StockAnalyzer.analyze` builds — same LevelEngine, same
SetupScanner, same MichaAnalyzer, same AnalysisContext — off a price frame that has
been truncated to the day in question. Anything else (a re-implementation, a
simplified level pass, a shortcut context) would measure a different engine than the
one that ships, which is the failure mode this harness exists to avoid.

Two things genuinely cannot be reconstructed historically and are passed as None
rather than faked:

  - `earnings_days`: we know when the NEXT report is, not when the next report was
    as of a Tuesday in 2025. Grading with today's countdown applied to a 2025 chart
    would let a cap fire on a date it could not have fired on.
  - `market_cap`: only today's is available. It gates the small-cap penalty only,
    and a name's cap rarely crosses $1B inside the sample window, so today's is
    passed through with that caveat noted here.

History is cached to disk once per ticker (`HistoryCache`), because the sample is
thousands of (ticker, date) pairs across a few hundred symbols and re-fetching per
call would make the harness slower than the thing it is testing.
"""

from __future__ import annotations

import os
import pickle
import sys
import threading
from typing import Optional

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(ROOT, 'backend'), ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from config import DISPLAY_BARS, HISTORY_PERIOD, MIN_BARS  # noqa: E402

# HISTORY_PERIOD expressed in trading days - production fetches '3y' of daily bars,
# which is what `ctx.full` (touch counting, all-time high) is built from.
HISTORY_BARS = int(float(HISTORY_PERIOD.rstrip('y')) * 252)
from context import AnalysisContext        # noqa: E402
from levels import LevelEngine             # noqa: E402
from market_data import MarketData         # noqa: E402
from micha import MichaAnalyzer            # noqa: E402
from setups import SetupScanner            # noqa: E402

CACHE_DIR = os.path.join(ROOT, '.harness')


class HistoryCache:
    """Long daily history per ticker, on disk, fetched once."""

    def __init__(self, period: str = '10y', path: str = None):
        self.period = period
        self.path = path or os.path.join(CACHE_DIR, 'hist_%s.pkl' % period)
        self._data: dict[str, Optional[pd.DataFrame]] = {}
        self._lock = threading.Lock()
        self._md = MarketData(history_period=period)
        if os.path.exists(self.path):
            try:
                with open(self.path, 'rb') as fh:
                    self._data = pickle.load(fh)
            except Exception:
                self._data = {}

    def __contains__(self, tk):
        return tk in self._data

    def get(self, ticker: str, fresh: bool = False) -> Optional[pd.DataFrame]:
        """
        Cached history. `fresh=True` re-fetches when the cache is missing recent
        bars.

        The default is deliberately "whatever is on disk": a 2024 as-of date does
        not care that the pickle stops last Tuesday, and re-fetching hundreds of
        symbols per run would make the harness unusable. But a run scored as of
        TODAY does care, and gets a different answer — NFLX read `avoid` off a cache
        one bar behind while production read `at_trigger`, purely because the
        missing bar was the buyers' candle. Anything scoring recent dates has to ask
        for `fresh`.
        """
        with self._lock:
            hit = self._data.get(ticker)
        if hit is not None and not (fresh and self._stale(hit)):
            if ticker in self._data:
                return hit
        df = self._md.fetch(ticker)
        with self._lock:
            if df is not None or ticker not in self._data:
                self._data[ticker] = df
            return self._data[ticker]

    @staticmethod
    def _stale(df, max_age_days: int = 0) -> bool:
        """
        Missing the newest bar?

        Zero tolerance by default, and that is not fussiness: the bar this misses is
        the CURRENT one, which is the bar every candle signal in the engine is read
        off. NFLX with yesterday's frame graded `avoid` 2/10 and with today's graded
        `at_trigger` 5/10 — one bar, five points and an opposite instruction, because
        the missing bar was the buyers' candle. `fresh` is only ever asked for by
        callers scoring recent dates, and `MarketData.fetch` has its own 300s TTL, so
        being strict here costs one request per symbol per run.
        """
        if df is None or df.empty:
            return True
        last = pd.Timestamp(df.index[-1]).normalize()
        return (pd.Timestamp.today().normalize() - last).days > max_age_days

    def warm(self, tickers, workers: int = 8, verbose: bool = True,
             fresh: bool = False) -> None:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        todo = [t for t in tickers
                if t not in self._data or (fresh and self._stale(self._data[t]))]
        if not todo:
            return
        done = 0
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(self.get, t, fresh) for t in todo]
            for _ in as_completed(futs):
                done += 1
                if verbose and done % 25 == 0:
                    print('    history %d/%d' % (done, len(todo)), flush=True)
        self.save()

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with self._lock:
            with open(self.path, 'wb') as fh:
                pickle.dump(self._data, fh)


class AsOfRunner:
    """The production pipeline, pointed at a truncated frame."""

    def __init__(self, cache: HistoryCache, window_bars: int = DISPLAY_BARS):
        self.cache = cache
        self.window_bars = window_bars
        self.levels = LevelEngine()
        self.setups = SetupScanner()
        self.micha = MichaAnalyzer()
        self._md = MarketData()
        self._caps: dict[str, Optional[float]] = {}

    def _cap(self, ticker: str) -> Optional[float]:
        if ticker not in self._caps:
            try:
                self._caps[ticker] = self._md.market_cap(ticker)
            except Exception:
                self._caps[ticker] = None
        return self._caps[ticker]

    def run(self, ticker: str, asof: str, with_cap: bool = True,
            fresh: bool = False) -> Optional[dict]:
        """
        The `micha` payload for `ticker` as it would have read on `asof`
        (YYYY-MM-DD), plus the overlays the grade is argued from. None when there
        is not enough history before that date to analyse.
        """
        raw = self.cache.get(ticker, fresh=fresh)
        if raw is None or raw.empty:
            return None
        cut = raw[raw.index <= pd.Timestamp(asof)]
        if len(cut) < MIN_BARS:
            return None
        # ── Same DEPTH of history production sees, not just the same end date ──
        # The cache holds 10 years so that a 2023 as-of date still has a warmed-up
        # SMA150 behind it, but `StockAnalyzer` fetches HISTORY_PERIOD ('3y') and
        # `ctx.full` is what the level engine counts touches in and what `ath` is
        # taken from. Handing it ten years makes this a different analyzer: a deeper
        # all-time high moves `off_high`, the target ladder and therefore the whole
        # REWARD axis. Caught by NFLX reading `avoid` here and `at_trigger` in
        # production on the same day. Trimmed to the production window so the only
        # thing this module changes is WHERE the frame ends.
        cut = cut.tail(HISTORY_BARS)

        full = self._md.add_indicators(cut).sort_index()
        w = full.tail(self.window_bars).copy()
        if len(w) < MIN_BARS:
            return None

        bench = None
        if ticker != 'SPY':
            b = self.cache.get('SPY')
            if b is not None and 'close' in b:
                bs = b['close']
                bench = bs[bs.index <= pd.Timestamp(asof)]

        ctx = AnalysisContext.build(
            ticker, full, w,
            market_cap=self._cap(ticker) if with_cap else None,
            # deliberately None - see the module docstring
            earnings_days=None,
            bench=bench, profile=None)

        overlays = {
            'levels': [], 'trendlines': [], 'channels': [], 'triangles': [],
            'fib': None, 'markers': [], 'gaps': [], 'flag_top': None,
            'flag_breaking': False, 'swings': [],
        }
        setups: list[dict] = []
        res_levels, sup_levels = self.levels.build(ctx)
        overlays['levels'] = self.levels.display_levels(ctx, res_levels, sup_levels)
        self.setups.scan(ctx, res_levels, sup_levels, overlays, setups)
        micha = self.micha.evaluate(ctx, res_levels, sup_levels, setups, overlays)
        return {'micha': micha, 'overlays': overlays, 'ctx': ctx,
                'price': float(ctx.price), 'atr': float(ctx.atr),
                'date': str(cut.index[-1].date())}


def forward(cache: HistoryCache, ticker: str, asof: str, bars: int) -> Optional[dict]:
    """
    What the stock actually did after `asof`, measured in ways that do NOT depend
    on the stop or target the engine chose.

    That independence is the whole design. [[micha-grade-outcome-test]] records a
    retune driven by a +2R win rate that turned out to be an artifact: at a fixed R
    multiple the target IS a function of the stop, so a tighter stop wins by
    construction, and the ordering fully reversed under a fixed target. Everything
    here is priced off the entry and the stock's own ATR instead, so no choice the
    grade makes can feed back into its own score.
    """
    raw = cache.get(ticker)
    if raw is None or raw.empty:
        return None
    past = raw[raw.index <= pd.Timestamp(asof)]
    fut = raw[raw.index > pd.Timestamp(asof)]
    if len(past) < 2 or len(fut) < 5:
        return None
    fut = fut.head(bars)
    entry = float(past['close'].iloc[-1])
    if entry <= 0:
        return None
    hi = float(fut['high'].max())
    lo = float(fut['low'].min())
    end = float(fut['close'].iloc[-1])
    out = {
        'bars': len(fut),
        'ret_pct': (end / entry - 1) * 100,     # plain forward return
        'mfe_pct': (hi / entry - 1) * 100,      # best it got
        'mae_pct': (lo / entry - 1) * 100,      # worst it got
        'exc_pct': None,
    }
    # ── Excess over the market, across the SAME calendar window ───────────────
    # The sample spans three years of a mostly-rising market, so the raw forward
    # return is dominated by beta: the baseline run came out at +4.86% for
    # EVERYTHING, which is a number about 2023-2026, not about the grade. Two names
    # posted a year apart cannot be compared on raw return at all. Subtracting SPY
    # over the identical bars is what makes "did picking this one help" answerable.
    if ticker != 'SPY':
        spy = cache.get('SPY')
        if spy is not None and not spy.empty:
            sp = spy[spy.index <= pd.Timestamp(asof)]
            sf = spy[spy.index > pd.Timestamp(asof)].head(len(fut))
            if len(sp) and len(sf):
                s0 = float(sp['close'].iloc[-1])
                s1 = float(sf['close'].iloc[-1])
                if s0 > 0:
                    out['exc_pct'] = out['ret_pct'] - (s1 / s0 - 1) * 100
    return out
