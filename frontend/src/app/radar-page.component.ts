import { Component, HostListener, OnDestroy, OnInit } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { Subscription } from 'rxjs';
import { ApiService } from './api.service';
import { ScanHit } from './models';

type SortKey = 'expectancy' | 'risk' | 'gain' | 'rr' | 'grade';
type RadarPreset = 'aggressive' | 'ready' | 'conservative' | 'reversal' | null;
type Grade = 'A' | 'B' | 'C' | 'D' | 'F';

const MOBILE_BREAKPOINT = 768;

interface SectorGroup {
  sector: string;
  icon: string;
  rows: ScanHit[];
  /** Precomputed `{ list: rows }` — see `computeSectorGroups` for why the template
   *  must bind to this instead of building the context object inline. */
  ctx: { list: ScanHit[] };
}

@Component({
  selector: 'app-radar-page',
  templateUrl: './radar-page.component.html',
  styleUrls: ['./radar-page.component.css'],
})
export class RadarPageComponent implements OnInit, OnDestroy {
  loading = false;
  /** True from the first hit until the closing `done` frame — drives the small
   *  "נסרקו X…" progress line, distinct from `loading` (which only covers the
   *  initial blank-screen wait before anything has arrived at all). */
  streaming = false;
  error = '';
  results: ScanHit[] = [];
  scanned = 0;
  matched = 0;
  lastScan: Date | null = null;
  private scanSub?: Subscription;

  limit = 250;
  // 1120 = the full universe (Dow + Nasdaq100 + S&P500 + S&P600 — see
  // ticker_finder.py). Was 517 before S&P 600 was added; this sentinel and the
  // matching `=== 1120` checks in the template must move together with any
  // future universe change or "scan everything" silently stops meaning that.
  readonly limitOptions = [60, 120, 250, 1120];

  minGrade: Grade = 'B';
  readonly gradeOptions: Grade[] = ['A', 'B', 'C', 'D'];

  sort: SortKey = 'expectancy';
  readonly sortOptions: { key: SortKey; label: string }[] = [
    { key: 'expectancy', label: 'Expectancy' },
    { key: 'risk', label: 'סיכון' },
    { key: 'gain', label: 'רווח' },
    { key: 'rr', label: 'יחס R' },
    { key: 'grade', label: 'ציון' },
  ];

  /** A distinct trading profile, not another grade floor — sorting by grade alone
   *  converges on the same calm large-caps every time, since they satisfy every
   *  axis at once. `null` is today's existing behaviour (unchanged): the
   *  `actionable`-only sweep. See api.py's `_preset_ok` for what each one means. */
  preset: RadarPreset = null;
  readonly presetOptions: { key: RadarPreset; label: string }[] = [
    { key: null, label: 'הכל' },
    { key: 'aggressive', label: '🔥 אגרסיבי' },
    { key: 'ready', label: '🔔 מוכן עכשיו' },
    { key: 'conservative', label: '🛡️ סווינג שמרני' },
    { key: 'reversal', label: '↩️ מהפך' },
  ];

  /** How many cards render per bucket, live — as better hits stream in and get
   *  re-sorted to the top, weaker ones fall off this cap automatically. Independent
   *  from `limit` (how many tickers get SCANNED — a performance/breadth control);
   *  this is purely a display cap. `Infinity` is "הכל". */
  displayCap = 30;
  readonly displayCapOptions = [20, 30, 50, Infinity];
  /** Angular templates can't reference the bare global `Infinity` identifier —
   *  only component-instance members are in scope — so it's exposed here the same
   *  way `limitOptions` exposes its own "show everything" sentinel (1120). */
  readonly INFINITY = Infinity;

  /** "sitting on the correct price to enter, or ready for it" — the exact question
   *  this page answers, split into the two buckets that answer it: already there,
   *  or one clean break away. Grouping by sector inside each is what stops a
   *  single-factor bet (4 semiconductor A-grades) from reading as 4 independent
   *  opportunities. */
  bySector = true;

  // ── Mobile: sector tiles → drill down, instead of one long scrolling grid ────
  selectedBucketMobile: 'enteringNow' | 'ready' | null = null;
  selectedSectorMobile: string | null = null;

  // ── Quick-look preview (hover on desktop, tap on mobile) ──────────────────────
  previewTicker: string | null = null;
  previewAnchor: DOMRect | null = null;
  previewMode: 'popover' | 'sheet' = 'popover';
  private hoverTimer: ReturnType<typeof setTimeout> | null = null;
  private closeTimer: ReturnType<typeof setTimeout> | null = null;
  private readonly HOVER_OPEN_DELAY = 280;
  private readonly CLOSE_GRACE = 220;

  // Re-renders the "updated Xs ago" line without a fresh scan.
  private clockTimer?: ReturnType<typeof setInterval>;
  now = Date.now();

  constructor(private api: ApiService, private route: ActivatedRoute) {}

  ngOnInit(): void {
    // Mirrors AnalyzerPageComponent's `?ticker=` pattern — mainly for deep-linking
    // a specific scan breadth, validated against the known chip values so a
    // malformed/arbitrary query param can't request something the backend wasn't
    // asked to support.
    const qLimit = Number(this.route.snapshot.queryParamMap.get('limit'));
    if (this.limitOptions.includes(qLimit)) {
      this.limit = qLimit;
    }
    this.runScan();
    this.clockTimer = setInterval(() => { this.now = Date.now(); }, 1000);
  }

  ngOnDestroy(): void {
    if (this.clockTimer) clearInterval(this.clockTimer);
    if (this.hoverTimer) clearTimeout(this.hoverTimer);
    if (this.closeTimer) clearTimeout(this.closeTimer);
    this.scanSub?.unsubscribe();
  }

  @HostListener('window:resize')
  onResize(): void {
    // no-op body — just gives Angular a zone-tracked event to re-run change
    // detection on, so `isMobileNow`'s window.innerWidth read stays current
    // across an orientation change or a devtools resize while testing.
  }

  get isMobileNow(): boolean {
    return typeof window !== 'undefined' && window.innerWidth <= MOBILE_BREAKPOINT;
  }

  runScan(): void {
    this.scanSub?.unsubscribe();
    this.loading = true;
    this.streaming = true;
    this.error = '';
    this.results = [];
    this.scanned = 0;
    this.matched = 0;
    this.refreshBuckets();
    this.scanSub = this.api.scanStream({
      limit: this.limit,
      // A preset already defines its own population (e.g. `reversal` wants
      // `turning`, which the `actionable` sweep's own "at_trigger + imminent"
      // definition of "ready" does not cover) — forcing `actionable` on top
      // would silently exclude exactly the names a preset exists to surface.
      actionable: this.preset == null,
      preset: this.preset ?? undefined,
      minGrade: this.minGrade,
      sort: this.sort === 'grade' ? 'grade' : this.sort,
      workers: 8,
    }).subscribe({
      next: (msg) => {
        if ('done' in msg && msg.done) {
          this.scanned = msg.scanned;
          this.matched = msg.matched;
          this.streaming = false;
          this.lastScan = new Date();
          this.loading = false;
          this.refreshBuckets();
          return;
        }
        const hit = msg as ScanHit;
        const i = this.results.findIndex((r) => r.ticker === hit.ticker);
        if (i >= 0) { this.results[i] = hit; } else { this.results.push(hit); }
        // first hit: drop the full-screen loader, buckets start rendering live
        this.loading = false;
        this.refreshBuckets();
      },
      error: () => {
        this.error = 'הסריקה נכשלה — האם ה-API רץ?';
        this.loading = false;
        this.streaming = false;
      },
    });
  }

  setLimit(n: number): void {
    if (n === this.limit) return;
    this.limit = n;
    this.runScan();
  }

  setMinGrade(g: Grade): void {
    if (g === this.minGrade) return;
    this.minGrade = g;
    this.runScan();
  }

  setSort(s: SortKey): void {
    if (s === this.sort) return;
    this.sort = s;
    this.runScan();
  }

  setPreset(p: RadarPreset): void {
    if (p === this.preset) return;
    this.preset = p;
    this.runScan();
  }

  setDisplayCap(n: number): void {
    this.displayCap = n;
    this.refreshBuckets();
  }

  toggleSector(): void {
    this.bySector = !this.bySector;
  }

  // ── The two buckets: entering now vs coiled at the trigger, ready ─────────
  //
  // These used to be getters, recomputed (and reallocated — `[...rows].sort()`,
  // a fresh array every call) on EVERY Angular change-detection cycle, including
  // the ones the 1-second clock timer triggers for `timeAgo()`. That fed a fresh
  // `{ list: enteringNow }` OBJECT LITERAL into `*ngTemplateOutlet`'s context on
  // every cycle — and `NgTemplateOutlet` tears down and recreates its ENTIRE
  // embedded view whenever that context reference changes, so the whole card grid
  // was being destroyed and rebuilt about once a second regardless of whether the
  // data had actually changed. Invisible before hover existed; with it, a card
  // being replaced out from under the cursor mid-hover meant `onCardEnter` kept
  // re-firing and its open timer never survived long enough to complete — found
  // via a live console trace showing dozens of re-fires per hover, not by
  // inspection. Fixed by making these (and the derived sector groups, and the
  // template's context objects) explicitly-refreshed fields with STABLE
  // references, updated only when the underlying data genuinely changes.
  enteringNow: ScanHit[] = [];
  ready: ScanHit[] = [];
  enteringNowCtx: { list: ScanHit[] } = { list: [] };
  readyCtx: { list: ScanHit[] } = { list: [] };
  enteringNowGroups: SectorGroup[] = [];
  readyGroups: SectorGroup[] = [];

  private isReady(h: ScanHit): boolean {
    return h.state === 'at_trigger' && (h.alert?.tier === 'imminent' || h.alert?.tier === 'close');
  }

  private refreshBuckets(): void {
    // `headline_action` is the single source of truth for "is this an entering
    // card" (verdict.HEADLINE_ACTION) — this used to re-declare the same three
    // states independently as `ACTIONABLE_NOW`, which is exactly the kind of
    // duplicated decision that drifts the day one of them changes and the other
    // doesn't.
    this.enteringNow = this.sortRows(this.results.filter((h) => h.headline_action === 'ENTER')).slice(0, this.displayCap);
    this.ready = this.sortRows(this.results.filter((h) => this.isReady(h))).slice(0, this.displayCap);
    this.enteringNowCtx = { list: this.enteringNow };
    this.readyCtx = { list: this.ready };
    this.enteringNowGroups = this.computeSectorGroups(this.enteringNow);
    this.readyGroups = this.computeSectorGroups(this.ready);
    this.refreshSelectedSector();
  }

  /** How full the proximity gauge reads — closer to the trigger = fuller.
   *  `ALERT_NEAR_ATR` (backend) caps this signal at 2.0 ATR, so that is the empty
   *  end of the scale. */
  fillPct(hit: ScanHit): number {
    const d = hit.alert?.distance_atr;
    if (d == null) return 0;
    return Math.max(4, Math.min(100, (1 - d / 2) * 100));
  }

  /** A short instruction for the same tier `verdict._alert` already computed —
   *  "READY" rather than a bare percentage, so a card this close to its trigger
   *  does not read as inactive under a blanket WAIT styling. */
  readyLabel(tier: 'imminent' | 'close' | 'near'): string {
    return { imminent: 'מוכנה — ממש קרוב', close: 'מוכנה — קרוב', near: 'מתקרבת' }[tier];
  }

  private sortRows(rows: ScanHit[]): ScanHit[] {
    const key = this.sort;
    return [...rows].sort((a, b) => {
      switch (key) {
        case 'expectancy': return (b.expectancy_r ?? -9) - (a.expectancy_r ?? -9);
        case 'risk': return (a.stop_atr ?? 1e9) - (b.stop_atr ?? 1e9);
        case 'gain': return (b.gain_pct ?? -1e9) - (a.gain_pct ?? -1e9);
        case 'rr': return (b.risk_reward ?? -1e9) - (a.risk_reward ?? -1e9);
        case 'grade': return b.grade_score - a.grade_score;
        default: return 0;
      }
    });
  }

  /** Sector groups for a bucket, each already internally sorted, groups ordered by
   *  their own best row so the sector with the single best opportunity leads. Also
   *  the source for the mobile sector TILES — `rows[0]` is already the top pick in
   *  that sector for the current sort. Private + called only from `refreshBuckets`
   *  now — see the comment there for why this can't be a template-invoked method
   *  returning a fresh array/objects on every change-detection cycle. */
  private computeSectorGroups(rows: ScanHit[]): SectorGroup[] {
    const by = new Map<string, ScanHit[]>();
    for (const h of rows) {
      const key = h.sector || 'אחר';
      if (!by.has(key)) by.set(key, []);
      by.get(key)!.push(h);
    }
    // `ctx` is precomputed here, once, rather than built inline in the template as
    // `{ list: sg.rows }` — that would be a fresh object literal on every change-
    // detection cycle even though `sg.rows` itself is now a stable reference, and
    // `*ngTemplateOutlet` tears down and rebuilds its whole view whenever the
    // context object it's given has a new identity (see `refreshBuckets`'s comment
    // for the full story — this is the same bug one level deeper).
    const groups = Array.from(by.entries()).map(([sector, rs]) => ({
      sector, icon: rs[0].sector_icon || '📈', rows: rs, ctx: { list: rs },
    }));
    const rank = (rs: ScanHit[]) => (rs[0]?.expectancy_r ?? rs[0]?.grade_score ?? -1e9);
    groups.sort((a, b) => rank(b.rows) - rank(a.rows));
    return groups;
  }

  /** Grade concentration warning — the actual "4 stocks all graded A, all
   *  semiconductors" case named on the page instead of left for the reader to
   *  notice card by card. Flags a sector once it is 3+ of the actionable set. */
  sectorWarning(rows: ScanHit[]): { sector: string; count: number } | null {
    const by = new Map<string, number>();
    for (const h of rows) {
      const key = h.sector || 'אחר';
      by.set(key, (by.get(key) || 0) + 1);
    }
    let worst: { sector: string; count: number } | null = null;
    for (const [sector, count] of by.entries()) {
      if (count >= 3 && (!worst || count > worst.count)) worst = { sector, count };
    }
    return worst;
  }

  // ── Mobile sector drill-down ───────────────────────────────────────────────
  selectedSectorRows: ScanHit[] = [];
  selectedSectorCtx: { list: ScanHit[] } = { list: [] };

  openSector(bucket: 'enteringNow' | 'ready', sector: string): void {
    this.selectedBucketMobile = bucket;
    this.selectedSectorMobile = sector;
    this.refreshSelectedSector();
  }

  closeSector(): void {
    this.selectedBucketMobile = null;
    this.selectedSectorMobile = null;
    this.selectedSectorRows = [];
    this.selectedSectorCtx = { list: [] };
  }

  /** Re-derived every time `refreshBuckets()` runs (not a snapshot taken when the
   *  tile was tapped) — a better hit streaming in for the open sector shows up in
   *  the drill-down list without the user backing out and re-entering. Same
   *  stable-reference reasoning as `enteringNow`/`ready` above. */
  private refreshSelectedSector(): void {
    if (!this.selectedBucketMobile || !this.selectedSectorMobile) return;
    const rows = this.selectedBucketMobile === 'enteringNow' ? this.enteringNow : this.ready;
    this.selectedSectorRows = rows.filter((h) => (h.sector || 'אחר') === this.selectedSectorMobile);
    this.selectedSectorCtx = { list: this.selectedSectorRows };
  }

  // ── Quick-look: hover (desktop) or tap (mobile) instead of navigating away ───
  onCardEnter(ticker: string, ev: MouseEvent): void {
    if (this.isMobileNow) return; // no hover on touch — onCardTap handles it
    this.cancelClose();
    if (this.hoverTimer) clearTimeout(this.hoverTimer);
    const rect = (ev.currentTarget as HTMLElement).getBoundingClientRect();
    this.hoverTimer = setTimeout(() => {
      this.previewTicker = ticker;
      this.previewAnchor = rect;
      this.previewMode = 'popover';
    }, this.HOVER_OPEN_DELAY);
  }

  onCardLeave(): void {
    if (this.hoverTimer) clearTimeout(this.hoverTimer);
    if (this.isMobileNow) return;
    this.scheduleClose();
  }

  onCardTap(ticker: string): void {
    // A click — mobile tap or desktop click alike — always jumps straight to the
    // full-screen sheet: the same embedded Analyzer page, closable back to this
    // exact scan with `close()`, never a `router.navigate` that would lose it.
    // Desktop's hover popover (`onCardEnter`) is untouched — still a quick trimmed
    // glance — this only changes what commits to the FULL analysis.
    if (this.hoverTimer) clearTimeout(this.hoverTimer);
    this.cancelClose();
    this.previewTicker = ticker;
    this.previewAnchor = null;
    this.previewMode = 'sheet';
  }

  /** The popover's own "→ ניתוח מלא" button (desktop hover) asking to escalate the
   *  ticker already being previewed into the same full sheet `onCardTap` opens. */
  onQuicklookRequestFull(): void {
    this.previewMode = 'sheet';
  }

  /** The popover reports its own hover state so moving the mouse FROM the card
   *  INTO the popover doesn't read as "left" and close it out from under the
   *  pointer. */
  onQuicklookHover(hovering: boolean): void {
    if (hovering) this.cancelClose(); else this.scheduleClose();
  }

  closePreview(): void {
    this.cancelClose();
    if (this.hoverTimer) clearTimeout(this.hoverTimer);
    this.previewTicker = null;
    this.previewAnchor = null;
  }

  private scheduleClose(): void {
    if (this.closeTimer) clearTimeout(this.closeTimer);
    this.closeTimer = setTimeout(() => {
      this.previewTicker = null;
      this.previewAnchor = null;
    }, this.CLOSE_GRACE);
  }

  private cancelClose(): void {
    if (this.closeTimer) clearTimeout(this.closeTimer);
  }

  timeAgo(): string {
    if (!this.lastScan) return '';
    const s = Math.max(0, Math.round((this.now - this.lastScan.getTime()) / 1000));
    if (s < 5) return 'ממש עכשיו';
    if (s < 60) return `לפני ${s} שניות`;
    const m = Math.round(s / 60);
    return `לפני ${m} ${m === 1 ? 'דקה' : 'דקות'}`;
  }

  readonly stateLabelHe: { [k: string]: string } = {
    breakout_now: 'פריצה עכשיו',
    buyers_at_level: 'קונים נכנסו על הרמה',
    value_pullback: 'השקעת ערך בתיקון',
    at_trigger: 'מתכנסת לפני פריצה',
    needs_buyers: 'על הרמה, מחכים לקונים',
    holding: 'בתוך המהלך, שומרת',
    nothing_yet: 'עוד לא עשתה כלום',
    broken: 'הסט אפ נגמר',
    avoid: 'מתחת ל-150 במגמה יורדת',
  };
  readonly actionLabelHe: { [k: string]: string } = {
    enter: 'כניסה',
    wait_trigger: 'להמתין לפריצה',
    wait_buyers: 'להמתין לקונים',
    wait_pullback: 'להמתין לתיקון',
    wait_event: 'להמתין לדיווח',
    hold: 'להחזיק',
    watch: 'מעקב + התראה',
    out: 'בחוץ',
    avoid: 'לא להיכנס',
  };
  readonly optionKindHe: { [k: string]: string } = {
    now: 'כניסה כאן', breakout: 'בפריצה', pullback: 'בתיקון',
  };

  readonly gradeColors: { [g: string]: string } = {
    A: '#26a69a', B: '#66bb6a', C: '#ffa726', D: '#ff7043', F: '#ef5350',
  };
  gradeColor(g: string): string {
    return this.gradeColors[g] || '#787b86';
  }

  expClass(e: number | null): string {
    if (e == null) return '';
    return e >= 0.25 ? 'exp-good' : e < 0 ? 'exp-bad' : '';
  }

  /** Identity by ticker rather than Angular's default (object reference, which is
   *  already stable here — see `refreshBuckets`) or array index — belt-and-
   *  suspenders so a card's DOM node survives re-sorts even if some future change
   *  ever reintroduces a fresh object per hit. */
  trackByTicker(_index: number, h: ScanHit): string {
    return h.ticker;
  }
}
