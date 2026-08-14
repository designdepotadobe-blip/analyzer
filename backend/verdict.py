"""
verdict.py — the judgement layer.

Everything upstream (levels, trendlines, Fibonacci, channels, candles, volume)
answers "what is drawn on this chart". This module answers the only four questions
Micha ever actually answers about a chart:

    is there a trade here — at what price — where does the stop go — what is it worth?

It is rebuilt from 2,273 of his own posts (Dec 2024 → Jul 2026) and follows the shape
that every single one of them has:

    [what the chart IS] → [the trigger price] → [the stop, under the structure]
    → [the target / potential]

...and their brevity. He once posted a long, ChatGPT-style breakdown of TT and then
wrote underneath it: "when I wrote it without ChatGPT it looked like this: nothing to
add, the stock is bouncing on the 150 😂" (2024-12-30). Length is not analysis.

Three things drive everything here:

1. A STATE MACHINE, not a score. Every post he writes lands in one of a small set of
   states, and each state has its own script. "אין סט אפ" is a state (the setup ENDED —
   "צריך לצאת מנקודת הנחה שהסטופ שלכם קפץ"), not a low score.

2. NEVER BEFORE THE TRIGGER. "אין מה להיכנס לפני" (FLY), "חכו לפריצה שלא סתם תעופו
   בסטופ" (SEDG). A pending trigger is an alert, never an entry.

3. THE STOP IS THE GRADE. His A-grade sentence is always the same shape: "מעל נקודת
   הפריצה. מעל ממוצע 150. קרוב לממוצע. מה עוד נותר לבקש" (GEV) / "עם סטופ מתחת לקו
   הלבן / מתחת לממוצע 150 — לא צריך להיות אפילו שיקול" (AVGO) / "אחלה נקודת כניסה עם
   סטופ נוח בממוצע" (INOD). What makes a setup excellent is that the invalidation sits
   right there, tight and obvious. That is also why a great company far from its
   averages is NOT a trade — "המניה מעולה, פשוט רחוקה כרגע מהממוצעים" (CRD): there is
   no good stop from up here.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Optional

from config import (
    ALERT_CLOSE_ATR,
    ALERT_IMMINENT_ATR,
    ALERT_MAX_PCT,
    ALERT_MIN_ATR,
    ALERT_MIN_PCT,
    ALERT_NEAR_ATR,
    CUP_RIM_DEPTH_ATR,
    CUP_RIM_NEAR_ATR,
    EARNINGS_SOON_DAYS,
    EXTENDED_ATR,
    FAR_FROM_MA_PCT,
    TARGET_ODDS_FLOOR,
    GAP_STOP_MAX_ATR,
    GRADE_BAND_RANGE,
    GRADE_BANDS,
    GRADE_BUDGET,
    MIN_MARKET_CAP,
    NEAR_ATR,
    OFF_HIGH_VALUE_PCT,
    STOP_BUFFER,
    STOP_IDEAL_ATR,
    STOP_MAX_RISK_PCT,
    STOP_NOISE_ATR,
    STOP_POSITION_WIDEN,
    STOP_RISK_BUDGET_PCT,
    STOP_WIDE_ATR,
    TIME_EFFICIENCY_MAX,
    TIME_FAST_DAYS,
    TIME_MEDIAN_DAYS,
    TIME_SLOW_DAYS,
    TRIGGER_AT_HAND_ATR,
    TRIGGER_NEAR_ATR,
    TRIGGER_REACH_ATR,
    TRIGGER_ZONE_ATR,
    VALUE_NEAR_150_ATR,
    expectancy,
    jnum,
    time_to_target,
)

# ── The states, in his language ───────────────────────────────────────────────
STATE_LABELS = {
    'breakout_now':    ('Breakout happening',        'פריצה עכשיו'),
    'buyers_at_level': ('Buyers stepped in at the level', 'קונים נכנסו על הרמה'),
    'value_pullback':  ('Value pullback',            'השקעת ערך בתיקון'),
    'at_trigger':      ('Coiled at the trigger',     'מתכנסת לפני פריצה'),
    'needs_buyers':    ('At the level, waiting for buyers', 'על הרמה, מחכים לקונים'),
    'holding':         ('In the move, holding',      'בתוך המהלך, שומרת'),
    'nothing_yet':     ("Hasn't done anything yet",  'עוד לא עשתה כלום'),
    'broken':          ('Setup is over',             'הסט אפ נגמר'),
    'avoid':           ('Below the 150 in a downtrend', 'מתחת ל-150 במגמה יורדת'),
}

ACTION_LABELS = {
    'enter':        ('Enter',                'כניסה'),
    'wait_trigger': ('Wait for the trigger', 'להמתין לפריצה'),
    'wait_buyers':  ('Wait for buyers',      'להמתין לקונים'),
    'wait_pullback': ('Wait for a pullback', 'להמתין לתיקון'),
    'wait_event':   ('Wait for the report',  'להמתין לדיווח'),
    'hold':         ('Hold — no new entry here', 'להחזיק — לא כניסה חדשה כאן'),
    'watch':        ('Watchlist + alert',    'מעקב + התראה'),
    'out':          ('Out',                  'בחוץ'),
    'avoid':        ('Do not enter',         'לא להיכנס'),
}

GRADE_MEANING = {
    'A': ("Everything lines up — above the 150, near it, trigger in hand, tight stop.",
          'הכל מסתדר — מעל ה-150, קרוב אליו, טריגר ביד, סטופ צמוד.'),
    'B': ('A real setup with one caveat.', 'סט אפ אמיתי עם הסתייגות אחת.'),
    'C': ('On the watchlist — not ripe.', 'ברשימת מעקב — עוד לא בשל.'),
    'D': ('Weak — the structure or the stop is not there.',
          'חלש — המבנה או הסטופ לא שם.'),
    'F': ('Not a trade.', 'לא טרייד.'),
}
GRADES = ['F', 'D', 'C', 'B', 'A']


@dataclass
class Signals:
    """Everything the judgement reads. Computed upstream, never here."""
    # price context
    trend: str = 'sideways'
    off_high: float = 0.0
    ath: float = 0.0
    fib_r: float = 0.0
    golden: bool = False
    ext: dict = field(default_factory=dict)
    vol: dict = field(default_factory=dict)
    candle: dict = field(default_factory=dict)
    capitulation: bool = False
    base: Optional[dict] = None
    momentum: int = 0
    # structure
    res_levels: list = field(default_factory=list)
    sup_levels: list = field(default_factory=list)
    nearest_res: Optional[dict] = None
    nearest_sup: Optional[dict] = None
    broke_desc: bool = False
    break_level: Optional[float] = None   # a level just broken upward, if any
    lost_level: Optional[float] = None    # a level just lost downward, if any
    overlays: dict = field(default_factory=dict)
    codes: set = field(default_factory=set)
    dir_change: Optional[dict] = None
    channel: Optional[dict] = None
    targets: list = field(default_factory=list)
    pattern: Optional[tuple] = None
    recent_low: Optional[float] = None    # lowest low of the last few bars
    # richer readings, used by reasons.py to argue the call
    vol_detail: Optional[dict] = None
    duration: Optional[dict] = None
    rel_strength: Optional[dict] = None
    pattern_detail: Optional[dict] = None
    level_context: Optional[dict] = None


def drawn_line(overlays, kind: str) -> Optional[dict]:
    """
    The trendline of this kind ACTUALLY DRAWN on the chart, or None.

    Text must never claim a line the chart does not show. Two different things get
    called "rising lows" in this codebase and they disagree often: `Signals.trend`
    is a polyfit slope through two years of swing pivots, and the direction-change
    sequence falls back to a weekly-lows reading — both real signals, neither a
    drawn object. The chart's line is a strict pivot-snapped segment
    (`Geometry.segment_trendline`) that is hidden entirely unless price is testing
    or has just broken it, exactly as he draws them. So any sentence containing the
    word "line" has to be sourced from here; sentences about the slope may not use
    it. Measured on 18 names, 7 asserted "rising highs and lows" on a chart showing
    no such line before this existed.
    """
    for t in (overlays or {}).get('trendlines') or []:
        if t.get('kind') == kind:
            return t
    return None


def _edge(lvl, side: str) -> Optional[float]:
    """A zone is cleared above its TOP and held above its BOTTOM — he quotes zones as
    bands ("58.83 - 60.35" LMND), so collapsing one to its midpoint fakes a breakout."""
    if not lvl:
        return None
    if lvl.get('is_zone'):
        e = lvl.get('zone_top') if side == 'res' else lvl.get('zone_bottom')
        if e:
            return float(e)
    return float(lvl['price'])


class Judgement:
    # ── Entry point ───────────────────────────────────────────────────────────

    def evaluate(self, ctx, s: Signals) -> dict:
        price, atr = ctx.price, ctx.atr
        small_cap = bool(ctx.market_cap and ctx.market_cap < MIN_MARKET_CAP)
        earn = ctx.earnings_days

        trigger = self._trigger(ctx, s)
        hold = self._hold_level(ctx, s)
        state = self._state(ctx, s, trigger, hold)
        options = self._options(ctx, s, state, trigger, hold)
        action = self._action(state, s, earn, options)
        grade, breakdown = self._grade(ctx, s, state, trigger, options, action,
                                       small_cap, earn)
        alert = self._alert(ctx, s, trigger, action)
        if_break = self._grade_if_break(ctx, s, state, trigger, options, grade,
                                        breakdown, small_cap, earn)
        report = self._report(ctx, s, state, action, trigger, hold, options, grade,
                              breakdown, earn, small_cap, alert)

        st_en, st_he = STATE_LABELS[state]
        ac_en, ac_he = ACTION_LABELS[action]
        gm_en, gm_he = GRADE_MEANING[grade]
        return {
            'state': state, 'state_label': st_en, 'state_label_he': st_he,
            'action': action, 'action_label': ac_en, 'action_label_he': ac_he,
            'grade': grade, 'grade_score': breakdown['score'],
            'grade_meaning': gm_en, 'grade_meaning_he': gm_he,
            # Why THIS stock earned THIS letter, in two sentences, built from the
            # grade's own terms. `grade_meaning` above is one fixed string per
            # letter and says the same thing about every B in the universe; this
            # replaces it in the panel and is kept beside it only for compatibility.
            'grade_why': breakdown['summary'], 'grade_why_he': breakdown['summary_he'],
            'grade_breakdown': breakdown,
            # "and if it DOES break?" — see _grade_if_break
            'grade_if_break': if_break,
            'trigger': trigger,
            'alert': alert,
            'hold_level': hold,
            'options': options,
            'report': report,
        }

    def _grade_if_break(self, ctx, s: Signals, state, trigger, options, grade,
                        breakdown, small_cap, earn) -> Optional[dict]:
        """
        "…and if it DOES break?"

        The grade answers what a chart IS today, which is the right question and the
        wrong one to act on alone. GILD sits 1.6 ATR under the 150MA: setup 18/40
        because the method's anchor is failing, trigger 17/30, total D 51 — all
        correct, and all of it describing a stock that is one close away from a
        different chart. A reader seeing D moves on; the code knows the trigger is
        near and that clearing it flips `above_150`, fills the trigger axis, and
        re-prices the stop against the level just broken. That gap between "what it
        is" and "what it becomes" was invisible, and it is exactly where the
        watchlist decision lives.

        Computed by re-grading with the break assumed: state `breakout_now`, the
        breakout option as the plan, and — when the trigger IS the 150MA — a context
        shimmed to sit just above it. Everything else (trend, volume, pattern,
        candle) is left at today's reading, because those are facts about the chart
        and not consequences of the break. So this is a projection of the MECHANICAL
        consequences of clearing the price, not a prediction that it will clear, and
        it deliberately does not touch the real grade.
        """
        # Only for a chart you are WAITING on. Where the call is already "enter", the
        # reader is being told to buy at today's price, and a breakout entry is simply
        # a worse version of the same trade — same stop, higher entry, so mechanically
        # lower R/R. Reporting that as "if it breaks: A → B" (CPAY, -14) reads as a
        # warning against the breakout when it is only an artifact of comparing a
        # chase to an entry already in hand. `nothing_yet` is excluded for the opposite
        # reason: with no setup, a break projects a grade off a chart that has not
        # earned one.
        if not trigger or state in ('breakout_now', 'buyers_at_level', 'value_pullback',
                                    'broken', 'avoid', 'nothing_yet'):
            return None
        brk = next((o for o in options if o['kind'] == 'breakout'), None)
        if not brk or trigger['tier'] == 'far':
            return None

        tp = trigger['price']
        # A break of the 150 is a different chart; a break of a flag top is the same
        # chart one level higher. Only the former earns the structural upgrade.
        if trigger.get('kind') == 'ma150' and not ctx.above_150:
            ctx2 = replace(ctx, price=tp * 1.001, above_150=True,
                           above_200=bool(ctx.sma200 and tp >= ctx.sma200))
        else:
            ctx2 = replace(ctx, price=tp * 1.001)

        g2, bd2 = self._grade(ctx2, s, 'breakout_now', trigger, [brk], 'enter',
                              small_cap, earn)
        delta = bd2['score'] - breakdown['score']
        moved = g2 != grade
        return {
            'grade': g2, 'score': bd2['score'], 'delta': jnum(delta),
            'moves': moved,
            'at_price': jnum(tp),
            'components': bd2['components'],
            'caps': bd2['caps'],
            # the same two-sentence explanation, for the projected letter
            'why': bd2['summary'], 'why_he': bd2['summary_he'],
            'label': (f"clears {tp:.2f} → {g2} ({bd2['score']:.0f})"
                      if moved else f"clears {tp:.2f} → still {g2}"),
            'label_he': (f"פורצת {tp:.2f} → {g2} ({bd2['score']:.0f})"
                         if moved else f"פורצת {tp:.2f} → נשארת {g2}"),
        }

    # ── 1. The trigger — the price he names ───────────────────────────────────

    def _trigger(self, ctx, s: Signals) -> Optional[dict]:
        """
        The single price that has to be cleared for the trade to be on. He names
        exactly one ("פריצה מעל $69", "מעבר מעל 215", "חכו לפריצה מעל $280") and it is
        always the FIRST obstacle overhead, whatever kind of thing that is: a
        horizontal level, the descending-highs line, a flag top, the triangle, the
        upper rail of a falling channel, or the 150MA itself when price is under it.
        """
        price, atr = ctx.price, ctx.atr
        ov = s.overlays or {}
        # (price, kind, en, he, wall) — `wall` carries how well-defended this price is.
        # Only a horizontal level has a touch history; a trendline/flag/triangle is a
        # geometry, and the 150MA is an average, so those stay None rather than being
        # given a fake strength.
        cands: list[tuple[float, str, str, str, Optional[dict]]] = []

        edge = _edge(s.nearest_res, 'res')
        if edge and edge > price:
            nr = s.nearest_res or {}
            flipped = bool(nr.get('flipped'))
            en = 'the breakout price' if flipped else 'resistance'
            he = 'מחיר הפריצה' if flipped else 'ההתנגדות'
            cands.append((edge, 'level', en, he, {
                'strength': nr.get('strength'),
                'touches': nr.get('touches'),
                'quality': nr.get('quality'),
                'flipped': flipped,
                'freshness': nr.get('freshness'),
            }))

        for t in ov.get('trendlines') or []:
            if t.get('kind') == 'falling_highs':
                p = (t.get('p2') or {}).get('price')
                if p and p > price:
                    cands.append((float(p), 'trendline', 'the descending-highs line',
                                  'קו השיאים היורדים', None))

        ft = ov.get('flag_top')
        if ft and ft > price:
            cands.append((float(ft), 'flag', 'the flag top', 'ראש הדגל', None))

        for tri in ov.get('triangles') or []:
            p = ((tri.get('upper') or {}).get('p2') or {}).get('price')
            if p and p > price:
                cands.append((float(p), 'triangle', 'the triangle', 'המשולש', None))

        if s.channel and s.channel.get('kind') == 'descending' and s.channel.get('upper'):
            u = s.channel['upper']
            if u > price:
                cands.append((float(u), 'channel', 'the upper rail of the falling channel',
                              'הרף העליון של התעלה היורדת', None))

        # The rim of a cup, and the top of a long base. Both are prices he names as
        # the breakout — "קאם אנד הנדל, פריצה פוטנציאלית מעל 177.5" (MMM), "פריצה
        # אחרי מחיר $34" (GTLB) — and neither can reach the level map: a cup rim is a
        # single pivot (MIN_LEVEL_TOUCHES=2 excludes it) and a base top is a range
        # edge. Without them the trigger fell through to the all-time high, which put
        # the whole setup further away than he calls it. No `wall`: a rim has no
        # touch history, and inventing one would be exactly the fabricated strength
        # the level-backed candidates above are careful to avoid.
        rim = self._cup_rim(ctx, price)
        if rim:
            cands.append((rim, 'cup_rim', 'the cup rim', 'שפת הקאפ', None))

        if s.base and s.base.get('top') and s.base['top'] > price:
            cands.append((float(s.base['top']), 'base', 'the top of the base',
                          'ראש הבסיס', None))

        # Below the 150 the 150 IS the trigger — "עד שהיא פורצת את ה-200 אין מה לרדוף",
        # "ברגע שתעבור את ממוצע 150 ... זה אפילו טרייד יותר בשרני" (ADBE).
        if ctx.sma150 and ctx.sma150 > price:
            cands.append((float(ctx.sma150), 'ma150', 'the 150MA', 'ממוצע 150', None))

        # With nothing else overhead the prior high IS the breakout price — WGMI's
        # staircase ends at "74.29 מחיר פריצה שיא", PM "מגיעה שוב לשיאים שלה. שוב מנסה
        # לפרוץ ... פריצה ממחיר $193", KBE "67.75 הפריצה המלאה לשיא כל הזמנים".
        if s.ath and s.ath > price * 1.002:
            cands.append((float(s.ath), 'ath', 'the prior high', 'השיא הקודם', None))

        if not cands:
            return None
        p, kind, en, he, wall = min(cands, key=lambda c: c[0])

        # ── The breakout line is a ZONE, not a single price ────────────────────
        # He quotes it as a band whenever the walls cluster: "קו הפריצה 85.8-86.5$"
        # (LRCX), "התנגדות עשבו ב 477-484" (SPGI). Clearing only the first line of a
        # cluster is not a breakout — the next wall is right there, so the move has
        # no room and the "potential" measured past it is fiction. Observed: GTLB
        # triggered at 37.03 while a STRONGER wall (3 touches, q .45) sat at 37.95,
        # and CSCO triggered off a trendline at 116.81 with a 6-touch level at 116.89.
        # So: absorb any resistance sitting within TRIGGER_ZONE_ATR above the pick and
        # quote the top of the zone, which is the price that actually has to give.
        zone_top, zone_lo, absorbed = p, p, 0
        # ascending: the zone chains upward one wall at a time, so an unsorted list
        # would silently skip a rung and merge across a gap it should have stopped at
        for r in sorted((r for r in (s.res_levels or []) if r.get('price')),
                        key=lambda r: r['price']):
            rp = r.get('price')
            if rp <= p:
                continue
            if (rp - zone_top) / atr <= TRIGGER_ZONE_ATR:
                zone_top, absorbed = float(rp), absorbed + 1
                # the strongest wall in the zone is the one being described
                if (r.get('touches') or 0) > ((wall or {}).get('touches') or 0):
                    wall = {'strength': r.get('strength'), 'touches': r.get('touches'),
                            'quality': r.get('quality'), 'flipped': bool(r.get('flipped')),
                            'freshness': r.get('freshness')}
                    kind = 'level'
        if absorbed:
            en = f'the breakout zone {zone_lo:.2f}-{zone_top:.2f}'
            he = f'אזור הפריצה {zone_lo:.2f}-{zone_top:.2f}'
            p = zone_top

        # ── The FLOOR of that line — where the stop goes ───────────────────────
        # His two labelled charts say it outright: OKTA's band is drawn "86.88 -
        # 88.17" and the post reads "פריצה מעל 88.17. סטופ מתחת 86"; SMCI's is
        # "34.94 - 35.88" and the post reads "מחיר מעל 35.88. סטופ 34.5". The
        # trigger is the band's TOP and the stop is just under its BOTTOM — the
        # width of the wall IS the risk budget, which is why his stops measure a
        # median 0.43 ATR while a stop hunted from unrelated structure below
        # measured 1.52 ATR over the same 404 posts.
        # `zone_lo` already holds the lowest wall of an absorbed cluster; drop to
        # that wall's own lower edge, so this works for the ordinary single-level
        # case too and not only for a level wide enough to be DRAWN as a band.
        floor = zone_lo
        for r in (s.res_levels or []):
            b = r.get('bottom')
            if b and abs(float(r.get('price') or 0) - zone_lo) <= atr * 0.05:
                floor = min(floor, float(b))

        d_atr = (p - price) / atr if atr else 0.0
        d_pct = (p / price - 1) * 100 if price else 0.0
        tier = ('at_hand' if d_atr <= TRIGGER_AT_HAND_ATR else
                'near' if d_atr <= TRIGGER_NEAR_ATR else
                'moderate' if d_atr <= TRIGGER_REACH_ATR else 'far')
        return {
            'price': jnum(p), 'kind': kind, 'what': en, 'what_he': he,
            # the lower edge of the same wall — see above; `_stop` leans on this
            'floor': jnum(floor),
            # How well-defended this price is, when it is a horizontal level with a
            # touch history (a trendline/flag/average has none, and gets None rather
            # than a fabricated strength). DESCRIPTIVE ONLY — deliberately not fed
            # into the grade: measured over ~9k breakouts, a hard wall (4+ touches)
            # beat a soft one (2 touches) by -0% / +5% / +2% at 2R / 3R / 5R, and as
            # a stop anchor by 1.4 points of hold-rate with identical forward
            # returns. Real information for the reader; not a predictive edge.
            'wall': wall,
            'distance_atr': jnum(d_atr), 'distance_pct': jnum(d_pct), 'tier': tier,
            'label': f"break above {p:.2f} ({en}) — {d_pct:.1f}% / {d_atr:.1f} ATR away",
            'label_he': f"פריצה מעל {p:.2f} ({he}) — {d_pct:.1f}% / {d_atr:.1f} ATR",
        }

    @staticmethod
    def _cup_rim(ctx, price: float) -> Optional[float]:
        """
        The left rim of a cup: a swing high price fell away from by a real depth and
        has since climbed back toward.

        He names exactly this price as the breakout even though a lone pivot can
        never become a clustered level, which is why the trigger used to fall
        through to the all-time high instead. Gated on the SHAPE, not on the pivot:
        the decline behind the rim must be deep enough to be a cup rather than a
        shelf, and price must have recovered back near it — from the bottom of the
        cup the rim is not the next obstacle, it is a different trade.

        Returns the LOWEST qualifying rim above price (the first obstacle), or None.
        """
        atr = ctx.atr
        if not atr or ctx.sh_idx is None or not len(ctx.sh_idx):
            return None
        highs, lows, M = ctx.highs, ctx.lows, ctx.M
        best = None
        for i in (int(x) for x in ctx.sh_idx):
            if i >= M - 2:
                continue                    # no room behind it to have formed a cup
            rim = float(highs[i])
            if rim <= price or (rim - price) / atr > CUP_RIM_NEAR_ATR:
                continue
            trough = float(lows[i + 1:].min())
            if (rim - trough) / atr < CUP_RIM_DEPTH_ATR:
                continue                    # a shelf, not a cup
            if best is None or rim < best:
                best = rim
        return best

    # ── 1b. "מתקרב להכרעה" — not a trade today, but close to becoming one ──────

    @staticmethod
    def _days_phrase(d: float) -> tuple:
        """
        ATR distance in his own unit — "לוקחים את התנועה הממוצעת היומית". Phrased as
        a RANGE, not as elapsed time: ATR measures how far a stock travels in a day,
        not how far it trends, so "two average days away" would promise a directional
        move the number does not support.
        """
        if d <= ALERT_IMMINENT_ATR:
            return "under half an average day's range", 'פחות מחצי טווח יומי ממוצע'
        if d <= ALERT_CLOSE_ATR:
            return "about one average day's range", 'בערך טווח יומי ממוצע אחד'
        return f'about {d:.1f} average daily ranges', f'בערך {d:.1f} טווחים יומיים ממוצעים'

    def _alert(self, ctx, s: Signals, trigger, action) -> Optional[dict]:
        """
        The watchlist signal, kept deliberately apart from the grade.

        A stock can be a correct D — below the 150, no setup, nothing to buy — and
        still be a third of an average day from the price that starts the argument.
        That is not a better grade, it is a different fact, and it is the one he acts
        on: "מתקרב להכרעה. שימו התראה. כשהיא תקפוץ אני אעלה את הסט אפ" (ONDS).

        `gate` keeps it honest: clearing the nearest level does not automatically make
        a sub-150 name tradeable, so when the 150 still sits overhead we say so rather
        than implying the whole thesis is one candle away.
        """
        if action == 'enter' or not trigger or not ctx.atr:
            return None
        d, pct = trigger.get('distance_atr'), trigger.get('distance_pct')
        if d is None or pct is None:
            return None
        # near in BOTH units, or it is not soon: a big percentage move is a different
        # thesis however volatile the name, and a sub-noise gap is not a decision.
        if d > ALERT_NEAR_ATR or pct > ALERT_MAX_PCT:
            return None
        if d < ALERT_MIN_ATR or pct < ALERT_MIN_PCT:
            return None
        tier = ('imminent' if d <= ALERT_IMMINENT_ATR else
                'close' if d <= ALERT_CLOSE_ATR else 'near')

        gate = None
        if (ctx.sma150 and ctx.price < ctx.sma150
                and trigger['kind'] != 'ma150' and trigger['price'] < ctx.sma150):
            gate = {
                'price': jnum(ctx.sma150), 'what': 'the 150MA', 'what_he': 'ממוצע 150',
                'distance_pct': jnum((ctx.sma150 / ctx.price - 1) * 100),
                'distance_atr': jnum((ctx.sma150 - ctx.price) / ctx.atr),
            }

        d_en, d_he = self._days_phrase(d)
        tp = trigger['price']
        label = (f"{d_en} from {tp:.2f} ({trigger['what']}, +{pct:.1f}%) — worth an alert")
        label_he = (f"{d_he} מ-{tp:.2f} ({trigger['what_he']}, +{pct:.1f}%) — שווה להציב התראה")
        if gate:
            label += f"; the 150MA at {gate['price']:.2f} is still the real gate"
            label_he += f"; ממוצע 150 ב-{gate['price']:.2f} עדיין השער האמיתי"
        return {
            'near': True, 'tier': tier,
            'price': jnum(tp), 'what': trigger['what'], 'what_he': trigger['what_he'],
            'distance_pct': jnum(pct), 'distance_atr': jnum(d), 'atr_days': jnum(d),
            'gate': gate,
            'label': label, 'label_he': label_he,
        }

    # ── 2. The level the thesis lives on ──────────────────────────────────────

    def _hold_level(self, ctx, s: Signals) -> Optional[dict]:
        """
        "כל עוד שומרת מעל X — הטרייד פעיל / זה מצוין" is his single most-used sentence.
        It is the highest real structure under price: the level it just broke, the line
        holding it, or the 150MA. The stop then sits a hair under it (±0.5%).
        """
        price = ctx.price
        cands: list[tuple[float, str, str, str]] = []

        if s.nearest_sup and s.nearest_sup['price'] < price:
            b = _edge(s.nearest_sup, 'sup')
            flipped = bool(s.nearest_sup.get('flipped'))
            cands.append((b, 'level',
                          'the level it broke' if flipped else 'support',
                          'נקודת הפריצה' if flipped else 'התמיכה'))

        for t in (s.overlays or {}).get('trendlines') or []:
            if t.get('kind') == 'rising_lows' and not t.get('broke'):
                p = (t.get('p2') or {}).get('price')
                if p and p < price:
                    cands.append((float(p), 'line', 'the rising-lows line',
                                  'קו השפלים העולים'))

        if s.channel and s.channel.get('kind') == 'rising' and s.channel.get('lower'):
            lo = s.channel['lower']
            if lo < price:
                cands.append((float(lo), 'line', 'the lower rail of the channel',
                              'תחתית התעלה'))

        if ctx.sma150 and ctx.sma150 < price:
            cands.append((float(ctx.sma150), 'ma150', 'the 150MA', 'ממוצע 150'))

        if not cands:
            return None
        p, kind, en, he = max(cands, key=lambda c: c[0])
        dist = (price / p - 1) * 100 if p else 0.0
        return {
            'price': jnum(p), 'kind': kind, 'what': en, 'what_he': he,
            'dist_pct': jnum(dist),
            'label': f"as long as it holds above {p:.2f} ({en}) the trade is on",
            'label_he': f"כל עוד שומרת מעל {p:.2f} ({he}) — הטרייד פעיל",
        }

    # ── 3. The state machine ──────────────────────────────────────────────────

    def _state(self, ctx, s: Signals, trigger, hold) -> str:
        price, atr = ctx.price, ctx.atr
        vol_ok = s.vol.get('trend') != 'falling' or s.vol.get('falling_streak', 0) <= 2
        rl_broke = bool(s.dir_change and s.dir_change.get('rising_lows_broke'))

        # BROKEN — "כשאני מציין 'אין סט אפ' זה אומר שהסט אפ נגמר ... צריך לצאת מנקודת
        # הנחה שהסטופ שלכם קפץ". Losing the rising-lows line that WAS the structure, or
        # dropping back under a level that had just flipped to support, ends it.
        if s.lost_level and not ctx.above_150:
            return 'broken'
        if rl_broke and not ctx.above_150 and s.trend != 'uptrend':
            return 'broken'

        if not ctx.above_150 and s.trend == 'downtrend':
            turning = bool(s.dir_change and s.dir_change.get('turning'))
            if not turning:
                return 'avoid'

        # BREAKOUT NOW — a fresh break of a real level with volume behind it, AND
        # price still at that level. Once you are several ATR above the level you
        # broke, the entry is gone and buying here is the chase he refuses:
        # "לא צריך לרדוף" / "מקסימום איחרנו ביום יומיים". That case is `holding`.
        if ctx.above_150 and s.break_level and vol_ok:
            if (price - s.break_level) / atr <= EXTENDED_ATR:
                return 'breakout_now'

        at_floor = self._at_floor(ctx, s)

        # BUYERS AT THE LEVEL — "כניסת קונים באיזור הממוצע" (AVGO), "קפצה על קו
        # תמיכה/התנגדות מהעבר + נכנס ווליום + נר קונים חזק" (LMND). An entry in its own
        # right, no breakout required.
        if ctx.above_150 and at_floor and s.candle.get('found') and vol_ok:
            return 'buyers_at_level'

        # VALUE — the deep pullback back to the average. "מה זה מחיר טוב? קרוב לממוצע."
        if self._is_value(ctx, s):
            return 'value_pullback' if s.candle.get('found') else 'needs_buyers'

        # A turn candle ON the level is his "חכו לקונים" — interesting, not yet an
        # entry. It is the difference between "there's a doji here, why does that
        # matter?" and "buyers came in".
        if at_floor and s.candle.get('turn'):
            return 'needs_buyers'

        # AT THE TRIGGER — coiled right under the named price. This is not limited to
        # names already above the 150: when price is under it, the 150 IS the trigger,
        # and that is one of his most-posted setups — "עוברת את הממוצע 150. שפלים
        # עולים" (BULL), "ברגע שתעבור את ממוצע 150 ... זה אפילו טרייד יותר בשרני"
        # (ADBE), OKTA "✅ עברה את ממוצע 150 ... מתי נכנסים? פריצה מעל 88.17".
        if trigger and trigger['tier'] in ('at_hand', 'near') and s.trend != 'downtrend':
            return 'at_trigger'

        # HOLDING — already inside a move, above its structure, nothing new to do.
        if ctx.above_150 and hold and s.trend != 'downtrend':
            return 'holding'

        return 'nothing_yet'

    @staticmethod
    def _at_floor(ctx, s: Signals) -> bool:
        """Price is ON a floor: the nearest support or the 150 itself."""
        price, atr = ctx.price, ctx.atr
        if s.nearest_sup:
            b = _edge(s.nearest_sup, 'sup')
            if b and 0 <= (price - b) / atr <= NEAR_ATR * 2:
                return True
        return bool(ctx.sma150 and abs(price - ctx.sma150) / atr <= NEAR_ATR * 2)

    @staticmethod
    def _is_value(ctx, s: Signals) -> bool:
        """
        "growth at a reasonable price — מה זה מחיר טוב? קרוב לממוצע". Every value call he
        posts is AT the average: ARM "קרובה לממוצע 150", GLW "על הממוצע 150", KLAC
        "מתקרבת לממוצע 150". Being far off the high is never sufficient on its own.
        """
        price, atr = ctx.price, ctx.atr
        if s.off_high < OFF_HIGH_VALUE_PCT:
            return False
        near_ma = bool(ctx.sma150 and (
            ctx.above_150 or (ctx.sma150 - price) / atr <= VALUE_NEAR_150_ATR))
        if not near_ma:
            return False
        deep = s.fib_r >= 0.40 or s.golden
        at_150 = bool(ctx.sma150 and abs(price / ctx.sma150 - 1) <= 0.12)
        return bool(deep or at_150 or s.capitulation)

    # ── 4. Entry options — he routinely offers two ────────────────────────────

    def _options(self, ctx, s: Signals, state, trigger, hold) -> list:
        """
        TSLA: "אפשרות 1: כניסה וסטופ מתחת לקו $403 · אפשרות 2: לחכות לפריצה $455".
        MSTR: "או שנכנסים ושמים סטופ בקו או מחכים לפריצה". MUR, ONDS, OPEN the same.
        When price is sitting ON a structure with a trigger overhead, both are live and
        each carries its OWN stop and reward-to-risk — which is the whole point, because
        the breakout entry is higher but its stop is tighter.
        """
        price = ctx.price
        out = []

        entering_now = state in ('breakout_now', 'buyers_at_level', 'value_pullback')
        if entering_now:
            stop = self._stop(ctx, s, state, hold, entry=price)
            out.append(self._option('now', price, stop, ctx, s,
                                    'Enter here', 'כניסה כאן'))

        # The breakout option: valid whenever a trigger is overhead, within reach, and
        # there is somewhere for it to GO once cleared — a breakout into no target is
        # not a trade to plan, it is just a price.
        if trigger and trigger['tier'] in ('at_hand', 'near', 'moderate'):
            tp = trigger['price']
            room = any(t.get('price') and t['price'] > tp * 1.002 for t in s.targets)
            if room:
                stop = self._stop(ctx, s, 'breakout_now', hold, entry=tp, trigger=trigger)
                out.append(self._option(
                    'breakout', tp, stop, ctx, s,
                    f"Enter on a close above {tp:.2f} with volume",
                    f"כניסה בסגירה מעל {tp:.2f} עם ווליום"))

        # The pullback option: for a healthy but extended name, the entry is lower.
        if not entering_now and hold and (s.ext.get('stretched') or state == 'holding'):
            hp = hold['price']
            if hp < price:
                stop = self._stop(ctx, s, 'buyers_at_level', hold, entry=hp)
                out.append(self._option(
                    'pullback', hp, stop, ctx, s,
                    f"Wait for a pullback to {hp:.2f} ({hold['what']})",
                    f"להמתין לתיקון ל-{hp:.2f} ({hold['what_he']})"))
        return out

    def _option(self, kind, entry, stop, ctx, s, note, note_he) -> dict:
        rr, rr_first = self._rr(entry, stop.get('price'), s.targets)
        risk = stop.get('risk_pct')
        # The one number that can rank a 12%/10R home run against a 55%/1R scalp.
        p_win, exp_r = expectancy(stop.get('atr'), rr)
        return {
            'kind': kind, 'entry': jnum(entry), 'note': note, 'note_he': note_he,
            'risk_reward_first': rr_first,
            'stop': stop.get('price'), 'stop_what': stop.get('what'),
            'stop_what_he': stop.get('what_he'), 'stop_anchored': stop.get('anchored'),
            'risk_pct': risk, 'stop_atr': stop.get('atr'),
            'stop_position': stop.get('position_price'),
            'position_risk_pct': stop.get('position_risk_pct'),
            # sizing consequence of the stop width — see STOP_RISK_BUDGET_PCT
            'size_pct_of_account': stop.get('size_pct_of_account'),
            'atr_pct': stop.get('atr_pct'),
            'risk_reward': rr,
            # measured P(target before stop) and expectancy in R — see
            # config.expectancy. A LOW p_win on a high-R setup is the shape of a
            # home run, not a defect: 12% at 10R beats 55% at 1R.
            'p_win': p_win,
            'expectancy_r': exp_r,
        }

    @staticmethod
    def _rr(entry, stop, targets):
        """
        Reward-to-risk against the TOP of the ladder, not the first station.

        The number he quotes is the whole opportunity — "יש פה פוטנציאל של 25%" (PM),
        "תשואה פוטנציאלית של 50%" (KRE), "היעד לקאפ הוא $97" (IREN) — while the near
        station is only the first obstacle on the way ("היעד הראשוני הוא פתח הגאפ.
        אחרי זה סגירת הגאפ"). Measuring risk against a +2% first station produced
        nonsense like 0.3 on trades whose actual thesis was +30%.
        Returns (rr_to_thesis, rr_to_first_station).
        """
        if not (entry and stop) or entry <= stop or not targets:
            return None, None
        ups = [t['price'] for t in targets if t.get('price') and t['price'] > entry]
        if not ups:
            return None, None
        risk = entry - stop
        return jnum((max(ups) - entry) / risk), jnum((ups[0] - entry) / risk)

    # ── 5. The stop — anchored to whatever the thesis IS ──────────────────────

    def _stop(self, ctx, s: Signals, state, hold, entry, trigger=None) -> dict:
        """
        Priority order, straight from ~100 of his stop calls:
          breakout      → just under the level it broke ("סטופ מתחת לפריצה", LRCX "סטופ
                          מתחת לקו הפריצה ב-1%")
          buyers/line   → under that line ("סטופ מתחת לקו"), or the candle's own low
                          ("סטופ בנמוך של שישי" ARM, "סטופ בנמוך היומי" ANET/MSTR)
          value         → under the 150 ("סטופ מתחת לממוצע 150" GLW/AFRM/CVX)
          gap trade     → under the gap box ("סטופ מתחת לריבוע הגאפ" NVO)
          no structure  → by ATR ("סטופ לפי ATR" CBRS, post-IPO with nothing to lean on)
        and always "המחירים שאני כותב — אלו גם איזורי הסטופ ±חצי אחוז".
        """
        price, atr = ctx.price, ctx.atr
        cands: list[tuple[float, str, str]] = []

        if trigger and state == 'breakout_now':
            # once broken, the level itself is the floor ("סטופ מתחת לפריצה")
            cands.append((trigger['price'], 'the breakout level', 'רמת הפריצה'))
        # The lower edge of the wall being broken. This is the stop his own labelled
        # charts show (OKTA "86.88 - 88.17" → stop 86, SMCI "34.94 - 35.88" → stop
        # 34.5) and it applies before the break as well as after: the trade is wrong
        # the moment price is back UNDER the wall, not when it reaches some unrelated
        # low further down. Without it the tightest candidate available was typically
        # a swing low or the 150MA, which put our stop a median 1.52 ATR below the
        # line against his 0.43 over the same 404 posts.
        if trigger and trigger.get('floor') and trigger['floor'] < entry:
            cands.append((float(trigger['floor']), 'the bottom of the line it is breaking',
                          'תחתית הרמה הנפרצת'))
        if s.break_level and s.break_level < entry:
            cands.append((s.break_level, 'the level it broke', 'הרמה שנפרצה'))
        if hold and hold['price'] < entry:
            cands.append((hold['price'], hold['what'], hold['what_he']))
        if ctx.sma150 and ctx.sma150 < entry:
            cands.append((ctx.sma150, 'the 150MA', 'ממוצע 150'))
        g = self._gap_below(s.overlays, entry, atr)
        if g:
            cands.append((g, 'the gap box', 'ריבוע הגאפ'))
        # The signal candle's own low is a stop in its own right, and he reaches for it
        # constantly: "סטופ בנמוך של שישי" (ARM), "סטופ בנמוך היומי 135.3" (ANET),
        # "תראו איזה פטיש יפה בסיום היום ... סטופ בנמוך היומי" (MSTR).
        lo = s.candle.get('low')
        if lo and lo < entry:
            cands.append((float(lo), "the signal candle's low", 'הנמוך של נר הקונים'))
        if s.recent_low and s.recent_low < entry:
            cands.append((float(s.recent_low), 'the recent low', 'הנמוך האחרון'))

        # Among real structures he takes the TIGHTEST one that still gives the trade
        # room to breathe — "סטופ די קרוב" (CHRD), "סטופ קרוב למניעת טעויות" (BBAI),
        # "מקסימום נכנסים שוב" (BWXT/SHAK: worst case we re-enter). But never inside a
        # single average day, or ordinary noise takes you out of a setup that is fine.
        noise_floor = entry - STOP_NOISE_ATR * atr
        usable = [c for c in cands if c[0] <= noise_floor]
        anchored = bool(usable)
        # …with one exemption, and it is his: the bottom of the wall being broken is
        # a stop even when it sits inside a single average day. The noise floor
        # protects against a stop with no meaning behind it — a round number, a
        # yesterday's low. This one has the whole wall behind it, so "back under the
        # wall" is a real answer to "am I wrong", not noise. Without the exemption
        # the floor candidate was filtered out in exactly the cases it was added
        # for: his median stop is 0.43 ATR, i.e. BELOW our 0.5 ATR noise floor, so
        # the rule was vetoing his own placement
        floor = trigger.get('floor') if trigger else None
        if floor and float(floor) < entry:
            fl = float(floor)
            if not usable or fl > max(c[0] for c in usable):
                usable = [c for c in cands if c[0] == fl] or usable
                anchored = True
        if usable:
            anchor, anchor_en, anchor_he = max(usable, key=lambda c: c[0])
        elif cands:
            # everything real is inside the noise band — keep the structure but push
            # the stop out to the edge of it
            _, anchor_en, anchor_he = max(cands, key=lambda c: c[0])
            anchor, anchored = noise_floor, True
        else:
            # "סטופ לפי ATR" — nothing structural to lean on at all (CBRS, post-IPO)
            anchor = entry - max(1.5 * atr, entry * 0.02)
            anchor_en, anchor_he = 'ATR distance (no structure below)', 'מרחק ATR (אין מבנה מתחת)'

        stop_price = anchor * (1 - STOP_BUFFER)
        risk = (entry / stop_price - 1) * 100 if stop_price > 0 else None
        d_atr = (entry - stop_price) / atr if atr else None
        # "מעל 288 עם סטופ קרוב יחסית למי שבטרייד. מי שמחזיק לטווח ארוך - סטופ רחב
        # יותר" (AAPL) — the same setup carries two stops depending on what you are
        # doing with it, and a swing position must not be choked (KRE).
        pos_stop = entry - (entry - stop_price) * STOP_POSITION_WIDEN
        # A stop is a % number and an ATR number, and confusing the two is how a
        # volatile name gets mis-sized. ONDS' 16.8% stop is NOT four times "worse"
        # than NVDA's 2.4% one — measured in what the stock actually does daily they
        # are 2.0 ATR vs 0.6 ATR, i.e. the tight one is the volatile stock's. The %
        # is what sets POSITION SIZE; the ATR is what says whether ordinary noise
        # takes you out. Carry both, plus the sizing consequence, so the reader is
        # never comparing a 2%-ATR stop to an 8%-ATR one in raw percent.
        size_factor = (STOP_RISK_BUDGET_PCT / risk) if risk and risk > 0 else None
        return {
            'price': jnum(stop_price), 'anchored': anchored, 'atr': jnum(d_atr),
            'risk_pct': jnum(risk),
            'position_price': jnum(pos_stop),
            'position_risk_pct': jnum((entry / pos_stop - 1) * 100) if pos_stop > 0 else None,
            # what fraction of the account this position can be, to keep the loss at
            # the stop equal to STOP_RISK_BUDGET_PCT of the account
            'size_pct_of_account': jnum(size_factor * 100) if size_factor else None,
            'atr_pct': jnum(ctx.atr_pct),
            'what': f'{anchor_en} (±0.5%)', 'what_he': f'{anchor_he} (±0.5%)',
        }

    @staticmethod
    def _gap_below(overlays, price, atr):
        # only while the box is still NEAR price — an unfilled gap ~30% below is
        # history, not a stop reference
        cands = [g['near'] for g in (overlays or {}).get('gaps') or []
                 if g.get('dir') == 'up' and g.get('near') and g['near'] < price
                 and (price - g['near']) <= GAP_STOP_MAX_ATR * (atr or 0)]
        return max(cands) if cands else None

    # ── 6. The action ─────────────────────────────────────────────────────────

    @staticmethod
    def _action(state, s: Signals, earn, options) -> str:
        # "רק חכו לדיווח התוצאות מחר - פשוט לא רוצה לשכוח את הסט אפ" (PM) — the setup
        # still stands, the entry is deferred.
        entering = state in ('breakout_now', 'buyers_at_level', 'value_pullback')
        if entering and earn is not None and earn <= 1:
            return 'wait_event'
        # Stretched is a modifier, not a veto: "מתוחה אבל ... כל עוד שומרת מעל 19 היא
        # בסדר" (CRML). It never blocks holding — it blocks CHASING.
        if entering and s.ext.get('stretched'):
            return 'wait_pullback'
        if entering:
            return 'enter'
        return {
            'at_trigger':   'wait_trigger',
            'needs_buyers': 'wait_buyers',
            'holding':      'hold',
            'nothing_yet':  'watch',
            'broken':       'out',
            'avoid':        'avoid',
        }[state]

    # ── 7. The grade — setup / trigger / risk ─────────────────────────────────

    def _grade(self, ctx, s: Signals, state, trigger, options, action, small_cap, earn):
        """
        Three axes, because his own A-grade sentence has exactly three clauses:
        "מעל נקודת הפריצה (trigger). מעל ממוצע 150 (setup). קרוב לממוצע (risk — the stop
        is right there). מה עוד נותר לבקש" (GEV).
        """
        B = GRADE_BUDGET
        price, atr = ctx.price, ctx.atr

        # Every scoring decision below also files a short clause, so the sentence
        # under the letter is composed from the SAME arithmetic that produced it and
        # can never drift from it. `w` is the weight the clause carries in that
        # sentence: for a term that scored, the points it earned; for a miss, the
        # negative of what it forfeited. See `_grade_sentence`.
        notes: list[tuple[str, float, str, str]] = []

        def note(axis, w, en, he):
            notes.append((axis, float(w), en, he))

        d150 = ((price / ctx.sma150 - 1) * 100) if ctx.sma150 else 0.0

        # ── SETUP: is there a real structure here? ─────────────────────────────
        setup = 0.0
        # Being above the 150 is the anchor — but "קרוב לממוצע" is a separate clause of
        # his A-grade sentence, and it is the one that decides whether a stop exists at
        # all. A great chart 5 ATR above its average is the CRD case: "המניה מעולה,
        # פשוט רחוקה כרגע מהממוצעים" — excellent, and not a trade from here.
        if ctx.above_150:
            # Three-way, not two: "close to the average" is the A-grade clause, but
            # 15% above and 52% above are not the same chart and used to differ by a
            # single point out of a hundred. FTNT (+52%) and CRWD (+42%) scored the
            # same here as F (+9%) and TEAM (+9%) — the exact pair the reader called
            # out. See FAR_FROM_MA_PCT for his wording and the drawdown measurement.
            if self._near_ma(ctx):
                setup += 12
                note('setup', 12, f'above the 150MA and close to it ({d150:+.0f}%)',
                     f'מעל ממוצע 150 וקרובה אליו ({d150:+.0f}%)')
            elif self._far_from_ma(ctx):
                setup += 3
                note('setup', -9, f'{d150:+.0f}% above the 150 — no tight stop from up here',
                     f'{d150:+.0f}% מעל ממוצע 150 — אין מכאן סטופ צמוד')
            else:
                setup += 7
                note('setup', 7, f'above the 150MA ({d150:+.0f}%)',
                     f'מעל ממוצע 150 ({d150:+.0f}%)')
            # "she crossed the average - correct. My problem is she has run so much in
            # recent days… 6 consecutive green days" (CRWD). Reclaiming the 150 is a
            # trigger by the method's own rules, and he still passed, because the run
            # into it WAS the move. Charged here rather than on the trigger axis: the
            # trigger is real, it is the entry that has gone bad.
            if s.ext.get('ran_hot'):
                setup -= 5
                note('setup', -5,
                     f"ran {s.ext.get('run_pct') or 0:+.0f}% in the last few days — the run into "
                     f"the trigger was the move",
                     f"רצה {s.ext.get('run_pct') or 0:+.0f}% בימים האחרונים — הריצה אל הטריגר "
                     f"הייתה המהלך")
            # "קצת מתוחה" — the band below his cap. He still takes these ("אתם לא
            # מאחרים" AAPL) but flags the entry ("זהירות עם הכניסה" LUNR), so it
            # costs a little and shows up in the argument rather than capping.
            if s.ext.get('mild'):
                setup -= 2
                note('setup', -2, f'a bit stretched from the average ({d150:+.0f}%)',
                     f'קצת מתוחה מהממוצע ({d150:+.0f}%)')
        elif ctx.sma150 and (ctx.sma150 - price) / atr <= NEAR_ATR:
            setup += 9
            note('setup', -3, f'just under the 150MA ({d150:+.0f}%) — not above it yet',
                 f'ממש מתחת לממוצע 150 ({d150:+.0f}%) — עוד לא מעליו')
        elif s.dir_change and s.dir_change.get('turning'):
            setup += 5
            note('setup', -7, 'below the 150MA, but starting to change direction',
                 'מתחת לממוצע 150, אבל מתחילה לשנות כיוון')
        else:
            note('setup', -12, 'below the 150MA — the anchor of the whole method is missing',
                 'מתחת לממוצע 150 — העוגן של כל השיטה חסר')
        if s.trend == 'uptrend':
            setup += 10
            note('setup', 10, 'rising highs and rising lows', 'שיאים ושפלים עולים')
        elif s.trend == 'sideways':
            setup += 5
            note('setup', -5, 'sideways — no directional structure yet',
                 'דשדוש — עוד אין מבנה כיווני')
        else:
            note('setup', -10, 'lower highs and lower lows', 'שיאים ושפלים יורדים')
        has_rl = bool(s.dir_change and any(
            st['done'] for st in s.dir_change['stages'] if st['key'] == 'rising_lows'))
        if has_rl:
            setup += 4
            # Only call it a LINE when the chart actually draws one — the stage is
            # also satisfied by rising weekly lows with no drawable segment.
            rl = drawn_line(s.overlays, 'rising_lows')
            if rl:
                note('setup', 4, f"the rising-lows line is holding ({rl.get('touches') or 0} touches)",
                     f"קו השפלים העולים מחזיק ({rl.get('touches') or 0} נגיעות)")
            else:
                note('setup', 4, 'rising lows on the weekly', 'שפלים עולים בשבועי')
        if s.pattern:
            setup += 4
            note('setup', 4, f'{s.pattern[0]} on the chart', f'{s.pattern[1]} על הגרף')
        if s.vol.get('trend') == 'rising':
            setup += 5
            note('setup', 5, 'volume expanding into the move', 'ווליום מתרחב לתוך המהלך')
        elif s.vol.get('trend') == 'flat':
            setup += 2.5
        else:
            note('setup', -5,
                 "volume isn't expanding into the move — without it this isn't a breakout",
                 'הווליום לא מתרחב לתוך המהלך — ובלי זה זו לא פריצה')
        if s.candle.get('found'):
            setup += 5
            note('setup', 5, s.candle.get('label') or 'buyers candle',
                 s.candle.get('label_he') or 'נר קונים')
        # An unfilled gap-up left below price. He treats one as a liability — "I am
        # aware it has a gap below, THAT is why there is a stop" (ALAB), "if it turns
        # it can go toward the gap" (TSLA), quoting 80% (TSLA) / 96%-in-90-days (VIX)
        # fill rates. Measured over 40k entries above the 150, the sign is the other
        # way round: E(2R) is +0.279 with a gap inside 2 ATR, +0.230 at 2-5, +0.167
        # beyond, against +0.079 with no gap at all — monotonic in closeness, and the
        # measured fill rate is 36% in 120 bars, not 80-96%. A gap left behind is
        # evidence of the momentum event that made it, not a debt. His instinct is
        # not wrong about the risk though: drawdown IS worse (-14.1% vs -13.0%),
        # which is why the gap box stays a stop anchor (`_gap_below`) — the cost
        # belongs on the stop, the edge belongs here. Small, and bounded by the axis.
        # Kept deliberately small and short-range. A gap sits below most charts in an
        # uptrend, so a wider or larger bonus is not a discriminator — it is a
        # constant added to the whole universe, which just redefines the letters: at
        # +3/+2/+1 it re-inflated CSCO from B83 back to A86 and lifted every name 1-3
        # points. The measured edge is +0.2R of expectancy and it is concentrated in
        # the near band, so it is priced as a nudge that can break a tie, not as a
        # term that moves grades on its own.
        gap_atr = self._gap_below_atr(s.overlays, price, atr)
        if gap_atr is not None and gap_atr < 5:
            setup += 2.0 if gap_atr < 2 else 1.0
        setup = min(setup, B['setup'])

        # ── TRIGGER: how close is the thing that starts the trade? ─────────────
        if state in ('breakout_now', 'buyers_at_level', 'value_pullback'):
            trig = float(B['trigger'])          # it is happening now
            note('trigger', 30, 'the trigger is happening right now', 'הטריגר קורה ממש עכשיו')
        elif trigger:
            trig = {'at_hand': 24.0, 'near': 17.0, 'moderate': 9.0, 'far': 3.0}[trigger['tier']]
            tp, td, tpc = trigger['price'], trigger['distance_atr'], trigger['distance_pct']
            if trigger['tier'] == 'at_hand':
                note('trigger', 24, f"{trigger['what']} at {tp:.2f} is right overhead ({td:.1f} ATR)",
                     f"{trigger['what_he']} ב-{tp:.2f} ממש מעל הראש ({td:.1f} ATR)")
            elif trigger['tier'] == 'near':
                note('trigger', 17, f"the trigger {tp:.2f} is {tpc:+.0f}% away",
                     f"הטריגר {tp:.2f} במרחק {tpc:+.0f}%")
            elif trigger['tier'] == 'moderate':
                note('trigger', -8, f"the trigger {tp:.2f} is still {tpc:+.0f}% away",
                     f"הטריגר {tp:.2f} עוד {tpc:+.0f}% מכאן")
            else:
                note('trigger', -14, f"the breakout is far off — {tpc:+.0f}% from here",
                     f"הפריצה רחוקה — {tpc:+.0f}% מכאן")
        else:
            trig = 6.0                          # blue sky: nothing overhead to clear
            note('trigger', 6, 'nothing overhead left to clear', 'אין מעל הראש מה לפרוץ')
        if state in ('broken', 'avoid'):
            trig = min(trig, 5.0)

        # ── RISK: the decisive axis — is the stop tight, real and obvious? ─────
        best = self._best_option(options, action)

        # How far the thesis target is, and how often a target that far is actually
        # reached. Measured over 62k real levels across 70 names x 5y: 4-6 ATR is
        # reached 72.7% of the time, 6-9 ATR 53.0%, 9-13 ATR only 24.8%, 13-20 ATR
        # 6.2%. Hoisted above both the R/R term and the time term because both need
        # it — R/R states the size of the prize, this states the odds of collecting.
        thesis_atr = thesis_hit = None
        if best and s.targets and state not in ('broken', 'avoid', 'nothing_yet'):
            _e = best.get('entry') or price
            _ups = [t['price'] for t in s.targets if t.get('price') and t['price'] > _e]
            if _ups and ctx.atr_pct:
                thesis_atr = (max(_ups) / _e - 1) * 100 / ctx.atr_pct
                _d, thesis_hit = time_to_target(thesis_atr, ctx.atr_pct)

        risk_score, stop_flag = 6.0, None       # no plan yet = unknown, not condemned
        if best:
            d = best.get('stop_atr')
            pct = best.get('risk_pct')
            # Drop the "(±0.5%)" his stop notation carries — it is right for the plan
            # row, but inside a flowing sentence it is a parenthesis too many.
            sw = (best.get('stop_what') or 'the structure').replace(' (±0.5%)', '')
            swh = (best.get('stop_what_he') or 'המבנה').replace(' (±0.5%)', '')
            sp = best.get('stop')
            if d is not None and pct is not None:
                if d > STOP_WIDE_ATR or pct > STOP_MAX_RISK_PCT:
                    risk_score, stop_flag = 0.0, 'wide'
                    note('risk', -16, f'no sane stop from here — {pct:.0f}% of the position',
                         f'אין סטופ הגיוני מכאן — {pct:.0f}% מהכניסה')
                elif STOP_IDEAL_ATR[0] <= d <= STOP_IDEAL_ATR[1]:
                    risk_score = 16.0           # exactly what he wants
                    note('risk', 16, f'a tight stop {d:.1f} ATR under {sw} ({sp:.2f})',
                         f'סטופ צמוד {d:.1f} ATR מתחת ל{swh} ({sp:.2f})')
                elif d < STOP_NOISE_ATR:
                    # Kept as-is. The tempting change here is to waive the complaint
                    # when the stop is anchored on a wall, on the grounds that his own
                    # stops sit a median 0.43 ATR under the line and are plainly not
                    # "noise". That may well be true, but the outcome evidence offered
                    # for it did not survive its own control — see STOP_IDEAL_ATR — and
                    # his practice alone is an argument, not a measurement. Left alone
                    # until there is one.
                    risk_score, stop_flag = 10.0, 'tight'
                    note('risk', -6,
                         f'the stop sits inside a single average day ({d:.1f} ATR) — ordinary '
                         f'noise takes you out',
                         f'הסטופ בתוך יום ממוצע אחד ({d:.1f} ATR) — רעש רגיל יוציא אותך')
                else:
                    risk_score = 12.0 if d <= 3.0 else 7.0
                    stop_flag = 'loose' if d > 3.0 else None
                    note('risk', -4 if d <= 3.0 else -9,
                         f'the stop is wide — {pct:.0f}% / {d:.1f} ATR from the entry',
                         f'הסטופ רחב — {pct:.0f}% / {d:.1f} ATR מהכניסה')
            if best.get('stop_anchored'):
                risk_score += 6.0               # under a real structure, not an ATR guess
            else:
                note('risk', -6, 'nothing structural below — the stop is an ATR guess',
                     'אין מבנה מתחת — הסטופ הוא הערכת ATR')

            # NOT graded here: the thickness of the wall being broken
            # (`trigger['floor']` gives it). It is a genuine standalone signal —
            # measured on forward 20-day return over 395 of his posts, a band of
            # 0.15-0.35 ATR returns +5.82% / 65% win against +1.06% / 44% for a
            # sub-0.15 ATR hairline — and it is drawn on the chart for that reason.
            # But adding it to this axis made the LETTER worse, not better:
            #     A bucket's forward return   +4.88%  ->  +3.59% (bonus + penalty)
            #                                          ->  +3.65% (penalty only)
            #     A-vs-D spread                6.92pp ->   5.07pp
            # i.e. the information is already inside what the axis scores, and
            # paying for it twice flattens the top of the scale. See
            # GRADE_BAND_IDEAL_ATR for the full bucket table.
            rr = best.get('risk_reward')
            if rr is not None:
                # Below 1 the trade risks more than the whole thesis is worth — that is
                # not a bad trade, it is not a trade, so it takes points off rather
                # than merely earning few.
                #
                # The top of this scale used to stop at `rr >= 3`, which made a 3R and
                # a 10R setup score identically. Measured (config.expectancy), the
                # highest-expectancy shape in this method is a TIGHT stop with a FAR
                # target — 1.0 ATR/10R pays +0.40R at a 12% win rate, beating every
                # 2-3R combination — so a ceiling at 3 hid precisely the trades worth
                # preferring. Extended, but only rewarded when the stop is genuinely
                # tight: a 10R target hung off a 3 ATR stop is the timeout trap
                # (-0.25R measured), not a home run, and `d` gates it below.
                #
                # …and scored on EXPECTED R (rr x the odds of reaching that target),
                # not the headline ratio. Raw R/R quotes a prize without saying how
                # often it is collected, so a thesis 9-13 ATR out (reached 24.8% of
                # the time) earned exactly what one 4-6 ATR out (72.7%) did. That is
                # the FTNT/PANW/CRWD case the ratio could not see: their whole reward
                # case is a measured-move projection ~9.5 ATR overhead — FTNT's R/R to
                # its last REAL chart level is 0.86 — while F and TEAM carry the same
                # ratio to real levels at ~5.8 ATR, ~3x more likely to pay. He prices
                # it the same way: "each one of these is a resistance and is expected
                # to serve as a place for a slight correction" (BX), and the potential
                # runs only "up to the lows-line which will serve as resistance" (CELH).
                rr_eff = rr * thesis_hit if thesis_hit is not None else rr
                # rr_eff is linear in rr, so an extreme ratio survives any
                # proportional discount: CSCO reached 4.63 as 16.77 x 0.276 and F
                # reached 4.20 as 7.53 x 0.558 — the same score for a 1-in-4 shot and
                # a coin-flip-plus. The top brackets therefore also require the thesis
                # to be one the market actually reaches; measured, 9-13 ATR out pays
                # 24.8% of the time, and full marks for that is the "I don't see the
                # potential" complaint in one number. CSCO's 16.77 is itself built on
                # a 0.71 ATR stop — under STOP_IDEAL_ATR's 0.75 floor — which the stop
                # bracket above already docked 4 points for, so without this the same
                # too-tight stop is punished once and paid for twice.
                odds_ok = thesis_hit is None or thesis_hit >= TARGET_ODDS_FLOOR
                rr_pts = (11.0 if rr_eff >= 4.0 and odds_ok and d is not None and d <= 2.0 else
                          10.0 if rr_eff >= 3.0 and odds_ok and d is not None and d <= 2.5 else
                          8.0 if rr_eff >= 2.0 else 6.0 if rr_eff >= 1.5 else
                          4.0 if rr_eff >= 1.0 else 1.0 if rr_eff >= 0.6 else -6.0)
                risk_score += rr_pts
                if rr < 1.0:
                    note('risk', -10,
                         f'risking more than the whole thesis is worth (R/R {rr:.1f})',
                         f'מסכנים יותר ממה שכל התזה שווה (יחס {rr:.1f})')
                elif rr_pts >= 10.0:
                    note('risk', rr_pts, f'reward-to-risk {rr:.1f} to a target the market really reaches',
                         f'יחס סיכוי/סיכון {rr:.1f} ליעד שהשוק באמת מגיע אליו')
                elif thesis_hit is not None and not odds_ok:
                    note('risk', -5,
                         f'the thesis is a long shot — a target that far is reached '
                         f'{thesis_hit*100:.0f}% of the time',
                         f'התזה רחוקה — יעד במרחק כזה מושג ב-{thesis_hit*100:.0f}% מהמקרים')
                else:
                    note('risk', rr_pts, f'reward-to-risk {rr:.1f}', f'יחס סיכוי/סיכון {rr:.1f}')
        # ── TIME: the half of "reward" the R/R ratio cannot see ────────────────
        # R/R says how much per unit of risk, never how long the money is tied up for
        # — so it scores a 60-day grind and a 12-day move identically. Measured, the
        # distance to the first station in ATR sets both the wait AND the odds
        # (config.time_to_target), so one term covers both. Bounded to
        # ±TIME_EFFICIENCY_MAX and never able to lift a capped state (the caps below
        # are applied with min() afterwards).
        eff_days = eff = None
        # Only where there is a live thesis to be timed. On a setup that is over,
        # "the target is close" is not a virtue — it is the MSTR trap the growth
        # model used to print ("+30% ≈ 4 days, fast" under a headline of "get out"),
        # and without this gate it was lifting META/ADP/ZS out of F.
        # measured against the same target `risk_reward` is, so the pair reads as one
        # sentence: this much reward per unit risk, in this long
        if thesis_atr is not None:
            eff_days, _hit = time_to_target(thesis_atr, ctx.atr_pct)
            if eff_days <= TIME_FAST_DAYS:
                eff = TIME_EFFICIENCY_MAX
            elif eff_days >= TIME_SLOW_DAYS:
                eff = -TIME_EFFICIENCY_MAX
            elif eff_days <= TIME_MEDIAN_DAYS:
                eff = TIME_EFFICIENCY_MAX * (TIME_MEDIAN_DAYS - eff_days) / \
                      (TIME_MEDIAN_DAYS - TIME_FAST_DAYS)
            else:
                eff = -TIME_EFFICIENCY_MAX * (eff_days - TIME_MEDIAN_DAYS) / \
                      (TIME_SLOW_DAYS - TIME_MEDIAN_DAYS)
            # "Fast" is only a virtue if there is something to collect. A thesis
            # target half an ATR overhead is quick because the ladder is nearly
            # exhausted (AMD: 3 days, ~0.5 ATR of room) — speed there is a
            # symptom of no upside, not of a good trade. R/R already punishes it;
            # this stops the time term from paying for it at the same moment.
            # Penalties stay unconditional — a slow thesis is slow regardless.
            thesis_rr = best.get('risk_reward')
            if eff > 0 and (thesis_rr is None or thesis_rr < 1.0):
                eff = 0.0
            # …and a stretched name does not get paid for being quick either: "you can
            # see it is starting to be stretched — that means from here the rises
            # should be slower / consolidation" (GOOGL). The curve is fitted on all
            # bars above the 150 and so understates the wait for an extended one.
            if eff > 0 and (s.ext.get('stretched') or s.ext.get('ran_hot')):
                eff = 0.0
            risk_score += eff
            if eff > 0:
                note('risk', eff, f'the thesis is ~{eff_days:.0f} trading days out — quick at this volatility',
                     f'היעד ~{eff_days:.0f} ימי מסחר מכאן — מהיר בתנודתיות הזו')
            elif eff < 0:
                note('risk', eff, f'the target is ~{eff_days:.0f} trading days out — a long wait',
                     f'היעד ~{eff_days:.0f} ימי מסחר מכאן — המתנה ארוכה')

        # NOTE — an "overhead congestion" penalty was built here from his
        # "הבעיה זה ההתנגדויות מעל הראש" (CRWD) and BX's "each of these is a
        # resistance", and REMOVED after measuring it. The target ladder is built out
        # of resistance levels, so counting walls between the entry and the thesis
        # charges a stock for having a ladder at all: it took TEAM (three real
        # stations — the shape this method wants) from A90 to B83, while F escaped
        # untouched only because its ladder is a single far target. That is backwards.
        # Re-reading the sources, BX is descriptive — the stations are where the move
        # PAUSES, which is why the ladder exists — and the CRWD remark is about a doji
        # that had not cleared anything, a state `nothing_yet`/`needs_buyers` already
        # scores. Do not reintroduce without a measurement that keeps TEAM above F.
        risk_score = max(0.0, min(risk_score, B['risk']))

        score = setup + trig + risk_score
        idx = next(i for i, lo in GRADE_BANDS if score >= lo)

        # ── His hard ceilings ─────────────────────────────────────────────────
        # `bound` records whether a ceiling actually MOVED the letter, not merely
        # that it applied. The sentence under the grade leads with the binding one,
        # because that is literally what set the letter — a cap listed but not
        # binding explains nothing.
        caps = []

        def cap(key, en, he, ceiling):
            nonlocal idx
            hit = ceiling < idx
            caps.append((key, en, he, hit))
            idx = min(idx, ceiling)

        if state == 'broken':
            # A broken setup on a chart that is still structurally healthy is a D —
            # wait for it to reclaim. Reserve F for a broken setup in a downtrend,
            # where there is nothing left to come back to.
            cap('broken', 'the setup is over — assume the stop was hit',
                'הסט אפ נגמר — להניח שהסטופ קפץ',
                0 if s.trend == 'downtrend' else 1)
        if state == 'avoid':
            cap('downtrend', 'below the 150MA in a downtrend',
                'מתחת לממוצע 150 במגמה יורדת', 1)
        if state == 'nothing_yet':
            # "עוד לא עשתה שום דבר" (PGR) is by definition a watchlist item, so it
            # tops out at C — "on the watchlist, not ripe". Without this the risk
            # axis scores a hypothetical breakout entry's stop and lifts a chart with
            # no setup on it to a B, directly contradicting its own headline.
            cap('no_setup', "it hasn't done anything yet — watchlist only",
                'עוד לא עשתה שום דבר — רשימת מעקב בלבד', 2)
        if stop_flag == 'wide':
            cap('stop_wide', 'no sane stop from here — that is not a stop in this method',
                'אין סטופ הגיוני מכאן — זה לא סטופ בשיטה הזו', 1)
        if s.ext.get('severe'):
            # Clear of BOTH the 150 and the 200 — "מהממוצעים", plural. This is the
            # one he declines rather than merely flags: "מתוחה ורחוקה מהממוצע. האם זו
            # נקודת כניסה מתאימה כרגע - אני לא בטוח" (RDDT, on a cup-and-handle he
            # otherwise liked). One average gone is a caveat; both is not an entry.
            cap('stretched_far',
                'far from BOTH the 150 and the 200 — not an entry point here',
                'רחוקה משני הממוצעים (150 ו-200) — זו לא נקודת כניסה', 2)
        elif s.ext.get('stretched'):
            cap('stretched', 'stretched from the 150 — do not chase, wait for the pullback',
                'מתוחה מממוצע 150 — לא לרדוף, להמתין לתיקון', 3)
        if earn is not None and earn <= 1:
            cap('earnings', 'earnings land within a day — he does not open into a report',
                'דיווח תוצאות בתוך יום — לא נכנסים לפני דיווח', 3)
        if small_cap:
            caps.append(('small_cap', 'under $1B — outside the 150 method, speculative',
                         'מתחת ל-1 מיליארד — מחוץ לשיטה, ספקולטיבי', idx > 0))
            idx = max(0, idx - 1)

        # The letter must not contradict the recommendation. An unconditional "enter"
        # with no ceiling cannot read as a failing chart.
        if action == 'enter' and not caps:
            idx = max(idx, 2)

        lo, hi = GRADE_BAND_RANGE[idx]
        score = max(lo, min(score, hi))
        shown = int(score)
        why_en, why_he = self._grade_sentence(notes, caps, GRADES[idx])
        return GRADES[idx], {
            'score': float(shown),
            # Two sentences saying WHY this letter, composed from the notes filed by
            # the scoring above — see `_grade_sentence`.
            'summary': why_en, 'summary_he': why_he,
            'components': [
                {'key': 'setup', 'label': 'Setup', 'label_he': 'מבנה',
                 'got': jnum(setup), 'max': B['setup'],
                 'detail': 'structure on the chart', 'detail_he': 'המבנה על הגרף'},
                {'key': 'trigger', 'label': 'Trigger', 'label_he': 'טריגר',
                 'got': jnum(trig), 'max': B['trigger'],
                 'detail': ('the trigger is happening now'
                            if state in ('breakout_now', 'buyers_at_level', 'value_pullback')
                            else trigger['label'] if trigger else 'nothing overhead to clear'),
                 'detail_he': ('הטריגר קורה עכשיו'
                               if state in ('breakout_now', 'buyers_at_level', 'value_pullback')
                               else trigger['label_he'] if trigger else 'אין מה לפרוץ מעל')},
                {'key': 'risk', 'label': 'Risk / stop', 'label_he': 'סיכון / סטופ',
                 'got': jnum(risk_score), 'max': B['risk'],
                 'detail': (f"stop {best['risk_pct']:.1f}% / {best['stop_atr']:.1f} ATR"
                            if best and best.get('risk_pct') is not None else 'no stop defined yet'),
                 'detail_he': (f"סטופ {best['risk_pct']:.1f}% / {best['stop_atr']:.1f} ATR"
                               if best and best.get('risk_pct') is not None else 'אין סטופ מוגדר')},
            ] + ([
                # not a fourth axis — a named, bounded adjustment already counted
                # inside `risk`, shown separately so the letter stays auditable
                {'key': 'time', 'label': 'Time to target',
                 'label_he': 'זמן ליעד',
                 'got': jnum(eff), 'max': TIME_EFFICIENCY_MAX, 'adjustment': True,
                 'detail': f"~{eff_days:.0f} trading days to the thesis target",
                 'detail_he': f"~{eff_days:.0f} ימי מסחר ליעד"},
            ] if eff is not None else []),
            'caps': [{'key': k, 'label': e, 'label_he': h, 'bound': bool(b)}
                     for k, e, h, b in caps],
        }

    # ── 7b. The grade, in two sentences ───────────────────────────────────────

    @staticmethod
    def _lc(text: str) -> str:
        """Lowercase a label's first letter so it reads mid-sentence — unless it
        opens on an acronym ("MA bounce", "ATR distance"), where the capital is
        part of the word rather than sentence case."""
        return text[0].lower() + text[1:] if len(text) > 1 and text[1].islower() else text

    @classmethod
    def _join(cls, parts: list, he: bool) -> str:
        """
        List join, in each language's own grammar.

        Hebrew attaches the conjunction to the word (ו + מחיר). A maqaf goes in when
        the next character is not a Hebrew letter — a price or a Latin ticker — and
        a signed number gets "וגם" instead, because "ו-+60%" is unreadable. English
        keeps the Oxford comma: these clauses contain "and" internally often enough
        ("rising highs and rising lows") that dropping it produces a genuine garden
        path.
        """
        if not parts:
            return ''
        if not he:
            parts = [cls._lc(p) for p in parts]
        if len(parts) == 1:
            return parts[0]
        head, last = parts[:-1], parts[-1]
        if not he:
            return ', '.join(head) + (', and ' if len(head) > 1 else ' and ') + last
        c = last[:1]
        vav = ('ו' + last if 'א' <= c <= 'ת' else
               'וגם ' + last if c in '+-' else 'ו-' + last)
        return ', '.join(head) + ', ' + vav

    def _grade_sentence(self, notes, caps, grade) -> tuple:
        """
        The two sentences under the letter, in his shape.

        Every post he writes states what the chart HAS and then the one thing it is
        missing — "מעל נקודת הפריצה. מעל ממוצע 150. קרוב לממוצע. מה עוד נותר לבקש"
        (GEV) when nothing is missing, "המניה מעולה, פשוט רחוקה כרגע מהממוצעים" (CRD)
        and "הבעיה היחידה היא הווליום" (OKLO) when something is. This composes the
        same two beats out of the notes the scoring itself filed, so the sentence can
        never argue with the number above it. That is the same guarantee `_why` gets
        by calling `_near_ma` rather than re-deriving the test — the alternative,
        lifting sentences out of `reasons.py`, is a SECOND opinion, and a second
        opinion is free to contradict the first.

        On a chart whose problems outweigh its merits the order inverts: leading a
        failing stock with three nice things it has, then one small caveat, reads as
        an endorsement of a name the app is telling you to stay away from.
        """
        # Strongest first WITHIN each axis, but the axes themselves in his order —
        # structure, then the trigger, then the stop. That is the running order of
        # his own A-grade sentence ("מעל ממוצע 150. קרוב לממוצע. מעל נקודת הפריצה"),
        # and it is also the only order that reads: sorting the whole list by weight
        # alone opened F with "the trigger is happening right now", which is the
        # punchline, before saying anything about the chart it happened on.
        axis_order = {'setup': 0, 'trigger': 1, 'risk': 2}
        pos = sorted([n for n in notes if n[1] > 0],
                     key=lambda n: (axis_order.get(n[0], 3), -n[1]))
        neg = sorted([n for n in notes if n[1] < 0], key=lambda n: n[1])
        # A ceiling that actually moved the letter outranks any single deduction:
        # it IS the reason the grade is what it is.
        binding = next((c for c in caps if c[3]), None)

        def clause(items, n, he):
            return self._join([i[3] if he else i[2] for i in items[:n]], he)

        # A bound ceiling always leads. Opening a broken F with three things the
        # chart still has going for it and only then mentioning that the setup is
        # over reads as an endorsement of a stock the app is telling you to leave.
        best_pos = max((n[1] for n in pos), default=0)
        good_first = binding is None and ((not neg) or best_pos >= -neg[0][1])
        if good_first:
            lead_en, lead_he = clause(pos, 3, False), clause(pos, 3, True)
            if binding:
                tail_en = f'What holds the grade back: {binding[1]}.'
                tail_he = f'מה שמוריד את הציון: {binding[2]}.'
            elif neg:
                tail_en = f'What holds the grade back: {neg[0][2]}.'
                tail_he = f'מה שמוריד את הציון: {neg[0][3]}.'
            else:
                # his literal A-grade closer, earned only when nothing scored against
                risk = next((n for n in pos if n[0] == 'risk'), None)
                tail_en = ((risk[2] + ' — ') if risk else '') + 'what more is there to ask for.'
                tail_he = ((risk[3] + ' — ') if risk else '') + 'מה עוד נותר לבקש.'
            if not lead_en:
                return tail_en, tail_he
            return f'{lead_en[0].upper()}{lead_en[1:]}. {tail_en}', f'{lead_he}. {tail_he}'

        # ...and the inverted order, for a chart that is mostly problems
        bad = ([(None, 0, binding[1], binding[2])] if binding else []) + \
              [n for n in neg if not binding or n[2] != binding[1]]
        lead_en, lead_he = clause(bad, 2, False), clause(bad, 2, True)
        if pos:
            tail_en = f'Still going for it: {clause(pos, 2, False)}.'
            tail_he = f'מה שכן עובד לטובתה: {clause(pos, 2, True)}.'
        else:
            tail_en, tail_he = 'There is nothing here to trade.', 'אין פה על מה לסחור.'
        return f'{lead_en[0].upper()}{lead_en[1:]}. {tail_en}', f'{lead_he}. {tail_he}'

    @staticmethod
    def _near_ma(ctx) -> bool:
        """
        "קרוב לממוצע" — the clause that decides whether a stop exists at all.

        Distance from the average is judged in PERCENT, not ATR, because that is what
        it looks like on his chart (he reads them on a log scale — "גרף בלוגריתמי,
        לינארי זה מפחיד מדי"), and being 42% above the 150 is visibly extended no
        matter how volatile the name is. ATR stays the unit for stop WIDTH, where the
        question is a different one: how many average days is this stop away.
        """
        if not ctx.sma150:
            return False
        pct = (ctx.price - ctx.sma150) / ctx.sma150
        return bool(pct <= 0.15 or (ctx.price - ctx.sma150) / ctx.atr <= EXTENDED_ATR)

    @staticmethod
    def _gap_below_atr(overlays, price, atr):
        """
        Distance to the nearest unfilled gap-up below price, in ATR (None if there is
        none). Separate from `_gap_below`, which answers a different question — that
        one is looking for a stop anchor and so only cares about a box still within
        GAP_STOP_MAX_ATR; the measured edge here runs well past that, so the distance
        is returned raw and banded by the caller.
        """
        if not atr:
            return None
        cands = [g['near'] for g in (overlays or {}).get('gaps') or []
                 if g.get('dir') == 'up' and g.get('near') and g['near'] < price]
        return (price - max(cands)) / atr if cands else None

    @staticmethod
    def _far_from_ma(ctx) -> bool:
        """
        "מתוחה ורחוקה מהממוצע … האם זו נקודת כניסה מתאימה כרגע - אני לא בטוח" (RDDT).

        The far end of the same spectrum `_near_ma` reads. Percent for the same
        reason it uses percent — this is about how the chart LOOKS, and a name half
        again above its own 150 looks extended however volatile it is. Kept as a
        scoring penalty rather than a cap: measured, these still hit their R targets
        at the same rate, they just make you sit through roughly twice the drawdown,
        so it costs points as an entry without condemning the stock.
        """
        if not ctx.sma150:
            return False
        return bool((ctx.price - ctx.sma150) / ctx.sma150 > FAR_FROM_MA_PCT)

    @staticmethod
    def _best_option(options, action=None):
        """
        The option the grade — and the headline — is judged on: the one the reader is
        actually being told to take. Grading a "wait for the pullback" call on the
        breakout option's stop is how VRTX ended up rated F while its own text said
        "in the move, holding" and its pullback entry carried a 2 ATR stop and 3.3 R/R.
        """
        if not options:
            return None
        want = {'enter': 'now', 'wait_trigger': 'breakout', 'wait_event': 'breakout',
                'wait_pullback': 'pullback', 'hold': 'pullback'}.get(action)
        if want:
            match = next((o for o in options if o['kind'] == want), None)
            if match:
                return match
        order = {'now': 0, 'breakout': 1, 'pullback': 2}
        return sorted(options, key=lambda o: order.get(o['kind'], 3))[0]

    # ── 8. The write-up — his shape, his length ───────────────────────────────

    def _report(self, ctx, s: Signals, state, action, trigger, hold, options, grade,
                breakdown, earn, small_cap, alert=None) -> dict:
        """
        [call] → [read] → [✅ why] → [invalidation] → [caveats].
        Short lines, real prices, no essay. Hebrew is primary.
        """
        price = ctx.price
        best = self._best_option(options, action)

        # ── the call: one line, with the number ────────────────────────────────
        if action == 'enter' and best:
            call = f"Enter around {best['entry']:.2f}, stop {best['stop']:.2f}."
            call_he = f"כניסה סביב {best['entry']:.2f}, סטופ {best['stop']:.2f}."
        elif action == 'wait_trigger' and trigger:
            call = f"No entry yet — alert at {trigger['price']:.2f}, enter on a close above it with volume."
            call_he = f"אין כניסה עדיין — התראה על {trigger['price']:.2f}, כניסה בסגירה מעליו עם ווליום."
        elif action == 'wait_buyers':
            call = "It reached the zone — wait for a buyers' candle before entering."
            call_he = "הגיעה לאזור — להמתין לנר קונים לפני כניסה."
        elif action == 'wait_pullback' and hold:
            call = f"Don't chase — wait for a pullback toward {hold['price']:.2f}."
            call_he = f"לא לרדוף — להמתין לתיקון לכיוון {hold['price']:.2f}."
        elif action == 'wait_event':
            call = f"Setup stands — wait for the report ({earn}d), don't open into it."
            call_he = f"הסט אפ עומד — להמתין לדיווח ({earn} ימים), לא נכנסים לפניו."
        elif action == 'hold' and hold:
            call = f"In the move — no new entry here. It has to hold above {hold['price']:.2f}."
            call_he = f"בתוך המהלך — לא כניסה חדשה כאן. צריכה לשמור מעל {hold['price']:.2f}."
        elif action == 'out':
            call = "The setup is over — assume the stop was hit and move to the next trade."
            call_he = "הסט אפ נגמר — להניח שהסטופ קפץ ולעבור לטרייד הבא."
        elif action == 'avoid':
            ma = f" ({ctx.sma150:.2f})" if ctx.sma150 else ''
            call = f"Not a buy — wait for it to base and reclaim the 150MA{ma}."
            call_he = f"לא קונים — להמתין שתתבסס ותחזור מעל ממוצע 150{ma}."
        else:
            call = "Nothing here yet — watchlist and an alert."
            call_he = "אין פה כלום עדיין — מעקב והתראה."

        # ── the read: what the chart IS, one sentence ──────────────────────────
        read, read_he = self._read(ctx, s, state)

        # ── why: his ✅ list ───────────────────────────────────────────────────
        why = self._why(ctx, s, trigger)

        # ── caveats: the ⚠ line(s) ─────────────────────────────────────────────
        warn = []
        for c in breakdown['caps']:
            warn.append({'en': c['label'], 'he': c['label_he']})
        if earn is not None and 1 < earn <= EARNINGS_SOON_DAYS:
            warn.append({'en': f'Earnings in {earn} days', 'he': f'דיווח תוצאות בעוד {earn} ימים'})
        if s.momentum >= 5:
            warn.append({'en': f'{s.momentum} green days in a row — expect a rest',
                         'he': f'{s.momentum} ימים ירוקים ברצף — לצפות להתקררות'})

        # "מתקרב להכרעה" — say it out loud on a chart whose call is otherwise
        # negative, because "no trade" and "nothing to watch" are not the same
        # statement and only one of them is true here.
        watch = watch_he = None
        if alert and action not in ('enter',):
            lead_en = {'imminent': 'Close to the decision',
                       'close': 'Approaching the decision',
                       'near': 'Getting close'}[alert['tier']]
            lead_he = {'imminent': 'ממש קרובה להכרעה',
                       'close': 'מתקרבת להכרעה',
                       'near': 'מתחילה להתקרב'}[alert['tier']]
            watch = f"{lead_en} — {alert['label']}."
            watch_he = f"{lead_he} — {alert['label_he']}."

        return {
            'call': call, 'call_he': call_he,
            'read': read, 'read_he': read_he,
            'watch': watch, 'watch_he': watch_he,
            'why': why,
            'invalidation': hold['label'] if hold else None,
            'invalidation_he': hold['label_he'] if hold else None,
            'warnings': warn,
        }

    @staticmethod
    def _read(ctx, s: Signals, state) -> tuple:
        """One sentence describing the chart, in the register he writes in."""
        p = ctx.price
        if state == 'breakout_now':
            lvl = f" {s.break_level:.2f}" if s.break_level else ''
            return (f"Broke the level{lvl} on volume and is holding above it, above the 150MA.",
                    f"פרצה את הרמה{lvl} עם ווליום ושומרת מעליה, מעל ממוצע 150.")
        if state == 'buyers_at_level':
            return (f"Buyers stepped in at the level ({s.candle.get('label','')}), the 150MA underneath.",
                    f"נכנסו קונים על הרמה ({s.candle.get('label_he','')}), ממוצע 150 מתחת.")
        if state == 'value_pullback':
            bits, bits_he = [], []
            if s.fib_r:
                bits.append(f"retraced {s.fib_r*100:.0f}% of the whole move")
                bits_he.append(f"תיקנה {s.fib_r*100:.0f}% מכל המהלך")
            bits.append(f"{s.off_high:.0f}% off its high")
            bits_he.append(f"{s.off_high:.0f}% מהשיא")
            bits.append("back at the 150MA")
            bits_he.append("חזרה לממוצע 150")
            return (", ".join(bits) + ". This is a value investment.",
                    ", ".join(bits_he) + ". זו השקעת ערך.")
        if state == 'at_trigger':
            return ("Coiled right under its breakout price — nothing to do until it clears it.",
                    "מתכנסת ממש מתחת למחיר הפריצה — אין מה לעשות עד שתעבור אותו.")
        if state == 'needs_buyers':
            # reachable two ways: a deep pullback into value, or simply a turn candle
            # sitting on a level. Saying "down 4% and back at the average" about a
            # stock at its highs reads as nonsense.
            if s.off_high >= OFF_HIGH_VALUE_PCT:
                return (f"Down {s.off_high:.0f}% and back at the average, but no buyers' candle yet.",
                        f"ירדה {s.off_high:.0f}% וחזרה לממוצע, אבל עוד לא ראינו נר קונים.")
            return ("On the level with a turn candle, but buyers haven't confirmed it yet.",
                    "על הרמה עם נר שינוי כיוון, אבל הקונים עוד לא אישרו.")
        if state == 'holding':
            return ("Above the 150MA and holding its structure — the move is intact.",
                    "מעל ממוצע 150 ושומרת על המבנה — המהלך תקין.")
        if state == 'broken':
            lvl = f" {s.lost_level:.2f}" if s.lost_level else ''
            return (f"It just lost the level{lvl} it was built on, and it is under the 150MA.",
                    f"בדיוק איבדה את הרמה{lvl} שעליה נבנה הטרייד, ומתחת לממוצע 150.")
        if state == 'avoid':
            return ("Below the 150MA with lower highs and lower lows.",
                    "מתחת לממוצע 150 עם שיאים ושפלים יורדים.")
        return (f"Trading at {p:.2f} with no setup formed yet.",
                f"נסחרת ב-{p:.2f} בלי סט אפ שנוצר עדיין.")

    @staticmethod
    def _why(ctx, s: Signals, trigger) -> list:
        """
        His ✅ list — the actual format he posts (DKNG, OKTA, TSLA, AFRM, EW, ORCL).
        Only facts that are TRUE get a ✅; the ones that matter and are missing get a ✕,
        because "what's missing" is half of his read.
        """
        out = []

        def add(ok, en, he):
            out.append({'ok': bool(ok), 'en': en, 'he': he})

        if ctx.sma150:
            d = (ctx.price / ctx.sma150 - 1) * 100
            add(ctx.above_150, f"Above the 150MA ({d:+.1f}%)", f"מעל ממוצע 150 ({d:+.1f}%)")
            # same test the grade uses, so the checklist can never disagree with the
            # score it is meant to explain
            near = Judgement._near_ma(ctx)
            if ctx.above_150:
                add(near, "Close to the 150 — the stop is right there" if near
                    else "Far from the 150 — no tight stop from here",
                    "קרוב לממוצע 150 — הסטופ ממש שם" if near
                    else "רחוקה מממוצע 150 — אין סטופ צמוד מכאן")
        add(s.trend == 'uptrend', 'Rising highs and lows', 'שיאים ושפלים עולים')
        if s.dir_change:
            has_rl = any(st['done'] for st in s.dir_change['stages'] if st['key'] == 'rising_lows')
            ok = has_rl and not s.dir_change['rising_lows_broke']
            # Only say "line" when there IS one on the chart. The stage can also be
            # satisfied by rising WEEKLY lows with no drawable segment (he reads the
            # sequence on the weekly — "שבועי, אני מדבר איתכם כרגע על שבועי"), and
            # printing "the rising-lows line is holding" over a chart with no line
            # drawn on it is the reader's most direct reason to distrust the panel.
            rl = drawn_line(s.overlays, 'rising_lows')
            if ok and rl:
                n = rl.get('touches') or 0
                add(True, f'Rising-lows line holding ({n} touches)',
                    f'קו שפלים עולים מחזיק ({n} נגיעות)')
            elif ok:
                add(True, 'Rising lows on the weekly', 'שפלים עולים בשבועי')
            else:
                add(False, 'Rising-lows line holding', 'קו שפלים עולים מחזיק')
        add(s.vol.get('trend') == 'rising', 'Volume rising', 'ווליום עולה')
        add(s.candle.get('found'), s.candle.get('label', 'Buyers candle'),
            s.candle.get('label_he', 'נר קונים'))
        if s.pattern:
            add(True, s.pattern[0], s.pattern[1])
        if s.golden:
            add(True, 'In the 61.8% golden pocket', 'בגולדן פוקט (61.8%)')
        elif s.fib_r >= 0.40:
            add(True, f'Deep retracement ({s.fib_r*100:.0f}%)', f'תיקון עמוק ({s.fib_r*100:.0f}%)')
        if trigger:
            add(False, f"Still under {trigger['price']:.2f} ({trigger['what']})",
                f"עדיין מתחת ל-{trigger['price']:.2f} ({trigger['what_he']})")
        return out[:7]
