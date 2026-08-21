"""
lastcalls.py — score the engine against his MOST RECENT calls.

The ranking gate (tools/rank.py) asks whether the grade predicts what happened next
over a thousand historical posts. This asks a different and much more direct
question, the owner's: on the names he has just posted, does the engine say the same
thing he does?

The filter is what makes it a fair test. A call he made two weeks ago is only still
his call if the chart is still roughly the chart he was looking at — if the stock has
since run 20% or broken down, our disagreement with his post is not an error, it is
the two of us describing different charts. So every candidate is checked against the
price on the day he posted and dropped when it has moved more than `--drift` percent
(and, in ATR terms, more than a couple of average days). What survives is the set
where "he said X, we say Y" is a real comparison.

    python tools/lastcalls.py --days 14
    python tools/lastcalls.py --days 30 --drift 6
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
sys.path.insert(0, os.path.join(ROOT, 'backend'))
sys.path.insert(0, ROOT)

import corpus                                    # noqa: E402
from analyzer import StockAnalyzer               # noqa: E402
from asof import HistoryCache                    # noqa: E402

# What HIS post is telling the reader to do. Deliberately crude and keyword-based:
# the point is to bucket his sentence into the same vocabulary the engine emits, not
# to parse Hebrew properly. Anything that matches nothing stays 'unclear' and is
# reported as such rather than being forced into a bucket.
HIS = [
    ('out',     ['אין סט אפ', 'הסטופ קפץ', 'לצאת', 'נשבר', 'איבדה']),
    ('wait',    ['פריצה מעל', 'מעל ', 'לחכות', 'חכו', 'להמתין', 'התראה', 'ברגע ש',
                 'אם תעבור', 'אם יעבור', 'מחכים']),
    ('enter',   ['כניסה', 'נכנסים', 'קניתי', 'נכנסתי', 'אחלה נקודה', 'נקודת כניסה']),
    ('hold',    ['מחזיק', 'להחזיק', 'בתוך המהלך', 'ממשיכה']),
    ('avoid',   ['לא הייתי', 'לא מעניין', 'אין פה', 'מתלבט', 'לא בטוח', 'להתרחק']),
]

# Which engine actions count as agreeing with which of his buckets. `wait_event` and
# `wait_pullback` are agreements with "wait": they name a different thing to wait for
# but they are not telling the reader to buy now.
AGREE = {
    'enter': {'enter'},
    'wait':  {'wait_trigger', 'wait_buyers', 'wait_pullback', 'wait_event', 'watch'},
    'hold':  {'hold', 'enter'},
    'out':   {'out', 'avoid'},
    'avoid': {'avoid', 'out', 'watch'},
}


def his_call(text: str) -> str:
    t = text or ''
    for key, words in HIS:
        if any(w in t for w in words):
            return key
    return 'unclear'


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--days', type=int, default=14, help='how far back to take calls')
    ap.add_argument('--drift', type=float, default=8.0,
                    help='max %% the price may have moved since the post')
    ap.add_argument('--drift-atr', type=float, default=2.5,
                    help='...and max ATRs, so a volatile name is not dropped unfairly')
    ap.add_argument('--workers', type=int, default=8)
    a = ap.parse_args()

    corpus_dir = os.environ.get('MICHA_CORPUS') or os.path.join(ROOT, 'corpus')
    calls = corpus.load(corpus_dir)
    since = (dt.date.today() - dt.timedelta(days=a.days)).isoformat()
    calls = [c for c in calls if c['date'] >= since]
    # newest call per ticker — his latest word on a name is the one to test
    seen, uniq = set(), []
    for c in calls:
        if c['ticker'] in seen:
            continue
        seen.add(c['ticker'])
        uniq.append(c)
    print('his last %d days: %d calls, %d tickers' % (a.days, len(calls), len(uniq)))

    # ── Scored by PRODUCTION, not by the as-of runner ─────────────────────────
    # `AsOfRunner` exists to truncate history to a past date; today needs no
    # truncation, and using it anyway introduced a discrepancy that had nothing to
    # do with the engine: its cache fetches a 10-year window and production fetches
    # three, and the two disagree on the value of the CURRENT, unsettled bar
    # (NFLX 79.87 vs 80.26 on the same date). One bar was enough to flip the
    # buyers'-candle test and with it the whole call, `avoid` against `at_trigger`.
    # Settled history agrees; only today's bar does not. So today is scored by the
    # thing that actually ships, and the cache is kept only for the drift filter,
    # which reads closed bars.
    cache = HistoryCache()
    cache.warm([c['ticker'] for c in uniq] + ['SPY'], workers=a.workers,
               verbose=False, fresh=True)
    analyzer = StockAnalyzer()

    rows = []

    def work(c):
        try:
            hist = cache.get(c['ticker'])
            if hist is None or hist.empty:
                return ('nodata', c, None)
            import pandas as pd
            then = hist[hist.index <= pd.Timestamp(c['date'])]
            if len(then) < 2:
                return ('nodata', c, None)
            p_then = float(then['close'].iloc[-1])
            p_now = float(hist['close'].iloc[-1])
            atr_then = float(then['high'].iloc[-14:].max() - then['low'].iloc[-14:].min()) / 14
            drift_pct = (p_now / p_then - 1) * 100
            drift_atr = abs(p_now - p_then) / atr_then if atr_then else 99
            if abs(drift_pct) > a.drift and drift_atr > a.drift_atr:
                return ('moved', c, {'drift': drift_pct})
            r = analyzer.analyze(c['ticker'])
            if not r:
                return ('nodata', c, None)
            m = r['micha']
            return ('ok', c, {
                'drift': drift_pct, 'rating': m['rating'], 'grade': m['grade'],
                'score': m['grade_score'], 'state': m['state'], 'action': m['action'],
                'why': m['grade_why'],
                'trigger': (m.get('trigger') or {}).get('price'),
            })
        except Exception as e:
            return ('err', c, {'e': repr(e)[:80]})

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        for f in as_completed([ex.submit(work, c) for c in uniq]):
            rows.append(f.result())

    ok = [r for r in rows if r[0] == 'ok']
    moved = [r for r in rows if r[0] == 'moved']
    print('comparable: %d   dropped (price moved): %d   no data: %d\n'
          % (len(ok), len(moved), len(rows) - len(ok) - len(moved)))

    agree = disagree = unclear = 0
    print('%-7s %-6s %-8s %-16s %-14s %s' %
          ('ticker', 'drift', 'his', 'ours', 'rating', 'verdict'))
    print('-' * 78)
    for _, c, d in sorted(ok, key=lambda r: -abs(r[2]['drift'])):
        h = his_call(c['text'])
        if h == 'unclear':
            unclear += 1
            mark = '?'
        elif d['action'] in AGREE.get(h, set()):
            agree += 1
            mark = 'AGREE'
        else:
            disagree += 1
            mark = 'DIFFER'
        print('%-7s %+5.1f%% %-8s %-16s %2d/10 %-7s %s'
              % (c['ticker'], d['drift'], h, d['action'], d['rating'], d['grade'], mark))
    tot = agree + disagree
    print('\nagree %d / %d (%.0f%%)   unclear-in-his-text %d'
          % (agree, tot, 100 * agree / tot if tot else 0, unclear))
    print('\nDISAGREEMENTS in full:')
    for _, c, d in ok:
        h = his_call(c['text'])
        if h != 'unclear' and d['action'] not in AGREE.get(h, set()):
            print('\n  %s (%s, drift %+.1f%%)' % (c['ticker'], c['date'], d['drift']))
            print('    his:  %s' % c['text'].replace('\n', ' ')[:150])
            print('    ours: %s / %s  %d/10 - %s'
                  % (d['state'], d['action'], d['rating'], (d['why'] or '')[:130]))


if __name__ == '__main__':
    main()
