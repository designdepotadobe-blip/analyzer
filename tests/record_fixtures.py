"""
Record the frozen fixtures the test suite runs against.

Run this ONCE (and again only when the sample deliberately changes):

    ./venv/Scripts/python.exe tests/record_fixtures.py

It hits Yahoo, pickles the raw OHLCV + fundamentals for a fixed ticker sample,
and writes tests/fixtures/frozen.pkl. After that the suite is offline and
deterministic — see tests/conftest.py for why that matters.

The sample is chosen to span the states the verdict engine can produce rather
than to be large: an entering breakout, a coiled at_trigger, a buyers-at-level,
a stretched name, a broken/avoid name, and a VCP. A sample that only contains
healthy charts cannot catch a regression in the paths that reject a chart.
"""

from __future__ import annotations

import os
import pickle
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(ROOT, 'backend'), ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from market_data import MarketData  # noqa: E402

# Spread across verdict states, not chosen for being good charts. ADBE is here
# specifically because it is the one name in the sample carrying a detected VCP,
# so the VCP path has a regression anchor at all.
SAMPLE = ['ARM', 'ADBE', 'NVDA', 'LRCX', 'GOOGL', 'PM', 'OPEN', 'MRNA', 'ROP']

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures')


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    md = MarketData()
    payloads: dict = {}

    # SPY first: it is the relative-strength benchmark every other ticker reads,
    # and freezing it is what keeps `rel_strength` stable across runs.
    spy = md.fetch('SPY')
    if spy is None or spy.empty:
        print('FAILED: could not fetch SPY (the benchmark) — aborting')
        return 1
    payloads['SPY'] = {'raw': spy, 'bench': spy['close'],
                       'market_cap': None, 'earnings_days': None, 'profile': {}}

    for tk in SAMPLE:
        md.prime(tk)
        raw = md.fetch(tk)
        if raw is None or raw.empty:
            print(f'  {tk:6} SKIPPED — no usable data')
            continue
        payloads[tk] = {
            'raw': raw,
            'bench': None,
            'market_cap': md.market_cap(tk),
            # Frozen as recorded. This is a COUNTDOWN, so it is the one field
            # that silently means something different on a later day — a fixture
            # recorded with earnings 1 day out keeps testing the earnings guard
            # forever, which is what we want from a regression anchor but is not
            # a live reading. Never interpret it as today's calendar.
            'earnings_days': md.earnings_days(tk),
            'profile': md.profile(tk),
        }
        print(f'  {tk:6} {len(raw)} bars, cap={payloads[tk]["market_cap"]}, '
              f'earnings_days={payloads[tk]["earnings_days"]}')

    path = os.path.join(OUT, 'frozen.pkl')
    with open(path, 'wb') as fh:
        pickle.dump(payloads, fh)
    print(f'\nwrote {path} — {len(payloads)} symbols')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
