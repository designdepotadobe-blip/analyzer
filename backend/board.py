"""
board.py — the daily board: the whole universe analysed ONCE per session, stored,
and compared with the previous board.

The verdict is decided on the last CLOSED daily bar (analyzer._partial_today), so
nothing in it can change between one close and the next — scanning the universe
again whenever someone opens the Radar recomputed the same answer for minutes at a
time. The board is built once after the US close, kept on disk, and the Radar reads
it instantly; every filter runs client-side on the stored rows.

    built   weekdays after BUILD_AFTER (New York time), and on startup when the
            stored board is older than the last completed session
    refresh weekdays in the pre-market window: quotes only, for the names on the
            board, so the morning read shows where they are trading before the bell
    changes the board vs the one before it — new entries, breakouts through
            yesterday's trigger, names that came within reach of their trigger, and
            setups that ended (lost yesterday's stop / turned "out")

Storage: BOARD_DIR (env), default <repo>/.data/board. On Railway that directory must
be a mounted volume, or every redeploy starts from an empty board (and rebuilds).
"""

from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Callable, Optional
from zoneinfo import ZoneInfo

ET = ZoneInfo('America/New_York')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOARD_DIR = os.environ.get('BOARD_DIR') or os.path.join(ROOT, '.data', 'board')
BUILD_AFTER = (16, 40)                 # ET — the close has settled in the daily bars
PREMARKET = ((7, 0), (9, 29))          # ET window for the quotes-only refresh
KEEP_BOARDS = 15
WORKERS = 4
PACE_S = 0.5                           # min gap between starting two names (~10 min / 1120)
THROTTLE_WINDOW = 30                   # half of the last 30 empty → the provider is throttling
COOL_DOWN_S = 120                      # …so everyone waits this long before the next name
# (pause before, workers) for each later pass over the names that got no data
RETRY_PASSES = ((180, 2), (300, 1))

CHANGE_ORDER = ('new_enter', 'broke_out', 'near_trigger', 'setup_over')


def last_session(now: Optional[datetime] = None) -> str:
    """The date (ET) of the last COMPLETED session — counted from BUILD_AFTER, when the
    close has settled in the daily bars. Holidays are not known; on one the board is
    simply rebuilt from unchanged bars."""
    now = now or datetime.now(ET)
    d = now.date()
    if now.weekday() >= 5 or (now.hour, now.minute) < BUILD_AFTER:
        d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.isoformat()


def _alert_close(h: Optional[dict]) -> bool:
    return bool(h and (h.get('alert') or {}).get('tier') in ('imminent', 'close'))


def compute_changes(cur: dict, prev: dict) -> list:
    """What happened between the previous board and this one, per ticker."""
    out = []
    for tk, h in cur.items():
        p = prev.get(tk)
        base = {'ticker': tk, 'price': h.get('price'), 'rating': h.get('rating'),
                'sector': h.get('sector'), 'action': h.get('action')}
        if h.get('action') == 'enter' and (not p or p.get('action') != 'enter'):
            out.append({**base, 'kind': 'new_enter', 'text_he': h.get('call_he') or 'נקודת כניסה'})
            continue
        pt, pp = (p or {}).get('trigger'), (p or {}).get('price')
        if pt and pp is not None and pp < pt <= (h.get('price') or 0):
            out.append({**base, 'kind': 'broke_out',
                        'text_he': f"פרצה את {pt:.2f} — סגירה ב-{h['price']:.2f}"})
            continue
        if _alert_close(h) and h.get('action') != 'enter' and not _alert_close(p):
            al = h['alert']
            out.append({**base, 'kind': 'near_trigger',
                        'text_he': f"{al['distance_atr']:.1f} ATR ממחיר הפריצה {al['price']:.2f}"})
            continue
        if p and p.get('action') in ('enter', 'wait_trigger', 'wait_buyers', 'wait_pullback', 'hold'):
            ps = p.get('stop')
            if ps and (h.get('price') or 0) < ps:
                out.append({**base, 'kind': 'setup_over',
                            'text_he': f"סגרה מתחת לסטופ {ps:.2f} — הסט-אפ נגמר"})
            elif h.get('action') == 'out':
                out.append({**base, 'kind': 'setup_over', 'text_he': 'הסט-אפ נגמר'})
    out.sort(key=lambda c: (CHANGE_ORDER.index(c['kind']), -(c.get('rating') or 0)))
    return out


def radar_rows(hits: dict) -> list:
    """The rows the Radar shows: in an entry state, close to the trigger, or in a
    preset's population — the rest are kept only to compare tomorrow against."""
    return [h for h in hits.values()
            if h.get('headline_action') == 'ENTER' or h.get('presets')
            or (h.get('state') == 'at_trigger'
                and (h.get('alert') or {}).get('tier') in ('imminent', 'close'))]


class Board:
    def __init__(self, universe: Callable[[], list], analyze: Callable[[str], Optional[dict]],
                 to_row: Callable[[str, dict], Optional[dict]],
                 quote: Optional[Callable[[str], Optional[dict]]] = None):
        self._universe, self._analyze, self._to_row, self._quote = universe, analyze, to_row, quote
        self._lock = threading.Lock()
        self._latest: Optional[dict] = None
        self._last_fail = 0.0
        self.status = {'building': False, 'done': 0, 'total': 0, 'started_at': None, 'error': None}
        os.makedirs(BOARD_DIR, exist_ok=True)
        self._latest = self._load_latest()

    # ── storage ────────────────────────────────────────────────────────────────
    def _files(self) -> list:
        return sorted(f for f in os.listdir(BOARD_DIR) if f.startswith('board_') and f.endswith('.json'))

    def _load(self, name: str) -> Optional[dict]:
        try:
            with open(os.path.join(BOARD_DIR, name), encoding='utf-8') as fh:
                return json.load(fh)
        except Exception:
            return None

    def _load_latest(self) -> Optional[dict]:
        files = self._files()
        return self._load(files[-1]) if files else None

    def _save(self, board: dict) -> None:
        name = f"board_{board['date']}.json"
        tmp = os.path.join(BOARD_DIR, name + '.tmp')
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(board, fh, ensure_ascii=False)
        os.replace(tmp, os.path.join(BOARD_DIR, name))
        for old in self._files()[:-KEEP_BOARDS]:
            try:
                os.remove(os.path.join(BOARD_DIR, old))
            except OSError:
                pass

    def latest(self) -> Optional[dict]:
        return self._latest

    # ── build ──────────────────────────────────────────────────────────────────
    def _work(self, tk: str):
        """(ticker, row or None, answered) — `answered` False when the data never came."""
        try:
            r = self._analyze(tk)
            return tk, (self._to_row(tk, r) if r else None), r is not None
        except Exception:
            return tk, None, False

    def _pass(self, names: list, workers: int, pace: float, hits: dict, count: bool = False) -> list:
        """One paced pass over `names`; fills `hits`, returns the names that got no data."""
        failed: list = []
        recent: list = []                       # last outcomes, True = no data
        gate = threading.Lock()
        state = {'next_at': 0.0, 'cool_until': 0.0}

        def paced(tk):
            with gate:                          # one start per `pace`, and none while cooling
                wait = max(state['next_at'], state['cool_until']) - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
                state['next_at'] = time.monotonic() + pace
            return self._work(tk)

        with ThreadPoolExecutor(max_workers=workers) as ex:
            for fut in as_completed([ex.submit(paced, tk) for tk in names]):
                tk, row, ok = fut.result()
                if count:
                    self.status['done'] += 1
                if row:
                    hits[tk] = row
                elif not ok:
                    failed.append(tk)
                recent = (recent + [not ok])[-THROTTLE_WINDOW:]
                if len(recent) == THROTTLE_WINDOW and sum(recent) >= THROTTLE_WINDOW // 2                         and time.monotonic() >= state['cool_until']:
                    state['cool_until'] = time.monotonic() + COOL_DOWN_S
                    self.status['cooling'] = self.status.get('cooling', 0) + 1
                    recent = []
        return failed

    def build(self) -> Optional[dict]:
        with self._lock:
            if self.status['building']:
                return None
            self.status = {'building': True, 'done': 0, 'total': 0,
                           'started_at': datetime.now(ET).isoformat(timespec='seconds'), 'error': None}
        try:
            universe = self._universe()
            self.status['total'] = len(universe)
            hits: dict = {}

            # Paced, not a burst. The data provider throttles an IP that asks too fast:
            # measured 2026-10-10, eight unpaced workers got ~800 names in and then
            # 8 of every 10 came back empty — and for minutes afterwards EVERY request
            # from the server did, which is what made the app look dead after a long
            # scan. So: few workers, a minimum gap between names, a shared cool-down
            # when the recent results turn empty, and slower passes over the misses.
            failed = self._pass(universe, WORKERS, PACE_S, hits, count=True)
            for pause, workers in RETRY_PASSES:
                if not failed:
                    break
                self.status['retrying'] = len(failed)
                time.sleep(pause)
                failed = self._pass(failed, workers, PACE_S * 2, hits)
            self.status['retrying'] = 0
            self.status['failed'] = len(failed)
            dates = [h.get('decided_on') for h in hits.values() if h.get('decided_on')]
            date = max(dates) if dates else last_session()
            prev_board = None
            for name in reversed(self._files()):
                b = self._load(name)
                if b and b.get('date') < date:
                    prev_board = b
                    break
            board = {
                'date': date,
                # the session this build stands for — a holiday's bars never advance
                # `date`, so staleness is judged on this, not on the data
                'built_for': last_session(),
                'built_at': datetime.now(ET).isoformat(timespec='seconds'),
                'prev_date': (prev_board or {}).get('date'),
                'scanned': len(universe),
                'failed': len(failed),
                'hits': hits,
                'changes': compute_changes(hits, (prev_board or {}).get('hits') or {}) if prev_board else [],
                'extended': {},
            }
            self._save(board)
            self._latest = board
            return board
        except Exception as e:                     # keep the last good board on a failure
            self.status['error'] = repr(e)[:200]
            self._last_fail = time.monotonic()
            return None
        finally:
            self.status['building'] = False

    def premarket_refresh(self) -> None:
        b = self._latest
        if not b or not self._quote:
            return
        names = [h['ticker'] for h in radar_rows(b['hits'])] + [c['ticker'] for c in b.get('changes') or []]
        ext = {}
        for tk in dict.fromkeys(names):
            try:
                q = self._quote(tk)
            except Exception:
                q = None
            if q and q.get('pre_price'):
                ext[tk] = {'price': q['pre_price'], 'change_pct': q.get('pre_change_pct')}
        b['extended'] = ext
        b['extended_at'] = datetime.now(ET).isoformat(timespec='seconds')
        self._save(b)

    # ── schedule ───────────────────────────────────────────────────────────────
    def start(self) -> None:
        threading.Thread(target=self._loop, name='board-scheduler', daemon=True).start()

    def _loop(self) -> None:
        while True:
            try:
                now = datetime.now(ET)
                b = self._latest
                stale = (not b) or (b.get('built_for') or b.get('date', '')) < last_session(now)
                if stale and time.monotonic() - self._last_fail > 900:
                    if self.build() is None and not self.status.get('building'):
                        self._last_fail = time.monotonic()
                elif (now.weekday() < 5 and PREMARKET[0] <= (now.hour, now.minute) <= PREMARKET[1]
                      and b and (b.get('extended_at') or '')[:10] != now.date().isoformat()):
                    self.premarket_refresh()
            except Exception:
                pass
            time.sleep(60)
