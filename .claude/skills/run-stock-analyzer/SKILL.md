---
name: run-stock-analyzer
description: Build, launch, drive, screenshot and smoke-test the Stock Analyzer (FastAPI backend + Angular chart client). Use when asked to run/start the app or API, analyze a ticker, check the Micha verdict/grade for a symbol, screenshot the UI, or verify a backend change end-to-end.
---

# Run the Stock Analyzer

FastAPI backend (`backend/`, port 10000) that computes the technical analysis and the
"Micha" verdict, plus an Angular 14 + lightweight-charts client (`frontend/`, port
6000) that renders it. The client hardcodes `http://localhost:10000`.

**Drive it with `.claude/skills/run-stock-analyzer/driver.py`** — four subcommands
covering the layers changes actually touch. All paths below are relative to the repo
root (`d:\pythonProject7`); all commands were run on Windows via the Bash tool
(Git Bash).

Use the venv interpreter explicitly — `./venv/Scripts/python.exe`. The venv is not
activated in a fresh shell and the system `python` is not it.

## The agent path: driver.py

Most backend work needs **no server and no browser**. `analyze` and `check` import
`StockAnalyzer` directly:

```bash
# full human-readable read-out for specific tickers
./venv/Scripts/python.exe .claude/skills/run-stock-analyzer/driver.py analyze PM NVDA

# assert payload shape + verdict self-consistency; exits non-zero on failure
./venv/Scripts/python.exe .claude/skills/run-stock-analyzer/driver.py check NVDA PM ARM OPEN GOOGL
```

`check` is the smoke test. It verifies the payload is JSON-serializable, that every
key the Angular client reads is present, and that the verdict story holds together —
`action=enter` must come from an entry state and must have a `now` option; every
stop must sit below its entry; a graded D/F "enter" must carry a cap explaining it.
Its output is one line per ticker:

```
  NVDA   at_trigger       wait_trigger  B 80.0
  PM     needs_buyers     wait_buyers   C 58.0
  ARM    breakout_now     enter         B 79.0
  OPEN   nothing_yet      watch         F 23.0
  GOOGL  broken           out           D 50.0

PASS: 5 tickers, payload + consistency checks clean
```

Each ticker costs one yahooquery download (~2-10 s, TTL-cached 300 s in-process).

### Smoke the HTTP layer

Start the server (background it — it runs until killed):

```bash
./venv/Scripts/python.exe main.py
```

Then, in another shell:

```bash
./venv/Scripts/python.exe .claude/skills/run-stock-analyzer/driver.py api --port 10000 --scan 3 NVDA
```

Verified output:

```
  health   ok
  tickers  517 symbols
  analyze  NVDA: 504 bars, at_trigger/wait_trigger, grade B
  micha    NVDA: $208.76 B
  scan     matched 3/3

PASS: all endpoints responded
```

### Find names close to becoming relevant

`alert` is separate from the grade: a correct D can still sit a fraction of a daily
range from the price that would make it a setup. To sweep for those across the
universe (nearest trigger first):

```bash
curl -s "http://localhost:10000/api/scan?limit=25&workers=8&alerting=true&sort=alert"
```

Verified — 18 of the first 25 Dow names were within two daily ranges of a trigger:

```
  SHW    $328.37   broken       F 39   imminent 0.22ATR / 0.7%  -> 330.62 (resistance)
  HD     $341.78   broken       F 39   imminent 0.29ATR / 0.8%  -> 344.47 (the 150MA)
  AMZN   $233.32   at_trigger   B 77   imminent 0.43ATR / 1.3%  -> 236.37 (the 150MA)
```

`sort` accepts `setups` (default), `alert`, `grade`.

### Screenshot the UI

Build, serve the build statically, screenshot with headless Edge:

```bash
cd frontend && npx ng build && cd ..
cd frontend/dist/stock-analyzer && "d:/pythonProject7/venv/Scripts/python.exe" -m http.server 8123
# ...in another shell, with the API also running on 10000:
./venv/Scripts/python.exe .claude/skills/run-stock-analyzer/driver.py shot --out shot.png
```

Then **actually Read the PNG.** A blank page or an error page still writes a valid
131 KB file. A correct shot shows: candles zoomed to a RECENT window (not the full
2-year history — see Gotchas), the 150MA (blue) and 200MA (purple), a top-left
on-chart legend (color swatch + current value — the SMAs plus Entry and Stop),
white horizontal S/R lines (only well-tested ones carry a price-axis tag), blue
dashed entry / red solid stop / green dotted target lines drawn WITHOUT axis labels,
and on the right the RTL Hebrew panel — grade badge, the call, the entry-option
cards with per-option stops, the target ladder, the three grade bars
(מבנה / טריגר / סיכון), and the ✅/✕ list.

The price axis should NOT show a stack of overlapping `Target`/`Break`/`Stop`/`T2`
boxes — if it does, the plan lines have regained their default `axisLabelVisible`.

On a phone-width shot (`--size 390,844`), the chart must still get real vertical
space — the panel below it caps itself and scrolls internally rather than pushing
the chart down to a sliver (see Gotchas). On mobile specifically:
  - there is NO separate `<header>` row for ticker/sector/price/badge/ATR — it
    floats on the chart itself (top-left, semi-transparent) as
    `ChartComponent.chart-info`, reading the same `analysis.meta` the desktop
    header does;
  - the topbar has only search + Analyze — the Micha-mode switch moved down into
    the indicator-checkbox row (`.mode-tgl`, first chip, bold/bordered) so it
    doesn't cost its own row;
  - the indicator checkboxes sit in ONE horizontally-scrollable line
    (`overflow-x:auto`), not wrapped to two rows;
  - the peek (always visible, above the expand button) shows ONLY the grade, the
    call-line, and the "מתקרבת להכרעה" alert band when one applies — the
    chart-context repeat, the entry-option cards, and the condition/expected-gain
    rows are all one tap away behind the SAME existing expand button, not new UI;
  - Markers defaults OFF everywhere (not just mobile) — a deliberate default
    change, not a state that needs restoring.

To cross-check the panel against the chart, compare the **red value in the price
axis** (e.g. `29.70`) with the panel's `סטופ`, not the position of the `Stop` tag.
Overlapping price lines crowd their axis tags, so the tag can render beside a
neighbouring number while its line is correct — that is a rendering artifact, not a
data bug. The price-scale range also varies slightly between runs (autoscale settles
differently under virtual time), so two screenshots of the same state are not
byte-identical.

## Build

```bash
./venv/Scripts/python.exe -m pip install -r backend/requirements.txt   # exit 0
cd frontend && npm install                                             # exit 0
cd frontend && npx ng build                                            # ~50 s
```

`npm install` reports audit warnings on Angular 14 — expected, not a failure.

## Human path

```bash
./venv/Scripts/python.exe main.py     # API on http://localhost:10000, docs at /docs
cd frontend && npm start              # ng serve on http://localhost:6000
```

Useless for an agent: `npm start` blocks forever and serves a page nothing can click.
Prefer `ng build` + `http.server` + `driver.py shot`.

## Gotchas

- **`ng serve` uses port 6000, which Chromium/Edge refuse to load** (`ERR_UNSAFE_PORT`
  — 6000 is X11). Headless screenshots of `localhost:6000` fail. Serve the built
  `dist/` on another port (8123 above) instead. This is why `shot` defaults to 8123.
- **The static server locks `dist/` and breaks the next build** with
  `EBUSY: resource busy or locked, rmdir '\\?\D:\...\dist\stock-analyzer'`. Stop the
  `http.server` before `ng build`, then restart it.
- **The app has three routes now** (`/` = analyzer, `/radar` = the alert-proximity
  scan page, `/portfolio` = the guided portfolio-builder wizard,
  `AppModule`'s `RouterModule.forRoot`). Plain `python -m http.server`
  has no SPA fallback, so hitting `/radar` or `/portfolio` directly 404s even
  though they work fine when reached by clicking the nav link from `/`. To
  screenshot them directly, serve `dist/` with a tiny SPA-fallback server instead
  (rewrite any path without a matching file to `index.html`). The scratchpad is
  session-scoped and does not persist between conversations, so this needs
  rewriting each time — it's short enough to inline here rather than hunt for a
  prior session's copy:
  ```python
  # spa_server.py <dist-dir> <port>
  import http.server, os, sys
  root, port = os.path.abspath(sys.argv[1]), int(sys.argv[2])
  class Handler(http.server.SimpleHTTPRequestHandler):
      def __init__(self, *a, **kw): super().__init__(*a, directory=root, **kw)
      def do_GET(self):
          if not os.path.isfile(self.translate_path(self.path.split('?')[0])):
              self.path = '/index.html'
          return super().do_GET()
      def log_message(self, *a): pass
  http.server.ThreadingHTTPServer(('0.0.0.0', port), Handler).serve_forever()
  ```
- **`driver.py shot`'s `--virtual-time-budget` can capture a page mid-layout on
  pages with several conditional sections (Radar's control rows, Portfolio's
  summary bar).** A shot taken this way can show text clipped at the viewport
  edge that isn't actually clipped — reloading the identical URL with a real
  browser automation tool (networkidle wait + a few seconds settle time) shows
  the correct, non-overflowing layout. Before treating a `driver.py shot` as
  proof of a layout bug, check `document.body.scrollWidth` vs `window.innerWidth`
  (e.g. via a throwaway puppeteer-core/playwright script — neither is a project
  dependency, install with `--no-save` and remove it after) — if they're equal,
  the shot's a paint-timing artifact, not a real overflow.
- **Bidi corruption in Hebrew+number spans**: a plain text node mixing Hebrew
  words with several separate interpolated numbers, under an ancestor with no
  explicit `dir`/`direction` (the norm on this app — see the flex invisible-text
  bug below), lets the browser's bidi algorithm reorder the numbers and even
  visibly reverse-render short Hebrew words. Fix: `dir="rtl"` directly on that
  specific plain (non-flex, text-only) leaf span — safe because the documented
  invisible-text bug is about flex containers distributing space among multiple
  *element* children, not about bidi resolution within one text node. Applied to
  `.rd-gain-txt`/`.rd-risk-txt` (Radar), `.pf-gain-txt`/`.pf-risk-txt`
  (Portfolio), `.ifbreak-txt`/`.opt-exp` (Analyzer). At small pixel sizes,
  correctly-rendered Hebrew letters (e.g. ס ט ו פ) can look like mirrored Latin
  glyphs ("9IUD") under heavy zoom — compare pixel-for-pixel against a
  known-good instance of the same word elsewhere on the page before concluding
  it's actually reversed.
- **Two `http.server` processes can silently double-bind the same port on
  Windows.** If a previous static server wasn't actually killed (e.g. the
  `Get-NetTCPConnection | Stop-Process` pipeline ran before the process registered,
  or matched nothing and silently no-opped) and a new one starts on the same port,
  Windows lets both listen and routes new connections to either one
  nondeterministically — `curl` to the same URL flips between the old and new
  build across requests. Symptom: a rebuilt page intermittently serves stale
  content/404s that make no sense given the current `dist/`. Verify with
  `netstat -ano | findstr :8123 | findstr LISTENING` — if it prints more than one
  PID, kill all of them by PID and start exactly one fresh server, then re-`curl`
  to confirm a single consistent response before screenshotting.
- **Killing the shell does not kill uvicorn.** Stopping the backgrounded `main.py`
  leaves the Python child holding port 10000, so the next launch dies with
  `[Errno 10048] only one usage of each socket address ... is normally permitted` —
  and any request you make meanwhile is silently answered by the *old* code, which
  looks like your change did nothing. Kill by port:
  ```powershell
  Get-NetTCPConnection -LocalPort 10000 -State Listen |
    Select-Object -ExpandProperty OwningProcess | Sort-Object -Unique |
    ForEach-Object { Stop-Process -Id $_ -Force }
  ```
- **The server can take ~20 s to bind** (it imports pandas/scipy/yahooquery first).
  `curl` exiting 7 right after launch means "not up yet", not "failed" — poll
  `/api/health` instead of sleeping a fixed 10 s.
- **Git Bash `/tmp` is invisible to the Windows Python.** `curl -o /tmp/x.json`
  followed by `python -c "open('/tmp/x.json')"` fails with `FileNotFoundError`. Write
  to a real Windows-visible path.
- **The console mangles the Hebrew/em-dashes** in the payload (cp1255). The JSON
  itself is fine — `driver.py` writes UTF-8 bytes straight to `stdout.buffer` to avoid
  a `UnicodeEncodeError` truncating output mid-run. If you write your own script,
  print to a file with `encoding='utf-8'` and Read it rather than piping to the shell.
- **`backend/` is a namespace package with no `__init__.py`.** Submodules import each
  other by bare name (`from config import ...`), which only works because `api.py` and
  `main.py` push `backend/` onto `sys.path`. `driver.py` does the same. Importing
  `backend.micha` directly from elsewhere will fail on `from config import ...`.
- **`ticker_finder.py` at the repo root must stay unchanged** — a standing constraint
  from the owner.
- **`resistance_breakout_indicator.py` and `sma150_indicator.py` are dead prototypes**,
  not imported by the app. Don't wire them in.
- **First `/api/tickers` call hits pytickersymbols** and is cached for the process
  (`lru_cache`); 517 symbols.
- **Analyze is ~100% network-bound** — compute is only ~40 ms per ticker; everything
  else is Yahoo. If you are optimising, profile the network, not the algorithms.
- **Constructing a `yahooquery.Ticker` costs ~3 s** (cookie/crumb handshake), so
  `MarketData` builds ONE per symbol and reuses it for all four calls, and every
  `Ticker` after the first borrows the first one's session. Do not "simplify" this
  back to `yq.Ticker(sym).price` per call — that was 4 handshakes per analyze and it
  is where a 17-35 s analyze came from.
- **The shared session must be yahooquery's own** (`first_ticker.session`). Passing a
  plain `requests.Session` looks fine — construction succeeds and `.price` returns
  data — but silently breaks `history()` with `KeyError: '<SYMBOL>'` deep inside
  `_historical_data_to_dataframe`, so `analyze()` returns `None` for every symbol.
- **`Ticker` construction is deliberately serialised behind a lock.** Letting the
  scan's 8 workers construct concurrently measured almost 4× SLOWER end to end
  (12 symbols: ~10.5 s locked vs 43.9 s unlocked) — Yahoo throttles a burst of
  parallel handshakes and the retries cost more than the serialisation saves.
- **`get_modules("price assetProfile calendarEvents")` is NOT reliable** on
  yahooquery 2.4.1 — it intermittently returns `{symbol: None}` while the individual
  `.price` / `.calendar_events` / `.asset_profile` accessors work. It would collapse
  3 requests into 1, so it is tempting; it was tested and rejected.
- **Yahoo throttles hard and intermittently.** Response times swing from 0.2 s to
  17 s for the same call, and a burst of profiling can make every request return
  `None` for minutes. Never conclude "the data is gone" from one bad run, and never
  benchmark A vs B with a single sample.
- **No test suite exists.** `driver.py check` is the closest thing; use it as the
  regression gate after backend changes. It asserts the *story*, not just the schema:
  every reason must be bilingual, and the letter may not contradict the headline
  (`nothing_yet` / `broken` / `avoid` can never grade A or B).
- **To prove a refactor changed nothing, freeze the inputs.** Live prices move
  between runs, so re-running `analyze` before/after always "differs". Pickle the raw
  OHLCV + fundamentals, stub `StockAnalyzer.data` with an object exposing the same
  surface (`fetch`/`market_cap`/`earnings_days`/`profile`/`benchmark`/`prime`/
  `add_indicators`), and diff the JSON — that is deterministic and network-free. Note
  it deliberately bypasses `MarketData`, so it proves the ANALYSIS pipeline is intact
  but says nothing about the fetch layer; verify that separately against live data.
- **Analysis is live, so two runs minutes apart legitimately differ.** A ticker can
  move state and grade between runs — that is the data, not a regression. Compare
  behaviour on the same payload, not across fetches.
- **`SPY` is fetched as the relative-strength benchmark** on every analyze (TTL-cached,
  so a scan pays once). Analyzing `SPY` itself skips it — `ctx.bench` is then `None`
  and the "Vs the market" group is absent by design.
- **The chart used to default to the FULL 2-year history** — 500 candles crammed into
  one screen made the recent action a few-pixel sliver, which read as "the chart is
  broken", not "zoom in". It now opens on a recent window sized from the container's
  pixel width (`TARGET_BAR_PX`/`MIN_VISIBLE_BARS`/`MAX_VISIBLE_BARS` in
  `chart.component.ts`) — a phone gets fewer, wider candles instead of the same count
  squeezed thin. This reset fires ONLY on an actual ticker change (`isNewSeries`,
  tracked via `lastTicker`): every toggle checkbox triggers a full re-render via
  `ngOnChanges`, and re-zooming on every one of those used to silently discard
  whatever the user had just zoomed or panned to — the other half of "weird".
- **A `SeriesMarker`'s text can overflow the canvas edge** on a narrow viewport when
  its bar lands close to "today" — invisible on desktop, reproducible on a
  `--size 390,844` shot. `rightOffset` does NOT fix a marker several bars before the
  very last one (the extra margin only applies past the *last* bar). The actual fix:
  keep marker text short or empty and rely on color + shape, the way TradingView's
  own markers work — see the MA-bounce marker in `setups.py` (`'text': ''`).
- **Horizontal S/R lines are WHITE** (`LEVEL_COLOR_STRONG`/`_WEAK` in
  `chart.component.ts`), strength shown via opacity + line style. Role-colouring them
  (support=teal / resistance=red) was tried and explicitly reverted by the owner —
  a level is price memory, not a directional call: the same line is a ceiling on the
  way up and a floor on the way back down, so red/teal there overstated it and
  competed with the same hues used for bullish/bearish everywhere else. Only
  `strength:'strong'` levels (or the rare `type:'breakout'` marker) get a price-axis
  tag; weak levels still draw, just without another box on the axis.
- **The Micha plan lines (entry/stop/targets) carry NO price-axis label by default.**
  Entry, Stop and up to three target stations sit in one narrow price band, so
  labelling them all stacked five boxes on the axis — and when two land on the same
  price (a breakout level that is also target 1) they overlapped into a smear. Their
  numbers live in the corner legend (entry/stop) and the side panel (full ladder);
  the axis label appears only for the line the panel is currently pointing at.
- **Panel ⇄ chart highlighting**: hovering (or tapping, for touch) an option card or
  a target row sets `chartHighlight`, which `chart.component.ts` reads via an
  `@Input()` and applies with `applyPlanEmphasis()` — `IPriceLine.applyOptions()` on
  the stored `planLines`, NOT a full re-render (`ngOnChanges` short-circuits when
  `highlight` is the only changed key, so a mouse move doesn't rebuild every series).
  `app.component.ts` mirrors the chart's action→option map in `drawnOptionByAction`
  so hovering a card the chart never drew doesn't pretend to highlight anything.
- **The on-chart SMA legend is hidden entirely on mobile** (not shrunk) — it costs
  candle width for info the panel already states in words. Don't re-add a smaller
  version; drop it.
- **A flex item with `overflow-y:auto` needs `min-height:0`, or its default
  `min-height:auto` wins.** `.workspace.with-panel .micha` (the mobile panel) had
  `max-height` + `overflow-y:auto` but no `min-height:0`; inside a column flex
  container that ALSO has `overflow:hidden` (`.workspace`), that let `.micha` try to
  render at its full unconstrained content height, and the excess got clipped by the
  PARENT's `overflow:hidden` instead of ever becoming reachable through `.micha`'s
  own scrollbar. Symptom: "scrolling doesn't reach the end of the analysis." A
  general flexbox trap, not specific to this app — recognise it anywhere a
  scrollable flex item's content silently gets cut off short.
- **`fixRightEdge:true` blocks panning past the default view entirely** — no drag,
  no rubber-band, a hard wall exactly at `rightOffset`. TradingView allows real
  panning past its default margin (into blank space — that's the point, it's what
  makes a chart feel alive rather than static). `fixRightEdge:false` restores that;
  `rightOffset` still controls the INITIAL view on a ticker switch, it just stops
  being the scroll ceiling too.
- **There is no separate `<header>` row on mobile.** Ticker/sector/price/badge/ATR
  float on the chart itself as `ChartComponent`'s `.chart-info` block (top-left,
  semi-transparent, reads the same `analysis.meta` the desktop header does) —
  `app.component.css` hides `.title` at ≤768px to give that row's height back to
  the chart. The Micha-mode switch is similarly duplicated: the topbar's own
  checkbox for desktop, plus a `.mode-tgl` chip inside `.header .toggles` for
  mobile (first item, bold/bordered), both bound to the same
  `[(ngModel)]="michaMode"` so they stay in sync automatically. CSS shows/hides
  each per breakpoint rather than relocating one DOM element between containers —
  cheaper than fighting `position:absolute` containing-block requirements across
  what are otherwise sibling elements.
- **The mobile peek shows ONLY the grade, the call-line, and the "מתקרבת להכרעה"
  alert band** — read-line, the full entry-option cards, and the condition/expected-
  gain rows (`.ep-row.hold`/`.ep-row.growth`) all moved behind the SAME existing
  expand button (`.decision .read-line`/`.opts`/`.ep-row.hold`/`.ep-row.growth`
  hidden by default, `display:block`/`flex` under `.micha.expanded`). Desktop is
  untouched — every one of these rules lives inside the `@media (max-width:768px)`
  block.
- **Markers default OFF everywhere** (`toggles`/`michaToggles` in `app.component.ts`,
  and the per-ticker resync in `syncMichaToggles()`) — a deliberate default change
  on both desktop and mobile, not something to "fix" back to `true`.
- **ATR is a unit of DISTANCE, never of TIME.** `_growth` used to compute
  `days = gain% / ATR%`, i.e. one full average daily range of NET progress every
  day, and printed "ONDS +20% ≈ 2.4 days" and "MSTR +30% ≈ 4.2 days, fast" under a
  headline of "get out". Measured (69 tickers × 5y, every bar above the SMA150,
  first touch within a 120-day horizon): a k-ATR move takes ~**6-7× longer** than
  that through the tradeable range, and lands far less than always —
  k=2 → 12d/83%, k=4 → 28d/68%, k=8 → 52d/42%, k=16 → 78d/17%. The curve is close
  to the random-walk `days ≈ 2k²` up to k≈4, then bends under survivorship (past
  k≈8 only the fast movers arrive inside the horizon), which is exactly why
  `hit_rate` must be printed beside `days` and never dropped. Live in
  `config.time_to_target()`. The same trap was already known for the alert and
  guarded there by `ALERT_MAX_PCT` — `_growth` simply never got the memo. If you
  re-derive the table, re-run the study; do not hand-tune the knots.
- **The grade's `time` term is an adjustment inside `risk`, not a fourth axis.**
  `grade_breakdown.components` carries it with `adjustment: true` and a signed
  `got` — summing all four components double-counts it. Bounded to ±4/100, banded
  on the MEASURED quantiles of days-to-thesis across the universe (p25 14d / p50
  25d / p90 56d) so it pivots at typical rather than handing out a free bonus.
  Two guards, both of which were added only after measuring what happened without
  them: it is skipped entirely for `broken`/`avoid`/`nothing_yet` (without that it
  lifted META/ADP/ZS out of F — the MSTR trap again, rewarding a close target on a
  setup that is over), and the POSITIVE side is suppressed when `risk_reward < 1`
  (without that it paid AMD +4 for a thesis 0.5 ATR overhead, where "fast" means
  "no room left", not "good"). Penalties stay unconditional. Blast radius on 197
  names: 5% of letters move, all downgrades of genuinely slow theses (CSCO 68d,
  DXCM 82d), A-count 24→19. **It deliberately does NOT reward raw ATR** — high ATR
  earns more %/day and risks more %/trade, which cancels risk-adjusted; what is
  paid for is distance-to-thesis in ATR, and `corr(days, ATR%) = -0.34` on the
  sample confirms that is related to but not a proxy for volatility.
- **The two-sentence "why this grade" is composed from the grade's OWN arithmetic,
  not from `reasons.py`.** Every scoring decision in `verdict._grade` files a short
  bilingual clause via `note(axis, w, en, he)`, and `_grade_sentence` composes them:
  sentence 1 = what carries the letter (top clauses, ordered setup → trigger → risk,
  which is the running order of his own A-grade sentence), sentence 2 = the single
  thing holding it back, or his literal "מה עוד נותר לבקש" when nothing does. `w` is
  the points a term EARNED, or for a miss the negative of what it forfeited. Two
  rules make it read correctly and both were added after seeing the output without
  them: a cap that actually **bound** (`caps[].bound`, i.e. it moved the letter, not
  merely applied) always leads and inverts the order to problem-first — otherwise a
  broken F opened with three nice things and buried "the setup is over" at the end,
  reading as an endorsement; and sorting purely by weight opened charts with the
  punchline ("the trigger is happening right now") before naming the chart it
  happened on. Sourcing these sentences from `reasons.py` instead would be a SECOND
  opinion, free to contradict the letter — the same reason `_why` calls `_near_ma`
  rather than re-deriving the test. Surfaced as `micha.grade_why(_he)` and on
  `grade_if_break.why(_he)`; **the client renders Hebrew only.**
- **Text may never claim a line the chart does not draw** — use
  `verdict.drawn_line(overlays, kind)`. Two different things get called "rising
  lows": `Signals.trend` is a polyfit slope through 2y of swing pivots, and the
  direction-change stage falls back to a weekly-lows reading — both real signals,
  neither a drawn object. The chart's line is a strict pivot-snapped segment hidden
  unless price is testing it, so they disagree constantly: measured, **7 of 18**
  names asserted "rising highs and lows / the rising-lows line is holding" over a
  chart with no such line before this was enforced. Sentences about the slope are
  fine, they just may not use the word "line". `driver.py check` now fails the build
  on any violation, so this cannot regress silently.
- **`_trigger` has cup-rim and base-top candidates** (`kind: 'cup_rim' | 'base'`,
  `CUP_RIM_DEPTH_ATR` / `CUP_RIM_NEAR_ATR`). He names these prices as the breakout —
  "קאם אנד הנדל, פריצה פוטנציאלית מעל 177.5" (MMM), "פריצה אחרי מחיר $34" (GTLB) —
  but a cup rim is a SINGLE pivot, so `MIN_LEVEL_TOUCHES=2` means it can never become
  a level and the trigger used to fall through to the all-time high. Gated on the
  shape (a real decline behind the rim, and price back near it) or every ordinary
  pullback high qualifies. Neither kind carries a `wall` — no touch history to
  report, and fabricating one is exactly what the level-backed candidates avoid.
  Measured A/B on identical data across 30 names: 3 use it, **1 score moved, 0
  letters changed**, F/TEAM/CSCO/CRWD/PANW all untouched.
- **To A/B a scoring change, patch the function and analyse twice IN ONE PROCESS.**
  Prices move between runs, so a before/after across two processes always "differs"
  for reasons unrelated to the change; back-to-back passes share the TTL-cached
  OHLCV, so every reported difference is caused by the edit. Gotcha in the harness
  itself: `Judgement._cup_rim` unwraps to a plain function on attribute access, so
  restoring it needs `staticmethod(...)` or `self` starts arriving as the first
  argument and every ticker raises `TypeError`.
- **Restart the API after ANY backend edit before trusting a screenshot.** The
  frontend renders whatever the process on 10000 serves, and that process holds the
  code it started with. A stale server made the new expected-gain row render with
  blank numbers (the pipes got `undefined` for fields the old payload lacked) while
  `driver.py analyze`, which imports `StockAnalyzer` directly, showed them correctly
  the whole time — the two disagreeing that way is the signature of this, not a
  frontend bug. Kill by port (see above) and wait for `/api/health`.
- **This headless Edge/Chrome build (both, confirmed) has a genuine rendering bug
  where a flex-wrap child sized with a PERCENTAGE width makes a descendant's own
  text invisible** — reproducible with zero Angular involved, in plain static
  HTML, on a `.rd-grid{display:flex;flex-wrap:wrap}` > `.rd-card-wrap` (the flex
  item) > `.rd-card` (the actual card) structure on the Radar page. `width:100%`
  (or `calc(100% - Npx)`, or a `vw`-based width) on `.rd-card-wrap` breaks it at
  narrow (~300-400px) viewport widths specifically — narrower (230px) or wider
  (450px+) both render fine, and CRUCIALLY a literal pixel width that resolves to
  the exact same on-screen size as the broken percentage (e.g. `width:362px`
  instead of `width:100%` of a 362px container) renders perfectly. The fix in
  `radar-page.component.css`'s mobile block is `.rd-card-wrap { width: 320px; }`
  (a literal px value, chosen to fit inside the phone-width-safe 230–362px range
  proven by a bisection sweep) — never reach for `%`/`vw`/`calc()` involving `%`
  on that element again. This is unrelated to, and was found only after fixing, a
  SEPARATE bug: a `dir="rtl"` set on any ancestor (however distant) of a flex row
  using `justify-content` values other than `flex-end` makes that row's own short
  text invisible too, regardless of the row's own `direction`. Both bugs were
  reproduced with hand-written static HTML (no Angular) to rule out app-specific
  causes — see the (deleted, but reconstructable from this description)
  `isolate*.html`/`test*.html`/`width_*.html` sweep this was diagnosed with. The
  fix for the second bug is why `radar-page.component.html`'s `.layout` has no
  `dir="rtl"` at all — every row-direction flex container instead uses
  `flex-direction: row-reverse` (or, for the once-per-card `.rd-card-top` /
  `.rd-card-trigger` / `.rd-card-foot` rows specifically, plain `row` with the DOM
  order manually reversed — row-reverse repeated once per card was ITS OWN third
  variant of the same underlying bug class at scale) with `text-align: right` on
  `.main` for the Hebrew alignment `dir="rtl"` used to provide for free. A THIRD
  variant: `display: grid` as an ancestor of the card also made its text
  invisible — this is why `.rd-grid` is `display:flex;flex-wrap:wrap` and not CSS
  Grid, even though Grid would be the more natural fit for an auto-filling card
  layout. **If a future change to this page reintroduces `dir="rtl"` on a
  container, CSS Grid, or a percentage/vw width on a flex-wrap item, screenshot
  every viewport from 350–500px in ~30px steps before trusting it** — the bug is
  invisible at some widths and not others, so a single screenshot at 390px or at
  1600px will not by itself prove a change is safe.
- **`GET /api/scan?...&stream=true` is a live server-sent-events feed** — one
  `data: {hit}\n\n` per ticker as `ThreadPoolExecutor`'s `as_completed()` yields it,
  closed by `data: {"done":true,"scanned":N,"matched":M}\n\n`. Default `stream=false`
  is byte-identical to before; this is purely additive. Built for Radar's live
  leaderboard and the Portfolio wizard's candidate search — both use
  `ApiService.scanStream()`, which wraps a native `EventSource` in an RxJS
  `Observable` and completes itself on the `done` frame (`EventSource` auto-
  reconnects on a dropped connection by default, and a naturally-ended stream looks
  identical to a dropped one from its perspective — closing first is what stops it
  from silently re-opening the whole scan in a loop).
- **`api.py`'s `work(tk)` closure must stay guarded end-to-end, not just around
  `analyzer.analyze()`.** It used to be `try: r = analyzer.analyze(tk) / except:
  return None`, leaving the POST-processing (dict lookups, `Judgement._best_option`)
  unguarded. On the blocking endpoint that was merely a clean 500 on the rare
  ticker whose shape trips something; on the streaming endpoint it silently killed
  the whole generator mid-flight and the client lost every result already shown.
  Found via an actual `limit=517` end-to-end run, not by inspection — the failure
  looked identical to a network error (`EventSource.onerror` fires on any non-2xx
  or dropped connection) until traced. Now the entire body is inside one
  `try/except Exception: return None`, and both the streaming and blocking
  `as_completed()` loops also guard `fut.result()` itself as belt-and-suspenders.
- **`/api/scan`'s `limit` ceiling must stay ABOVE the true universe size.** It was
  `le=500` while the frontend's own "scan everything" chip requests 517 (the real
  Dow+Nasdaq100+S&P500 union) — `_universe()[:limit]` already self-clamps to
  whatever the real size is, so the ceiling was purely an unenforced safety bound
  that happened to sit below a value the UI itself offers. The client-side symptom
  (an instant, connection-flavored error with no HTTP detail visible) is identical
  to the guard-gap above — don't assume one when the other is just as likely; check
  the actual response status first. Now `le=600`.
- **`EventSource`'s `onmessage`/`onerror` callbacks are not reliably picked up by
  zone.js's default browser patches** the way `setTimeout`/`XHR`/`fetch` are. The
  callback still runs and still mutates component state — a `console.log` inside it
  fires exactly on schedule — but OUTSIDE Angular's zone, so no change-detection
  pass ever follows, and the view silently stops updating. This was invisible on
  the Radar page purely by luck: its 1-second `setInterval` clock (zone-patched)
  was triggering an unrelated CD pass roughly once a second anyway, which
  incidentally picked up whatever `scanStream()` had already written to component
  fields in between. It was NOT invisible on the Portfolio wizard's review step,
  which has no such timer — confirmed by a live console trace showing `next()`
  firing 25 times while "0 found so far" never moved once in the DOM. Fix (in
  `ApiService.scanStream()`): inject `NgZone` and wrap every `subscriber.next/
  error/complete()` call in `this.zone.run(() => ...)`. Do this in the SERVICE, not
  per-caller — relying on a page happening to have an unrelated timer nearby is not
  a fix, it's an accident that stops being true the moment that timer is refactored.
- **A literal object passed as `*ngTemplateOutlet`'s `context` (`context: { list:
  X }`) is a NEW reference every change-detection cycle, and `NgTemplateOutlet`
  tears down and rebuilds its ENTIRE embedded view whenever that reference
  changes** — regardless of whether `X` itself is stable. On Radar this meant the
  whole card grid was being destroyed and recreated about once a second (driven by
  the same clock timer from the gotcha above), which is invisible to a static
  screenshot but fatal to hover: a card being replaced out from under the cursor
  mid-hover means `mouseenter`'s handler keeps re-firing and its open-delay timer
  never survives long enough to complete. Found via a live trace showing dozens of
  re-fires per single hover. Fix: never build the context object inline in the
  template. Compute `enteringNowCtx = { list: this.enteringNow }` etc. as a
  component field, reassigned only when the underlying array is genuinely
  reassigned (`radar-page.component.ts`'s `refreshBuckets()`, `portfolio-page.
  component.ts`'s `refreshCtx()`) — including one level deeper for objects built
  inside a loop (`computeSectorGroups()` precomputes each group's own `ctx` field
  for the same reason `{ list: sg.rows }` inline would have the identical bug).
  Also added `trackBy` on the inner `*ngFor` as belt-and-suspenders. This is a
  general Angular trap, not specific to this app — watch for it anywhere
  `ngTemplateOutletContext` is built as an object literal directly in a template.
- **`ngOnChanges` fires BEFORE `ngOnInit`.** `StockQuicklookComponent` is always
  created with `[ticker]` already bound (`*ngIf="previewTicker"` in the parent, not
  set after creation), so its first `ngOnChanges` call fires before `ngOnInit` ever
  runs. A `Subject`-based pipeline subscribed to in `ngOnInit` misses that first
  emission entirely — plain `Subject`s don't replay past values to a late
  subscriber — and the component sits on its initial state forever. Symptom: `.ql-
  wrap` present in the DOM, but every conditional child (loading/error/content)
  rendered as an empty `*ngIf` anchor (`<!---->`), meaning the pipeline never fired
  at all. Fix: subscribe in the CONSTRUCTOR, which always runs before any lifecycle
  hook fires. General rule for any component whose `@Input` can already be
  non-null at creation time (as opposed to being set to a value only sometime
  after) — `ngOnInit` is too late for a Subject you feed from `ngOnChanges`.
- **To screenshot an interactive state `driver.py shot` can't reach** (a real mouse
  hover, a tap, or anything needing REAL wall-clock waiting rather than headless
  Chrome's `--virtual-time-budget`, which can sever a still-open `EventSource`
  connection right as the budget expires and produce a misleading error-state
  screenshot instead of the mid-stream frame being sought) — a small throwaway
  puppeteer-core script, installed with `--no-save` in an ISOLATED scratch
  directory (not `frontend/`, so nothing leaks into the project's own
  `node_modules`), pointed at the existing Edge install via `executablePath`
  (`C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe` — no Chromium
  download needed). The installed `puppeteer-core` version is ESM-only; give the
  script a `.mjs` extension and use `import`, not `require`. Use
  `ElementHandle.hover()`, not a manual multi-step `page.mouse.move()` — both
  eventually fire `mouseenter`, but `hover()` is the documented-reliable one.
- **A cold ~250-ticker candidate scan genuinely takes 60-100+ seconds**, not
  the 15-30s that feels like a reasonable test timeout — measured directly
  (`curl -N` to `/api/scan?limit=250&...&stream=true`, timed end-to-end: ~69s for
  88 matches). Give verification scripts real headroom (150-200s) rather than
  guessing short and mistaking Yahoo's inherent latency for a bug. Relatedly:
  running several such scans back-to-back against the same warm backend process
  (e.g. while iterating on a diagnostic script) measurably slows each subsequent
  one down — Yahoo's documented intermittent throttling compounds under
  concurrent/repeated load. Restart `main.py` fresh before trusting a timing
  number, and don't conclude a real bug from one slow run; re-test in isolation.

## Where the logic lives

- `backend/verdict.py` — the judgement layer: state machine, three-axis grade
  (setup / trigger / risk) plus a bounded ±4 `time` adjustment folded INTO the risk
  axis (see Gotchas), structural stop selection, entry options, the `alert`
  ("close to becoming relevant"), the two-sentence `grade_why` (see Gotchas), the
  write-up. Most "the grade is wrong" work happens here. `drawn_line()` lives here
  too and is imported by `reasons.py` — the guard that stops any text claiming a
  trendline the chart does not draw.
- `backend/reasons.py` — the argument behind the call: seven groups (trend / level /
  volume / pattern / strength / risk / timing), each item stanced `for` / `against` /
  `note`, bilingual, all measured off today's candles. "Why does it say that?" work
  happens here.
- `backend/micha.py` — signals only (Fib, 20MA stretch, trend, volume depth, buyers'
  candle, duration above the 150, relative strength vs SPY, direction-change
  sequence, target ladder). Computes facts, decides nothing. `_growth` is the
  expected-gain model — see the time-to-target Gotcha before touching it.
- `backend/config.py` — every threshold, and `time_to_target()`, the measured
  gain→(days, hit-rate) curve the expected gain and the grade's time term both read.
- `backend/levels.py`, `setups.py`, `geometry.py` — S/R, patterns, trendlines.
- `backend/market_data.py` — also sector/industry/logo (`profile()`, TTL-cached,
  best-effort — ETFs/indices have no `asset_profile`).
- `frontend/src/app/app.module.ts` — the Angular Router config. Three routes:
  `''` → `AnalyzerPageComponent`, `'radar'` → `RadarPageComponent`, `'portfolio'`
  → `PortfolioPageComponent`. `AppComponent` itself is just `<router-outlet>`.
  `StockQuicklookComponent` is also declared here (not routed — embedded by
  Radar/Portfolio).
  `analyzer-page.component.ts|html|css` — the ENTIRE original single-page app
  (chart + verdict panel), extracted verbatim from the old `app.component.*` when
  the Radar page was added; no behavioral change from before the split. The RTL
  verdict panel + header (ticker icon/logo, sector chip) live in the `.html|.css`.
- `backend/api.py`'s `scan()` — `stream: bool` branches between the original
  blocking response and the SSE generator (see Gotchas for both). `work(tk)` is
  the single source of truth for a hit's shape either way.
- `frontend/src/app/api.service.ts` — `scanStream()` is the `EventSource`→RxJS
  bridge every live-updating view is built on (see the NgZone Gotcha before
  touching it — this is the one place that fix belongs, not per-caller).
- `frontend/src/app/stock-quicklook.component.ts|html|css` — the shared "hover a
  card (desktop) / tap a card (mobile)" chart+verdict preview used by BOTH Radar
  and Portfolio, so navigating away to see a stock is now an explicit choice (the
  "→ ניתוח מלא" button, which does the actual `router.navigate`) rather than
  what every click does. `mode: 'popover'` (desktop, anchored + positioned from
  the hovered element's `getBoundingClientRect()`) vs `'sheet'` (mobile,
  `position:fixed` bottom sheet). Deliberately a TRIMMED verdict (grade, call,
  read, alert band, `grade_why_he`, best option) mirroring the main panel's own
  "peek" subset, not the full 15-section `.micha` aside — see the `ngOnChanges`-
  before-`ngOnInit` Gotcha before changing how `ticker` is consumed.
- `radar-page.component.ts|html|css` — the daily watchlist at `/radar`: a LIVE
  leaderboard fed by `scanStream()` (`enteringNow`/`ready` are refreshed fields,
  not getters — see the `ngTemplateOutlet` Gotcha before turning them back into
  getters), capped and re-sorted live by `displayCap`, grouped by sector. Mobile
  (`isMobileNow`, ≤768px) replaces the desktop grid entirely with sector TILES →
  tap → drill-down (`selectedBucketMobile`/`selectedSectorMobile`), gated by
  `*ngIf` (not CSS `display:none`) so the desktop grid markup isn't even in the
  DOM at phone widths. Hover/tap on any card opens `<app-stock-quicklook>` via a
  debounced-open/graced-close timer pair (`onCardEnter`/`onCardLeave`/
  `onQuicklookHover`). See the Gotchas above before touching any layout property
  here — this page has hit three variants of the headless invisible-text bug.
- `portfolio-page.component.ts|html|css` — the portfolio builder at `/portfolio`,
  a guided wizard (`wizardStep: 'holdings'|'risk'|'sectors'|'review'|'summary'`):
  risk preset → sector exclusions → ONE candidate at a time from a `scanStream()`
  pool (✓ accept / ✕ next, backed by `findNextCandidate()`'s diversity walk —
  `MAX_PER_SECTOR` respected against BOTH held and already-accepted sectors) →
  the summary (unchanged expectancy/risk math from before the wizard existed).
  Shares the exact quick-look/stable-context-object machinery with Radar
  (`holdingsCtx`/`suggestionsCtx`/`refreshCtx()`) — see the Gotchas above.
- `frontend/src/app/chart.component.ts` — candle/overlay rendering, the default-zoom
  logic, the on-chart legend, and the S/R color semantics (`LEVEL_COLORS`). Most
  "the chart looks wrong/cluttered" work happens here. Embedded both by the
  Analyzer page's main view and by `StockQuicklookComponent`'s popover/sheet —
  never two instances live on screen at once in practice (different routes vs. a
  transient overlay), so the multiple-instance question never actually arises.
- `frontend/src/app/models.ts` — must mirror the backend payload; `driver.py check`
  guards the keys but not their types.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `driver.py api` → `health FAILED` | Server isn't up, or still binding (~20 s). `./venv/Scripts/python.exe main.py` |
| `[Errno 10048] ... only one usage of each socket address` | An orphaned uvicorn owns 10000 — kill by port (see Gotchas) |
| Server restarted but responses look unchanged | Same thing: the old process is still answering |
| `EBUSY ... rmdir dist\stock-analyzer` | Stop the `http.server` holding `dist/`, rebuild |
| Screenshot is blank / 0 bytes | API not on 10000, or you pointed at port 6000 (unsafe port) |
| `FileNotFoundError` on a `/tmp` path | Git Bash `/tmp` ≠ Windows temp; use a real path |
| `analyze` → "no usable data" | Delisted symbol, or fewer than `MIN_BARS`=160 bars of history |
| `ModuleNotFoundError: config` | Something imported `backend.*` without `backend/` on `sys.path` |
| Panel `סטופ` ≠ red value in the price axis | Real bug — the option the chart picks and the one the panel shows have diverged (`chart.component.ts` action→option map must cover every `action`, or the lookup returns `undefined` and it silently draws `options[0]`) |
| `Stop`/`Target` tags look mispositioned | Axis-label crowding, not a bug — read the axis values |
