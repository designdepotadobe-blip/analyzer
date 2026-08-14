"""
MichaAnalyzer — the signal layer of the "Micha Stocks" analysis.

This module computes the FACTS about a chart the way Micha reads them: where price
sits against the 150MA, how far it retraced, whether volume is coming in, whether a
buyers' candle printed, how stretched it is from the 20MA, where the target stations
are, and how far through his four-stage "שינוי כיוון" sequence the stock is.

It deliberately does NOT decide anything. The judgement — is there a trade, at what
price, where the stop goes, and what letter it earns — lives in `verdict.py`, which is
built directly from his own posts. Keeping the two apart is what stops the grading
logic from quietly drifting into the indicator code again.

The selective overlay choice (`_chart_focus`) stays here because it is a statement
about the chart, not about the trade: Micha wipes the chart ("אני מוחק את הציורים")
and draws only what fits this particular stock — the 150MA and horizontal S/R always,
everything else only when it is the thing actually happening.
"""

from __future__ import annotations

import math

import numpy as np

from geometry import Geometry
from reasons import Reasons
from verdict import Judgement, Signals
from config import (
    BREAKOUT_FRESH_BARS,
    CAPITULATION_VOL,
    DC_DOJI_BODY,
    DC_LOOKBACK_WEEKS,
    DC_RECENT_WEEKS,
    DC_VOL_SPIKE,
    DC_WEEKLY_BARS,
    EARNINGS_SOON_DAYS,
    FAR_FROM_MA200_PCT,
    MILD_FROM_MA_PCT,
    EXT20_STRETCHED_ATR,
    FAR_FROM_MA_PCT,
    RUN_UP_ATR,
    RUN_UP_DAYS,
    RUN_UP_LOOKBACK,
    GOLDEN_POCKET,
    LONG_BASE_BARS,
    MAX_TARGET_STATIONS,
    MIN_MARKET_CAP,
    MOMENTUM_RUN_DAYS,
    OFF_HIGH_VALUE_PCT,
    PACE_FAST_DAYS,
    PACE_NORMAL_DAYS,
    ROUND_NEAR_ATR,
    STATION_MERGE_ATR,
    VOL_SPIKE_FACTOR,
    jnum,
    time_to_target,
)

DEEP_FIB = 0.40


class MichaAnalyzer:
    def evaluate(self, ctx, res_levels: list, sup_levels: list,
                 setups: list, overlays: dict) -> dict:
        price, atr = ctx.price, ctx.atr
        codes = {s['code'] for s in setups}

        # ── Facts about the chart ──────────────────────────────────────────────
        ath = float(np.nanmax(ctx.fh))
        off_high = (1.0 - price / ath) * 100 if ath > 0 else 0.0
        fib = self._fib(ctx)
        fib_r = fib['retracement'] if fib else 0.0
        golden = bool(fib and GOLDEN_POCKET[0] <= fib_r <= GOLDEN_POCKET[1])
        nearest_res = min((r for r in res_levels if r['price'] > price),
                          key=lambda r: r['price'], default=None)
        nearest_sup = max((s for s in sup_levels if s['price'] < price),
                          key=lambda s: s['price'], default=None)
        vol = self._volume_trend(ctx)
        candle = self._buyers_candle(ctx, nearest_sup)
        ext = self._ext20(ctx)
        trend = self._trend(ctx)
        momentum = self._momentum_days(ctx)
        capitulation = self._capitulation(ctx, off_high)
        base = self._long_base(ctx)
        broke_desc = self._broke_descending(ctx, overlays)
        break_level = self._fresh_break(ctx, sup_levels, overlays, broke_desc)
        lost_level = self._lost_level(ctx, res_levels)
        small_cap = bool(ctx.market_cap and ctx.market_cap < MIN_MARKET_CAP)
        pattern = self._pattern(codes, base)
        dir_change = self._direction_change(ctx, overlays, break_level is not None)
        channel = self._channel_state(ctx, overlays)
        targets, target = self._targets_ladder(ctx, res_levels, sup_levels, ath, base,
                                               overlays)
        # richer readings — the material reasons.py argues from
        vol_detail = self._volume_detail(ctx, break_level)
        duration = self._duration(ctx)
        rel_strength = self._relative_strength(ctx)
        pattern_detail = self._pattern_detail(ctx, codes, base, overlays, channel)
        level_ctx = self._level_context(ctx, nearest_res, nearest_sup)

        sig = Signals(
            trend=trend, off_high=off_high, ath=ath, fib_r=fib_r, golden=golden,
            ext=ext, vol=vol, candle=candle, capitulation=capitulation, base=base,
            momentum=momentum, res_levels=res_levels, sup_levels=sup_levels,
            nearest_res=nearest_res, nearest_sup=nearest_sup, broke_desc=broke_desc,
            break_level=break_level, lost_level=lost_level,
            overlays=overlays, codes=codes,
            dir_change=dir_change, channel=channel, targets=targets, pattern=pattern,
            recent_low=float(np.min(ctx.lows[-5:])),
            vol_detail=vol_detail, duration=duration, rel_strength=rel_strength,
            pattern_detail=pattern_detail, level_context=level_ctx,
        )

        # ── The judgement (verdict.py) ─────────────────────────────────────────
        j = Judgement().evaluate(ctx, sig)
        # ...and the argument behind it, from the same live readings
        reasons = Reasons().build(ctx, sig, j)

        # expected gain is measured from the entry the reader is actually being told
        # to take, not whichever option happens to be listed first
        best = Judgement._best_option(j['options'], j['action'])
        growth = self._growth(ctx, targets, best)
        focus = self._chart_focus(ctx, j['state'], codes, fib, off_high, ext, overlays)
        key_levels = self._key_levels(ctx, j, target)
        notes = self._notes(ext, golden, base, capitulation, momentum, small_cap,
                            ctx, price, dir_change, channel, overlays)
        scenarios = self._scenarios(ctx, res_levels, sup_levels, targets, ath)

        return {
            # what to do
            'relevant': j['state'] not in ('nothing_yet', 'avoid', 'broken'),
            'state': j['state'],
            'state_label': j['state_label'], 'state_label_he': j['state_label_he'],
            'action': j['action'],
            'action_label': j['action_label'], 'action_label_he': j['action_label_he'],
            'report': j['report'],
            # the full argument, grouped and quantified — all computed from today's
            # data, nothing carried over from a previous run
            'reasons': reasons,
            'options': j['options'],
            'trigger': j['trigger'],
            # not a trade today, but close to becoming one — deliberately separate
            # from the grade (see verdict._alert)
            'alert': j['alert'],
            'hold_level': j['hold_level'],
            # the grade
            'grade': j['grade'],
            'grade_score': j['grade_score'],
            'grade_meaning': j['grade_meaning'], 'grade_meaning_he': j['grade_meaning_he'],
            # why THIS stock got THIS letter, in two sentences (verdict._grade_sentence).
            # NB: this dict is rebuilt field by field, so a new verdict.py key that is
            # not added here is silently dropped from the API — that is how
            # `grade_if_break` went missing once while being computed correctly.
            'grade_why': j['grade_why'], 'grade_why_he': j['grade_why_he'],
            'grade_breakdown': j['grade_breakdown'],
            # what the letter becomes if the named price is cleared — the difference
            # between "D, move on" and "D today, B the moment it breaks"
            'grade_if_break': j.get('grade_if_break'),
            # the numbers behind it
            'targets': targets,
            'target': target,
            'growth': growth,
            'scenarios': scenarios,
            'level_context': level_ctx,
            'direction_change': dir_change,
            'channel': channel,
            'notes': notes,
            'chart_focus': focus,
            # the 1-3 horizontals that ARE the decision (trigger / entry / stop /
            # target) — the chart draws these, not the whole level map. See
            # `_key_levels` for the measurement behind that.
            'key_levels': key_levels,
            # the ATR / 150MA / earnings status card his own charts carry
            'badges': self._badges(ctx),
            # raw readings, for the detail rows
            'trend': trend,
            'off_high_pct': jnum(off_high),
            'fib_retracement': jnum(fib_r * 100) if fib else None,
            'golden_pocket': golden,
            'ext20_pct': jnum(ext['pct']),
            'ext20_atr': jnum(ext['atr']),
            'stretched': ext['stretched'],
            # the graded reading behind that boolean — 'none' | 'mild' | 'stretched'
            # | 'severe' — so the client can say WHICH of his three he would use
            'extension': ext.get('level'),
            'extension_far_150': ext.get('far_150'),
            'd150_pct': jnum(ext.get('d150_pct')),
            'd200_pct': jnum(ext.get('d200_pct')),
            'run_days': ext.get('run_days'),
            'run_pct': jnum(ext.get('run_pct')),
            'ran_hot': ext.get('ran_hot'),
            'momentum_days': momentum,
            'volume_trend': vol['trend'],
            'volume_note': vol['note'], 'volume_note_he': vol['note_he'],
            'market_cap': jnum(ctx.market_cap),
            'small_cap': small_cap,
            'earnings_days': ctx.earnings_days,
        }

    # ── The header card he puts on every 2026 chart ────────────────────────────

    @staticmethod
    def _badges(ctx):
        """
        The three-line status block his own charts carry above the price action:

            ATR (14): 9.51 (3.06%) 🟡
            Above 150 MA 🟢
            Earnings: 85 days remaining

        Every input already existed (`vol_tier` is literally commented in context.py
        as "Micha's green/yellow/red watermark"); this just states them as one ordered,
        pre-coloured list so the client renders instead of re-deriving thresholds.
        Kept server-side because the cut-offs are his, not presentation.
        """
        out = []

        tier = ctx.vol_tier or 'medium'
        tone = {'low': 'good', 'medium': 'warn', 'high': 'bad'}.get(tier, 'warn')
        pct = f' ({ctx.atr_pct:.1f}%)' if ctx.atr_pct is not None else ''
        out.append({
            'key': 'volatility', 'tone': tone,
            'label': f'ATR{pct}',
            'label_he': f'תנודתיות{pct}',
            # his own framing of a red watermark — a size/suitability warning, not a
            # reason to skip: "לא לבעלי לב חלש", "ממש לא לחדשים בשוק"
            'note': {'low': 'calm', 'medium': 'normal', 'high': 'very volatile'}[tier],
            'note_he': {'low': 'רגועה', 'medium': 'רגילה',
                        'high': 'תנודתית מאוד — לא למתחילים'}[tier],
        })

        if ctx.sma150:
            d = (ctx.price / ctx.sma150 - 1) * 100
            above = bool(ctx.above_150)
            out.append({
                'key': 'ma150', 'tone': 'good' if above else 'bad',
                'label': f"{'Above' if above else 'Below'} 150 MA ({d:+.1f}%)",
                'label_he': f"{'מעל ממוצע 150' if above else 'מתחת לממוצע 150'} ({d:+.1f}%)",
                'note': '', 'note_he': '',
            })

        d = ctx.earnings_days
        if d is not None:
            # "מדווחת שבוע הבא. אז זהירות!!!!!" — a report this close is a real flag on
            # any setup; beyond it, context rather than warning. Deliberately the SAME
            # constant the action logic defers entries on, so the badge can never say
            # "fine" while the recommendation is deferring for exactly this reason.
            soon = d <= EARNINGS_SOON_DAYS
            out.append({
                'key': 'earnings', 'tone': 'bad' if soon else 'neutral',
                'label': f'Earnings in {int(d)}d',
                'label_he': f'דוח בעוד {int(d)} ימים',
                'note': 'report is close — size accordingly' if soon else '',
                'note_he': 'הדוח קרוב — להיזהר עם הגודל' if soon else '',
            })
        return out

    # ── The lines that ARE the thesis ──────────────────────────────────────────

    def _key_levels(self, ctx, j, target):
        """
        The 1-3 horizontals worth drawing, and nothing else.

        Measured against 2,500 of his own posts: a chart of his carries ONE or TWO
        hand-drawn horizontals — the line the stock has to cross, and the line it has
        to hold — each price-tagged. Never a "level map". Our `overlays['levels']`
        emits 5-6 (LEVEL_MAX_SHOW per side, both sides), which is the single biggest
        source of the "too complex" reading: five equally-weighted lines force the
        reader to work out which one is the decision, when the analyzer already knows.

        Nothing new is computed here. The trigger, the stop and the target are the
        SAME numbers the verdict already decided and the text already quotes — this
        just marks which of them are lines, so the chart and the sentence can never
        disagree. `role` is what the frontend styles on; `what_he` is his own
        description of the level ("קו הפריצה", "תמיכה שנבדקה 6 פעמים").
        """
        out: list[dict] = []
        seen: list[float] = []
        price = float(ctx.price)

        def add(value, role, label, label_he, what='', what_he=''):
            if value is None:
                return
            try:
                p = float(value)
            except (TypeError, ValueError):
                return
            if p <= 0 or not np.isfinite(p):
                return
            # Two roles landing on the same price (a trigger that is also the target
            # of a tiny move) would draw two lines on top of each other — keep the
            # first, which is the more decision-relevant one by insertion order.
            if any(abs(p - q) <= max(1e-6, ctx.atr * 0.05) for q in seen):
                return
            seen.append(p)
            out.append({
                'price': jnum(p), 'role': role,
                'label': label, 'label_he': label_he,
                'what': what or '', 'what_he': what_he or '',
                'dist_pct': jnum((p / price - 1) * 100) if price else None,
            })

        trig = j.get('trigger') or {}
        add(trig.get('price'), 'trigger', 'Trigger', 'קו הפריצה',
            trig.get('what'), trig.get('what_he'))

        best = Judgement._best_option(j.get('options') or [], j.get('action'))
        if best:
            # The entry earns its own line only when it is somewhere the price is NOT.
            # An "enter now" entry equals today's close, and drawing a line on top of
            # the price candle says nothing the price axis doesn't already say — on
            # AAPL that produced a 4th line at -0.0% from spot. A pullback entry sits
            # somewhere real, and he does draw that one.
            entry = best.get('entry')
            if entry is not None and abs(float(entry) - price) > ctx.atr * 0.25:
                add(entry, 'entry', 'Entry', 'כניסה')
            add(best.get('stop'), 'stop', 'Stop', 'סטופ',
                best.get('stop_what'), best.get('stop_what_he'))

        # "the line it has to hold" when there is no option to carry a stop — his
        # "צריכה לשמור מעל X" post shape.
        hold = j.get('hold_level') or {}
        if not any(o['role'] == 'stop' for o in out):
            add(hold.get('price'), 'stop', 'Must hold', 'חייבת לשמור מעל',
                hold.get('what'), hold.get('what_he'))

        # Room above, and only if there IS room. The ladder's first station can sit
        # below the trigger (AAPL: target 308.26 under a 309.29 trigger) or a single
        # percent from spot — drawing that as "יעד" tells the reader to expect a move
        # that is inside the noise, and contradicts the trigger line right above it.
        # His targets are always real room: "פריצה של 141 ... בדרך ל 190-200".
        tp = target.get('price') if isinstance(target, dict) else target
        if tp is not None:
            floor = max([price] + [o['price'] for o in out if o['role'] == 'trigger'])
            if float(tp) > floor + ctx.atr * 0.5:
                add(tp, 'target', 'Target', 'יעד')
        return out

    # ── Chart focus: only the overlays that fit THIS stock ─────────────────────

    def _chart_focus(self, ctx, state, codes, fib, off_high, ext, overlays):
        """
        Draw everything that is REAL on this chart, and nothing that isn't.

        The distinction matters and cost a round trip to get right. An earlier pass
        gated almost everything behind narrow states, which read as "the analyzer
        found nothing" on charts that genuinely had a trend line under them. The
        measurement says the opposite: across 2,323 of his posts the support /
        trend-line vocabulary is his SECOND strongest signal (+14.0 lift between
        praise and warnings, behind only breakout at +18.5), he marks gaps
        explicitly ("גאפ מעל הראש", "סגירת הגאפ"), and he uses channels when the
        stock is in one ("אפל נעה בתעלה ללא הפרעה"). Those are drawn whenever they
        exist.

        What stays rare stays rare because HE is rare with it, not to keep the chart
        empty: Fibonacci appears in 1.3% of his posts and triangles in 0.3%, so both
        still have to be the actual thesis (`fibonacci` / `triangle` in `codes`) and
        not merely detectable. Breakout arrow markers stay off entirely — he never
        annotates past breakouts, he draws the line they broke.
        """
        focus = {
            'sma150': True, 'sma200': False, 'sma20': False,
            # He does draw horizontal S/R — "תמיכה/סטופ ב 27.8. התנגדות ב 31.47".
            # The level engine is already capped at LEVEL_MAX_SHOW=2 per side, and
            # `key_levels` separately promotes the trigger/stop to their own bold,
            # labelled lines, so the map reads as context underneath the decision
            # rather than competing with it.
            'levels': True, 'fib': False, 'trendlines': False,
            'channels': False, 'triangles': False,
        }
        # Every one of his screenshots shows ONE moving average — the 150. The 200
        # appears only when it is itself the decision line.
        if ctx.sma200 and ctx.ma_context in ('transition', 'weak', 'bear'):
            focus['sma200'] = True
        if ext['stretched']:
            focus['sma20'] = True        # the "20 method" — only to show the stretch

        has_tl = bool(overlays.get('trendlines'))
        has_ch = bool(overlays.get('channels'))
        has_tri = bool(overlays.get('triangles'))
        fib_relevant = bool(fib and off_high >= 10 and 0.30 <= fib['retracement'] <= 0.95
                            and 'fibonacci' in codes)

        # A real diagonal is drawn whenever one exists — it is "קו המגמה", the line
        # he says the stock is sitting on. Not state-gated: a trend line under a
        # stock in `needs_buyers` is exactly as real as one under a breakout.
        focus['trendlines'] = has_tl
        # A channel is a stronger statement than a lone diagonal, so when the setup
        # engine actually recognised one it supersedes the single line.
        if has_ch and ('rising_channel' in codes or 'descending_channel' in codes):
            focus['channels'] = True
        # Both of these have to BE the thesis, per the frequencies above.
        if has_tri and 'triangle' in codes:
            focus['triangles'] = True
        if fib_relevant:
            focus['fib'] = True
        return focus

    # ── "שינוי כיוון" — the four stages he dictates ────────────────────────────

    @staticmethod
    def _weekly(ctx, weeks):
        """
        Weekly candles. He reads the direction-change sequence on the weekly
        explicitly — "שבועי, אני מדבר איתכם כרגע על שבועי" — because a single daily
        bar is noise at this scale. Also his general fallback when the daily is messy:
        "ביומי בעייתי לבחון את הגרף לכן העברתי לשבועי".
        """
        n = weeks * DC_WEEKLY_BARS
        o, h, l, c, v = ctx.opens[-n:], ctx.highs[-n:], ctx.lows[-n:], ctx.closes[-n:], ctx.vols[-n:]
        M = len(c)
        if M < DC_WEEKLY_BARS * 3:
            return None
        edges = list(range(M, 0, -DC_WEEKLY_BARS))[::-1]
        starts = [max(0, e - DC_WEEKLY_BARS) for e in edges]
        wo = np.array([o[s] for s in starts])
        wh = np.array([float(np.max(h[s:e])) for s, e in zip(starts, edges)])
        wl = np.array([float(np.min(l[s:e])) for s, e in zip(starts, edges)])
        wc = np.array([c[e - 1] for e in edges])
        wv = np.array([float(np.sum(v[s:e])) for s, e in zip(starts, edges)])
        return wo, wh, wl, wc, wv

    @staticmethod
    def _was_weak(ctx, older_closes):
        """
        "שינוי כיוון" only means something for a name that was actually struggling
        before the turn (בריש טו בוליש). An already-healthy stock printing one green
        week is continuation, not a direction change.
        """
        if len(older_closes) < 3:
            return ctx.ma_context in ('weak', 'bear')
        if ctx.sma150 and float(np.mean(older_closes < ctx.sma150)) >= 0.4:
            return True
        if older_closes[-1] < older_closes[0] * 0.95:
            return True
        return ctx.ma_context in ('weak', 'bear')

    def _direction_change(self, ctx, overlays, fresh_break):
        """
        His dictated four stages, in his order:
          1. ווליום ספייק  — "a spike is not a rise of 0.1"
          2. נר שינוי כיוון — a doji (RED counts), a harami, or a hammer week
          3. שפלים עולים   — "I can connect them with a line — that gives more confidence"
          4. פריצה          — the breakout, "the last stage, no less important"
        Stages 1-3 make it interesting; only stage 4 makes him buy.
        """
        wk = self._weekly(ctx, DC_LOOKBACK_WEEKS)
        if wk is None:
            return None
        wo, wh, wl, wc, wv = wk
        n = len(wc)
        recent = min(DC_RECENT_WEEKS, n)
        applicable = self._was_weak(ctx, wc[:-recent] if n > recent else wc[:1])

        avg_v = float(np.mean(wv[:-recent])) if n > recent else float(np.mean(wv))
        spike_ratio = float(np.max(wv[-recent:]) / avg_v) if avg_v > 0 else 0.0
        vol_spike = spike_ratio >= DC_VOL_SPIKE

        candle_found, candle_kind = False, None
        for i in range(n - recent, n):
            rng = wh[i] - wl[i]
            if rng <= 0:
                continue
            body = abs(wc[i] - wo[i])
            if body <= DC_DOJI_BODY * rng:
                candle_found, candle_kind = True, 'doji'
                break
            if i > 0:
                p_hi, p_lo = max(wo[i - 1], wc[i - 1]), min(wo[i - 1], wc[i - 1])
                if p_hi > p_lo and max(wo[i], wc[i]) <= p_hi and min(wo[i], wc[i]) >= p_lo:
                    candle_found, candle_kind = True, 'harami'
                    break
            lower_wick = min(wo[i], wc[i]) - wl[i]
            if lower_wick >= 2 * body and wc[i] >= wl[i] + rng * 0.5:
                candle_found, candle_kind = True, 'hammer'
                break

        rising_lows, rl_touches, rl_broke = False, 0, False
        for t in overlays.get('trendlines', []):
            if t.get('kind') == 'rising_lows':
                rl_touches = int(t.get('touches') or 0)
                rl_broke = bool(t.get('broke'))
                rising_lows = not rl_broke
                break
        if not rising_lows and not rl_touches:
            k = min(4, n)
            lows_seq = wl[-k:]
            rising_lows = bool(k >= 3 and lows_seq[-1] > lows_seq[0]
                               and float(np.min(lows_seq[1:])) >= float(lows_seq[0]))

        stages = [
            ('vol_spike', vol_spike, 'Volume spike', 'ספייק בווליום'),
            ('reversal_candle', candle_found, 'Direction-change candle', 'נר שינוי כיוון'),
            ('rising_lows', rising_lows, 'Rising lows', 'שפלים עולים'),
            ('breakout', bool(fresh_break), 'Breakout = continuity', 'פריצה = המשכיות'),
        ]
        done = sum(1 for _, ok, _, _ in stages if ok)
        confirmed = applicable and bool(fresh_break) and done >= 3
        turning = applicable and done >= 3 and not fresh_break

        if not applicable:
            en, he = ('Already healthy — continuation, not a direction change',
                      'כבר במגמה בריאה — המשכיות, לא שינוי כיוון')
        elif confirmed:
            en, he = 'Direction change confirmed by the breakout', 'שינוי כיוון עם אישור פריצה'
        elif turning:
            en, he = ('Changing direction — waiting on the breakout',
                      'משנה כיוון — מחכים לפריצה')
        elif done == 2:
            en, he = 'Early signs of a direction change', 'סימנים מוקדמים לשינוי כיוון'
        else:
            en, he = 'No direction change yet', 'אין שינוי כיוון עדיין'

        return {
            'applicable': applicable, 'stages_done': done, 'stages_total': len(stages),
            'confirmed': confirmed, 'turning': turning,
            'vol_spike_ratio': jnum(spike_ratio), 'candle_kind': candle_kind,
            'rising_lows_touches': rl_touches, 'rising_lows_broke': rl_broke,
            'label': en, 'label_he': he,
            'stages': [{'key': k, 'done': bool(ok), 'label': e, 'label_he': h}
                       for k, ok, e, h in stages],
        }

    @staticmethod
    def _channel_state(ctx, overlays):
        """
        Where price sits inside a channel is the trade: at the lower rail of a rising
        channel it is an entry ("תיקון לחלק התחתון של התעלה — מה לבקש יותר"),
        mid-channel is explicitly nothing ("אין פה משהו אטרקטיבי רק תנועה בתעלה"),
        and pressing the upper rail of a FALLING channel is the breakout trigger.
        """
        chs = overlays.get('channels') or []
        if not chs:
            return None
        ch = chs[0]
        pos, kind = ch.get('pos_pct'), ch.get('kind')
        if pos is None:
            return None
        if kind == 'rising':
            zone = 'bottom' if pos <= 30 else 'top' if pos >= 75 else 'middle'
        else:
            zone = 'upper_rail' if pos >= 70 else 'lower' if pos <= 30 else 'middle'
        return {'kind': kind, 'pos_pct': jnum(pos), 'zone': zone,
                'lower': ch.get('lower_now'), 'upper': ch.get('upper_now')}

    # ── Expected gain, and how fast it is realistic ────────────────────────────

    def _growth(self, ctx, targets, option):
        """
        ATR is the right UNIT for the distance — his own framing, "בגלל שהיא מניה
        תנודתית — כל יומיים כאלה זה יכול להיות 16%" — and it is why the same +20% is a
        different trade on a 8%-ATR name than on a 2%-ATR one. What it is NOT is a
        unit of time: ATR is a daily RANGE, and price does not net one full range in
        one direction every day. Measured (see config.time_to_target), a 4-ATR move
        takes ~28 trading days, not 4, and only lands ~68% of the time.

        Headline is the THESIS — the top of the ladder, the same target `risk_reward`
        and the grade's time term are measured to, and the number he actually quotes
        ("יש פה פוטנציאל של 25%"). The first station leads nowhere as a headline: it
        is the next level up, ~1 ATR out by construction, so on ARM it reads "+4% in
        1 day", which is noise on an 11%-ATR name rather than a reason to take a
        trade. What makes the thesis honest is not demoting it but pricing it — every
        leg carries its own probability, because "+30%" at a 17% hit rate is not the
        same claim as "+8%" at 75% and must not print alike.
        """
        price, ap = ctx.price, ctx.atr_pct
        if not price or not ap or ap <= 0 or not targets:
            return None
        base = (option or {}).get('entry') or price
        legs = []
        for t in targets:
            tp = t.get('price')
            if tp and tp > base:
                g = (tp / base - 1) * 100
                k = g / ap
                days, hit = time_to_target(k, ap)
                legs.append({
                    'gain_pct': jnum(g), 'gain_atr': jnum(k),
                    'days': jnum(days), 'hit_rate': jnum(hit),
                    # the number a swing trader actually compares across candidates:
                    # how much percent this position earns per day it is tied up
                    'pct_per_day': jnum(g / days) if days else None,
                })
        if not legs:
            return None
        first = legs[0]
        best = max(legs, key=lambda x: x['gain_pct'])
        d = best['days']
        pace = ('fast' if d <= PACE_FAST_DAYS else
                'normal' if d <= PACE_NORMAL_DAYS else 'slow')
        pace_en, pace_he = {
            'fast':   ('a quick move at this volatility', 'מהלך מהיר בתנודתיות הזו'),
            'normal': ('a normal-paced move',             'מהלך בקצב רגיל'),
            'slow':   ('a slow grind at this volatility', 'מהלך איטי בתנודתיות הזו'),
        }[pace]
        return {
            # headline = the thesis, priced with its own odds
            'gain_pct': best['gain_pct'], 'gain_atr': best['gain_atr'],
            'days': best['days'], 'hit_rate': best['hit_rate'],
            'pct_per_day': best['pct_per_day'],
            'pace': pace,
            # the near station on the way, so the first obstacle is still visible
            'first_gain_pct': first['gain_pct'], 'first_days': first['days'],
            'first_hit_rate': first['hit_rate'],
            'legs': legs,
            'label': (f"+{best['gain_pct']:.0f}% ≈ {d:.0f} trading days "
                      f"({best['hit_rate']*100:.0f}% of the time) — {pace_en}"),
            'label_he': (f"+{best['gain_pct']:.0f}% ≈ {d:.0f} ימי מסחר "
                         f"({best['hit_rate']*100:.0f}% מהפעמים) — {pace_he}"),
        }

    # ── Target stations ────────────────────────────────────────────────────────

    @staticmethod
    def _gap_stations(overlays, floor_price):
        """
        An unfilled gap overhead gives two named stations in order: "פתח הגאפ" then
        "סגירת הגאפ" — ANET "היעד הראשוני הוא פתח הגאפ. אחרי זה סגירת הגאפ".
        """
        out = []
        for g in (overlays or {}).get('gaps') or []:
            if g.get('dir') != 'down':
                continue
            for edge, en, he in ((g.get('near'), 'gap open', 'פתח הגאפ'),
                                 (g.get('far'), 'gap fill', 'סגירת הגאפ')):
                if edge and edge > floor_price:
                    out.append((float(edge), en, he))
        return out

    @staticmethod
    def _fib_stations(overlays, floor_price):
        """The Fib prices he trades by name — NOW "מנסה לעצור על ה-618 על ה-103.38"."""
        fib = (overlays or {}).get('fib')
        out = []
        for lv in ((fib or {}).get('levels') or []):
            p, r = lv.get('price'), lv.get('ratio')
            if p and p > floor_price:
                out.append((float(p), f'Fib {r*100:.1f}%', f"פיבונאצ'י {r*100:.1f}%"))
        return out

    def _targets_ladder(self, ctx, res_levels, sup_levels, ath, base, overlays=None):
        """
        A LADDER of stations, not one number (WGMI: 58.89 → 67.89 "מחיר פריצה" → 74.29
        "מחיר פריצה שיא"; NFLX "3 יעדים על הגרף"). Station 1 is the nearest real
        resistance overhead; then the next; then the prior high. A measured move (cup
        depth projected off the breakout — IREN "היעד לקאפ הוא $97, מחיר פריצה $63")
        slots in wherever it lands.
        """
        price = ctx.price
        floor_price = price + max(0.3 * ctx.atr, price * 0.005)

        cands: list[tuple[float, str, str]] = []
        for r in res_levels:
            if r['price'] > floor_price:
                flipped = r.get('flipped')
                cands.append((float(r['price']),
                              'former support / breakout price' if flipped else 'next resistance',
                              'תמיכה לשעבר / מחיר פריצה' if flipped else 'התנגדות הבאה'))
        if ath > floor_price * 1.005:
            cands.append((float(ath), 'prior high (ATH)', 'השיא הקודם'))
        if overlays:
            cands.extend(self._gap_stations(overlays, floor_price))
            cands.extend(self._fib_stations(overlays, floor_price))

        measured = measured_detail = measured_detail_he = None
        b_bottom = b_top = None
        if base and base['top'] > base['bottom']:
            b_bottom, b_top = base['bottom'], base['top']
        else:
            flipped = [s for s in sup_levels
                       if s.get('flipped') and 0 < (price - s['price']) <= 3 * ctx.atr]
            if flipped:
                lvl = max(flipped, key=lambda s: s['price'])['price']
                yr_lows, yr_closes = ctx.lows[-252:], ctx.closes[-252:]
                under = yr_lows[yr_closes < lvl]
                if under.size:
                    cup_low = float(under.min())
                    if lvl - cup_low >= 2 * ctx.atr:
                        b_bottom, b_top = cup_low, lvl
        if b_bottom is not None:
            depth = b_top - b_bottom
            mv = b_top + depth
            if mv > floor_price * 1.005 and depth >= 2 * ctx.atr:
                measured = mv
                measured_detail = (f"base ${b_bottom:.2f} → top ${b_top:.2f} "
                                   f"(${depth:.2f} deep) projected → ${mv:.2f}")
                measured_detail_he = (f"בסיס ${b_bottom:.2f} ← שיא ${b_top:.2f} "
                                      f"(עומק ${depth:.2f}) מוקרן ← ${mv:.2f}")
                cands.append((mv, 'measured move (base depth)', 'מהלך מדוד (עומק הבסיס)'))

        cands.sort(key=lambda c: c[0])
        stations: list[tuple[float, str, str]] = []
        for p, lbl, lbl_he in cands:
            if stations and (p - stations[-1][0]) <= STATION_MERGE_ATR * ctx.atr:
                continue
            stations.append((p, lbl, lbl_he))
        stations = stations[:MAX_TARGET_STATIONS]

        targets = [{'price': jnum(p), 'pct': jnum((p / price - 1) * 100) if price else None,
                    'label': lbl, 'label_he': lbl_he} for p, lbl, lbl_he in stations]

        if targets:
            primary = dict(targets[0])
            primary.update({'note': targets[0]['label'], 'note_he': targets[0]['label_he'],
                            'measured_move': jnum(measured),
                            'measured_detail': measured_detail,
                            'measured_detail_he': measured_detail_he})
        else:
            primary = {'price': jnum(measured),
                       'pct': jnum((measured / price - 1) * 100) if measured and price else None,
                       'note': 'all-time high — no overhead resistance',
                       'note_he': 'שיא כל הזמנים — אין התנגדות מעל',
                       'measured_move': jnum(measured),
                       'measured_detail': measured_detail,
                       'measured_detail_he': measured_detail_he}
        return targets, primary

    # ── If-then scenarios ──────────────────────────────────────────────────────

    def _scenarios(self, ctx, res_levels, sup_levels, targets, ath):
        """
        "מה שיפה בניתוח טכני — אנחנו לא קובעים מראש... פועלים אם-אז". Two branches,
        priced off the real level map.
        """
        price, atr = ctx.price, ctx.atr
        out = []
        nearest_res = min((r for r in res_levels if r['price'] > price * 1.002),
                          key=lambda r: r['price'], default=None)
        sups = sorted((s for s in sup_levels if s['price'] < price * 0.998),
                      key=lambda s: -s['price'])
        nearest_sup = sups[0] if sups else None
        next_sup = next((s for s in sups[1:]
                         if nearest_sup and nearest_sup['price'] - s['price'] > atr), None)

        if nearest_res:
            rp = nearest_res['price']
            after = next((t for t in targets if t['price'] and t['price'] > rp * 1.002), None)
            if after:
                out.append(self._sc('bull',
                    f"Breaks {rp:.2f} with volume → opens {after['price']:.2f} ({after['pct']:+.0f}%)",
                    f"פורצת {rp:.2f} עם ווליום ← נפתח המהלך ל-{after['price']:.2f} ({after['pct']:+.0f}%)"))
            else:
                up = (ath / price - 1) * 100 if price else 0
                out.append(self._sc('bull',
                    f"Breaks {rp:.2f} with volume → clear road to the prior high {ath:.2f} ({up:+.0f}%)",
                    f"פורצת {rp:.2f} עם ווליום ← דרך פנויה לשיא הקודם {ath:.2f} ({up:+.0f}%)"))
        elif price >= ath * 0.995:
            out.append(self._sc('bull',
                'At all-time highs — no overhead resistance; every new high is a station',
                'בשיא כל הזמנים — אין התנגדות מעל; כל שיא חדש הוא תחנה'))

        if nearest_sup:
            sp = nearest_sup['price']
            if next_sup:
                dn = (next_sup['price'] / price - 1) * 100 if price else 0
                out.append(self._sc('bear',
                    f"Loses {sp:.2f} → next support {next_sup['price']:.2f} ({dn:.0f}%)",
                    f"שוברת את {sp:.2f} ← התמיכה הבאה {next_sup['price']:.2f} ({dn:.0f}%)"))
            elif ctx.sma150 and ctx.sma150 < sp:
                out.append(self._sc('bear',
                    f"Loses {sp:.2f} → the 150MA at {ctx.sma150:.2f} is the test",
                    f"שוברת את {sp:.2f} ← ממוצע 150 ב-{ctx.sma150:.2f} הוא המבחן"))
            else:
                out.append(self._sc('bear',
                    f"Loses {sp:.2f} → setup invalid, step aside",
                    f"שוברת את {sp:.2f} ← הסט אפ מתבטל, זזים הצידה"))
        if ctx.above_150 and ctx.sma150 and (not nearest_sup or ctx.sma150 < nearest_sup['price']):
            out.append(self._sc('bear',
                f"Below the 150MA ({ctx.sma150:.2f}) the whole thesis is off",
                f"מתחת לממוצע 150 ({ctx.sma150:.2f}) — כל התזה יורדת מהשולחן"))
        return out[:3]

    @staticmethod
    def _sc(kind, en, he):
        return {'kind': kind, 'en': en, 'he': he}

    # ── Current status: the S/R map, explained ─────────────────────────────────

    def _level_context(self, ctx, nearest_res, nearest_sup):
        """Where the stock actually stands between its floor and its ceiling."""
        price, atr = ctx.price, ctx.atr

        def describe(lvl, kind):
            if not lvl:
                return None
            flipped = bool(lvl.get('flipped'))
            role_en, role_he = '', ''
            if flipped:
                role_en, role_he = (('former support', 'תמיכה לשעבר') if kind == 'resistance'
                                    else ('former resistance', 'התנגדות לשעבר'))
            return {
                'price': jnum(lvl['price']),
                'dist_pct': jnum((lvl['price'] / price - 1) * 100) if price else None,
                'dist_atr': jnum(abs(lvl['price'] - price) / atr) if atr else None,
                'touches': lvl['touches'], 'freshness': lvl.get('freshness', 'fresh'),
                'flipped': flipped, 'role_note': role_en, 'role_note_he': role_he,
            }

        res_d, sup_d = describe(nearest_res, 'resistance'), describe(nearest_sup, 'support')
        position_pct = None
        if nearest_res and nearest_sup and nearest_res['price'] > nearest_sup['price']:
            span = nearest_res['price'] - nearest_sup['price']
            if span > 0:
                position_pct = jnum((price - nearest_sup['price']) / span * 100)

        parts_en, parts_he = [], []
        if sup_d:
            flip = f" ({sup_d['role_note']})" if sup_d['flipped'] else ''
            flip_he = f" ({sup_d['role_note_he']})" if sup_d['flipped'] else ''
            parts_en.append(f"{abs(sup_d['dist_pct']):.1f}% above support at {sup_d['price']:.2f} "
                            f"(tested {sup_d['touches']}x{flip})")
            parts_he.append(f"{abs(sup_d['dist_pct']):.1f}% מעל תמיכה ב-{sup_d['price']:.2f} "
                            f"(נבדקה {sup_d['touches']} פעמים{flip_he})")
        if res_d:
            flip = f" ({res_d['role_note']})" if res_d['flipped'] else ''
            flip_he = f" ({res_d['role_note_he']})" if res_d['flipped'] else ''
            parts_en.append(f"{abs(res_d['dist_pct']):.1f}% below resistance at {res_d['price']:.2f} "
                            f"(tested {res_d['touches']}x{flip})")
            parts_he.append(f"{abs(res_d['dist_pct']):.1f}% מתחת להתנגדות ב-{res_d['price']:.2f} "
                            f"(נבדקה {res_d['touches']} פעמים{flip_he})")
        if position_pct is not None:
            parts_en.append(f"sitting {position_pct:.0f}% of the way from support to resistance")
            parts_he.append(f"נמצאת ב-{position_pct:.0f}% מהדרך מהתמיכה להתנגדות")

        return {
            'resistance': res_d, 'support': sup_d, 'position_pct': position_pct,
            'narrative': ("Trading " + ", ".join(parts_en) + "." if parts_en
                          else "No nearby support/resistance levels in range."),
            'narrative_he': ("נסחרת " + ", ".join(parts_he) + "." if parts_he
                             else "אין רמות תמיכה/התנגדות קרובות בטווח."),
        }

    # ── Observations ───────────────────────────────────────────────────────────

    def _notes(self, ext, golden, base, capitulation, momentum, small_cap, ctx, price,
               dir_change=None, channel=None, overlays=None):
        notes = []
        if dir_change and dir_change['applicable'] and dir_change['stages_done'] >= 2:
            d, t = dir_change['stages_done'], dir_change['stages_total']
            missing = [s['label_he'] for s in dir_change['stages'] if not s['done']]
            missing_en = [s['label'] for s in dir_change['stages'] if not s['done']]
            if dir_change['confirmed']:
                notes.append(self._n(
                    f'Direction change complete ({d}/{t}) — volume, candle, rising lows and the breakout',
                    f'שינוי כיוון מלא ({d}/{t}) — ווליום, נר, שפלים עולים ופריצה'))
            else:
                notes.append(self._n(
                    f'Direction change {d}/{t} — still missing: {", ".join(missing_en)}',
                    f'שינוי כיוון {d}/{t} — עוד חסר: {", ".join(missing)}'))
        if dir_change and dir_change['rising_lows_broke']:
            notes.append(self._n(
                'The rising-lows line has been lost — the structure that held it is gone',
                'קו השפלים העולים נשבר — המבנה שהחזיק אותה נגמר'))
        if channel:
            if channel['kind'] == 'rising' and channel['zone'] == 'bottom':
                notes.append(self._n(
                    f"At the bottom of a rising channel ({channel['lower']:.2f}) — the pullback he waits for",
                    f"בתחתית תעלה עולה ({channel['lower']:.2f}) — התיקון שמחכים לו"))
            elif channel['kind'] == 'rising' and channel['zone'] == 'top':
                notes.append(self._n('At the top of the channel — not where you open a position',
                                     'בחלק העליון של התעלה — לא המקום לפתוח פוזיציה'))
            elif channel['zone'] == 'middle':
                notes.append(self._n('Mid-channel — nothing attractive, just movement inside the channel',
                                     'באמצע התעלה — אין פה משהו אטרקטיבי, רק תנועה בתעלה'))
            elif channel['kind'] == 'descending' and channel['zone'] == 'upper_rail':
                notes.append(self._n(
                    f"Pressing the upper rail of a falling channel ({channel['upper']:.2f}) — a break there is the trigger",
                    f"לוחצת על הרף העליון של תעלה יורדת ({channel['upper']:.2f}) — פריצה שם היא הטריגר"))
        if ext['stretched']:
            # "מתוחה" is a caution, not a disqualification: "מתוחה אבל ... כל עוד שומרת
            # מעל 19 היא בסדר" (CRML). And once stretched, expect the pace to slow:
            # "מעתה העליות אמורות להיות איטיות יותר / התכנסות" (GOOGL).
            notes.append(self._n(
                f"{ext['atr']:.1f} ATR above the 20MA — stretched; don't chase, gains slow from here",
                f"{ext['atr']:.1f} ATR מעל ממוצע 20 — מתוחה; לא לרדוף, מכאן העליות איטיות יותר"))
        if golden:
            notes.append(self._n("In the 61.8% golden pocket — his premium value zone",
                                 "בגולדן פוקט (61.8%) — אזור הערך המועדף"))
        if base:
            notes.append(self._n(f"{base['length']}-bar base — pressure relief; a breakout can run",
                                 f"בסיס של {base['length']} נרות — שחרור לחץ; פריצה יכולה לרוץ"))
        if capitulation:
            notes.append(self._n("High-volume wash-out then stabilizing — possible bottom",
                                 "קפיטולציה בווליום גבוה ואז התייצבות — תחתית אפשרית"))
        if momentum >= MOMENTUM_RUN_DAYS:
            notes.append(self._n(f"{momentum} green days in a row — momentum (watch for exhaustion)",
                                 f"{momentum} ימים ירוקים ברצף — מומנטום (להיזהר מהתשה)"))
        for g in (overlays.get('gaps') if overlays else []) or []:
            if g.get('dir') == 'down' and g.get('near') and g['near'] > price:
                pct = (g['near'] / price - 1) * 100
                notes.append(self._n(
                    f"Unfilled gap overhead — first station {g['near']:.2f} (+{pct:.0f}%), full fill at {g['far']:.2f}",
                    f"גאפ לא סגור מעל — תחנה ראשונה {g['near']:.2f} (+{pct:.0f}%), סגירה מלאה ב-{g['far']:.2f}"))
            elif g.get('dir') == 'up' and g.get('near') and g['near'] < price:
                notes.append(self._n(
                    f"Rose on a gap up — unfilled below at {g['near']:.2f}; it tends to get revisited",
                    f"עלתה בגאפ אפ — לא סגור מתחת ב-{g['near']:.2f}; נוטה לחזור לשם"))
        rn = self._round_number(price, ctx.atr)
        if rn is not None:
            # "מגיעים לנקודת המבחן. שימו לב שיש לי שם התראה - $400. יש משהו במספרים
            # עגולים" (MSFT); ORCL "$200"; he sets the alert ON the round number.
            notes.append(self._n(f"Round number {rn:g} right here — worth an alert on it",
                                 f"מספר עגול {rn:g} ממש כאן — שווה התראה עליו"))
        ed = ctx.earnings_days
        if ed is not None and ed <= EARNINGS_SOON_DAYS:
            notes.append(self._n(
                f"Earnings in {ed} day{'s' if ed != 1 else ''} — he defers new entries into a report",
                f"דיווח תוצאות בעוד {ed} ימים — לא נכנסים חדש לפני דיווח"))
        if small_cap:
            notes.append(self._n("Sub-$1B — outside the 150 method (more speculative)",
                                 "מתחת ל-1 מיליארד — מחוץ לשיטת ה-150 (ספקולטיבי יותר)"))
        return notes

    # ── Signal computations ────────────────────────────────────────────────────

    def _fib(self, ctx):
        mv = Geometry.fib_move(ctx.highs, ctx.lows, ctx.price, swing_lows=ctx.sl_idx)
        if mv is None or mv['retracement'] > 1.05:
            return None
        return {'retracement': mv['retracement'], 'peak': mv['peak_high'], 'base': mv['base_low']}

    def _ext20(self, ctx):
        """Extension above the 20MA — his 'too far, too fast' gauge (the 20 method)."""
        # …plus the short-term version of the same worry, which he states as a count
        # of days rather than a distance: "רבים שלחו לי שהיא עברה את הממוצע - צודקים.
        # הבעיה שלי זה שהיא רצה כל כך הרבה בימים האחרונים. זה מה שמטריד. 6 ימים
        # רצופים של עליות" (CRWD 2026-04-22) — the stock had just reclaimed the 150,
        # which the method calls a trigger, and he still would not take it because the
        # run into that trigger was the whole move. Distance from the 20MA does not
        # catch this on a name that gapped and then went sideways at the highs.
        closes = ctx.closes
        run_days = 0
        for i in range(len(closes) - 1, 0, -1):
            if closes[i] > closes[i - 1]:
                run_days += 1
            else:
                break
        n = min(RUN_UP_LOOKBACK, len(closes) - 1)
        run_pct = ((closes[-1] / closes[-1 - n] - 1) * 100) if n > 0 else 0.0
        run_atr = (run_pct / ctx.atr_pct) if ctx.atr_pct else 0.0
        ran_hot = bool(run_days >= RUN_UP_DAYS or run_atr >= RUN_UP_ATR)

        # "מתוחה" is a spectrum in his hands, not a flag:
        #   "קצת מתוחה מהממוצע … אתם לא מאחרים" (AAPL) / "קצת מתוחה אז זהירות עם
        #     הכניסה" (LUNR)                                          → mild
        #   "מתוחה מהממוצעים שלה … חייבים לשים סטופ בגלל שהיא מתוחה" (SHAK),
        #     "מתוחה אבל עדיין … כל עוד שומרת מעל 19 היא בסדר" (CRML)   → stretched
        #   "מתוחה ורחוקה מהממוצע. האם זו נקודת כניסה מתאימה כרגע — אני
        #     לא בטוח" (RDDT)                                          → severe
        # informational only — see the band comment below for why it drives nothing
        pct = (ctx.price / ctx.sma20 - 1) * 100 if (ctx.sma20 and ctx.sma20 > 0) else 0.0
        atr_mult = ((ctx.price - ctx.sma20) / ctx.atr
                    if (ctx.sma20 and ctx.sma20 > 0 and ctx.atr) else 0.0)
        # "מתוחה" is declared off the 150 and the 200 ONLY — the two averages the
        # method is built on, and the ones he names: "רחוק מהממוצע 150 + בקצה העליון
        # של התעלה" (GOLD), "עדיין מאוד רחוקה מהממוצע" (NOW), "מאוד רחוקה
        # מהממוצעים" (NBIS, plural — both), "מאוד רחוקה מהממוצע וגם רחוקה מקו
        # השיאים — יש זמן. מלא זמן" (AMD). Distance from the 20 is NOT this reading:
        # it disagrees constantly (CRWD, FTNT and PANW all sit at or under their 20
        # while 40%+ above their 150) and it answers a different question — how fast
        # the last few weeks went, which `ran_hot` already covers. `ext20_atr` stays
        # in the payload as an informational number and drives nothing.
        d150 = (ctx.price / ctx.sma150 - 1) if (ctx.sma150 and ctx.sma150 > 0) else 0.0
        d200 = (ctx.price / ctx.sma200 - 1) if (ctx.sma200 and ctx.sma200 > 0) else None
        mild = MILD_FROM_MA_PCT < d150 <= FAR_FROM_MA_PCT
        stretched = d150 > FAR_FROM_MA_PCT
        # "מהממוצעים" — plural. Clear of BOTH by a distance, which is the state he
        # declines outright rather than merely flags ("האם זו נקודת כניסה מתאימה
        # כרגע - אני לא בטוח", RDDT).
        far150 = stretched
        severe = stretched and d200 is not None and d200 > FAR_FROM_MA200_PCT
        level = ('severe' if severe else 'stretched' if stretched
                 else 'mild' if mild else 'none')
        return {'pct': pct, 'atr': atr_mult, 'stretched': stretched,
                'mild': mild, 'severe': severe, 'far_150': far150, 'level': level,
                'd150_pct': d150 * 100, 'd200_pct': (d200 * 100) if d200 is not None else None,
                'run_days': run_days, 'run_pct': run_pct, 'run_atr': run_atr,
                'ran_hot': ran_hot}

    def _trend(self, ctx):
        """Uptrend requires rising swing highs AND rising swing lows."""
        def slope(idx, arr):
            if len(idx) < 2:
                return 0.0
            s = np.polyfit(idx.astype(float), arr[idx], 1)[0]
            return s / ctx.mean_price * 100 if ctx.mean_price else 0.0
        sh, sl = slope(ctx.sh_idx, ctx.highs), slope(ctx.sl_idx, ctx.lows)
        thr = 0.02
        if sh > thr and sl > thr:
            return 'uptrend'
        if sh < -thr and sl < -thr:
            return 'downtrend'
        return 'sideways'

    def _momentum_days(self, ctx):
        c = ctx.closes
        n = 0
        for i in range(len(c) - 1, 0, -1):
            if c[i] > c[i - 1]:
                n += 1
            else:
                break
        return n

    def _capitulation(self, ctx, off_high):
        """A high-volume wash-out (or doji) after a deep decline, now stabilizing."""
        if off_high < OFF_HIGH_VALUE_PCT:
            return False
        o, h, l, c, v = ctx.opens, ctx.highs, ctx.lows, ctx.closes, ctx.vols
        avg = float(np.nanmean(v[-20:])) if len(v) >= 20 else float(np.nanmean(v))
        washed = False
        for i in range(max(len(c) - 15, 1), len(c)):
            rng = h[i] - l[i]
            if rng < 1e-9:
                continue
            body = abs(c[i] - o[i])
            if v[i] >= avg * CAPITULATION_VOL and (c[i] < o[i] or body <= 0.2 * rng):
                washed = True
        stabilizing = float(np.min(l[-3:])) >= float(np.min(l[-10:])) if len(l) >= 10 else True
        return bool(washed and stabilizing)

    def _long_base(self, ctx):
        """Longest recent tight range (≤1.5 ATR) — a pressure-relief coil near price."""
        h, l, atr, M = ctx.highs, ctx.lows, ctx.atr, len(ctx.highs)
        best, i = None, 0
        while i < M:
            top, bot, j = h[i], l[i], i
            while j < M and (max(top, h[j]) - min(bot, l[j])) <= 1.5 * atr:
                top, bot, j = max(top, h[j]), min(bot, l[j]), j + 1
            length = j - i
            if length >= LONG_BASE_BARS and (best is None or length > best['length']):
                best = {'length': length, 'top': float(top), 'bottom': float(bot), 'end': j}
            i = j if j > i else i + 1
        if best and best['end'] >= M - 20 and ctx.price >= best['bottom']:
            return best
        return None

    def _round_number(self, price, atr):
        if price <= 0:
            return None
        step = 10 ** max(0, int(math.floor(math.log10(price))) - 1) * 5
        nearest = round(price / step) * step
        return nearest if abs(price - nearest) <= ROUND_NEAR_ATR * atr else None

    def _fresh_break(self, ctx, sup_levels, overlays, broke_desc):
        """
        A breakout, the way he means it: price closed above a level that WAS resistance
        — "פריצה של התנגדות כלשהי מעל הראש שלי, אף פעם לא מתחתיי" — recently, and with
        volume behind it ("התנאי לפריצה - ווליום גבוה + פריצת שיאים יורדים", META).

        The old version fired on any close above a 30-bar rolling high at merely
        average volume, so it reported breakouts where no identified level had been
        cleared. This checks the actual level map: a former resistance that flipped to
        support is exactly the thing price just broke, so those are the candidates.

        Returns the LEVEL that was broken — the caller needs it to check price is
        still at it, because a break you are already several ATR above is not an
        entry any more, it is a chase — or None.
        """
        c, v, atr = ctx.closes, ctx.vols, ctx.atr
        lo = max(len(c) - BREAKOUT_FRESH_BARS, 1)
        avg = ctx.vol_avg or float(np.nanmean(v))
        flipped = [s['price'] for s in sup_levels
                   if s.get('flipped') and 0 < (ctx.price - s['price']) <= 3 * atr]
        best = None
        for lvl in flipped:
            for i in range(lo, len(c)):
                if c[i - 1] <= lvl < c[i] and (c[i] - lvl) > 0.05 * atr:
                    if avg and v[i] >= avg * VOL_SPIKE_FACTOR:
                        best = lvl if best is None else max(best, lvl)
        if best is not None:
            return best
        # a freshly broken descending-highs line is the same event in diagonal form
        # ("פורצת שיאים יורדים" — WGMI, NVDA, OKTA)
        if broke_desc:
            for t in overlays.get('trendlines', []):
                if t.get('kind') == 'falling_highs' and t.get('broke'):
                    return float(t['p2']['price'])
        return None

    def _lost_level(self, ctx, res_levels):
        """
        The mirror of `_fresh_break`: a level price was holding ABOVE and has just
        dropped through. This is what "אין סט אפ" actually reports — "כשאני מציין 'אין
        סט אפ' זה אומר שהסט אפ נגמר ... צריך לצאת מנקודת הנחה שהסטופ שלכם קפץ".

        Recency is the whole point. A stock that has been under its levels for months
        is not a setup that just broke, it is simply a downtrend — and telling someone
        their stop was hit on a chart they were never in is nonsense. Returns the level
        lost within the recent window, or None.
        """
        c, atr = ctx.closes, ctx.atr
        lo = max(len(c) - BREAKOUT_FRESH_BARS, 1)
        best = None
        for r in res_levels:
            lvl = r['price']
            if not (0 < (lvl - ctx.price) <= 2 * atr):
                continue
            for i in range(lo, len(c)):
                if c[i - 1] >= lvl > c[i] and (lvl - c[i]) > 0.05 * atr:
                    best = lvl if best is None else min(best, lvl)
        return best

    def _broke_descending(self, ctx, overlays):
        for t in overlays.get('trendlines', []):
            if t.get('kind') == 'falling_highs':
                edge = t['p2']['price']
                if edge is not None and ctx.price > edge:
                    return True
        return False

    def _volume_detail(self, ctx, break_level):
        """
        Volume, past "rising / falling". The two things he actually reads:

        • The BREAK bar. "התנאי לפריצה - ווליום גבוה + פריצת שיאים יורדים" (META).
          A break without volume is not a break — "הבעיה היחידה היא הווליום" (OKLO).
        • The PULLBACK. A correction on drying-up volume is healthy and he ticks it
          explicitly: "✅ תיקון עם ווליום נמוך" (TSLA), "הווליום יורד תוך כדי הירידה
          כלומר המוכרים מתמעטים" (OPEN). Same falling volume in a RISE is the
          opposite — nobody is interested.
        """
        v, c = ctx.vols, ctx.closes
        avg = ctx.vol_avg or float(np.nanmean(v))
        if not avg:
            return None
        today = float(v[-1]) / avg
        # biggest volume bar of the last two weeks, and whether it was up or down
        lo = max(len(v) - 10, 0)
        seg = v[lo:]
        i = int(np.argmax(seg)) + lo
        spike_ratio = float(v[i]) / avg
        spike_up = bool(c[i] >= c[i - 1]) if i > 0 else True
        spike_ago = len(v) - 1 - i

        # last 5 bars: is price falling while volume dries up?
        span = 5
        rising_price = c[-1] > c[-span]
        vol_recent = float(np.mean(v[-span:]))
        vol_prior = float(np.mean(v[-2 * span:-span])) if len(v) >= 2 * span else vol_recent
        dry = vol_prior > 0 and vol_recent < vol_prior * 0.85
        quiet_pullback = bool(dry and not rising_price)

        break_vol = None
        if break_level:
            for j in range(max(len(c) - BREAKOUT_FRESH_BARS, 1), len(c)):
                if c[j - 1] <= break_level < c[j]:
                    break_vol = float(v[j]) / avg
                    break

        return {
            'today_x': jnum(today),
            'spike_x': jnum(spike_ratio), 'spike_up': spike_up, 'spike_bars_ago': spike_ago,
            'quiet_pullback': quiet_pullback,
            'dry_up': bool(dry),
            'break_vol_x': jnum(break_vol),
        }

    def _duration(self, ctx):
        """
        How LONG the current state has held — his own framing: "מאז יולי 25 היא שומרת
        מעל ממוצע 150. כל פעם מתרחקת וחוזרת" (BE). A stock that reclaimed the 150
        three days ago and one that has held it for a year are not the same chart.
        """
        sma = ctx.w['sma150'].to_numpy(float)
        c = ctx.closes
        ok = ~np.isnan(sma)
        if not ok.any():
            return None
        above = c >= sma
        # length of the current run (above or below)
        cur = bool(above[-1])
        run = 0
        for i in range(len(above) - 1, -1, -1):
            if bool(above[i]) != cur or np.isnan(sma[i]):
                break
            run += 1
        window = int(ok.sum())
        pct_above = float(np.mean(above[ok])) * 100 if window else None
        return {
            'above': cur, 'run_bars': run,
            'pct_above_window': jnum(pct_above), 'window_bars': window,
        }

    def _relative_strength(self, ctx):
        """
        The stock against the market. He reads this constantly — NVDA "עדיין יותר זולה
        מהסנפ והנסדק 100", AMD "ביחס לסנפ 500 הגענו לנקודה שכבר קפצנו ממנה בעבר".
        Rising with the tide is not the same as leading it.
        """
        b = ctx.bench
        if b is None or len(b) != len(ctx.closes):
            return None
        c = ctx.closes
        out = {}
        for name, bars in (('m1', 21), ('m3', 63), ('m6', 126)):
            if len(c) <= bars or b[-bars - 1] <= 0 or c[-bars - 1] <= 0:
                continue
            stock = (c[-1] / c[-bars - 1] - 1) * 100
            mkt = (b[-1] / b[-bars - 1] - 1) * 100
            out[name] = {'stock': jnum(stock), 'market': jnum(mkt),
                         'excess': jnum(stock - mkt)}
        if not out:
            return None
        ref = out.get('m3') or out.get('m1') or out.get('m6')
        ex = ref['excess']
        lead = 'leading' if ex >= 5 else 'lagging' if ex <= -5 else 'inline'
        return {'legs': out, 'lead': lead, 'excess_pct': ex}

    def _pattern_detail(self, ctx, codes, base, overlays, channel):
        """The measurable facts of whichever structure is on the chart."""
        out = {}
        if base:
            depth = (base['top'] - base['bottom']) / base['bottom'] * 100 if base['bottom'] else None
            out['base'] = {'bars': base['length'], 'top': jnum(base['top']),
                           'bottom': jnum(base['bottom']), 'depth_pct': jnum(depth)}
        ft = (overlays or {}).get('flag_top')
        if ft:
            out['flag'] = {'top': jnum(ft),
                           'breaking': bool((overlays or {}).get('flag_breaking')),
                           'dist_pct': jnum((ft / ctx.price - 1) * 100)}
        if channel:
            out['channel'] = {'kind': channel['kind'], 'pos_pct': channel['pos_pct'],
                              'zone': channel['zone']}
        for t in (overlays or {}).get('trendlines') or []:
            out.setdefault('lines', []).append({
                'kind': t.get('kind'), 'touches': t.get('touches'),
                'broke': bool(t.get('broke')),
                'price': (t.get('p2') or {}).get('price'),
            })
        tri = (overlays or {}).get('triangles') or []
        if tri:
            up = ((tri[0].get('upper') or {}).get('p2') or {}).get('price')
            lo = ((tri[0].get('lower') or {}).get('p2') or {}).get('price')
            out['triangle'] = {'upper': up, 'lower': lo}
        return out or None

    def _volume_trend(self, ctx):
        v = ctx.vols
        if len(v) < 12:
            return {'trend': 'flat', 'falling_streak': 0,
                    'note': 'not enough volume history', 'note_he': 'אין מספיק היסטוריית ווליום'}
        recent, prior = float(np.mean(v[-5:])), float(np.mean(v[-10:-5]))
        streak = 0
        for i in range(len(v) - 1, 0, -1):
            if v[i] < v[i - 1]:
                streak += 1
            else:
                break
        if recent > prior * 1.05:
            return {'trend': 'rising', 'falling_streak': streak,
                    'note': 'volume expanding into the move', 'note_he': 'ווליום מתרחב לתוך המהלך'}
        if recent < prior * 0.95:
            return {'trend': 'falling', 'falling_streak': streak,
                    'note': 'volume drying up', 'note_he': 'ווליום מתייבש'}
        return {'trend': 'flat', 'falling_streak': streak,
                'note': 'volume steady', 'note_he': 'ווליום יציב'}

    def _buyers_candle(self, ctx, nearest_sup):
        """
        Two DIFFERENT candles, which he treats differently and which the old version
        conflated into one flag:

          `found` — buyers actually arrived: a hammer, a bullish engulfing, or a strong
            green body on real volume. This is an entry — "נכנס ווליום בשישי + נר קונים
            חזק. סטופ מתחת לקו" (LMND), "כניסת קונים באיזור הממוצע" (AVGO).

          `turn` — a doji or a harami: the direction-change candle. It is indecision,
            NOT buyers, and on it he says the opposite thing — WAIT: "נר דוג'י על קו
            תמיכה. למה זה מעניין? ... חכו לקונים" (OPEN), "הגיעה לקו - ושמה דוג'י"
            (ASTS). Counting a doji as an entry turned almost every chart into a buy,
            because some 3-bar window nearly always holds one.

        Only the last two bars count — a buyers' candle from a week ago is history.
        The candle's own LOW is published because it is a stop reference in its own
        right: "סטופ בנמוך של שישי" (ARM), "סטופ בנמוך היומי 135.3" (ANET).
        """
        o, h, l, c, v = ctx.opens, ctx.highs, ctx.lows, ctx.closes, ctx.vols
        atr = ctx.atr
        avg = float(np.nanmean(v[-20:])) if len(v) >= 20 else float(np.nanmean(v))
        near_sup = True
        if nearest_sup:
            near_sup = (ctx.price - nearest_sup['price']) / atr <= 2.0
        turn = None
        for i in range(len(c) - 1, max(len(c) - 3, 0), -1):
            rng = h[i] - l[i]
            if rng < 1e-9 or not near_sup:
                continue
            body = abs(c[i] - o[i])
            lower_wick = min(o[i], c[i]) - l[i]
            hammer = lower_wick >= 2 * body and c[i] >= l[i] + rng * 0.5
            engulf = (i > 0 and c[i] > o[i] and o[i - 1] > c[i - 1]
                      and c[i] >= o[i - 1] and o[i] <= c[i - 1])
            strong_green = c[i] > o[i] and body >= 0.5 * rng and v[i] >= avg
            if hammer or engulf or strong_green:
                en, he = (('Hammer at the level', 'נר פטיש על הרמה') if hammer else
                          ('Bullish engulfing', 'נר בולען') if engulf else
                          ('Strong buyers candle on volume', 'נר קונים חזק עם ווליום'))
                return {'found': True, 'turn': False, 'label': en, 'label_he': he,
                        'low': float(l[i]), 'bars_ago': len(c) - 1 - i,
                        'detail': f'bar -{len(c) - 1 - i}'}
            # a doji counts even when it closes RED — "יכול להיות אדום ועדיין מבחינתי
            # זה דוג'י" — but it means "wait", not "buy"
            if turn is None and body <= DC_DOJI_BODY * rng:
                turn = (float(l[i]), len(c) - 1 - i)
        if turn:
            return {'found': False, 'turn': True,
                    'label': "Doji at the level — indecision, wait for buyers",
                    'label_he': "דוג'י על הרמה — היסוס, לחכות לקונים",
                    'low': turn[0], 'bars_ago': turn[1], 'detail': f'bar -{turn[1]}'}
        return {'found': False, 'turn': False, 'label': 'No buyers candle',
                'label_he': 'אין נר קונים', 'low': None, 'bars_ago': None, 'detail': ''}

    def _ma_confluence(self, ctx):
        if not (ctx.sma150 and ctx.sma200):
            return False
        return bool(abs(ctx.sma150 - ctx.sma200) <= 1.5 * ctx.atr
                    and min(abs(ctx.price - ctx.sma150),
                            abs(ctx.price - ctx.sma200)) <= 2.0 * ctx.atr)

    def _pattern(self, codes, base):
        for code, en, he in (
            ('bull_flag', 'Cup & handle / flag', 'קאפ אנד הנדל'),
            ('triangle', 'Converging triangle', 'משולש מתכנס'),
            ('rising_channel', 'Rising channel', 'תעלה עולה'),
            ('descending_channel', 'Descending channel', 'תעלה יורדת'),
            ('bearish_to_bullish', 'Bearish→bullish base', 'בריש טו בוליש'),
            ('ma_bounce', 'MA bounce', 'קפיצה מהממוצע'),
            ('support_test', 'Breakout retest', 'בדיקת תמיכה אחרי פריצה'),
            ('above150_breakout', 'Rising lows into resistance', 'שפלים עולים לתוך התנגדות'),
            ('resistance_retest', 'Back at the scene of the crime', 'חזרה לזירת הפשע'),
            ('below150_floor', 'Support floor', 'רצפת תמיכה'),
        ):
            if code in codes:
                return en, he
        if base:
            return 'Long consolidation base', 'בסיס התכנסות ארוך'
        return None

    @staticmethod
    def _n(en, he):
        return {'en': en, 'he': he}
