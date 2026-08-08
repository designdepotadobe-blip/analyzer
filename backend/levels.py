"""
LevelEngine — horizontal support / resistance.

Core idea (from watching Micha analyze charts): a price level is a single piece of
"price memory" — it doesn't matter whether it was originally a swing HIGH or a swing
LOW. What matters is which side of the CURRENT price it sits on right now, because
that determines whether it acts as a ceiling or a floor today. A level price sometimes
gets touched from both directions over the years — Micha calls returning to such a
level "חוזרת לזירת הפשע" (returning to the scene of the crime): an old high that
finally gets reclaimed, or an old low that gets lost and later retested from below.
The old code clustered highs and lows into two SEPARATE pools and bucketed display by
which pool a level came from — so a broken support sitting ABOVE price (now overhead
resistance) was invisible, because it lived only in the "support" pool. This version
clusters ALL swing pivots into ONE pool, scores each level's touch quality from BOTH
directions, then assigns today's role (resistance/support) purely by current price.

Pipeline:
  1. cluster ALL swing pivots (highs + lows) into one pool of price-memory levels
  2. score each level's rejection quality from both directions (as-resistance / as-support)
  3. assign today's role by current price; flag levels touched from both sides ("flipped")
  4. tag freshness (fresh / retested) and drop absorbed levels
  5. refine each level's zone boundary (wick extreme → candle body), role-aware
  6. inject tight consolidation bases as extra levels
  7. select the few nearest/strongest per side and merge coincident R/S into zones
Also emits volume-confirmed breakout markers.
"""

from __future__ import annotations

import numpy as np

from config import (
    ABSORPTION_PCT,
    CLUSTER_ATR_FACTOR,
    LEVEL_MAX_SPAN_ATR,
    CONSOL_MAX_RANGE,
    CONSOL_MIN_BARS,
    LEVEL_MAX_SHOW,
    LEVEL_NEAR_ATR,
    LEVEL_NEAR_BUCKET_ATR,
    LEVEL_STRONG_TOUCHES,
    MIN_LEVEL_TOUCHES,
    PEAK_DISTANCE_BARS,
    SR_KEEP_TOUCHES,
    SR_MERGE_ATR,
    VOL_BREAKOUT_LOOKBACK,
    VOL_SPIKE_FACTOR,
    ZONE_MIN_SPREAD_ATR,
    jnum,
)


class LevelEngine:
    # ── Public pipeline ───────────────────────────────────────────────────────

    def build(self, ctx) -> tuple[list, list]:
        """Full clustered/scored/filtered R and S level lists for `ctx`."""
        all_pivots = np.concatenate([ctx.highs[ctx.sh_idx], ctx.lows[ctx.sl_idx]])
        levels = self._cluster(all_pivots, ctx.atr)

        # Score every bar in the full 3-year history from BOTH directions — a level
        # may have rejected price as resistance in one era and held it as support in
        # another. We keep both scores and pick the one matching today's role next.
        self._recount_touches(levels, ctx.fh, ctx.fl, ctx.fo, ctx.fc, ctx.fv, ctx.atr, 'resistance')
        self._recount_touches(levels, ctx.fh, ctx.fl, ctx.fo, ctx.fc, ctx.fv, ctx.atr, 'support')
        self._assign_role(levels, ctx.price)

        # NB: this FILTERS as well as tags — levels recent price has traded clean
        # through are dropped. The return value used to be discarded, so absorbed
        # levels stayed in the map and could be quoted as live support/resistance.
        levels = self._mark_freshness(levels, ctx.fc, ctx.closes, ctx.atr)
        self._refine_boundaries(ctx, levels)

        for cz in self._consolidation_zones(ctx.highs, ctx.lows, ctx.closes, ctx.atr, ctx.M):
            cz['type'] = 'resistance' if cz['price'] > ctx.price else 'support'
            levels.append(cz)

        res_levels = [lvl for lvl in levels if lvl['type'] == 'resistance']
        sup_levels = [lvl for lvl in levels if lvl['type'] == 'support']
        return res_levels, sup_levels

    def display_levels(self, ctx, res_levels: list, sup_levels: list) -> list:
        """The <=LEVEL_MAX_SHOW-per-side levels to draw, with coincident R/S merged into zones."""
        selected = self._select_nearby(ctx, res_levels, sup_levels)
        return self._merge_pairs(ctx, selected)

    def breakout_markers(self, ctx, levels: list) -> list:
        """
        First clean cross above each strong level in the recent window.
        Green arrow = volume-confirmed (≥1.5× 20-day avg), orange = unconfirmed.

        Takes ALL levels, not just the ones currently overhead: the most important
        breakout of all is the one that just happened, and after it the level sits
        BELOW price (it flipped to support), so scanning resistances alone missed
        exactly the event the marker exists to show.
        """
        markers: list[dict] = []
        brk_lookback = min(VOL_BREAKOUT_LOOKBACK, ctx.M - 1)
        brk_bars: set[int] = set()
        closes, vols, times, atr = ctx.closes, ctx.vols, ctx.times, ctx.atr
        for r in sorted(levels, key=lambda x: x['touches'], reverse=True)[:12]:
            lvl = r['price']
            for i in range(max(1, ctx.M - brk_lookback), ctx.M):
                if i in brk_bars:
                    continue
                if closes[i - 1] <= lvl < closes[i] and (closes[i] - lvl) > 0.05 * atr:
                    vol_ok = bool(ctx.vol_avg and ctx.vol_avg > 0 and vols[i] >= ctx.vol_avg * VOL_SPIKE_FACTOR)
                    markers.append({
                        'time': times[i], 'position': 'belowBar',
                        'color': '#00e676' if vol_ok else '#ff9800',
                        'shape': 'arrowUp',
                        'text': 'vol ✓' if vol_ok else 'break',
                    })
                    brk_bars.add(i)
                    break
        return markers

    # ── Clustering ────────────────────────────────────────────────────────────

    @staticmethod
    def _cluster(prices, atr: float) -> list:
        if len(prices) == 0:
            return []
        thr = atr * CLUSTER_ATR_FACTOR
        span = atr * LEVEL_MAX_SPAN_ATR
        prices = sorted(prices)
        clusters = [[prices[0]]]
        for p in prices[1:]:
            # Both tests matter. The first keeps genuinely adjacent pivots together;
            # the second stops single-linkage chaining from walking a cluster across
            # the whole chart one 0.59-ATR step at a time (see LEVEL_MAX_SPAN_ATR).
            if p - clusters[-1][-1] <= thr and p - clusters[-1][0] <= span:
                clusters[-1].append(p)
            else:
                clusters.append([p])
        result = []
        for c in clusters:
            if len(c) < MIN_LEVEL_TOUCHES:
                continue
            result.append({
                'price':  float(np.mean(c)),
                'top':    float(max(c)),
                'bottom': float(min(c)),
                'spread': float(max(c) - min(c)),
                'touches': len(c),
            })
        return result

    @staticmethod
    def _recount_touches(levels: list, highs, lows, opens, closes, vols, atr: float,
                         level_type: str) -> list:
        """
        For each clustered level, scan every historical bar to count genuine
        approaches FROM ONE DIRECTION and score rejection quality:
          • wick size relative to the bar range (longer wick = cleaner rejection)
          • candle direction (close opposite to approach = confirmed rejection)
          • volume bonus (≥1.3× average = institutional activity)

        Results are written to direction-specific keys (`res_touches`/`sup_touches`,
        etc.) so a level can hold BOTH a resistance-history and a support-history —
        `_assign_role` later picks whichever matches today's actual position.
        """
        if not levels:
            return levels
        avg_vol = float(np.nanmean(vols)) or 1.0
        tol = atr * 0.4        # within 0.4 ATR → "at the level"
        gap = PEAK_DISTANCE_BARS  # min bars between counted approaches
        is_res = level_type == 'resistance'
        pfx = 'res' if is_res else 'sup'

        for lvl in levels:
            lp = lvl['price']
            q_list: list[float] = []
            has_pin = False
            last_i = -gap * 2

            for i in range(len(closes)):
                if i - last_i < gap:
                    continue
                total = highs[i] - lows[i]
                if total < 1e-9:
                    continue

                if is_res:
                    # Approached from below, high reached the zone, didn't close far above
                    if not (lows[i] < lp and highs[i] >= lp - tol and closes[i] <= lp + atr * 0.5):
                        continue
                    body_top = max(opens[i], closes[i])
                    wick = max(0.0, highs[i] - body_top)
                    q = (wick / total) * (1.3 if closes[i] < opens[i] else 1.0)
                else:  # support
                    # Approached from above, low reached the zone, didn't close far below
                    if not (highs[i] > lp and lows[i] <= lp + tol and closes[i] >= lp - atr * 0.5):
                        continue
                    body_bot = min(opens[i], closes[i])
                    wick = max(0.0, body_bot - lows[i])
                    q = (wick / total) * (1.3 if closes[i] > opens[i] else 1.0)

                if vols[i] >= avg_vol * 1.3:
                    q *= 1.2

                # Pin bar: wick ≥ 2× body and close driven to the far end of the bar
                if not has_pin:
                    body = abs(closes[i] - opens[i])
                    mid_bar = lows[i] + total * 0.5
                    if is_res:
                        has_pin = bool(wick >= 2 * body and closes[i] <= mid_bar)
                    else:
                        has_pin = bool(wick >= 2 * body and closes[i] >= mid_bar)

                q_list.append(q)
                last_i = i

            avg_q = float(np.mean(q_list)) if q_list else 0.0
            lvl[f'{pfx}_touches'] = max(lvl['touches'], len(q_list))
            lvl[f'{pfx}_quality'] = round(avg_q, 3)
            lvl[f'{pfx}_has_pin'] = has_pin

        return levels

    @staticmethod
    def _assign_role(levels: list, price: float) -> None:
        """
        Pick today's role (resistance if the level sits above price, support if
        below) and copy that direction's touch/quality/pin data onto the canonical
        'touches'/'quality'/'strength'/'has_pin' fields the rest of the pipeline (and
        the frontend) reads. `flipped=True` marks a level with a genuine touch
        history on BOTH sides — Micha's "used to be support/resistance, now the
        other way around" — the level to watch when price comes back to it.
        """
        for lvl in levels:
            is_res = lvl['price'] > price
            lvl['type'] = 'resistance' if is_res else 'support'
            pfx = 'res' if is_res else 'sup'
            other = 'sup' if is_res else 'res'
            lvl['touches'] = lvl.get(f'{pfx}_touches', lvl['touches'])
            lvl['quality'] = lvl.get(f'{pfx}_quality', 0.0)
            lvl['has_pin'] = lvl.get(f'{pfx}_has_pin', False)
            lvl['strength'] = ('strong' if lvl['touches'] >= LEVEL_STRONG_TOUCHES
                               or lvl['quality'] >= 0.40 else 'normal')
            # flipped = genuinely tested from the OTHER side too (not just the
            # min-2-point cluster minimum) — a real role reversal, not noise.
            lvl['flipped'] = bool(lvl.get(f'{other}_touches', 0) >= MIN_LEVEL_TOUCHES)

    @staticmethod
    def _mark_freshness(levels: list, closes_full, closes_display, atr: float) -> list:
        """
        Tag each level 'fresh' (never crossed) or 'retested' (crossed before, price
        came back to the SAME side). Drop levels that recent price has traded
        through so thoroughly they no longer hold (absorbed). Role-aware: reads
        `lvl['type']` per level since resistance and support now share one list.
        """
        recent = closes_display[-30:]
        tol = atr * 0.25
        keep = []
        for lvl in levels:
            lp = lvl['price']
            if lvl['type'] == 'resistance':
                ever_above = bool(np.any(closes_full > lp + tol))
                lvl['freshness'] = 'retested' if ever_above else 'fresh'
                if float(np.mean(recent > lp + tol)) >= ABSORPTION_PCT:
                    continue
            else:
                ever_below = bool(np.any(closes_full < lp - tol))
                lvl['freshness'] = 'retested' if ever_below else 'fresh'
                if float(np.mean(recent < lp - tol)) >= ABSORPTION_PCT:
                    continue
            keep.append(lvl)
        return keep

    @staticmethod
    def _consolidation_zones(highs, lows, closes, atr: float, M: int) -> list:
        """
        Tight sideways ranges (high-low ≤ 1.5 ATR for ≥8 consecutive bars). Prior
        consolidations near current price act as strong S/R — areas where supply and
        demand were in balance. Returns the 2 most recently formed.
        """
        price = closes[-1]
        zones: list[dict] = []
        i = 0
        while i <= M - CONSOL_MIN_BARS:
            zh, zl = highs[i], lows[i]
            j = i
            while j < M:
                zh = max(zh, highs[j])
                zl = min(zl, lows[j])
                if zh - zl > CONSOL_MAX_RANGE * atr:
                    break
                j += 1
            length = j - i
            if length >= CONSOL_MIN_BARS and j < M - 2:  # exclude current bars
                mid = (zh + zl) / 2.0
                if abs(mid - price) / atr <= LEVEL_NEAR_ATR:
                    zones.append({
                        'price':     float(mid),
                        'top':       float(zh),
                        'bottom':    float(zl),
                        'spread':    float(zh - zl),
                        'touches':   max(2, length // 4),
                        'quality':   min(0.45, length / 25.0),
                        'strength':  'strong' if length >= 15 else 'normal',
                        'freshness': 'fresh',
                        'has_pin':   False,
                        'flipped':   False,
                        'is_consol': True,
                    })
                i = max(i + 1, j - CONSOL_MIN_BARS // 2)
            else:
                i += 1
        return zones[-2:]

    # ── Boundary refinement ───────────────────────────────────────────────────

    @staticmethod
    def _refine_boundaries(ctx, levels: list) -> None:
        """
        Refine each zone: wick extreme on one side, candle BODY on the other.
          Resistance: top = wick high (ceiling), bottom = body top (where selling began)
          Support:    bottom = wick low (floor),  top = body bottom (where buying began)
        Role-aware: a resistance-role level is refined against swing HIGHS even if it
        originated from a swing low (and vice versa), because refinement should match
        how price is behaving against it TODAY.
        """
        atr = ctx.atr
        sh_highs = ctx.highs[ctx.sh_idx]
        sl_lows = ctx.lows[ctx.sl_idx]
        sh_body_tops = np.maximum(ctx.opens[ctx.sh_idx], ctx.closes[ctx.sh_idx])
        sl_body_bottoms = np.minimum(ctx.opens[ctx.sl_idx], ctx.closes[ctx.sl_idx])

        for lvl in levels:
            if lvl.get('is_consol'):
                continue
            if lvl['type'] == 'resistance':
                mask = (sh_highs >= lvl['bottom']) & (sh_highs <= lvl['top'] + 0.01 * atr)
                if mask.any():
                    body_floor = float(sh_body_tops[mask].min())
                    if body_floor < lvl['top']:
                        lvl['bottom'] = body_floor
                        lvl['spread'] = lvl['top'] - body_floor
            else:
                mask = (sl_lows >= lvl['bottom'] - 0.01 * atr) & (sl_lows <= lvl['top'])
                if mask.any():
                    body_ceil = float(sl_body_bottoms[mask].max())
                    if body_ceil > lvl['bottom']:
                        lvl['top'] = body_ceil
                        lvl['spread'] = body_ceil - lvl['bottom']

    # ── Selection + merge ─────────────────────────────────────────────────────

    @staticmethod
    def _select_nearby(ctx, res_levels: list, sup_levels: list) -> list:
        """
        Keep only levels within LEVEL_NEAR_ATR of price (or very well-tested), nearest
        first, capped at LEVEL_MAX_SHOW per side, and serialize them for the frontend.
        """
        price, atr = ctx.price, ctx.atr

        def res_key(x):
            near = (x['price'] - price) / atr
            return (0 if near <= LEVEL_NEAR_BUCKET_ATR else 1, -x['quality'], near)

        def sup_key(x):
            near = (price - x['price']) / atr
            return (0 if near <= LEVEL_NEAR_BUCKET_ATR else 1, -x['quality'], near)

        nearby_res = sorted(
            [r for r in res_levels
             if r.get('freshness') != 'absorbed'
             and ((r['price'] - price) / atr <= LEVEL_NEAR_ATR or r['touches'] >= LEVEL_STRONG_TOUCHES)],
            key=res_key)[:LEVEL_MAX_SHOW]
        nearby_sup = sorted(
            [s for s in sup_levels
             if s.get('freshness') != 'absorbed'
             and ((price - s['price']) / atr <= LEVEL_NEAR_ATR or s['touches'] >= LEVEL_STRONG_TOUCHES)],
            key=sup_key)[:LEVEL_MAX_SHOW]

        zone_thr = ZONE_MIN_SPREAD_ATR * atr
        out: list[dict] = []
        for lvl in nearby_res:
            out.append(LevelEngine._serialize(lvl, 'resistance', zone_thr, price, atr))
        for lvl in nearby_sup:
            out.append(LevelEngine._serialize(lvl, 'support', zone_thr, price, atr))
        return out

    @staticmethod
    def _serialize(lvl: dict, level_type: str, zone_thr: float, price: float, atr: float) -> dict:
        is_zone = lvl['spread'] >= zone_thr
        tag = 'R' if level_type == 'resistance' else 'S'
        flipped = bool(lvl.get('flipped'))
        dist_pct = jnum((lvl['price'] / price - 1) * 100) if price else None
        dist_atr = jnum(abs(lvl['price'] - price) / atr) if atr else None
        flip_note = ('' if not flipped else
                    ' (was support)' if level_type == 'resistance' else ' (was resistance)')
        # Micha labels zone bands with their price range ("160.81 - 162.35")
        label = (f"{lvl['bottom']:.2f} - {lvl['top']:.2f} · {lvl['touches']}×{flip_note}"
                 if is_zone else
                 f"{tag} {lvl['price']:.2f} · {lvl['touches']}×{flip_note}")
        return {
            'type': level_type,
            'price': jnum(lvl['price']),
            'zone_top':    jnum(lvl['top'])    if is_zone else None,
            'zone_bottom': jnum(lvl['bottom']) if is_zone else None,
            'is_zone': is_zone,
            'strength':  lvl['strength'],
            'freshness': lvl.get('freshness', 'fresh'),
            'has_pin':   lvl.get('has_pin', False),
            'flipped':   flipped,
            'dist_pct':  dist_pct,
            'dist_atr':  dist_atr,
            'touches': lvl['touches'], 'quality': lvl['quality'],
            'label': label,
        }

    @staticmethod
    def _merge_pairs(ctx, raw_levels: list) -> list:
        """
        Collapse a resistance+support pair into one midpoint "zone" line when they sit
        within SR_MERGE_ATR of each other and neither is well-tested (or already a zone).
        """
        atr = ctx.atr
        merged: list[dict] = []
        used: set[int] = set()
        for i, a in enumerate(raw_levels):
            if i in used:
                continue
            if a['type'] not in ('resistance', 'support'):
                merged.append(a)
                used.add(i)
                continue
            partner = None
            for j, b in enumerate(raw_levels):
                if j <= i or j in used:
                    continue
                if b['type'] not in ('resistance', 'support') or b['type'] == a['type']:
                    continue
                if abs(a['price'] - b['price']) / atr > SR_MERGE_ATR:
                    continue
                if (max(a['touches'], b['touches']) < SR_KEEP_TOUCHES
                        and not a.get('is_zone') and not b.get('is_zone')):
                    partner = (j, b)
                    break
            if partner:
                j, b = partner
                mid = (a['price'] + b['price']) / 2.0
                tot = a['touches'] + b['touches']
                merged.append({
                    'type': 'zone',
                    'price': jnum(mid),
                    'zone_top': jnum(max(a['price'], b['price'])),
                    'zone_bottom': jnum(min(a['price'], b['price'])),
                    'is_zone': True,
                    'strength':  'strong' if tot >= LEVEL_STRONG_TOUCHES else 'normal',
                    'freshness': a.get('freshness', 'fresh'),
                    'has_pin':   a.get('has_pin', False) or b.get('has_pin', False),
                    'flipped':   a.get('flipped', False) or b.get('flipped', False),
                    'dist_pct':  a.get('dist_pct'),
                    'dist_atr':  a.get('dist_atr'),
                    'touches': tot,
                    'quality': max(a['quality'], b['quality']),
                    'label': f"Zone {mid:.2f}",
                })
                used.add(i)
                used.add(j)
            else:
                merged.append(a)
                used.add(i)
        return merged
