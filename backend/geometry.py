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

    @staticmethod
    def pivot_strength(highs, lows, sh_idx, sl_idx, atr, never_bonus: int):
        """
        Per pivot: prominence in ATR (how far price reversed before taking the pivot
        out) and dominance in bars (how long it had stood as the extreme — bars back to
        a higher high / lower low; never exceeded = its index plus `never_bonus`).
        Returns two dicts keyed by bar index: highs, lows → (prominence, dominance).
        """
        a = max(atr, 1e-9)

        def one(series, idx, sign):
            out = {}
            if not len(idx):
                return out
            prom = spsignal.peak_prominences(sign * series, idx)[0] / a
            for i, p in zip((int(x) for x in idx), prom):
                beyond = np.where(sign * series[:i] > sign * series[i])[0]
                dom = (i - int(beyond[-1])) if len(beyond) else i + never_bonus
                out[i] = (float(p), int(dom))
            return out

        return one(np.asarray(highs, float), sh_idx, 1.0), one(np.asarray(lows, float), sl_idx, -1.0)

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
                touch_devs = [
                    abs(vals[j] - (slope * j + intercept)) for j in piv if j >= anchor
                    and abs(vals[j] - (slope * j + intercept)) <= tol
                ]
                touches = len(touch_devs)
                if touches < TL_MIN_TOUCHES and not (touches >= 2 and broke):
                    continue

                cand = {
                    'slope': slope, 'intercept': intercept, 'x0': anchor,
                    'touches': touches, 'broke': broke,
                    'line_now': slope * (M - 1) + intercept,
                    # mean distance from the line to the pivots it claims to touch —
                    # "how magnetized is this line", not just "how many touches".
                    # `tol` (0.5 ATR) is generous on purpose so a real trend survives
                    # normal noise, but that same slack let the OLD tie-break (touch
                    # count, then just the most recent anchor) pick a candidate that
                    # technically touches enough pivots while sitting visibly off of
                    # them — reported repeatedly as a line "cutting through candles"
                    # instead of hugging their wicks. Real analyst notes on ARM/BR
                    # confirmed it: two candidates tied on touch count, one fit within
                    # 0.30 ATR of its pivots, the other (chosen, purely for being more
                    # recent) sat 0.43 ATR off. Tightness now breaks the tie instead.
                    'mean_dev': sum(touch_devs) / touches if touches else tol,
                }
                key = (cand['touches'], -cand['mean_dev'], cand['x0'])
                if best is None or key > (best['touches'], -best['mean_dev'], best['x0']):
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

    @staticmethod
    def leg_channel(sh_idx, sl_idx, highs, lows, atr: float, M: int, mean_price: float,
                    min_bars: int, min_width_atr: float, recent_break_bars: int):
        """
        The channel he draws: anchored at the START of the current leg, not the
        best-touched line anywhere on the chart.

        His channels (IWM from the 2025-04 low, CAH from 195.54 after its gap, ASTS
        from 49.31, AAPL from 169.21) start at the leg's extreme — a swing low no
        later low undercuts (rising) / a swing high no later high exceeds
        (descending) — run a base rail through a later pivot on the same side, and
        put the parallel rail through the leg's most extreme opposite point, so the
        whole leg lives inside. The old builder took `segment_trendline`'s pick
        (most touches over the whole window), which on CAH was a pre-gap line from
        80.9 and read "top of the channel" where he says "at its bottom".

        Candidates need >= 2 pivots on EACH rail, a span of `min_bars`, and a real
        width; among valid ones the MOST RECENT anchor wins (his current leg), then
        the most rail touches. A close through the base rail is allowed only inside
        the last `recent_break_bars` (a fresh break, not an invalid channel).

        Returns dict(kind, slope, lower_i, upper_i, x0, touches, broke) or None.
        """
        tol = atr * TL_TOUCH_TOL_ATR
        hi = np.asarray(highs, float)
        lo = np.asarray(lows, float)
        best = None
        for kind, base_piv, base_vals, other_piv, other_vals in (
                ('rising', [int(i) for i in sl_idx], lo, [int(i) for i in sh_idx], hi),
                ('descending', [int(i) for i in sh_idx], hi, [int(i) for i in sl_idx], lo)):
            rising = kind == 'rising'
            for a in base_piv:
                if M - 1 - a < min_bars:
                    continue
                later = [k for k in base_piv if k > a]
                if not later:
                    continue
                # the leg's extreme: never undercut (rising) / exceeded (descending)
                if rising and any(base_vals[k] < base_vals[a] for k in later):
                    continue
                if not rising and any(base_vals[k] > base_vals[a] for k in later):
                    continue
                for b in later:
                    if b - a < PEAK_DISTANCE_BARS:
                        continue
                    slope = (base_vals[b] - base_vals[a]) / (b - a)
                    if rising and slope <= 0 or not rising and slope >= 0:
                        continue
                    if abs(slope / mean_price * 100) < MIN_TREND_SLOPE_PCT:
                        continue
                    icpt = base_vals[a] - slope * a
                    xs = np.arange(a, M)
                    line = slope * xs + icpt
                    seg = base_vals[a:M]
                    viol = np.nonzero(seg < line - tol)[0] if rising else np.nonzero(seg > line + tol)[0]
                    broke = False
                    if viol.size:
                        if a + int(viol[0]) < M - recent_break_bars:
                            continue
                        broke = True
                    # the opposite rail through the leg's most extreme opposite point
                    off = other_vals[a:M] - slope * xs
                    o_icpt = float(off.max()) if rising else float(off.min())
                    width = abs(o_icpt - icpt)
                    if width < min_width_atr * atr:
                        continue
                    b_t = sum(1 for j in base_piv if j >= a
                              and abs(base_vals[j] - (slope * j + icpt)) <= tol)
                    o_t = sum(1 for j in other_piv if j >= a
                              and abs(other_vals[j] - (slope * j + o_icpt)) <= tol)
                    if b_t < 2 or o_t < 2:
                        continue
                    cand = {'kind': kind, 'slope': slope, 'x0': a, 'broke': broke,
                            'touches': b_t + o_t,
                            'lower_i': icpt if rising else o_icpt,
                            'upper_i': o_icpt if rising else icpt}
                    # Most respected channel first — rail touches, less a charge for
                    # width so an envelope around two years of chop can't win on
                    # touches alone — then the more recent leg.
                    cand['score'] = b_t + o_t - (width / atr) / 3.0
                    key = (round(cand['score'], 3), a)
                    if best is None or key > (round(best['score'], 3), best['x0']):
                        best = cand
        return best

    # ── Line primitives ───────────────────────────────────────────────────────

    @staticmethod
    def line_primitive(slope, intercept, x0, x1, times, kind, color, label) -> dict:
        return {
            'kind': kind, 'color': color, 'label': label,
            'p1': {'time': times[x0], 'price': jnum(slope * x0 + intercept)},
            'p2': {'time': times[x1], 'price': jnum(slope * x1 + intercept)},
        }
