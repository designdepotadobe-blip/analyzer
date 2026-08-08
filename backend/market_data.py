"""
Data acquisition + indicator computation.

`MarketData` fetches raw OHLCV history from yahooquery, normalizes the index, and
attaches the SMA family and Wilder's ATR. Downloads are cached per ticker for a short
TTL so that a scan followed by an explicit analyze (or overlapping scans) does not
re-hit the network for the same symbol.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
from urllib.parse import urlparse

import numpy as np
import pandas as pd
import yahooquery as yq

from config import (
    ATR_PERIOD,
    FETCH_CACHE_TTL,
    HISTORY_INTERVAL,
    HISTORY_PERIOD,
    SMA_PERIODS,
)

_REQUIRED = ('open', 'high', 'low', 'close', 'volume')

# GICS-ish sector -> one glyph, for the header chip when there's no company logo
# (an ETF/index has no `asset_profile`, so this is also the fallback for those).
SECTOR_ICONS = {
    'Technology': '💻',
    'Communication Services': '📡',
    'Consumer Cyclical': '🛍️',
    'Consumer Defensive': '🛒',
    'Energy': '⛽',
    'Financial Services': '🏦',
    'Financials': '🏦',
    'Healthcare': '⚕️',
    'Health Care': '⚕️',
    'Industrials': '🏭',
    'Real Estate': '🏢',
    'Basic Materials': '⚗️',
    'Materials': '⚗️',
    'Utilities': '💡',
}
DEFAULT_SECTOR_ICON = '📈'


def _root_domain(host: str) -> str:
    """
    'about.gitlab.com' -> 'gitlab.com'. Yahoo's `website` field is often a marketing
    subdomain with no logo asset of its own (GitLab's is `about.gitlab.com`), so
    Clearbit needs the registrable domain, not the exact host. Naive last-two-labels
    heuristic — wrong for a country-code TLD like `co.uk`, but the client falls back
    to the sector emoji on a failed image load, so a wrong guess costs a glyph, not
    a broken page.
    """
    host = host.lower().removeprefix('www.')
    parts = host.split('.')
    return '.'.join(parts[-2:]) if len(parts) >= 2 else host


class MarketData:
    """
    All network access, with two costs kept firmly under control.

    Constructing a `yahooquery.Ticker` is expensive — measured at ~3 s, because it
    negotiates Yahoo's cookie/crumb before the first request. The original code paid
    that FOUR times per analysed symbol (history, price, calendar, profile each built
    their own throwaway `Ticker`), which is where ~90% of a 17-35 s "analyze" went.
    Two changes fix it without altering a single returned value:

      • one `Ticker` per symbol, cached and reused for all four calls;
      • every `Ticker` after the first reuses the FIRST one's session, so the crumb
        handshake is amortised across the process rather than repeated per symbol
        (measured: ~3.0 s → ~0.2 s per new symbol).

    That session must be yahooquery's own — handing `Ticker` a plain
    `requests.Session` looks like it works (construction succeeds, `.price` returns
    data) but silently breaks `history()`, which needs the crumb and otherwise fails
    deep inside with `KeyError: '<SYMBOL>'`. Take the session off a real `Ticker`.

    Everything is still fetched from the same endpoints via the same accessors, so
    the DATA is identical — only the number of TCP/TLS handshakes changes.

    Thread-safety matters here because `/api/scan` analyses symbols on a thread pool.
    `requests.Session` is safe for concurrent GETs (urllib3's pool is), but building a
    `Ticker` mutates shared session state, so construction is serialised behind a lock
    and the caches are written under it too.
    """

    def __init__(self, history_period: str = HISTORY_PERIOD,
                 interval: str = HISTORY_INTERVAL,
                 cache_ttl: float = FETCH_CACHE_TTL):
        self.history_period = history_period
        self.interval = interval
        self.cache_ttl = cache_ttl
        self._cache: dict[str, tuple[float, pd.DataFrame]] = {}
        self._cap_cache: dict[str, Optional[float]] = {}
        self._earn_cache: dict[str, Optional[int]] = {}
        self._profile_cache: dict[str, dict] = {}
        self._session = None            # yahooquery's own session, from the 1st Ticker
        self._tickers: dict[str, object] = {}
        self._lock = threading.Lock()

    def _tk(self, symbol: str):
        """
        The one `Ticker` for this symbol, built at most once per process.

        Construction is serialised behind the lock ON PURPOSE. Letting the scan's
        eight workers build theirs concurrently was measured as almost four times
        SLOWER end to end (12 symbols: 11.9 s locked vs 43.9 s unlocked) — Yahoo
        throttles a burst of parallel handshakes, and the retries cost far more than
        the serialisation saves. The lock doubles as a crude rate limiter, which is
        the behaviour we want against this API.
        """
        t = self._tickers.get(symbol)
        if t is not None:
            return t
        with self._lock:
            t = self._tickers.get(symbol)
            if t is None:
                if self._session is None:
                    # first symbol pays the cookie/crumb negotiation for everyone
                    t = yq.Ticker(symbol)
                    self._session = t.session
                else:
                    t = yq.Ticker(symbol, session=self._session)
                self._tickers[symbol] = t
            return t

    def prime(self, ticker: str) -> None:
        """
        Warm every per-symbol lookup an analysis needs, in one place.

        The four fetches are independent HTTP GETs on an already-built `Ticker`, so
        they run concurrently — turning ~0.7 s of serial round trips into roughly the
        slowest one. `Ticker` construction happens first (and under the lock) so the
        threads never race to negotiate the crumb.

        Purely a warm-up: every call underneath is individually cached and safe on its
        own, so `prime` failing costs speed, never correctness.
        """
        self._tk(ticker)                      # pay construction once, up front
        jobs = (
            lambda: self.fetch(ticker),
            lambda: self.market_cap(ticker),
            lambda: self.earnings_days(ticker),
            lambda: self.profile(ticker),
        )
        with ThreadPoolExecutor(max_workers=len(jobs)) as ex:
            for fut in [ex.submit(j) for j in jobs]:
                try:
                    fut.result()
                except Exception:
                    pass                      # each getter already degrades to None

    # ── Fetch ─────────────────────────────────────────────────────────────────

    def fetch(self, ticker: str) -> Optional[pd.DataFrame]:
        """Cached OHLCV history for `ticker`, or None if unavailable."""
        now = time.monotonic()
        hit = self._cache.get(ticker)
        if hit is not None and now - hit[0] < self.cache_ttl:
            return hit[1]
        df = self._download(ticker)
        if df is not None:
            self._cache[ticker] = (now, df)
        return df

    def _download(self, ticker: str) -> Optional[pd.DataFrame]:
        try:
            raw = self._tk(ticker).history(period=self.history_period,
                                           interval=self.interval)
        except Exception:
            return None
        if not isinstance(raw, pd.DataFrame) or raw.empty:
            return None
        # Flatten MultiIndex (symbol, date) → date
        if isinstance(raw.index, pd.MultiIndex):
            raw = raw.reset_index(level=0, drop=True)
        # Ensure a proper DatetimeIndex
        if not isinstance(raw.index, pd.DatetimeIndex):
            try:
                raw.index = pd.to_datetime(raw.index)
            except Exception:
                return None
        # Strip timezone so strftime is unambiguous
        if raw.index.tz is not None:
            raw.index = raw.index.tz_localize(None)
        raw = raw.sort_index()
        raw = raw[~raw.index.duplicated(keep='last')]
        if not set(_REQUIRED).issubset(raw.columns):
            return None
        return raw.dropna(subset=list(_REQUIRED))

    def benchmark(self, symbol: str = 'SPY') -> Optional[pd.Series]:
        """
        Close series for the market benchmark, so a stock can be read RELATIVE to it.

        He reads this constantly — NVDA "עדיין יותר זולה מהסנפ והנסדק 100", AMD "ביחס
        לסנפ 500 הגענו לנקודה שכבר קפצנו ממנה בעבר - זה האיתות?" — because a name
        going up while the market goes up is not the same as one leading it.

        Uses the same TTL cache as any other fetch, so a 60-name scan pays for it once.
        """
        df = self.fetch(symbol)
        if df is None or 'close' not in df:
            return None
        return df['close']

    def market_cap(self, ticker: str) -> Optional[float]:
        """Best-effort market cap (cached for the process). None if unavailable —
        Micha screens out sub-$1B names, so this feeds the relevance/grade only."""
        if ticker in self._cap_cache:
            return self._cap_cache[ticker]
        cap: Optional[float] = None
        try:
            price = self._tk(ticker).price
            if isinstance(price, dict):
                info = price.get(ticker)
                if isinstance(info, dict):
                    cap = info.get('marketCap')
        except Exception:
            cap = None
        cap = float(cap) if cap else None
        self._cap_cache[ticker] = cap
        return cap

    def profile(self, ticker: str) -> dict:
        """
        Best-effort sector/industry + a company logo URL, for the header. Cached for
        the process. ETFs/indices (XLV, SPY, BTCUSD...) have no `asset_profile` — the
        caller falls back to a generic icon rather than treating that as an error.
        """
        if ticker in self._profile_cache:
            return self._profile_cache[ticker]
        out = {'sector': None, 'industry': None, 'logo_url': None,
              'sector_icon': DEFAULT_SECTOR_ICON}
        try:
            prof = self._tk(ticker).asset_profile
            info = prof.get(ticker) if isinstance(prof, dict) else None
            if isinstance(info, dict):
                sector = info.get('sector')
                out['sector'] = sector
                out['industry'] = info.get('industry')
                out['sector_icon'] = SECTOR_ICONS.get(sector, DEFAULT_SECTOR_ICON)
                website = info.get('website')
                if website:
                    domain = urlparse(website).netloc or urlparse(f'//{website}').netloc
                    domain = _root_domain(domain)
                    if domain:
                        # clearbit's logo CDN, keyed by company domain — no API key,
                        # fetched client-side as a plain <img>; the client falls back
                        # to `sector_icon` on a 404 (private/thinly-covered names)
                        out['logo_url'] = f'https://logo.clearbit.com/{domain}?size=64'
        except Exception:
            pass
        self._profile_cache[ticker] = out
        return out

    def earnings_days(self, ticker: str) -> Optional[int]:
        """Days until the next earnings report (Micha's watermark countdown).
        Best-effort via yahooquery calendar; None if unavailable."""
        if ticker in self._earn_cache:
            return self._earn_cache[ticker]
        days: Optional[int] = None
        try:
            cal = self._tk(ticker).calendar_events
            if isinstance(cal, dict):
                info = cal.get(ticker)
                if isinstance(info, dict):
                    dates = (info.get('earnings') or {}).get('earningsDate') or []
                    today = pd.Timestamp.now().normalize()
                    future = []
                    for d in dates:
                        ts = pd.to_datetime(d, errors='coerce')
                        if ts is not None and not pd.isna(ts):
                            delta = (ts.normalize() - today).days
                            if delta >= 0:
                                future.append(delta)
                    if future:
                        days = min(future)
        except Exception:
            days = None
        self._earn_cache[ticker] = days
        return days

    # ── Indicators ──────────────────────────────────────────────────────────────

    @staticmethod
    def atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> pd.Series:
        """
        Wilder's ATR (matches TradingView ta.rma / TA-Lib):
          first value = SMA of the first `period` true-range bars
          subsequent  = (prev_ATR × (period−1) + TR) / period
        Retains all historical volatility with exponential decay, unlike a simple
        rolling mean which drops data older than `period` bars.
        """
        h, l, c = df['high'], df['low'], df['close']
        prev = c.shift(1)
        tr = pd.concat([h - l, (h - prev).abs(), (l - prev).abs()], axis=1).max(axis=1)

        tr_vals = tr.to_numpy(float)
        atr_vals = np.full(len(tr_vals), np.nan)
        if len(tr_vals) > period:
            # tr[0] is NaN (prev close undefined); first valid TR is tr[1]
            atr_vals[period] = np.nanmean(tr_vals[1:period + 1])
            for i in range(period + 1, len(tr_vals)):
                atr_vals[i] = (atr_vals[i - 1] * (period - 1) + tr_vals[i]) / period
        return pd.Series(atr_vals, index=df.index)

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        for p in SMA_PERIODS:
            df[f'sma{p}'] = df['close'].rolling(p).mean()
        df['atr'] = self.atr(df)
        return df
