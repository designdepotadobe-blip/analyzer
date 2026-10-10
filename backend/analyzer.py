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

import pandas as pd
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

    def analyze(self, ticker: str, live: bool = False) -> Optional[dict]:
        # Warm history + market cap + earnings + profile together. They are four
        # independent GETs that used to run one after another, each building its own
        # `Ticker` (~3 s of cookie/crumb setup apiece); priming pays that once and
        # overlaps the rest. Every getter below is still individually cached, so this
        # is an optimisation only — remove it and the results are unchanged.
        self.data.prime(ticker)

        raw = self.data.fetch(ticker)
        if raw is None or len(raw) < MIN_BARS:
            return None

        # ── The latest price, not the last close (single-stock view) ──────────
        # In session, today's bar is refreshed from the live quote so every reading
        # — and the call — sits on the current price. Pre-market / after-hours carry
        # no real volume, so they are NOT folded into the bars (a fake bar would
        # corrupt the volume and candle reads); they are reported beside the call.
        quote = self.data.quote(ticker) if live else None
        if quote and quote.get('state') == 'REGULAR' and quote.get('price'):
            raw = raw.copy()
            last = raw.index[-1]
            qd = pd.Timestamp(quote['time'][:10]) if quote.get('time') else None
            if qd is not None and last.normalize() == qd.normalize():
                raw.loc[last, 'close'] = quote['price']
                if quote.get('high'):
                    raw.loc[last, 'high'] = max(raw.loc[last, 'high'], quote['high'], quote['price'])
                if quote.get('low'):
                    raw.loc[last, 'low'] = min(raw.loc[last, 'low'], quote['low'], quote['price'])
                if quote.get('volume'):
                    raw.loc[last, 'volume'] = max(raw.loc[last, 'volume'], quote['volume'])
            elif qd is not None and qd > last and quote.get('open'):
                raw.loc[qd] = {**{c: raw[c].iloc[-1] for c in raw.columns},
                               'open': quote['open'], 'high': quote.get('high') or quote['price'],
                               'low': quote.get('low') or quote['price'], 'close': quote['price'],
                               'volume': quote.get('volume') or 0}
                raw = raw.sort_index()

        # ── The decision is made on CLOSED bars ───────────────────────────────
        # During the session today's daily bar is unfinished: its close, its range
        # and its volume move every minute, and every rule that reads the last bar
        # (the buyers' candle, the floor touch, volume, the % to a line, the 5-day
        # run) flipped with it — measured: 3 of 40 names changed state and 19 of 40
        # changed score inside 9 minutes on 0.1-0.3% moves. He decides on the close
        # ("הפריצה נספרת בסגירה"), so the engine reads the bars up to yesterday's
        # close while the session runs; the chart, the header price and a "live now"
        # line still show today. The verdict changes once a day, after the close.
        partial = self._partial_today(raw, quote)
        closed = raw.iloc[:-1] if partial else raw

        # Indicators are computed on the full 3-year fetch, so SMA150 is already
        # warmed up by the time the display window begins — no NaN gap.
        full = self.data.add_indicators(closed).sort_index()
        w = full.tail(self.window_bars).copy()
        if len(w) < MIN_BARS:
            return None
        if partial:
            full_d = self.data.add_indicators(raw).sort_index()
            w_d = full_d.tail(self.window_bars).copy()
        else:
            full_d, w_d = full, w

        market_cap = self.data.market_cap(ticker)
        earnings_days = self.data.earnings_days(ticker)
        profile = self.data.profile(ticker)
        # the benchmark is TTL-cached, so a whole scan fetches it once
        bench = self.data.benchmark() if ticker != 'SPY' else None
        ctx = AnalysisContext.build(ticker, full, w, market_cap=market_cap,
                                    earnings_days=earnings_days, bench=bench,
                                    profile=profile)
        # what the reader SEES: today's live candle included
        dctx = (AnalysisContext.build(ticker, full_d, w_d, market_cap=market_cap,
                                      earnings_days=earnings_days, bench=bench,
                                      profile=profile) if partial else ctx)

        overlays = {
            'levels': [], 'trendlines': [], 'channels': [],
            'triangles': [], 'fib': None, 'markers': [], 'gaps': [],
            'flag_top': None, 'flag_breaking': False,
            # every swing pivot, price-tagged. This is the most consistent thing on
            # his charts and the thing ours had none of: OKE carries 45 labelled
            # turns, OKTA 25, NOW 7 — the count tracks the timeframe, not a cap. The
            # levels are drawn ON TOP of the labels, so a reader can see which turns
            # a line was fitted to instead of taking the line on faith.
            'swings': [],
        }
        setups: list[dict] = []

        overlays['swings'] = self._swings(ctx)

        # ── Support / resistance ───────────────────────────────────────────────
        res_levels, sup_levels = self.levels.build(ctx)
        overlays['levels'] = self.levels.display_levels(ctx, res_levels, sup_levels)
        overlays['markers'].extend(
            self.levels.breakout_markers(ctx, res_levels + sup_levels))

        # ── Chart-pattern setups (mutate overlays + setups in place) ───────────
        self.setups.scan(ctx, res_levels, sup_levels, overlays, setups)

        # ── Micha-style verdict (read-only side service) ───────────────────────
        micha = self.micha.evaluate(ctx, res_levels, sup_levels, setups, overlays)
        if quote or partial:
            from verdict import extended_hours
            extended_hours(micha, quote, float(ctx.price),
                           live_price=float(dctx.price) if partial else None)

        return {
            'ticker': ticker,
            'meta': {**self._meta(dctx, setups), 'quote': quote,
                     # the verdict's own reference: the last CLOSED bar
                     'decided_on': ctx.times[-1], 'decided_close': jnum(ctx.price),
                     'session_live': bool(partial)},
            'bars': self._bars(dctx),
            'indicators': self._indicators(dctx),
            'overlays': overlays,
            'setups': setups,
            'micha': micha,
        }

    @staticmethod
    def _partial_today(raw, quote) -> bool:
        """Is the last daily bar today's UNFINISHED session bar?"""
        from datetime import datetime
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo('America/New_York'))
        if raw is None or raw.empty or raw.index[-1].date() != now.date():
            return False
        st = (quote or {}).get('state')
        if st:
            return st == 'REGULAR'
        return now.weekday() < 5 and (now.hour, now.minute) < (16, 0)

    # ── JSON serialization ────────────────────────────────────────────────────

    @staticmethod
    def _swings(ctx) -> list:
        """
        The labelled turns. `sh_idx`/`sl_idx` are already computed for the level
        engine and the geometry fits — this only serialises them, so nothing about
        the analysis changes, the chart just stops hiding what it was reading.
        """
        out = []
        for idx, kind, series in ((ctx.sh_idx, 'high', ctx.highs),
                                  (ctx.sl_idx, 'low', ctx.lows)):
            for i in idx:
                i = int(i)
                if 0 <= i < ctx.M:
                    out.append({'time': ctx.times[i], 'price': jnum(series[i]),
                                'kind': kind})
        out.sort(key=lambda s: s['time'])
        return out

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
