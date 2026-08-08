"""
reasons.py — the argument behind the call.

The verdict says WHAT to do. This says WHY, in the terms Micha argues in: concrete
numbers, on this chart, today. Every line is computed from the live data — nothing
here is remembered from a previous post or a previous session.

It is grouped the way he actually walks a chart:

    trend    the 150 anchor, the direction, and HOW LONG it has held
    level    the S/R map: what is overhead, what is under, how well tested
    volume   the two bars that matter — the break bar and the pullback
    pattern  the structure that is actually on the chart, measured
    strength the stock against the market ("עדיין יותר זולה מהסנפ")
    risk     where the stop is, what it costs, what the trade is worth
    timing   what has to happen, and what would stop it happening

Each item carries a `stance`:
    for      an argument FOR the call
    against  an argument against it — kept, not hidden, because "what's missing" is
             half of his read ("עוד לא עשתה שום דבר", "הבעיה היחידה היא הווליום")
    note     context that colours the read without arguing either way
"""

from __future__ import annotations

from config import EARNINGS_SOON_DAYS, EXTENDED_ATR, VOL_SPIKE_FACTOR, jnum
from verdict import drawn_line

GROUP_LABELS = {
    'trend':    ('Trend & the 150', 'מגמה וממוצע 150'),
    'level':    ('The level map', 'מפת הרמות'),
    'volume':   ('Volume', 'ווליום'),
    'pattern':  ('Structure', 'מבנה'),
    'strength': ('Vs the market', 'מול השוק'),
    'risk':     ('Risk', 'סיכון'),
    'timing':   ('Timing', 'תזמון'),
}


def _bars_phrase(n: int) -> tuple:
    """Trading bars → the way a person says it."""
    if n >= 252:
        y = n / 252
        return (f'over {y:.1f} years', f'יותר מ-{y:.1f} שנים')
    if n >= 21:
        mo = n / 21
        return (f'about {mo:.0f} months', f'בערך {mo:.0f} חודשים')
    if n >= 5:
        return (f'about {n // 5} weeks', f'בערך {n // 5} שבועות')
    return (f'{n} days', f'{n} ימים')


class Reasons:
    def build(self, ctx, s, j) -> list:
        """Returns [{key, label, label_he, items:[{stance, en, he}]}] — empty groups dropped."""
        g: dict[str, list] = {k: [] for k in GROUP_LABELS}

        def add(group, stance, en, he):
            g[group].append({'stance': stance, 'en': en, 'he': he})

        self._trend(ctx, s, add)
        self._level(ctx, s, j, add)
        self._volume(ctx, s, j, add)
        self._pattern(ctx, s, add)
        self._strength(ctx, s, add)
        self._risk(ctx, s, j, add)
        self._timing(ctx, s, j, add)

        out = []
        for k, items in g.items():
            if items:
                en, he = GROUP_LABELS[k]
                out.append({'key': k, 'label': en, 'label_he': he, 'items': items})
        return out

    # ── trend ────────────────────────────────────────────────────────────────

    def _trend(self, ctx, s, add):
        if ctx.sma150:
            d = (ctx.price / ctx.sma150 - 1) * 100
            if ctx.above_150:
                add('trend', 'for',
                    f'Above the 150MA at {ctx.sma150:.2f} ({d:+.1f}%) — the anchor of the method',
                    f'מעל ממוצע 150 ב-{ctx.sma150:.2f} ({d:+.1f}%) — העוגן של השיטה')
            else:
                add('trend', 'against',
                    f'Below the 150MA at {ctx.sma150:.2f} ({d:+.1f}%) — until it reclaims it there is no setup',
                    f'מתחת לממוצע 150 ב-{ctx.sma150:.2f} ({d:+.1f}%) — עד שלא חוזרת מעליו אין סט אפ')
            near = abs(ctx.price - ctx.sma150) / ctx.atr
            if ctx.above_150:
                if near <= EXTENDED_ATR:
                    add('trend', 'for',
                        f'Only {near:.1f} ATR off the average — close enough for a tight stop',
                        f'רק {near:.1f} ATR מהממוצע — מספיק קרוב לסטופ צמוד')
                elif d > 15:
                    add('trend', 'against',
                        f'{d:.0f}% above the 150 — a great chart, but no good stop from up here',
                        f'{d:.0f}% מעל ממוצע 150 — גרף מעולה, אבל אין מכאן סטופ טוב')

        dur = s.duration
        if dur and dur.get('run_bars'):
            en, he = _bars_phrase(dur['run_bars'])
            if dur['above']:
                add('trend', 'for',
                    f'Has held above the 150 for {en} ({dur["pct_above_window"]:.0f}% of the window)',
                    f'שומרת מעל ממוצע 150 כבר {he} ({dur["pct_above_window"]:.0f}% מהתקופה)')
            else:
                add('trend', 'against',
                    f'Has been under the 150 for {en}',
                    f'מתחת לממוצע 150 כבר {he}')

        if s.trend == 'uptrend':
            # `trend` is a slope through two years of swings, so a name that tripled
            # and then halved still reads "up". Saying "a real uptrend" about a chart
            # that is under its 150 and 30% behind the market is the kind of stale
            # read he deletes the drawings over. State the slope, then the caveat.
            stale = (not ctx.above_150) or (s.rel_strength or {}).get('lead') == 'lagging'
            rl = drawn_line(s.overlays, 'rising_lows')
            if stale:
                add('trend', 'note',
                    'The multi-year slope of highs and lows still points up, but recent action does not',
                    'שיפוע השיאים והשפלים לטווח הארוך עדיין עולה, אבל התנועה האחרונה לא')
            elif rl and not rl.get('broke'):
                # The strong version of the claim, and the only one allowed to say
                # "line": there is one on the chart and the reader can go look at it.
                n = rl.get('touches') or 0
                add('trend', 'for',
                    f'Rising highs and lows — and the rising-lows line on the chart is holding ({n} touches)',
                    f'שיאים ושפלים עולים — וקו השפלים העולים על הגרף מחזיק ({n} נגיעות)')
            else:
                # Same fact, honestly scoped. `trend` is a polyfit slope through the
                # whole window; his lines are pivot-snapped segments kept only while
                # price is testing them, so an uptrend routinely has no drawable
                # line. Saying "a real uptrend" beside a chart with nothing drawn on
                # it is what makes a reader stop believing the panel.
                add('trend', 'for',
                    'Rising highs and lows across the window — no line is drawn, price is not testing one right now',
                    'שיאים ושפלים עולים לאורך התקופה — אין קו מצויר, המחיר לא בודק אף קו כרגע')
        elif s.trend == 'downtrend':
            add('trend', 'against', 'Lower highs and lower lows',
                'שיאים ושפלים יורדים')
        else:
            add('trend', 'note', 'Sideways — no directional structure yet',
                'דשדוש — אין עדיין מבנה כיווני')

        dc = s.dir_change
        if dc and dc.get('applicable'):
            miss_en = [x['label'] for x in dc['stages'] if not x['done']]
            miss_he = [x['label_he'] for x in dc['stages'] if not x['done']]
            if dc['confirmed']:
                add('trend', 'for',
                    'Direction change complete — volume, turn candle, rising lows and the breakout',
                    'שינוי כיוון מלא — ווליום, נר היפוך, שפלים עולים ופריצה')
            elif dc['stages_done'] >= 2:
                add('trend', 'note',
                    f'Direction change {dc["stages_done"]}/4 — still missing: {", ".join(miss_en)}',
                    f'שינוי כיוון {dc["stages_done"]}/4 — עוד חסר: {", ".join(miss_he)}')

    # ── level ────────────────────────────────────────────────────────────────

    def _level(self, ctx, s, j, add):
        lc = s.level_context or {}
        sup, res = lc.get('support'), lc.get('resistance')
        if sup:
            flip = ' (a level it broke and is now standing on)' if sup['flipped'] else ''
            flip_he = ' (רמה שפרצה ועכשיו עומדת עליה)' if sup['flipped'] else ''
            # support you would have to fall 40% to reach is not support you can trade
            # against — it is just the next thing on the chart
            far = (sup.get('dist_atr') or 0) > 4
            tail = ' — far enough below to be no help to a stop' if far else ''
            tail_he = ' — רחוקה מדי מלשמש סטופ' if far else ''
            add('level', 'note' if far else 'for',
                f'Support {sup["price"]:.2f}, {abs(sup["dist_pct"]):.1f}% below, tested {sup["touches"]}×{flip}{tail}',
                f'תמיכה ב-{sup["price"]:.2f}, {abs(sup["dist_pct"]):.1f}% מתחת, נבדקה {sup["touches"]} פעמים{flip_he}{tail_he}')
        else:
            add('level', 'against', 'No tested support underneath — nothing to lean the stop on',
                'אין תמיכה בדוקה מתחת — אין על מה להשעין סטופ')
        if res:
            flip = ' (former support — the scene of the crime)' if res['flipped'] else ''
            flip_he = ' (תמיכה לשעבר — זירת הפשע)' if res['flipped'] else ''
            add('level', 'against',
                f'Resistance {res["price"]:.2f}, {abs(res["dist_pct"]):.1f}% above, tested {res["touches"]}×{flip}',
                f'התנגדות ב-{res["price"]:.2f}, {abs(res["dist_pct"]):.1f}% מעל, נבדקה {res["touches"]} פעמים{flip_he}')
        else:
            add('level', 'for', 'Nothing tested overhead — open road',
                'אין התנגדות בדוקה מעל — דרך פתוחה')

        pos = lc.get('position_pct')
        if pos is not None:
            if pos <= 30:
                add('level', 'for',
                    f'Sitting {pos:.0f}% up its range — near the floor, where the risk is small',
                    f'נמצאת ב-{pos:.0f}% מהטווח — קרוב לרצפה, ששם הסיכון קטן')
            elif pos >= 70:
                add('level', 'against',
                    f'Sitting {pos:.0f}% up its range — near the ceiling, a poor place to start',
                    f'נמצאת ב-{pos:.0f}% מהטווח — קרוב לתקרה, מקום גרוע להתחיל בו')
            else:
                add('level', 'note', f'Mid-range ({pos:.0f}%) — no edge either way',
                    f'באמצע הטווח ({pos:.0f}%) — אין יתרון לאף כיוון')

        if s.off_high:
            add('level', 'note', f'{s.off_high:.0f}% below its high',
                f'{s.off_high:.0f}% מתחת לשיא')
        if s.fib_r:
            gp = ' — the golden pocket he buys' if s.golden else ''
            gp_he = ' — הגולדן פוקט שהוא קונה' if s.golden else ''
            add('level', 'for' if s.fib_r >= 0.4 else 'note',
                f'Retraced {s.fib_r*100:.0f}% of the whole move{gp}',
                f'תיקנה {s.fib_r*100:.0f}% מכל המהלך{gp_he}')

    # ── volume ───────────────────────────────────────────────────────────────

    def _volume(self, ctx, s, j, add):
        v = s.vol_detail
        if not v:
            return
        if v.get('break_vol_x') is not None:
            x = v['break_vol_x']
            ok = x >= VOL_SPIKE_FACTOR
            add('volume', 'for' if ok else 'against',
                f'The break came on {x:.1f}× average volume'
                + ('' if ok else ' — thin for a breakout; that is the one thing missing'),
                f'הפריצה הגיעה עם ווליום פי {x:.1f} מהממוצע'
                + ('' if ok else ' — דליל לפריצה; זה הדבר היחיד שחסר'))
        if v.get('spike_x', 0) and v['spike_x'] >= 1.8:
            ago = v['spike_bars_ago']
            up = v['spike_up']
            add('volume', 'for' if up else 'note',
                f'A {v["spike_x"]:.1f}× volume spike {ago} bars ago, on {"an up" if up else "a down"} bar'
                + ('' if up else ' — sellers showed up there'),
                f'ספייק ווליום פי {v["spike_x"]:.1f} לפני {ago} נרות, בנר {"עולה" if up else "יורד"}'
                + ('' if up else ' — שם נכנסו מוכרים'))
        if v.get('quiet_pullback'):
            add('volume', 'for',
                'Pulling back on drying-up volume — sellers are thinning out, which is the healthy kind',
                'מתקנת בווליום מתייבש — המוכרים מתמעטים, וזה התיקון הבריא')
        elif v.get('dry_up'):
            add('volume', 'against',
                'Volume drying up into the rise — nobody is chasing it',
                'הווליום מתייבש לתוך העלייה — אף אחד לא רודף אחריה')
        # "the latest bar", not "today": if the session is still open the provider
        # returns a partial bar, and calling a half-day's volume "today's" invites a
        # conclusion the data does not support.
        tx = v.get('today_x')
        if tx and tx >= 0.4:
            add('volume', 'note', f'Latest bar {tx:.1f}× the 20-day average volume',
                f'הנר האחרון פי {tx:.1f} מממוצע הווליום ל-20 יום')

    # ── pattern ──────────────────────────────────────────────────────────────

    def _pattern(self, ctx, s, add):
        p = s.pattern_detail or {}
        if s.pattern:
            add('pattern', 'for', f'{s.pattern[0]} on the chart', f'{s.pattern[1]} על הגרף')
        b = p.get('base')
        if b:
            add('pattern', 'for',
                f'{b["bars"]}-bar base between {b["bottom"]:.2f} and {b["top"]:.2f} '
                f'({b["depth_pct"]:.0f}% deep) — pressure building',
                f'בסיס של {b["bars"]} נרות בין {b["bottom"]:.2f} ל-{b["top"]:.2f} '
                f'(עומק {b["depth_pct"]:.0f}%) — לחץ שנצבר')
        f = p.get('flag')
        if f:
            add('pattern', 'for' if f['breaking'] else 'against',
                f'Flag top at {f["top"]:.2f} — ' +
                ('closed above it' if f['breaking'] else f'still under it ({f["dist_pct"]:+.1f}%), wait for the close'),
                f'ראש הדגל ב-{f["top"]:.2f} — ' +
                ('נסגר מעליו' if f['breaking'] else f'עדיין מתחתיו ({f["dist_pct"]:+.1f}%), להמתין לסגירה'))
        for ln in p.get('lines') or []:
            if not ln.get('price'):
                continue
            kind_en = 'descending-highs' if ln['kind'] == 'falling_highs' else 'rising-lows'
            kind_he = 'שיאים יורדים' if ln['kind'] == 'falling_highs' else 'שפלים עולים'
            if ln['broke']:
                add('pattern', 'for' if ln['kind'] == 'falling_highs' else 'against',
                    f'The {kind_en} line ({ln["touches"]} touches) has just been broken',
                    f'קו ה{kind_he} ({ln["touches"]} נגיעות) בדיוק נפרץ')
            else:
                add('pattern', 'note',
                    f'A {kind_en} line with {ln["touches"]} touches at {ln["price"]:.2f}',
                    f'קו {kind_he} עם {ln["touches"]} נגיעות ב-{ln["price"]:.2f}')
        ch = p.get('channel')
        if ch and ch.get('pos_pct') is not None:
            z = ch['zone']
            if z == 'bottom':
                add('pattern', 'for', 'At the bottom of a rising channel — the pullback he waits for',
                    'בתחתית תעלה עולה — התיקון שמחכים לו')
            elif z == 'top':
                add('pattern', 'against', 'At the top of the channel — not where a position starts',
                    'בחלק העליון של התעלה — לא המקום לפתוח פוזיציה')
            elif z == 'middle':
                add('pattern', 'note', 'Mid-channel — just movement inside the channel',
                    'באמצע התעלה — רק תנועה בתוך התעלה')

    # ── strength ─────────────────────────────────────────────────────────────

    def _strength(self, ctx, s, add):
        rs = s.rel_strength
        if not rs:
            return
        legs = rs['legs']
        for key, label_en, label_he in (('m1', 'over 1 month', 'בחודש'),
                                        ('m3', 'over 3 months', 'ב-3 חודשים'),
                                        ('m6', 'over 6 months', 'בחצי שנה')):
            leg = legs.get(key)
            if not leg:
                continue
            stance = 'for' if leg['excess'] >= 5 else 'against' if leg['excess'] <= -5 else 'note'
            add('strength', stance,
                f'{label_en.capitalize()}: {leg["stock"]:+.1f}% vs the market {leg["market"]:+.1f}% '
                f'({leg["excess"]:+.1f}% relative)',
                f'{label_he}: {leg["stock"]:+.1f}% מול השוק {leg["market"]:+.1f}% '
                f'({leg["excess"]:+.1f}% יחסית)')
        if rs['lead'] == 'leading':
            add('strength', 'for', 'Leading the market, not just riding it',
                'מובילה את השוק, לא רק נגררת אחריו')
        elif rs['lead'] == 'lagging':
            add('strength', 'against', 'Lagging the market — the tide is doing the work elsewhere',
                'מפגרת אחרי השוק — הכסף עובד במקום אחר')

    # ── risk ─────────────────────────────────────────────────────────────────

    def _risk(self, ctx, s, j, add):
        opts = j.get('options') or []
        best = opts[0] if opts else None
        if best and best.get('stop') is not None:
            anchored = best.get('stop_anchored')
            add('risk', 'for' if anchored else 'against',
                f'Stop {best["stop"]:.2f} — {best["stop_what"]}, '
                f'{best["risk_pct"]:.1f}% / {best["stop_atr"]:.1f} ATR away'
                + ('' if anchored else ' (no structure below — an ATR guess)'),
                f'סטופ {best["stop"]:.2f} — {best["stop_what_he"]}, '
                f'{best["risk_pct"]:.1f}% / {best["stop_atr"]:.1f} ATR'
                + ('' if anchored else ' (אין מבנה מתחת — הערכת ATR)'))
            if best.get('stop_position'):
                add('risk', 'note',
                    f'For a longer hold rather than a trade, the stop widens to {best["stop_position"]:.2f}',
                    f'למי שמחזיק לטווח ארוך ולא לטרייד — הסטופ מתרחב ל-{best["stop_position"]:.2f}')
            rr = best.get('risk_reward')
            if rr is not None:
                stance = 'for' if rr >= 2 else 'against' if rr < 1 else 'note'
                add('risk', stance,
                    f'Reward-to-risk {rr:.1f} to the top of the ladder'
                    + (' — risking more than the whole thesis is worth' if rr < 1 else ''),
                    f'יחס סיכוי/סיכון {rr:.1f} עד קצה סולם היעדים'
                    + (' — מסכנים יותר ממה ששווה כל התזה' if rr < 1 else ''))
        else:
            add('risk', 'against', 'No stop can be defined yet — so there is no position to size',
                'אי אפשר להגדיר סטופ עדיין — ולכן אין פוזיציה לתמחר')

        if ctx.atr_pct:
            tier = {'low': ('a calm', 'רגועה'), 'medium': ('an average', 'ממוצעת'),
                    'high': ('a volatile', 'תנודתית')}[ctx.vol_tier]
            add('risk', 'note',
                f'ATR {ctx.atr_pct:.1f}% a day — {tier[0]} name; size accordingly',
                f'ATR {ctx.atr_pct:.1f}% ליום — מניה {tier[1]}; לגודל הפוזיציה בהתאם')
        # His three bands, each with the consequence he actually attaches to it —
        # see micha._ext20 for the quotes the thresholds come from.
        d150 = s.ext.get('d150_pct') or 0.0
        d200 = s.ext.get('d200_pct')
        if s.ext.get('severe'):
            add('risk', 'against',
                f'{d150:+.0f}% above the 150 and {d200:+.0f}% above the 200 — clear of both '
                f'averages; that is not an entry point, it is a stock to wait for',
                f'{d150:+.0f}% מעל ממוצע 150 וגם {d200:+.0f}% מעל ממוצע 200 — רחוקה '
                f'משני הממוצעים; זו לא נקודת כניסה, זו מניה שמחכים לה')
        elif s.ext.get('stretched'):
            add('risk', 'against',
                f'{d150:+.0f}% above the 150 — stretched; chasing here is what the method '
                f'forbids, and if you take it the stop is mandatory',
                f'{d150:+.0f}% מעל ממוצע 150 — מתוחה; לרדוף כאן זה בדיוק מה שהשיטה '
                f'אוסרת, ואם בכל זאת נכנסים — חייבים סטופ')
        elif s.ext.get('mild'):
            add('risk', 'note',
                f'{d150:+.0f}% above the 150 — a bit stretched; careful with the entry, '
                f'but not late',
                f'{d150:+.0f}% מעל ממוצע 150 — קצת מתוחה; זהירות עם הכניסה, '
                f'אבל לא מאחרים')
        # The short-term twin: he refuses a chase after a run even when the trigger
        # is valid — "6 ימים רצופים של עליות. זה מה שמטריד" (CRWD).
        if s.ext.get('ran_hot'):
            d, rp = s.ext.get('run_days') or 0, s.ext.get('run_pct') or 0.0
            add('risk', 'against',
                f'Ran {rp:+.0f}% in the last few days'
                + (f' ({d} green days in a row)' if d >= 3 else '')
                + ' — the run into the trigger was the move',
                f'רצה {rp:+.0f}% בימים האחרונים'
                + (f' ({d} ימים ירוקים ברצף)' if d >= 3 else '')
                + ' — הריצה אל הטריגר הייתה המהלך')
        if ctx.market_cap and ctx.market_cap < 1e9:
            add('risk', 'against', 'Under $1B — outside the 150 method, speculative',
                'מתחת ל-1 מיליארד — מחוץ לשיטת ה-150, ספקולטיבי')

    # ── timing ───────────────────────────────────────────────────────────────

    def _timing(self, ctx, s, j, add):
        trig, alert = j.get('trigger'), j.get('alert')
        if trig:
            add('timing', 'note',
                f'The trigger is {trig["price"]:.2f} ({trig["what"]}) — {trig["distance_pct"]:+.1f}% away',
                f'הטריגר הוא {trig["price"]:.2f} ({trig["what_he"]}) — {trig["distance_pct"]:+.1f}% מכאן')
        if alert:
            add('timing', 'for', alert['label'], alert['label_he'])
        hold = j.get('hold_level')
        if hold:
            add('timing', 'note',
                f'It has to hold above {hold["price"]:.2f} ({hold["what"]}) for any of this to stand',
                f'צריכה לשמור מעל {hold["price"]:.2f} ({hold["what_he"]}) כדי שכל זה יעמוד')
        if s.candle.get('found'):
            add('timing', 'for', f'{s.candle["label"]} — buyers have shown up',
                f'{s.candle["label_he"]} — הקונים הגיעו')
        elif s.candle.get('turn'):
            add('timing', 'against', 'A turn candle, but buyers have not confirmed it',
                'נר היפוך, אבל הקונים עוד לא אישרו')
        else:
            add('timing', 'against', 'No buyers candle at the level yet',
                'עדיין אין נר קונים על הרמה')
        ed = ctx.earnings_days
        if ed is not None and ed <= EARNINGS_SOON_DAYS:
            add('timing', 'against',
                f'Earnings in {ed} day{"s" if ed != 1 else ""} — he does not open into a report',
                f'דיווח תוצאות בעוד {ed} ימים — לא נכנסים לפני דיווח')
        if s.momentum >= 5:
            add('timing', 'against',
                f'{s.momentum} green days in a row — late to be starting',
                f'{s.momentum} ימים ירוקים ברצף — מאוחר להתחיל עכשיו')
