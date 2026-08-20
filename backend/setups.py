"""
SetupScanner — every chart pattern / setup from the trading spec.

`scan()` runs each detector in a fixed order, appending geometry to `overlays` and
setup cards to `setups`. Detectors are ATR-relative so calm and volatile names are
judged on the same footing. The individual `_detect_*` helpers are pure: they read
the context arrays and return small dicts (or None).
"""

from __future__ import annotations

import math

import numpy as np

from config import (
    BOUNCE_LOOKBACK,
    BULLFLAG_FLAG_BARS,
    BULLFLAG_POLE_BARS,
    BULLFLAG_POLE_GAIN,
    EXTENDED_ATR,
    FIB_MIN_RISE_PCT,
    FIB_ZONE,
    GAP_LOOKBACK,
    NEAR_ATR,
    TRI_RELEVANT_ATR,
    jnum,
)
from geometry import Geometry


class SetupScanner:
    # ── Orchestration ─────────────────────────────────────────────────────────

    def scan(self, ctx, res_levels: list, sup_levels: list,
             overlays: dict, setups: list) -> None:
        times, highs, lows, closes = ctx.times, ctx.highs, ctx.lows, ctx.closes
        M, atr, price, mean_price = ctx.M, ctx.atr, ctx.price, ctx.mean_price
        sh_idx, sl_idx = ctx.sh_idx, ctx.sl_idx

        # ── Trendlines: Micha-style pivot-snapped segments ─────────────────────
        # Anchored at the extreme of the current leg, snapped through touching
        # pivots, and kept only when today's price is actually testing/breaking
        # the line — most charts get one line or none, exactly like his.
        rl_meta = Geometry.segment_trendline(sl_idx, lows, atr, 'rising', M, mean_price)
        fh_meta = Geometry.segment_trendline(sh_idx, highs, atr, 'falling', M, mean_price)

        rising_lows = None
        if rl_meta and Geometry.line_relevant(rl_meta, price, atr):
            rising_lows = Geometry.line_primitive(
                rl_meta['slope'], rl_meta['intercept'], rl_meta['x0'], M - 1, times,
                'rising_lows', '#26a69a', f"Rising lows · {rl_meta['touches']}×")
            # Carry the line's own facts onto the overlay: a rising-lows line that
            # has just been LOST is Micha's "שברה מקו התמיכה שלה" (AVGO) — a real
            # bearish event — and the touch count is what makes the line credible
            # ("high to high to high, four-five highs"). The verdict engine needs
            # both; without them it can only see the line's current price.
            rising_lows.update({'broke': bool(rl_meta['broke']),
                                'touches': int(rl_meta['touches'])})
            overlays['trendlines'].append(rising_lows)

        if fh_meta and Geometry.line_relevant(fh_meta, price, atr):
            falling_highs = Geometry.line_primitive(
                fh_meta['slope'], fh_meta['intercept'], fh_meta['x0'], M - 1, times,
                'falling_highs', '#ef5350', f"Falling highs · {fh_meta['touches']}×")
            falling_highs.update({'broke': bool(fh_meta['broke']),
                                  'touches': int(fh_meta['touches'])})
            overlays['trendlines'].append(falling_highs)

        # ── Triangle (converging segment lines) ────────────────────────────────
        # Near a real apex BOTH lines squeeze around today's price — pairing a fresh
        # falling line with some old rally line whose edge is far below is not a
        # triangle, it's two unrelated lines.
        if rl_meta and fh_meta:
            sL, iL = rl_meta['slope'], rl_meta['intercept']
            sH, iH = fh_meta['slope'], fh_meta['intercept']
            near_apex = (abs(price - rl_meta['line_now']) <= TRI_RELEVANT_ATR * atr
                         and abs(price - fh_meta['line_now']) <= TRI_RELEVANT_ATR * atr)
            if sH != sL and near_apex:
                x_cross = (iL - iH) / (sH - sL)
                upper_now = sH * (M - 1) + iH
                lower_now = sL * (M - 1) + iL
                if (M - 1) < x_cross < (M - 1) + 2 * M and upper_now > lower_now:
                    overlays['triangles'].append({
                        'upper': Geometry.line_primitive(sH, iH, fh_meta['x0'], M - 1, times,
                                                         'triangle_upper', '#ab47bc', 'Triangle'),
                        'lower': Geometry.line_primitive(sL, iL, rl_meta['x0'], M - 1, times,
                                                         'triangle_lower', '#ab47bc', 'Triangle'),
                    })
                    setups.append(self._setup(
                        'triangle', 'Converging triangle',
                        f'Falling highs + rising lows converging ~{int(x_cross - (M - 1))} bars ahead.'))

        # ── Channels: base trendline + parallel rail over the SAME segment ─────
        # Micha's way: find the rising-lows line first, then check whether the highs
        # of that same move ride a parallel rail (BOX: "put a channel here or a
        # highs-line — doesn't matter"). A channel exists only if the rail has its
        # own touches and real width.
        channel_kind = None
        if rl_meta and rl_meta['slope'] > 0:
            rail = Geometry.parallel_rail(rl_meta, sh_idx, highs, atr, M)
            if rail:
                channel_kind = 'rising'
                base_meta, sC, x0 = rl_meta, rl_meta['slope'], rl_meta['x0']
                lower_i, upper_i = rl_meta['intercept'], rail['intercept']
        if channel_kind is None and fh_meta and fh_meta['slope'] < 0:
            rail = Geometry.parallel_rail(fh_meta, sl_idx, lows, atr, M)
            if rail:
                channel_kind = 'descending'
                base_meta, sC, x0 = fh_meta, fh_meta['slope'], fh_meta['x0']
                upper_i, lower_i = fh_meta['intercept'], rail['intercept']
        if channel_kind:
            lower_now = sC * (M - 1) + lower_i
            upper_now = sC * (M - 1) + upper_i
            # relevant only while price still lives inside (or at the edge of) the channel
            if lower_now - atr <= price <= upper_now + atr:
                # WHERE inside the channel price sits is the whole trade for Micha:
                # at the lower rail it's an entry ("תיקון לחלק התחתון של התעלה — מה
                # לבקש יותר" / CAH "כרגע בתחתית שלה, סטופ ב-212"); mid-channel is
                # explicitly nothing ("אין פה משהו אטרקטיבי רק תנועה בתעלה" — RTX).
                span = upper_now - lower_now
                pos_pct = ((price - lower_now) / span * 100) if span > 0 else None
                overlays['channels'].append({
                    'kind': channel_kind,
                    'pos_pct': jnum(pos_pct),
                    'lower_now': jnum(lower_now),
                    'upper_now': jnum(upper_now),
                    'upper': Geometry.line_primitive(sC, upper_i, x0, M - 1, times,
                                                     'channel_upper', '#42a5f5', f'{channel_kind} channel'),
                    'lower': Geometry.line_primitive(sC, lower_i, x0, M - 1, times,
                                                     'channel_lower', '#42a5f5', f'{channel_kind} channel'),
                })
                if channel_kind == 'rising':
                    near_bottom = (price - lower_now) / atr <= NEAR_ATR
                    setups.append(self._setup(
                        'rising_channel', 'Rising channel',
                        'Price near lower rail — room to the top.' if near_bottom
                        else 'Inside a rising channel.', active=near_bottom))
                else:
                    # A descending channel is a falling structure — the tradeable
                    # event is price pushing out of its UPPER rail, which is exactly
                    # Micha's OKLO call ("היא פרצה תעלה יורדת... פריצה מעל 66").
                    breaking_up = (upper_now - price) / atr <= NEAR_ATR
                    setups.append(self._setup(
                        'descending_channel', 'Descending channel',
                        f'Testing the upper rail at {upper_now:.2f} — a break out of a '
                        f'falling channel is the momentum trigger.' if breaking_up
                        else f'Inside a descending channel — upper rail {upper_now:.2f}.',
                        active=breaking_up))

        # ── Bull flag (pole + descending channel breaking up) ──────────────────
        bull = self._detect_bull_flag(closes, highs, lows, M)
        if bull:
            # publish the flag top: while price is under it, that line — not some other
            # broken diagonal — is the operative trigger ("להמתין לסגירה" — LITE)
            overlays['flag_top'] = jnum(bull['top'])
            overlays['flag_breaking'] = bool(bull['breaking'])
            setups.append(self._setup('bull_flag', 'Bull flag', bull['detail'], active=bull['breaking']))
            overlays['markers'].append({
                'time': times[bull['pole_start']], 'position': 'belowBar',
                'color': '#ffb74d', 'shape': 'arrowUp', 'text': 'pole'})

        # ── Fibonacci retracement ──────────────────────────────────────────────
        fib = self._detect_fib(highs, lows, closes, times, price, M, sl_idx)
        if fib:
            overlays['fib'] = fib['overlay']
            setups.append(self._setup('fibonacci', 'Fibonacci retracement', fib['detail'], active=fib['ripe']))

        # ── MA bounce (150 / 200) ──────────────────────────────────────────────
        for p, col in (('150', ctx.w['sma150'].to_numpy(float)),
                       ('200', ctx.w['sma200'].to_numpy(float))):
            b = self._detect_ma_bounce(lows, closes, col, atr, M)
            if b:
                overlays['markers'].append({
                    'time': times[b['idx']], 'position': 'belowBar',
                    # Text-free — a marker anchored a few bars from today can land
                    # close enough to the chart's right edge for its label to overflow
                    # on a narrow phone screen. The cyan arrow itself, distinguishable
                    # from the other marker colors, is enough to mark WHERE it
                    # happened; what it means is already in the setup card / reasons.
                    'color': '#26c6da', 'shape': 'arrowUp', 'text': ''})
                setups.append(self._setup('ma_bounce', f'Bounce off {p}MA',
                                          f'Tagged the {p} SMA and turned back up.'))

        # ── Gaps (recent, unfilled) ────────────────────────────────────────────
        # Also published on `overlays['gaps']` with their price boundaries, because the
        # verdict engine trades them: an unfilled gap overhead supplies target stations
        # ("פתח הגאפ" then "סגירת הגאפ") and one below price is a stop reference.
        # Previously these were drawn as markers and nothing else could see them.
        for g in self._detect_gaps(highs, lows, M):
            overlays['markers'].append({
                'time': times[g['idx']], 'position': 'aboveBar' if g['dir'] == 'down' else 'belowBar',
                'color': '#ef5350' if g['dir'] == 'down' else '#66bb6a',
                'shape': 'circle', 'text': f"gap {g['dir']}"})
            overlays['gaps'].append({
                'time': times[g['idx']], 'dir': g['dir'],
                'near': jnum(g['near']), 'far': jnum(g['far']),
                'filled_pct': None,
            })

        # ── 150MA position + breakout / floor / bearish→bullish ────────────────
        self._detect_ma_context(ctx, res_levels, sup_levels, rising_lows, setups)

        # ── Support test on a broken resistance (bullish "scene of the crime") ──
        # After the S/R engine's role-by-current-price fix, a former resistance that
        # broke upward now sits BELOW price, i.e. in sup_levels, not res_levels.
        st = self._detect_level_retest(closes, sup_levels, price, atr, bullish=True)
        if st:
            self._tag_retest(overlays, st, atr, f"broken R {st['level']:.2f} — {st['state']}")
            setups.append(self._setup('support_test', 'Support test / breakout',
                                      st['detail'], active=st['active']))

        # ── Resistance retest on a broken support (bearish mirror) ──────────────
        # A former support that broke DOWNWARD now sits ABOVE price, in res_levels —
        # Micha's "חוזרת לזירת הפשע": price rallying back up to a level it lost.
        rt = self._detect_level_retest(closes, res_levels, price, atr, bullish=False)
        if rt:
            self._tag_retest(overlays, rt, atr, f"broken S {rt['level']:.2f} — {rt['state']}")
            setups.append(self._setup('resistance_retest', 'Resistance retest (broken support)',
                                      rt['detail'], active=rt['active']))

    @staticmethod
    def _tag_retest(overlays, hit, atr, label) -> None:
        """
        Mark the retested level, don't draw a second one on top of it.

        `_detect_level_retest` picks its level OUT of the same res/sup lists that
        `display_levels` has already drawn, so appending it added a byte-identical
        line at a price that was on the chart. Measured over 404 of his posts run as
        of the day he posted, that made 90% of charts carry a duplicate and 31% of
        all horizontals a redraw of a line already there — the bulk of the "too many
        S/R levels" complaint, and none of it new information.

        The retest is still worth saying; it is a property OF that level ("this is
        the line it broke, and it came back to it"), so it belongs on the level.
        Only when the level did not survive `_select_nearby`'s cut is a new one added.
        """
        lvl = hit['level']
        for existing in overlays['levels']:
            p = existing.get('price')
            if p is not None and abs(p - lvl) <= atr * 0.15:
                existing['freshness'] = 'retested'
                existing['flipped'] = True
                existing['label'] = label
                return
        overlays['levels'].append({
            'type': 'breakout', 'price': jnum(lvl),
            'zone_top': None, 'zone_bottom': None, 'is_zone': False,
            'strength': 'normal', 'freshness': 'retested', 'has_pin': False,
            'flipped': True, 'dist_pct': None, 'dist_atr': None,
            'touches': 0, 'quality': 0, 'label': label})

    # ── Setup card helper ─────────────────────────────────────────────────────

    @staticmethod
    def _setup(code, label, detail, active=True):
        return {'code': code, 'label': label, 'detail': detail, 'active': bool(active)}

    # ── Individual detectors ──────────────────────────────────────────────────

    def _detect_bull_flag(self, closes, highs, lows, M):
        if M < BULLFLAG_POLE_BARS + BULLFLAG_FLAG_BARS + 2:
            return None
        flag = slice(M - BULLFLAG_FLAG_BARS, M)
        pole = slice(M - BULLFLAG_FLAG_BARS - BULLFLAG_POLE_BARS, M - BULLFLAG_FLAG_BARS)
        pole_lo = float(closes[pole].min())
        pole_hi = float(closes[pole].max())
        if pole_lo <= 0:
            return None
        pole_gain = pole_hi / pole_lo - 1
        if pole_gain < BULLFLAG_POLE_GAIN:
            return None
        # flag must drift down / sideways (lower or flat highs)
        fh = highs[flag]
        fit = Geometry.fit(np.arange(len(fh)), fh)
        if fit is None:
            return None
        slope, intercept, _ = fit
        if slope > 0:  # flag rising strongly ⇒ not a flag
            return None
        upper_now = slope * (len(fh) - 1) + intercept
        # A CLOSE above the line, not within 1% of it. The old `>= upper_now * 0.99`
        # declared the break while price was still under the flag — which is exactly
        # the state he refuses to buy: LITE "הדגל השורי רוצה להיפרץ. רוצים לראות
        # סגירה מעל הקו ... להמתין לסגירה" (wants to break; wait for the close).
        breaking = closes[-1] > upper_now
        pole_start = M - BULLFLAG_FLAG_BARS - BULLFLAG_POLE_BARS
        pole_start += int(np.argmin(closes[pole]))
        detail = (f'Pole +{pole_gain * 100:.0f}% then a descending flag; '
                  + (f'closed above the flag top {upper_now:.2f}.' if breaking
                     else f'still inside the flag — needs a close above {upper_now:.2f}.'))
        return {'breaking': breaking, 'detail': detail, 'top': float(upper_now),
                'pole_start': max(0, pole_start)}

    def _detect_fib(self, highs, lows, closes, times, price, M, sl_idx=None):
        mv = Geometry.fib_move(highs, lows, price, swing_lows=sl_idx)
        if mv is None:
            return None
        base, peak = mv['base_idx'], mv['peak_idx']
        base_low, peak_high, rise = mv['base_low'], mv['peak_high'], mv['rise']
        if rise / base_low < FIB_MIN_RISE_PCT:
            return None
        ratios = [0.382, 0.5, 0.618, 0.786]
        levels = [{'ratio': r, 'price': jnum(peak_high - r * rise)} for r in ratios]
        cur = mv['retracement']
        ripe = FIB_ZONE[0] <= cur <= FIB_ZONE[1]
        return {
            'overlay': {
                'base': {'time': times[base], 'price': jnum(base_low)},
                'peak': {'time': times[peak], 'price': jnum(peak_high)},
                'levels': levels,
            },
            'ripe': ripe,
            'detail': (f'Retraced {cur * 100:.0f}% of a +{rise / base_low * 100:.0f}% rise'
                       + (' — sitting in the 0.5–0.618 buy zone.' if ripe else '.')),
        }

    def _detect_ma_bounce(self, lows, closes, ma, atr, M):
        lb = min(BOUNCE_LOOKBACK, M - 1)
        for i in range(M - lb, M):
            if math.isnan(ma[i]):
                continue
            touched = abs(lows[i] - ma[i]) <= NEAR_ATR * atr
            held = closes[i] >= ma[i] - 0.1 * atr
            recovered = closes[-1] > closes[i] and closes[-1] >= ma[-1]
            if touched and held and recovered:
                return {'idx': i}
        return None

    def _detect_gaps(self, highs, lows, M):
        """
        Unfilled gaps, WITH their price boundaries — Micha trades the two edges by
        name: "פתח הגאפ" (the near edge, where the gap starts) is the first target and
        "סגירת הגאפ" (the far edge, a full fill) is the next one, e.g. ANET "היעד
        הראשוני הוא פתח הגאפ. אחרי זה סגירת הגאפ", FTNT "סגירת הגאפ זה היעד הראשון".
        The box itself is also a stop reference ("סטופ מתחת לריבוע הגאפ" — NVO).

        `near`/`far` are relative to CURRENT PRICE, which is what makes them usable as
        an ordered ladder:
          • DOWN gap (price fell through it, so the box sits ABOVE price): the bottom
            of the box — this bar's high — is reached first, so that is `near`; the
            top — the prior bar's low — is the full fill, so that is `far`.
          • UP gap (price rose away from it, box sits BELOW price): the top of the box
            — this bar's low — is `near`; the bottom — the prior bar's high — is `far`.

        Scans the WHOLE display window, not a recent-bars cutoff — a real, unfilled
        gap does not stop being a real, unfilled gap because it aged past an
        arbitrary number of bars. ROP is the case that found this: a genuine -8.2%
        gap from 2025-10-23 (~508) sat well inside the 2-year display window but was
        invisible everywhere — the chart marker, the target ladder, `_grade`'s
        POTENTIAL — because it was ~210 bars old against a 60-bar cutoff. Owner's
        directive (2026-08-20): "gap stay open until it closes" — a gap's relevance
        is decided by whether it has been filled (already checked below, at any
        distance), not by its age. `out[-6:]` still caps what's RETURNED to the 6
        most recently opened unfilled gaps, so this widens what can be FOUND, not
        how much is shown.
        """
        out = []
        for i in range(1, M):
            if lows[i] > highs[i - 1]:
                if not np.any(lows[i + 1:] <= highs[i - 1]):
                    out.append({'idx': i, 'dir': 'up',
                                'near': float(lows[i]), 'far': float(highs[i - 1])})
            elif highs[i] < lows[i - 1]:
                if not np.any(highs[i + 1:] >= lows[i - 1]):
                    out.append({'idx': i, 'dir': 'down',
                                'near': float(highs[i]), 'far': float(lows[i - 1])})
        return out[-6:]

    def _detect_ma_context(self, ctx, res_levels, sup_levels, rising_lows, setups):
        sma150, sma200 = ctx.sma150, ctx.sma200
        price, atr = ctx.price, ctx.atr
        if not sma150:
            return
        closes_full = ctx.fc
        sma_full = ctx.full['sma150'].to_numpy(float)

        if ctx.above_150:
            # ── Breakout candidate: rising lows into nearest resistance ────────
            up = [r for r in res_levels if r['price'] > price]
            if up and rising_lows:
                nearest = min(up, key=lambda r: r['price'])
                dist = (nearest['price'] - price) / atr
                if dist <= NEAR_ATR:
                    ma_label = 'above 150 & 200' if ctx.above_200 else 'above 150 · below 200'
                    setups.append(self._setup(
                        'above150_breakout', f'Rising lows → breakout ({ma_label})',
                        f'Rising-lows trend into resistance {nearest["price"]:.2f} '
                        f'({dist:.1f} ATR away).'))

            # ── 150→200 transition: 200MA overhead acts as resistance ──────────
            if not ctx.above_200 and sma200:
                dist_200 = (sma200 - price) / atr
                if dist_200 <= NEAR_ATR * 2:
                    setups.append(self._setup(
                        'above150_breakout', '150→200 transition zone',
                        f'Above 150MA but facing 200MA resistance at {sma200:.2f} '
                        f'({dist_200:.1f} ATR away) — key decision point.',
                        active=False))

            # ── Bearish→bullish: crashed below 150, now re-established above ───
            look = min(120, len(closes_full))
            seg_c = closes_full[-look:]
            seg_s = sma_full[-look:]
            valid = ~np.isnan(seg_s)
            if valid.any():
                min_gap = float(np.nanmin((seg_c - seg_s)[valid]) / atr)
                recent_above = np.mean(seg_c[-15:] >= seg_s[-15:]) if valid[-15:].any() else 0
                if min_gap < -3.0 and recent_above >= 0.7:
                    setups.append(self._setup(
                        'bearish_to_bullish', 'Bearish→Bullish re-base',
                        'Crashed below the 150MA, now re-establishing above it — high upside.'))
        else:
            # ── Below 150MA: look for a multi-tested support floor ─────────────
            down = [s for s in sup_levels if s['price'] <= price]
            if down:
                floor = max(down, key=lambda s: s['price'])
                dist = (price - floor['price']) / atr
                if dist <= NEAR_ATR and floor['touches'] >= 3:
                    setups.append(self._setup(
                        'below150_floor', 'Below 150MA · support floor',
                        f'Holding a {floor["touches"]}x-tested floor at {floor["price"]:.2f} '
                        f'({dist:.1f} ATR below price).'))

    def _detect_level_retest(self, closes, levels, price, atr, bullish: bool):
        """
        Shared logic for both retest directions Micha treats as mirror images:
          bullish=True  → level WAS resistance and broke upward; price now sits at
                          or above it, retesting it as support ("support test").
          bullish=False → level WAS support and broke downward; price now sits at
                          or below it, retesting it from below as resistance — his
                          "חוזרת לזירת הפשע" (returning to the scene of the crime).
        """
        best = None
        for r in levels:
            lvl = r['price']
            if bullish:
                broke = np.any(closes[:-1] > lvl + 0.2 * atr) and np.any(closes[:-1] <= lvl)
                if not broke or price < lvl - NEAR_ATR * atr:
                    continue
                dist = (price - lvl) / atr
            else:
                broke = np.any(closes[:-1] < lvl - 0.2 * atr) and np.any(closes[:-1] >= lvl)
                if not broke or price > lvl + NEAR_ATR * atr:
                    continue
                dist = (lvl - price) / atr
            if dist > EXTENDED_ATR + 2:
                continue
            if bullish:
                if dist > EXTENDED_ATR:
                    state, active, detail = ('extended', False,
                                             f'{dist:.1f} ATR above a broken level — wait for a pullback.')
                elif dist <= NEAR_ATR:
                    state, active, detail = ('retesting', True,
                                             f'Retesting broken resistance {lvl:.2f} as support — prime entry.')
                else:
                    state, active, detail = ('holding', True,
                                             f'Holding above broken resistance {lvl:.2f} ({dist:.1f} ATR).')
            else:
                if dist > EXTENDED_ATR:
                    state, active, detail = ('extended', False,
                                             f'{dist:.1f} ATR below a broken level — bearish; needs a bounce '
                                             'or a clean breakdown confirmation.')
                elif dist <= NEAR_ATR:
                    state, active, detail = ('retesting', True,
                                             f'Retesting broken support {lvl:.2f} as resistance from below — '
                                             'back at the scene of the crime.')
                else:
                    state, active, detail = ('approaching', True,
                                             f'Approaching broken support {lvl:.2f} as resistance '
                                             f'({dist:.1f} ATR below).')
            cand = {'level': lvl, 'state': state, 'active': active, 'detail': detail, 'dist': dist}
            if best is None or cand['dist'] < best['dist']:
                best = cand
        return best
