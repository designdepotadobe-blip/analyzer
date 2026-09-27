"""
book.py — the grade, by the book.

Micha never scores a chart. He writes a verdict and the conditions around it, and
every 2025-2026 post and live has the same skeleton:

    "מעל נקודת הפריצה. מעל ממוצע 150. קרוב לממוצע. מה עוד נותר לבקש" (GEV)
    "חכו לפריצה מעל X ... סטופ מתחת ל-Y ... פוטנציאל Z%"
    "רצה ארבעה ימים רצופים בלי תיקון — לא נקודת כניסה" (NOW, 20/20 live 06-01)
    "מדווחת שבוע הבא. אז זהירות!!!!!"

The owner needs a grade anyway, to prefer one stock over another on a watchlist. So
this grade is that skeleton turned into a checklist and nothing else: six things he
checks, each worth what it is worth to him, then the few things that make him say
"not now", then the few that make him say "not this stock". Every point on the board
is a line the reader can see, in his words, with a ✓ or a ✗.

    the 150 (anchor + its direction) 20   "קונים רק מעל הקו", on a line that is going up
    location (close to the 150)      15   "קרוב לממוצע" — the stop is right there
    the event (what happened)        25   break / retest / buyers at the line / waiting
    volume                           10   "התנאי לפריצה - ווליום גבוה"
    the stop                         15   a real line to be wrong at, not a guess
    potential + room                 15   the measured move, and no wall on its head

What it deliberately does NOT read: the expectancy grid, time-to-target and the other
measured-outcome terms in `verdict._grade`. Those answer a question he never asks (and
the outcome harness showed the grade built on them does not predict returns either).
They stay in the payload as information; the letter comes from the book.

This is a swing system that wants profit AND wants to be picky, so the letters are
strict on purpose: A only for a trade you can take today with everything lined up,
waiting setups top out at B however pretty the chart, and anything under the 150,
under $1B or with no sane stop cannot reach the top half at all.
"""

from __future__ import annotations

from typing import Optional

from config import (
    CHASE_PAST_TRIGGER_ATR,
    EARNINGS_SOON_DAYS,
    EVENT_BASIS,
    MA150_RECLAIM_GRACE_BARS,
    NEAR_ATR,
    STOP_MAX_RISK_PCT,
    STOP_WIDE_ATR,
    jnum,
)

WEIGHTS = {'trend': 20, 'location': 15, 'event': 25, 'volume': 10, 'stop': 15, 'potential': 15}

# Letters on the 0-100 board. Strict: an A is 80+ AND an entry (see CAPS below).
BANDS = [('A', 80.0), ('B', 65.0), ('C', 50.0), ('D', 35.0), ('F', 0.0)]

ENTERING_ACTIONS = ('enter',)
WAITING_ACTIONS = ('wait_trigger', 'wait_buyers', 'wait_pullback', 'wait_event', 'watch')

# Headline word per action, in his register.
VERDICT_HE = {
    'enter': 'כניסה',
    'wait_trigger': 'לחכות לפריצה',
    'wait_buyers': 'לחכות לקונים',
    'wait_pullback': 'לא לרדוף — לחכות לתיקון',
    'wait_event': 'לחכות לדוח',
    'hold': 'להחזיק — לא כניסה חדשה',
    'watch': 'מעקב + התראה',
    'out': 'אין סט אפ',
    'avoid': 'לא רלוונטית',
}
VERDICT_EN = {
    'enter': 'Enter',
    'wait_trigger': 'Wait for the break',
    'wait_buyers': 'Wait for buyers',
    'wait_pullback': "Don't chase — wait for a pullback",
    'wait_event': 'Wait for the report',
    'hold': 'Hold — no new entry',
    'watch': 'Watchlist + alert',
    'out': 'No setup',
    'avoid': 'Not relevant',
}


def run_phrase(ext: dict) -> tuple:
    """
    How the run into the entry is said — (en, he). `ran_hot` fires two ways (see
    micha._ext20): a streak of up days, or a big move over the last week whatever the
    day count. Printing "ran 1 days in a row (+17%)" for the second is nonsense, so
    each gets its own sentence.
    """
    n = ext.get('run_days') or 0
    pct = ext.get('run_pct') or 0
    if n >= 3:
        return (f'ran {n} days in a row ({pct:+.0f}%)', f'רצה {n} ימים ברצף ({pct:+.0f}%)')
    return (f'up {pct:+.0f}% in the last week', f'עלתה {pct:+.0f}% בשבוע האחרון')


def _letter(score: float) -> str:
    return next(l for l, lo in BANDS if score >= lo)


def _item(key, pts, en, he, detail_en='', detail_he=''):
    mx = WEIGHTS[key]
    pts = max(0.0, min(float(pts), float(mx)))
    return {'key': key, 'points': jnum(pts), 'max': mx,
            'ok': 'yes' if pts >= 0.75 * mx else 'partial' if pts >= 0.35 * mx else 'no',
            'label': en, 'label_he': he, 'detail': detail_en, 'detail_he': detail_he}


# ── The book target: the number he actually quotes ─────────────────────────────

def book_target(ctx, s, entry: float) -> Optional[dict]:
    """
    The potential he would quote, not the farthest price the engine can find.

    He quotes the MEASURED MOVE — "לוקחים את עומק הספל ... קופי פסטה, מדביקים —
    פוטנציאל של 96%" — and checks it against real prices on the left ("157 ... תסתכלו
    שמאלה, 152"). A Fibonacci 2.0 extension or a record high three years back is a
    station he may mention, never "the potential". So: the pattern projection when
    there is one; otherwise the farthest REAL price on the ladder (a wall, a flipped
    level, the prior high, a gap to close); a Fibonacci level only when nothing else
    exists. The near station is returned beside it as the conservative target.
    """
    if not entry:
        return None
    ups = [t for t in (s.targets or []) if t.get('price') and t['price'] > entry * 1.002]
    cup = (s.overlays or {}).get('cup') or {}
    proj = None
    if cup.get('target_big') and cup['target_big'] > entry * 1.002:
        proj = (float(cup['target_big']), 'cup measured move', 'מהלך מדוד של הקאפ')
    if proj is None:
        pm = [t for t in ups if t.get('source') in ('pattern_projection', 'measured_move')]
        if pm:
            t = max(pm, key=lambda t: t['price'])
            proj = (float(t['price']), t.get('label') or 'measured move',
                    t.get('label_he') or 'מהלך מדוד')
    if proj is None:
        real = [t for t in ups if t.get('source') in ('resistance', 'flipped_level', 'ath', 'gap',
                                                      'channel_rail', 'fib_bounce')]
        pool = real or ups
        if pool:
            t = max(pool, key=lambda t: t['price'])
            proj = (float(t['price']), t.get('label') or 'target', t.get('label_he') or 'יעד')
    if proj is None:
        return None
    price, en, he = proj
    first = min(ups, key=lambda t: t['price']) if ups else None
    return {
        'price': jnum(price), 'pct': jnum((price / entry - 1) * 100),
        'what': en, 'what_he': he,
        'first_price': jnum(first['price']) if first and first['price'] < price else None,
        'first_pct': (jnum((first['price'] / entry - 1) * 100)
                      if first and first['price'] < price else None),
        'first_what_he': (first.get('label_he') if first and first['price'] < price else None),
    }


# ── The grade ──────────────────────────────────────────────────────────────────

def grade(j, ctx, s, state: str, action: str, trigger, options, earn, small_cap) -> dict:
    """
    `j` is the Judgement instance — its `_event`, `_headroom` and `_best_option` are
    reused rather than re-derived, so the book can never disagree with the state
    machine about what happened, what is overhead or which plan is being graded.
    """
    price, atr = ctx.price, ctx.atr
    best = j._best_option(options, action)
    items, minus, caps = [], [], []
    d150 = ((price / ctx.sma150 - 1) * 100) if ctx.sma150 else None
    ma_dir = getattr(ctx, 'ma150_dir', 'unknown')
    rc = s.ma150_reclaim or {}
    fresh_reclaim = rc.get('bars') is not None and rc['bars'] <= MA150_RECLAIM_GRACE_BARS

    # ── 1. The 150: which side, and which way it points ────────────────────────
    dir_he = {'rising': 'עולה', 'flat': 'שטוח', 'falling': 'יורד'}.get(ma_dir, '')
    dir_en = {'rising': 'rising', 'flat': 'flat', 'falling': 'falling'}.get(ma_dir, '')
    if ctx.above_150:
        if ma_dir == 'rising':
            pts, he, en = 20, 'מעל ממוצע 150, והממוצע עולה', 'Above a rising 150MA'
        elif ma_dir == 'flat':
            pts, he, en = 16, 'מעל ממוצע 150, הממוצע שטוח', 'Above a flat 150MA'
        elif fresh_reclaim:
            pts, he, en = (13, f"חזרה מעל ממוצע 150 לפני {rc['bars']} ימים — הממוצע עוד יורד",
                           f"Reclaimed the 150MA {rc['bars']} bars ago — the average still falls")
        else:
            pts, he, en = (6, 'מעל ממוצע 150, אבל הממוצע יורד — זו לא שיטת ה-150',
                           'Above the 150MA, but the average is falling — not the 150 method')
    elif ctx.sma150 and atr and (ctx.sma150 - price) / atr <= NEAR_ATR:
        pts, he, en = (6, 'ממש מתחת לממוצע 150 — צריכה לעבור את הקו',
                       'Just under the 150MA — it has to cross the line')
    elif state == 'turning':
        pts, he, en = (5, 'מתחת לממוצע 150, משנה כיוון', 'Below the 150MA, turning')
    else:
        pts, he, en = (0, 'מתחת לממוצע 150 — קונים רק מעל הקו',
                       'Below the 150MA — he only buys above the line')
    items.append(_item('trend', pts, en, he,
                       f"150MA {dir_en} {ctx.ma150_slope_pct:+.1f}% / 20 bars"
                       if getattr(ctx, 'ma150_slope_pct', None) is not None else '',
                       f"ממוצע 150 {dir_he} {ctx.ma150_slope_pct:+.1f}% ב-20 ימים"
                       if getattr(ctx, 'ma150_slope_pct', None) is not None else ''))

    # ── 2. Location: close to the average ──────────────────────────────────────
    lvl = (s.ext or {}).get('level')
    if d150 is None:
        pts, he, en = 0, 'אין ממוצע 150', 'No 150MA'
    elif ctx.above_150:
        if lvl == 'severe':
            pts, he, en = (0, f'רחוקה משני הממוצעים ({d150:+.0f}%)',
                           f'Far from both averages ({d150:+.0f}%)')
        elif lvl == 'stretched':
            pts, he, en = (3, f'מתוחה ורחוקה מהממוצע ({d150:+.0f}%)',
                           f'Stretched far from the average ({d150:+.0f}%)')
        elif lvl == 'mild':
            pts, he, en = (9, f'קצת מתוחה מהממוצע ({d150:+.0f}%)',
                           f'A bit stretched from the average ({d150:+.0f}%)')
        else:
            pts, he, en = (15, f'קרובה לממוצע ({d150:+.0f}%) — הסטופ ממש שם',
                           f'Close to the average ({d150:+.0f}%) — the stop is right there')
    elif atr and (ctx.sma150 - price) / atr <= NEAR_ATR * 2:
        pts, he, en = (8, f'צמודה לממוצע מלמטה ({d150:+.0f}%)',
                       f'Right under the average ({d150:+.0f}%)')
    else:
        pts, he, en = (0, f'רחוקה מתחת לממוצע ({d150:+.0f}%)',
                       f'Far under the average ({d150:+.0f}%)')
    items.append(_item('location', pts, en, he))

    # ── 3. The event — reuses the state machine's own reading ──────────────────
    ev = j._event(ctx, s, state, trigger)
    pts = WEIGHTS['event'] * min(ev['points'], EVENT_BASIS) / EVENT_BASIS
    items.append(_item('event', pts, ev['en'], ev['he']))

    # ── 4. Volume ─────────────────────────────────────────────────────────────
    vd = s.vol_detail or {}
    vt = (s.vol or {}).get('trend')
    streak = (s.vol or {}).get('falling_streak', 0) or 0
    bvx = vd.get('break_vol_x')
    if ev['key'] in ('hard_break', 'soft_break', 'dir_change') and bvx is not None:
        if bvx >= 2.0:
            pts, he, en = 10, f'פריצה עם ווליום ({bvx:.1f}× מהממוצע)', f'Broke on volume ({bvx:.1f}× avg)'
        elif bvx >= 1.5:
            pts, he, en = 8, f'פריצה עם ווליום ({bvx:.1f}× מהממוצע)', f'Broke on volume ({bvx:.1f}× avg)'
        else:
            pts, he, en = (3, f'פריצה על ווליום דק ({bvx:.1f}×)',
                           f'Broke on thin volume ({bvx:.1f}×)')
    elif vd.get('quiet_pullback'):
        pts, he, en = (8, 'הירידה על ווליום יורד — המוכרים מתמעטים',
                       'Pulling back on drying volume — sellers are thinning out')
    elif vt == 'rising':
        pts, he, en = 8, 'ווליום מתרחב', 'Volume expanding'
    elif vt == 'falling' and streak > 2:
        pts, he, en = (0, f'ווליום יורד {streak} ימים ברצף — אין עניין',
                       f'Volume falling {streak} days running — nobody is interested')
    elif vt == 'falling':
        pts, he, en = 3, 'ווליום מתייבש', 'Volume drying up'
    else:
        pts, he, en = 5, 'ווליום יציב', 'Volume steady'
    items.append(_item('volume', pts, en, he))

    # ── 5. The stop: a real line to be wrong at ────────────────────────────────
    stop_wide = False
    if not best or best.get('stop') is None or best.get('stop_atr') is None:
        pts, he, en = 0, 'אין סטופ מוגדר', 'No stop defined'
    else:
        d, rp = float(best['stop_atr']), float(best.get('risk_pct') or 0)
        sw_he = (best.get('stop_what_he') or 'המבנה').replace(' (±0.5%)', '')
        sw_en = (best.get('stop_what') or 'the structure').replace(' (±0.5%)', '')
        tail_he, tail_en = f" ({best['stop']:.2f}, −{rp:.1f}%)", f" ({best['stop']:.2f}, −{rp:.1f}%)"
        if d > STOP_WIDE_ATR or rp > STOP_MAX_RISK_PCT:
            stop_wide = True
            pts, he, en = (0, f'אין סטופ הגיוני מכאן — {rp:.0f}%', f'No sane stop from here — {rp:.0f}%')
        elif not best.get('stop_anchored'):
            pts, he, en = (6, 'סטופ לפי ATR — אין מבנה מתחת' + tail_he,
                           'Stop by ATR — nothing structural below' + tail_en)
        elif d <= 2.0:
            pts, he, en = 15, f'סטופ מתחת ל{sw_he}' + tail_he, f'Stop under {sw_en}' + tail_en
        elif d <= 3.0:
            pts, he, en = 11, f'סטופ מתחת ל{sw_he}, קצת רחוק' + tail_he, f'Stop under {sw_en}, a bit far' + tail_en
        else:
            pts, he, en = 7, f'סטופ רחוק מתחת ל{sw_he}' + tail_he, f'Far stop under {sw_en}' + tail_en
    items.append(_item('stop', pts, en, he))

    # ── 6. Potential, and room to run ──────────────────────────────────────────
    entry = float(best['entry']) if best and best.get('entry') else price
    tgt = book_target(ctx, s, entry)
    pct = tgt['pct'] if tgt else None
    if pct is None:
        pts, he, en = 0, 'אין יעד מעל הכניסה', 'No target above the entry'
    else:
        pts = 12 if pct >= 30 else 10 if pct >= 20 else 7 if pct >= 12 else 4 if pct >= 8 else 0
        he = f"פוטנציאל {pct:+.0f}% — {tgt['what_he']} ({tgt['price']:.2f})"
        en = f"Potential {pct:+.0f}% — {tgt['what']} ({tgt['price']:.2f})"
    hr = j._headroom(ctx, s, max(price, entry)) if state not in ('broken', 'avoid') else {}
    room = (hr or {}).get('level')
    if room == 'tight':
        pts -= 5
        he += f" · קיר עם {hr.get('touches') or 0} נגיעות ממש מעל ({hr['price']:.2f})"
        en += f" · a {hr.get('touches') or 0}-touch wall right overhead ({hr['price']:.2f})"
    elif room == 'close':
        pts -= 2
        he += f" · התנגדות קרובה ב-{hr['price']:.2f}"
        en += f" · resistance close at {hr['price']:.2f}"
    elif room in ('clear', 'open') and pct is not None:
        pts += 3
        he += ' · יש מקום לרוץ'
        en += ' · room to run'
    items.append(_item('potential', pts, en, he))

    # ── What makes him say "not now" — deductions ──────────────────────────────
    ext = s.ext or {}
    if ext.get('ran_hot'):
        r_en, r_he = run_phrase(ext)
        minus.append({'key': 'ran_hot', 'points': -8,
                      'label': f'{r_en} — too late to chase',
                      'label_he': f'{r_he} — מאוחר לרדוף'})
    if (s.break_level and atr and state == 'breakout_now'
            and (price - s.break_level) / atr > CHASE_PAST_TRIGGER_ATR):
        minus.append({'key': 'chase', 'points': -5,
                      'label': f'already {(price - s.break_level) / atr:.1f} ATR past the break',
                      'label_he': f'כבר {(price - s.break_level) / atr:.1f} ATR מעל הפריצה'})
    if earn is not None and earn <= EARNINGS_SOON_DAYS:
        minus.append({'key': 'earnings', 'points': -5,
                      'label': f'earnings in {earn} days — no entry before the report',
                      'label_he': f'דוח בעוד {earn} ימים — לא נכנסים לפני דוח'})

    raw = sum(i['points'] for i in items) + sum(m['points'] for m in minus)
    score = max(0.0, min(100.0, raw))

    # ── What makes him say "not this stock" — ceilings ─────────────────────────
    def cap(key, ceiling, en, he):
        caps.append({'key': key, 'ceiling': ceiling, 'bound': score > ceiling,
                     'label': en, 'label_he': he})

    if state == 'avoid':
        cap('avoid', 25, 'below the 150MA in a downtrend — nothing to do with it',
            'מתחת לממוצע 150 במגמה יורדת — אין מה להתעסק איתה')
    if state == 'broken':
        cap('broken', 30, 'the setup is over — assume the stop was hit',
            'הסט אפ נגמר — להניח שהסטופ קפץ')
    if state == 'nothing_yet':
        cap('nothing_yet', 49, "it hasn't done anything yet — watchlist only",
            'עוד לא עשתה כלום — מעקב בלבד')
    if not ctx.above_150 and state not in ('avoid', 'broken'):
        tk = (trigger or {}).get('kind')
        if state == 'turning' or tk == 'ma150':
            cap('below_150', 64, 'under the 150MA — speculative until it crosses the line',
                'מתחת לממוצע 150 — ספקולטיבי עד שתעבור את הקו')
        else:
            cap('below_150', 49, 'under the 150MA — outside the method',
                'מתחת לממוצע 150 — מחוץ לשיטה')
    if small_cap:
        cap('small_cap', 49, 'under $1B — outside the 150 method', 'מתחת ל-1 מיליארד — מחוץ לשיטה')
    if stop_wide:
        cap('stop_wide', 49, 'no sane stop from here', 'אין סטופ הגיוני מכאן')
    # "עד אז אתם בטרייד מאוד קטן שלפעמים הוא לא שווה" (20/20 live 2026-05-28): a swing
    # trade has to have somewhere to go. Under 10% to the target he would quote it is
    # not a setup worth choosing over the others, however clean the chart.
    if pct is not None and pct < 10 and state not in ('avoid', 'broken'):
        cap('small_move', 64, f'only {pct:+.0f}% to the target — a small trade, not worth choosing',
            f'רק {pct:+.0f}% עד היעד — טרייד קטן שלא בהכרח שווה')
    # The strict part. An A is a trade you can take TODAY with everything lined up —
    # "מה עוד נותר לבקש". A chart he likes that still has to break is the top of the
    # watchlist, which is a B, however pretty; one he is holding is not a new entry.
    if action in WAITING_ACTIONS or action == 'hold':
        cap('not_an_entry', 79, 'not an entry yet — the top of the watchlist, not a trade',
            'עוד לא נקודת כניסה — ראש רשימת המעקב, לא טרייד')

    for c in caps:
        score = min(score, c['ceiling'])
    letter = _letter(score)
    rating = max(1, min(10, int(round(score / 10.0))))

    # ── Why: what carries it, and the one thing holding it back ────────────────
    strong = sorted((i for i in items if i['ok'] == 'yes'),
                    key=lambda i: -i['points'] / i['max'])[:2]
    weak_i = sorted((i for i in items if i['ok'] != 'yes'),
                    key=lambda i: (i['points'] - i['max']))
    bound = [c for c in caps if c['bound']]
    if bound:
        worst = min(bound, key=lambda c: c['ceiling'])
        held_en, held_he = worst['label'], worst['label_he']
    elif minus:
        m = min(minus, key=lambda m: m['points'])
        held_en, held_he = m['label'], m['label_he']
    elif weak_i:
        held_en, held_he = weak_i[0]['label'], weak_i[0]['label_he']
    else:
        held_en, held_he = 'nothing left to ask for', 'מה עוד נותר לבקש'
    lead_he = '. '.join(i['label_he'] for i in strong) or 'אין פה הרבה בעד'
    lead_en = '. '.join(i['label'] for i in strong) or 'Not much going for it'
    why_he = f"{lead_he}. {'מה שחסר: ' if held_he != 'מה עוד נותר לבקש' else ''}{held_he}."
    why_en = f"{lead_en}. {'Holding it back: ' if held_en != 'nothing left to ask for' else ''}{held_en}."

    return {
        'score': jnum(score), 'raw': jnum(raw), 'letter': letter, 'rating': rating,
        'rating_max': 10,
        'verdict': VERDICT_EN.get(action, action), 'verdict_he': VERDICT_HE.get(action, action),
        'items': items, 'minus': minus, 'caps': caps,
        'target': tgt,
        'why': why_en, 'why_he': why_he,
    }
