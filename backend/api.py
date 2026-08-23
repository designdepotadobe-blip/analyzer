"""
FastAPI backend for the stock analyzer.

Endpoints
---------
GET /api/health                  → liveness probe
GET /api/tickers                 → universe from TickerFinder (Dow/Nasdaq100/S&P500)
GET /api/analyze/{ticker}        → full analysis + chart geometry for one ticker
GET /api/scan?setup=&limit=      → scan the universe, return only stocks with ≥1 setup
                                    (optionally filter by a specific setup code)
GET /api/scan?...&stream=true    → same filters, but a server-sent-events stream:
                                    one `data:` line per hit AS IT COMPLETES, then a
                                    closing `{"done":true,"scanned":N,"matched":M}` —
                                    for a live-updating scan UI instead of a multi-
                                    minute blank wait. `stream` defaults to false, so
                                    every existing caller (driver.py included) is
                                    completely unaffected.

Run:  uvicorn backend.api:app --reload --port 8000
      (from the project root, d:\\pythonProject7)
"""

from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache

from datetime import datetime, timezone

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

# make both this dir (analyzer.py) and the project root (ticker_finder.py) importable,
# whether launched as `uvicorn backend.api:app` or imported as a module
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _p in (_HERE, _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from analyzer import StockAnalyzer  # noqa: E402
from config import ATR_PCT_HIGH, ATR_PCT_LOW, STOP_IDEAL_ATR  # noqa: E402
from ticker_finder import TickerFinder  # noqa: E402
from verdict import Judgement  # noqa: E402

app = FastAPI(title="Stock Analyzer API", version="1.0")

# Angular dev server runs on :6000
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

analyzer = StockAnalyzer()


@lru_cache(maxsize=1)
def _universe() -> tuple[str, ...]:
    """Ticker universe, cached for the process lifetime."""
    try:
        names = list(TickerFinder().find_tickers())
        # de-dupe, drop blanks, keep order
        seen, out = set(), []
        for n in names:
            if n and n not in seen:
                seen.add(n)
                out.append(n)
        return tuple(out)
    except Exception:
        # fallback so the API is still usable if pytickersymbols fails
        return ('AAPL', 'MSFT', 'NVDA', 'GOOGL', 'META', 'AMZN', 'GTLB',
                'ORCL', 'NEE', 'LITE', 'NVTS', 'TE')


@app.get("/")
def root():
    # Deploy platforms (Railway included) default their own healthcheck to
    # GET / — this API otherwise has no route there, which made Railway treat
    # an actually-healthy container as failed and never cut public traffic
    # over to it (502 at the edge despite a clean startup log).
    return {"status": "ok", "docs": "/docs"}


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/tickers")
def tickers():
    u = _universe()
    return {"count": len(u), "tickers": list(u)}


@app.get("/api/analyze/{ticker}")
def analyze(ticker: str):
    import traceback
    ticker = ticker.strip().upper()
    try:
        result = analyzer.analyze(ticker)
    except Exception as e:
        traceback.print_exc()          # full stack trace in the backend terminal
        raise HTTPException(status_code=502, detail=f"analysis failed: {e}")
    if result is None:
        raise HTTPException(status_code=404, detail=f"no usable data for {ticker}")
    return result


@app.get("/api/micha/{ticker}")
def micha(ticker: str):
    """Just the Micha-style verdict + scorecard for one ticker (lighter payload)."""
    import traceback
    ticker = ticker.strip().upper()
    try:
        result = analyzer.analyze(ticker)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=502, detail=f"analysis failed: {e}")
    if result is None:
        raise HTTPException(status_code=404, detail=f"no usable data for {ticker}")
    return {
        'ticker': ticker,
        'price': result['meta']['price'],
        'meta': result['meta'],
        'micha': result['micha'],
    }


ACTIONABLE_NOW = ('breakout_now', 'buyers_at_level', 'value_pullback')
GRADE_RANK = {'F': 0, 'D': 1, 'C': 2, 'B': 3, 'A': 4}

# ── Scanner presets ─────────────────────────────────────────────────────────
# A scan sorted purely by grade converges on the same handful of large, calm,
# already-clean names every time — they satisfy every axis at once, so they
# always win the sort, and a reader gets one flavour of idea regardless of what
# they're actually looking for today. Four presets, one per trading profile he
# names distinctly rather than grading the same way: the momentum chase, the
# name about to decide, the clean swing, and the base still under its 150.
#
# Each is a PREDICATE over fields the scan hit already carries — no new
# per-ticker computation, just a different question asked of the same numbers.
# Thresholds reuse constants already calibrated elsewhere in this codebase
# (ATR_PCT_HIGH/LOW are the exact watermark-circle cutoffs on his own charts,
# MIN_MARKET_CAP is his own screen) rather than inventing a fifth opinion of
# "what counts as volatile" or "what counts as small".
def _preset_ok(preset: str, m: dict, meta: dict, best: dict | None, al: dict | None) -> bool:
    atr_pct = meta.get('atr_pct') or 0
    if preset == 'aggressive':
        # explosive potential, wider risk — a real momentum setup, not merely a
        # volatile ticker sitting there doing nothing
        return bool(
            (m.get('market_cap') or 0) < 50_000_000_000
            and atr_pct >= ATR_PCT_HIGH
            and m['state'] in ACTIONABLE_NOW + ('at_trigger',))
    if preset == 'ready':
        # imminent, specifically — not already in hand (that's `enter`) and not
        # merely on the radar (that's a wider `alerting` sweep); reuses the SAME
        # tiers verdict._headline_action already resolves to READY, so this list
        # and that badge can never name a different set of tickers
        return m.get('headline_action') == 'READY'
    if preset == 'conservative':
        # clean confirmation, calm volatility, a real entry in hand — the
        # opposite profile from `aggressive`, not just "high grade". Measured:
        # requiring `confirmation.status == 'confirmed'` specifically (an event
        # 8+ bars old — EVENT_CONFIRM_BARS) alongside the other four conditions
        # left 2 of 517 names standing, which does not give a reader a list to
        # browse. Loosened to excluding only 'unconfirmed' (nothing has
        # happened at all) — a fresh but real event is still a clean one, it
        # just has not aged into the "confirmed" label yet.
        return bool(
            m['state'] in ACTIONABLE_NOW
            and GRADE_RANK.get(m['grade'], 0) >= GRADE_RANK['B']
            and atr_pct <= ATR_PCT_LOW
            and (m.get('confirmation') or {}).get('status') != 'unconfirmed'
            and (best or {}).get('stop_atr') is not None
            and best['stop_atr'] <= STOP_IDEAL_ATR[1])
    if preset == 'reversal':
        # `turning` is by construction only ever returned while still under the
        # 150 (`Judgement._state`: "if turned and not ctx.above_150: return
        # 'turning'") — a confirmed bearish-to-bullish sequence, no extra check
        # needed. `value_pullback`/`buyers_at_level` are the mirror case his own
        # phrase names — a bounce back to the average as support, not away from
        # a downtrend, but the same "reclaiming structure" shape.
        return m['state'] in ('turning', 'value_pullback', 'buyers_at_level')
    return True


@app.get("/api/scan")
def scan(
    setup: str | None = Query(None, description="filter by a setup code, e.g. bull_flag"),
    # `_universe()[:limit]` already clamps to the real universe size (~517
    # Dow+Nasdaq100+S&P500 names) regardless of how high this goes, so the ceiling
    # here is just a safety bound, not a real constraint — it must sit ABOVE the
    # universe size or the client's own "scan everything" option (517) gets
    # rejected outright with a 422 before a single ticker runs. Found via an actual
    # end-to-end run, not inspection: `le=500` silently broke the Radar page's own
    # "הכל" scope chip, and on the streaming endpoint a 422 reads to `EventSource`
    # as an immediate connection error with no explanation in the UI.
    limit: int = Query(60, ge=1, le=600, description="max tickers to scan"),
    workers: int = Query(8, ge=1, le=24),
    alerting: bool = Query(False, description="only names close to their trigger"),
    actionable: bool = Query(False, description="only names tradeable today or ready"),
    min_grade: str | None = Query(None, description="A | B | C | D | F — floor, inclusive"),
    preset: str | None = Query(None, description="aggressive | ready | conservative | reversal — "
                                                  "a distinct trading profile, not another grade floor"),
    sort: str = Query("setups", description="setups | alert | grade | expectancy | rr | gain | risk"),
    stream: bool = Query(False, description="server-sent events: one hit per line, "
                                            "as it completes, instead of one blob at the end"),
):
    """
    Scan the universe. `alerting=true` answers the question the per-stock panel can
    only answer one symbol at a time: which names are NOT a trade today but sit within
    a daily range or two of the price that would make them one — "מתקרב להכרעה. שימו
    התראה" (ONDS). Sort by `alert` to get the closest ones first.

    `actionable=true` is the stricter question the watchlist actually asks: what can I
    act on TODAY. That is either an entry state right now, or coiled at the trigger
    with the alert already imminent/close — "ready for it". Pair it with `min_grade`
    so a name that is merely close but structurally poor cannot reach the list.

    `stream=true` turns this into a live feed instead of a blocking scan-then-return:
    a 250-517 ticker scan is a multi-minute wait if the client has to sit through the
    whole `ThreadPoolExecutor` batch before rendering anything. `work()` below is
    unchanged either way — streaming only changes how already-computed hits leave the
    process, one `as_completed()` result at a time instead of collected into a list.
    """
    universe = _universe()[:limit]
    hits = []

    def work(tk: str):
        # The WHOLE body is guarded, not just `analyze()` — a scan is 60-517
        # independent tickers, and one name with an unusual data shape tripping a
        # KeyError/TypeError three lines below here must not cost every OTHER
        # ticker's result. That used to be merely a clean 500 on the blocking
        # endpoint (annoying); on the streaming endpoint an uncaught exception
        # here kills the whole generator mid-stream and the client loses every
        # result already shown — found via a real end-to-end run at limit=517,
        # not by inspection, which is exactly the failure mode this guards.
        try:
            r = analyzer.analyze(tk)
            if not r:
                return None
            m = r['micha']
            al = m.get('alert')
            if alerting and not al:
                return None
            if actionable:
                # tradeable now, or coiled right under the trigger with the alert
                # already firing — anything further out is a watchlist item, not
                # today's decision
                ready = (m['state'] == 'at_trigger'
                         and (al or {}).get('tier') in ('imminent', 'close'))
                if m['state'] not in ACTIONABLE_NOW and not ready:
                    return None
            elif not alerting and not r['setups']:
                return None
            if min_grade and GRADE_RANK.get(m['grade'], 0) < GRADE_RANK.get(min_grade.upper(), 0):
                return None
            codes = r['meta']['setup_codes']
            if setup and setup not in codes:
                return None
            best = Judgement._best_option(m['options'], m['action'])
            g = m.get('growth')
            if preset and not _preset_ok(preset, m, r['meta'], best, al):
                return None
            return {
                'ticker': tk,
                'price': r['meta']['price'],
                'above_150': r['meta']['above_150'],
                'market_cap': m.get('market_cap'),
                'sma150_dist_pct': r['meta']['sma150_dist_pct'],
                # the verdict, so a scan row is readable without a second request
                'state': m['state'],
                'action': m['action'],
                # the 4-value ENTER/WAIT/WATCH/AVOID bucket — see verdict.HEADLINE_ACTION
                'headline_action': m.get('headline_action'),
                # unconfirmed / pending / confirmed — see verdict._confirmation
                'confirmation': m.get('confirmation'),
                # the full pattern projection, labeled — see verdict._macro_target
                'macro_target': m.get('macro_target'),
                'grade': m['grade'],
                'grade_score': m['grade_score'],
                # the headline 1-10 the cards lead with — see verdict._rating
                'rating': m.get('rating'), 'rating_max': m.get('rating_max'),
                'call_he': m['report']['call_he'],
                # The WHY. `call_he` restates the entry and the stop, which the row
                # already prints as prices — on a card the two together said the
                # same number three times. `read_he` is the half of his post that
                # is not a number ("נכנסו קונים על הרמה, ממוצע 150 מתחת").
                'read_he': m['report']['read_he'],
                # "close to becoming relevant", independent of the grade
                'alert': al,
                'setup_count': len(r['setups']),
                'setups': [{'code': s['code'], 'label': s['label'], 'active': s['active']}
                           for s in r['setups']],
                # ── everything the watchlist and the portfolio builder rank on ──
                # Sector is free here: analyze() already fetched the profile for
                # the header, so this is a dict lookup, not another request.
                'sector': r['meta'].get('sector'),
                'sector_icon': r['meta'].get('sector_icon'),
                'atr_pct': r['meta'].get('atr_pct'),
                # the option the reader is actually being pointed at, flattened —
                # a scan row has to be rankable without a second request per name
                'entry': (best or {}).get('entry'),
                'stop': (best or {}).get('stop'),
                'stop_atr': (best or {}).get('stop_atr'),
                'risk_pct': (best or {}).get('risk_pct'),
                'risk_reward': (best or {}).get('risk_reward'),
                'size_pct_of_account': (best or {}).get('size_pct_of_account'),
                'p_win': (best or {}).get('p_win'),
                'expectancy_r': (best or {}).get('expectancy_r'),
                'option_kind': (best or {}).get('kind'),
                # potential gain, priced with its own odds (see micha._growth)
                'gain_pct': (g or {}).get('gain_pct'),
                'gain_days': (g or {}).get('days'),
                'gain_hit_rate': (g or {}).get('hit_rate'),
                'pct_per_day': (g or {}).get('pct_per_day'),
                # how well-defended the price that starts the trade is — a
                # horizontal level carries a touch history, a trendline or an
                # average does not
                'trigger_wall': (m.get('trigger') or {}).get('wall'),
                # The line the stock has to CROSS, and his own name for it. This is
                # the headline of essentially every post he writes ("פריצה מעל
                # 21.45$", "מעל 552. אם לא עוברת מעל אין טרייד") and the scan row
                # was ranking on expectancy while never showing it — the reader got
                # "E +0.53R" where he would have written a price.
                'trigger': (m.get('trigger') or {}).get('price'),
                'trigger_what_he': (m.get('trigger') or {}).get('what_he'),
                # what the rating becomes if the trigger clears — slim on purpose:
                # a scan row is 60-517 of these, and the full grade_if_break
                # breakdown (axis-by-axis, caps, why text) is the single-stock
                # view's job. See verdict._grade_if_break.
                'if_break_rating': (m.get('grade_if_break') or {}).get('rating'),
                'if_break_moves': (m.get('grade_if_break') or {}).get('moves'),
            }
        except Exception:
            return None

    if stream:
        # No final sort here — the client re-sorts/re-slices reactively off the raw
        # stream as hits arrive (the Radar page already does this via `sortRows()`),
        # so a server-side sort would just be thrown away work.
        def sse():
            matched = 0
            with ThreadPoolExecutor(max_workers=workers) as ex:
                for fut in as_completed([ex.submit(work, tk) for tk in universe]):
                    # Belt-and-suspenders on top of `work()`'s own guard: `work`
                    # should never raise now, but for a LIVE view losing every
                    # result already shown to one future's unexpected exception
                    # is a far worse failure than the blocking endpoint's clean
                    # 500 ever was, so this loop skips a bad future instead of
                    # ending the whole stream over it.
                    try:
                        res = fut.result()
                    except Exception:
                        continue
                    if res:
                        matched += 1
                        yield f"data: {json.dumps(res)}\n\n"
            yield f"data: {json.dumps({'done': True, 'scanned': len(universe), 'matched': matched})}\n\n"

        return StreamingResponse(sse(), media_type="text/event-stream")

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for fut in as_completed([ex.submit(work, tk) for tk in universe]):
            # `work()` is fully guarded now (see above) so this shouldn't fire,
            # kept for symmetry with the streaming branch's identical guard.
            try:
                res = fut.result()
            except Exception:
                continue
            if res:
                hits.append(res)

    if sort == 'alert':
        # nearest trigger first; names with no alert sink to the bottom
        hits.sort(key=lambda h: (h['alert'] or {}).get('distance_atr', 1e9))
    elif sort == 'grade':
        hits.sort(key=lambda h: -h['grade_score'])
    elif sort == 'expectancy':
        # the ranking that actually compares a 12%/10R home run with a 55%/1R scalp
        hits.sort(key=lambda h: -(h.get('expectancy_r') or -9))
    elif sort == 'rr':
        hits.sort(key=lambda h: -(h.get('risk_reward') or 0))
    elif sort == 'gain':
        hits.sort(key=lambda h: -(h.get('gain_pct') or 0))
    elif sort == 'risk':
        # tightest real stop first — "sitting on the correct price to enter"
        hits.sort(key=lambda h: (h.get('stop_atr') if h.get('stop_atr') is not None else 1e9))
    else:
        hits.sort(key=lambda h: (-h['setup_count'],
                                 -sum(1 for s in h['setups'] if s['active'])))
    return {"scanned": len(universe), "matched": len(hits), "results": hits}


# ── Analyst notes: the hidden per-analysis feedback box ──────────────────────
# Reached only through the front-end's own easter egg (no route/button points here
# for an ordinary user) — deliberately unauthenticated rather than built out with
# real accounts, since the owner asked not to take on user-rights management for
# this. Every submission is just appended to a local, gitignored JSONL file; NOTHING
# here reads it back into the grade automatically. The owner reviews the file by
# hand (or hands it to a future session with "read analyst_notes.jsonl and fix the
# code accordingly") and decides what, if anything, becomes a real change — same
# arm's-length shape as the Discord corpus (`discord_harvest.py`/`tools/corpus.py`),
# just sourced from typing directly on the analysis being looked at instead of a
# Discord post.
NOTES_PATH = os.path.join(_ROOT, 'analyst_notes.jsonl')


@app.post("/api/notes")
def add_note(payload: dict = Body(...)):
    ticker = str(payload.get('ticker') or '').strip().upper()
    note = str(payload.get('note') or '').strip()
    if not ticker or not note:
        raise HTTPException(status_code=400, detail="ticker and note are required")
    row = {
        'ts': datetime.now(timezone.utc).isoformat(),
        'ticker': ticker,
        'note': note,
        # Whatever the panel was showing when the note was written — so reading
        # this back later doesn't require re-running analyze() against a price
        # that has since moved to reconstruct what was actually being reacted to.
        'context': {
            'price': payload.get('price'),
            'grade': payload.get('grade'),
            'grade_score': payload.get('grade_score'),
            'state': payload.get('state'),
            'action': payload.get('action'),
        },
    }
    with open(NOTES_PATH, 'a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')
    return {'saved': True}
