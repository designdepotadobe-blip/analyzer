# Stock Analyzer — TradingView-style pattern screener

A Python (FastAPI) backend that scans a stock universe and runs the full
technical-pattern spec, plus an Angular + [lightweight-charts](https://tradingview.github.io/lightweight-charts/)
frontend that renders each stock TradingView-style with all the analysis drawn on top.

```
d:\pythonProject7
├── backend
│   ├── analyzer.py      # pattern detection → JSON geometry primitives
│   ├── api.py           # FastAPI endpoints
│   └── requirements.txt
├── frontend             # Angular 14 + lightweight-charts client
│   └── src/app
│       ├── chart.component.ts   # renders candles + all overlays
│       ├── app.component.*      # layout, search, scan list, setup panel
│       ├── api.service.ts
│       └── models.ts
├── ticker_finder.py     # (unchanged) Dow/Nasdaq100/S&P500 universe
└── resistance_breakout_indicator.py  # (legacy matplotlib version, still runnable)
```

## Setups detected

Each stock is tested against every setup; **zero, one, or many** may apply.

| Code | Setup | Meaning |
|------|-------|---------|
| `above150_breakout` | Above 150MA · rising lows → breakout | Uptrend with higher-lows trendline pressing into resistance |
| `bearish_to_bullish` | Bearish→Bullish re-base | Crashed below 150MA, now re-establishing above it |
| `below150_floor` | Below 150MA · support floor | Below 150MA but holding a well-tested support floor |
| `triangle` | Converging triangle | Falling highs + rising lows converging |
| `fibonacci` | Fibonacci retracement | Pulled back to the 0.5–0.618 zone of a prior rise |
| `ma_bounce` | Bounce off 150/200MA | Tagged a major MA and turned back up |
| `rising_channel` | Rising channel | Parallel up-channel, price near the lower rail |
| `bull_flag` | Bull flag | Sharp pole + descending flag breaking upward |
| `support_test` | Support test / breakout | Broken resistance being retested from above |

All proximity thresholds scale with ATR, so calm and volatile names are judged fairly.

## Run it

### 1. Backend (port 10000)

```bash
# from d:\pythonProject7
venv\Scripts\python.exe -m pip install -r backend\requirements.txt
venv\Scripts\python.exe main.py          # launches uvicorn (FastAPI app)
```

Check it: <http://localhost:10000/api/analyze/GTLB> and the auto-docs at
<http://localhost:10000/docs>.

### 2. Frontend (port 6000)

```bash
# from d:\pythonProject7\frontend
npm install       # first time only
npm start         # ng serve --port 6000
```

Open <http://localhost:6000>.

## Using the app

- **Analyze box** — type a ticker (e.g. `GTLB`, `ORCL`, `NEE`, `GOOGL`) → Enter.
- **Scan universe** — pick a limit (and optionally one setup) → *Run scan*. Matching
  tickers appear in the sidebar with their setup chips; click one to load its chart.
- **Toggles** (top-right) — show/hide the SMAs, S/R levels, trendlines, channels,
  triangles, Fibonacci levels, and markers.
- **Setups panel** (bottom) — every detected setup with an *active* (tradeable now) vs
  *watch* tag and a one-line explanation.

## API

| Endpoint | Description |
|----------|-------------|
| `GET /api/health` | liveness |
| `GET /api/tickers` | full ticker universe |
| `GET /api/analyze/{ticker}` | bars + indicators + overlay geometry + setups |
| `GET /api/scan?limit=&setup=` | scan universe, return stocks with ≥1 setup |

## Notes

- Data source is `yahooquery` (2y daily history). The first scan of a large universe is
  slow (~2–3 s per name); use the `limit` field to keep scans snappy.
- The universe comes from the **unchanged** `ticker_finder.py` (Dow + Nasdaq 100 + S&P 500).
- The old matplotlib screener (`resistance_breakout_indicator.py` + `main.py`) still runs
  standalone if you want static charts instead of the web UI.
