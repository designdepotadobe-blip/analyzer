"""
Golden-snapshot regression over the frozen sample.

This is the safety net every other change in the spec leans on: it pins the
CURRENT verdict for each fixture ticker so any later refactor that moves a
grade, a state, an action or a cap fails loudly and visibly instead of drifting
unnoticed. It deliberately asserts the decision surface (state / action /
headline / grade / rating / bound caps / axis budgets) rather than every float
in the payload — a snapshot that pins every number is a snapshot nobody can
ever legitimately update, so it stops being a signal and starts being noise.

Regenerating is deliberate and explicit:

    ./venv/Scripts/python.exe tests/test_baseline.py --update

Only do that when a behavior change is INTENDED, and say so in the commit.
"""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GOLDEN = os.path.join(HERE, 'fixtures', 'baseline.json')


def decision_surface(r: dict) -> dict:
    """The fields a regression actually cares about, in a stable shape."""
    m = r['micha']
    bd = m['grade_breakdown']
    return {
        'state': m['state'],
        'action': m['action'],
        'headline_action': m['headline_action'],
        'grade': m['grade'],
        'grade_score': round(float(m['grade_score']), 1),
        'rating': m['rating'],
        # Only BOUND caps: a cap that applied without moving the letter explains
        # nothing (see verdict._grade's own comment) and listing it would make
        # the snapshot churn on changes that did not alter a decision.
        'bound_caps': sorted(c['key'] for c in bd['caps'] if c['bound']),
        'axis_max': {c['key']: c['max'] for c in bd['components']
                     if not c.get('adjustment')},
        'setup_codes': sorted({s['code'] for s in r['setups']}),
    }


def build(analyses: dict) -> dict:
    return {tk: decision_surface(r) for tk, r in sorted(analyses.items())}


def test_baseline_unchanged(analyses):
    if not os.path.exists(GOLDEN):
        import pytest
        pytest.skip('no baseline recorded — run: python tests/test_baseline.py --update')
    with open(GOLDEN, encoding='utf-8') as fh:
        golden = json.load(fh)
    current = build(analyses)

    # Compare per-ticker so a failure names the symbol that moved rather than
    # dumping two whole documents at the reader.
    drifted = {tk: (golden.get(tk), current.get(tk))
               for tk in sorted(set(golden) | set(current))
               if golden.get(tk) != current.get(tk)}
    assert not drifted, (
        'verdict drift vs the recorded baseline:\n'
        + '\n'.join(f'  {tk}\n    was: {was}\n    now: {now}'
                    for tk, (was, now) in drifted.items())
        + '\n\nIf this change was INTENTIONAL, regenerate with:\n'
          '  ./venv/Scripts/python.exe tests/test_baseline.py --update')


def _update() -> int:
    """Record the current behavior as the new baseline."""
    import pickle
    sys.path.insert(0, HERE)
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'backend'))
    from conftest import FrozenMarketData
    from analyzer import StockAnalyzer

    with open(os.path.join(HERE, 'fixtures', 'frozen.pkl'), 'rb') as fh:
        payloads = pickle.load(fh)
    an = StockAnalyzer()
    an.data = FrozenMarketData(payloads)
    analyses = {}
    for tk in sorted(payloads):
        if tk == 'SPY':
            continue
        r = an.analyze(tk)
        if r is not None:
            analyses[tk] = r
    snap = build(analyses)
    with open(GOLDEN, 'w', encoding='utf-8') as fh:
        json.dump(snap, fh, indent=2, ensure_ascii=False, sort_keys=True)
    for tk, d in snap.items():
        print(f"  {tk:6} {d['state']:16} {d['action']:13} "
              f"{d['grade']}{d['grade_score']:.0f} caps={d['bound_caps']}")
    print(f'\nwrote {GOLDEN} — {len(snap)} symbols')
    return 0


if __name__ == '__main__':
    if '--update' in sys.argv:
        raise SystemExit(_update())
    print(__doc__)
