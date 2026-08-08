"""
AnalysisContext — the prepared, immutable snapshot of one ticker's price data that
every engine reads from. Building it once (arrays, ATR, MA relationship, swings)
keeps the analysis engines free of data-wrangling and avoids recomputing the same
numpy conversions in each subsystem.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from config import (
    ATR_PCT_HIGH,
    ATR_PCT_LOW,
    VOL_AVG_PERIOD,
    jnum,
)
from geometry import Geometry


@dataclass
class AnalysisContext:
    ticker: str
    full: pd.DataFrame          # 3yr history + indicators (for level touch-counting)
    w: pd.DataFrame             # display window (~2yr) + indicators
    M: int                      # len(w)

    # display-window arrays
    times: list
    opens: np.ndarray
    highs: np.ndarray
    lows: np.ndarray
    closes: np.ndarray
    vols: np.ndarray

    # full-window arrays (touch counting / freshness)
    fo: np.ndarray
    fh: np.ndarray
    fl: np.ndarray
    fc: np.ndarray
    fv: np.ndarray

    # scalars
    atr: float
    price: float
    sma20: float | None
    sma50: float | None
    sma150: float | None
    sma200: float | None
    mean_price: float
    atr_pct: float | None
    vol_tier: str
    vol_avg: float | None
    above_150: bool
    above_200: bool
    ma_context: str

    # swing pivot indices (display window)
    sh_idx: np.ndarray
    sl_idx: np.ndarray

    # optional fundamentals (best-effort; None if the fetch failed)
    market_cap: float | None = None
    earnings_days: int | None = None   # days until next earnings report
    # benchmark closes aligned to the display window, for relative strength
    bench: np.ndarray | None = None
    # header identity — sector/logo for display, not consumed by any indicator
    sector: str | None = None
    industry: str | None = None
    logo_url: str | None = None
    sector_icon: str | None = None

    @classmethod
    def build(cls, ticker: str, full: pd.DataFrame, w: pd.DataFrame,
              market_cap: float | None = None,
              earnings_days: int | None = None,
              bench: pd.Series | None = None,
              profile: dict | None = None) -> "AnalysisContext":
        M = len(w)
        times = w.index.strftime('%Y-%m-%d').tolist()
        opens = w['open'].to_numpy(float)
        highs = w['high'].to_numpy(float)
        lows = w['low'].to_numpy(float)
        closes = w['close'].to_numpy(float)
        vols = w['volume'].to_numpy(float)

        atr = jnum(w['atr'].iloc[-1]) or (float(np.nanmean(highs - lows)) or 1.0)
        price = float(closes[-1])
        sma20 = jnum(w['sma20'].iloc[-1])
        sma50 = jnum(w['sma50'].iloc[-1])
        sma150 = jnum(w['sma150'].iloc[-1])
        sma200 = jnum(w['sma200'].iloc[-1])
        mean_price = float(np.nanmean(closes))

        # ATR% + volatility tier (Micha's green/yellow/red watermark)
        atr_pct = jnum((atr / price) * 100) if price > 0 else None
        vol_tier = ('low' if atr_pct and atr_pct < ATR_PCT_LOW
                    else 'high' if atr_pct and atr_pct >= ATR_PCT_HIGH
                    else 'medium')

        # 20-day volume baseline for breakout confirmation
        vol_avg = (float(np.nanmean(vols[-VOL_AVG_PERIOD:]))
                   if len(vols) >= VOL_AVG_PERIOD else float(np.nanmean(vols)))

        # MA relationship: price vs 150 AND 200 (both are primary trend filters)
        above_150 = bool(sma150 and price >= sma150)
        above_200 = bool(sma200 and price >= sma200)
        if above_150 and above_200:
            ma_context = 'bull'        # above both → strongest bullish bias
        elif above_150:
            ma_context = 'transition'  # 150 < price < 200 → key decision zone
        elif above_200:
            ma_context = 'weak'        # below 150 but above 200 → weakening
        else:
            ma_context = 'bear'        # below both → bearish bias

        sh_idx, sl_idx = Geometry.swings(highs, lows, atr)

        # Align the benchmark onto this stock's own trading days. Holidays and
        # listing gaps differ between symbols, so reindex-and-forward-fill rather
        # than assuming the two series line up; None if it isn't usable.
        bench_arr = None
        if bench is not None and len(bench):
            try:
                aligned = bench.reindex(w.index).ffill().bfill()
                if aligned.notna().all():
                    bench_arr = aligned.to_numpy(float)
            except Exception:
                bench_arr = None

        return cls(
            ticker=ticker, full=full, w=w, M=M,
            times=times, opens=opens, highs=highs, lows=lows, closes=closes, vols=vols,
            fo=full['open'].to_numpy(float), fh=full['high'].to_numpy(float),
            fl=full['low'].to_numpy(float), fc=full['close'].to_numpy(float),
            fv=full['volume'].to_numpy(float),
            atr=atr, price=price, sma20=sma20, sma50=sma50,
            sma150=sma150, sma200=sma200, mean_price=mean_price,
            atr_pct=atr_pct, vol_tier=vol_tier, vol_avg=vol_avg,
            above_150=above_150, above_200=above_200, ma_context=ma_context,
            sh_idx=sh_idx, sl_idx=sl_idx, market_cap=market_cap,
            earnings_days=earnings_days, bench=bench_arr,
            sector=(profile or {}).get('sector'),
            industry=(profile or {}).get('industry'),
            logo_url=(profile or {}).get('logo_url'),
            sector_icon=(profile or {}).get('sector_icon'),
        )
