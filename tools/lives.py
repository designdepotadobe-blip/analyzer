"""
lives.py — pull the transcripts of his community livestreams.

The Discord channel 1496896146789105805 is 64 YouTube livestreams, "20 דק' 20
מניות" (twenty minutes, twenty stocks), Apr-Aug 2026. Unlike the old method video
in [[micha-judgement-layer]] — which has subtitles disabled and should not be
retried — these carry auto-generated Hebrew captions, so the reasoning he speaks
out loud over twenty charts a session is actually readable.

That is a different and much richer source than the Discord posts the engine was
derived from. A post is a median 70 characters and states the conclusion; a live
is him talking through HOW he got there, one stock at a time, including the parts
he never writes down.

    python tools/lives.py --pull          # fetch + cache every transcript
    python tools/lives.py --grep "יעד"    # concordance for a phrase

Auto-captions are imperfect: no punctuation, and Hebrew ASR mangles tickers
("אנבידיה" for NVDA, English names transliterated inconsistently). Treat the text
as evidence of REASONING, never as a source of prices — the numbers in it are the
least reliable part.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, '.harness', 'lives')


def video_ids(vids_dir: str) -> list[tuple[str, str]]:
    """(date, youtube id) for every video embed in the harvested channel."""
    out, seen = [], set()
    path = os.path.join(vids_dir, 'messages.jsonl')
    for line in open(path, encoding='utf-8'):
        try:
            m = json.loads(line)
        except Exception:
            continue
        for e in (m.get('embeds') or []):
            if e.get('type') != 'video':
                continue
            u = e.get('url') or ''
            hit = re.search(r'(?:live/|watch\?v=|youtu\.be/)([A-Za-z0-9_-]{11})', u)
            if hit and hit.group(1) not in seen:
                seen.add(hit.group(1))
                out.append((m['timestamp'][:10], hit.group(1)))
    out.sort()
    return out


def pull(vids_dir: str) -> None:
    from youtube_transcript_api import YouTubeTranscriptApi
    os.makedirs(CACHE, exist_ok=True)
    api = YouTubeTranscriptApi()
    vids = video_ids(vids_dir)
    print('%d videos' % len(vids))
    got = skipped = failed = 0
    for date, vid in vids:
        dest = os.path.join(CACHE, '%s_%s.json' % (date, vid))
        if os.path.exists(dest):
            skipped += 1
            continue
        try:
            tr = api.fetch(vid, languages=['iw', 'he'])
            snips = [{'t': round(s.start, 1), 'd': round(s.duration, 1), 'x': s.text}
                     for s in tr]
            json.dump({'id': vid, 'date': date, 'snippets': snips},
                      open(dest, 'w', encoding='utf-8'), ensure_ascii=False)
            got += 1
            print('  %s %s  %d lines' % (date, vid, len(snips)), flush=True)
        except Exception as e:
            failed += 1
            print('  %s %s  FAIL %s' % (date, vid, type(e).__name__), flush=True)
    print('pulled %d, cached %d, failed %d -> %s' % (got, skipped, failed, CACHE))


def load() -> list[dict]:
    if not os.path.isdir(CACHE):
        sys.exit('nothing cached - run with --pull first')
    out = []
    for f in sorted(os.listdir(CACHE)):
        if f.endswith('.json'):
            out.append(json.load(open(os.path.join(CACHE, f), encoding='utf-8')))
    return out


def text_of(doc: dict) -> str:
    return ' '.join(s['x'].replace('\n', ' ') for s in doc['snippets'])


def grep(pattern: str, window: int = 220) -> None:
    """Concordance. The unit is the phrase in context, because a hit on its own
    says he used a word and nothing about what he meant by it."""
    rx = re.compile(pattern)
    n = 0
    for doc in load():
        t = text_of(doc)
        for m in rx.finditer(t):
            a, b = max(0, m.start() - window // 2), min(len(t), m.end() + window // 2)
            n += 1
            print('\n[%s] ...%s...' % (doc['date'], t[a:b]))
    print('\n%d hits' % n)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--pull', action='store_true')
    ap.add_argument('--vids', default=os.environ.get('MICHA_VIDS', ''),
                    help='dir holding the harvested video channel messages.jsonl')
    ap.add_argument('--grep')
    ap.add_argument('--window', type=int, default=220)
    ap.add_argument('--stats', action='store_true')
    a = ap.parse_args()
    if a.pull:
        pull(a.vids or os.path.join(ROOT, 'vids'))
    if a.grep:
        grep(a.grep, a.window)
    if a.stats:
        docs = load()
        tot = sum(len(text_of(d)) for d in docs)
        print('%d transcripts, %s .. %s, %.0fk characters'
              % (len(docs), docs[0]['date'], docs[-1]['date'], tot / 1000))


if __name__ == '__main__':
    main()
