"""
rank.py — the validation gate. Does the grade RANK, and does the ranking survive
two independent controls?

Why ranking and not a win rate: [[micha-grade-outcome-test]] records a stop retune
driven by a +2R win rate that was an artifact. At a fixed R multiple the target IS a
multiple of the stop, so a tighter stop puts the target nearer and wins by
construction; re-scored against a fixed ATR target the ordering fully reversed and
the change had to be reverted. Any metric whose definition contains a number the
grade itself chose can do this. So nothing here reads the engine's stop or target.

Two controls, and a change has to survive BOTH:

  A. FORWARD RETURN — plain close-to-close over N bars from the post date. Knows
     nothing about stops, targets or R. The primary metric.
  B. ATR BARRIER — first touch of entry +TARGET_ATR vs entry -STOP_ATR within N
     bars, both scaled by the stock's OWN ATR, neither taken from the engine.
     A shape check on A: it answers "did it get there before it broke", which is
     what a swing trader actually collects, while A answers "where did it end up".

Reported as decile/bucket lift rather than a single correlation, because the
question is not "is the score related to the outcome" but "if I trade the top of
this list instead of the middle, am I better off" — which is what the letter is
for.

    python tools/rank.py --sample 900 --bars 60
    python tools/rank.py --label after-rework          # tag a run for comparison
    python tools/rank.py --compare before.json after.json
"""

from __future__ import annotations

import argparse
import json
import os
import collections
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))

import corpus                                    # noqa: E402
from asof import CACHE_DIR, AsOfRunner, HistoryCache  # noqa: E402

# The barrier control. Deliberately NOT derived from anything the engine computes:
# a fixed multiple of the stock's own average daily range, so a grade that prefers
# tight stops cannot move the target it is scored against.
TARGET_ATR = 1.5
STOP_ATR = 1.0

GRADES = ['A', 'B', 'C', 'D', 'F']


def spearman(xs, ys) -> float:
    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2.0
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r
    a, b = rank(xs), rank(ys)
    ma, mb = statistics.mean(a), statistics.mean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    den = (sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b)) ** 0.5
    return num / den if den else 0.0


def barrier(cache, ticker, asof, atr, bars):
    """+TARGET_ATR before -STOP_ATR? 1 win / 0 loss / None undecided in `bars`."""
    import pandas as pd
    raw = cache.get(ticker)
    if raw is None or not atr:
        return None
    past = raw[raw.index <= pd.Timestamp(asof)]
    fut = raw[raw.index > pd.Timestamp(asof)].head(bars)
    if len(past) < 2 or len(fut) < 5:
        return None
    entry = float(past['close'].iloc[-1])
    up, dn = entry + TARGET_ATR * atr, entry - STOP_ATR * atr
    for _, row in fut.iterrows():
        hit_dn = float(row['low']) <= dn
        hit_up = float(row['high']) >= up
        if hit_dn and hit_up:
            return 0          # both in one bar: assume the stop, the honest way round
        if hit_dn:
            return 0
        if hit_up:
            return 1
    return None


def build(sample, bars, since, workers, out_path):
    corpus_dir = os.environ.get('MICHA_CORPUS') or os.path.join(ROOT, 'corpus')
    if not os.path.exists(os.path.join(corpus_dir, 'messages.jsonl')):
        sys.exit('no corpus at %s - run discord_harvest.py first, or set '
                 'MICHA_CORPUS to where it lives' % corpus_dir)
    calls = corpus.load(corpus_dir)
    if since:
        calls = [c for c in calls if c['date'] >= since]
    # One call per (ticker, date): he often posts a chart and a follow-up line.
    seen, uniq = set(), []
    for c in calls:
        k = (c['ticker'], c['date'])
        if k not in seen:
            seen.add(k)
            uniq.append(c)
    # Newest first, but leave room for the forward window to have happened.
    import datetime as dt
    cutoff = (dt.date.today() - dt.timedelta(days=int(bars * 1.6))).isoformat()
    uniq = [c for c in uniq if c['date'] <= cutoff]
    if sample:
        # even coverage across the history rather than the newest N
        step = max(1, len(uniq) // sample)
        uniq = uniq[::step][:sample]
    print('scoring %d calls (<= %s), %d tickers'
          % (len(uniq), cutoff, len(corpus.tickers(uniq))), flush=True)

    cache = HistoryCache()
    cache.get('SPY')
    cache.warm(corpus.tickers(uniq) + ['SPY'], workers=workers)
    runner = AsOfRunner(cache)

    from asof import forward
    rows, done = [], 0

    def work(c):
        try:
            r = runner.run(c['ticker'], c['date'])
            if not r:
                return None
            fw = forward(cache, c['ticker'], c['date'], bars)
            if not fw:
                return None
            m = r['micha']
            bd = m['grade_breakdown']
            comp = {x['key']: x['got'] for x in bd['components']}
            best = (m.get('options') or [None])[0]
            return {
                'ticker': c['ticker'], 'date': c['date'],
                'grade': m['grade'], 'score': m['grade_score'],
                'state': m['state'], 'action': m['action'],
                'setup': comp.get('setup'), 'trigger': comp.get('trigger'),
                'risk': comp.get('risk'), 'event': comp.get('event'),
                'reward': comp.get('reward'), 'structure': comp.get('structure'),
                'potential': comp.get('potential'),
                'rr': (best or {}).get('risk_reward'),
                'expectancy_r': (best or {}).get('expectancy_r'),
                'ret': fw['ret_pct'], 'mfe': fw['mfe_pct'], 'mae': fw['mae_pct'],
                'exc': fw['exc_pct'],
                'rating': m.get('rating'),
                'barrier': barrier(cache, c['ticker'], c['date'], r['atr'], bars),
            }
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for f in as_completed([ex.submit(work, c) for c in uniq]):
            r = f.result()
            done += 1
            if r:
                rows.append(r)
            if done % 100 == 0:
                print('    scored %d/%d' % (done, len(uniq)), flush=True)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    json.dump({'bars': bars, 'rows': rows}, open(out_path, 'w'))
    print('wrote %s (%d scored)' % (out_path, len(rows)))
    return rows


def report(rows, bars, title=''):
    """The gate itself. Printed the same way every run so two runs can be diffed."""
    live = [r for r in rows if r['state'] not in ('broken', 'avoid')]
    print()
    print('=' * 72)
    print('RANKING GATE %s   n=%d  (live=%d)  forward %d bars'
          % (title, len(rows), len(live), bars))
    print('=' * 72)

    for name, sub in (('ALL CALLS', rows), ('LIVE ONLY (excl broken/avoid)', live)):
        if len(sub) < 30:
            continue
        print('\n--- %s ---' % name)
        base = statistics.mean([r['ret'] for r in sub])
        print('  base forward return %+.2f%%   n=%d' % (base, len(sub)))
        exc_all = [r['exc'] for r in sub if r.get('exc') is not None]
        ebase = statistics.mean(exc_all) if exc_all else 0.0
        print('  base excess vs SPY  %+.2f%%' % ebase)
        print('  %-6s %5s %9s %9s %9s %9s %8s' %
              ('grade', 'n', 'ret%', 'exc%', 'exc lift', 'mfe%', 'barrier'))
        for g in GRADES:
            b = [r for r in sub if r['grade'] == g]
            if not b:
                continue
            dec = [r['barrier'] for r in b if r['barrier'] is not None]
            ex = [r['exc'] for r in b if r.get('exc') is not None]
            em = statistics.mean(ex) if ex else 0.0
            print('  %-6s %5d %+9.2f %+9.2f %+9.2f %+9.2f %8s'
                  % (g, len(b), statistics.mean([r['ret'] for r in b]),
                     em, em - ebase,
                     statistics.mean([r['mfe'] for r in b]),
                     ('%.0f%%' % (100 * sum(dec) / len(dec))) if dec else '-'))
        # rating deciles - the headline number's own ranking power
        rt = collections.defaultdict(list)
        for r in sub:
            if r.get('rating') is not None and r.get('exc') is not None:
                rt[r['rating']].append(r['exc'])
        if rt:
            print('  rating:  ' + '  '.join(
                '%d/10 n=%d %+.1f' % (k, len(v), statistics.mean(v))
                for k, v in sorted(rt.items())))
        # A-vs-D/F spread is the number that says whether the LETTER is worth reading
        top = [r['ret'] for r in sub if r['grade'] in ('A', 'B')]
        bot = [r['ret'] for r in sub if r['grade'] in ('D', 'F')]
        if top and bot:
            print('  AB-vs-DF spread  %+.2f pp' %
                  (statistics.mean(top) - statistics.mean(bot)))
        # score quintiles: finer than the letter, and immune to band boundaries
        s = sorted(sub, key=lambda r: r['score'])
        q = max(1, len(s) // 5)
        print('  score quintiles (low->high): ' + '  '.join(
            '%+.2f' % statistics.mean([r['ret'] for r in s[i * q:(i + 1) * q]])
            for i in range(5)))
        for key in ('score', 'expectancy_r', 'rr', 'reward', 'event', 'potential'):
            for tgt in ('ret', 'exc'):
                vals = [(r[key], r[tgt]) for r in sub
                        if r.get(key) is not None and r.get(tgt) is not None]
                if len(vals) > 40:
                    print('  spearman(%-12s, %s) = %+.3f   n=%d'
                          % (key, tgt, spearman([v[0] for v in vals],
                                                [v[1] for v in vals]), len(vals)))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--sample', type=int, default=900)
    ap.add_argument('--bars', type=int, default=60)
    ap.add_argument('--since', default='2023-01-01')
    ap.add_argument('--workers', type=int, default=8)
    ap.add_argument('--label', default='current')
    ap.add_argument('--reuse', action='store_true',
                    help='report on an existing run instead of re-scoring')
    ap.add_argument('--compare', nargs=2, metavar=('BEFORE', 'AFTER'))
    a = ap.parse_args()

    if a.compare:
        for p in a.compare:
            d = json.load(open(p))
            report(d['rows'], d['bars'], title=os.path.basename(p))
        return

    out = os.path.join(CACHE_DIR, 'rank_%s_%db.json' % (a.label, a.bars))
    if a.reuse and os.path.exists(out):
        d = json.load(open(out))
        rows, bars = d['rows'], d['bars']
    else:
        rows = build(a.sample, a.bars, a.since, a.workers, out)
        bars = a.bars
    report(rows, bars, title=a.label)


if __name__ == '__main__':
    main()
