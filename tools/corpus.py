"""
corpus.py — turn the harvested Discord archive into a list of dated CALLS.

`discord_harvest.py` writes raw message dicts; this reads them back and answers the
only question the validation harness asks of them: *on this date, he posted about
this ticker*. That pair (ticker, date) is the sample the grade is scored against —
his own selections, which is a far better test set than a random universe slice
because every one of them is a chart he thought was worth posting.

The ticker lives in the mention line he ends every post with ("@everyone NVDA"),
which is why this does not need to guess at symbols inside the Hebrew body.
Non-equities he also posts (BTCUSD, KOSPI, SOXX-style indices) are kept here and
filtered later by whoever cannot price them — this module reports, it does not judge.
"""

from __future__ import annotations

import json
import os
import re
from typing import Iterator, Optional

# "@everyone NVDA" / "@here TSLA" / a bare trailing "NVDA" on its own line.
_MENTION = re.compile(r'@(?:everyone|here)\s+([A-Z][A-Z0-9.\-]{0,6})\b')
_TRAILING = re.compile(r'(?:^|\n)\s*([A-Z][A-Z0-9.\-]{0,6})\s*$')

# Prices he states in the text. Used to compare our numbers against his, not to
# drive the ranking metric — see tools/rank.py for why the ranking is scored on
# forward price action instead.
_PRICE = re.compile(r'(?<![\d.])(\d{1,5}(?:\.\d{1,2})?)(?![\d.])')

# Words that make a following number NOT a price — "ממוצע 150" is the 150-day
# average, not $150. This exact trap put a stop 93% above the entry on JPM the
# first time this corpus was parsed; see [[micha-numeric-validation]].
_NOT_A_PRICE = ('ממוצע', 'מדמה', 'סמא', 'sma', 'ma')


def ticker_of(text: str) -> Optional[str]:
    m = _MENTION.search(text or '')
    if m:
        return m.group(1)
    m = _TRAILING.search((text or '').strip())
    return m.group(1) if m else None


def prices_in(text: str) -> list[float]:
    """Every number in the text that plausibly denotes a price."""
    out = []
    for m in _PRICE.finditer(text or ''):
        before = (text[:m.start()] or '')[-14:].lower()
        if any(w in before for w in _NOT_A_PRICE):
            continue
        v = float(m.group(1))
        if 0.5 <= v <= 20000:
            out.append(v)
    return out


def load(corpus_dir: str, author: str = 'micha.stocks') -> list[dict]:
    """
    Every post by `author` that names a ticker, newest first.

    Returns dicts of {ticker, date, ts, text, prices, has_image}.
    """
    path = os.path.join(corpus_dir, 'messages.jsonl')
    out: list[dict] = []
    with open(path, encoding='utf-8') as fh:
        for line in fh:
            try:
                m = json.loads(line)
            except Exception:
                continue
            if author and (m.get('author') or {}).get('username') != author:
                continue
            text = (m.get('content') or '').strip()
            tk = ticker_of(text)
            if not tk:
                continue
            ts = (m.get('timestamp') or '')[:19]
            out.append({
                'ticker': tk,
                'date': ts[:10],
                'ts': ts,
                'text': text,
                'prices': prices_in(text),
                'has_image': bool(m.get('attachments') or m.get('embeds')),
            })
    out.sort(key=lambda r: r['ts'], reverse=True)
    return out


def tickers(calls: list[dict]) -> list[str]:
    seen, out = set(), []
    for c in calls:
        if c['ticker'] not in seen:
            seen.add(c['ticker'])
            out.append(c['ticker'])
    return out
