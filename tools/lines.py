"""
lines.py — does the engine draw HIS lines?

`agree.py` scores the decision (enter / wait / out). This scores what every decision
is built from: the line he names. Replayed as of the evening of each post
(`AsOfRunner`), it measures, over his setup-channel posts:

  trigger   — our trigger within TOL of the breakout price he names
              ("פריצה מעל X", "מחיר פריצה X", "פריצה קורית במחיר X")
  any level — some level in the engine's full map (drawn or not) at his price
  drawn     — a level we actually draw at his price
  nearer    — we quote a LOWER wall than his (we stopped at a minor edge)
  cup       — a cup detected on the posts where he names one ("קאפ")
  universe  — share of ALL cached names that read as a cup today: the
              false-positive side, so "find his cups" can't be won by calling
              everything a cup (owner: "not every graph has cup and handle")

    python tools/lines.py --since 2025-07-01
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(ROOT, 'tools'), os.path.join(ROOT, 'backend'), ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import agree                                    # noqa: E402
import corpus                                   # noqa: E402
from asof import AsOfRunner, HistoryCache       # noqa: E402
from levels import LevelEngine                  # noqa: E402

PRICE_RX = re.compile(
    r'(?:פריצה (?:מעל|ב|של|קורית מעל|קורית במחיר)|מחיר פריצה|לעבור (?:את )?(?:ה)?)'
    r'\s*\$?\s*(\d{1,5}(?:[.,]\d{1,2})?)')
TOL = 0.015


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--since', default='2025-07-01')
    ap.add_argument('--universe', type=int, default=250,
                    help='cached names to score for the cup false-positive rate (0 = skip)')
    ap.add_argument('--show', action='store_true', help='print every trigger miss')
    a = ap.parse_args()

    corpus_dir = os.environ.get('MICHA_CORPUS') or os.path.join(ROOT, 'corpus')
    calls = [c for c in corpus.load(corpus_dir) if c['date'] >= a.since]
    cache = HistoryCache()
    runner = AsOfRunner(cache)
    engine = LevelEngine()

    rows, cup = [], Counter()
    for c in calls:
        m = PRICE_RX.search(c['text'])
        is_cup = 'קאפ' in c['text']
        if (not m and not is_cup) or c['ticker'] not in cache:
            continue
        x = runner.run(c['ticker'], agree.asof_date(c['ts']))
        if not x:
            continue
        ctx, mi = x['ctx'], x['micha']
        if is_cup:
            cup['posts'] += 1
            cup['found'] += bool(x['overlays'].get('cup'))
        if not m:
            continue
        his = float(m.group(1).replace(',', ''))
        if not (0.5 * ctx.price < his < 1.6 * ctx.price):
            continue                      # a typo or a price from another chart
        trig = (mi['trigger'] or {}).get('price')
        # A price UNDER today's is the line that just broke — his "מחיר פריצה $1041,
        # תנו לה לנשום" (MU): the must-hold, which the engine reports as the hold /
        # break level, not as the next trigger overhead.
        if his < ctx.price:
            below = [p for p in ((mi.get('hold_level') or {}).get('price'),
                                 (x['micha'].get('trigger') or {}).get('floor')) if p]
            for lv in (engine.build(ctx)[1] or []):
                if (lv.get('freshness') == 'just_broken'):
                    below.append(lv.get('top') or lv['price'])
            trig = min(below, key=lambda p: abs(p - his)) if below else trig
        res, sup = engine.build(ctx)

        def dist(lv):
            pts = [lv['price'], lv.get('top') or lv['price'], lv.get('bottom') or lv['price']]
            return min(abs(p - his) for p in pts) / his

        rows.append({
            'tk': c['ticker'], 'date': c['date'], 'his': his, 'trig': trig,
            'trig_ok': bool(trig) and abs(trig - his) / his <= TOL,
            'any_ok': min((dist(l) for l in res + sup), default=9) <= TOL,
            'drawn_ok': min((dist(l) for l in x['overlays']['levels']), default=9) <= TOL,
            'nearer': bool(trig) and his > trig * (1 + TOL),
        })

    n = len(rows) or 1

    def share(key):
        k = sum(1 for r in rows if r[key])
        return '%d/%d (%.0f%%)' % (k, len(rows), 100 * k / n)

    print('breakout-price posts: %d' % len(rows))
    print('  trigger = his price    %s' % share('trig_ok'))
    print('  any level at his price %s' % share('any_ok'))
    print('  drawn level at price   %s' % share('drawn_ok'))
    print('  we quote a nearer wall %s' % share('nearer'))
    if cup['posts']:
        print('cup posts: found %d/%d (%.0f%%)' % (cup['found'], cup['posts'],
                                                   100 * cup['found'] / cup['posts']))

    if a.universe:
        names = [t for t in sorted(cache._data) if t != 'SPY'][:a.universe]
        hit = tot = 0
        for tk in names:
            h = cache.get(tk)
            if h is None or h.empty:
                continue
            x = runner.run(tk, str(h.index[-1].date()))
            if not x:
                continue
            tot += 1
            hit += bool(x['overlays'].get('cup'))
        if tot:
            print('universe cup rate: %d/%d (%.0f%%)' % (hit, tot, 100 * hit / tot))

    if a.show:
        print('\nTRIGGER MISSES:')
        for r in rows:
            if not r['trig_ok']:
                print('  %-6s %s his %.2f  ours %s%s' % (
                    r['tk'], r['date'], r['his'], r['trig'] and round(r['trig'], 2),
                    '  (nearer)' if r['nearer'] else ''))


if __name__ == '__main__':
    main()
