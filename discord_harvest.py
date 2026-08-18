"""
discord_harvest.py — pull the FULL channel history to disk, so the analysis work
has a corpus to measure against.

`discord_reader.py` is the live viewer: it prints messages and follows the channel
in real time. This is the archiver — it walks the whole history backwards, handles
rate limits, resumes where it left off, and writes raw JSON plus the chart images
that the measurements actually need.

    python discord_harvest.py                      # everything, text only
    python discord_harvest.py --images             # ...and download attachments
    python discord_harvest.py --since 2024-12-01   # stop once older than this
    python discord_harvest.py --max 500            # cap the message count

Credentials come from .env, exactly as discord_reader.py reads them:

    DISCORD_TOKEN=<your token>
    DISCORD_CHANNEL_ID=<channel id>

Output (default ./corpus):
    corpus/messages.jsonl   one raw message dict per line, newest-first as fetched
    corpus/images/          attachments, named <message_id>__<filename>
    corpus/state.json       the oldest id reached, so a re-run resumes

Re-running is safe: it reads the existing state and continues further back rather
than re-downloading what is already on disk.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN", "")
CHANNEL_ID = os.getenv("DISCORD_CHANNEL_ID", "")

if not TOKEN or not CHANNEL_ID:
    sys.exit(
        "Set DISCORD_TOKEN and DISCORD_CHANNEL_ID in .env (same two names\n"
        "discord_reader.py uses). Create the file next to this script:\n"
        "    DISCORD_TOKEN=...\n"
        "    DISCORD_CHANNEL_ID=...\n"
    )

API = "https://discord.com/api/v10"
HEADERS = {
    "Authorization": TOKEN,
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0",
}


def _get(url: str, params: dict | None = None, stream: bool = False):
    """GET with Discord's 429 handling. Everything else is the caller's problem."""
    for attempt in range(6):
        r = requests.get(url, headers=HEADERS, params=params, stream=stream, timeout=60)
        if r.status_code == 429:
            # Discord tells us exactly how long to wait; obey it rather than guess.
            try:
                wait = float(r.json().get("retry_after", 2.0))
            except Exception:
                wait = 2.0
            print(f"    rate limited, sleeping {wait:.1f}s", flush=True)
            time.sleep(wait + 0.25)
            continue
        if r.status_code == 401:
            sys.exit("401 Unauthorized — token is invalid or expired")
        if r.status_code == 403:
            sys.exit("403 Forbidden — no access to this channel")
        return r
    sys.exit("gave up after repeated rate limits")


def _ts(msg: dict) -> str:
    return (msg.get("timestamp") or "")[:19]


def harvest(out_dir: str, max_msgs: int | None, since: str | None,
            want_images: bool) -> None:
    os.makedirs(out_dir, exist_ok=True)
    jsonl = os.path.join(out_dir, "messages.jsonl")
    state_path = os.path.join(out_dir, "state.json")

    # Resume: continue from the oldest id already on disk.
    before = None
    have = 0
    if os.path.exists(state_path):
        try:
            st = json.load(open(state_path, encoding="utf-8"))
            before, have = st.get("oldest_id"), st.get("count", 0)
            if before:
                print(f"resuming from message {before} ({have} already saved)")
        except Exception:
            pass

    fetched = 0
    stop = False
    with open(jsonl, "a", encoding="utf-8") as fh:
        while not stop:
            params = {"limit": 100}
            if before:
                params["before"] = before
            r = _get(f"{API}/channels/{CHANNEL_ID}/messages", params=params)
            if r.status_code != 200:
                print(f"  HTTP {r.status_code}: {r.text[:200]}")
                break
            batch = r.json()
            if not batch:
                print("reached the beginning of the channel")
                break

            for m in batch:
                if since and _ts(m) and _ts(m)[:10] < since:
                    stop = True
                    break
                fh.write(json.dumps(m, ensure_ascii=False) + "\n")
                fetched += 1
                if max_msgs and fetched >= max_msgs:
                    stop = True
                    break

            before = batch[-1]["id"]
            fh.flush()
            json.dump({"oldest_id": before, "count": have + fetched},
                      open(state_path, "w", encoding="utf-8"))
            oldest = _ts(batch[-1])[:10]
            print(f"  {have + fetched} messages … back to {oldest}", flush=True)

    print(f"\nsaved {fetched} new messages -> {jsonl}")

    if want_images:
        download_images(out_dir)


def download_images(out_dir: str) -> None:
    """Download every attachment referenced in messages.jsonl that isn't on disk yet."""
    jsonl = os.path.join(out_dir, "messages.jsonl")
    img_dir = os.path.join(out_dir, "images")
    os.makedirs(img_dir, exist_ok=True)
    if not os.path.exists(jsonl):
        print("no messages.jsonl yet — nothing to download")
        return

    jobs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for line in open(jsonl, encoding="utf-8"):
        try:
            m = json.loads(line)
        except Exception:
            continue
        mid = m.get("id", "?")
        for att in m.get("attachments") or []:
            url, name = att.get("url"), att.get("filename", "att")
            if url:
                jobs.append((url, f"{mid}__{name}"))
        for emb in m.get("embeds") or []:
            url = (emb.get("image") or {}).get("url")
            if url:
                jobs.append((url, f"{mid}__embed.png"))

    got = skipped = failed = 0
    for url, name in jobs:
        if name in seen:
            continue
        seen.add(name)
        dest = os.path.join(img_dir, name)
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            skipped += 1
            continue
        try:
            r = _get(url, stream=True)
            if r.status_code != 200:
                failed += 1
                continue
            with open(dest, "wb") as f:
                for chunk in r.iter_content(65536):
                    f.write(chunk)
            got += 1
            if got % 25 == 0:
                print(f"    {got} images…", flush=True)
        except Exception:
            failed += 1

    print(f"images: {got} downloaded, {skipped} already present, {failed} failed "
          f"-> {img_dir}")


def summarise(out_dir: str) -> None:
    """What did we actually get? Printed so the corpus can be sanity-checked at a glance."""
    jsonl = os.path.join(out_dir, "messages.jsonl")
    if not os.path.exists(jsonl):
        return
    n = with_text = with_img = 0
    authors: dict[str, int] = {}
    first = last = None
    for line in open(jsonl, encoding="utf-8"):
        try:
            m = json.loads(line)
        except Exception:
            continue
        n += 1
        t = _ts(m)[:10]
        if t:
            first = t if first is None or t < first else first
            last = t if last is None or t > last else last
        if (m.get("content") or "").strip():
            with_text += 1
        if (m.get("attachments") or m.get("embeds")):
            with_img += 1
        a = (m.get("author") or {}).get("username", "?")
        authors[a] = authors.get(a, 0) + 1
    print(f"\ncorpus: {n} messages, {first} .. {last}")
    print(f"  with text: {with_text}   with an image/embed: {with_img}")
    top = sorted(authors.items(), key=lambda kv: -kv[1])[:5]
    print("  top authors: " + ", ".join(f"{a} ({c})" for a, c in top))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="corpus", help="output directory (default: corpus)")
    ap.add_argument("--max", type=int, default=None, help="stop after N new messages")
    ap.add_argument("--since", default=None, help="stop once older than YYYY-MM-DD")
    ap.add_argument("--images", action="store_true", help="also download attachments")
    ap.add_argument("--images-only", action="store_true",
                    help="skip fetching, just download images for what is on disk")
    a = ap.parse_args()

    if a.images_only:
        download_images(a.out)
    else:
        harvest(a.out, a.max, a.since, a.images)
    summarise(a.out)


if __name__ == "__main__":
    main()
