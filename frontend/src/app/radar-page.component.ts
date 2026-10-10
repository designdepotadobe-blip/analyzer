import { Component, HostListener, OnDestroy, OnInit } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { Subscription } from 'rxjs';
import { ApiService } from './api.service';
import { BoardChange, ScanHit } from './models';
import { sectorHe } from './sectors';

type SortKey = 'rating' | 'dist' | 'risk' | 'gain';
type RadarPreset = 'aggressive' | 'ready' | 'conservative' | 'reversal' | null;
type Tab = 'enter' | 'wait' | 'changes';

const MOBILE_BREAKPOINT = 768;

interface Group { sector: string; rows: ScanHit[]; }

/**
 * The daily board (backend/board.py): the universe is analysed once after the close
 * and stored; this page reads it instantly and filters it here — no rescan.
 *
 * Desktop is a dense watchlist table (sortable columns) with "what changed since
 * the last board" as a side column; the phone is the same data as tabs over
 * two-line list rows. Every row keeps the quick-look (hover on desktop, tap → sheet).
 *
 * Headless-Edge render constraints (memory: micha-radar-page) still hold for the
 * repeated rows: plain flex with the DOM order reversed for RTL (no row-reverse),
 * no CSS grid ancestors, no %-widths, `dir="rtl"` only on text-only leaves.
 */
@Component({
  selector: 'app-radar-page',
  templateUrl: './radar-page.component.html',
  styleUrls: ['./radar-page.component.css'],
})
export class RadarPageComponent implements OnInit, OnDestroy {
  loading = false;
  error = '';
  scanned = 0;
  failed = 0;
  private sub?: Subscription;
  private pollTimer?: ReturnType<typeof setTimeout>;

  private allHits: ScanHit[] = [];
  boardDate = '';
  prevDate = '';
  building: { done: number; total: number } | null = null;
  extended: { [t: string]: { price: number; change_pct: number | null } } = {};

  // ── what the page shows (stable references, refreshed only on data/filter change)
  tab: Tab = 'enter';
  enterRows: ScanHit[] = [];
  waitRows: ScanHit[] = [];
  rows: ScanHit[] = [];
  groups: Group[] = [];
  changeGroups: { kind: string; title: string; list: BoardChange[] }[] = [];
  changeCount = 0;
  concentration: { sector: string; count: number } | null = null;

  // ── filters
  preset: RadarPreset = null;
  readonly presetOptions: { key: RadarPreset; label: string }[] = [
    { key: null, label: 'הכל' },
    { key: 'aggressive', label: 'אגרסיבי' },
    { key: 'ready', label: 'מוכן עכשיו' },
    { key: 'conservative', label: 'סווינג שמרני' },
    { key: 'reversal', label: 'מהפך' },
  ];
  /** rating floor — 7+ is the old "B and up" default */
  minRating = 7;
  readonly ratingOptions = [5, 6, 7, 8];
  sort: SortKey = 'rating';
  readonly sortOptions: { key: SortKey; label: string }[] = [
    { key: 'rating', label: 'דירוג' },
    { key: 'dist', label: 'קרוב לקו' },
    { key: 'risk', label: 'סטופ צמוד' },
    { key: 'gain', label: 'פוטנציאל' },
  ];
  bySector = false;
  // the same lists in DOM order for the hand-built RTL rows
  readonly presetOptionsR = [...this.presetOptions].reverse();
  readonly ratingOptionsR = [...this.ratingOptions].reverse();
  readonly sortOptionsR = [...this.sortOptions].reverse();
  showFilters = false;

  readonly changeTitles: { [k: string]: string } = {
    new_enter: 'חדש לכניסה', broke_out: 'פרצה', near_trigger: 'התקרבה לפריצה', setup_over: 'הסט-אפ נגמר',
  };
  private readonly changeKinds = ['new_enter', 'broke_out', 'near_trigger', 'setup_over'];
  readonly sectorHe = sectorHe;
  readonly notches = [10, 9, 8, 7, 6, 5, 4, 3, 2, 1];   // DOM order reversed: 1 sits on the right

  // ── quick-look (hover on desktop, tap → full sheet)
  previewTicker: string | null = null;
  previewAnchor: DOMRect | null = null;
  previewMode: 'popover' | 'sheet' = 'popover';
  private hoverTimer: ReturnType<typeof setTimeout> | null = null;
  private closeTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(private api: ApiService, private route: ActivatedRoute, private router: Router) {}

  ngOnInit(): void {
    const q = this.route.snapshot.queryParamMap;
    const tab = q.get('tab');
    if (tab === 'enter' || tab === 'wait' || tab === 'changes') this.tab = tab;
    const p = q.get('profile');
    if (this.presetOptions.some((o) => o.key === p)) this.preset = p as RadarPreset;
    const m = Number(q.get('min'));
    if (this.ratingOptions.includes(m)) this.minRating = m;
    this.loadBoard();
  }

  ngOnDestroy(): void {
    this.sub?.unsubscribe();
    if (this.pollTimer) clearTimeout(this.pollTimer);
    if (this.hoverTimer) clearTimeout(this.hoverTimer);
    if (this.closeTimer) clearTimeout(this.closeTimer);
  }

  /** zone-tracked event so `isMobileNow` re-reads the width on rotate/resize */
  @HostListener('window:resize')
  onResize(): void {
    if (!this.isMobileNow && this.tab === 'changes') this.setTab('enter');
  }

  get isMobileNow(): boolean {
    return typeof window !== 'undefined' && window.innerWidth <= MOBILE_BREAKPOINT;
  }

  loadBoard(): void {
    this.sub?.unsubscribe();
    if (this.pollTimer) clearTimeout(this.pollTimer);
    this.error = '';
    this.loading = !this.allHits.length;
    this.sub = this.api.board().subscribe({
      next: (b) => {
        this.loading = false;
        if (!b.ready) {
          // first build of the day still running (a fresh server) — look again soon
          this.building = { done: b.status.done, total: b.status.total };
          this.pollTimer = setTimeout(() => this.loadBoard(), 8000);
          return;
        }
        this.building = null;
        this.allHits = b.hits || [];
        const changes = b.changes || [];
        this.changeCount = changes.length;
        this.changeGroups = this.changeKinds
          .map((k) => ({ kind: k, title: this.changeTitles[k], list: changes.filter((c) => c.kind === k) }))
          .filter((g) => g.list.length);
        this.extended = b.extended || {};
        this.boardDate = b.date || '';
        this.prevDate = b.prev_date || '';
        this.scanned = b.scanned || 0;
        this.failed = b.failed || 0;
        this.refresh();
      },
      error: () => {
        this.loading = false;
        this.error = 'הלוח היומי לא נטען. בדקו את החיבור ונסו שוב.';
      },
    });
  }

  // ── filters → rows ──────────────────────────────────────────────────────────
  private isReady(h: ScanHit): boolean {
    return h.state === 'at_trigger' && (h.alert?.tier === 'imminent' || h.alert?.tier === 'close');
  }

  private refresh(): void {
    const keep = this.allHits.filter((h) =>
      (!this.preset || (h.presets || []).includes(this.preset)) && h.rating >= this.minRating);
    this.enterRows = this.sortRows(keep.filter((h) => h.headline_action === 'ENTER'));
    this.waitRows = this.sortRows(keep.filter((h) => h.headline_action !== 'ENTER' && this.isReady(h)));
    this.rows = this.tab === 'wait' ? this.waitRows : this.enterRows;
    // always rendered through groups — one unnamed group when not split by sector
    this.groups = this.bySector ? this.group(this.rows) : [{ sector: '', rows: this.rows }];
    this.concentration = this.sectorWarning(this.rows);
  }

  private sortRows(rows: ScanHit[]): ScanHit[] {
    const k = this.sort;
    return [...rows].sort((a, b) => {
      let d = 0;
      if (k === 'rating') d = b.rating - a.rating || (b.expectancy_r ?? -9) - (a.expectancy_r ?? -9);
      if (k === 'dist') d = (a.alert?.distance_atr ?? 0) - (b.alert?.distance_atr ?? 0);
      if (k === 'risk') d = (a.stop_atr ?? 1e9) - (b.stop_atr ?? 1e9);
      if (k === 'gain') d = (b.gain_pct ?? -1e9) - (a.gain_pct ?? -1e9);
      return d !== 0 ? d : this.preferCompare(a, b);
    });
  }

  /** Tie-break (owner, 2026-10-09): bigger company first, then closer to the 150. */
  private preferCompare(a: ScanHit, b: ScanHit): number {
    const size = (c: number | null) => !c ? 0 : c >= 2e11 ? 4 : c >= 5e10 ? 3 : c >= 1e10 ? 2 : c >= 2e9 ? 1 : 0;
    const s = size(b.market_cap) - size(a.market_cap);
    if (s !== 0) return s;
    return Math.abs(a.sma150_dist_pct ?? 1e9) - Math.abs(b.sma150_dist_pct ?? 1e9);
  }

  private group(rows: ScanHit[]): Group[] {
    const by = new Map<string, ScanHit[]>();
    for (const h of rows) {
      const key = h.sector || 'אחר';
      if (!by.has(key)) by.set(key, []);
      by.get(key)!.push(h);
    }
    return Array.from(by.entries()).map(([sector, rs]) => ({ sector, rows: rs }));
  }

  /** One sector making up 3+ names (and a third or more) of the list is one bet, not several. */
  private sectorWarning(rows: ScanHit[]): { sector: string; count: number } | null {
    const by = new Map<string, number>();
    for (const h of rows) by.set(h.sector || 'אחר', (by.get(h.sector || 'אחר') || 0) + 1);
    let worst: { sector: string; count: number } | null = null;
    for (const [sector, count] of by.entries()) {
      if (count >= 3 && count * 3 >= rows.length && (!worst || count > worst.count)) worst = { sector, count };
    }
    return worst;
  }

  setTab(t: Tab): void {
    if (t === this.tab) return;
    this.tab = t;
    this.refresh();
    this.syncUrl();
  }

  setPreset(p: RadarPreset): void {
    if (p === this.preset) return;
    this.preset = p;
    this.refresh();
    this.syncUrl();
  }

  setMinRating(n: number): void {
    if (n === this.minRating) return;
    this.minRating = n;
    this.refresh();
    this.syncUrl();
  }

  setSort(s: SortKey): void {
    if (s === this.sort) return;
    this.sort = s;
    this.refresh();
  }

  toggleSector(): void {
    this.bySector = !this.bySector;
    this.refresh();
  }

  private syncUrl(): void {
    this.router.navigate([], {
      relativeTo: this.route,
      replaceUrl: true,
      queryParams: {
        tab: this.tab === 'enter' ? null : this.tab,
        profile: this.preset,
        min: this.minRating === 7 ? null : this.minRating,
      },
    });
  }

  // ── row text ────────────────────────────────────────────────────────────────
  /** "9 באוקטובר" */
  dayHe(iso: string): string {
    if (!iso) return '';
    return new Date(iso + 'T12:00:00').toLocaleDateString('he-IL', { day: 'numeric', month: 'long' });
  }

  /** The one price this row is about: the entry when it is in, the line to cross when it waits. */
  lineKey(h: ScanHit): string {
    return h.headline_action === 'ENTER' || h.trigger == null ? 'כניסה' : 'פריצה מעל';
  }

  lineVal(h: ScanHit): number | null {
    return h.headline_action === 'ENTER' || h.trigger == null ? h.entry : h.trigger;
  }

  /** closeness to a breakout is in ATR (owner rule, 2026-10-09) */
  distTxt(h: ScanHit): string {
    if (h.headline_action === 'ENTER') return 'על הקו';
    const d = h.alert?.distance_atr;
    return d == null ? '' : `${d.toFixed(2)} ATR`;
  }

  tierClass(h: ScanHit): string {
    if (h.headline_action === 'ENTER') return 'on';
    return h.alert?.tier === 'imminent' ? 'hot' : 'warm';
  }

  /** phone: the row's second line, one bidi-safe text leaf */
  planTxt(h: ScanHit): string {
    const v = this.lineVal(h);
    const parts: string[] = [];
    if (v != null) parts.push(`${this.lineKey(h)} ${v.toFixed(2)}`);
    if (h.headline_action !== 'ENTER' && h.alert) parts.push(`במרחק ${h.alert.distance_atr.toFixed(2)} ATR`);
    if (h.stop != null) parts.push(`סטופ ${h.stop.toFixed(2)}`);
    return parts.join(', ');
  }

  /** The waiting rows all share one generic read ("coiled under the breakout
   *  price"), so their "why" names the line itself and where the 150 is instead. */
  whyTxt(h: ScanHit): string {
    if (h.headline_action === 'ENTER' || h.trigger == null) return h.read_he;
    const what = h.trigger_what_he || 'מחיר הפריצה';
    const d = h.sma150_dist_pct;
    const ma = d == null ? '' : d >= 0 ? ` המחיר ${d.toFixed(1)}% מעל ממוצע 150.` : ` המחיר ${(-d).toFixed(1)}% מתחת לממוצע 150.`;
    return `ממתינה לפריצה של ${what}.${ma}`;
  }

  /** phone: the folded filter button still says what is active */
  filtersLabel(): string {
    const on: string[] = [];
    if (this.preset) on.push(this.presetOptions.find((o) => o.key === this.preset)!.label);
    if (this.minRating !== 7) on.push(`דירוג ${this.minRating}+`);
    if (this.bySector) on.push('לפי סקטור');
    return on.length ? `סינון: ${on.join(', ')}` : 'סינון ומיון';
  }

  gainTxt(h: ScanHit): string {
    return h.gain_pct == null ? '' : `+${Math.round(h.gain_pct)}%`;
  }

  ratingColor(r: number): string {
    return r >= 8 ? 'var(--up)' : r >= 6 ? '#7cc98f' : r >= 4 ? 'var(--wait)' : 'var(--down)';
  }

  trackByTicker(_i: number, h: ScanHit): string { return h.ticker; }
  trackBySector(_i: number, g: Group): string { return g.sector; }

  // ── quick-look ──────────────────────────────────────────────────────────────
  onRowEnter(ticker: string, ev: MouseEvent): void {
    if (this.isMobileNow) return;
    this.cancelClose();
    if (this.hoverTimer) clearTimeout(this.hoverTimer);
    const rect = (ev.currentTarget as HTMLElement).getBoundingClientRect();
    this.hoverTimer = setTimeout(() => {
      this.previewTicker = ticker;
      this.previewAnchor = rect;
      this.previewMode = 'popover';
    }, 280);
  }

  onRowLeave(): void {
    if (this.hoverTimer) clearTimeout(this.hoverTimer);
    if (!this.isMobileNow) this.scheduleClose();
  }

  /** A click always opens the full analysis as a sheet over this page — never a
   *  navigation that would lose the board's filters. */
  openFull(ticker: string): void {
    if (this.hoverTimer) clearTimeout(this.hoverTimer);
    this.cancelClose();
    this.previewTicker = ticker;
    this.previewAnchor = null;
    this.previewMode = 'sheet';
  }

  onQuicklookRequestFull(): void { this.previewMode = 'sheet'; }

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
    this.closeTimer = setTimeout(() => { this.previewTicker = null; this.previewAnchor = null; }, 220);
  }

  private cancelClose(): void {
    if (this.closeTimer) clearTimeout(this.closeTimer);
  }
}
