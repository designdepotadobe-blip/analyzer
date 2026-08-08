"""
StockAnalyzer — orchestrates the analysis pipeline and emits plain JSON geometry
primitives (timestamped points / price levels / markers) that the Angular +
lightweight-charts frontend renders TradingView-style.

The heavy lifting lives in focused collaborators:
  • MarketData    — fetch OHLCV + attach SMAs / Wilder's ATR   (market_data.py)
  • AnalysisContext — prepared arrays + MA context + swings     (context.py)
  • LevelEngine   — horizontal support / resistance             (levels.py)
  • SetupScanner  — chart-pattern setups                        (setups.py)
  • Geometry      — swings / regression / sloped lines          (geometry.py)

Setups detected (0, 1 or many may apply to a given stock):
  1. above150_breakout  2. bearish_to_bullish  3. below150_floor  4. triangle
  5. fibonacci  6. ma_bounce  7. rising_channel  8. bull_flag  9. support_test

All distance thresholds scale with ATR so calm and volatile stocks are judged fairly.
"""

from __future__ import annotations

import math
from typing import Optional

from config import DISPLAY_BARS, HISTORY_PERIOD, MIN_BARS, SMA_PERIODS, jnum
from context import AnalysisContext
from levels import LevelEngine
from market_data import MarketData
from micha import MichaAnalyzer
from setups import SetupScanner


class StockAnalyzer:
    def __init__(self, history_period: str = HISTORY_PERIOD, window_bars: int = DISPLAY_BARS):
        self.window_bars = window_bars
        self.data = MarketData(history_period=history_period)
        self.levels = LevelEngine()
        self.setups = SetupScanner()
        self.micha = MichaAnalyzer()

    def analyze(self, ticker: str) -> Optional[dict]:
        # Warm history + market cap + earnings + profile together. They are four
        # independent GETs that used to run one after another, each building its own
        # `Ticker` (~3 s of cookie/crumb setup apiece); priming pays that once and
        # overlaps the rest. Every getter below is still individually cached, so this
        # is an optimisation only — remove it and the results are unchanged.
        self.data.prime(ticker)

        raw = self.data.fetch(ticker)
        if raw is None or len(raw) < MIN_BARS:
            return None

        # Indicators are computed on the full 3-year fetch, so SMA150 is already
        # warmed up by the time the display window begins — no NaN gap.
        full = self.data.add_indicators(raw).sort_index()
        w = full.tail(self.window_bars).copy()
        if len(w) < MIN_BARS:
            return None

        market_cap = self.data.market_cap(ticker)
        earnings_days = self.data.earnings_days(ticker)
        profile = self.data.profile(ticker)
        # the benchmark is TTL-cached, so a whole scan fetches it once
        bench = self.data.benchmark() if ticker != 'SPY' else None
        ctx = AnalysisContext.build(ticker, full, w, market_cap=market_cap,
                                    earnings_days=earnings_days, bench=bench,
                                    profile=profile)

        overlays = {
            'levels': [], 'trendlines': [], 'channels': [],
            'triangles': [], 'fib': None, 'markers': [], 'gaps': [],
            'flag_top': None, 'flag_breaking': False,
        }
        setups: list[dict] = []

        # ── Support / resistance ───────────────────────────────────────────────
        res_levels, sup_levels = self.levels.build(ctx)
        overlays['levels'] = self.levels.display_levels(ctx, res_levels, sup_levels)
        overlays['markers'].extend(
            self.levels.breakout_markers(ctx, res_levels + sup_levels))

        # ── Chart-pattern setups (mutate overlays + setups in place) ───────────
        self.setups.scan(ctx, res_levels, sup_levels, overlays, setups)

        # ── Micha-style verdict (read-only side service) ───────────────────────
        micha = self.micha.evaluate(ctx, res_levels, sup_levels, setups, overlays)

        return {
            'ticker': ticker,
            'meta': self._meta(ctx, setups),
            'bars': self._bars(ctx),
            'indicators': self._indicators(ctx),
            'overlays': overlays,
            'setups': setups,
            'micha': micha,
        }

    # ── JSON serialization ────────────────────────────────────────────────────

    @staticmethod
    def _bars(ctx) -> list:
        return [{
            'time': ctx.times[i], 'open': jnum(ctx.opens[i]), 'high': jnum(ctx.highs[i]),
            'low': jnum(ctx.lows[i]), 'close': jnum(ctx.closes[i]), 'volume': jnum(ctx.vols[i]),
        } for i in range(ctx.M)]

    @staticmethod
    def _indicators(ctx) -> dict:
        out = {}
        for p in SMA_PERIODS:
            col = ctx.w[f'sma{p}'].to_numpy(float)
            out[f'sma{p}'] = [
                {'time': ctx.times[i], 'value': jnum(col[i])}
                for i in range(ctx.M) if not math.isnan(col[i])
            ]
        return out

    @staticmethod
    def _meta(ctx, setups: list) -> dict:
        return {
            'price': jnum(ctx.price), 'atr': jnum(ctx.atr),
            'atr_pct': ctx.atr_pct,
            'vol_tier': ctx.vol_tier,
            'sector': ctx.sector, 'industry': ctx.industry,
            'logo_url': ctx.logo_url, 'sector_icon': ctx.sector_icon,
            'sma150': ctx.sma150, 'sma200': ctx.sma200,
            'sma150_dist_pct': jnum((ctx.price / ctx.sma150 - 1) * 100) if ctx.sma150 else None,
            'sma200_dist_pct': jnum((ctx.price / ctx.sma200 - 1) * 100) if ctx.sma200 else None,
            'above_150': ctx.above_150,
            'above_200': ctx.above_200,
            'ma_context': ctx.ma_context,
            'vol_avg': jnum(ctx.vol_avg),
            'earnings_days': ctx.earnings_days,
            'setup_count': len(setups),
            'setup_codes': [s['code'] for s in setups],
        }
