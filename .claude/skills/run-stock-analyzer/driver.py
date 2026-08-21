#!/usr/bin/env python
"""
driver.py — the programmatic handle on the Stock Analyzer.

Four ways in, matching the four layers a change here can touch:

    analyze  TICKERS   run the analysis engine directly, no server, no network
                       beyond yahooquery. THE path for backend/verdict work.
    check    TICKERS   the same run, asserted: JSON-serializable, required keys
                       present, and the state/action/grade story is self-consistent.
                       Exits non-zero on the first failure. Use this as the smoke test.
    api      [--port]  hit every HTTP endpoint on an already-running server.
    shot     [--url]   headless screenshot of the built frontend.

Run from the repo root with the venv interpreter:

    ./venv/Scripts/python.exe .claude/skills/run-stock-analyzer/driver.py analyze NVDA PM

Every subcommand prints a one-line PASS/FAIL summary and sets the exit code, so it
can be chained without parsing the body.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
import traceback
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
for p in (os.path.join(ROOT, "backend"), ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

# The analysis payload contract. If a key here disappears, the Angular client
# breaks silently at runtime — cheaper to catch it in the driver.
REQUIRED_TOP = ("ticker", "meta", "bars", "indicators", "overlays", "setups", "micha")
REQUIRED_META = ("sector", "industry", "logo_url", "sector_icon")
REQUIRED_MICHA = (
    "state", "action", "grade", "grade_score", "rating", "rating_max",
    "grade_breakdown", "report",
    "reasons", "options", "trigger", "alert", "hold_level", "targets", "scenarios",
    "notes", "chart_focus", "level_context",
    # micha.py rebuilds its output dict field by field, so a key computed correctly
    # in verdict.py is still dropped from the API unless it is copied across there
    # too — that is exactly how `grade_if_break` went missing once. Guard both.
    "grade_why", "grade_why_he", "grade_if_break",
)
REASON_GROUPS = {"trend", "level", "volume", "pattern", "strength", "risk", "timing"}
STANCES = {"for", "against", "note"}
REQUIRED_REPORT = ("call", "call_he", "read", "read_he", "why", "warnings")

ENTERING = {"breakout_now", "buyers_at_level", "value_pullback"}
ACTIONS = {"enter", "wait_trigger", "wait_buyers", "wait_pullback", "wait_event",
           "hold", "watch", "out", "avoid"}


# ── stdout on Windows is cp1255-ish; the payload is bilingual ────────────────
def out(s: str = "") -> None:
    sys.stdout.buffer.write((s + "\n").encode("utf-8", "replace"))
    sys.stdout.flush()


# ── analyze / check ──────────────────────────────────────────────────────────

def _analyzer():
    from analyzer import StockAnalyzer
    return StockAnalyzer()


def cmd_analyze(args) -> int:
    an = _analyzer()
    bad = 0
    for tk in args.tickers:
        try:
            r = an.analyze(tk)
        except Exception:
            out(f"\n===== {tk}: EXCEPTION\n{traceback.format_exc()}")
            bad += 1
            continue
        if not r:
            out(f"\n===== {tk}: no usable data (delisted, or < MIN_BARS history)")
            bad += 1
            continue
        m, meta = r["micha"], r["meta"]
        rep = m["report"]
        out(f"\n{'=' * 76}")
        out(f"{tk}  ${meta['price']}  150MA={meta['sma150']}  ATR%={meta['atr_pct']}")
        out(f"  STATE  {m['state']:16} ACTION {m['action']:13} "
            f"RATING {m['rating']}/10  (grade {m['grade']} {m['grade_score']})")
        for c in m["grade_breakdown"]["components"]:
            out(f"     {c['key']:8} {c['got']:>5}/{c['max']:<4} {c['detail']}")
        caps = m["grade_breakdown"]["caps"]
        if caps:
            out("     CAPS: " + "; ".join(c["key"] for c in caps))
        out(f"  CALL   {rep['call']}")
        out(f"  HE     {rep['call_he']}")
        out(f"  READ   {rep['read']}")
        for w in rep["why"]:
            out(f"     {'V' if w['ok'] else 'X'} {w['en']}")
        for o in m["options"]:
            out(f"  OPT[{o['kind']:8}] entry {o['entry']} stop {o['stop']} "
                f"({o['risk_pct']}% / {o['stop_atr']} ATR, anchored={o['stop_anchored']}) "
                f"RR {o['risk_reward']} — {o['stop_what']}")
        if m["trigger"]:
            out(f"  TRIGGER {m['trigger']['label']}")
        if m["targets"]:
            out("  TARGETS " + " | ".join(
                f"{t['price']} (+{t['pct']:.0f}% {t['label']})" for t in m["targets"]))
        if m["growth"]:
            out(f"  GROWTH  {m['growth']['label']}")
        out("  FOCUS   " + ",".join(k for k, v in m["chart_focus"].items() if v))
        out(f"  SETUPS  {meta['setup_codes']}")
    out(f"\n{'FAIL' if bad else 'PASS'}: {len(args.tickers) - bad}/{len(args.tickers)} analyzed")
    return 1 if bad else 0


def cmd_check(args) -> int:
    an = _analyzer()
    fails: list[str] = []
    for tk in args.tickers:
        try:
            r = an.analyze(tk)
        except Exception as e:
            fails.append(f"{tk}: raised {type(e).__name__}: {e}")
            continue
        if not r:
            fails.append(f"{tk}: returned None")
            continue
        try:
            json.dumps(r)
        except Exception as e:
            fails.append(f"{tk}: payload not JSON-serializable — {e}")
        for k in REQUIRED_TOP:
            if k not in r:
                fails.append(f"{tk}: missing top-level key {k!r}")
        meta = r.get("meta") or {}
        for k in REQUIRED_META:
            if k not in meta:
                fails.append(f"{tk}: meta missing {k!r}")
        # sector_icon always defaults, even for ETFs with no asset_profile — so a
        # missing one means the default fell through, not that the sector is unknown
        if not meta.get("sector_icon"):
            fails.append(f"{tk}: no sector_icon at all — the default fallback is broken")
        m = r.get("micha") or {}
        for k in REQUIRED_MICHA:
            if k not in m:
                fails.append(f"{tk}: micha missing {k!r}")
        for k in REQUIRED_REPORT:
            if k not in (m.get("report") or {}):
                fails.append(f"{tk}: micha.report missing {k!r}")
        if not r.get("bars"):
            fails.append(f"{tk}: no bars")

        # ── the story has to hold together ───────────────────────────────────
        state, action, grade = m.get("state"), m.get("action"), m.get("grade")
        if action not in ACTIONS:
            fails.append(f"{tk}: unknown action {action!r}")
        if action == "enter":
            if state not in ENTERING:
                fails.append(f"{tk}: action=enter from non-entry state {state!r}")
            if not any(o["kind"] == "now" for o in m.get("options", [])):
                fails.append(f"{tk}: action=enter but no 'now' option to take")
            if grade in ("D", "F") and not m["grade_breakdown"]["caps"]:
                fails.append(f"{tk}: action=enter graded {grade} with no cap explaining it")
        if state in ENTERING and action in ("out", "avoid"):
            fails.append(f"{tk}: state {state!r} contradicts action {action!r}")
        # the letter must never contradict the headline: "nothing here yet" / "the
        # setup is over" / "do not enter" cannot read as a good setup
        if state in ("nothing_yet", "broken", "avoid") and grade in ("A", "B"):
            fails.append(f"{tk}: state {state!r} graded {grade} — letter contradicts the call")
        for o in m.get("options", []):
            if o.get("stop") is not None and o["stop"] >= o["entry"]:
                fails.append(f"{tk}: {o['kind']} stop {o['stop']} is not below entry {o['entry']}")
        sc = m.get("grade_score")
        if sc is None or not (0 <= sc <= 100):
            fails.append(f"{tk}: grade_score out of range: {sc}")

        # the argument has to be bilingual and well-formed, or the RTL panel renders
        # blank rows the user cannot tell from "nothing to say"
        groups = m.get("reasons") or []
        if not groups:
            fails.append(f"{tk}: no reasons produced")
        n_items = 0
        for g in groups:
            if g.get("key") not in REASON_GROUPS:
                fails.append(f"{tk}: unknown reason group {g.get('key')!r}")
            if not g.get("items"):
                fails.append(f"{tk}: reason group {g.get('key')!r} is empty")
            for it in g.get("items", []):
                n_items += 1
                if it.get("stance") not in STANCES:
                    fails.append(f"{tk}: bad stance {it.get('stance')!r}")
                if not (it.get("en") or "").strip() or not (it.get("he") or "").strip():
                    fails.append(f"{tk}: reason missing en/he text in {g.get('key')!r}")
        al = m.get("alert")
        if al and not (0 < al.get("distance_atr", 0) <= 2.0):
            fails.append(f"{tk}: alert distance_atr out of band: {al.get('distance_atr')}")

        # ── the grade has to explain itself, in two sentences ────────────────
        # The panel renders `grade_why_he` where the old fixed per-letter string
        # used to sit, so an empty one leaves the badge unexplained.
        for key in ("grade_why", "grade_why_he"):
            txt = (m.get(key) or "").strip()
            if not txt:
                fails.append(f"{tk}: {key} is empty — the grade explains nothing")
            elif txt.count(".") < 2:
                fails.append(f"{tk}: {key} is not two sentences: {txt!r}")

        # ── no text may claim a line the chart does not draw ─────────────────
        # `trend` is a polyfit slope through 2y of swings and the direction-change
        # stage falls back to weekly lows; neither is a drawn object. Before this
        # was enforced, 7 of 18 names asserted rising lows over a chart with no
        # such line on it, which is the fastest way to lose a reader's trust.
        drawn_rl = any(t.get("kind") == "rising_lows"
                       for t in (r.get("overlays") or {}).get("trendlines") or [])
        if not drawn_rl:
            claims = [w["he"] for w in (m.get("report") or {}).get("why", [])
                      if w.get("ok") and "קו שפלים" in w.get("he", "")]
            claims += [it["he"] for g in groups for it in g.get("items", [])
                       if "קו השפלים" in it.get("he", "")]
            if "קו השפלים" in (m.get("grade_why_he") or ""):
                claims.append(m["grade_why_he"])
            for c in claims:
                fails.append(f"{tk}: claims a rising-lows LINE with none drawn — {c!r}")

        out(f"  {tk:6} {state:16} {action:13} {grade} {sc:<5} "
            f"{len(groups)} groups / {n_items} reasons"
            + (f"  ALERT {al['tier']}" if al else ""))

    if fails:
        out("\nFAIL:")
        for f in fails:
            out("  - " + f)
        return 1
    out(f"\nPASS: {len(args.tickers)} tickers, payload + consistency checks clean")
    return 0


# ── api ──────────────────────────────────────────────────────────────────────

def _get(url: str, timeout: int = 180):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def cmd_api(args) -> int:
    base = f"http://localhost:{args.port}"
    fails = []
    try:
        h = _get(f"{base}/api/health", 10)
        assert h.get("status") == "ok", h
        out(f"  health   ok")
    except Exception as e:
        out(f"  health   FAILED — is the server up? ({e})")
        out(f"\nFAIL: start it first:  ./venv/Scripts/python.exe main.py")
        return 1
    try:
        t = _get(f"{base}/api/tickers", 60)
        out(f"  tickers  {t['count']} symbols")
        assert t["count"] > 0
    except Exception as e:
        fails.append(f"tickers: {e}")
    for tk in args.tickers:
        try:
            a = _get(f"{base}/api/analyze/{tk}")
            m = a["micha"]
            out(f"  analyze  {tk}: {len(a['bars'])} bars, {m['state']}/{m['action']}, grade {m['grade']}")
        except Exception as e:
            fails.append(f"analyze {tk}: {e}")
        try:
            v = _get(f"{base}/api/micha/{tk}")
            out(f"  micha    {tk}: ${v['price']} {v['micha']['grade']}")
        except Exception as e:
            fails.append(f"micha {tk}: {e}")
    try:
        s = _get(f"{base}/api/scan?limit={args.scan}&workers=4", 600)
        out(f"  scan     matched {s['matched']}/{s['scanned']}")
    except Exception as e:
        fails.append(f"scan: {e}")
    if fails:
        out("\nFAIL:")
        for f in fails:
            out("  - " + f)
        return 1
    out("\nPASS: all endpoints responded")
    return 0


# ── shot ─────────────────────────────────────────────────────────────────────

EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def _browser() -> str | None:
    for p in EDGE_CANDIDATES:
        if os.path.exists(p):
            return p
    for name in ("chrome.exe", "msedge.exe"):
        hits = glob.glob(rf"C:\Program Files*\**\{name}", recursive=True)
        if hits:
            return hits[0]
    return None


def cmd_shot(args) -> int:
    exe = _browser()
    if not exe:
        out("FAIL: no Edge/Chrome found — install one or pass --browser")
        return 1
    dest = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    if os.path.exists(dest):
        os.remove(dest)
    cmd = [
        exe, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
        f"--window-size={args.size}",
        # the app fetches its analysis on load, then lightweight-charts paints;
        # virtual time lets headless fast-forward that wait deterministically
        f"--virtual-time-budget={args.wait}",
        f"--screenshot={dest}", args.url,
    ]
    subprocess.run(cmd, capture_output=True, timeout=args.wait / 1000 + 90)
    if not os.path.exists(dest) or os.path.getsize(dest) < 5000:
        out(f"FAIL: no usable screenshot at {dest}")
        out("  is the static server up?  cd frontend/dist/stock-analyzer && python -m http.server 8123")
        return 1
    out(f"PASS: {os.path.getsize(dest)} bytes -> {dest}")
    out("  now LOOK at it — a blank or error page still writes a valid PNG")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("analyze", help="run the engine directly (no server)")
    a.add_argument("tickers", nargs="+")
    a.set_defaults(fn=cmd_analyze)

    c = sub.add_parser("check", help="assert payload shape + verdict consistency")
    c.add_argument("tickers", nargs="*", default=["NVDA", "PM", "ARM", "OPEN", "GOOGL"])
    c.set_defaults(fn=cmd_check)

    p = sub.add_parser("api", help="smoke an already-running server")
    p.add_argument("--port", type=int, default=10000)
    p.add_argument("--scan", type=int, default=4)
    p.add_argument("tickers", nargs="*", default=["NVDA"])
    p.set_defaults(fn=cmd_api)

    s = sub.add_parser("shot", help="headless screenshot of the built frontend")
    s.add_argument("--url", default="http://localhost:8123/")
    s.add_argument("--out", default="shot.png")
    s.add_argument("--size", default="1600,1000")
    s.add_argument("--wait", type=int, default=25000, help="virtual-time budget, ms")
    s.set_defaults(fn=cmd_shot)

    args = ap.parse_args()
    if getattr(args, "tickers", None):
        args.tickers = [t.strip().upper() for t in args.tickers]
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
