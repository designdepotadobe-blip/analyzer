"""
agree.py — does the engine say what HE said, on the day he said it?

`lastcalls.py` compares his recent posts with the engine TODAY, which only works for
names whose price has not moved since. This replays every clear call in a date range
through the production pipeline AS OF the evening he posted (`AsOfRunner`), so the
two readings describe the same chart, and reports agreement per call type.

His posts go out after the US close (~20:00 ET = ~00:00 UTC next day), so the as-of
bar is the last one CLOSED at posting time: the ET date when posted after 16:00 ET,
else the previous session.

    python tools/agree.py --since 2025-07-01 --until 2026-09-30
    python tools/agree.py --since 2026-01-01 --show enter      # list the misses

Earnings are unknown historically (None), so the earnings guard never fires here.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(ROOT, 'tools'), os.path.join(ROOT, 'backend'), ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import corpus                                   # noqa: E402
from asof import AsOfRunner, HistoryCache       # noqa: E402

# His sentence → one bucket. Order matters (first match wins) and the phrases are
# the ones he actually uses; "לצאת לדרך" (about to take off) is excluded from `out`.
HIS = [
    ('out',   ['אין סט אפ', 'הסטופ קפץ', 'הסט אפ נגמר', 'נשברה', 'איבדה את']),
    ('avoid', ['אין פה שום דבר', 'לא הייתי נכנס', 'לא מעניין', 'להתרחק', 'אין מה להתעסק']),
    ('enter', ['נקודת כניסה טובה', 'נקודת כניסה מצוינת', 'אחלה נקודת כניסה', 'נכנסים קונים',
               'כניסת קונים', 'נקודת כניסה מעולה', 'נכנסתי', 'קניתי']),
    ('wait',  ['פריצה מעל', 'חכו', 'לחכות', 'להמתין', 'מחכים', 'שימו התראה', 'ברגע שתעבור',
               'אם תעבור', 'צריכה לעבור', 'חייבת לעבור', 'צריך לשמור', 'חייבת לשמור']),
]

AGREE = {
    'both':  {'enter', 'wait_trigger', 'wait_buyers', 'wait_pullback', 'hold'},
    'enter': {'enter'},
    'wait':  {'wait_trigger', 'wait_buyers', 'wait_pullback', 'wait_event', 'watch', 'hold'},
    'out':   {'out', 'avoid'},
    'avoid': {'avoid', 'out', 'watch'},
}


# An entry he makes CONDITIONAL — "אם מחר נכנסים קונים - זה יופי של נקודת כניסה"
# (AVGO), "אם שומרת ... נקודת כניסה מצוינת" (AVGO, META), "תנאי על תנאי" (MSTR) — is
# him telling the reader to wait for that condition, not to buy tonight.
CONDITIONAL = ('אם מחר', 'אם נכנסים', 'אם שומרת', 'אם היא נשארת', 'אם יכנסו', 'בתנאי',
               'תנאי על תנאי', 'צריכה להיות מעל', 'אם המוכרים')


# A post that offers BOTH ways in — "אם שיטת 150 - נקודת כניסה. אם מחכים לפריצה 87.11"
# (NBIS), "סטופים מתחת לממוצע 150. או להמתין לפריצה" (HOOD), "לחכות לשני אלא אם ממש
# לחוצים" (OKLO) — is matched by an engine that says either; it prints both options too.
BOTH = ('או להמתין', 'או לחכות', 'אפשר לחכות', 'אם מחכים', 'אלא אם', 'אפשרות להיכנס',
        'אפשר להתחיל פה', 'למי שחייב להיכנס')


def his_call(text: str) -> str:
    # negations that contain an 'out'/'avoid' phrase: "לא נשברה" (has NOT broken),
    # "אין פה שום דבר חריג / מדאיג / בעייתי" (nothing UNUSUAL / worrying)
    t = (text or '').replace('לצאת לדרך', '').replace('לא נשברה', '')
    for q in ('חריג', 'מדאיג', 'בעייתי'):
        t = t.replace('אין פה שום דבר ' + q, '').replace('שום דבר ' + q, '')
    if any(b in t for b in BOTH):
        return 'both'
    for key, words in HIS:
        if any(w in t for w in words):
            if key == 'enter' and any(c in t for c in CONDITIONAL):
                return 'wait'
            return key
    return 'unclear'


def asof_date(ts: str) -> str:
    """UTC ISO timestamp → the last US session closed when he posted."""
    u = dt.datetime.fromisoformat(ts[:19])
    et = u - dt.timedelta(hours=4)
    # During the session he is describing TODAY's candle ("עלתה כבר 6% מהנמוך היומי",
    # VRT) — use that day's bar. Before the open, the last closed session.
    d = et.date() if (et.hour, et.minute) >= (9, 30) else et.date() - dt.timedelta(days=1)
    return d.isoformat()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--since', default='2025-07-01')
    ap.add_argument('--until', default='2099-01-01')
    ap.add_argument('--show', default='', help='print the misses of this call type')
    ap.add_argument('--ours', default='', help='...only where the engine said this action')
    ap.add_argument('--workers', type=int, default=8)
    ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args()

    corpus_dir = os.environ.get('MICHA_CORPUS') or os.path.join(ROOT, 'corpus')
    calls = [c for c in corpus.load(corpus_dir) if a.since <= c['date'] <= a.until]
    calls = [dict(c, his=his_call(c['text'])) for c in calls]
    calls = [c for c in calls if c['his'] != 'unclear']
    if a.limit:
        calls = calls[:a.limit]
    print('clear calls %s..%s: %d  %s' % (a.since, a.until, len(calls),
                                          dict(Counter(c['his'] for c in calls))))

    cache = HistoryCache()
    cache.warm(sorted({c['ticker'] for c in calls}) + ['SPY'], workers=a.workers,
               verbose=False)
    runner = AsOfRunner(cache)

    def work(c):
        try:
            r = runner.run(c['ticker'], asof_date(c['ts']))
            if not r:
                return c, None
            m = r['micha']
            return c, {'state': m['state'], 'action': m['action'], 'rating': m['rating'],
                       'grade': m['grade'], 'why': m.get('grade_why') or ''}
        except Exception as e:                       # a bad frame must not end the run
            return c, {'err': repr(e)[:100]}

    rows = []
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        for f in as_completed([ex.submit(work, c) for c in calls]):
            rows.append(f.result())

    ok = [(c, d) for c, d in rows if d and 'err' not in d]
    errs = [(c, d) for c, d in rows if d and 'err' in d]
    by = defaultdict(lambda: [0, 0])
    acts = defaultdict(Counter)
    ratings = defaultdict(list)
    for c, d in ok:
        hit = d['action'] in AGREE[c['his']]
        by[c['his']][0] += hit
        by[c['his']][1] += 1
        acts[c['his']][d['action']] += 1
        ratings[c['his']].append(d['rating'])
    tot_hit = sum(v[0] for v in by.values())
    tot = sum(v[1] for v in by.values())
    print('scored %d   no data %d   errors %d' % (len(ok), len(rows) - len(ok) - len(errs), len(errs)))
    for k in ('enter', 'wait', 'both', 'out', 'avoid'):
        if by[k][1]:
            rs = sorted(ratings[k])
            print('  %-6s agree %3d/%3d (%3.0f%%)   median rating %d   ours: %s'
                  % (k, by[k][0], by[k][1], 100 * by[k][0] / by[k][1], rs[len(rs) // 2],
                     dict(acts[k].most_common(5))))
    print('  TOTAL  agree %d/%d (%.0f%%)' % (tot_hit, tot, 100 * tot_hit / tot if tot else 0))
    if errs:
        print('  first error: %s %s' % (errs[0][0]['ticker'], errs[0][1]['err']))

    if a.show:
        print('\nMISSES for %r:' % a.show)
        for c, d in sorted(ok, key=lambda r: r[0]['ts'], reverse=True):
            if c['his'] == a.show and d['action'] not in AGREE[a.show] and (
                    not a.ours or d['action'] == a.ours):
                print('\n  %s %s  ours %s/%s %d/10' % (c['ticker'], asof_date(c['ts']),
                                                     d['state'], d['action'], d['rating']))
                print('    his: %s' % c['text'].replace('\n', ' ')[:170])
                print('    why: %s' % d['why'][:170])


if __name__ == '__main__':
    main()
