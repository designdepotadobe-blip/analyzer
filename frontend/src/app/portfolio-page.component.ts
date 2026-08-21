import { Component, OnDestroy } from '@angular/core';
import { Router } from '@angular/router';
import { forkJoin, of, Subscription } from 'rxjs';
import { catchError } from 'rxjs/operators';
import { ApiService } from './api.service';
import { Analysis, ScanHit } from './models';

/** One row of the portfolio table — held or suggested, same shape either way so
 *  the template renders both through one card, and a suggestion that gets added
 *  becomes a holding without reshaping anything. */
export interface PortfolioRow {
  ticker: string;
  held: boolean;
  sector: string | null;
  sector_icon: string | null;
  grade: 'A' | 'B' | 'C' | 'D' | 'F';
  grade_score: number;
  /** the 1-10 the card shows; the letter stays as the colour band behind it */
  rating: number;
  state: string;
  action: string;
  price: number;
  entry: number | null;
  stop: number | null;
  stop_atr: number | null;
  risk_pct: number | null;
  risk_reward: number | null;
  p_win: number | null;
  expectancy_r: number | null;
  gain_pct: number | null;
  gain_days: number | null;
  gain_hit_rate: number | null;
  call_he: string;
  /** why this suggestion was picked — shown only on suggested rows */
  why?: string;
}

/** Every position sized so its OWN stop risks the same STOP_RISK_BUDGET_PCT of the
 *  account (backend config.py) — so summing expectancy_r across N such positions
 *  approximates the whole block's expected return in the same units, and N times
 *  that budget is the exact worst-case loss if every stop fires at once. Mirrors
 *  the backend constant; not re-derived from the payload because no single
 *  response carries it — each option already encodes its OWN sizing, this is the
 *  unit that sizing was computed in. */
const STOP_RISK_BUDGET_PCT = 1.0;
/** How many holdings the same sector may claim among the suggestions before it is
 *  skipped in favor of the next-best candidate elsewhere — the direct answer to
 *  "we can't count on 4 stocks all graded A and all semiconductors". Held
 *  positions the user already typed are never touched by this, only what gets
 *  suggested to sit beside them. */
const MAX_PER_SECTOR = 2;

type RiskTolerance = 'conservative' | 'balanced' | 'aggressive';
type WizardStep = 'holdings' | 'risk' | 'sectors' | 'review' | 'summary';

/** Each preset maps directly to params `/api/scan` already supports — this is a
 *  frontend-only wiring choice, no backend change needed. "risk reward etc." made
 *  concrete: conservative prefers the tightest stop available, aggressive prefers
 *  the largest raw upside, balanced is today's old default (expectancy, min B). */
const RISK_PRESETS: Record<RiskTolerance, {
  minGrade: 'A' | 'B' | 'C' | 'D' | 'F';
  sort: 'expectancy' | 'rr' | 'gain' | 'risk';
  label: string;
  desc: string;
}> = {
  conservative: {
    minGrade: 'A', sort: 'risk',
    label: 'שמרני',
    desc: 'רק ציון A, והסטופ הכי צמוד קודם — הכי פחות סיכון בכניסה',
  },
  balanced: {
    minGrade: 'B', sort: 'expectancy',
    label: 'מאוזן',
    desc: 'ציון B ומעלה, ממוין לפי Expectancy — האיזון בין סיכוי לסיכון',
  },
  aggressive: {
    minGrade: 'C', sort: 'gain',
    label: 'אגרסיבי',
    desc: 'ציון C ומעלה, הפוטנציאל הגבוה ביותר קודם — סיכוי נמוך יותר, תמורה גדולה יותר',
  },
};

/** The known sector set, mirrored from `backend/market_data.py`'s `SECTOR_ICONS`
 *  keys (deduped to one canonical label per sector — the backend maps both
 *  "Financials"/"Financial Services" and both "Health Care"/"Healthcare" spellings
 *  to the same icon, since different data another era of yahooquery returns
 *  either; `sectorKey()` below normalizes an incoming row the same way before
 *  checking it against `excludedSectors`). */
const KNOWN_SECTORS: { name: string; icon: string }[] = [
  { name: 'Technology', icon: '💻' },
  { name: 'Communication Services', icon: '📡' },
  { name: 'Consumer Cyclical', icon: '🛍️' },
  { name: 'Consumer Defensive', icon: '🛒' },
  { name: 'Energy', icon: '⛽' },
  { name: 'Financial Services', icon: '🏦' },
  { name: 'Healthcare', icon: '⚕️' },
  { name: 'Industrials', icon: '🏭' },
  { name: 'Real Estate', icon: '🏢' },
  { name: 'Materials', icon: '⚗️' },
  { name: 'Utilities', icon: '💡' },
];

/** Mirrors verdict.Judgement._best_option exactly — the option the GRADE and the
 *  headline were judged on, not just whichever option happens to be listed first.
 *  Grading the wrong option is how VRTX once read F while its own text said "in
 *  the move, holding" against a 3.3 R/R pullback entry. */
function bestOption(a: Analysis) {
  const opts = a.micha.options;
  if (!opts.length) return null;
  const want: { [k: string]: string } = {
    enter: 'now', wait_trigger: 'breakout', wait_event: 'breakout',
    wait_pullback: 'pullback', hold: 'pullback',
  };
  const wantKind = want[a.micha.action];
  if (wantKind) {
    const match = opts.find((o) => o.kind === wantKind);
    if (match) return match;
  }
  const order: { [k: string]: number } = { now: 0, breakout: 1, pullback: 2 };
  return [...opts].sort((x, y) => (order[x.kind] ?? 3) - (order[y.kind] ?? 3))[0];
}

function fromAnalysis(tk: string, a: Analysis): PortfolioRow {
  const m = a.micha;
  const best = bestOption(a);
  return {
    ticker: tk, held: true,
    sector: a.meta.sector, sector_icon: a.meta.sector_icon,
    grade: m.grade, grade_score: m.grade_score, rating: m.rating,
    state: m.state, action: m.action,
    price: a.meta.price,
    entry: best?.entry ?? null, stop: best?.stop ?? null, stop_atr: best?.stop_atr ?? null,
    risk_pct: best?.risk_pct ?? null, risk_reward: best?.risk_reward ?? null,
    p_win: best?.p_win ?? null, expectancy_r: best?.expectancy_r ?? null,
    gain_pct: m.growth?.gain_pct ?? null, gain_days: m.growth?.days ?? null,
    gain_hit_rate: m.growth?.hit_rate ?? null,
    call_he: m.report.call_he,
  };
}

function fromScanHit(h: ScanHit, why?: string): PortfolioRow {
  return {
    ticker: h.ticker, held: false,
    sector: h.sector, sector_icon: h.sector_icon,
    grade: h.grade, grade_score: h.grade_score, rating: h.rating,
    state: h.state, action: h.action,
    price: h.price,
    entry: h.entry, stop: h.stop, stop_atr: h.stop_atr,
    risk_pct: h.risk_pct, risk_reward: h.risk_reward,
    p_win: h.p_win, expectancy_r: h.expectancy_r,
    gain_pct: h.gain_pct, gain_days: h.gain_days, gain_hit_rate: h.gain_hit_rate,
    call_he: h.call_he, why,
  };
}

@Component({
  selector: 'app-portfolio-page',
  templateUrl: './portfolio-page.component.html',
  styleUrls: ['./portfolio-page.component.css'],
})
export class PortfolioPageComponent implements OnDestroy {
  tickerInput = '';
  targetSize = 6;
  readonly targetOptions = [4, 5, 6];

  loading = false;
  error = '';
  ran = false;

  holdings: PortfolioRow[] = [];
  suggestions: PortfolioRow[] = [];
  /** tickers the user typed that failed to analyze (bad symbol, no data) */
  failedTickers: string[] = [];

  // Stable `*ngTemplateOutlet` context objects — see radar-page.component.ts's
  // `refreshBuckets()` comment for the full story: an inline `{ list: holdings }`
  // literal in the template is a NEW object every change-detection cycle (and a
  // hovering mouse fires plenty of those via `mousemove`), and `NgTemplateOutlet`
  // tears down and rebuilds its whole embedded view whenever that reference
  // changes — which silently breaks hover if the card underneath the cursor keeps
  // getting replaced. Refreshed only when the arrays they wrap are reassigned.
  holdingsCtx: { list: PortfolioRow[] } = { list: [] };
  suggestionsCtx: { list: PortfolioRow[] } = { list: [] };
  private refreshCtx(): void {
    this.holdingsCtx = { list: this.holdings };
    this.suggestionsCtx = { list: this.suggestions };
  }

  // ── The wizard ────────────────────────────────────────────────────────────
  wizardStep: WizardStep = 'holdings';
  readonly riskPresets = RISK_PRESETS;
  readonly riskOrder: RiskTolerance[] = ['conservative', 'balanced', 'aggressive'];
  riskTolerance: RiskTolerance = 'balanced';

  readonly knownSectors = KNOWN_SECTORS;
  excludedSectors = new Set<string>();

  reviewStreaming = false;
  reviewFoundCount = 0;
  private candidatePool: ScanHit[] = [];
  private reviewIndex = 0;
  private rejectedTickers = new Set<string>();
  private sectorCounts = new Map<string, number>();
  private reviewSub?: Subscription;
  currentCandidateHit: ScanHit | null = null;

  // ── Quick-look preview (hover on desktop, tap on mobile) — same mechanism as
  // the Radar page, reused verbatim so both pages "take advantage of the
  // analyzer" the same way. ──────────────────────────────────────────────────
  previewTicker: string | null = null;
  previewAnchor: DOMRect | null = null;
  previewMode: 'popover' | 'sheet' = 'popover';
  private hoverTimer: ReturnType<typeof setTimeout> | null = null;
  private closeTimer: ReturnType<typeof setTimeout> | null = null;
  private readonly HOVER_OPEN_DELAY = 280;
  private readonly CLOSE_GRACE = 220;
  private readonly MOBILE_BREAKPOINT = 768;

  constructor(private api: ApiService, private router: Router) {}

  ngOnDestroy(): void {
    this.reviewSub?.unsubscribe();
    if (this.hoverTimer) clearTimeout(this.hoverTimer);
    if (this.closeTimer) clearTimeout(this.closeTimer);
  }

  get isMobileNow(): boolean {
    return typeof window !== 'undefined' && window.innerWidth <= this.MOBILE_BREAKPOINT;
  }

  // ── Step 1: holdings (unchanged behavior — type tickers, analyze, then the
  // wizard begins) ─────────────────────────────────────────────────────────
  build(): void {
    const tickers = Array.from(new Set(
      this.tickerInput
        .split(/[\s,]+/)
        .map((t) => t.trim().toUpperCase())
        .filter(Boolean)
    ));

    this.loading = true;
    this.error = '';
    this.ran = true;
    this.holdings = [];
    this.suggestions = [];
    this.failedTickers = [];
    this.refreshCtx();

    const held$ = tickers.length
      ? forkJoin(tickers.map((tk) =>
          this.api.analyze(tk).pipe(catchError(() => of(null)))
        ))
      : of([] as (Analysis | null)[]);

    held$.subscribe({
      next: (results) => {
        results.forEach((a, i) => {
          if (a) this.holdings.push(fromAnalysis(tickers[i], a));
          else this.failedTickers.push(tickers[i]);
        });
        this.refreshCtx();
        this.loading = false;
        this.wizardStep = 'risk';
      },
      error: () => {
        this.error = 'לא הצלחתי לנתח את הרשימה — בדקו את הסמלים ונסו שוב.';
        this.loading = false;
      },
    });
  }

  // ── Step 2: risk tolerance ──────────────────────────────────────────────
  selectRisk(r: RiskTolerance): void {
    this.riskTolerance = r;
  }

  confirmRisk(): void {
    this.wizardStep = 'sectors';
  }

  // ── Step 3: sectors to avoid ─────────────────────────────────────────────
  private sectorKey(s: string | null): string {
    if (!s) return 'אחר';
    if (s === 'Financials') return 'Financial Services';
    if (s === 'Health Care') return 'Healthcare';
    if (s === 'Basic Materials') return 'Materials';
    return s;
  }

  toggleExcludedSector(name: string): void {
    if (this.excludedSectors.has(name)) this.excludedSectors.delete(name);
    else this.excludedSectors.add(name);
  }

  backToRisk(): void {
    this.wizardStep = 'risk';
  }

  confirmSectors(): void {
    this.wizardStep = 'review';
    this.startReview();
  }

  // ── Step 4: review candidates one at a time ─────────────────────────────
  get slotsLeft(): number {
    return Math.max(0, this.targetSize - this.holdings.length);
  }

  private startReview(): void {
    this.reviewSub?.unsubscribe();
    this.candidatePool = [];
    this.rejectedTickers.clear();
    this.suggestions = [];
    this.refreshCtx();
    this.reviewIndex = 0;
    this.currentCandidateHit = null;
    this.reviewFoundCount = 0;
    this.reviewStreaming = true;
    this.error = '';

    this.sectorCounts.clear();
    for (const h of this.holdings) {
      const s = this.sectorKey(h.sector);
      this.sectorCounts.set(s, (this.sectorCounts.get(s) || 0) + 1);
    }

    const preset = RISK_PRESETS[this.riskTolerance];
    const heldTickers = new Set(this.holdings.map((h) => h.ticker));

    this.reviewSub = this.api.scanStream({
      limit: 250, actionable: true, minGrade: preset.minGrade, sort: preset.sort, workers: 8,
    }).subscribe({
      next: (msg) => {
        if ('done' in msg && msg.done) {
          this.reviewStreaming = false;
          this.candidatePool = this.sortByPreset(this.candidatePool, preset.sort);
          this.currentCandidateHit = this.findNextCandidate(0);
          if (!this.currentCandidateHit) this.wizardStep = 'summary';
          return;
        }
        const hit = msg as ScanHit;
        if (!heldTickers.has(hit.ticker)) {
          this.candidatePool.push(hit);
          this.reviewFoundCount = this.candidatePool.length;
        }
      },
      error: () => {
        this.reviewStreaming = false;
        this.error = 'הסריקה נכשלה — האם ה-API רץ?';
      },
    });
  }

  private sortByPreset(rows: ScanHit[], sort: 'expectancy' | 'rr' | 'gain' | 'risk'): ScanHit[] {
    return [...rows].sort((a, b) => {
      switch (sort) {
        case 'expectancy': return (b.expectancy_r ?? -9) - (a.expectancy_r ?? -9);
        case 'risk': return (a.stop_atr ?? 1e9) - (b.stop_atr ?? 1e9);
        case 'gain': return (b.gain_pct ?? -1e9) - (a.gain_pct ?? -1e9);
        case 'rr': return (b.risk_reward ?? -1e9) - (a.risk_reward ?? -1e9);
        default: return 0;
      }
    });
  }

  /** The next candidate respecting: not held, not already rejected this session,
   *  not already accepted, sector not excluded, and its sector hasn't already
   *  claimed MAX_PER_SECTOR slots — the same diversity constraint the old
   *  one-shot `pickSuggestions()` enforced, just walked one at a time instead of
   *  greedily filling the whole list in a single pass. */
  private findNextCandidate(fromIndex: number): ScanHit | null {
    for (let i = fromIndex; i < this.candidatePool.length; i++) {
      const hit = this.candidatePool[i];
      if (this.rejectedTickers.has(hit.ticker)) continue;
      if (this.suggestions.some((s) => s.ticker === hit.ticker)) continue;
      const sector = this.sectorKey(hit.sector);
      if (this.excludedSectors.has(sector)) continue;
      if ((this.sectorCounts.get(sector) || 0) >= MAX_PER_SECTOR) continue;
      this.reviewIndex = i + 1;
      return hit;
    }
    this.reviewIndex = this.candidatePool.length;
    return null;
  }

  get currentCandidateRow(): PortfolioRow | null {
    return this.currentCandidateHit ? fromScanHit(this.currentCandidateHit) : null;
  }

  acceptCandidate(): void {
    const hit = this.currentCandidateHit;
    if (!hit) return;
    const sector = this.sectorKey(hit.sector);
    this.sectorCounts.set(sector, (this.sectorCounts.get(sector) || 0) + 1);
    const isNewSector = !this.holdings.some((h) => this.sectorKey(h.sector) === sector)
      && !this.suggestions.some((s) => this.sectorKey(s.sector) === sector);
    this.suggestions.push(fromScanHit(hit, isNewSector
      ? 'הכי טוב, וגם סקטור חדש בתיק'
      : `${sector} — כבר בתיק, זה עדיין הכי משתלם`));
    this.refreshCtx();
    this.advanceReview();
  }

  rejectCandidate(): void {
    if (this.currentCandidateHit) this.rejectedTickers.add(this.currentCandidateHit.ticker);
    this.advanceReview();
  }

  private advanceReview(): void {
    if (this.suggestions.length >= this.slotsLeft) {
      this.wizardStep = 'summary';
      return;
    }
    this.currentCandidateHit = this.findNextCandidate(this.reviewIndex);
    if (!this.currentCandidateHit && !this.reviewStreaming) {
      this.wizardStep = 'summary';
    }
  }

  backFromReview(): void {
    this.reviewSub?.unsubscribe();
    this.reviewStreaming = false;
    this.wizardStep = 'sectors';
  }

  // ── Step 5: summary ───────────────────────────────────────────────────────
  editPreferences(): void {
    this.reviewSub?.unsubscribe();
    this.suggestions = [];
    this.refreshCtx();
    this.rejectedTickers.clear();
    this.wizardStep = 'risk';
  }

  // ── Portfolio-level numbers ────────────────────────────────────────────────
  get allRows(): PortfolioRow[] { return [...this.holdings, ...this.suggestions]; }

  /** Worst case: every position's stop fires the same day. Each position is sized
   *  to risk exactly STOP_RISK_BUDGET_PCT — that is the whole point of sizing by
   *  risk budget rather than by dollar amount, it makes this sum meaningful. */
  get worstCaseRiskPct(): number {
    return this.allRows.length * STOP_RISK_BUDGET_PCT;
  }

  get totalExpectancyR(): number {
    return this.allRows.reduce((s, r) => s + (r.expectancy_r ?? 0), 0);
  }

  /** Approximate expected return on the capital this portfolio deploys, in the
   *  same risk-budget units as worstCaseRiskPct — sum(expectancy_r) positions,
   *  each already scaled to the same 1%-risk unit. */
  get expectedReturnPct(): number {
    return this.totalExpectancyR * STOP_RISK_BUDGET_PCT;
  }

  sectorBreakdown(): { sector: string; icon: string; count: number }[] {
    const by = new Map<string, { icon: string; count: number }>();
    for (const r of this.allRows) {
      const key = r.sector || 'אחר';
      const cur = by.get(key) || { icon: r.sector_icon || '📈', count: 0 };
      cur.count += 1;
      by.set(key, cur);
    }
    return Array.from(by.entries())
      .map(([sector, v]) => ({ sector, icon: v.icon, count: v.count }))
      .sort((a, b) => b.count - a.count);
  }

  get worstSectorConcentration(): { sector: string; count: number } | null {
    const b = this.sectorBreakdown();
    if (!b.length || this.allRows.length < 2) return null;
    const top = b[0];
    return top.count >= 3 ? top : null;
  }

  removeHolding(tk: string): void {
    this.holdings = this.holdings.filter((h) => h.ticker !== tk);
    this.refreshCtx();
  }

  removeSuggestion(tk: string): void {
    this.suggestions = this.suggestions.filter((s) => s.ticker !== tk);
    this.refreshCtx();
  }

  // ── Quick-look: hover (desktop) or tap (mobile) — identical mechanism to the
  // Radar page's, see that file for why the timers/stable-context work the way
  // they do. ──────────────────────────────────────────────────────────────────
  onCardEnter(ticker: string, ev: MouseEvent): void {
    if (this.isMobileNow) return;
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
    // exact wizard step with `close()`, never a `router.navigate` that would lose
    // it. Desktop's hover popover (`onCardEnter`) is untouched — still a quick
    // trimmed glance — this only changes what commits to the FULL analysis.
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

  openStock(tk: string): void {
    this.router.navigate(['/'], { queryParams: { ticker: tk } });
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

  trackByTicker(_index: number, r: PortfolioRow): string {
    return r.ticker;
  }
}
