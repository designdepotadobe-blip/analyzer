// Mirrors the JSON shape emitted by backend/analyzer.py

export interface Bar {
  time: string; // ISO date "YYYY-MM-DD"
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface Point {
  time: string;
  price: number;
}

export interface LinePrimitive {
  kind: string;
  color: string;
  label: string;
  p1: Point;
  p2: Point;
}

export interface Level {
  type: 'resistance' | 'support' | 'breakout' | 'zone';
  price: number;
  zone_top: number | null;
  zone_bottom: number | null;
  is_zone: boolean;
  strength: 'strong' | 'normal';
  freshness: 'fresh' | 'retested';
  has_pin: boolean;
  /** Was genuinely tested from BOTH sides historically — a former resistance now
   *  acting as support, or vice versa (Micha's "returning to the scene of the crime"). */
  flipped: boolean;
  dist_pct: number | null;
  dist_atr: number | null;
  touches: number;
  quality: number;
  label: string;
}

export interface Channel {
  kind: 'rising' | 'descending';
  upper: LinePrimitive;
  lower: LinePrimitive;
}

export interface Triangle {
  upper: LinePrimitive;
  lower: LinePrimitive;
}

export interface FibLevel {
  ratio: number;
  price: number;
}

export interface Fib {
  base: Point;
  peak: Point;
  levels: FibLevel[];
}

export interface Marker {
  time: string;
  position: 'aboveBar' | 'belowBar' | 'inBar';
  color: string;
  shape: 'arrowUp' | 'arrowDown' | 'circle' | 'square';
  text: string;
}

/** The cup (and its handle), with the two targets it produces.
 *
 *  His most-posted shape — 269 charted posts name a cup — and the source of the
 *  potential he quotes: "לוקחים את עומק הספל האדיר הזה, קופי-פסטה, מדביקים —
 *  פוטנציאל של 96%". `target_big` is the cup depth projected off the rim, which is
 *  his "היעד הגדול … שזה כל הקאפ הזה"; `target_small` is the handle measure, the
 *  one that comes first. Both are quoted in PERCENT because that is how he labels
 *  them on the chart (MMM's arrow reads "59.36%"). */
export interface Cup {
  rim: number;
  trough: number;
  left_time: string;
  trough_time: string;
  depth_pct: number;
  has_handle: boolean;
  /** O'Neil's stop for this pattern — under the HANDLE, never the cup low */
  handle_low: number | null;
  target_big: number;
  target_big_pct: number;
  target_small: number | null;
  target_small_pct: number | null;
  label: string;
  label_he: string;
}

/** Fibonacci EXTENSION — the target when nothing is overhead.
 *  "כדי לדעת מה הפוטנציאל למניה באול-טיים-היי, ניקח את אחד התיקונים שלה, נמתח
 *  פיבונצ'י הפוך". Measured off the largest correction price has already reclaimed;
 *  a decline not yet reclaimed is the thing in the way, not a launchpad. */
export interface FibExtension {
  top: number;
  bottom: number;
  levels: { ratio: number; price: number; pct: number }[];
}

export interface Overlays {
  levels: Level[];
  /** present only when a cup qualifies — see Cup */
  cup?: Cup | null;
  /** present only when there is a reclaimed correction to project from */
  fib_ext?: FibExtension | null;
  trendlines: LinePrimitive[];
  channels: Channel[];
  triangles: Triangle[];
  fib: Fib | null;
  markers: Marker[];
  gaps: Gap[];
  /** every swing pivot, price-tagged — the labelled turns his charts always carry */
  swings?: Swing[];
}

export interface Swing {
  time: string;
  price: number;
  kind: 'high' | 'low';
}

export interface Setup {
  code: string;
  label: string;
  detail: string;
  active: boolean;
}

export interface Meta {
  price: number;
  atr: number;
  atr_pct: number | null;
  vol_tier: 'low' | 'medium' | 'high';
  sector: string | null;
  industry: string | null;
  /** Clearbit logo CDN URL keyed by company domain; 404s for thinly-covered names —
   *  the client falls back to `sector_icon` on image error. */
  logo_url: string | null;
  /** One glyph for the sector (or a generic default for ETFs/indices with no
   *  `asset_profile`), used when there's no logo or the logo fails to load. */
  sector_icon: string | null;
  sma150: number | null;
  sma200: number | null;
  sma150_dist_pct: number | null;
  sma200_dist_pct: number | null;
  above_150: boolean;
  above_200: boolean;
  ma_context: 'bull' | 'transition' | 'weak' | 'bear';
  vol_avg: number | null;
  earnings_days: number | null;
  setup_count: number;
  setup_codes: string[];
}

/** The state machine in verdict.py — every one of his posts lands in one of these. */
export type MichaState =
  | 'breakout_now' | 'buyers_at_level' | 'value_pullback' | 'at_trigger'
  | 'needs_buyers' | 'holding' | 'nothing_yet' | 'broken' | 'avoid'
  /** bearish->bullish, all four stages of "שינוי כיוון" done including the break,
   *  while still under the 150. Before this existed the same chart was filed as
   *  `broken` or `avoid` and capped at D/F. */
  | 'turning';

/** What to actually do. `out` = the setup ended, assume the stop was hit. */
export type MichaAction =
  | 'enter' | 'wait_trigger' | 'wait_buyers' | 'wait_pullback' | 'wait_event'
  | 'hold' | 'watch' | 'out' | 'avoid';

/** The bucket a top-level button keys off — `MichaAction`'s 9 states collapsed,
 *  not a second opinion of the decision. See verdict._headline_action.
 *  `READY` is a WAIT whose own `alert` tier is already imminent/close — reuses
 *  that gate rather than a second "how close" threshold. */
export type HeadlineAction = 'ENTER' | 'READY' | 'WAIT' | 'WATCH' | 'AVOID';

/** The full pattern projection, labeled — the SAME price the REWARD axis's
 *  prize term is already scored against (`_opportunity_top`), separate from
 *  `targets[0]`/`target`, which stay the near station the ladder leads with.
 *  See verdict._macro_target. */
export interface MacroTarget {
  price: number;
  pct: number;
  label: string;
  label_he: string;
}

/** How proven the EVENT behind the grade is — see verdict._confirmation. Reuses
 *  the SAME winning event candidate the EVENT axis already scored, so this can
 *  never disagree with the grade; it is a label on an existing decision. */
export interface Confirmation {
  status: 'unconfirmed' | 'pending' | 'confirmed';
  /** Bars since the event, or null for `unconfirmed` (either nothing has
   *  happened, or the axis already aged the candidate out). */
  age: number | null;
  label: string;
  label_he: string;
}

/** One tradeable way into this chart. He routinely names two — "אפשרות 1: כניסה
 *  וסטופ מתחת לקו · אפשרות 2: לחכות לפריצה" — and each carries its OWN stop, because
 *  the breakout entry is higher but its invalidation is tighter. */
export interface MichaOption {
  kind: 'now' | 'breakout' | 'pullback';
  entry: number;
  note: string;
  note_he: string;
  stop: number | null;
  stop_what: string;
  stop_what_he: string;
  /** False when the stop is a plain ATR distance because nothing structural sits
   *  below — "סטופ לפי ATR". A structural stop is worth more. */
  stop_anchored: boolean;
  risk_pct: number | null;
  stop_atr: number | null;
  /** The wider stop for a swing position rather than a trade — "מי שמחזיק לטווח
   *  ארוך - סטופ רחב יותר" (AAPL). */
  stop_position: number | null;
  position_risk_pct: number | null;
  /** What share of the account this position can be while risking only
   *  STOP_RISK_BUDGET_PCT at the stop. A 16.8% stop is not "worse" than a 2.4% one
   *  — it is a smaller position for the same money at risk, and quoting the stop %
   *  without this makes a volatile name look untradeable. */
  size_pct_of_account: number | null;
  /** the stock's own ATR%, so stop_atr and risk_pct can be read against each other */
  atr_pct: number | null;
  /** Against the top of the ladder (the actual thesis), not the first station. */
  risk_reward: number | null;
  risk_reward_first: number | null;
  /** P(target reached before the stop) and the resulting expectancy in R, from the
   *  measured curve in config.expectancy — NOT the same number as growth.hit_rate,
   *  which ignores the stop entirely. A LOW p_win on a high-R setup is the shape of
   *  a home run, not a defect: measured, 12% at 10R (E +0.40R) beats 55% at 1R. */
  p_win: number | null;
  expectancy_r: number | null;
}

/** How well-defended the trigger price is. Only a horizontal level carries a touch
 *  history — a trendline/flag/triangle/the 150MA itself gets no wall at all, not a
 *  fabricated one. Deliberately informational: measured across ~9k breakouts and
 *  ~12k stop tests, touch count predicted neither breakout follow-through nor stop
 *  reliability, so this is shown but never added to the grade. */
export interface MichaWall {
  strength: 'strong' | 'normal' | null;
  touches: number | null;
  quality: number | null;
  flipped: boolean;
  freshness: 'fresh' | 'retested' | null;
}

/** The one price that has to be cleared — he names exactly one. */
export interface MichaTrigger {
  price: number;
  /** `cup_rim` and `base` are prices he names as the breakout that can never reach
   *  the level map — a cup rim is a single pivot (MIN_LEVEL_TOUCHES=2 excludes it)
   *  and a base top is a range edge. Without them the trigger fell through to the
   *  all-time high. Neither carries a `wall`: no touch history to report. */
  kind: 'level' | 'trendline' | 'flag' | 'triangle' | 'channel' | 'ma150' | 'ath'
      | 'cup_rim' | 'base';
  what: string;
  what_he: string;
  /** The lower edge of the same wall — the breakout is a BAND, and both of his
   *  labelled charts name it as one ("86.88 - 88.17" OKTA, "34.94 - 35.88" SMCI).
   *  The top is the price that has to give, this is where the trade is wrong. */
  floor: number | null;
  /** null unless `kind === 'level'` — see MichaWall */
  wall: MichaWall | null;
  distance_atr: number;
  distance_pct: number;
  tier: 'at_hand' | 'near' | 'moderate' | 'far';
  label: string;
  label_he: string;
}

export interface MichaTarget {
  price: number | null;
  pct: number | null;
  note: string;
  note_he: string;
  next_resistance?: number | null;
  measured_move?: number | null;
  measured_detail?: string | null;
  measured_detail_he?: string | null;
}

export interface MichaNote {
  en: string;
  he: string;
}

export interface MichaTargetStation {
  price: number;
  pct: number | null;
  label: string;
  label_he: string;
}

export interface MichaScenario {
  kind: 'bull' | 'bear';
  en: string;
  he: string;
}

/** One ✅ / ✕ line — the format he actually posts (DKNG, OKTA, TSLA, AFRM, EW). */
export interface MichaWhy {
  ok: boolean;
  en: string;
  he: string;
}

/** One line of the argument. `against` items are kept, not hidden — "what's missing"
 *  is half his read ("הבעיה היחידה היא הווליום", "עוד לא עשתה שום דבר"). */
export interface MichaReasonItem {
  stance: 'for' | 'against' | 'note';
  en: string;
  he: string;
}

/** The reasoning behind the call, grouped the way he walks a chart. Every line is
 *  computed from today's data — nothing is carried over between runs. */
export interface MichaReasonGroup {
  key: 'trend' | 'level' | 'volume' | 'pattern' | 'strength' | 'risk' | 'timing';
  label: string;
  label_he: string;
  items: MichaReasonItem[];
}

/** "מתקרב להכרעה. שימו התראה" — not a trade today, but close enough to becoming one
 *  that it belongs on the watchlist. Deliberately SEPARATE from the grade: a correct
 *  D can still sit a third of a daily range from the price that starts the argument
 *  (ONDS: "כשהיא תקפוץ אני אעלה את הסט אפ"). Measured in ATR so it means the same on
 *  a 10%-ATR miner and a 2%-ATR mega-cap, and capped in percent so a 17% move never
 *  reads as imminent just because the name is volatile. */
export interface MichaAlert {
  near: true;
  tier: 'imminent' | 'close' | 'near';
  price: number;
  what: string;
  what_he: string;
  distance_pct: number;
  distance_atr: number;
  atr_days: number;
  /** What the setup STILL needs after this trigger clears — usually the 150MA when
   *  price is under it. Keeps the alert from implying the thesis is one candle away. */
  gate: {
    price: number; what: string; what_he: string;
    distance_pct: number; distance_atr: number;
  } | null;
  label: string;
  label_he: string;
}

/** The write-up, in his shape: what to do → what the chart is → why → what kills it. */
export interface MichaReport {
  call: string;
  call_he: string;
  read: string;
  read_he: string;
  /** Present only when the call is NOT "enter" and the trigger is close — the
   *  "no trade, but watch it" line. */
  watch: string | null;
  watch_he: string | null;
  why: MichaWhy[];
  invalidation: string | null;
  invalidation_he: string | null;
  warnings: { en: string; he: string }[];
}

/** Expected gain, and how many average daily ranges it needs — the same % is a
 *  very different trade on a 9%-ATR name vs a 2%-ATR one. */
export interface MichaGrowthLeg {
  gain_pct: number;
  /** distance to this station in ATR — the unit that makes a 2%-ATR mega-cap and a
   *  10%-ATR mover comparable */
  gain_atr: number;
  /** REAL trading days, from the measured curve in config.time_to_target — not
   *  gain%/ATR%, which assumed a full average range of net progress every day and
   *  ran ~6× fast */
  days: number;
  /** how often this station is actually reached within ~6 months */
  hit_rate: number;
  pct_per_day: number | null;
}

/** Headline fields are the THESIS — the top of the ladder, the same target
 *  `risk_reward` and the grade's time term use. `hit_rate` is what keeps that
 *  honest: a far target is a real number at a stated probability, not a promise. */
export interface MichaGrowth extends MichaGrowthLeg {
  pace: 'fast' | 'normal' | 'slow';
  /** the near station on the way — the first obstacle, not the reason to trade */
  first_gain_pct: number;
  first_days: number;
  first_hit_rate: number;
  legs: MichaGrowthLeg[];
  label: string;
  label_he: string;
}

/** The level the thesis lives on — "צריכה לשמור מעל 57" (BAC), "כל עוד שומרת מעל
 *  98 אנחנו במשחק" (NOW). Sits just above the stop. */
export interface MichaHoldLevel {
  price: number;
  what: string;
  what_he: string;
  dist_pct: number;
  label: string;
  label_he: string;
}

/** One of the four stages of Micha's dictated "שינוי כיוון" sequence. */
export interface MichaDcStage {
  key: 'vol_spike' | 'reversal_candle' | 'rising_lows' | 'breakout';
  done: boolean;
  label: string;
  label_he: string;
}

export interface MichaDirectionChange {
  /** False when the stock was already healthy before — "direction change" as a
   *  concept doesn't apply to it, this is just normal continuation. */
  applicable: boolean;
  stages_done: number;
  stages_total: number;
  confirmed: boolean;
  turning: boolean;
  vol_spike_ratio: number | null;
  candle_kind: 'doji' | 'harami' | 'hammer' | null;
  rising_lows_touches: number;
  rising_lows_broke: boolean;
  label: string;
  label_he: string;
  stages: MichaDcStage[];
}

/** One axis of the grade.
 *
 *  Four now, not three. Three of them are the three clauses of his own top-grade
 *  sentence — "מעל נקודת הפריצה (event). מעל ממוצע 150 (structure). קרוב לממוצע
 *  (risk — the stop is right there). מה עוד נותר לבקש" (GEV) — and `reward` is the
 *  one his posts assume rather than state: he only posts a chart at all when he
 *  thinks it is worth something. Grading without it inverted the whole scale (a
 *  universe sweep measured the score NEGATIVELY correlated with the size of the
 *  prize); see backend config.GRADE_BUDGET for the measurement. */
export interface MichaGradeComponent {
  key: 'event' | 'reward' | 'structure' | 'risk' | 'time' | 'headroom' | 'potential';
  label: string;
  label_he: string;
  got: number;
  max: number;
  /** True for the named sub-terms — `headroom` (counted inside `structure`),
   *  `potential` and `time` (both counted inside `reward`): a signed ± adjustment
   *  ALREADY included in its axis, listed separately so the letter stays auditable.
   *  None of them is a fifth axis — do not add them to the others or the total will
   *  double-count. */
  adjustment?: boolean;
  detail?: string;
  detail_he?: string;
}

/** A ceiling that held the letter down, named so the grade explains itself. */
export interface MichaGradeCap {
  key: string;
  label: string;
  label_he: string;
  /** True when this ceiling actually MOVED the letter, rather than merely applying.
   *  The grade sentence leads with the binding one — that is literally what set the
   *  grade, whereas a cap that applied without lowering anything explains nothing. */
  bound: boolean;
}

export interface MichaGradeBreakdown {
  score: number;
  rating: number;
  rating_max: number;
  /** The same two sentences as `Micha.grade_why` — see there. */
  summary: string;
  summary_he: string;
  components: MichaGradeComponent[];
  caps: MichaGradeCap[];
}

/** "…and if it DOES break?" — a re-grade with the named trigger price assumed
 *  cleared (state forced to breakout_now, the breakout option as the plan, and
 *  when the trigger IS the 150MA, above_150 flipped true). Trend/volume/pattern/
 *  candle stay at TODAY's reading — this projects the mechanical consequence of
 *  clearing the price, not a prediction that it will. Present only when there is a
 *  trigger to project (never for broken/avoid/already-breaking-out), and it never
 *  touches the real `grade` — it is a second, clearly-labeled number, not a
 *  replacement. GILD's real case: D 51 today (below its 150MA) -> B 76 if it
 *  clears — the gap between "what it is" and "what it becomes" was invisible
 *  before this existed. Not every break is good news: AMD's real case projects to
 *  A 89 from A 91 (-2) because the breakout entry sits further from its stop. */
export interface MichaGradeIfBreak {
  grade: 'A' | 'B' | 'C' | 'D' | 'F';
  score: number;
  delta: number;
  /** the projected 1-10, and its change from today's */
  rating: number;
  rating_delta: number;
  /** True when the projected LETTER differs from today's — the case worth flagging */
  moves: boolean;
  at_price: number;
  components: MichaGradeComponent[];
  caps: MichaGradeCap[];
  /** The projected letter explained in the same two sentences as `grade_why`. */
  why: string;
  why_he: string;
  label: string;
  label_he: string;
}

/** An unfilled gap. `near` = "פתח הגאפ" (the edge nearest price), `far` = "סגירת
 *  הגאפ" (a full fill). Overhead they act as target stations; below price the box
 *  edge is a stop reference. */
export interface Gap {
  time: string;
  dir: 'up' | 'down';
  near: number;
  far: number;
  filled_pct: number | null;
}

export interface MichaChannel {
  kind: 'rising' | 'descending';
  pos_pct: number | null;
  zone: 'bottom' | 'middle' | 'top' | 'upper_rail' | 'lower';
  lower: number | null;
  upper: number | null;
}

export interface MichaChartFocus {
  sma150: boolean;
  sma200: boolean;
  sma20: boolean;
  levels: boolean;
  fib: boolean;
  trendlines: boolean;
  channels: boolean;
  triangles: boolean;
  gaps: boolean;
}

export interface MichaLevelDesc {
  price: number;
  dist_pct: number;
  dist_atr: number | null;
  touches: number;
  freshness: 'fresh' | 'retested';
  flipped: boolean;
  role_note: string;
  role_note_he: string;
}

export interface MichaLevelContext {
  resistance: MichaLevelDesc | null;
  support: MichaLevelDesc | null;
  position_pct: number | null;
  narrative: string;
  narrative_he: string;
}

export interface Micha {
  relevant: boolean;
  state: MichaState;
  state_label: string;
  state_label_he: string;
  action: MichaAction;
  action_label: string;
  action_label_he: string;
  headline_action: HeadlineAction;
  confirmation: Confirmation;
  macro_target: MacroTarget | null;
  report: MichaReport;
  reasons: MichaReasonGroup[];
  options: MichaOption[];
  trigger: MichaTrigger | null;
  alert: MichaAlert | null;
  grade: 'A' | 'B' | 'C' | 'D' | 'F';
  grade_score: number;
  /** The headline number the panel and the cards lead with: 1-10.
   *
   *  Five letters could not order a watchlist — a 246-name sweep put 85 in C and 74
   *  in B, so two thirds of the universe sat in two indistinguishable piles. This is
   *  derived from the SAME 0-100 `grade_score`, not banded separately, so it can
   *  never disagree with the letter; the letter is kept because the ceiling
   *  machinery and the scan filters are written in terms of it. */
  rating: number;
  rating_max: number;

  grade_meaning: string;
  grade_meaning_he: string;
  /** Why THIS stock earned THIS letter, in two sentences: what carries the grade,
   *  then the single thing holding it back — or his own "מה עוד נותר לבקש" when
   *  nothing does. Built in `verdict._grade_sentence` from the notes the scoring
   *  itself files, so it is guaranteed consistent with `grade_score` in a way that
   *  lifting sentences out of `reasons` (a second opinion, free to contradict the
   *  first) would not be. This REPLACES `grade_meaning_he` in the panel — that one
   *  is a single fixed string per letter and says the same thing about every B in
   *  the universe. The client renders Hebrew only; the English is for the API. */
  grade_why: string;
  grade_why_he: string;
  grade_breakdown: MichaGradeBreakdown;
  grade_if_break: MichaGradeIfBreak | null;
  trend: 'uptrend' | 'downtrend' | 'sideways';
  off_high_pct: number | null;
  fib_retracement: number | null;
  golden_pocket: boolean;
  ext20_pct: number | null;
  ext20_atr: number | null;
  stretched: boolean;
  /** his three bands, not a flag — see micha._ext20 for the posts behind each */
  extension: 'none' | 'mild' | 'stretched' | 'severe' | null;
  extension_far_150: boolean | null;
  d150_pct: number | null;
  d200_pct: number | null;
  run_days: number | null;
  run_pct: number | null;
  ran_hot: boolean | null;
  momentum_days: number;
  volume_trend: 'rising' | 'falling' | 'flat';
  volume_note: string;
  volume_note_he: string;
  market_cap: number | null;
  small_cap: boolean;
  growth: MichaGrowth | null;
  hold_level: MichaHoldLevel | null;
  direction_change: MichaDirectionChange | null;
  channel: MichaChannel | null;
  earnings_days: number | null;
  target: MichaTarget;
  targets: MichaTargetStation[];
  scenarios: MichaScenario[];
  notes: MichaNote[];
  chart_focus: MichaChartFocus;
  /** The 1-3 horizontals that ARE the decision — the line to cross and the line
   *  that must hold, named. See micha._key_levels for why the full S/R map is no
   *  longer the default drawing. */
  key_levels: MichaKeyLevel[];
  /** The ATR / 150MA / earnings status card his own charts carry, pre-coloured
   *  server-side because the thresholds are his, not presentation. */
  badges: MichaBadge[];
  level_context: MichaLevelContext;
}

export interface MichaKeyLevel {
  price: number;
  role: 'trigger' | 'entry' | 'stop' | 'target';
  label: string;
  label_he: string;
  /** His own description of the level — "אזור הפריצה 232.28-234.41". */
  what: string;
  what_he: string;
  dist_pct: number | null;
}

export interface MichaBadge {
  key: 'volatility' | 'ma150' | 'earnings';
  tone: 'good' | 'warn' | 'bad' | 'neutral';
  label: string;
  label_he: string;
  note: string;
  note_he: string;
}

export interface Analysis {
  ticker: string;
  meta: Meta;
  bars: Bar[];
  indicators: { [key: string]: { time: string; value: number }[] };
  overlays: Overlays;
  setups: Setup[];
  micha: Micha;
}

export interface ScanHit {
  ticker: string;
  price: number;
  above_150: boolean;
  sma150_dist_pct: number | null;
  market_cap: number | null;
  state: MichaState;
  action: MichaAction;
  headline_action: HeadlineAction | null;
  confirmation: Confirmation | null;
  macro_target: MacroTarget | null;
  grade: 'A' | 'B' | 'C' | 'D' | 'F';
  grade_score: number;
  /** The headline number the panel and the cards lead with: 1-10.
   *
   *  Five letters could not order a watchlist — a 246-name sweep put 85 in C and 74
   *  in B, so two thirds of the universe sat in two indistinguishable piles. This is
   *  derived from the SAME 0-100 `grade_score`, not banded separately, so it can
   *  never disagree with the letter; the letter is kept because the ceiling
   *  machinery and the scan filters are written in terms of it. */
  rating: number;
  rating_max: number;

  call_he: string;
  /** The WHY — the half of his post that isn't a price. `call_he` restates the
   *  entry and stop, which a card already prints as numbers. */
  read_he: string;
  /** Set when the name is close to its trigger — `?alerting=true&sort=alert` returns
   *  only these, nearest first. */
  alert: MichaAlert | null;
  setup_count: number;
  setups: { code: string; label: string; active: boolean }[];
  // ── everything the Radar and Portfolio pages rank on — free on this endpoint,
  // analyze() already fetched the profile/option/growth for the single-stock view.
  sector: string | null;
  sector_icon: string | null;
  atr_pct: number | null;
  /** the option the reader is actually pointed at, flattened for one-request ranking */
  entry: number | null;
  stop: number | null;
  stop_atr: number | null;
  risk_pct: number | null;
  risk_reward: number | null;
  size_pct_of_account: number | null;
  p_win: number | null;
  expectancy_r: number | null;
  option_kind: 'now' | 'breakout' | 'pullback' | null;
  gain_pct: number | null;
  gain_days: number | null;
  gain_hit_rate: number | null;
  pct_per_day: number | null;
  /** display-only — see MichaWall. Never a ranking input. */
  trigger_wall: MichaWall | null;
  /** The line the stock has to CROSS, and his name for it — the headline of
   *  almost every post he writes ("פריצה מעל 21.45$"). */
  trigger: number | null;
  trigger_what_he: string | null;
  /** The rating the trigger clearing would mechanically produce — a slim cut of
   *  `grade_if_break` (full breakdown is the single-stock view's job). See
   *  verdict._grade_if_break. */
  if_break_rating: number | null;
  if_break_moves: boolean | null;
}

export interface ScanResponse {
  scanned: number;
  matched: number;
  results: ScanHit[];
}

// Which overlay groups are visible — toggled from the UI
export interface Toggles {
  sma20: boolean;
  sma50: boolean;
  sma150: boolean;
  sma200: boolean;
  levels: boolean;
  trendlines: boolean;
  channels: boolean;
  triangles: boolean;
  fib: boolean;
  markers: boolean;
  gaps: boolean;
  /** the cup outline + its two targets, and the open-sky Fib projection */
  cup: boolean;
}
