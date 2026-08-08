"""
Pure trend geometry: swing-pivot detection, least-squares line fitting, the shared
Fibonacci move, and Micha-style segment trendlines / channel rails.

Micha does not regress a line through every pivot of the last two years. He anchors a
line at the extreme of the CURRENT leg (the peak for descending highs, the base for
rising lows), snaps it through the successive swing pivots that touch it ("with
magnets — high to high to high, four, five highs"), deletes lines the moment the
structure stops fitting, and only keeps a line on the chart when today's price is
actually interacting with it. `segment_trendline` reproduces that: pivot-chain
candidates, bar-level validation (price must stay on one side, except a fresh break),
touch counting, and a recency/relevance gate applied by the caller.
"""

from __future__ import annotations

import numpy as np
import scipy.signal as spsignal

from config import (
    CH_MIN_RAIL_TOUCHES,
    CH_MIN_WIDTH_ATR,
    MIN_TREND_SLOPE_PCT,
    PEAK_DISTANCE_BARS,
    RALLY_LOOKBACK_BARS,
    SWING_PROMINENCE_ATR,
    TL_MAX_VIOLATION_BARS,
    TL_MIN_SPAN_BARS,
    TL_MIN_TOUCHES,
    TL_RELEVANT_ATR,
    TL_TOUCH_TOL_ATR,
    jnum,
)


class Geometry:
    # ── Fibonacci move (shared by the overlay + the Micha verdict) ─────────────

    @staticmethod
    def fib_move(highs, lows, price, lookback: int = RALLY_LOOKBACK_BARS, swing_lows=None):
        """
        The move Micha actually retraces: from the peak he's measuring down to the
        base of the *recent rally* that led there — NOT the absolute multi-year low.
        Bounding the base search to ~1 year before the peak grounds it in the recent
        rally; preferring a swing low ignores single-bar wick spikes so the base sits
        on the accumulation structure, closer to what Micha eyeballs.

        Returns dict(base_idx, peak_idx, base_low, peak_high, rise, retracement) or None.
        `retracement` is the fraction of the rise given back (0=at peak, 1=back at base).
        """
        peak = int(np.argmax(highs))
        if peak == 0:
            return None
        lo_start = max(0, peak - lookback)
        # prefer the lowest *swing* low in the window (structural base, not a wick spike)
        base = None
        if swing_lows is not None:
            cand = [int(i) for i in swing_lows if lo_start <= i < peak]
            if cand:
                base = min(cand, key=lambda i: lows[i])
        if base is None:
            base = lo_start + int(np.argmin(lows[lo_start:peak]))
        base_low = float(lows[base])
        peak_high = float(highs[peak])
        rise = peak_high - base_low
        if base_low <= 0 or rise <= 0 or price >= peak_high:
            return None
        return {
            'base_idx': base, 'peak_idx': peak,
            'base_low': base_low, 'peak_high': peak_high,
            'rise': rise, 'retracement': (peak_high - price) / rise,
        }

    # ── Swing pivots ──────────────────────────────────────────────────────────

    @staticmethod
    def swings(highs, lows, atr) -> tuple[np.ndarray, np.ndarray]:
        """Indices of swing highs and swing lows (prominence scaled by ATR)."""
        prom = max(atr * SWING_PROMINENCE_ATR, 1e-6)
        hi, _ = spsignal.find_peaks(highs, distance=PEAK_DISTANCE_BARS, prominence=prom)
        lo, _ = spsignal.find_peaks(-lows, distance=PEAK_DISTANCE_BARS, prominence=prom)
        return hi, lo

    # ── Regression ────────────────────────────────────────────────────────────

    @staticmethod
    def fit(xs, ys):
        """Return (slope, intercept, r2) for a least-squares line, or None."""
        if len(xs) < 2:
            return None
        xs = np.asarray(xs, float)
        ys = np.asarray(ys, float)
        slope, intercept = np.polyfit(xs, ys, 1)
        pred = slope * xs + intercept
        ss_res = float(np.sum((ys - pred) ** 2))
        ss_tot = float(np.sum((ys - ys.mean()) ** 2))
        r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
        return slope, intercept, r2

    # ── Micha-style segment trendlines ────────────────────────────────────────

    @staticmethod
    def segment_trendline(pivots, values, atr: float, direction: str, M: int,
                          mean_price: float):
        """
        Find the best pivot-snapped trendline segment, the way Micha draws one.

        direction='falling' → descending-highs line: `pivots`/`values` are swing-high
        indices / the highs array; the line caps price from above.
        direction='rising'  → rising-lows line: swing lows; the line holds price from
        below.

        Anchor candidates are chain heads — pivots not exceeded by any later pivot
        (the peak of the current leg, then each successively lower peak). For each
        anchor, every later pivot is tried as the line's second point; the line is
        valid only if no bar crosses it by more than the touch tolerance — except
        within the last TL_MAX_VIOLATION_BARS, which is a fresh break (a breakout,
        not an invalid line). Best line = most pivot touches, then most recent anchor.

        Returns dict(slope, intercept, x0, touches, broke, line_now) or None.
        """
        piv = [int(i) for i in pivots]
        if len(piv) < 2:
            return None
        vals = np.asarray(values, float)
        tol = atr * TL_TOUCH_TOL_ATR
        is_falling = direction == 'falling'

        # Chain heads: for a falling line, pivots higher than every later pivot;
        # mirror for rising. These are the anchors Micha starts his lines from.
        anchors = []
        for j in piv:
            later = [k for k in piv if k > j]
            if not later:
                continue
            if is_falling and all(vals[k] < vals[j] for k in later):
                anchors.append(j)
            elif not is_falling and all(vals[k] > vals[j] for k in later):
                anchors.append(j)

        best = None
        for anchor in anchors:
            for second in (k for k in piv if k > anchor + PEAK_DISTANCE_BARS):
                if is_falling and vals[second] >= vals[anchor]:
                    continue
                if not is_falling and vals[second] <= vals[anchor]:
                    continue
                slope = (vals[second] - vals[anchor]) / (second - anchor)
                # a near-flat line is a horizontal level — the S/R engine's job
                if abs(slope / mean_price * 100) < MIN_TREND_SLOPE_PCT:
                    continue
                intercept = vals[anchor] - slope * anchor
                if M - 1 - anchor < TL_MIN_SPAN_BARS:
                    continue

                # Bar-level validation: price stays on the correct side of the line
                # over the whole segment, except a fresh crossing at the right edge.
                xs = np.arange(anchor, M)
                line = slope * xs + intercept
                if is_falling:
                    viol = np.nonzero(vals[anchor:M] > line + tol)[0]
                else:
                    viol = np.nonzero(vals[anchor:M] < line - tol)[0]
                broke = False
                if viol.size:
                    if anchor + int(viol[0]) < M - TL_MAX_VIOLATION_BARS:
                        continue          # an old crossing — the line never held
                    broke = True          # crossed only in recent bars = fresh break

                # Touches: pivots within tolerance of the line (anchor included).
                # A standing line needs TL_MIN_TOUCHES; a 2-touch line counts too
                # when it was JUST broken — the break is the third interaction
                # (Micha's "high to high — and now it's breaking" calls, e.g. WGMI).
                touches = sum(
                    1 for j in piv
                    if j >= anchor and abs(vals[j] - (slope * j + intercept)) <= tol
                )
                if touches < TL_MIN_TOUCHES and not (touches >= 2 and broke):
                    continue

                cand = {
                    'slope': slope, 'intercept': intercept, 'x0': anchor,
                    'touches': touches, 'broke': broke,
                    'line_now': slope * (M - 1) + intercept,
                }
                if best is None or (cand['touches'], cand['x0']) > (best['touches'], best['x0']):
                    best = cand
        return best

    @staticmethod
    def line_relevant(meta, price: float, atr: float) -> bool:
        """
        Micha keeps a line on the chart only when it matters TODAY: price is close
        enough to be testing it, or has just broken through it.
        """
        if meta is None:
            return False
        if meta['broke']:
            return True
        return abs(price - meta['line_now']) <= TL_RELEVANT_ATR * atr

    @staticmethod
    def parallel_rail(meta, other_pivots, other_values, atr: float, M: int):
        """
        Channel rail: same slope as the base trendline, snapped to the extreme pivot
        on the OTHER side within the line's own segment (Micha: rising-lows line
        first, then the parallel line over the highs of the same move). Requires its
        own touches and a real width — otherwise there is no channel to speak of.

        Returns dict(intercept, touches, width) or None.
        """
        if meta is None:
            return None
        piv = [int(i) for i in other_pivots if i >= meta['x0']]
        if len(piv) < CH_MIN_RAIL_TOUCHES:
            return None
        vals = np.asarray(other_values, float)
        slope = meta['slope']
        offsets = [vals[j] - slope * j for j in piv]
        # rail hugs the extreme offset: max for an upper rail, min for a lower one
        upper_side = np.mean(offsets) > meta['intercept']
        rail_intercept = max(offsets) if upper_side else min(offsets)
        tol = atr * TL_TOUCH_TOL_ATR
        touches = sum(1 for j in piv
                      if abs(vals[j] - (slope * j + rail_intercept)) <= tol)
        width = abs(rail_intercept - meta['intercept'])
        if touches < CH_MIN_RAIL_TOUCHES or width < CH_MIN_WIDTH_ATR * atr:
            return None
        return {'intercept': rail_intercept, 'touches': touches, 'width': width}

    # ── Line primitives ───────────────────────────────────────────────────────

    @staticmethod
    def line_primitive(slope, intercept, x0, x1, times, kind, color, label) -> dict:
        return {
            'kind': kind, 'color': color, 'label': label,
            'p1': {'time': times[x0], 'price': jnum(slope * x0 + intercept)},
            'p2': {'time': times[x1], 'price': jnum(slope * x1 + intercept)},
        }
