import { Component, Input, OnInit } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { ApiService } from './api.service';
import { Analysis, Meta, Micha, MichaReasonGroup, MichaState, Toggles } from './models';

@Component({
  selector: 'app-analyzer-page',
  templateUrl: './analyzer-page.component.html',
  styleUrls: ['./analyzer-page.component.css'],
})
export class AnalyzerPageComponent implements OnInit {
  /** Set only when embedded by `<app-stock-quicklook>` (`mode === 'sheet'`) — the
   *  ticker to load instead of the routed default below. Consumed once in
   *  `ngOnInit`, not the constructor: `@Input` bindings aren't set yet when the
   *  constructor runs, so reading it there would always see `null` and fall
   *  through to loading 'GTLB' first regardless — exactly the bug this fixes
   *  (a wasted, briefly-visible GTLB request every time a Radar/Portfolio card
   *  was clicked, before the real ticker's response overwrote it). */
  @Input() initialTicker: string | null = null;

  ticker = 'GTLB';
  analysis: Analysis | null = null;
  loading = false;
  error = '';

  // Reset on every load() — otherwise one ticker's dead logo (a thinly-covered name
  // Clearbit has no domain for) would permanently hide every logo loaded after it.
  logoFailed = false;

  // Which plan line the chart should emphasise. The entry/stop/target lines carry no
  // price-axis label by default (five of them in one narrow band was unreadable);
  // pointing at the matching row here reveals that one. Hover on desktop, tap on
  // touch — `chartHighlight` is just a key the chart component reads.
  chartHighlight: string | null = null;

  setHighlight(key: string | null): void {
    this.chartHighlight = key;
  }

  /** The chart draws only ONE option's entry/stop — the one matching the recommended
   *  action. Kept in sync with the same map in chart.component.ts so hovering a card
   *  the chart never drew doesn't pretend to highlight something. */
  private readonly drawnOptionByAction: { [k: string]: string } = {
    enter: 'now', wait_trigger: 'breakout', wait_event: 'breakout',
    wait_buyers: 'breakout', wait_pullback: 'pullback', hold: 'pullback',
    watch: 'breakout', out: 'breakout', avoid: 'breakout',
  };

  isDrawnOption(m: Micha, kind: string): boolean {
    const want = this.drawnOptionByAction[m.action];
    const drawn = m.options.find((o) => o.kind === want) || m.options[0];
    return !!drawn && drawn.kind === kind;
  }

  /** Touch has no hover, so a tap toggles the same emphasis. */
  toggleHighlight(key: string): void {
    this.chartHighlight = this.chartHighlight === key ? null : key;
  }

  // "Micha Analyze" mode — bilingual verdict panel + a Micha-only chart view
  // (150/200 MA, S/R levels, trend lines, Fib, breakout markers, entry & stop).
  michaMode = true;

  // The Micha panel opens on a compact "peek" — grade + why, headline action,
  // trigger/stop/target, key warnings — at EVERY width, not just phone. Tapping
  // the expand toggle reveals the rest (axis bars, full reasons list, option
  // cards, expected gain, the if-it-breaks projection). Was phone-only; desktop
  // used to render all of it unconditionally (measured 1,253-1,491 Hebrew
  // characters for one stock — see the CSS's own note on `.micha-expand-toggle`).
  michaExpanded = false;

  // Desktop/tablet only (CSS-gated the other way from michaExpanded above):
  // shrinks the 380px side panel to nothing so the chart can use that width,
  // WITHOUT touching michaMode — the analysis keeps running and the chart
  // keeps its Micha-only overlays, only the text panel hides. Independent of
  // the checkbox on purpose: unchecking michaMode also switches the chart's
  // own overlay set, which isn't what "just let me see more of the graph"
  // means.
  panelCollapsed = false;

  togglePanelCollapsed(): void {
    this.panelCollapsed = !this.panelCollapsed;
  }

  // ── Autocomplete ──────────────────────────────────────────────────────────
  tickerList: string[] = [];
  showSuggestions = false;
  suggestionIndex = -1;

  get filteredTickers(): string[] {
    const q = this.ticker.trim().toUpperCase();
    if (!q) return [];
    const sw = this.tickerList.filter(t => t.startsWith(q));
    const ct = this.tickerList.filter(t => !t.startsWith(q) && t.includes(q));
    return [...sw, ...ct].slice(0, 10);
  }

  /** Clicking into the search box to look up a new ticker used to require
   *  clearing the old one by hand first — clear it for them on focus instead. */
  onTickerFocus(): void {
    this.ticker = '';
    this.showSuggestions = false;
  }

  onTickerInput(): void {
    this.ticker = AnalyzerPageComponent.normalizeTicker(this.ticker);
    this.showSuggestions = true;
    this.suggestionIndex = -1;
  }

  /**
   * A ticker is Latin capitals and nothing else.
   *
   * Typed into the box, anything else is a lookup that cannot succeed: the symbol
   * universe is upper-case ASCII, and this app's other half is in Hebrew, so an
   * RTL keyboard left on is the ordinary way to end up typing "בvda" and getting
   * a dead result with no explanation. Lower case is folded up rather than
   * rejected — "nvda" is not a mistake, it is the same ticker.
   *
   * `.` and `-` survive because they are part of real symbols (BRK.B, RDS-A), and
   * digits because of names like 7203.T. Everything else — Hebrew, spaces,
   * punctuation, emoji — is dropped as it is typed.
   */
  static normalizeTicker(v: string): string {
    return (v || '').toUpperCase().replace(/[^A-Z0-9.\-]/g, '');
  }

  onBlur(): void {
    setTimeout(() => { this.showSuggestions = false; }, 150);
  }

  selectTicker(t: string): void {
    this.ticker = t;
    this.showSuggestions = false;
    this.load();
  }
  // ─────────────────────────────────────────────────────────────────────────

  toggles: Toggles = {
    sma20: false,
    sma50: false,
    sma150: true,
    sma200: true,
    levels: true,
    trendlines: true,
    channels: true,
    triangles: true,
    // off by default in both modes — see `syncMichaToggles`
    fib: false,
    markers: false,
    gaps: true,
    cup: false,
  };

  // Micha mode has its own independent toggle set, defaulted each load from the
  // backend's per-stock `chart_focus` (only what fits THIS stock is checked by
  // default) — but the user can still hide any of them individually.
  michaToggles: Toggles = {
    sma20: false, sma50: false, sma150: true, sma200: false,
    levels: true, trendlines: false, channels: false, triangles: false,
    fib: false, markers: false, gaps: false, cup: false,
  };

  readonly toggleKeys: { key: keyof Toggles; label: string }[] = [
    { key: 'sma20', label: 'SMA20' },
    { key: 'sma50', label: 'SMA50' },
    { key: 'sma150', label: 'SMA150' },
    { key: 'sma200', label: 'SMA200' },
    { key: 'levels', label: 'S/R levels' },
    { key: 'trendlines', label: 'Trendlines' },
    { key: 'channels', label: 'Channels' },
    { key: 'triangles', label: 'Triangles' },
    { key: 'fib', label: 'Fibonacci' },
    { key: 'markers', label: 'Markers' },
    // The yellow band. Its own control because it answers a question of its own —
    // "what is that yellow range?" — and `hasOverlay` hides the checkbox entirely
    // on a chart with no unfilled gap, so it only appears when there is one.
    { key: 'gaps', label: 'Gap' },
    { key: 'cup', label: 'Cup / target' },
  ];

  /** True only when the current analysis actually has data for this overlay. */
  hasOverlay(key: keyof Toggles): boolean {
    const a = this.analysis;
    if (!a) return true;
    switch (key) {
      case 'sma20':      return (a.indicators['sma20']?.length ?? 0) > 0;
      case 'sma50':      return (a.indicators['sma50']?.length ?? 0) > 0;
      case 'sma150':     return (a.indicators['sma150']?.length ?? 0) > 0;
      case 'sma200':     return (a.indicators['sma200']?.length ?? 0) > 0;
      case 'levels':     return a.overlays.levels.length > 0;
      case 'trendlines': return a.overlays.trendlines.length > 0;
      case 'channels':   return a.overlays.channels.length > 0;
      case 'triangles':  return a.overlays.triangles.length > 0;
      case 'fib':        return a.overlays.fib != null;
      case 'markers':    return a.overlays.markers.length > 0;
      case 'gaps':       return (a.overlays.gaps?.length ?? 0) > 0;
      // Most charts have neither. A cup needs a rounded base price has climbed
      // back up toward, and the extension needs a correction already reclaimed —
      // so the control appears only where there is something to draw, exactly
      // like the gap band above it. Nothing is invented to fill the checkbox.
      case 'cup':        return !!(a.overlays.cup || a.overlays.fib_ext);
      default:           return true;
    }
  }

  readonly setupColors: { [code: string]: string } = {
    above150_breakout: '#26a69a',
    bearish_to_bullish: '#66bb6a',
    below150_floor: '#ffa726',
    triangle: '#ab47bc',
    fibonacci: '#e6b800',
    ma_bounce: '#26c6da',
    rising_channel: '#42a5f5',
    descending_channel: '#5c6bc0',
    bull_flag: '#ffb74d',
    support_test: '#ef9a9a',
    resistance_retest: '#ce93d8',
  };

  constructor(private api: ApiService, private route: ActivatedRoute) {
    this.api.tickers().subscribe({ next: r => { this.tickerList = r.tickers; } });
  }

  // ── Hidden analyst-notes box ──────────────────────────────────────────────
  // The owner asked for a way to leave commentary against a specific analysis for
  // a later session to read and learn from, but explicitly did NOT want to build
  // real user accounts/permissions right now. Obscurity stands in: N rapid clicks
  // on the grade badge (an element every viewer already sees, but nothing tells
  // them to click repeatedly) reveals the box; nothing else in the UI points at
  // it. Submissions are just appended to a local, gitignored JSONL file
  // (`backend/api.py`'s `add_note`) — nothing reads them back into the grade
  // automatically, by design (see the endpoint's own comment).
  private static readonly EGG_CLICKS = 5;
  private static readonly EGG_WINDOW_MS = 1500;
  private badgeClickTimes: number[] = [];
  showNoteBox = false;
  noteText = '';
  noteSaved = false;

  onGradeBadgeClick(): void {
    const now = Date.now();
    this.badgeClickTimes = this.badgeClickTimes.filter(
      (t) => now - t < AnalyzerPageComponent.EGG_WINDOW_MS);
    this.badgeClickTimes.push(now);
    if (this.badgeClickTimes.length >= AnalyzerPageComponent.EGG_CLICKS) {
      this.badgeClickTimes = [];
      this.showNoteBox = true;
      this.noteSaved = false;
    }
  }

  closeNoteBox(): void {
    this.showNoteBox = false;
    this.noteText = '';
  }

  submitNote(): void {
    const text = this.noteText.trim();
    if (!text || !this.analysis) return;
    const m = this.analysis.micha;
    this.api.submitNote(this.ticker, text, {
      price: this.analysis.meta?.price ?? null,
      grade: m.grade, grade_score: m.grade_score, state: m.state, action: m.action,
    }).subscribe({
      next: () => {
        this.noteText = '';
        this.noteSaved = true;
        // Auto-close shortly after a confirmed save — the box is meant to be in
        // and out quickly, not a persistent panel someone has to remember to close.
        setTimeout(() => { this.showNoteBox = false; this.noteSaved = false; }, 1200);
      },
      // Left open with the text intact on failure, so a dropped request doesn't
      // silently lose what was typed.
      error: () => { this.noteSaved = false; },
    });
  }

  ngOnInit(): void {
    // `initialTicker` (embedded via quicklook) wins over the routed `?ticker=`
    // query param (the Radar page's now-unused "→ Analyzer" navigate-away path),
    // which wins over the plain-visit-to-'/' default of 'GTLB'. Whichever one
    // applies, `load()` fires exactly ONCE here — never in the constructor,
    // where `@Input`s aren't bound yet.
    if (this.initialTicker) {
      this.ticker = this.initialTicker;
    } else {
      const fromRadar = this.route.snapshot.queryParamMap.get('ticker');
      if (fromRadar) {
        this.ticker = fromRadar;
      }
    }
    this.load();
  }

  load(tk?: string): void {
    if (tk) this.ticker = tk;
    // Normalized here as well as on input, because three other paths reach this
    // without ever passing through the box: the `@Input`, the `?ticker=` query
    // param the Radar page navigates with, and `load(tk)` called directly.
    this.ticker = AnalyzerPageComponent.normalizeTicker(this.ticker);
    const t = this.ticker.trim();
    if (!t) return;
    this.loading = true;
    this.error = '';
    this.closeNoteBox();
    this.api.analyze(t).subscribe({
      next: (a) => {
        this.analysis = a;
        this.logoFailed = false;
        this.syncMichaToggles(a);
        this.loading = false;
      },
      error: (e) => {
        this.error = e?.error?.detail || `Failed to analyze ${t}`;
        this.analysis = null;
        this.loading = false;
      },
    });
  }

  setupColor(code: string): string {
    return this.setupColors[code] || '#787b86';
  }

  maContextLabel(meta: Meta): string {
    const pct = meta.sma150_dist_pct != null
      ? ` (${meta.sma150_dist_pct.toFixed(1)}%)` : '';
    switch (meta.ma_context) {
      case 'bull':       return `Above 150 & 200${pct}`;
      case 'transition': return `Above 150 · below 200${pct}`;
      case 'weak':       return `Below 150 · above 200${pct}`;
      case 'bear':       return `Below 150 & 200${pct}`;
      default:           return meta.above_150 ? `Above 150MA${pct}` : `Below 150MA${pct}`;
    }
  }

  // ── Micha verdict styling ─────────────────────────────────────────────────
  readonly michaColors: { [k in MichaState]: string } = {
    breakout_now: '#26a69a',
    buyers_at_level: '#26a69a',
    value_pullback: '#42a5f5',
    at_trigger: '#ffa726',
    // the turn is a bullish event, not a wait — coloured with the entries rather
    // than with the ambers, since it is one of the three the method enters on
    turning: '#42a5f5',
    needs_buyers: '#ffa726',
    holding: '#66bb6a',
    nothing_yet: '#787b86',
    broken: '#ef5350',
    avoid: '#ef5350',
  };

  michaColor(s: MichaState): string {
    return this.michaColors[s] || '#787b86';
  }

  readonly gradeColors: { [g: string]: string } = {
    A: '#26a69a', B: '#66bb6a', C: '#ffa726', D: '#ff7043', F: '#ef5350',
  };
  gradeColor(g: string): string {
    return this.gradeColors[g] || '#787b86';
  }

  /** Math.abs isn't reachable from an Angular template expression. */
  absVal(n: number): number {
    return Math.abs(n || 0);
  }

  /** The three ways in he names — "אפשרות 1 / אפשרות 2". */
  readonly optionLabelsHe: { [k: string]: string } = {
    now: 'כניסה עכשיו',
    breakout: 'בפריצה',
    pullback: 'בתיקון',
  };

  /** "מתקרב להכרעה" — how close the stock is to becoming relevant, independent of
   *  what it is graded today. */
  readonly alertTitleHe: { [k: string]: string } = {
    imminent: 'ממש קרובה להכרעה',
    close: 'מתקרבת להכרעה',
    near: 'מתחילה להתקרב',
  };

  /** ENTER/READY/WAIT/WATCH/AVOID, in one word — see verdict._headline_action. */
  readonly headlineHe: { [k: string]: string } = {
    ENTER: 'כניסה', READY: 'מוכנה', WAIT: 'המתנה', WATCH: 'מעקב', AVOID: 'להימנע',
  };

  /** Which reason groups are expanded. The two that carry the decision — where the
   *  stop is and what has to happen — start open; the rest are one tap away, so the
   *  panel stays short by default. */
  openReasons: { [k: string]: boolean } = { risk: true, timing: true };

  toggleReason(key: string): void {
    this.openReasons = { ...this.openReasons, [key]: !this.openReasons[key] };
  }

  countStance(group: MichaReasonGroup, stance: string): number {
    return group.items.filter((i) => i.stance === stance).length;
  }

  /**
   * The case for and against, flattened out of the grouped argument.
   *
   * The groups below stay collapsed — 24 reasons at once is not readable — but that
   * left the panel showing only "+2 −1" chips next to a letter, which says a grade
   * was computed without saying what from. He writes the summary himself when he
   * posts a setup, as a checklist:
   *   ✅ מעל ממוצע 150 · ✅ מעל קו פריצה · ✅ מעל שיאים יורדים · ✅ שפלים עולים  (DKNG)
   * so this is that list, taken from the same reasons the accordions hold. Ordered
   * by group so the strongest structural points (trend, then the level map) lead.
   */
  topReasons(a: Analysis, stance: 'for' | 'against', limit = 4): string[] {
    const out: string[] = [];
    for (const g of a.micha.reasons || []) {
      for (const it of g.items) {
        if (it.stance === stance) out.push(it.he);
        if (out.length >= limit) return out;
      }
    }
    return out;
  }

  marketCapLabel(cap: number | null): string {
    if (cap == null) return '';
    if (cap >= 1e12) return (cap / 1e12).toFixed(2) + 'T';
    if (cap >= 1e9) return (cap / 1e9).toFixed(1) + 'B';
    if (cap >= 1e6) return (cap / 1e6).toFixed(0) + 'M';
    return String(cap);
  }

  // ── Hebrew-only labels for the Micha panel (enum values from the backend) ──
  readonly trendLabelsHe: { [k: string]: string } = {
    uptrend: 'מגמה עולה', downtrend: 'מגמה יורדת', sideways: 'דשדוש',
  };
  readonly volumeLabelsHe: { [k: string]: string } = {
    rising: 'עולה', falling: 'יורד', flat: 'יציב',
  };
  /** How fast the expected gain is realistic at this stock's own volatility. */
  readonly paceLabelsHe: { [k: string]: string } = {
    fast: 'קצב מהיר', normal: 'קצב רגיל', slow: 'קצב איטי',
  };

  /** Rebuild the Micha toggle defaults from the backend's per-stock chart_focus —
   *  only the indicators relevant to THIS stock start checked. */
  private syncMichaToggles(a: Analysis): void {
    const f = a.micha.chart_focus;
    this.michaToggles = {
      sma20: f.sma20, sma50: false, sma150: f.sma150, sma200: f.sma200,
      levels: f.levels, trendlines: f.trendlines, channels: f.channels,
      // `gaps` is hard-overridden off for the same reason `markers` and `sma50`
      // are: the shaded gap boxes are large, sit behind the price action, and are
      // relevant on far fewer charts than `chart_focus` turns them on for. The
      // checkbox stays available whenever the stock HAS a gap — it just does not
      // start checked. Owner's call.
      //
      // `fib` and `cup` join them (owner's call, 2026-08-22). Both are the busiest
      // things the chart can draw — Fib puts five labelled bands across the whole
      // price range, the cup an arc plus a projection arrow — and they were the
      // last two overlays still turning themselves on. The cup was hard-ON wherever
      // one existed, on the argument that "a target you cannot see is a number the
      // reader has to take on faith"; the panel now quotes that target in percent
      // beside the grade, so the chart no longer has to carry it. Both checkboxes
      // stay available on every chart that has the overlay.
      triangles: f.triangles, fib: false, markers: false, gaps: false,
      cup: false,
    };
  }

  onMichaModeChange(): void {
    if (this.michaMode && this.analysis) {
      this.syncMichaToggles(this.analysis);
    }
  }

  onMichaToggleChange(): void {
    this.michaToggles = { ...this.michaToggles };
  }

  onKey(ev: KeyboardEvent): void {
    const ft = this.filteredTickers;
    if (ev.key === 'ArrowDown') {
      ev.preventDefault();
      this.suggestionIndex = Math.min(this.suggestionIndex + 1, ft.length - 1);
    } else if (ev.key === 'ArrowUp') {
      ev.preventDefault();
      this.suggestionIndex = Math.max(this.suggestionIndex - 1, -1);
    } else if (ev.key === 'Enter') {
      if (this.suggestionIndex >= 0 && ft[this.suggestionIndex]) {
        this.selectTicker(ft[this.suggestionIndex]);
      } else {
        this.load();
      }
      this.showSuggestions = false;
    } else if (ev.key === 'Escape') {
      this.showSuggestions = false;
    }
  }

  onToggleChange(): void {
    this.toggles = { ...this.toggles };
  }
}
