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
    EVENT_BASIS,
    EVENT_BOUNCE,
    EVENT_CAPITULATION,
    EVENT_CONFIRM_BARS,
    EVENT_DIR_CHANGE,
    EVENT_FRESH_BARS,
    EVENT_HARD_BREAK,
    EVENT_MA150_RECLAIM,
    EVENT_NONE,
    EVENT_PRIORITY,
    EVENT_RETEST,
    EVENT_SOFT_BREAK,
    EVENT_STALE_BARS,
    EVENT_STALE_FLOOR,
    EVENT_WAIT_FAR,
    EVENT_WAIT_NEAR,
    EVENT_WAIT_SPAN_ATR,
    EVENT_TURNING,
    EVENT_UNDER_WALL,
    HEADROOM_CLEAR_ATR,
    HEADROOM_CLOSE_ATR,
    HEADROOM_HARD_TOUCHES,
    HEADROOM_MAX,
    HEADROOM_OK_ATR,
    HEADROOM_TIGHT_ATR,
    ALERT_IMMINENT_ATR,
    ALERT_MAX_PCT,
    ALERT_MIN_ATR,
    ALERT_MIN_PCT,
    ALERT_NEAR_ATR,
    CUP_RIM_DEPTH_ATR,
    CUP_RIM_NEAR_ATR,
    EARNINGS_SOON_DAYS,
    CHASE_PAST_TRIGGER_ATR,
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
    STOP_SUPPORT_MAX_ATR,
    STOP_WIDE_ATR,
    REWARD_PRIZE_CAP_PCT,
    REWARD_PRIZE_FLOOR_PCT,
    REWARD_EV_FULL,
    REWARD_EV_GOOD_FRAC,
    REWARD_EV_MAX,
    REWARD_EV_THIN_FRAC,
    REWARD_EV_NEGATIVE,
    REWARD_GAP_NEAR_ATR,
    REWARD_OFF_HIGH_BIG_PCT,
    REWARD_OFF_HIGH_REAL_PCT,
    REWARD_PRIZE_MAX,
    REWARD_ROOM_MAX,
    TIME_EFFICIENCY_MAX,
    TIME_GLACIAL_DAYS,
    TIME_SLOW_DAYS,
    TRIGGER_AT_HAND_ATR,
    TRIGGER_NEAR_ATR,
    TRIGGER_ENTERING_OVERHEAD,
    TRIGGER_MAX_SPAN_ATR,
    TRIGGER_REACH_ATR,
    TRIGGER_REANCHOR_TOUCH_MULT,
    TRIGGER_ZONE_ATR,
    VALUE_NEAR_150_ATR,
    VCP_MIN_LEGS,
    VCP_STRUCTURE_BONUS,
    VOL_SPIKE_FACTOR,
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
    'turning':         ('Bearish to bullish — the turn is confirmed',
                        'שינוי כיוון — המהפך מאושר'),
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

# ── The 4-bucket headline a client panel can key a single button off ───────────
# `action` already carries the real decision — this is not a second opinion, it is
# the same 9 values folded into the shape a top-level UI needs: one word, not nine,
# and not the letter grade either (a B69 "enter" and an A92 "enter" are the same
# instruction with different confidence, which is what the grade next to it is
# for). `out` reads as AVOID rather than its own bucket because both tell the
# reader the same thing here — do not be in this name — and a 5th bucket for one
# state would just move the ambiguity from "9 values" to "is OUT different from
# AVOID enough to matter", which for a top-level button it is not.
HEADLINE_ACTION = {
    'enter': 'ENTER', 'wait_trigger': 'WAIT', 'wait_buyers': 'WAIT',
    'wait_pullback': 'WAIT', 'wait_event': 'WAIT', 'hold': 'WAIT',
    'watch': 'WATCH', 'out': 'AVOID', 'avoid': 'AVOID',
}

GRADE_MEANING = {
    'A': ("Everything lines up — above the 150, near it, trigger in hand, tight stop, "
          "and real room to grow.",
          'הכל מסתדר — מעל ה-150, קרוב אליו, טריגר ביד, סטופ צמוד, ומקום אמיתי לגדול.'),
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
    # a fresh, qualifying Volatility Contraction Pattern (setups._detect_vcp) —
    # a run of successive tightening, quieting-volume legs, distinct from `base`
    # (one flat box, `_long_base`) and from a cup/handle's fixed geometry.
    vcp: Optional[dict] = None
    momentum: int = 0
    # structure
    res_levels: list = field(default_factory=list)
    sup_levels: list = field(default_factory=list)
    nearest_res: Optional[dict] = None
    nearest_sup: Optional[dict] = None
    broke_desc: bool = False
    break_level: Optional[float] = None   # a level just broken upward, if any
    # bars since that break, so the EVENT axis can decay a stale one — see
    # micha._bars_since_cross
    break_age: Optional[int] = None
    # {'bars', 'price'} when price has closed back above the 150 and stayed there
    ma150_reclaim: Optional[dict] = None
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


def _rating(score: float) -> int:
    """
    The 0-100 grade score as a 1-10 rating.

    Ten buckets rather than five letters, because five could not order a watchlist:
    a 246-name sweep put 85 in C and 74 in B, so two thirds of the universe sat in
    two indistinguishable piles. Straight division rather than its own band table on
    purpose — a second set of boundaries is a second thing that can disagree with the
    letter, and the letter's bands are load-bearing (every `cap()` is written in band
    indices). Floors at 1: nothing is rated zero, a chart that is simply not a trade
    still has a rating, and `state`/`action` are where "stay away" is said.
    """
    return max(1, min(10, int(round(float(score) / 10.0))))


def _confirmation(breakdown: dict) -> dict:
    """
    unconfirmed / pending / confirmed — how proven the EVENT behind the grade is.

    Built for the Radar view, which surfaces names by urgency and needs a single
    word for "how solid is this" that a card-grid can badge without the reader
    opening the full breakdown. Reuses `breakdown['event_key']`/`['event_age']` —
    the SAME winning candidate `_event` already picked for the grade — so this can
    never disagree with the axis that scored it; it is a label on an existing
    decision, not a second opinion.

    Bands are EVENT_CONFIRM_BARS (see config for the measurement: forward 20-day
    excess turns from negative to positive between 8 and 12 bars old, not at 5).
    'unconfirmed' covers both "nothing happened yet" (`event_key` in
    waiting/none — the axis is pricing proximity, not an event) and a past-events
    candidate the axis itself already dropped as too old
    (`event_age is not None` would never reach here past EVENT_STALE_BARS,
    because `_event` excludes it from `cands` entirely — so age has already been
    filtered before this function ever sees it).
    """
    key = breakdown.get('event_key')
    age = breakdown.get('event_age')
    if key in (None, 'waiting', 'none') or age is None:
        return {'status': 'unconfirmed', 'age': None,
                'label': 'No confirmed event yet', 'label_he': 'עדיין אין אירוע מאושר'}
    if age < EVENT_CONFIRM_BARS:
        return {'status': 'pending', 'age': age,
                'label': f'Pending confirmation ({age}d)',
                'label_he': f'ממתין לאישור ({age} ימים)'}
    return {'status': 'confirmed', 'age': age,
            'label': f'Confirmed ({age}d)', 'label_he': f'מאושר ({age} ימים)'}


def _headline_action(action: str, alert: Optional[dict]) -> str:
    """
    ENTER / READY / WAIT / WATCH / AVOID.

    Owner's directive (2026-08-22): a stock a fraction of a daily range from its
    trigger must not resolve to the same flat "WAIT" as one that is nowhere close
    — a reader treats a blanket WAIT as inactive and the near ones are exactly
    the setups worth active monitoring today. `alert` already answers "how
    close" in the gated, volatility-normalized way this codebase always measures
    proximity (ALERT_IMMINENT_ATR / ALERT_CLOSE_ATR, both ATR- AND percent-
    gated — see config.py) — READY reuses those SAME tiers rather than a fresh
    1.5%-flat threshold, so this can never disagree with the alert card the
    reader is already looking at. `imminent`/`close` cover "≤1 ATR", which is
    the tighter of the two thresholds named ("1.5% or 1 ATR"); the ATR gate is
    the one degrading gracefully across a 2%-ATR mega-cap and a 10%-ATR miner,
    which a flat percent does not.

    Deliberately narrow: only WAIT-family actions upgrade. `enter` is already
    the strongest word this scale has; `watch`/`avoid` have nothing pending to
    be imminent about.
    """
    head = HEADLINE_ACTION[action]
    if head == 'WAIT' and alert and alert.get('tier') in ('imminent', 'close'):
        return 'READY'
    return head


def _macro_target(breakdown: dict) -> Optional[dict]:
    """
    The full pattern projection, clearly labeled — not the near station the
    ladder leads with.

    Owner's directive (2026-08-22), reversing an earlier answer in the same
    conversation: the panel's headline "Target" should be the realistic full
    reward — cup measured move, Fibonacci extension, the record, whichever is
    farthest — not `targets[0]`, the nearest resistance. Both numbers are real
    and both stay on the panel (the ladder still shows the near station first,
    labelled its own way); this is a NEW field naming the other one, not a
    replacement, since "what do I have to clear next" and "what is this worth if
    it works" are different questions and he answers both — "היעד הראשוני הוא
    פתח הגאפ. אחרי זה סגירת הגאפ" names the near one; "יש פה פוטנציאל של 25%"
    names this one.

    Reuses `breakdown['thesis_price']`/`['thesis_pct']` — the SAME number
    `_opportunity_top` already computes and the REWARD axis's prize term is
    already scored against — so the panel's headline number and the grade's own
    reward reasoning can never point at two different prices.
    """
    price, pct = breakdown.get('thesis_price'), breakdown.get('thesis_pct')
    if price is None or pct is None:
        return None
    return {
        'price': price, 'pct': pct,
        'label': f'full pattern target: {price:.2f} ({pct:+.0f}%)',
        'label_he': f'יעד מלא לתבנית: {price:.2f} ({pct:+.0f}%)',
    }


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
        action = self._action(ctx, state, s, earn, options)
        grade, breakdown = self._grade(ctx, s, state, trigger, options, action,
                                       small_cap, earn)
        confirmation = _confirmation(breakdown)
        macro_target = _macro_target(breakdown)
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
            # the 4-value bucket a top-level panel button keys off — see
            # HEADLINE_ACTION for why 9 states collapse to 4 without inventing a
            # second opinion of the decision `action` already made
            'headline_action': _headline_action(action, alert),
            'confirmation': confirmation,
            'macro_target': macro_target,
            'grade': grade, 'grade_score': breakdown['score'],
            # the headline number — see `_rating`. `grade`/`grade_score` stay for the
            # scan filters, the caps machinery and `grade_if_break`'s delta.
            'rating': breakdown['rating'], 'rating_max': 10,
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
        s2 = s
        if trigger.get('kind') == 'ma150' and not ctx.above_150:
            ctx2 = replace(ctx, price=tp * 1.001, above_150=True,
                           above_200=bool(ctx.sma200 and tp >= ctx.sma200))
            # `ctx2` now says the reclaim happened; `s` still doesn't. `_event()`
            # reads the reclaim off `s.ma150_reclaim`, a Signals field this shim
            # never touched, so the EVENT axis — the largest single budget, 33 of
            # 100 — projected the EXACT SAME "nothing yet, the 150MA is right
            # overhead" text after the break as before it (confirmed on INTU:
            # 14.03/33 both sides, byte-identical). The projection's own
            # `structure` term moved (+2.78, the near_ma bonus) while the axis
            # that should carry most of "you just cleared the anchor of the whole
            # method" sat frozen — which is most of why a chart 0.4 ATR from a
            # clean reclaim projected a 2-point move instead of the ~26 a fresh
            # `ma150_reclaim` event is worth. Shimmed the same shape the real
            # signal returns (`micha._ma150_reclaim`): 0 bars old, at today's
            # average — a reclaim that just happened, which is exactly the
            # mechanical consequence being projected.
            s2 = replace(s, ma150_reclaim={'bars': 0, 'price': ctx.sma150})
        else:
            ctx2 = replace(ctx, price=tp * 1.001)

        g2, bd2 = self._grade(ctx2, s2, 'breakout_now', trigger, [brk], 'enter',
                              small_cap, earn)
        delta = bd2['score'] - breakdown['score']
        # Tracked on the RATING, not the letter: the rating is what the panel leads
        # with, and a 1-10 move is the change a reader actually sees. On letters this
        # missed every projection that moved a full point without crossing a band
        # boundary, which after the four-axis rework is most of them.
        moved = bd2['rating'] != breakdown['rating']
        return {
            'grade': g2, 'score': bd2['score'], 'delta': jnum(delta),
            'rating': bd2['rating'], 'rating_delta': bd2['rating'] - breakdown['rating'],
            'moves': moved,
            'at_price': jnum(tp),
            'components': bd2['components'],
            'caps': bd2['caps'],
            # the same two-sentence explanation, for the projected letter
            'why': bd2['summary'], 'why_he': bd2['summary_he'],
            'label': (f"clears {tp:.2f} → {bd2['rating']}/10"
                      if moved else f"clears {tp:.2f} → still {bd2['rating']}/10"),
            'label_he': (f"פורצת {tp:.2f} → {bd2['rating']}/10"
                         if moved else f"פורצת {tp:.2f} → נשארת {bd2['rating']}/10"),
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
                    # A descending-highs line carries a real touch history — the
                    # pivots it was fitted through — and it has to be handed over as
                    # a `wall`, not as None.
                    #
                    # This was the CMG bug (owner's report): a stock sitting under
                    # BOTH a hard horizontal at 37.16 and a descending trendline, and
                    # every "is a real wall in the way" check in this file keys on
                    # `trigger['wall']['touches']`. With None there, the state machine
                    # would not defer, the EVENT axis's honesty ceiling would not
                    # fire, and the grade was free to price an entry at spot as
                    # though the road above were open. "If the stock is facing a hard
                    # resistance line or trendline above, we want it to be ABOVE it
                    # so the entrance will be clean" — a line is a line, whichever
                    # way it runs. The `kind` is carried so the copy can name it
                    # correctly rather than calling a diagonal a level.
                    cands.append((float(p), 'trendline', 'the descending-highs line',
                                  'קו השיאים היורדים',
                                  {'touches': t.get('touches') or 2,
                                   'strength': t.get('strength'),
                                   'kind': 'trendline'}))

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
        zone_touches = (wall or {}).get('touches') or 0

        def describe(r):
            return {'strength': r.get('strength'), 'touches': r.get('touches'),
                    'quality': r.get('quality'), 'flipped': bool(r.get('flipped')),
                    'freshness': r.get('freshness')}

        # ascending: the zone chains upward one wall at a time, so an unsorted list
        # would silently skip a rung and merge across a gap it should have stopped at
        for r in sorted((r for r in (s.res_levels or []) if r.get('price')),
                        key=lambda r: r['price']):
            rp = r.get('price')
            if rp <= zone_top:
                continue
            # ── Adjacency is EDGE to EDGE, not centre to centre ───────────────
            # A level is a band everywhere else in this file: `_trigger` quotes
            # `zone_top` as the price to clear, anchors the stop under `zone_lo`'s
            # own bottom, and `_headroom` measures the room to the band's LOWER
            # edge on the explicit argument that "a rally does not run to the
            # middle of a supply band before meeting sellers, it meets them at the
            # edge". This test was the last one still comparing midpoints, and the
            # two readings disagree exactly where it matters — on a wide band.
            #
            # ADSK is the clearest case: the quoted trigger 254.30 is a TWO-touch
            # level whose own band runs 246.08-262.52, and a 23-touch wall sits at
            # 260.07 with a band starting at 255.00 — 0.07 ATR above the quote, and
            # physically INSIDE the quoted level's band. Centre to centre they are
            # 0.60 ATR apart, so the gate skipped it and the engine named the
            # 2-touch line. Same shape on ODFL (0-touch cup rim quoted, 32-touch
            # wall's band 0.29 ATR above, centres 0.69 apart) and MSFT (0-touch rim,
            # 10-touch wall, band 0.19 / centres 0.61 — missed by one hundredth).
            bot = float(r.get('bottom') or rp)
            step = (bot - zone_top) / atr
            if step > TRIGGER_ZONE_ATR:
                continue                     # a genuinely separate wall, not this one
            tch = r.get('touches') or 0
            # Two conditions, not one: the gap to the last admitted wall (a cluster
            # is walls sitting on top of each other), AND the total width of what
            # has been merged (see TRIGGER_MAX_SPAN_ATR — without it the first
            # condition chains, and three distinct walls become one 10%-wide "zone").
            if (float(rp) - zone_lo) / atr <= TRIGGER_MAX_SPAN_ATR:
                zone_top, absorbed = float(rp), absorbed + 1
                # the strongest wall in the zone is the one being described
                if tch > zone_touches:
                    zone_touches, wall, kind = tch, describe(r), 'level'
            elif tch >= max(zone_touches * TRIGGER_REANCHOR_TOUCH_MULT,
                            HEADROOM_HARD_TOUCHES):
                # ── Re-anchor rather than quote the weaker line ────────────────
                # The span cap is doing its job — this wall is too far from the
                # BOTTOM of the zone to be part of it — but the thing it is
                # protecting turns out to be a barely-tested line, and dropping a
                # well-defended wall to keep quoting that line names the wrong
                # price. IREN is the owner's case: the trigger read "break above
                # 43.41" while a 19-touch band ran 43.64-46.00, i.e. one wall to
                # any human eye, split because `zone_lo` was pinned to a ZERO-touch
                # consolidation edge at 42.31 that ate the whole 0.6 ATR budget.
                #
                # Measured over 159 names: 14 (9%) quoted a trigger with a stronger
                # wall inside a third of an ATR above it, and in ten of the fourteen
                # the quoted line had 0-2 touches against 10-45 on the wall above
                # (AIG: 2 touches quoted, a 45-touch wall 1.1% overhead).
                #
                # The absolute floor is HEADROOM_HARD_TOUCHES, not MIN_LEVEL_TOUCHES.
                # The multiple alone collapses when the quoted line has NO touch
                # history at all (a cup rim, a trendline, the 150MA): zone_touches
                # is 0, so `0 x 2` lets the weakest thing that still counts as a
                # level move the quote. Measured, that is exactly where it went
                # wrong — NXPI re-anchored 4.7% higher onto a TWO-touch wall and
                # lost 24 points; ALGN, FANG and AMZN did the same onto 3-touch
                # walls. Only a wall he would actually call "התנגדות מעל הראש" —
                # one price has been rejected from repeatedly — may overrule the
                # line the engine picked first.
                #
                # This cannot reintroduce the IONQ failure TRIGGER_MAX_SPAN_ATR was
                # added for. There the chain ran 47.90 (20 touches) -> 49.03 (18) ->
                # 50.87 (13): each rung WEAKER than the last, so the "materially
                # stronger" test below never fires and the span cap still stops it.
                # Re-anchoring only ever moves the quote onto a better-defended line.
                zone_lo = zone_top = float(rp)
                absorbed, zone_touches, wall, kind = 0, tch, describe(r), 'level'
                p = float(rp)
                # the quote now describes a DIFFERENT line, so the copy has to be
                # rebuilt from it — otherwise a re-anchor onto a plain wall keeps
                # calling itself "the breakout price" because the line it replaced
                # happened to be flipped
                en = 'the breakout price' if wall['flipped'] else 'resistance'
                he = 'מחיר הפריצה' if wall['flipped'] else 'ההתנגדות'
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

        # ── BEARISH TO BULLISH — the turn, confirmed ──────────────────────────
        # "שינוי כיוון" with all four dictated stages done, the breakout included.
        # `_direction_change` only sets `confirmed` on a chart that WAS weak
        # (`applicable`), so this cannot fire on a healthy name in continuation, and
        # a confirmed turn already above the 150 still falls through to
        # `breakout_now` below exactly as before. What it changes is the case that
        # had no exit: below the 150, the two `broken` rules and `avoid` fired first
        # and every such name was capped at D or F. That is where this setup LIVES —
        # a stock only turns from bearish to bullish while it is still under its
        # averages, and the owner names it as one of the three events worth entering
        # on.
        #
        # Measured over 245 names before this existed: 28 had a confirmed direction
        # change, graded 14 C / 7 B / 4 F / 3 D with zero A and a median score dead
        # on the universe median. Of the 67 in `broken`, 8 had 3+ stages done. And
        # on the 1,098-call forward test, `broken` names returned +3.66% excess
        # against `breakout_now`'s -4.88% — the dead-end bucket was not full of dead
        # stocks.
        turned = bool(s.dir_change and s.dir_change.get('confirmed'))

        # ── A below-150 chart is not automatically finished ───────────────────
        # `turned` above is the strict case (all four stages, breakout included) and
        # it is rare. This is the loose one, and it exists because a test against his
        # own last three weeks of posts said it had to. Of 17 calls where his text
        # gave a clear instruction, we disagreed with 7 — and FOUR of those were this
        # exact shape, us saying "out"/"avoid" on a sub-150 name he was actively
        # posting as a setup:
        #
        #   ONDS  "לכל האוהבים מניות מתחת לממוצע 150 - מנסה לעלות מעל הקו הלבן"
        #         — he is naming the sub-150 audience explicitly.
        #   NFLX  "מעל 82 זו נקודה יותר מעניינת מאשר מעל 80" — a trigger call.
        #   META  "שבורה. אבל בראלי כל מטאטא יורה. שימו לב לגאפ מעל הראש" — he says
        #         broken himself, and still points at the gap overhead as the reason
        #         to watch it.
        #   CRWV  "קופצת על קו התמיכה עם יום חזק ווליום גבוה. הייתי ממתין מעל ממוצע
        #         150 או להיכנס עם סטופ ב-ATR" — a bounce, with two named plans.
        #
        # Independently, the 1,098-call forward test puts `broken` at +3.66% excess
        # over 60 days against `breakout_now`'s -4.88%: the bucket we were writing
        # off outperformed the one we were buying.
        #
        # Gated hard, so this stays a narrow exit and not a hole. It needs a fresh
        # BULLISH event on the chart — the flush, buyers actually stepping in, or the
        # turn under way — AND a trigger within reach for the reader to act on. The
        # sub-150 penalty is still charged in full on the STRUCTURE axis, and the
        # validation anchor still holds: DKNG at the date of his "סטופ מתחת ל 25.4"
        # post has none of these and still returns `broken`.
        recovering = bool(
            (s.capitulation or s.candle.get('found')
             or (s.dir_change or {}).get('turning'))
            and trigger and trigger.get('tier') in ('at_hand', 'near'))

        # BROKEN — "כשאני מציין 'אין סט אפ' זה אומר שהסט אפ נגמר ... צריך לצאת מנקודת
        # הנחה שהסטופ שלכם קפץ". Losing the rising-lows line that WAS the structure, or
        # dropping back under a level that had just flipped to support, ends it.
        if s.lost_level and not ctx.above_150 and not turned and not recovering:
            return 'broken'
        if (rl_broke and not ctx.above_150 and s.trend != 'uptrend'
                and not turned and not recovering):
            return 'broken'

        # A base sitting RIGHT AT the 150, with the shorter-term structure already
        # reclaimed, is not the same chart as a genuine downtrend the method
        # declines. Owner's report: INTU — 0.4 ATR under the 150 (1.6%), already
        # above BOTH the 20 and the 50 — graded a flat F26 because `_trend`'s
        # two-year regression still read 'downtrend' and none of `turning`/
        # `turned`/`recovering` fired (no pattern, no fresh buyers candle, no
        # confirmed direction-change — the escapes already built for a fresher
        # bounce don't cover a slow reclaim from below). The state cap ignored
        # what the STRUCTURE axis was already trying to say more gently a few
        # lines below (near_ma's own NEAR_ATR test pays a base this close +9
        # instead of the full -12) — a graduated sub-score meant nothing while
        # `avoid` still forced the letter to D/F regardless.
        #
        # Deliberately NOT gated on a detected pattern (cup/VCP/etc): INTU itself
        # has none (`overlays['cup']` is None on it), so requiring one would not
        # have helped the case this was written for. What actually distinguishes
        # "testing the anchor from below" from "still falling away from it" is
        # measurable directly — the SAME closeness test structure already uses,
        # plus proof the shorter-term trend has already turned (above both the 20
        # and the 50, which a name still genuinely falling has not managed).
        near_150_reclaim = bool(
            ctx.sma150 and atr and (ctx.sma150 - price) / atr <= NEAR_ATR
            and ctx.sma20 and ctx.sma50 and price > ctx.sma20 and price > ctx.sma50)

        if not ctx.above_150 and s.trend == 'downtrend':
            turning = bool(s.dir_change and s.dir_change.get('turning'))
            if not turning and not turned and not recovering and not near_150_reclaim:
                return 'avoid'

        if turned and not ctx.above_150:
            return 'turning'

        # ── An unbroken trigger right overhead is not an entry, whatever else is
        # true ── The chart can be excellent and the answer still be "not here":
        # "פריצה מעל 88.17" (OKTA) is said ABOUT a chart he likes; the entry is the
        # break, not the chart quality. `trigger['tier'] == 'at_hand'` (≤1 ATR) is
        # the SAME bar the rest of the app already uses to mean "essentially
        # happening" (the alert copy, the trigger-axis grading) — reusing it here
        # rather than inventing a second threshold is what closes the AMAT gap:
        # AMAT's own named trigger (530.43, a real 2-touch level 0.5 ATR overhead)
        # graded A 95 and said "enter" a line above the sentence naming that exact
        # price as the thing still to break.
        #
        # Deliberately reads `trigger` directly rather than `_headroom()`. Two
        # measured reasons: `_headroom`'s 0.75 ATR 'tight' cutoff is TIGHTER than
        # `trigger`'s own 1.0 ATR at_hand cutoff, so a 0.93-ATR trigger (AAPL) read
        # as at_hand everywhere else in the app failed to trip a check keyed to
        # 'tight' — two thresholds gating the same decision, silently disagreeing.
        # And `_headroom` only searches horizontal `res_levels`; `trigger` also
        # covers trendline/cup_rim/base/channel candidates (ARES, BR, DOC all had
        # an at_hand trigger of exactly one of those kinds and were invisible to a
        # levels-only check). `trigger` is already the single most-authoritative
        # "what's the next real obstacle" signal in this file — reuse it, don't
        # re-derive a second, narrower version of the same question.
        #
        # Extended to 'near' tier too (owner's report, ARE): a hard, 16-touch wall
        # 5.1% / 1.3 ATR overhead is exactly the kind of line he means by "a good
        # line" — being one tier farther than at_hand doesn't make it any less
        # real. Gated on the SAME `has_real_wall` condition TRIGGER_ENTERING_
        # OVERHEAD already uses for the grade reduction below, so action and
        # grade can no longer disagree about the same fact: measured, 7 of 8
        # names currently entering at 'near' tier had a genuine touch-tested wall
        # in the way (ARE 16 touches, CAG 5, EL 10, BAX 7, AJG 13, BR 10, AMZN 3)
        # — only ARM's near-tier "obstacle" was a trendline/ATH with no touch
        # history, i.e. distance into blue sky rather than a defended line, and
        # ARM correctly keeps its full trigger score AND its 'enter' action.
        # Requiring `has_real_wall` (not just tier) is what keeps that distinction
        # — widening to 'near' by tier ALONE, measured first, would have gutted
        # 8 of 11 live 'enter' actions down to 3, including ARM's legitimate one.
        has_real_wall = bool(trigger and (trigger.get('wall') or {}).get('touches'))
        if (trigger and trigger.get('tier') in ('at_hand', 'near') and trigger.get('price')
                and has_real_wall):
            atr_eps = (ctx.atr * 0.01) if ctx.atr else 0.0
            if float(trigger['price']) > price + atr_eps:
                return 'at_trigger'

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
        # A confirmed buyers' candle is still an entry in its own right. Without one
        # this used to return `needs_buyers`, which has the same problem as the branch
        # below: with a line waiting overhead the thing to wait for is that line.
        if self._is_value(ctx, s):
            if s.candle.get('found'):
                return 'value_pullback'
            if trigger and trigger.get('tier') == 'at_hand':
                return 'at_trigger'
            return 'needs_buyers'

        # A turn candle ON the level is his "חכו לקונים" — interesting, not yet an
        # entry. It is the difference between "there's a doji here, why does that
        # matter?" and "buyers came in".
        #
        # …but only when the trade is a BOUNCE. "חכו לקונים" is what he says at a
        # support with nothing overhead to cross ("נר דוג'י על קו תמיכה … חכו לקונים"
        # OPEN, ASTS); when a line is waiting above, his sentence is "פריצה מעל X".
        # `_at_floor` is true within 1.4 ATR of the 150, which on a coiled chart is
        # true at the same moment the trigger is one tick away — so this branch was
        # firing on breakout setups and telling the reader to wait for the wrong
        # thing. Measured before the fix: 21 of 21 `wait_buyers` names had a breakout
        # as their ONLY entry option, i.e. the instruction contradicted the plan the
        # engine had itself produced, and 15 of the 21 were B-grade.
        #
        # `at_hand` ONLY, not `near`. Deferring on `near` as well emptied this state
        # completely (0 of 119 names) — with two levels shown per side there is nearly
        # always SOME resistance within 2.5 ATR, so "wait for buyers" stopped existing,
        # and it is a call he genuinely makes. Inside 1 ATR the line is the event you
        # are waiting for; at 1-2.5 ATR a bounce off the floor underfoot is the nearer
        # one.
        if at_floor and s.candle.get('turn') and not (
                trigger and trigger.get('tier') == 'at_hand'):
            return 'needs_buyers'

        # AT THE TRIGGER — coiled right under the named price. This is not limited to
        # names already above the 150: when price is under it, the 150 IS the trigger,
        # and that is one of his most-posted setups — "עוברת את הממוצע 150. שפלים
        # עולים" (BULL), "ברגע שתעבור את ממוצע 150 ... זה אפילו טרייד יותר בשרני"
        # (ADBE), OKTA "✅ עברה את ממוצע 150 ... מתי נכנסים? פריצה מעל 88.17".
        # `recovering` overrides the downtrend guard for the same reason it overrides
        # `avoid` above: a two-year regression still reads 'downtrend' on exactly the
        # charts he posts as "trying to climb above the white line", and without this
        # a name that escaped `avoid` would fall through every branch into
        # `nothing_yet` — trading one wrong answer ("out") for another ("nothing
        # here") on a chart that has a flush, a buyers' candle and a line to cross.
        if trigger and trigger['tier'] in ('at_hand', 'near') and (
                s.trend != 'downtrend' or recovering):
            return 'at_trigger'

        # HOLDING — already inside a move, above its structure, nothing new to do.
        if ctx.above_150 and hold and s.trend != 'downtrend':
            return 'holding'

        # Above the 150 with the trigger in hand is never "hasn't done anything yet".
        # `_trend` is a polyfit through two years of pivots, so a name that crashed and
        # has since reclaimed the average still reads `downtrend` and used to fall
        # through BOTH branches above into this one — the bearish→bullish setup, which
        # is one of the shapes the method is built for, scored as "watch". Above the
        # 150 the 150 IS the trend filter; a two-year regression does not get to veto
        # it. (A genuine sub-150 downtrend is already caught by `avoid` further up, so
        # nothing that belongs there reaches here.)
        if (ctx.above_150 and trigger
                and trigger.get('tier') in ('at_hand', 'near')):
            return 'at_trigger'

        return 'nothing_yet'

    @staticmethod
    def _headroom(ctx, s: Signals, from_price: Optional[float] = None) -> dict:
        """
        How far the trade can run before it meets the next real wall.

        Measured from where you would actually be long — the entry, or the trigger
        when the entry is a breakout — not from spot, because for a `wait_trigger`
        name the trigger itself would otherwise register as the ceiling and every
        such chart would read "no room".

        ANY level in `res_levels` counts, with no extra touch-count bar of its own.
        This was a 4-touch-or-strong filter until AMAT exposed why that is wrong:
        the entry at 514.33 read as clean room because the filter would not admit
        530.43 (only 2 touches) as a wall — while `_trigger()`, computed from the
        exact same `res_levels`, was simultaneously naming 530.43 AS THE TRIGGER
        and printing it on the chart. Two different bars for "is this a real wall"
        on the same data meant the state machine could say "enter" one line above
        the sentence that says "break above 530.43". `res_levels` is already
        filtered upstream (`MIN_LEVEL_TOUCHES`), so anything in it is real enough
        to block the road; strength/touches still ride along for the sentence.

        No level above at all is blue sky — the case he calls "יש לה מקום לרוץ".

        Deliberately reports the FIRST wall only. Counting how many walls sit above
        is the congestion metric that was measured and removed (see `_grade`), and
        re-deriving it here through the back door would repeat that mistake.
        """
        price, atr = ctx.price, ctx.atr
        base = float(from_price) if from_price else float(price)
        if not atr:
            return {'atr': None, 'pct': None, 'price': None, 'touches': None,
                    'strength': None, 'level': 'unknown', 'from': base}

        hard = []
        for r in (s.res_levels or []):
            rp = r.get('price')
            # Only skip a wall that IS the entry — i.e. the one being bought or
            # broken. The epsilon was 0.05 ATR, which silently discarded walls
            # sitting essentially on top of spot and handed the name a clean bill:
            # APH graded A 98 with an 8-touch wall 0.05 ATR overhead and no penalty
            # at all, because that wall fell inside the skip. Tie it to the entry
            # instead, so it only excludes what the plan has actually accounted for.
            if not rp:
                continue
            if float(rp) <= base + atr * 0.01:
                continue
            hard.append(r)
        hard.sort(key=lambda r: r['price'])

        if not hard:
            return {'atr': None, 'pct': None, 'price': None, 'touches': None,
                    'strength': None, 'level': 'open', 'from': base}

        w = hard[0]
        wp = float(w['price'])
        # ── The room ends at the band's LOWER edge, not at its midpoint ────────
        # A level is a band everywhere else in this file — `_trigger` quotes
        # `zone_top` as the price to clear and anchors the stop under the band's
        # bottom, on the strength of his own two labelled charts ("86.88 - 88.17 →
        # סטופ מתחת 86"). Headroom was the last place still collapsing a wall to one
        # number, and it collapsed it to the wrong one: a rally does not run to the
        # middle of a supply band before meeting sellers, it meets them at the edge.
        #
        # ARE is the case the owner caught. Entry 53.15, the next wall a 12-touch
        # level drawn 54.04-55.27, and an 8-touch one at 55.12-56.35 right behind
        # it. Measured to the midpoint (54.95) that is 0.88 ATR — 'close', worth -2
        # points and no ceiling, so it graded A 77 / 8-10 while telling the reader to
        # buy into a wall. Measured to the edge the price actually reaches (54.04) it
        # is 0.43 ATR — 'tight', which is what `no_room` exists for. Same rule the
        # owner stated on CMG: if a hard line sits above, being under it is not a
        # clean entrance.
        #
        # Clamped at zero for a band that straddles the entry: you are not 'a
        # negative distance' from resistance, you are already inside it.
        lo = w.get('bottom')
        edge = min(wp, float(lo)) if lo else wp
        d = max(0.0, (edge - base) / atr)
        level = ('tight' if d < HEADROOM_TIGHT_ATR else
                 'close' if d < HEADROOM_CLOSE_ATR else
                 'some' if d < HEADROOM_OK_ATR else
                 'clear' if d < HEADROOM_CLEAR_ATR else 'open')
        return {'atr': jnum(d), 'pct': jnum((edge / base - 1) * 100),
                # the level is still NAMED by its own price — that is the number on
                # the chart and the one he would quote; only the DISTANCE is measured
                # to the edge that stops the move
                'price': jnum(wp), 'edge': jnum(edge),
                'touches': w.get('touches'), 'strength': w.get('strength'),
                'level': level, 'from': jnum(base)}

    @staticmethod
    def _headroom_detail(hr: Optional[dict], he: bool) -> str:
        """One phrase for the headroom row, worded to match the sign of what it scored."""
        if not hr or not hr.get('price'):
            return 'אין התנגדות משמעותית מעל' if he else 'no hard resistance overhead'
        a, p, t = hr['atr'], hr['price'], hr.get('touches') or 0
        lvl = hr.get('level')
        if lvl == 'tight':
            return (f"רמה עם {t} נגיעות רק {a:.1f} ATR מעל ({p:.2f})" if he
                    else f"a {t}-touch wall only {a:.1f} ATR above ({p:.2f})")
        if lvl == 'close':
            return (f"רק {a:.1f} ATR עד הרמה הבאה ({p:.2f})" if he
                    else f"only {a:.1f} ATR to the next wall ({p:.2f})")
        return (f"פנוי {a:.1f} ATR עד {p:.2f}" if he
                else f"clear for {a:.1f} ATR to {p:.2f}")

    @staticmethod
    def _break_strength(s: Signals, atr: float) -> Optional[dict]:
        """
        The wall that was just broken, and how well defended it was. `break_level` is
        only a price; the touch history lives on the level it came from — and after a
        break that level has usually flipped, so both sides have to be searched.

        `break_level` can also come from a broken descending-highs TREND LINE, not just
        a horizontal level (see micha._fresh_break's `broke_desc` branch) — "פורצת שיאים
        יורדים" (WGMI, NVDA, OKTA) is the same event in diagonal form. But `_fresh_break`
        hands back only the line's price, same as it does for a level, so a trendline
        break used to fall through the search below (it matches nothing in `res_levels`/
        `sup_levels`) and was silently scored as a bare 2-touch break regardless of how
        many pivots the line itself snapped through — a 5-touch descending-highs line
        breaking, exactly the "hard resistance" event the method is organised around,
        paid the same as a break with no history at all. The line's touch count lives in
        `overlays['trendlines']`, so it has to be searched separately from the level map.
        """
        bl = s.break_level
        if not bl or not atr:
            return None
        best = None
        for r in list(s.res_levels or []) + list(s.sup_levels or []):
            rp = r.get('price')
            if rp and abs(float(rp) - float(bl)) <= atr * 0.15:
                if best is None or (r.get('touches') or 0) > (best.get('touches') or 0):
                    best = r
        line_touches = 0
        for t in (s.overlays or {}).get('trendlines') or []:
            if t.get('kind') != 'falling_highs':
                continue
            tp = (t.get('p2') or {}).get('price')
            if tp is not None and abs(float(tp) - float(bl)) <= atr * 0.15:
                line_touches = max(line_touches, t.get('touches') or 0)
        level_touches = (best.get('touches') or 0) if best else 0
        if best is None and not line_touches:
            return {'price': jnum(bl), 'touches': None, 'hard': False}
        t = max(level_touches, line_touches)
        hard = bool((best and best.get('strength') == 'strong') or t >= HEADROOM_HARD_TOUCHES)
        return {'price': jnum(bl), 'touches': t, 'hard': hard}

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
        rr, rr_first = self._rr(ctx, s, entry, stop.get('price'))
        risk = stop.get('risk_pct')
        # The one number that can rank a 12%/10R home run against a 55%/1R scalp —
        # priced at the best exit the ladder offers, not at the thesis target. See
        # `_expectancy_at_best_exit`.
        p_win, exp_r, exp_rr = self._expectancy_at_best_exit(
            ctx, s, entry, stop.get('price'), stop.get('atr'))
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
            # the R the expectancy was actually measured at — usually below
            # `risk_reward`, which runs to the whole opportunity. Carried so the copy
            # can never quote the odds of one target beside the ratio of another.
            'expectancy_rr': exp_rr,
        }

    @staticmethod
    def _exit_prices(ctx, s: Signals, entry: float) -> list:
        """Every price this trade could be closed at, ascending. See
        `_opportunity_top` for where the five sources come from and why."""
        ups = [t['price'] for t in (s.targets or [])
               if t.get('price') and t['price'] > entry]
        if s.ath and s.ath > entry:
            ups.append(float(s.ath))
        ov = s.overlays or {}
        for g in ov.get('gaps') or []:
            if g.get('dir') == 'down' and g.get('far') and g['far'] > entry:
                ups.append(float(g['far']))
        cup = ov.get('cup') or {}
        for k in ('target_big', 'target_small'):
            if cup.get(k) and cup[k] > entry:
                ups.append(float(cup[k]))
        for lv in ((ov.get('fib_ext') or {}).get('levels') or []):
            if lv.get('price') and lv['price'] > entry:
                ups.append(float(lv['price']))
        return sorted(set(float(u) for u in ups))

    @classmethod
    def _expectancy_at_best_exit(cls, ctx, s: Signals, entry, stop, stop_atr) -> tuple:
        """
        (P(win), E[R], the R it was measured at) at the BEST exit on the ladder —
        not at the thesis target.

        `config.expectancy` is a 120-trading-day measurement. The thesis target is
        routinely a multi-year price: ADBE sits 56.9% under its own record and its
        thesis is that record, +123%. Asking a 120-day model whether that happens
        returns p = 4.8%, and because `expectancy` clamps R at the grid's last knot
        (R=10) while the reward keeps growing, E = p*R - (1-p) starts DECREASING in
        upside. Measured on a 245-name sweep the moment `_rr` was pointed at the
        thesis: names scoring a negative E[R] went 6 -> 18, `negative_ev` capped 4
        letters, and the fallers' median distance below their own high was 43.3%
        against 19.4% for the universe. That is `spearman(score, potential) = -0.10`
        coming back — the exact inversion GRADE_BUDGET was rewritten to remove. The
        same 123% was simultaneously paying ADBE a full 12/12 on the prize term.
        So: the PRIZE is the whole opportunity, and the ODDS are the best exit that
        opportunity actually offers. Both halves still read one target list
        (`_exit_prices`), which is what made them agree; they just ask different
        questions of it. It is also how the trade is managed rather than a modelling
        convenience — his 2022 pre-entry checklist has TP1 and TP2, and "היעד
        הראשוני הוא פתח הגאפ. אחרי זה סגירת הגאפ". Nobody holds for the record or
        nothing.
        """
        if not (entry and stop) or entry <= stop or not stop_atr:
            return None, None, None
        risk = float(entry) - float(stop)
        best = (None, None, None)
        for t in cls._exit_prices(ctx, s, entry):
            r = (t - float(entry)) / risk
            p, e = expectancy(stop_atr, r)
            if e is not None and (best[1] is None or e > best[1]):
                best = (p, e, jnum(r))
        return best

    @classmethod
    def _opportunity_top(cls, ctx, s: Signals, entry: float) -> Optional[float]:
        """
        The highest price this trade can reach from `entry` — the whole opportunity.

        THE SINGLE TARGET LIST. `_rr` and `_thesis` both answer "how far does this
        go" and they used to answer it from different lists: `_thesis` read this full
        set while `_rr` read only `s.targets`, which `MAX_TARGET_STATIONS` truncates
        to four rungs. Measured over 160 priced plans, 107 (67%) had a top above the
        ladder's, so two halves of the REWARD axis were pricing different trades —
        EBAY scored its prize to 123.13 (a Fib extension) and its odds to 117.88.

        The four sources beyond the ladder are all prices he quotes by name, and all
        four are exactly what the display cap drops first, because the biggest target
        is by construction last in the list: the prior high ("מגיעה שוב לשיאים שלה"),
        the far side of an unfilled gap ("סגירת הגאפ"), the cup's measured move
        ("לוקחים את עומק הספל, קופי-פסטה, מדביקים") and the reverse-Fibonacci
        projection ("ניקח את אחד התיקונים שלה, נמתח פיבונצ'י הפוך").

        Note what shares this list and what does not: the SIZE of the prize is this
        top, while the ODDS are priced at the best rung in the same list — see
        `_expectancy_at_best_exit` for the measurement that forced that split.
        """
        ups = cls._exit_prices(ctx, s, entry)
        return max(ups) if ups else None

    @classmethod
    def _rr(cls, ctx, s: Signals, entry, stop):
        """
        Reward-to-risk against the whole opportunity, not the first station.

        The number he quotes is the whole opportunity — "יש פה פוטנציאל של 25%" (PM),
        "תשואה פוטנציאלית של 50%" (KRE), "היעד לקאפ הוא $97" (IREN) — while the near
        station is only the first obstacle on the way ("היעד הראשוני הוא פתח הגאפ.
        אחרי זה סגירת הגאפ"). Measuring risk against a +2% first station produced
        nonsense like 0.3 on trades whose actual thesis was +30%.

        The top now comes from `_opportunity_top`, the same resolver `_thesis` uses —
        this docstring already claimed "the whole opportunity" while the code read a
        list truncated to four rungs. Returns (rr_to_thesis, rr_to_first_station);
        the first station stays the ladder's own next rung, which is what it means.
        """
        if not (entry and stop) or entry <= stop:
            return None, None
        top = cls._opportunity_top(ctx, s, entry)
        if top is None:
            return None, None
        stations = [t['price'] for t in (s.targets or [])
                    if t.get('price') and t['price'] > entry]
        risk = entry - stop
        first = stations[0] if stations else top
        return jnum((top - entry) / risk), jnum((first - entry) / risk)

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
        # ── The previous support level ────────────────────────────────────────
        # Owner (2026-08-22): "the stop doesn't have to be very tight, it can be the
        # previous support level if it's not that far." It was barely reachable:
        # measured over 245 names, 157 stops anchored to the bottom of the line
        # being broken and exactly 4 to a support level, because the only support
        # that ever became a candidate was whatever `_hold_level` happened to pick.
        # A tested support below the entry is the most obvious "am I wrong" line on
        # the chart and belongs in the running.
        for lv in (s.sup_levels or []):
            b = _edge(lv, 'sup')
            if b and b < entry and (entry - b) <= STOP_SUPPORT_MAX_ATR * atr:
                cands.append((float(b), f"the support at {lv['price']:.2f}",
                              f"התמיכה ב-{lv['price']:.2f}"))

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
                # ...but not when the band floor is a HAIRLINE and a real support
                # sits just below it. The exemption exists so his own 0.43-ATR
                # placement is not vetoed by the noise floor, not to force a stop
                # tighter than the chart's own structure: measured, it was pulling
                # 34% of names under 0.5 ATR, which the grade then complained about.
                # A support within STOP_SUPPORT_MAX_ATR is the better line whenever
                # the floor alone would be inside the noise band.
                sup_alt = max((c for c in cands if c[0] < noise_floor
                               and 'support' in c[1]), key=lambda c: c[0], default=None)
                if (entry - fl) < STOP_NOISE_ATR * atr and sup_alt:
                    usable, anchored = [sup_alt], True
                else:
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
    def _action(ctx, state, s: Signals, earn, options) -> str:
        # "רק חכו לדיווח התוצאות מחר - פשוט לא רוצה לשכוח את הסט אפ" (PM) — the setup
        # still stands, the entry is deferred.
        entering = state in ('breakout_now', 'buyers_at_level', 'value_pullback')
        if entering and earn is not None and earn <= 1:
            return 'wait_event'
        # Stretched is a modifier, not a veto: "מתוחה אבל ... כל עוד שומרת מעל 19 היא
        # בסדר" (CRML). It never blocks holding — it blocks CHASING.
        if entering and s.ext.get('stretched'):
            return 'wait_pullback'
        # The same "don't chase" idea, measured a different way: distance from the
        # level THIS break actually happened at, not from the 150/200MA. `stretched`
        # can be false on a chart that just broke out cleanly weeks below its
        # average and has since run hard off that fresh level — the MA is still
        # close, but the entry itself is no longer at the break. ATR-normalized
        # (CHASE_PAST_TRIGGER_ATR), same reasoning as EXTENDED_ATR's own hard
        # ceiling on `breakout_now` itself (`_state`) — this is the SOFTER, earlier
        # rung between "right at the level" and that hard ceiling, so an entry a
        # full ATR past its own trigger gets a caution before the state machine
        # gives up on calling it a breakout at all. A modifier, not a veto, same as
        # `stretched` above — a real, well-structured breakout that has run is
        # still a trade, just not a chase.
        if (entering and s.break_level and ctx.atr
                and (ctx.price - s.break_level) / ctx.atr > CHASE_PAST_TRIGGER_ATR):
            return 'wait_pullback'
        if entering:
            return 'enter'
        return {
            # A confirmed turn under the 150 is his "ברגע שתעבור את ממוצע 150 ... זה
            # אפילו טרייד יותר בשרני" (ADBE): the turn is real, the entry is the
            # average. `_trigger` already names the 150 as the price when price is
            # under it, so this routes to the same wait the rest of the app means.
            'turning':      'wait_trigger',
            'at_trigger':   'wait_trigger',
            'needs_buyers': 'wait_buyers',
            'holding':      'hold',
            'nothing_yet':  'watch',
            'broken':       'out',
            'avoid':        'avoid',
        }[state]

    # ── 7. The grade — event / reward / structure / risk ──────────────────────

    def _thesis(self, ctx, s: Signals, best, state) -> tuple:
        """
        How far the farthest upward target is, in percent and in ATR — and its
        price, for `Judgement._macro_target` (the panel's labeled "full pattern
        target," as opposed to the near station the ladder leads with).

        Read from `_opportunity_top` — the SAME resolver `_rr` uses, so the size of
        the prize and the odds of collecting it can no longer be priced against
        different targets. See that method for why the display ladder cannot be the
        source: `MAX_TARGET_STATIONS` caps what the PANEL shows and the biggest
        target is by construction last in the list, so the number that decides
        POTENTIAL was the first thing dropped (AXON: a cup target at 1092.97, +53%,
        computed, displayed nowhere, invisible to the grade).
        """
        if best is None or state in ('broken', 'avoid', 'nothing_yet'):
            return None, None, None
        entry = best.get('entry') or ctx.price
        top = self._opportunity_top(ctx, s, entry)
        if top is None:
            return None, None, None
        pct = (top / entry - 1) * 100
        return pct, (pct / ctx.atr_pct if ctx.atr_pct else None), top

    @staticmethod
    def _trend_for_grade(ctx, s: Signals) -> str:
        """
        `Signals.trend` as the STRUCTURE axis is allowed to read it.

        `micha._trend` is a polyfit through the swing pivots of the window (falling
        back from the last year to the full three). That is a real signal and it is
        the right one for a chart nobody has done anything to. It is the wrong one
        for the chart this method is built to buy: a stock only ever reclaims its
        150MA from below, so the regression through where it CAME FROM still slopes
        down on the exact setup he posts most.

        Measured over 245 live names: 54 sit above the 150 while the pivot slope
        reads 'downtrend', and 48 of those 54 had a real bullish EVENT on the chart
        (a break, a reclaim, a confirmed direction change). Every one was paying
        -10 of the 45-point structure basis for the condition its own EVENT score
        was being paid for escaping — the same fact scored twice, in opposite
        directions. CPRT is the owner's example and the sentence gave it away
        verbatim: "volume expanding into the move, and rising lows on the weekly.
        What holds the grade back: lower highs and lower lows."

        This is not a new opinion. `_state` already refuses to let the regression
        veto the average ("Above the 150 the 150 IS the trend filter; a two-year
        regression does not get to veto it") and `reasons.py` already downgrades
        the mirror-image claim — "a real uptrend" on a name under its 150 — to a
        note. The grade was the last place still taking the raw read at face value.

        Deliberately NOT promoted to 'uptrend': rising highs and rising lows is a
        claim about the chart and it is not true here. It becomes the sideways case
        — no directional structure yet — which is exactly what "above the average,
        nothing else proven" means.
        """
        if s.trend == 'downtrend' and ctx.above_150:
            return 'reclaimed'
        return s.trend

    def _event(self, ctx, s: Signals, state, trigger) -> dict:
        """
        What actually HAPPENED — the axis that replaced `trigger`.

        The owner's sentence: "we are looking to enter a stock when something
        happened - break hard resistance line, or trend line, bearish to bullish".
        The old trigger axis could not express any of that. It scored PROXIMITY: its
        observed distribution over 208 names was {28.0: 102, 5.8: 63, 19.8: 30,
        35.0: 6}, i.e. 35 points riding on "is a wall within 1 ATR of spot today".
        Measured at the same time, 108 names had a broken trendline and 9 were in a
        state that could be paid for it; 28 had a confirmed direction change and 3
        were payable, their grades 14 C / 7 B / 4 F / 3 D and a median score dead on
        the universe median. Anticipation outscored the event by 28 points to zero.

        So the catalogue below is ordered by how DECISIVE the event is, the events
        are read off the chart rather than off the state the price landed in
        afterwards, and an unbroken trigger — a wait, however close — is priced as a
        wait. Returns the best single event; they are alternatives, not a checklist,
        because a stock that breaks a hard level while confirming a direction change
        has had one good day, not two.
        """
        atr = ctx.atr
        brk = self._break_strength(s, atr)
        dc = s.dir_change or {}
        cands: list[tuple[float, str, Optional[int], str, str]] = []

        if brk:
            if brk['hard']:
                t = brk.get('touches') or 0
                cands.append((EVENT_HARD_BREAK, 'hard_break', s.break_age,
                              f"broke a well-defended level at {brk['price']:.2f} "
                              f"({t} touches)",
                              f"פרצה רמה חזקה ב-{brk['price']:.2f} ({t} נגיעות)"))
            else:
                cands.append((EVENT_SOFT_BREAK, 'soft_break', s.break_age,
                              f"broke the level at {brk['price']:.2f}",
                              f"פרצה את הרמה ב-{brk['price']:.2f}"))
        # "שינוי כיוון" complete — all four dictated stages including the breakout.
        # This is the bearish-to-bullish turn the owner names, and until now the
        # grade's only acknowledgement of it was +4 for one of its four stages.
        if dc.get('confirmed'):
            cands.append((EVENT_DIR_CHANGE, 'dir_change', s.break_age,
                          'bearish to bullish — all four stages, breakout included',
                          'שינוי כיוון מלא — כל ארבעת השלבים, כולל הפריצה'))
        if s.ma150_reclaim:
            cands.append((EVENT_MA150_RECLAIM, 'ma150_reclaim',
                          s.ma150_reclaim.get('bars'),
                          'closed back above the 150MA and held it',
                          'חזרה מעל ממוצע 150 ונשארה מעליו'))
        if state in ('buyers_at_level', 'value_pullback') and s.candle.get('found'):
            # ── The RETEST: buyers on the line the stock itself broke ─────────
            # His complete-setup sentence, said in this exact three-beat form in
            # live after live: "יש לנו את הקאפ, יש לנו את הפריצה, יש לנו את הבדיקת
            # תמיכה" — the base, the breakout, the support retest — followed by
            # "יש לנו את הכל מה שאנחנו צריכים ... בעיניי זה נראה מצוין" (2026-04-23,
            # and again on NVDA 2026-05-05). Also "זה הקאפ, זו הפריצה וזו בדיקת
            # התמיכה ... לדעתי יש לכם נקודת כניסה מצוינת" (2026-04-28) and LMND
            # "נעצרה בדיוק על קו ההתנגדויות תמיכות ... נקודת כניסה מצוינת".
            #
            # A bounce on a random old floor and a bounce on the wall this stock has
            # just cleared are not the same event, and only the second one is the
            # entry he calls excellent — the break proved the line, the retest gives
            # the tight stop back, and both facts were already computed here and
            # thrown away. `flipped` is the level engine's own record that this price
            # was resistance and is now support, so nothing new is inferred.
            #
            # Ranked above a bare break because he ranks it above one: at the break
            # he says "חכו לפריצה שלא סתם תעופו בסטופ"; at the retest he says the
            # entry is excellent. It is the same wall with one more thing proven.
            # Ties with EVENT_HARD_BREAK on points (30 is the axis basis and nothing
            # may exceed it) and wins on EVENT_PRIORITY, which matters because the
            # break that created the line is ALWAYS a candidate alongside the retest
            # — on a bare max() this sentence could never be the one printed.
            sup = s.nearest_sup or {}
            retest = bool(sup.get('flipped')) or (
                s.break_level is not None and ctx.atr
                and abs(float(sup.get('price') or 0) - float(s.break_level)) <= ctx.atr * 0.5)
            if retest:
                lvl = float(sup.get('price') or s.break_level or 0)
                cands.append((EVENT_RETEST, 'retest', None,
                              f'buyers stepped in ON the line it broke ({lvl:.2f}) — '
                              f'the breakout, then the retest',
                              f'קונים נכנסו על הקו שהיא פרצה ({lvl:.2f}) — '
                              f'הפריצה, ואז בדיקת התמיכה'))
            cands.append((EVENT_BOUNCE, 'bounce', None,
                          s.candle.get('label') or 'buyers stepped in at the level',
                          s.candle.get('label_he') or 'קונים נכנסו על הרמה'))
        if s.capitulation:
            cands.append((EVENT_CAPITULATION, 'capitulation', None,
                          'a high-volume wash-out then stabilizing — the flush that '
                          'resets the risk',
                          'קפיטולציה בווליום גבוה ואז התייצבות — התיקון שמאפס את הסיכון'))
        if dc.get('turning'):
            n = dc.get('stages_done') or 0
            cands.append((EVENT_TURNING, 'turning', None,
                          f'changing direction — {n} of 4 stages, waiting on the break',
                          f'משנה כיוון — {n} מתוך 4 שלבים, מחכים לפריצה'))

        # An event decays, and then it EXPIRES. A wall broken 3 bars ago is the news;
        # broken 22 bars ago it is the reason the stock is where it is; broken 154
        # bars ago it is not an event at all, and a decay floor alone still paid it
        # half — KO's real case, where a 150MA reclaim from 154 bars back scored
        # 13/30, more than a live wait. Past EVENT_STALE_BARS the honest reading is
        # that nothing has happened lately, so the candidate is dropped and the axis
        # falls through to whatever IS true now: waiting on the trigger.
        cands = [c for c in cands if c[2] is None or c[2] <= EVENT_STALE_BARS]
        age = None
        if cands:
            # points first, then EVENT_PRIORITY — see there for why the tie-break
            # exists (a retest always carries the break that made the line with it)
            pts, key, age, en, he = max(
                cands, key=lambda c: (c[0], EVENT_PRIORITY.get(c[1], 0)))
            pts = min(pts, EVENT_BASIS)
            if age is not None and age > EVENT_FRESH_BARS:
                span = EVENT_STALE_BARS - EVENT_FRESH_BARS
                f = 1.0 - (1.0 - EVENT_STALE_FLOOR) * min(1.0, (age - EVENT_FRESH_BARS) / span)
                pts *= f
                en += f' ({age} bars ago)'
                he += f' (לפני {age} נרות)'
        elif trigger:
            # Continuous in distance — see EVENT_WAIT_NEAR. Nothing has happened
            # either way, so the whole range sits below any real event; what varies
            # is how close the decision is.
            d = max(0.0, float(trigger.get('distance_atr') or 0.0))
            f = min(1.0, d / EVENT_WAIT_SPAN_ATR)
            pts = EVENT_WAIT_NEAR - (EVENT_WAIT_NEAR - EVENT_WAIT_FAR) * f
            key = 'waiting'
            tp, tpc, td = trigger['price'], trigger['distance_pct'], trigger['distance_atr']
            if trigger['tier'] == 'at_hand':
                en = f"nothing yet — {trigger['what']} at {tp:.2f} is right overhead ({td:.1f} ATR)"
                he = f"עוד לא קרה כלום — {trigger['what_he']} ב-{tp:.2f} ממש מעל ({td:.1f} ATR)"
            else:
                en = f"nothing has happened yet — the trigger {tp:.2f} is {tpc:+.0f}% away"
                he = f"עוד לא קרה כלום — הטריגר {tp:.2f} במרחק {tpc:+.0f}%"
        else:
            pts, key = EVENT_NONE, 'none'
            en, he = 'nothing overhead left to clear', 'אין מעל הראש מה לפרוץ'

        # ── The honesty ceiling ───────────────────────────────────────────────
        # An event may not claim the road is open while the engine's OWN trigger
        # names an unbroken wall above it. Paying full marks regardless is what let
        # TXN grade A 92 with a 10-touch wall 6.1% overhead.
        #
        # `at_hand` is exempt ONLY for a break. Inside 1 ATR a break genuinely is in
        # progress, so "it is happening now" is true — but that exemption was written
        # for the breakout case and it silently covered every other event too. CMG
        # (owner's report) is what it costs: a 150MA reclaim scoring 26/30 while the
        # stock sat under BOTH a hard horizontal at 37.16 and a descending trendline.
        # "Room to grow is very important, so the breaking line has to be on point —
        # if the stock is facing a hard resistance line or trendline above, we want
        # it to be ABOVE it so the entrance will be clean." A reclaim that happened
        # below an unbroken wall has not bought a clean entrance, however close the
        # wall is; only clearing the wall does that. So a NON-break event is ceilinged
        # at every tier, at_hand included.
        BREAK_EVENTS = ('hard_break', 'soft_break', 'dir_change')
        over = (trigger and trigger.get('price') and float(trigger['price']) > ctx.price
                and (trigger.get('wall') or {}).get('touches'))
        ceiling = None
        if over:
            ceiling = TRIGGER_ENTERING_OVERHEAD.get(trigger['tier'])
            if ceiling is None and key not in BREAK_EVENTS:
                # at_hand, and the event is not the break of this wall
                ceiling = EVENT_UNDER_WALL
        capped = False
        if ceiling is not None and pts > ceiling:
            pts, capped = float(ceiling), True
            tp, tpc = trigger['price'], trigger['distance_pct']
            en += f", but the wall that caps this move — {tp:.2f} — is still {tpc:+.0f}% overhead"
            he += f", אבל הרמה שחוסמת את המהלך — {tp:.2f} — עדיין {tpc:+.0f}% מעל"
        if state in ('broken', 'avoid'):
            pts = min(pts, 5.0)
        return {'points': pts, 'key': key, 'age': age, 'en': en, 'he': he, 'capped': capped}

    def _reward(self, ctx, s: Signals, best, thesis_pct, thesis_atr, state) -> dict:
        """
        What the trade is worth — the axis that did not exist.

        Three separable parts. EXPECTED VALUE is the measured one and carries the
        most: `config.expectancy` prices the odds of collecting against the size of
        the prize, and it was already being computed on every option and used to
        SORT /radar and /portfolio while the letter ignored it entirely. Measured
        over 208 live names, the grade's own top-10 had a median E[R] of 0.22 while
        ranking by E[R] gave 2.2 — the app's two opinions of the same stock.

        PRIZE SIZE is the old POTENTIAL, moved here out of `setup` where it was
        competing for room against structural checkboxes that already reached 42/45
        without it. RECOVERY ROOM is the pair the owner names by hand — an unfilled
        gap overhead to close, and distance back under the prior high.
        """
        out = {'ev': 0.0, 'prize': 0.0, 'room': 0.0, 'time': 0.0,
               'notes': [], 'ev_r': None, 'days': None}
        if state in ('broken', 'avoid', 'nothing_yet'):
            return out
        if best is None:
            # A live state with no priced plan zeroes the biggest axis on the board
            # and, because a zero has nothing to deduct, filed nothing for the
            # sentence to say. KO closed a D 39 with his A-grade line over a 0/34
            # reward for exactly this reason. State the forfeit explicitly.
            out['notes'].append(
                (-float(REWARD_EV_MAX + REWARD_PRIZE_MAX),
                 'no entry plan can be priced here — no target above the entry to '
                 'measure the trade against',
                 'אי אפשר לתמחר פה תוכנית כניסה — אין יעד מעל הכניסה למדוד מולו'))
            return out
        note = out['notes'].append

        # ── Expected value ───────────────────────────────────────────────────
        ev = best.get('expectancy_r')
        # the ratio the EXPECTANCY was measured at, not the one to the thesis top —
        # see `_expectancy_at_best_exit`. Quoting `risk_reward` here would print the
        # odds of the best exit beside the ratio of the farthest target.
        rr = best.get('expectancy_rr') or best.get('risk_reward')
        out['ev_r'] = ev
        if ev is not None:
            if ev < 0:
                out['ev'] = REWARD_EV_NEGATIVE
                note((-REWARD_EV_MAX,
                      f'negative expectancy — at its own measured odds this setup '
                      f'loses {abs(ev):.2f}R',
                      f'תוחלת שלילית — בסיכויים הנמדדים שלו הטרייד מפסיד {abs(ev):.2f}R'))
            else:
                # Continuous, and scaled to what `expectancy()` can actually return
                # — see REWARD_EV_FULL. The band table this replaces asked for
                # E[R] >= 1.20 on a surface whose measured maximum is +0.368, so
                # nothing in the market could score above 55% of this term.
                frac = min(1.0, ev / REWARD_EV_FULL) if REWARD_EV_FULL else 0.0
                out['ev'] = REWARD_EV_MAX * frac
                p = best.get('p_win')
                pw = f", {p*100:.0f}% of the time" if p else ''
                pwh = f", {p*100:.0f}% מהמקרים" if p else ''
                if frac >= REWARD_EV_GOOD_FRAC:
                    note((out['ev'],
                          f'expectancy {ev:+.2f}R at reward-to-risk {rr:.1f}{pw}',
                          f'תוחלת {ev:+.2f}R ביחס סיכוי/סיכון {rr:.1f}{pwh}'))
                elif frac <= REWARD_EV_THIN_FRAC:
                    note((-(REWARD_EV_MAX - out['ev']),
                          f'thin expectancy — {ev:+.2f}R for the risk taken',
                          f'תוחלת דקה — {ev:+.2f}R על הסיכון שנלקח'))
                else:
                    note((out['ev'], f'expectancy {ev:+.2f}R',
                          f'תוחלת {ev:+.2f}R'))

        # ── Prize size, in PERCENT ───────────────────────────────────────────
        # See REWARD_PRIZE_FLOOR_PCT: reward is measured in money, and money is
        # percent. The ATR path this used to carry is gone, and with it the
        # calm-stock artifact it needed POTENTIAL_MIN_ATR_PCT to suppress.
        if thesis_pct is not None and thesis_pct > REWARD_PRIZE_FLOOR_PCT:
            span = REWARD_PRIZE_CAP_PCT - REWARD_PRIZE_FLOOR_PCT
            f = min(1.0, (thesis_pct - REWARD_PRIZE_FLOOR_PCT) / span)
            out['prize'] = REWARD_PRIZE_MAX * f
            if f >= 0.6:
                note((out['prize'],
                      f'the thesis reaches {thesis_pct:.0f}% out — an exceptional amount of room',
                      f'התזה מגיעה ל-{thesis_pct:.0f}% מכאן — כמות עצומה של מקום'))
            elif f >= 0.25:
                note((out['prize'],
                      f'the thesis reaches {thesis_pct:.0f}% out — real room beyond the near target',
                      f'התזה מגיעה ל-{thesis_pct:.0f}% מכאן — מקום ממשי מעבר ליעד הקרוב'))
            else:
                note((out['prize'], f'the thesis reaches {thesis_pct:.0f}% out',
                      f'התזה מגיעה ל-{thesis_pct:.0f}% מכאן'))

        # ── Recovery room: the gap to close, and the old high to get back to ──
        room = 0.0
        entry = best.get('entry') or ctx.price
        gap = None
        for g in (s.overlays or {}).get('gaps') or []:
            if (g.get('dir') == 'down' and g.get('far') and g['far'] > entry
                    and ctx.atr and (g['far'] - entry) / ctx.atr <= REWARD_GAP_NEAR_ATR):
                gap = g['far'] if gap is None else min(gap, float(g['far']))
        if gap is not None:
            room += REWARD_ROOM_MAX * 0.5
            note((REWARD_ROOM_MAX * 0.5,
                  f'an unfilled gap overhead at {gap:.2f} to close',
                  f'גאפ פתוח מעל ב-{gap:.2f} שצריך להיסגר'))
        if s.off_high >= REWARD_OFF_HIGH_BIG_PCT:
            room += REWARD_ROOM_MAX * 0.5
            note((REWARD_ROOM_MAX * 0.5,
                  f'still {s.off_high:.0f}% under its own prior high',
                  f'עדיין {s.off_high:.0f}% מתחת לשיא שלה'))
        elif s.off_high >= REWARD_OFF_HIGH_REAL_PCT:
            room += REWARD_ROOM_MAX * 0.25
        out['room'] = min(room, REWARD_ROOM_MAX)

        # ── Time, one-sided ──────────────────────────────────────────────────
        # See TIME_EFFICIENCY_MAX: as a symmetric ± this billed a distant thesis
        # twice, once through the odds discount already inside `expectancy` and
        # again for the days that distance implies. What is left is the residue —
        # a target so far out it is a different trade from the one being graded.
        if thesis_atr is not None:
            days, _hit = time_to_target(thesis_atr, ctx.atr_pct)
            out['days'] = days
            if days > TIME_SLOW_DAYS:
                span = TIME_GLACIAL_DAYS - TIME_SLOW_DAYS
                f = min(1.0, (days - TIME_SLOW_DAYS) / span)
                out['time'] = -TIME_EFFICIENCY_MAX * f
                if f >= 0.5:
                    note((out['time'],
                          f'the target is ~{days:.0f} trading days out — a long wait',
                          f'היעד ~{days:.0f} ימי מסחר מכאן — המתנה ארוכה'))
        return out

    def _grade(self, ctx, s: Signals, state, trigger, options, action, small_cap, earn):
        """
        Four axes: EVENT, REWARD, STRUCTURE, RISK.

        His own A-grade sentence has three clauses — "מעל נקודת הפריצה (the event).
        מעל ממוצע 150 (structure). קרוב לממוצע (risk — the stop is right there). מה
        עוד נותר לבקש" (GEV) — and for a long time this scored exactly those three.
        The fourth is the owner's, and it is the one his posts assume rather than
        state: he only posts a chart at all when he thinks it is worth something.
        Grading without it produced the inversion that forced this rewrite — a
        universe sweep where spearman(score, potential) came out at -0.10, the
        median E[R] per letter ran A +0.17 / B +0.28 / C +0.21 / D +0.20, and CMG
        (86% thesis, 12.4 R/R, positive expectancy) graded C 69 while KO (R/R 0.34,
        E[R] -0.27, risking three times what its whole thesis was worth) graded
        B 81. See GRADE_BUDGET for the full measurement.
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
        best = self._best_option(options, action)
        thesis_pct, thesis_atr, thesis_price = self._thesis(ctx, s, best, state)

        # ── STRUCTURE: is there a real chart here? ─────────────────────────────
        # Written against the 45-point basis every literal here was designed on and
        # rescaled onto B['structure'] at the end, same contract as EVENT and RISK.
        structure = 0.0
        if ctx.above_150:
            # Three-way, not two: "close to the average" is the A-grade clause, but
            # 15% above and 52% above are not the same chart and used to differ by a
            # single point out of a hundred. FTNT (+52%) and CRWD (+42%) scored the
            # same here as F (+9%) and TEAM (+9%). See FAR_FROM_MA_PCT.
            if self._near_ma(ctx):
                structure += 12
                note('structure', 12, f'above the 150MA and close to it ({d150:+.0f}%)',
                     f'מעל ממוצע 150 וקרובה אליו ({d150:+.0f}%)')
            elif self._far_from_ma(ctx):
                structure += 3
                note('structure', -9, f'{d150:+.0f}% above the 150 — no tight stop from up here',
                     f'{d150:+.0f}% מעל ממוצע 150 — אין מכאן סטופ צמוד')
            else:
                structure += 7
                note('structure', 7, f'above the 150MA ({d150:+.0f}%)',
                     f'מעל ממוצע 150 ({d150:+.0f}%)')
            # "she crossed the average - correct. My problem is she has run so much in
            # recent days… 6 consecutive green days" (CRWD). The trigger is real; it
            # is the ENTRY that has gone bad, which is why this is charged here and
            # not against the event.
            if s.ext.get('ran_hot'):
                structure -= 5
                note('structure', -5,
                     f"ran {s.ext.get('run_pct') or 0:+.0f}% in the last few days — the run into "
                     f"the trigger was the move",
                     f"רצה {s.ext.get('run_pct') or 0:+.0f}% בימים האחרונים — הריצה אל הטריגר "
                     f"הייתה המהלך")
            # "קצת מתוחה" — the band below his cap. He still takes these ("אתם לא
            # מאחרים" AAPL) but flags the entry ("זהירות עם הכניסה" LUNR).
            if s.ext.get('mild'):
                structure -= 2
                note('structure', -2, f'a bit stretched from the average ({d150:+.0f}%)',
                     f'קצת מתוחה מהממוצע ({d150:+.0f}%)')
        elif ctx.sma150 and (ctx.sma150 - price) / atr <= NEAR_ATR:
            structure += 9
            note('structure', -3, f'just under the 150MA ({d150:+.0f}%) — not above it yet',
                 f'ממש מתחת לממוצע 150 ({d150:+.0f}%) — עוד לא מעליו')
        elif s.dir_change and s.dir_change.get('turning'):
            structure += 5
            note('structure', -7, 'below the 150MA, but starting to change direction',
                 'מתחת לממוצע 150, אבל מתחילה לשנות כיוון')
        else:
            note('structure', -12, 'below the 150MA — the anchor of the whole method is missing',
                 'מתחת לממוצע 150 — העוגן של כל השיטה חסר')
        trend = self._trend_for_grade(ctx, s)
        if trend == 'uptrend':
            structure += 10
            note('structure', 10, 'rising highs and rising lows', 'שיאים ושפלים עולים')
        elif trend == 'sideways':
            structure += 5
            note('structure', -5, 'sideways — no directional structure yet',
                 'דשדוש — עוד אין מבנה כיווני')
        elif trend == 'reclaimed':
            # above the 150 while the window's own pivots still slope down — see
            # `_trend_for_grade`. Scored as the sideways case; worded honestly.
            structure += 5
            note('structure', -5,
                 'the window still shows lower highs and lows — the 150 is the only '
                 'trend evidence yet',
                 'התקופה עדיין מראה שיאים ושפלים יורדים — ה-150 היא כרגע העדות היחידה למגמה')
        else:
            note('structure', -10, 'lower highs and lower lows', 'שיאים ושפלים יורדים')
        has_rl = bool(s.dir_change and any(
            st['done'] for st in s.dir_change['stages'] if st['key'] == 'rising_lows'))
        if has_rl:
            structure += 4
            # Only call it a LINE when the chart actually draws one — the stage is
            # also satisfied by rising weekly lows with no drawable segment.
            rl = drawn_line(s.overlays, 'rising_lows')
            if rl:
                note('structure', 4,
                     f"the rising-lows line is holding ({rl.get('touches') or 0} touches)",
                     f"קו השפלים העולים מחזיק ({rl.get('touches') or 0} נגיעות)")
            else:
                note('structure', 4, 'rising lows on the weekly', 'שפלים עולים בשבועי')
        if s.pattern:
            structure += 4
            note('structure', 4, f'{s.pattern[0]} on the chart', f'{s.pattern[1]} על הגרף')
        # VCP: a run of successive legs, each tighter AND quieter than the last
        # (setups._detect_vcp) — a stronger, more specific claim than "there is
        # SOME pattern here" (the generic +4 just above, which this stacks with
        # rather than replaces: "a pattern is present" and "this particular
        # pattern is a high-quality one" are different facts). Two-tier rather
        # than a fitted curve — PROVENANCE: reasoned from the owner's directive,
        # not measured, same status as HEADROOM_MAX/POTENTIAL_MAX when those were
        # introduced. One extra confirming leg beyond the minimum earns the full
        # bonus; sitting right at the minimum earns a partial one.
        if s.vcp:
            vcp_bonus = (VCP_STRUCTURE_BONUS if s.vcp['n_legs'] > VCP_MIN_LEGS
                         else VCP_STRUCTURE_BONUS * 0.6)
            structure += vcp_bonus
            note('structure', vcp_bonus,
                 f"{s.vcp['n_legs']} progressively tighter legs on lighter volume, "
                 f"coiling under {s.vcp['pivot']:.2f}",
                 f"{s.vcp['n_legs']} רגליים מתכווצות בהדרגה על ווליום קל יותר, "
                 f"מתכנסות מתחת ל-{s.vcp['pivot']:.2f}")
        if s.vol.get('trend') == 'rising':
            structure += 5
            note('structure', 5, 'volume expanding into the move', 'ווליום מתרחב לתוך המהלך')
        elif s.vol.get('trend') == 'flat':
            structure += 2.5
        elif not s.vcp:
            # Skipped specifically when a fresh VCP is present: a tightening base's
            # whole signature IS volume drying up leg over leg — that's the VCP note
            # just above explaining it as a POSITIVE, and firing this generic
            # "isn't expanding — without it this isn't a breakout" complaint right
            # alongside it would have the sentence arguing with itself over the same
            # underlying fact. Every chart without a detected VCP is unaffected.
            note('structure', -5,
                 "volume isn't expanding into the move — without it this isn't a breakout",
                 'הווליום לא מתרחב לתוך המהלך — ובלי זה זו לא פריצה')
        if s.candle.get('found'):
            structure += 5
            note('structure', 5, s.candle.get('label') or 'buyers candle',
                 s.candle.get('label_he') or 'נר קונים')
        # An unfilled gap-up left BELOW price. He treats one as a liability — "I am
        # aware it has a gap below, THAT is why there is a stop" (ALAB). Measured
        # over 40k entries above the 150 the sign is the other way round: E(2R) is
        # +0.279 with a gap inside 2 ATR against +0.079 with none, monotonic in
        # closeness. A gap left behind is evidence of the momentum event that made
        # it, not a debt. His instinct is right about the RISK though (drawdown
        # -14.1% vs -13.0%), which is why the gap box stays a stop anchor: the cost
        # belongs on the stop, the edge belongs here. Deliberately a nudge — a gap
        # sits below most charts in an uptrend, so anything larger is a constant
        # added to the whole universe, which just redefines the letters.
        gap_atr = self._gap_below_atr(s.overlays, price, atr)
        if gap_atr is not None and gap_atr < 5:
            structure += 2.0 if gap_atr < 2 else 1.0

        # ── HEADROOM: is there anywhere to go before the next wall? ────────────
        # "יש לה מקום לרוץ" against "הבעיה זה ההתנגדויות מעל הראש" (CRWD). Bounded
        # small on purpose — see HEADROOM_MAX: a hard wall overhead is mostly a
        # statement about WHEN, not about whether the chart is any good, and `_state`
        # already carries the "when" by routing these to "wait for the break".
        # Skipped for the dead states: a broken setup in a downtrend has "room above"
        # only because it already fell. The BONUS half is paid only where there is a
        # live thesis, so blue sky on a chart doing nothing cannot manufacture a letter.
        headroom = None
        hr = None
        if state not in ('broken', 'avoid', 'nothing_yet'):
            entry_ref = price
            if best and best.get('entry'):
                entry_ref = max(float(price), float(best['entry']))
            hr = self._headroom(ctx, s, entry_ref)
            lvl = hr.get('level')
            live = state in ('breakout_now', 'buyers_at_level', 'value_pullback',
                             'at_trigger', 'holding', 'turning')
            if lvl == 'tight':
                headroom = -HEADROOM_MAX
                note('structure', -HEADROOM_MAX,
                     f"a {hr['touches']}-touch wall at {hr['price']:.2f} is only "
                     f"{hr['atr']:.1f} ATR overhead — no room to run",
                     f"רמה עם {hr['touches']} נגיעות ב-{hr['price']:.2f} רק "
                     f"{hr['atr']:.1f} ATR מעל — אין מקום לרוץ")
            elif lvl == 'close':
                headroom = -HEADROOM_MAX / 2
                note('structure', -HEADROOM_MAX / 2,
                     f"the next wall at {hr['price']:.2f} is {hr['atr']:.1f} ATR up — "
                     f"the move is cramped",
                     f"הרמה הבאה ב-{hr['price']:.2f} במרחק {hr['atr']:.1f} ATR — "
                     f"מעט מקום למהלך")
            elif lvl == 'clear' and live:
                headroom = HEADROOM_MAX / 2
                note('structure', HEADROOM_MAX / 2,
                     f"clear to {hr['price']:.2f} — {hr['atr']:.1f} ATR of room",
                     f"פנוי עד {hr['price']:.2f} — {hr['atr']:.1f} ATR של מקום")
            elif lvl == 'open' and live:
                headroom = HEADROOM_MAX
                note('structure', HEADROOM_MAX,
                     'no hard resistance overhead — room to run',
                     'אין התנגדות משמעותית מעל — יש מקום לרוץ')
            if headroom:
                structure += headroom

        struct_scale = B['structure'] / 45.0
        structure = max(0.0, min(structure, 45.0)) * struct_scale
        notes = [(ax, w * struct_scale, en, he) if ax == 'structure' else (ax, w, en, he)
                 for ax, w, en, he in notes]

        # ── EVENT ─────────────────────────────────────────────────────────────
        ev = self._event(ctx, s, state, trigger)
        event_scale = B['event'] / 30.0
        event = ev['points'] * event_scale
        # A real event is a reason TO be here; a wait is the absence of one. Filing
        # the wait as a negative clause is what makes the sentence read "nothing has
        # happened yet" rather than listing it among the things going for the chart.
        happened = ev['key'] not in ('waiting', 'none')
        note('event', (event if happened and not ev['capped']
                       else -(B['event'] - event)), ev['en'], ev['he'])

        # ── REWARD ────────────────────────────────────────────────────────────
        rw = self._reward(ctx, s, best, thesis_pct, thesis_atr, state)
        reward = max(0.0, min(rw['ev'] + rw['prize'] + rw['room'] + rw['time'],
                              float(B['reward'])))
        for w, en, he in rw['notes']:
            note('reward', w, en, he)

        # ── RISK: is the stop real? ───────────────────────────────────────────
        # Deliberately the smallest axis, and deliberately no longer holding the
        # reward-to-risk term — that moved to REWARD, where the size of the prize
        # belongs. Owner's directive: "it's okay when there is risk, it's swing
        # trading and we are willing to do so." What is left here is the one
        # question the stop alone answers: is there a real place to be wrong.
        risk_score, stop_flag = 6.0, None       # no plan yet = unknown, not condemned
        if best:
            d = best.get('stop_atr')
            pct = best.get('risk_pct')
            sw = (best.get('stop_what') or 'the structure').replace(' (±0.5%)', '')
            swh = (best.get('stop_what_he') or 'המבנה').replace(' (±0.5%)', '')
            sp = best.get('stop')
            anchored = bool(best.get('stop_anchored'))
            # ── Width is not the question; REALITY is ─────────────────────────
            # Owner (2026-08-22): "the stop doesn't have to be very tight, it can be
            # the previous support level if it's not that far", and "a far stop is
            # not so bad a thing". This axis used to grade the WIDTH on a four-step
            # curve — ideal 16, hairline 10, ≤3 ATR 12, wider 7 — which is a
            # judgement the method does not actually make. His own doctrine is the
            # opposite: the stop is the price of admission, and a stop under a real
            # level is a good stop whether it sits 0.4 ATR away or 2.5.
            #
            # It was also incoherent with `_stop`, which picks the TIGHTEST
            # structural candidate: measured, 34% of names came back under the 0.5
            # ATR noise floor, i.e. the engine chose a hairline and then docked the
            # grade for it being one.
            #
            # So the axis is now close to binary — is there a real place to be
            # wrong — and the width only matters at the extreme where it stops
            # being a stop at all (STOP_WIDE_ATR / STOP_MAX_RISK_PCT), which still
            # caps the letter below.
            if d is not None and pct is not None:
                if d > STOP_WIDE_ATR or pct > STOP_MAX_RISK_PCT:
                    risk_score, stop_flag = 0.0, 'wide'
                    note('risk', -16, f'no sane stop from here — {pct:.0f}% of the position',
                         f'אין סטופ הגיוני מכאן — {pct:.0f}% מהכניסה')
                elif anchored:
                    risk_score = 16.0
                    note('risk', 16, f'the stop sits under {sw} ({sp:.2f}) — {d:.1f} ATR / {pct:.0f}%',
                         f'הסטופ מתחת ל{swh} ({sp:.2f}) — {d:.1f} ATR / {pct:.0f}%')
                elif d < STOP_NOISE_ATR:
                    # unanchored AND hairline: nothing behind it, and inside a day's
                    # noise. That is the one width complaint that survives.
                    risk_score, stop_flag = 8.0, 'tight'
                    note('risk', -8,
                         f'the stop sits inside a single average day ({d:.1f} ATR) with no '
                         f'structure behind it',
                         f'הסטופ בתוך יום ממוצע אחד ({d:.1f} ATR) ובלי מבנה מאחוריו')
                else:
                    risk_score = 12.0
            if anchored:
                risk_score += 6.0               # under a real structure, not an ATR guess
            else:
                note('risk', -6, 'nothing structural below — the stop is an ATR guess',
                     'אין מבנה מתחת — הסטופ הוא הערכת ATR')

        RISK_ATTAINABLE = 22.0
        risk_scale = B['risk'] / RISK_ATTAINABLE
        risk_score = max(0.0, min(risk_score, RISK_ATTAINABLE)) * risk_scale
        notes = [(ax, w * risk_scale, en, he) if ax == 'risk' else (ax, w, en, he)
                 for ax, w, en, he in notes]

        # NOTE — an "overhead congestion" penalty was built here from his
        # "הבעיה זה ההתנגדויות מעל הראש" (CRWD) and BX's "each of these is a
        # resistance", and REMOVED after measuring it. The target ladder is built out
        # of resistance levels, so counting walls between the entry and the thesis
        # charges a stock for having a ladder at all: it took TEAM (three real
        # stations — the shape this method wants) from A90 to B83, while F escaped
        # untouched only because its ladder is a single far target. That is backwards.
        # Re-reading the sources, BX is descriptive — the stations are where the move
        # PAUSES, which is why the ladder exists. Do not reintroduce without a
        # measurement that keeps TEAM above F.

        score = event + reward + structure + risk_score
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
            # tops out at C. Without this the risk axis scores a hypothetical
            # breakout entry's stop and lifts a chart with no setup on it to a B,
            # directly contradicting its own headline.
            cap('no_setup', "it hasn't done anything yet — watchlist only",
                'עוד לא עשתה שום דבר — רשימת מעקב בלבד', 2)
        if stop_flag == 'wide':
            cap('stop_wide', 'no sane stop from here — that is not a stop in this method',
                'אין סטופ הגיוני מכאן — זה לא סטופ בשיטה הזו', 1)
        # Belt-and-suspenders with the volume-spike test `_fresh_break` already
        # applies before `s.break_level` is ever set (both branches, horizontal
        # and diagonal — see micha.py): reuses `s.vol_detail['break_vol_x']`
        # (already computed for the reasons-panel text, not recomputed here) so
        # ANY path that could someday populate `break_level` without the spike
        # check still gets caught at the letter. "A break without volume is not
        # a break" — a break attempt on ordinary volume is not the event the
        # method is organised around, so this caps rather than merely dings.
        bvx = (s.vol_detail or {}).get('break_vol_x')
        if state == 'breakout_now' and bvx is not None and bvx < VOL_SPIKE_FACTOR:
            cap('weak_volume',
                f"the break came on only {bvx:.1f}× average volume — thin for a "
                f"breakout, that is the one thing missing",
                f"הפריצה הגיעה על {bvx:.1f}× מהווליום הממוצע בלבד — דק מדי לפריצה, "
                f"זה הדבר היחיד שחסר", 2)
        if hr is not None and hr.get('level') == 'tight':
            # An A means "everything lines up — מה עוד נותר לבקש". A well-defended
            # wall inside HEADROOM_TIGHT_ATR of the entry is something left to ask
            # for, so this is a CEILING rather than a penalty: at ±4 on a ~100-point
            # scale the adjustment left A and B statistically identical on room
            # (median 0.99 vs 0.98 ATR), and a term big enough to separate them
            # would have pushed well-built charts toward F.
            cap('no_room',
                f"a {hr['touches']}-touch wall {hr['atr']:.1f} ATR above the entry "
                f"({hr['price']:.2f}) — no room to run yet",
                f"רמה עם {hr['touches']} נגיעות {hr['atr']:.1f} ATR מעל הכניסה "
                f"({hr['price']:.2f}) — אין עדיין מקום לרוץ", 3)
        # Symmetric to `no_room`: that one reserves A for a chart with somewhere to
        # go WHEN a wall is what blocks it; this reserves A for a chart with
        # somewhere to go, full stop. Gated on `idx >= 4` (only when the raw score
        # would otherwise BE an A) rather than firing on every prize-less setup:
        # most setups are by design not exceptional, so an ungated call would land
        # in `caps` for the large majority of C/D 'enter' actions and silently
        # disable the floor-to-B rule below for all of them.
        if idx >= 4 and state not in ('broken', 'avoid', 'nothing_yet') and not rw['prize']:
            cap('no_potential',
                "the thesis never reaches real room beyond the ordinary target — a "
                "fine setup, but not the exceptional one an A promises",
                'התזה אף פעם לא מגיעה למקום ממשי מעבר ליעד הרגיל — סט-אפ תקין, אבל '
                'לא החריג שא\' מבטיח', 3)
        # New with the four-axis split: an A may not be issued on a setup that loses
        # money at its own measured odds. Before REWARD existed this could not be
        # expressed at all — KO graded B 81 on an E[R] of -0.27 — and now that it
        # can, it is worth stating as a ceiling too, because a negative expectancy
        # is not "one caveat", it is the whole case failing.
        if (rw['ev_r'] is not None and rw['ev_r'] < 0
                and state not in ('broken', 'avoid', 'nothing_yet')):
            cap('negative_ev',
                f"negative expectancy ({rw['ev_r']:+.2f}R) — the odds do not pay for "
                f"the risk at this target",
                f"תוחלת שלילית ({rw['ev_r']:+.2f}R) — הסיכויים לא מצדיקים את הסיכון ליעד הזה", 2)
        elif (rw['ev_r'] is not None and REWARD_EV_FULL
                and (rw['ev_r'] / REWARD_EV_FULL) <= REWARD_EV_THIN_FRAC
                and state not in ('broken', 'avoid', 'nothing_yet')):
            # One tier gentler than `negative_ev`, and reusing the exact same
            # threshold `_reward`'s own "thin expectancy" note already fires on
            # (REWARD_EV_THIN_FRAC) rather than inventing a second number that
            # could quietly disagree with it. A hard MINIMUM RATIO (e.g. 1:2.5)
            # was considered and rejected: the axis's own expectancy grid shows
            # a tight-stop 1.0-ATR/2R setup can out-earn a wide-stop 3-ATR/3R one
            # (see config.EXPECTANCY_PWIN), so gating on the raw ratio would block
            # exactly the shape the method rates highest. Gating on EXPECTANCY
            # instead — real but thin edge — catches the same "not worth an
            # unqualified enter" case without that flaw. Capped at B, not C:
            # a thin edge is a weaker `enter` than a strong one, not a reason to
            # avoid it outright the way a losing one (`negative_ev`) is.
            cap('marginal_ev',
                f"a real edge, but a thin one ({rw['ev_r']:+.2f}R) — not worth an "
                f"unqualified enter",
                f"תוחלת אמיתית אך דקה ({rw['ev_r']:+.2f}R) — לא מצדיקה כניסה חד-משמעית", 3)
        if s.ext.get('severe'):
            # Clear of BOTH the 150 and the 200 — "מהממוצעים", plural. The one he
            # declines rather than merely flags: "מתוחה ורחוקה מהממוצע. האם זו נקודת
            # כניסה מתאימה כרגע - אני לא בטוח" (RDDT, on a cup-and-handle he liked).
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

        # The letter must not contradict the recommendation. GRADE_MEANING defines
        # C as "on the watchlist — not ripe" — the literal opposite of an
        # unconditional "enter" — so a floor of C let the two keep contradicting
        # each other. AMZN surfaced it: a genuine fresh break with a further wall at
        # 'moderate' tier and an unremarkable stop combined down to a raw 65, i.e.
        # "Enter around 259.45" under a badge whose own dictionary calls it "not
        # ripe". B ("a real setup with one caveat") is the lowest letter compatible
        # with a genuine, gated entry. No cap present means nothing DISQUALIFIED the
        # entry — the low raw score is components stacking, not a structural problem.
        if action == 'enter' and not caps:
            idx = max(idx, 3)

        lo, hi = GRADE_BAND_RANGE[idx]
        score = max(lo, min(score, hi))
        shown = int(score)
        why_en, why_he = self._grade_sentence(notes, caps, GRADES[idx])
        return GRADES[idx], {
            'score': float(shown),
            # the winning EVENT candidate's own key/age, threaded through for
            # `Judgement._confirmation` — see there for why this needed adding
            # rather than already existing (nothing exposed it structurally
            # before, only folded into the event axis's text detail)
            'event_key': ev['key'], 'event_age': ev['age'],
            # the full opportunity's price and %, threaded through for
            # `Judgement._macro_target` — the SAME number the prize term of
            # REWARD is already scored against (`_opportunity_top`), just also
            # exposed as a labeled display field rather than only a percentage
            # buried in the 'potential' component's detail text
            'thesis_price': jnum(thesis_price), 'thesis_pct': jnum(thesis_pct),
            # ── 1-10, the headline number ─────────────────────────────────────
            # Owner's call (2026-08-21): "maybe switch to a 1-10 scale, it is more
            # wide and more correct to our case." Five letters is a coarse ranking
            # instrument for a watchlist — the measured universe put 85 names in C
            # and 74 in B out of 246, so two buckets held two thirds of everything
            # and the reader had no way to order inside them. Ten does.
            #
            # Derived from the same 0-100 score rather than banded separately, so it
            # can never disagree with the letter or with the axis totals that
            # produced both: every cap, floor and band boundary still operates on
            # `score`, and this is a presentation of it. The letter is kept because
            # the ceiling machinery (`cap()`) is defined in band indices and because
            # `grade_if_break`, `reasons.py` and the scan filters all key on it.
            'rating': _rating(score),
            'rating_max': 10,
            # Two sentences saying WHY this letter, composed from the notes filed by
            # the scoring above — see `_grade_sentence`.
            'summary': why_en, 'summary_he': why_he,
            'components': [
                # Reuses the SAME strings the matching `note()` calls filed rather
                # than re-deriving them from `state`. That re-derivation was the bug:
                # the row said "the trigger is happening now" whenever state was an
                # entering one, even on the branch that had just scored a reduced
                # total for "the wall that caps this move is still overhead".
                {'key': 'event', 'label': 'Event', 'label_he': 'אירוע',
                 'got': jnum(event), 'max': B['event'],
                 'detail': ev['en'], 'detail_he': ev['he']},
                {'key': 'reward', 'label': 'Reward', 'label_he': 'תשואה',
                 'got': jnum(reward), 'max': B['reward'],
                 'detail': (f"expectancy {rw['ev_r']:+.2f}R"
                            + (f", thesis {thesis_pct:.0f}% out" if thesis_pct else '')
                            if rw['ev_r'] is not None else 'no thesis priced yet'),
                 'detail_he': (f"תוחלת {rw['ev_r']:+.2f}R"
                               + (f", התזה {thesis_pct:.0f}% מכאן" if thesis_pct else '')
                               if rw['ev_r'] is not None else 'אין עדיין תזה מתומחרת')},
                {'key': 'structure', 'label': 'Structure', 'label_he': 'מבנה',
                 'got': jnum(structure), 'max': B['structure'],
                 'detail': 'structure on the chart', 'detail_he': 'המבנה על הגרף'},
                {'key': 'risk', 'label': 'Risk / stop', 'label_he': 'סיכון / סטופ',
                 'got': jnum(risk_score), 'max': B['risk'],
                 'detail': (f"stop {best['risk_pct']:.1f}% / {best['stop_atr']:.1f} ATR"
                            if best and best.get('risk_pct') is not None else 'no stop defined yet'),
                 'detail_he': (f"סטופ {best['risk_pct']:.1f}% / {best['stop_atr']:.1f} ATR"
                               if best and best.get('risk_pct') is not None else 'אין סטופ מוגדר')},
            ] + ([
                # a bounded ± adjustment already counted inside `structure`, surfaced
                # so the reader can see what the wall cost. The wording follows the
                # SIGN: an earlier version read "clear for 0.8 ATR" beside a -2.0.
                {'key': 'headroom', 'label': 'Room above', 'label_he': 'מקום מעל',
                 'got': jnum(headroom), 'max': HEADROOM_MAX, 'adjustment': True,
                 'detail': self._headroom_detail(hr, False),
                 'detail_he': self._headroom_detail(hr, True)},
            ] if headroom else []) + ([
                # counted inside `reward`, surfaced so the size of the prize is
                # visible on its own line. Mirrors whichever path (ATR-normalized or
                # raw-percent) actually qualified the tier — showing the ATR distance
                # unconditionally used to state a number that had nothing to do with
                # the tier earned whenever the raw-percent floor was what fired.
                {'key': 'potential', 'label': 'Potential', 'label_he': 'פוטנציאל',
                 'got': jnum(rw['prize']), 'max': REWARD_PRIZE_MAX, 'adjustment': True,
                 # quoted in percent only — the unit the money is in
                 'detail': f"the thesis target is {thesis_pct:.0f}% out",
                 'detail_he': f"יעד התזה במרחק {thesis_pct:.0f}%"},
            ] if rw['prize'] else []) + ([
                # counted inside `reward`; one-sided now — see TIME_EFFICIENCY_MAX
                {'key': 'time', 'label': 'Time to target', 'label_he': 'זמן ליעד',
                 'got': jnum(rw['time']), 'max': TIME_EFFICIENCY_MAX, 'adjustment': True,
                 'detail': f"~{rw['days']:.0f} trading days to the thesis target",
                 'detail_he': f"~{rw['days']:.0f} ימי מסחר ליעד"},
            ] if rw['time'] else []),
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
        axis_order = {'structure': 0, 'event': 1, 'reward': 2, 'risk': 3}
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
            elif grade == 'A':
                # his literal A-grade closer — earned only when nothing scored
                # against AND the letter is actually the one he says it about.
                risk = next((n for n in pos if n[0] == 'risk'), None)
                tail_en = ((risk[2] + ' — ') if risk else '') + 'what more is there to ask for.'
                tail_he = ((risk[3] + ' — ') if risk else '') + 'מה עוד נותר לבקש.'
            else:
                # No note scored against it, and yet it is not an A: the points are
                # missing rather than deducted — an axis that scores zero has nothing
                # to file, so it cannot appear in `neg`. KO is the case that exposed
                # this, closing a D 39 with "מה עוד נותר לבקש" over a reward axis of
                # 0/34. Say what the arithmetic says instead of borrowing his
                # top-grade sentence.
                tail_en = 'Nothing scores against it — there is just not much here yet.'
                tail_he = 'אין משהו שפועל נגדה — פשוט אין פה עדיין הרבה.'
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
            # A bound cap describes a real problem with THIS entry — usually no room
            # to run, occasionally a stop that isn't sane. Leaving it only in the
            # separate `warnings` array is how the panel produced its worst reading:
            # NXPI's call said "Enter around 225.56, stop 216.58" with no hint that a
            # 2-touch wall sits 0.3 ATR overhead — a fact this SAME breakdown had
            # already computed. `_grade_sentence` already leads a capped letter with
            # its binding cap ("it IS the reason the grade is what it is"); the
            # sentence a reader actually acts on needs the same rule, not a milder
            # one. Reuses the cap's own label — no new judgment, just no longer
            # discarding one that was already made.
            binding = next((c for c in breakdown['caps'] if c['bound']), None)
            if binding:
                lbl = binding['label']
                call += f" {lbl[0].upper()}{lbl[1:]}."
                call_he += f" {binding['label_he']}."
        elif action == 'wait_trigger' and trigger:
            _stop_en = (f" Stop {best['stop']:.2f}." if best and best.get('stop') else "")
            _stop_he = (f" סטופ {best['stop']:.2f}." if best and best.get('stop') else "")
            if s.break_level:
                # This is the case the near-tier wall veto produces (see `_state`):
                # a REAL break just happened — `s.break_level` only holds a fresh one
                # — but a well-defended wall sits close enough overhead that it isn't
                # a clean trigger yet. Saying only "break above X" here would erase
                # what actually happened and read identically to a chart that has done
                # nothing at all. Owner's ask: make this read as a WARNING — it broke
                # something real, AND there is a hard wall right there — not as the
                # generic "still coiled" copy.
                call = (f"Broke {s.break_level:.2f}, but a hard wall is close — wait "
                        f"for {trigger['price']:.2f} too.{_stop_en}")
                call_he = (f"פרצה את {s.break_level:.2f}, אבל קיר קשה קרוב — להמתין "
                           f"גם ל-{trigger['price']:.2f}.{_stop_he}")
            else:
                # His own shape, and his own order: the price FIRST, then the refusal
                # to act before it, then the stop — "פריצה משמעותית מעל 21.45$", "מעל
                # 552. אם לא עוברת מעל אין טרייד", "אין מה להיכנס לפני" (FLY), "חכו
                # לפריצה שלא סתם תעופו בסטופ" (SEDG). The previous wording opened with
                # "אין כניסה עדיין — התראה על…", which is alert-console language: it
                # buries the one number he always leads with and describes the
                # mechanism instead of the trade.
                call = (f"Break above {trigger['price']:.2f} — no trade before that."
                        f"{_stop_en}")
                call_he = (f"פריצה מעל {trigger['price']:.2f} — לפני זה אין טרייד."
                           f"{_stop_he}")
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
        if state == 'turning':
            n = (s.dir_change or {}).get('stages_done') or 4
            return (f"Bearish to bullish — {n} of the four stages are done, breakout "
                    f"included, and it is still under the 150MA. The average is the entry.",
                    f"שינוי כיוון — {n} מתוך ארבעת השלבים הושלמו, כולל הפריצה, והמניה "
                    f"עדיין מתחת לממוצע 150. הממוצע הוא נקודת הכניסה.")
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
