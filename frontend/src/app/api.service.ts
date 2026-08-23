import { Injectable, NgZone } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../environments/environment';
import { Analysis, ScanHit, ScanResponse } from './models';

/** The `done` sentinel closing a `scanStream()` — the SSE equivalent of the blocking
 *  endpoint's `{scanned, matched}` summary, since a live stream has no other moment
 *  to report a final count. */
export interface ScanStreamDone {
  done: true;
  scanned: number;
  matched: number;
}

export interface ScanOpts {
  limit?: number;
  actionable?: boolean;
  minGrade?: 'A' | 'B' | 'C' | 'D' | 'F';
  sort?: 'setups' | 'alert' | 'grade' | 'expectancy' | 'rr' | 'gain' | 'risk';
  workers?: number;
  /** A distinct trading profile (api.py's `_preset_ok`), not another grade
   *  floor — the same sort-by-grade otherwise converges on the same calm
   *  large-caps every time, since they satisfy every axis at once. */
  preset?: 'aggressive' | 'ready' | 'conservative' | 'reversal';
}

@Injectable({ providedIn: 'root' })
export class ApiService {
  // FastAPI backend — localhost:10000 in dev, the deployed Railway URL in prod
  // (environment.prod.ts, swapped in at build time via angular.json's
  // fileReplacements).
  private readonly base = environment.apiBase;

  constructor(private http: HttpClient, private zone: NgZone) {}

  analyze(ticker: string): Observable<Analysis> {
    return this.http.get<Analysis>(`${this.base}/api/analyze/${ticker.trim().toUpperCase()}`);
  }

  scan(limit = 60, setup?: string): Observable<ScanResponse> {
    let url = `${this.base}/api/scan?limit=${limit}`;
    if (setup) {
      url += `&setup=${setup}`;
    }
    return this.http.get<ScanResponse>(url);
  }

  private scanParams(opts: ScanOpts): URLSearchParams {
    const p = new URLSearchParams();
    p.set('limit', String(opts.limit ?? 250));
    p.set('workers', String(opts.workers ?? 8));
    if (opts.actionable) p.set('actionable', 'true');
    if (opts.minGrade) p.set('min_grade', opts.minGrade);
    if (opts.sort) p.set('sort', opts.sort);
    if (opts.preset) p.set('preset', opts.preset);
    return p;
  }

  /** The general scan, for the Radar "actionable today" view and the Portfolio
   *  Builder's candidate universe. `actionable=true` is the stricter question the
   *  watchlist actually asks — entering now, or coiled at the trigger with the
   *  alert already imminent/close — not just "has a setup". `minGrade` is an
   *  inclusive floor. `sort` adds `expectancy`/`rr`/`gain`/`risk` to the base set. */
  scanFull(opts: ScanOpts): Observable<ScanResponse> {
    return this.http.get<ScanResponse>(`${this.base}/api/scan?${this.scanParams(opts).toString()}`);
  }

  /** Same filters as `scanFull()`, but a LIVE feed: one hit as it completes instead
   *  of waiting for the whole scan (which is a multi-minute blank wait at limit=250+).
   *  Backed by `GET /api/scan?...&stream=true` (backend/api.py), a server-sent-events
   *  response — `work()` there is byte-identical either way, streaming only changes
   *  how the same computed hits leave the process.
   *
   *  Completes the Observable itself (and closes the `EventSource`) the moment the
   *  server's closing `{done:true,...}` frame arrives. This matters: `EventSource`
   *  auto-reconnects by default whenever its connection drops, and a naturally-ended
   *  stream looks exactly like a dropped one from its perspective — without closing
   *  here first, it would silently re-open the whole scan in a loop. Callers just
   *  subscribe and get a normal RxJS completion; no manual unsubscribe bookkeeping.
   *
   *  Every `subscriber` call is wrapped in `this.zone.run()` — zone.js's default
   *  browser patches do not reliably intercept `EventSource`'s `onmessage`/`onerror`
   *  assignment the way they intercept `setTimeout`/`XHR`/`fetch`, so without this
   *  the callbacks fire and DO mutate component state, but OUTSIDE Angular's zone —
   *  no change detection ever runs afterward, and the view just never updates. This
   *  was invisible on the Radar page purely by accident: its 1-second `setInterval`
   *  clock (which IS zone-patched) was triggering a change-detection pass roughly
   *  once a second anyway, incidentally picking up whatever this stream had already
   *  written to component fields in between. It was NOT invisible on the Portfolio
   *  page, which has no such timer during its review step — confirmed by a live
   *  console trace showing `next()` firing 25 times while the DOM's "0 found so
   *  far" text never moved once. `NgZone.run()` makes this correct unconditionally,
   *  rather than depending on an unrelated timer happening to exist nearby. */
  scanStream(opts: ScanOpts): Observable<ScanHit | ScanStreamDone> {
    const p = this.scanParams(opts);
    p.set('stream', 'true');
    const url = `${this.base}/api/scan?${p.toString()}`;
    return new Observable<ScanHit | ScanStreamDone>((subscriber) => {
      const es = new EventSource(url);
      es.onmessage = (ev) => {
        try {
          const parsed = JSON.parse(ev.data);
          this.zone.run(() => {
            subscriber.next(parsed);
            if (parsed && parsed.done) {
              es.close();
              subscriber.complete();
            }
          });
        } catch (e) {
          this.zone.run(() => subscriber.error(e));
        }
      };
      // A genuine connection failure (server down, network drop) — NOT the normal
      // end-of-stream case, which is already handled above by closing on the `done`
      // frame before EventSource's own reconnect logic ever gets a chance to run.
      es.onerror = (ev) => this.zone.run(() => subscriber.error(ev));
      return () => es.close();
    });
  }

  tickers(): Observable<{ count: number; tickers: string[] }> {
    return this.http.get<{ count: number; tickers: string[] }>(`${this.base}/api/tickers`);
  }

  /** The hidden analyst-notes box (see the easter egg in AnalyzerPageComponent) —
   *  posts straight to the local, gitignored JSONL file api.py's `add_note` appends
   *  to. Nothing reads this back automatically; it is reviewed by hand later. */
  submitNote(ticker: string, note: string, ctx: {
    price?: number | null; grade?: string | null; grade_score?: number | null;
    state?: string | null; action?: string | null;
  }): Observable<{ saved: boolean }> {
    return this.http.post<{ saved: boolean }>(`${this.base}/api/notes`, { ticker, note, ...ctx });
  }
}
