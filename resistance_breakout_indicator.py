import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scipy.signal as spsignal
import yahooquery as yq
import mplfinance as mpf
from typing import Optional

# ─── Hard filters ─────────────────────────────────────────────────────────────
SMA_PERIOD = 150
ATR_PERIOD = 14

# Price must be above SMA150, or at most this many ATRs below it.
MAX_ATR_DISTANCE_SMA = 1.0

# SMA150 must be higher now than it was this many bars ago (upward slope required).
SMA_SLOPE_LOOKBACK = 10

# "Knocking on door" – price must be within this many ATRs below the resistance zone.
# 0.5 ATR is tight: the stock is almost touching the level.
NEAR_RESISTANCE_ATR = 0.5

# A resistance zone must have produced at least this average % gain on past breakouts
# to be considered a high-quality level worth trading.
MIN_RESISTANCE_QUALITY = 5.0

# After breaking the target resistance, the next ceiling must be at least this many
# ATRs away.  Ensures there is genuine room to run post-breakout.
MIN_ROOM_TO_GROW_ATR = 3.0

# ─── Scoring bonuses (don't filter out, but rank higher) ──────────────────────
# VCP (Volatility Contraction Pattern): recent N-bar ATR / full-period ATR < ratio
# means the stock is quietly coiling near resistance — classic pre-breakout behaviour.
VCP_RECENT_BARS = 10
VCP_ATR_RATIO = 0.8

# Volume dry-up: recent avg volume / 50-bar avg < ratio.
# Low volume consolidation near resistance is very bullish (no sellers).
VOLUME_DRY_BARS = 10
VOLUME_DRY_RATIO = 0.8

# ─── S/R detection parameters ─────────────────────────────────────────────────
BREAKOUT_LOOKFORWARD = 20   # bars forward to measure post-breakout gain
MIN_LEVEL_TOUCHES = 2       # minimum touches to count as a real zone
CLUSTER_ATR_FACTOR = 0.5    # merge pivots within this many ATRs
PEAK_DISTANCE_BARS = 5      # min bar gap between pivots
ON_SUPPORT_ATR = 0.5        # Setup B: price within this many ATRs above support

HISTORY_PERIOD = '2y'
HISTORY_INTERVAL = '1d'
CHART_DISPLAY_BARS = 252    # ≈ 1 trading year shown on each chart
# ─────────────────────────────────────────────────────────────────────────────


class ResistanceBreakoutIndicator:
    """
    Screens for Setup A only: stock is in a confirmed uptrend (above rising SMA150),
    coiling quietly just below a high-quality resistance zone, with clear room above
    after the breakout.

    Filtering logic (all must pass):
      1. Price ≥ SMA150 − (MAX_ATR_DISTANCE_SMA × ATR)
      2. SMA150 sloping upward
      3. Price within NEAR_RESISTANCE_ATR of resistance
      4. Resistance quality score ≥ MIN_RESISTANCE_QUALITY
      5. Next resistance ≥ MIN_ROOM_TO_GROW_ATR above target

    Ranking (composite score, higher = stronger):
      + Quality score of resistance level (history of big post-breakout moves)
      + Number of touches (zone strength)
      + Proximity bonus (closer to resistance = more actionable)
      + Room to grow (% to next ceiling)
      + VCP bonus (volatility contraction = coiling)
      + Volume dry-up bonus (no supply near resistance)
      + SMA50 > SMA150 alignment bonus
      + SMA150 > SMA200 alignment bonus
    """

    def __init__(
        self,
        history_period: str = HISTORY_PERIOD,
        sma_period: int = SMA_PERIOD,
        atr_period: int = ATR_PERIOD,
        max_atr_distance_sma: float = MAX_ATR_DISTANCE_SMA,
        sma_slope_lookback: int = SMA_SLOPE_LOOKBACK,
        near_resistance_atr: float = NEAR_RESISTANCE_ATR,
        min_resistance_quality: float = MIN_RESISTANCE_QUALITY,
        min_room_to_grow_atr: float = MIN_ROOM_TO_GROW_ATR,
        on_support_atr: float = ON_SUPPORT_ATR,
        vcp_recent_bars: int = VCP_RECENT_BARS,
        vcp_atr_ratio: float = VCP_ATR_RATIO,
        volume_dry_bars: int = VOLUME_DRY_BARS,
        volume_dry_ratio: float = VOLUME_DRY_RATIO,
        breakout_lookforward: int = BREAKOUT_LOOKFORWARD,
        min_level_touches: int = MIN_LEVEL_TOUCHES,
        cluster_atr_factor: float = CLUSTER_ATR_FACTOR,
        peak_distance_bars: int = PEAK_DISTANCE_BARS,
        chart_display_bars: int = CHART_DISPLAY_BARS,
    ):
        self.history_period = history_period
        self.sma_period = sma_period
        self.atr_period = atr_period
        self.max_atr_distance_sma = max_atr_distance_sma
        self.sma_slope_lookback = sma_slope_lookback
        self.near_resistance_atr = near_resistance_atr
        self.min_resistance_quality = min_resistance_quality
        self.min_room_to_grow_atr = min_room_to_grow_atr
        self.on_support_atr = on_support_atr
        self.vcp_recent_bars = vcp_recent_bars
        self.vcp_atr_ratio = vcp_atr_ratio
        self.volume_dry_bars = volume_dry_bars
        self.volume_dry_ratio = volume_dry_ratio
        self.breakout_lookforward = breakout_lookforward
        self.min_level_touches = min_level_touches
        self.cluster_atr_factor = cluster_atr_factor
        self.peak_distance_bars = peak_distance_bars
        self.chart_display_bars = chart_display_bars

    # ── Indicators ────────────────────────────────────────────────────────────

    @staticmethod
    def _compute_atr(df: pd.DataFrame, period: int) -> pd.Series:
        h, l, c = df['high'], df['low'], df['close']
        prev_c = c.shift(1)
        tr = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
        return tr.rolling(period).mean()

    def _add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df['sma150'] = df['close'].rolling(self.sma_period).mean()
        df['vol_avg50'] = df['volume'].rolling(50).mean()
        df['atr'] = self._compute_atr(df, self.atr_period)
        return df

    # ── SMA / trend filter ────────────────────────────────────────────────────

    def _passes_sma_filter(self, df: pd.DataFrame) -> bool:
        """
        Two hard requirements:
          1. Price is not more than MAX_ATR_DISTANCE_SMA × ATR below SMA150.
          2. SMA150 is sloping upward (current > SMA_SLOPE_LOOKBACK bars ago).
        Together these confirm a Stage 2 uptrend (Minervini terminology).
        """
        last = df.iloc[-1]
        price, sma150, atr = last['close'], last['sma150'], last['atr']

        if pd.isna(sma150) or pd.isna(atr) or atr == 0:
            return False

        # Too far below SMA150
        if (sma150 - price) / atr > self.max_atr_distance_sma:
            return False

        # SMA150 must be rising — flat or falling SMA means no uptrend
        lb = min(self.sma_slope_lookback, len(df) - 1)
        if df['sma150'].iloc[-1] <= df['sma150'].iloc[-(lb + 1)]:
            return False

        return True

    # ── Pivot detection & clustering ──────────────────────────────────────────

    def _find_raw_pivots(self, df: pd.DataFrame) -> tuple[list[float], list[float]]:
        highs, lows = df['high'].values, df['low'].values
        peak_idx, _ = spsignal.find_peaks(highs, distance=self.peak_distance_bars)
        trough_idx, _ = spsignal.find_peaks(-lows, distance=self.peak_distance_bars)
        return highs[peak_idx].tolist(), lows[trough_idx].tolist()

    def _cluster_levels(self, prices: list[float], atr: float) -> list[dict]:
        """
        Merge pivots within CLUSTER_ATR_FACTOR × ATR into one zone.
        ATR-scaled threshold keeps zones proportional to stock volatility.
        Zones below MIN_LEVEL_TOUCHES are discarded.
        """
        if not prices:
            return []
        threshold = atr * self.cluster_atr_factor
        clusters: list[list[float]] = [[sorted(prices)[0]]]
        for p in sorted(prices)[1:]:
            if p - clusters[-1][-1] <= threshold:
                clusters[-1].append(p)
            else:
                clusters.append([p])
        return [
            {'price': float(np.mean(c)), 'touches': len(c)}
            for c in clusters
            if len(c) >= self.min_level_touches
        ]

    # ── Resistance quality scoring ─────────────────────────────────────────────

    def _score_resistance(self, df: pd.DataFrame, resistance_price: float) -> float:
        """
        For every past confirmed breakout (prev close ≤ level, current close > level),
        measure the max % gain in the next BREAKOUT_LOOKFORWARD bars.
        Quality score = mean of those gains.
        High score → this level historically launched big moves when broken.
        """
        closes, highs = df['close'].values, df['high'].values
        n = len(closes)
        gains: list[float] = []
        for i in range(1, n - 1):
            if closes[i - 1] <= resistance_price < closes[i]:
                end = min(i + 1 + self.breakout_lookforward, n)
                fwd = highs[i + 1:end]
                if len(fwd):
                    gains.append((fwd.max() / closes[i] - 1) * 100)
        return float(np.mean(gains)) if gains else 0.0

    # ── Confirmation signals (bonus scoring) ──────────────────────────────────

    def _compute_confirmations(self, df: pd.DataFrame) -> dict:
        """
        VCP (Volatility Contraction Pattern): recent ATR contracting vs full-period ATR.
        Volume dry-up: recent avg volume below the 50-bar average.
        SMA alignment: whether the bullish SMA stack (50 > 150 > 200) is intact.
        """
        recent_atr = df['atr'].iloc[-self.vcp_recent_bars:].mean()
        full_atr = df['atr'].dropna().mean()
        vcp = bool(full_atr > 0 and recent_atr / full_atr < self.vcp_atr_ratio)

        recent_vol = df['volume'].iloc[-self.volume_dry_bars:].mean()
        avg_vol = df['volume'].iloc[-50:].mean()
        vol_dry = bool(avg_vol > 0 and recent_vol / avg_vol < self.volume_dry_ratio)

        return {
            'vcp_confirmed': vcp,
            'volume_dry_up': vol_dry,
        }

    # ── Composite score ───────────────────────────────────────────────────────

    def _compute_score(self, result: dict) -> float:
        """
        Single ranking number so the best setups float to the top of the output table.

        Component breakdown (max ~100 pts):
          Quality score  × 2  (0–30)  — how well did past breakouts perform
          Touches        × 3  (0–15)  — zone strength (more tests = more reliable)
          Proximity            (0–20)  — closer to resistance = more actionable
          Room to grow         (0–15)  — % to next ceiling after breakout
          VCP bonus            (+10)   — volatility contraction = coiling
          Volume dry-up        (+5)    — no supply = buyers in control
          SMA50>150 bonus      (+5)    — full bullish SMA alignment
          SMA150>200 bonus     (+5)    — long-term uptrend confirmed
        """
        score = 0.0
        score += min(result.get('res_quality_score', 0) * 2, 30)
        score += min(result.get('res_touches', 0) * 3, 15)
        dist = result.get('res_dist_atr', self.near_resistance_atr)
        score += max(0.0, (1 - dist / self.near_resistance_atr) * 20)
        score += min(result.get('room_to_grow_pct', 0) / 2, 15)
        if result.get('vcp_confirmed'):
            score += 10
        if result.get('volume_dry_up'):
            score += 5
        return round(score, 1)

    # ── Setup detection ───────────────────────────────────────────────────────

    def _find_setups(
        self,
        df: pd.DataFrame,
        resistance_levels: list[dict],
        support_levels: list[dict],
    ) -> Optional[dict]:
        last = df.iloc[-1]
        price, sma150, atr = last['close'], last['sma150'], last['atr']

        confirmations = self._compute_confirmations(df)
        setups: list[str] = []
        best_resistance: Optional[dict] = None
        best_support: Optional[dict] = None

        # ── Setup A ───────────────────────────────────────────────────────────
        # Gate 1: proximity + minimum quality
        candidates_a = [
            r for r in resistance_levels
            if r['price'] > price
            and (r['price'] - price) / atr <= self.near_resistance_atr
            and r.get('quality_score', 0) >= self.min_resistance_quality
        ]

        # Gate 2: room to grow — next resistance must be far enough above
        valid_a: list[dict] = []
        for r in candidates_a:
            above = [x for x in resistance_levels if x['price'] > r['price'] + atr * 0.3]
            if above:
                next_r = min(above, key=lambda x: x['price'])
                room_atr = (next_r['price'] - r['price']) / atr
                if room_atr < self.min_room_to_grow_atr:
                    continue   # next wall is too close — no room to run
                room_pct = round((next_r['price'] / r['price'] - 1) * 100, 1)
                valid_a.append({**r, 'next_resistance': next_r['price'], 'room_to_grow_pct': room_pct})
            else:
                # No ceiling detected above — unlimited upside
                valid_a.append({**r, 'next_resistance': None, 'room_to_grow_pct': 99.0})

        if valid_a:
            best_resistance = {**max(valid_a, key=lambda r: r['quality_score'])}
            best_resistance['distance_atr'] = (best_resistance['price'] - price) / atr
            setups.append('A')

        # ── Setup B ───────────────────────────────────────────────────────────
        candidates_b = [
            s for s in support_levels
            if s['price'] < price and (price - s['price']) / atr <= self.on_support_atr
        ]
        if candidates_b:
            best_support = {**min(candidates_b, key=lambda s: price - s['price'])}
            best_support['distance_atr'] = (price - best_support['price']) / atr
            setups.append('B')

        if not setups:
            return None

        result: dict = {
            'setup': '+'.join(sorted(set(setups))),
            'current_price': round(price, 2),
            'sma150': round(sma150, 2),
            'sma_distance_pct': round((price / sma150 - 1) * 100, 2),
            'atr': round(atr, 2),
            **confirmations,
        }

        if best_resistance:
            result.update({
                'nearest_resistance': round(best_resistance['price'], 2),
                'res_touches': best_resistance['touches'],
                'res_quality_score': round(best_resistance['quality_score'], 2),
                'res_dist_atr': round(best_resistance['distance_atr'], 2),
                'room_to_grow_pct': best_resistance['room_to_grow_pct'],
            })

        if best_support:
            result.update({
                'nearest_support': round(best_support['price'], 2),
                'sup_touches': best_support['touches'],
                'sup_dist_atr': round(best_support['distance_atr'], 2),
            })

        result['score'] = self._compute_score(result)
        return result

    # ── Visualization ─────────────────────────────────────────────────────────

    def draw_stock_view(
        self,
        ticker: str,
        df: pd.DataFrame,
        result: dict,
        resistance_levels: list[dict],
        support_levels: list[dict],
    ) -> None:
        """
        Candlestick chart showing:
          Blue  – SMA150 (trend baseline)
          Orange – SMA50  (medium-term trend)
          Purple dashed – SMA200 (long-term trend)
          Volume bar average line in the volume panel
          Red dashed – resistance zones (active = bright, thick)
          Green dashed – support zones (active = bright, thick)
          Gold – current price marker
          Room-to-grow arrow on active resistance
        Title includes setup label, score, VCP/vol-dry flags.
        """
        df_plot = df.tail(self.chart_display_bars).copy()
        df_plot.index = pd.to_datetime(df_plot.index, utc=True)

        setup = result['setup']
        price = result['current_price']
        sma_pct = result['sma_distance_pct']
        atr = result['atr']
        score = result.get('score', 0)
        vcp_tag = ' [VCP]' if result.get('vcp_confirmed') else ''
        vol_tag = ' [VolDry]' if result.get('volume_dry_up') else ''

        title = (
            f"{ticker}  |  Setup: {setup}  |  Score: {score}"
            f"{vcp_tag}{vol_tag}  |  "
            f"Price: \${price:.2f}  |  SMA150 dist: {sma_pct:+.1f}%  |  ATR: \${atr:.2f}"
        )

        addplots = [
            mpf.make_addplot(df_plot['sma150'], color='dodgerblue', width=1.8, panel=0),
            mpf.make_addplot(df_plot['vol_avg50'], color='yellow', width=1.0,
                             alpha=0.7, panel=1),
        ]

        fig, axes = mpf.plot(
            df_plot,
            type='candle',
            style='charles',
            title=title,
            volume=True,
            addplot=addplots,
            returnfig=True,
            figsize=(17, 9),
        )

        ax = axes[0]
        xlim = ax.get_xlim()
        span = xlim[1] - xlim[0]
        x_left = xlim[0] + span * 0.01
        x_mid  = xlim[0] + span * 0.50

        active_res = result.get('nearest_resistance')
        active_sup = result.get('nearest_support')

        # ── Resistance zones ──────────────────────────────────────────────────
        for r in sorted(resistance_levels, key=lambda x: x['price'], reverse=True):
            is_active = active_res is not None and abs(r['price'] - active_res) < 0.02 * r['price']
            color = '#ff3333' if is_active else '#994444'
            lw = 2.2 if is_active else 0.9
            alpha = 1.0 if is_active else 0.55
            q = r.get('quality_score', 0.0)
            tag = '  ◄ target' if is_active else ''
            label = f"  R \${r['price']:.2f}  t={r['touches']}  q={q:.1f}%{tag}"
            ax.axhline(r['price'], color=color, linestyle='--', linewidth=lw, alpha=alpha)
            ax.text(x_left, r['price'], label, color=color, fontsize=7.5,
                    va='bottom', fontweight='bold' if is_active else 'normal')

        # ── Room-to-grow bracket on active resistance ─────────────────────────
        if active_res and result.get('room_to_grow_pct', 0) < 90:
            next_r = result.get('nearest_resistance', active_res) * (1 + result['room_to_grow_pct'] / 100)
            ax.annotate(
                '',
                xy=(xlim[1] - span * 0.04, next_r),
                xytext=(xlim[1] - span * 0.04, active_res),
                arrowprops=dict(arrowstyle='<->', color='yellow', lw=1.5),
            )
            ax.text(
                xlim[1] - span * 0.03, (active_res + next_r) / 2,
                f" +{result['room_to_grow_pct']:.1f}%",
                color='yellow', fontsize=7.5, va='center',
            )

        # ── Support zones ─────────────────────────────────────────────────────
        for s in sorted(support_levels, key=lambda x: x['price']):
            is_active = active_sup is not None and abs(s['price'] - active_sup) < 0.02 * s['price']
            color = '#00dd55' if is_active else '#448866'
            lw = 2.2 if is_active else 0.9
            alpha = 1.0 if is_active else 0.55
            tag = '  ◄ active' if is_active else ''
            label = f"  S \${s['price']:.2f}  t={s['touches']}{tag}"
            ax.axhline(s['price'], color=color, linestyle='--', linewidth=lw, alpha=alpha)
            ax.text(x_mid, s['price'], label, color=color, fontsize=7.5,
                    va='bottom', fontweight='bold' if is_active else 'normal')

        # ── Current price marker ──────────────────────────────────────────────
        ax.axhline(price, color='gold', linestyle='-', linewidth=1.2, alpha=0.9)
        ax.text(xlim[1] - span * 0.01, price, f" \${price:.2f}",
                color='gold', fontsize=8, va='bottom', ha='right', fontweight='bold')

        # ── Legend ────────────────────────────────────────────────────────────
        from matplotlib.lines import Line2D
        ax.legend(handles=[
            Line2D([0], [0], color='dodgerblue', linewidth=1.8, label='SMA150'),
        ], loc='upper left', fontsize=8, framealpha=0.5)

        fig.tight_layout()

    # ── Public API ─────────────────────────────────────────────────────────────

    def analyze_ticker(self, ticker: str) -> Optional[dict]:
        print(f'  scanning {ticker} ...')
        raw = yq.Ticker(ticker).history(
            period=self.history_period, interval=HISTORY_INTERVAL
        ).reset_index(level=0, drop=True)

        if raw is None or len(raw) < self.sma_period + 60:
            print(f'    {ticker}: insufficient history')
            return None

        df = self._add_indicators(raw)

        if not self._passes_sma_filter(df):
            return None

        atr = df['atr'].iloc[-1]
        raw_res, raw_sup = self._find_raw_pivots(df)
        resistance_levels = self._cluster_levels(raw_res, atr)
        support_levels    = self._cluster_levels(raw_sup, atr)

        for lvl in resistance_levels:
            lvl['quality_score'] = self._score_resistance(df, lvl['price'])

        result = self._find_setups(df, resistance_levels, support_levels)

        if result:
            result['ticker'] = ticker
            flags = []
            if result.get('vcp_confirmed'):   flags.append('VCP')
            if result.get('volume_dry_up'):   flags.append('VolDry')
            flag_str = f"  [{', '.join(flags)}]" if flags else ''
            print(f'    {ticker}: setup {result["setup"]}  score={result["score"]}{flag_str}  ✓')
            self.draw_stock_view(ticker, df, result, resistance_levels, support_levels)

        return result

    def scan_tickers(self, tickers) -> pd.DataFrame:
        results: list[dict] = []
        print('Scanning — SMA150 uptrend + knocking on high-quality resistance + room to grow')

        for ticker in tickers:
            try:
                result = self.analyze_ticker(ticker)
                if result:
                    results.append(result)
            except Exception as e:
                print(f'    error on {ticker}: {e}')

        plt.show()

        df = pd.DataFrame(results)
        if not df.empty:
            cols = [
                'ticker', 'score', 'setup',
                'current_price', 'sma150', 'sma_distance_pct', 'atr',
                'nearest_resistance', 'res_touches', 'res_quality_score',
                'res_dist_atr', 'room_to_grow_pct',
                'nearest_support', 'sup_touches', 'sup_dist_atr',
                'vcp_confirmed', 'volume_dry_up',
            ]
            ordered = [c for c in cols if c in df.columns]
            df = df[ordered].sort_values('score', ascending=False).reset_index(drop=True)
        return df
