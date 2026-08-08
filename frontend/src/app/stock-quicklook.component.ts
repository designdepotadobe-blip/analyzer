import {
  Component, EventEmitter, Input, OnChanges, OnDestroy, Output, SimpleChanges,
} from '@angular/core';
import { Subject } from 'rxjs';
import { catchError, debounceTime, distinctUntilChanged, switchMap, tap } from 'rxjs/operators';
import { of } from 'rxjs';
import { ApiService } from './api.service';
import { Analysis, Toggles } from './models';

/**
 * The "take advantage of the analyzer" piece shared by Radar and Portfolio: a full
 * chart + trimmed verdict for one ticker, without navigating away and losing
 * whatever scan/wizard state the parent page is holding. Desktop hovers a card for
 * a quick trimmed glance; a CLICK — mobile tap or desktop click alike — commits to
 * the full analysis in-place. Either way this shows the SAME real
 * `ApiService.analyze()` call the Analyzer page itself makes, not just the
 * flattened `ScanHit` fields a scan row already carries.
 *
 * Deliberately NOT the full 15-section `.micha` aside (analyzer-page.component.html)
 * — that panel is heavy, deeply conditional DOM built for a dedicated page. This
 * mirrors its own existing "peek" subset instead: grade, call, read, alert band,
 * the two-sentence grade explanation, and the best entry option. A "→ ניתוח מלא"
 * button is the explicit escape hatch to the real page when more depth is wanted.
 */
@Component({
  selector: 'app-stock-quicklook',
  templateUrl: './stock-quicklook.component.html',
  styleUrls: ['./stock-quicklook.component.css'],
})
export class StockQuicklookComponent implements OnChanges, OnDestroy {
  @Input() ticker: string | null = null;
  /** Desktop hover → an anchored floating trimmed popover near the card. A click
   *  (mobile tap, or desktop click — either the card itself or the popover's own
   *  "→ ניתוח מלא") → the full-screen sheet. */
  @Input() mode: 'popover' | 'sheet' = 'popover';
  /** Popover-only: the hovered card's bounding box, used to place the popover next
   *  to it (clamped to the viewport). Ignored in sheet mode — the sheet is always
   *  docked to the bottom of the screen via CSS. */
  @Input() anchorRect: DOMRect | null = null;

  /** Fires on explicit close (✕ button, backdrop tap in sheet mode). The parent
   *  owns whether/what is being previewed — this component never hides itself. */
  @Output() closed = new EventEmitter<void>();
  /** Popover mode's "→ ניתוח מלא" button asking the parent to escalate this same
   *  ticker into the full-screen sheet — see `openFullAnalysis()` for why this has
   *  to be a request up to the parent rather than a local flag flip: `mode` is an
   *  `@Input` this component doesn't own, and the popover/sheet CSS classes are
   *  driven by it, so a local-only flag would show the full analyzer page crammed
   *  into the 400px popover box instead of actually going full-screen. */
  @Output() requestFull = new EventEmitter<void>();
  /** Mirrors native hover so the parent can keep the preview open while the mouse
   *  is over the popover itself, not just the card that opened it — without this a
   *  mouse crossing from the card into the popover would read as "left" and close
   *  it out from under the pointer. Sheet mode never emits this (nothing to merge
   *  a hover-intent timer with on touch). */
  @Output() hoverChange = new EventEmitter<boolean>();

  loading = false;
  error = '';
  analysis: Analysis | null = null;
  toggles: Toggles = {
    sma20: false, sma50: false, sma150: true, sma200: false,
    levels: true, trendlines: false, channels: false, triangles: false,
    fib: false, markers: false,
  };

  posLeft = 0;
  posTop = 0;
  private readonly POPOVER_W = 400;
  private readonly POPOVER_MAX_H = 520;

  /** True whenever `mode === 'sheet'`: the SAME full-screen sheet shows the real,
   *  complete Analyzer page — the whole `.micha` panel, every section — instead of
   *  `router.navigate`ing to '/' and destroying whatever Radar/Portfolio state the
   *  user had (scan results, wizard step). Mobile taps a card straight into sheet
   *  mode (no separate trimmed-preview step first, matching what searching a
   *  ticker on the real page gives you); desktop keeps hover's trimmed `popover`
   *  for a quick glance, but a CLICK — on the card itself, or the popover's own
   *  "→ ניתוח מלא" button (via `requestFull`) — escalates the same ticker into this
   *  same sheet rather than navigating away, so desktop gets the identical
   *  no-state-loss behavior as mobile. There is deliberately no "back to the
   *  trimmed preview" affordance from here: the only sane action once in the full
   *  sheet is `close()` — a `.ql-back` arrow that revealed the trimmed view anyway
   *  used to read as a pointless extra step before actually leaving. */
  showFullAnalysis = false;

  private readonly tickerIn$ = new Subject<string>();

  readonly gradeColors: { [g: string]: string } = {
    A: '#26a69a', B: '#66bb6a', C: '#ffa726', D: '#ff7043', F: '#ef5350',
  };
  readonly alertTitleHe: { [k: string]: string } = {
    imminent: 'ממש קרובה להכרעה', close: 'מתקרבת להכרעה', near: 'מתחילה להתקרב',
  };
  readonly optionLabelsHe: { [k: string]: string } = {
    now: 'כניסה עכשיו', breakout: 'בפריצה', pullback: 'בתיקון',
  };

  constructor(private api: ApiService) {
    // Subscribed here, not in ngOnInit: this component is always created with
    // `[ticker]` ALREADY bound (`*ngIf="previewTicker"` in the parent), so Angular
    // fires `ngOnChanges` with the initial value before `ngOnInit` ever runs. A
    // subscription set up in `ngOnInit` misses that first `tickerIn$.next()` call
    // entirely — plain `Subject`s don't replay past emissions to a late
    // subscriber — and the popover would sit on its loading skeleton forever.
    // Found via a live DOM trace showing `.ql-wrap` present but every conditional
    // child (loading/error/content) rendered as an empty `*ngIf` anchor, meaning
    // the pipeline never fired at all. The constructor always runs before any
    // lifecycle hook, so subscribing here is the fix.
    this.tickerIn$.pipe(
      debounceTime(220),
      distinctUntilChanged(),
      tap(() => { this.loading = true; this.error = ''; this.analysis = null; }),
      switchMap((tk) => this.api.analyze(tk).pipe(catchError(() => of(null)))),
    ).subscribe((a) => {
      this.loading = false;
      if (a) {
        this.analysis = a;
        this.toggles = this.buildToggles(a);
      } else {
        this.error = 'לא נמצאו נתונים עבור המניה';
      }
    });
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['mode'] || changes['ticker']) {
      // Recomputed on a `mode`-only change too, not just `ticker` — the parent
      // never destroys/recreates this component just to escalate a popover into
      // the full sheet (same ticker, `previewMode` flips from 'popover' to
      // 'sheet' on the SAME `<app-stock-quicklook>` instance), so `changes`
      // wouldn't contain `ticker` at all for that transition. Missing this meant
      // clicking a card you were already hovering silently did nothing — found
      // by testing exactly that sequence, not by inspection.
      this.showFullAnalysis = this.mode === 'sheet';
    }
    if (changes['ticker']) {
      // This component's OWN `analyze()` call (below, via `tickerIn$`) feeds only
      // the trimmed-preview block, which is `*ngIf="!showFullAnalysis"` — i.e.
      // never rendered in sheet mode. Skipping it there isn't just an optimization:
      // firing it unconditionally was a real duplicate `/api/analyze/<ticker>`
      // request on every single card click (mobile tap, or desktop click straight
      // into the sheet) alongside the embedded Analyzer page's own identical call
      // for the same ticker — found from the network panel after a user report of
      // an extra unwanted request, not by inspection.
      if (this.ticker && this.mode !== 'sheet') {
        this.tickerIn$.next(this.ticker);
      } else if (!this.ticker) {
        this.analysis = null;
        this.loading = false;
      }
    }
    if (changes['anchorRect'] || changes['mode']) {
      this.reposition();
    }
  }

  ngOnDestroy(): void {
    this.tickerIn$.complete();
  }

  gradeColor(g: string): string {
    return this.gradeColors[g] || '#787b86';
  }

  bestOption(a: Analysis) {
    const opts = a.micha.options;
    if (!opts.length) return null;
    const want: { [k: string]: string } = {
      enter: 'now', wait_trigger: 'breakout', wait_event: 'breakout',
      wait_buyers: 'breakout', wait_pullback: 'pullback', hold: 'pullback',
    };
    const wantKind = want[a.micha.action];
    if (wantKind) {
      const match = opts.find((o) => o.kind === wantKind);
      if (match) return match;
    }
    const order: { [k: string]: number } = { now: 0, breakout: 1, pullback: 2 };
    return [...opts].sort((x, y) => (order[x.kind] ?? 3) - (order[y.kind] ?? 3))[0];
  }

  close(): void {
    this.showFullAnalysis = false;
    this.closed.emit();
  }

  openFullAnalysis(): void {
    if (!this.ticker) return;
    if (this.mode === 'sheet') {
      this.showFullAnalysis = true; // already full-screen — nothing to escalate
      return;
    }
    // Popover mode: ask the parent to flip `previewMode` to 'sheet' for this same
    // ticker (see the `requestFull` doc comment for why this can't just be a local
    // flag flip) instead of navigating away and losing the scan/wizard state.
    this.requestFull.emit();
  }

  onEnter(): void {
    this.hoverChange.emit(true);
  }

  onLeave(): void {
    this.hoverChange.emit(false);
  }

  /** Mirrors `AnalyzerPageComponent.syncMichaToggles()` — the per-stock overlay
   *  choice the backend already computed (`chart_focus`), so a hover preview shows
   *  the same "only what fits this stock" chart the full page would. */
  private buildToggles(a: Analysis): Toggles {
    const f = a.micha.chart_focus;
    return {
      sma20: f.sma20, sma50: false, sma150: f.sma150, sma200: f.sma200,
      levels: f.levels, trendlines: f.trendlines, channels: f.channels,
      triangles: f.triangles, fib: f.fib, markers: false,
    };
  }

  private reposition(): void {
    if (this.mode !== 'popover' || !this.anchorRect) {
      return;
    }
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    let left = this.anchorRect.left;
    let top = this.anchorRect.bottom + 8;
    if (left + this.POPOVER_W > vw - 8) {
      left = vw - this.POPOVER_W - 8;
    }
    if (left < 8) {
      left = 8;
    }
    if (top + this.POPOVER_MAX_H > vh - 8) {
      // no room below the card — flip above it instead
      top = Math.max(8, this.anchorRect.top - this.POPOVER_MAX_H - 8);
    }
    this.posLeft = left;
    this.posTop = top;
  }
}
