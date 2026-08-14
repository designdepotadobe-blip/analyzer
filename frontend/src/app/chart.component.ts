import {
  Component,
  ElementRef,
  Input,
  OnChanges,
  OnDestroy,
  SimpleChanges,
  ViewChild,
  AfterViewInit,
} from '@angular/core';
import {
  createChart,
  IChartApi,
  ISeriesApi,
  LineStyle,
  ColorType,
  IPriceLine,
  SeriesMarker,
  Time,
} from 'lightweight-charts';
import { Analysis, LinePrimitive, Toggles } from './models';

/** One row of the on-chart key — TradingView shows exactly this: a color swatch,
 *  what the line is, and its current value, in the top-left corner of the pane
 *  itself rather than making the reader match colors against a checkbox list. */
interface LegendItem {
  color: string;
  label: string;
  value: string;
}

/** Horizontal S/R lines are white — neutral by design. They are price memory, not a
 *  directional call: the same level is a ceiling on the way up and a floor on the way
 *  back down ("חוזרת לזירת הפשע"), so colouring one red and the other teal states a
 *  bias the line itself does not carry. Strength is expressed through opacity and
 *  line style instead, leaving red/teal to mean bullish/bearish everywhere else. */
/* His own palette, read off his published charts:
 *   WHITE   — his hand-drawn horizontal S/R, and the freehand cup outlines. MMM
 *             (2026-08-09) is unambiguous: the S/R band at 174.93-177.41 is a
 *             white zone with a white label, and both cup curves are white.
 *             This is also what this file already used before I briefly changed
 *             it to yellow on a misread of the older NNE/MARA charts — the
 *             original rationale (strength via opacity and line style, leaving
 *             red/teal to mean bullish/bearish) was right and is restored.
 *   YELLOW  — kept for DIAGONALS only (trend line, channel rails, triangle), so
 *             a sloped structural line stays distinguishable from a horizontal
 *             one. NNE's rising trend line is drawn exactly this colour.
 *   CYAN    — the actionable prices: trigger, entry, target (MARA price-tags its
 *             14.69 trigger and its target above it in cyan).
 *   PINK    — the 150MA, on every chart he posts (NNE "MA 21.93", AAPL "281.12",
 *             MMM "157.67").
 *   RED     — the stop. He uses red for his measured-move arrows rather than for
 *             stops, but red already means risk everywhere else in this app and
 *             the stop is the one line that means "you are wrong". */
const LEVEL_COLOR_STRONG = '#ffffff';
const LEVEL_COLOR_WEAK = '#ffffff88';
const MICHA_YELLOW = '#ffd54f';
const MICHA_CYAN = '#22d3ee';
const MICHA_PINK = '#ff4081';

// Default zoom: enough bars to read the recent trend clearly without cramming two
// years of candles into one screen. Adapts to the container width so a phone gets
// fewer, wider candles instead of the same bar count squeezed unreadably thin.
const TARGET_BAR_PX = 7;
const MIN_VISIBLE_BARS = 45;
const MAX_VISIBLE_BARS = 220;

/**
 * Renders one Analysis TradingView-style using lightweight-charts:
 *   candlesticks + volume, the 20/50/150/200 SMAs, horizontal S/R price lines,
 *   sloped trendlines / channels / triangles (2-point line series),
 *   Fibonacci levels, and swing markers (MA bounce, gaps, pole).
 *
 * The chart is rebuilt whenever `analysis` changes; overlay visibility reacts
 * to `toggles` without a full rebuild where possible. Only a genuine TICKER
 * change resets the zoom/pan — flipping a toggle checkbox must not snap the
 * user's view back to the default, or every click feels like it breaks the chart.
 */
@Component({
  selector: 'app-chart',
  template: `
    <div class="chart-shell">
      <div #host class="chart-host"></div>
      <div class="chart-legend" *ngIf="legend.length">
        <div class="lg-row" *ngFor="let it of legend">
          <span class="lg-dot" [style.background]="it.color"></span>
          <span class="lg-label">{{ it.label }}</span>
          <span class="lg-value">{{ it.value }}</span>
        </div>
      </div>
      <!-- Phone-only: the ticker header (icon/sector/name/price/above-MA/ATR) lives
           here instead of its own row above the chart, so that row's height goes
           back to the chart. Desktop keeps the normal <header>, unchanged — this
           block is display:none until the mobile breakpoint. -->
      <div class="chart-info" *ngIf="analysis as a">
        <span class="ci-emoji">{{ a.meta.sector_icon || '📈' }}</span>
        <span class="ci-sym">{{ a.ticker }}</span>
        <span class="ci-price">{{ a.meta.price | number: '1.2-2' }}</span>
        <span
          class="ci-badge"
          [class.up]="a.meta.ma_context === 'bull'"
          [class.transition]="a.meta.ma_context === 'transition' || a.meta.ma_context === 'weak'"
          [class.down]="a.meta.ma_context === 'bear'"
        >{{ metaBadge }}</span>
        <span class="ci-atr" [ngClass]="'vol-' + a.meta.vol_tier">
          ATR {{ a.meta.atr_pct != null ? ((a.meta.atr_pct | number: '1.1-1') + '%') : (a.meta.atr | number: '1.2-2') }}
        </span>
        <span class="ci-sector" *ngIf="a.meta.sector">{{ a.meta.sector }}</span>
      </div>
    </div>
  `,
  styles: [
    `
      .chart-shell {
        position: relative;
        width: 100%;
        height: 100%;
        min-height: 0;
      }
      .chart-host {
        width: 100%;
        height: 100%;
        min-height: 0;
        /* Hands pinch/drag gestures inside the chart entirely to lightweight-charts'
           own zoom/pan handling instead of the browser's default touch behavior
           (page scroll/pinch-zoom) competing for the same gesture — see the
           viewport meta tag in index.html for the other half of this fix. */
        touch-action: none;
      }
      .chart-legend {
        position: absolute;
        top: 6px;
        left: 10px;
        z-index: 3;
        display: flex;
        flex-direction: column;
        gap: 1px;
        pointer-events: none;
        background: rgba(19, 23, 34, 0.6);
        border-radius: 5px;
        padding: 4px 8px;
        max-width: calc(100% - 90px);
      }
      .lg-row {
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 11px;
        line-height: 1.6;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      .lg-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        flex: 0 0 auto;
      }
      .lg-label {
        color: #9aa0aa;
        flex: 0 0 auto;
      }
      .lg-value {
        color: #d1d4dc;
        font-weight: 600;
        flex: 0 0 auto;
      }
      /* On a phone the color-swatch legend costs real candle width in exchange for
         info the panel already states in words (which line is which), so it's
         dropped entirely rather than shrunk — every pixel here goes to the chart. */
      @media (max-width: 768px) {
        .chart-legend {
          display: none;
        }
      }
      /* The floating ticker-info strip — desktop hides it (the normal <header>
         above the chart already shows this), phone shows it and app.component.css
         hides the <header>'s .title to reclaim that row's height. Its own colour
         rules are duplicated from app.component.css rather than shared, because
         Angular's per-component style encapsulation means that stylesheet's
         classes don't reach into this component's template. */
      .chart-info {
        display: none;
      }
      @media (max-width: 768px) {
        .chart-info {
          display: flex;
          position: absolute;
          top: 6px;
          left: 6px;
          right: 6px;
          z-index: 4;
          align-items: center;
          gap: 7px;
          flex-wrap: wrap;
          background: rgba(19, 23, 34, 0.72);
          border-radius: 6px;
          padding: 5px 8px;
          pointer-events: none;
        }
        .ci-emoji {
          font-size: 13px;
          line-height: 1;
        }
        .ci-sym {
          font-size: 12.5px;
          font-weight: 700;
          color: #fff;
        }
        .ci-price {
          font-size: 12.5px;
          font-weight: 700;
          color: #fff;
        }
        .ci-badge {
          font-size: 9.5px;
          padding: 2px 6px;
          border-radius: 4px;
          color: #9aa0aa;
          background: rgba(255, 255, 255, 0.08);
          white-space: nowrap;
        }
        .ci-badge.up { background: rgba(38, 166, 154, 0.24); color: #26a69a; }
        .ci-badge.transition { background: rgba(255, 152, 0, 0.24); color: #ff9800; }
        .ci-badge.down { background: rgba(239, 83, 80, 0.24); color: #ef5350; }
        .ci-atr {
          font-size: 10px;
          font-weight: 600;
          white-space: nowrap;
        }
        .ci-atr.vol-low { color: #26a69a; }
        .ci-atr.vol-medium { color: #9aa0aa; }
        .ci-atr.vol-high { color: #ef5350; }
        .ci-sector {
          font-size: 9.5px;
          color: #9aa0aa;
          background: rgba(255, 255, 255, 0.08);
          border-radius: 4px;
          padding: 2px 6px;
          white-space: nowrap;
        }
      }
    `,
  ],
})
export class ChartComponent implements AfterViewInit, OnChanges, OnDestroy {
  @ViewChild('host', { static: true }) host!: ElementRef<HTMLDivElement>;
  @Input() analysis: Analysis | null = null;
  @Input() toggles!: Toggles;
  @Input() michaMode = false;
  /** Key of the plan line the side panel is currently pointing at
   *  ('entry' | 'stop' | 't0' | 't1' | 't2'), or null. */
  @Input() highlight: string | null = null;
  /** The above/below-150&200 label text for the floating mobile header — computed
   *  by the parent (`AppComponent.maContextLabel`) rather than duplicated here. */
  @Input() metaBadge = '';

  private chart?: IChartApi;
  private candle?: ISeriesApi<'Candlestick'>;
  private volume?: ISeriesApi<'Histogram'>;
  private smaSeries: { [k: string]: ISeriesApi<'Line'> } = {};
  private overlaySeries: ISeriesApi<'Line'>[] = [];
  private priceLines: IPriceLine[] = [];
  /** The entry/stop/target lines, kept addressable so the panel can emphasise one
   *  without a full re-render (which would also reset zoom on a ticker change). */
  private planLines: {
    key: string; line: IPriceLine; color: string; width: 1 | 2; title: string;
  }[] = [];
  private ready = false;
  private resizeObs?: ResizeObserver;
  private lastTicker: string | null = null;

  legend: LegendItem[] = [];

  private readonly smaColors: { [k: string]: string } = {
    sma20: '#b0bec5',
    sma50: '#ffa726',
    // Pink, because that is the colour the 150 carries on every chart he posts —
    // it is the one average in his method and it reads instantly as "his" line.
    sma150: MICHA_PINK,
    sma200: '#ba68c8',
  };

  ngAfterViewInit(): void {
    this.buildChart();
    this.ready = true;
    this.render();
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (!this.ready) {
      return;
    }
    // A highlight change is a hover — repaint just that line's options rather than
    // rebuilding every series, which would be wasteful on every mouse move.
    const keys = Object.keys(changes);
    if (keys.length === 1 && keys[0] === 'highlight') {
      this.applyPlanEmphasis();
      return;
    }
    this.render();
  }

  /** Light up whichever plan line the panel is pointing at: thicken it and reveal
   *  its price-axis label. Everything else stays label-free, which is what keeps the
   *  axis from stacking Entry/Stop/T1/T2/T3 boxes on top of each other. */
  private applyPlanEmphasis(): void {
    for (const p of this.planLines) {
      const on = this.highlight === p.key;
      p.line.applyOptions({
        color: p.color,
        lineWidth: on ? 3 : p.width,
        axisLabelVisible: on,
        title: on ? p.title : '',
      });
    }
  }

  ngOnDestroy(): void {
    this.resizeObs?.disconnect();
    this.chart?.remove();
  }

  private buildChart(): void {
    this.chart = createChart(this.host.nativeElement, {
      layout: {
        background: { type: ColorType.Solid, color: '#131722' },
        textColor: '#d1d4dc',
      },
      grid: {
        vertLines: { color: '#1e222d' },
        horzLines: { color: '#1e222d' },
      },
      rightPriceScale: { borderColor: '#2a2e39' },
      timeScale: {
        borderColor: '#2a2e39',
        timeVisible: false,   // daily data — show dates only, not HH:MM
        // TradingView always leaves real breathing room past the last candle — and
        // a marker/label anchored on one of the last few bars needs room to render
        // without its text overflowing the canvas edge, which is exactly what a too-
        // tight margin did on a narrow phone screen.
        rightOffset: 14,
        barSpacing: 4,
        minBarSpacing: 0.5,
        fixLeftEdge: true,
        // `fixRightEdge:true` hard-locked panning at exactly `rightOffset` — you
        // couldn't drag any further into the empty space past the last candle. TV
        // lets you pull the chart a good deal further right than its default margin
        // (there's nothing there, but the extra slack is what makes panning feel
        // natural rather than hitting a wall). false keeps `rightOffset` as the
        // INITIAL view on a ticker switch — it just stops clamping where the user
        // can scroll to afterward.
        fixRightEdge: false,
      },
      crosshair: { mode: 1 },
      autoSize: true,
    });

    this.candle = this.chart.addCandlestickSeries({
      upColor: '#26a69a',
      downColor: '#ef5350',
      wickUpColor: '#26a69a',
      wickDownColor: '#ef5350',
      borderVisible: false,
    });

    this.volume = this.chart.addHistogramSeries({
      priceFormat: { type: 'volume' },
      priceScaleId: 'vol',
      priceLineVisible: false,
      lastValueVisible: false,
    });
    this.chart.priceScale('vol').applyOptions({
      scaleMargins: { top: 0.82, bottom: 0 },
    });

    // fallback manual resize (autoSize is best-effort)
    this.resizeObs = new ResizeObserver(() => {
      const el = this.host.nativeElement;
      this.chart?.resize(el.clientWidth, el.clientHeight);
    });
    this.resizeObs.observe(this.host.nativeElement);
  }

  /** Full redraw of everything derived from `analysis` + `toggles`. */
  private render(): void {
    if (!this.chart || !this.candle || !this.volume) {
      return;
    }
    this.clearOverlays();

    if (!this.analysis) {
      this.candle.setData([]);
      this.volume.setData([]);
      return;
    }

    const a = this.analysis;
    // The parent owns which toggle set to pass in (normal `toggles` or the
    // Micha-mode `michaToggles`, itself defaulted from the backend's per-stock
    // `chart_focus` but user-hideable) — this component just draws what it's told.
    const tg: Toggles = this.toggles;
    const isNewSeries = this.lastTicker !== a.ticker;
    this.lastTicker = a.ticker;
    const legend: LegendItem[] = [];

    // Sort bars ascending by time and remove any duplicates before handing to
    // lightweight-charts (which asserts strict ascending order).
    const sortedBars = [...a.bars]
      .sort((x, y) => (x.time < y.time ? -1 : x.time > y.time ? 1 : 0))
      .filter((b, i, arr) => i === 0 || b.time !== arr[i - 1].time);

    // ── Candles + volume ──────────────────────────────────────────────────
    this.candle.setData(
      sortedBars.map((b) => ({
        time: b.time as Time,
        open: b.open,
        high: b.high,
        low: b.low,
        close: b.close,
      }))
    );
    this.volume.setData(
      sortedBars.map((b) => ({
        time: b.time as Time,
        value: b.volume,
        color: b.close >= b.open ? 'rgba(38,166,154,0.4)' : 'rgba(239,83,80,0.4)',
      }))
    );

    // ── Moving averages ───────────────────────────────────────────────────
    for (const key of ['sma20', 'sma50', 'sma150', 'sma200']) {
      const on = (tg as any)[key] as boolean;
      const data = a.indicators[key];
      if (!on || !data || !data.length) {
        continue;
      }
      const s = this.chart.addLineSeries({
        color: this.smaColors[key],
        lineWidth: key === 'sma150' ? 2 : 1,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
      const smaData = [...data]
        .sort((x, y) => (x.time < y.time ? -1 : x.time > y.time ? 1 : 0))
        .filter((d, i, arr) => i === 0 || d.time !== arr[i - 1].time)
        .map((d) => ({ time: d.time as Time, value: d.value }));
      s.setData(smaData);
      this.smaSeries[key] = s;
      this.overlaySeries.push(s);
      const last = smaData[smaData.length - 1];
      if (last) {
        legend.push({
          color: this.smaColors[key],
          label: key.replace('sma', 'SMA '),
          value: last.value.toFixed(2),
        });
      }
    }

    // ── Horizontal S/R + broken-level price lines ─────────────────────────
    // The key levels get their own bold, cyan, labelled lines further down. A
    // trigger is usually ALSO one of the S/R levels (it is "ההתנגדות"), so
    // drawing both put a yellow structural line under the cyan decision line at
    // the same price and stacked two tags on the axis — AAPL rendered 309.29
    // twice. The decision line wins; the map keeps everything else.
    const keyPrices: number[] = (this.michaMode && a.micha?.key_levels)
      ? (a.micha.key_levels.map((k) => k.price).filter((p) => p != null) as number[])
      : [];
    const keyEps = Math.max(1e-6, (a.meta.atr || 0) * 0.05);
    const isKeyPrice = (p: number) => keyPrices.some((q) => Math.abs(q - p) <= keyEps);

    if (tg.levels) {
      for (const lvl of a.overlays.levels) {
        if (isKeyPrice(lvl.price)) { continue; }
        const strong = lvl.strength === 'strong';
        const lw: 1 | 2 = strong ? 2 : 1;
        const color = strong ? LEVEL_COLOR_STRONG : LEVEL_COLOR_WEAK;

        // Pin-bar-confirmed levels: solid regardless of strength — a real rejection
        // candle earns a firm line even on a level with few touches.
        const baseStyle = lvl.has_pin ? LineStyle.Solid
          : strong                    ? LineStyle.Solid
          :                              LineStyle.Dashed;

        // A price-axis TAG for every level — strong or barely-there — is how the
        // axis ends up a wall of stacked, overlapping boxes on a stock with six
        // marginal levels near its current price. Weak levels still draw (the line
        // itself is the useful part — "here's a floor/ceiling"); only the
        // well-tested ones, and the rare "scene of the crime" retest marker, earn a
        // tag on the axis.
        const labeled = strong || lvl.type === 'breakout';

        if (lvl.is_zone && lvl.zone_top != null && lvl.zone_bottom != null) {
          this.priceLines.push(
            this.candle.createPriceLine({
              price: lvl.zone_top, color, lineWidth: lw,
              lineStyle: LineStyle.Solid, axisLabelVisible: labeled, title: '',
            })
          );
          this.priceLines.push(
            this.candle.createPriceLine({
              price: lvl.zone_bottom, color, lineWidth: lw,
              lineStyle: LineStyle.Dashed, axisLabelVisible: false, title: '',
            })
          );
        } else {
          this.priceLines.push(
            this.candle.createPriceLine({
              price: lvl.price, color, lineWidth: lw,
              lineStyle: baseStyle, axisLabelVisible: labeled, title: '',
            })
          );
        }
      }
    }

    // ── Sloped trendlines (segments — drawn only over their own leg) ──────
    if (tg.trendlines) {
      for (const t of a.overlays.trendlines) {
        // Yellow and thick — this is "קו המגמה", the line he draws along the
        // lows/highs and the second strongest feature in his own posts.
        this.drawSloped(t, 2, LineStyle.Solid, MICHA_YELLOW);
      }
    }

    // ── Channels (parallel rails) ──────────────────────────────────────────
    // Thinner than the S/R + trendlines: a channel is secondary context (where
    // inside the range price sits), not a primary decision line, so it should not
    // compete with them for attention.
    if (tg.channels) {
      for (const c of a.overlays.channels) {
        // Same yellow family as the trend line — his channel rails are the same
        // kind of object, just two of them (MARA's descending channel, AAPL's
        // rising one).
        this.drawSloped(c.upper, 1, LineStyle.Solid, MICHA_YELLOW);
        this.drawSloped(c.lower, 1, LineStyle.Solid, MICHA_YELLOW);
      }
    }

    // ── Triangles (converging) ─────────────────────────────────────────────
    if (tg.triangles) {
      for (const tri of a.overlays.triangles) {
        // Yellow like every other structural diagonal. Left on the per-setup
        // backend colours this drew a salmon converging line a few pixels from
        // the pink 150MA on NVDA — two different objects reading as the same one.
        this.drawSloped(tri.upper, 1, LineStyle.Solid, MICHA_YELLOW);
        this.drawSloped(tri.lower, 1, LineStyle.Solid, MICHA_YELLOW);
      }
    }

    // ── Fibonacci levels (emphasise the 61.8% "golden pocket") ────────────
    // Four dotted lines is already a lot of chart; only the one he actually buys
    // (the golden pocket) earns a price-axis tag, so the retracement ladder reads
    // as a ladder instead of another stack of boxes on the axis.
    if (tg.fib && a.overlays.fib) {
      const golden = a.micha?.golden_pocket;
      for (const lv of a.overlays.fib.levels) {
        const isGolden = lv.ratio === 0.618;
        this.priceLines.push(
          this.candle.createPriceLine({
            price: lv.price,
            color: isGolden ? '#ffd54f' : '#e6b800',
            lineWidth: isGolden && golden ? 2 : 1,
            lineStyle: isGolden ? LineStyle.Solid : LineStyle.Dotted,
            axisLabelVisible: isGolden,
            title: isGolden ? '.618' : '',
          })
        );
      }
    }

    // ── Micha entry / stop / target price lines ───────────────────────────
    // Only the option the reader is actually being told to take gets drawn: three
    // entries and three stops on one chart is the clutter he deletes ("ניקיתי את כל
    // הגאפים, את הממוצעים, את הפיבונאצי, והשארתי רק קו אחד").
    if (this.michaMode && a.micha) {
      const m = a.micha;
      // must cover every action, or the lookup returns undefined and the chart
      // silently falls back to whichever option happens to be first
      const want: { [k: string]: string } = {
        enter: 'now', wait_trigger: 'breakout', wait_event: 'breakout',
        wait_buyers: 'breakout', wait_pullback: 'pullback', hold: 'pullback',
        watch: 'breakout', out: 'breakout', avoid: 'breakout',
      };
      // The plan lines carry NO price-axis label by default. Entry, Stop and up to
      // three target stations all sit in the same narrow price band, so labelling
      // every one of them stacked five boxes on the axis — and when two of them
      // land on the same price (a breakout level that is also target 1), they
      // overlap into an unreadable smear. The numbers live in the corner legend
      // and in the side panel; the axis label appears for whichever line the panel
      // is pointing at (see `applyPlanEmphasis`).
      // Prices already committed to the chart this render, so the key-level pass
      // below can skip a line that is physically already there (see its comment).
      const planPrices: number[] = [];
      const addPlanLine = (
        key: string, price: number, color: string, width: 1 | 2,
        style: LineStyle, title: string
      ) => {
        const line = this.candle!.createPriceLine({
          price, color, lineWidth: width, lineStyle: style,
          axisLabelVisible: false, title: '',
        });
        this.priceLines.push(line);
        this.planLines.push({ key, line, color, width, title });
        planPrices.push(price);
      };

      const opt = m.options.find((o) => o.kind === want[m.action]) || m.options[0];
      if (opt) {
        // Short words only — a long axis-label title ("Breakout") was getting
        // clipped against the edge of a narrow phone viewport.
        const entryTitle = opt.kind === 'now' ? 'Entry' : opt.kind === 'breakout' ? 'Break' : 'Pullback';
        addPlanLine('entry', opt.entry, MICHA_CYAN, 2, LineStyle.Dashed, entryTitle);
        legend.push({ color: MICHA_CYAN, label: entryTitle, value: opt.entry.toFixed(2) });
        if (opt.stop != null) {
          addPlanLine('stop', opt.stop, '#ef5350', 2, LineStyle.Solid, 'Stop');
          legend.push({ color: '#ef5350', label: 'Stop', value: opt.stop.toFixed(2) });
        }
      }
      // the ladder of stations, thinnest first — "3 יעדים על הגרף" (NFLX)
      for (let i = 0; i < m.targets.length; i++) {
        const t = m.targets[i];
        if (t.price == null) { continue; }
        const title = i === 0 ? 'Target' : `T${i + 1}`;
        // Cyan, like his target line on MARA — the same family as the trigger,
        // because both are prices the trade is aiming AT.
        addPlanLine(`t${i}`, t.price, i === 0 ? MICHA_CYAN : MICHA_CYAN + '88', 1,
                    LineStyle.Dotted, title);
      }

      // ── The trigger: the line the stock has to CROSS ────────────────────
      // `key_levels` (micha._key_levels) is the backend's statement of which
      // horizontals ARE the decision. The entry/stop/target lines above already
      // cover most of them, but NOT the trigger in an "enter now" state: there
      // the option's entry is spot, so the level the whole thesis turns on
      // (AAPL: 309.29, "קו הפריצה") was listed in the panel and drawn nowhere —
      // the panel naming a price the chart doesn't show is exactly the
      // never-claim-an-undrawn-line rule this codebase already fixed once.
      //
      // Deduped by PRICE, not by role: in a `wait_trigger` state the breakout
      // option's entry IS the trigger price, and drawing both stacked two lines
      // in the same pixel row.
      const EPS = Math.max(1e-6, (a.meta.atr || 0) * 0.05);
      for (const k of (m.key_levels || [])) {
        if (k.price == null) { continue; }
        if (planPrices.some((p) => Math.abs(p - k.price) <= EPS)) { continue; }
        const style = k.role === 'trigger' ? LineStyle.Dashed : LineStyle.Dotted;
        const color = k.role === 'stop' ? '#ef5350' : MICHA_CYAN;
        // Cyan for trigger / entry / target — the colour he price-tags his
        // actionable levels in (MARA: cyan 14.69 trigger, cyan target above it),
        // against the yellow he uses for structural S/R underneath.
        addPlanLine(k.role, k.price, color, 2, style, k.label);
        legend.push({ color, label: k.label, value: k.price.toFixed(2) });
      }

      // ── Unfilled gaps ──────────────────────────────────────────────────
      // Computed all along (`overlays.gaps`) and never drawn until now, even
      // though he calls them out by name constantly — "גאפ מעל הראש", "סגירת
      // הגאפ זה פלוס 7%", "אני מודע לגאפ מתחת, בגלל זה יש סטופ". Overhead a gap
      // is where the move is going; below price it is what the stop is protecting
      // against, so both edges earn a line: `near` is the edge price reaches
      // first ("פתח הגאפ"), `far` is a full fill ("סגירת הגאפ").
      //
      // Two thin lines rather than a filled box: lightweight-charts v4 has no box
      // primitive, and faking one with a translucent area series would sit under
      // the candles and fight the volume histogram for the same pixels.
      for (const g of (a.overlays.gaps || [])) {
        if (g.near == null || g.far == null) { continue; }
        const up = g.dir === 'up';
        const col = up ? '#26a69a66' : '#ef535066';
        addPlanLine('gapNear', g.near, col, 1, LineStyle.Dotted, 'Gap');
        addPlanLine('gapFar', g.far, col, 1, LineStyle.Dotted, '');
      }
    }

    // ── Markers (MA bounce / gaps / pole) ─────────────────────────────────
    if (tg.markers) {
      const markers: SeriesMarker<Time>[] = a.overlays.markers
        .map((m) => ({
          time: m.time as Time,
          position: m.position,
          color: m.color,
          shape: m.shape,
          text: m.text,
        }))
        .sort((x, y) => (x.time as string) < (y.time as string) ? -1 : 1);
      this.candle.setMarkers(markers);
    } else {
      this.candle.setMarkers([]);
    }

    this.legend = legend;
    // re-apply any active hover to the freshly created lines
    this.applyPlanEmphasis();

    // Default zoom is the RECENT window, not the full 2 years — cramming 500
    // candles into one screen made the latest price action a sliver a few pixels
    // wide, which is what actually read as "weird" (TradingView opens on a recent
    // window too, not all available history). The bar count adapts to the
    // container's pixel width so a narrow phone gets fewer, wider candles instead
    // of the same count rendered unreadably thin.
    //
    // This only runs on an actual TICKER change. Every toggle checkbox triggers a
    // full re-render (`ngOnChanges` fires on any @Input change), and resetting the
    // zoom on every one of those would silently discard whatever the user just
    // zoomed or scrolled to — the second half of what made the chart feel broken.
    if (isNewSeries) {
      if (sortedBars.length) {
        const width = this.host.nativeElement.clientWidth || 900;
        const visibleBars = Math.min(
          sortedBars.length,
          Math.max(MIN_VISIBLE_BARS, Math.min(MAX_VISIBLE_BARS, Math.round(width / TARGET_BAR_PX)))
        );
        const startIdx = sortedBars.length - visibleBars;
        this.chart.timeScale().setVisibleRange({
          from: sortedBars[startIdx].time as Time,
          to: sortedBars[sortedBars.length - 1].time as Time,
        });
      } else {
        this.chart.timeScale().fitContent();
      }
    }

    // Force the right price scale to recompute against the NEW data. Switching
    // tickers with very different price levels (e.g. ARM ~$283 → a $20 stock) can
    // leave lightweight-charts' autoscale cache stuck on the old range, squashing
    // the new candles into an unreadable sliver — re-enabling autoScale forces a
    // fresh fit every render, regardless of any prior zoom/pan/symbol-switch state.
    // Safe to do on every render (not just isNewSeries): it only affects the PRICE
    // axis, so it doesn't fight the time-axis zoom/pan preservation above.
    this.chart.priceScale('right').applyOptions({ autoScale: true });
  }

  /** Draw a 2-point sloped line (trendline / channel rail / triangle side). */
  private drawSloped(p: LinePrimitive, width: 1 | 2 | 3, style: LineStyle = LineStyle.Solid,
                     color?: string): void {
    if (!this.chart) {
      return;
    }
    const s = this.chart.addLineSeries({
      // `color` overrides the per-primitive colour the backend assigns, so the
      // diagonals can carry his yellow as a family instead of one hue per setup
      // code. Falls back to the backend colour when no override is given.
      color: color || p.color,
      lineWidth: width,
      lineStyle: style,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });
    // times must be ascending; sort by ISO date string
    const pts = [
      { time: p.p1.time as Time, value: p.p1.price },
      { time: p.p2.time as Time, value: p.p2.price },
    ].sort((a, b) => (a.time as string) < (b.time as string) ? -1 : 1);
    s.setData(pts);
    this.overlaySeries.push(s);
  }

  private clearOverlays(): void {
    if (!this.chart || !this.candle) {
      return;
    }
    for (const pl of this.priceLines) {
      this.candle.removePriceLine(pl);
    }
    this.priceLines = [];
    this.planLines = [];
    for (const s of this.overlaySeries) {
      this.chart.removeSeries(s);
    }
    this.overlaySeries = [];
    this.smaSeries = {};
  }
}
