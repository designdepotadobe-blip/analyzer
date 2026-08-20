"""
Tuning constants and shared helpers for the stock analyzer.

Every distance threshold is expressed in ATR multiples so that calm and volatile
stocks are judged on the same footing. Grouped by the subsystem that consumes them.
"""

from __future__ import annotations

import math
from typing import Optional

# ── Data / indicators ─────────────────────────────────────────────────────────
SMA_PERIODS = (20, 50, 150, 200)
ATR_PERIOD = 14

HISTORY_PERIOD = '3y'        # fetch 3 yrs so SMA150 is fully warmed up before the display window
HISTORY_INTERVAL = '1d'
DISPLAY_BARS = 504           # bars sent to the frontend (~2 trading years)
MIN_BARS = 160              # refuse to analyze anything with fewer usable bars

FETCH_CACHE_TTL = 300       # seconds to reuse a downloaded history (speeds up scans + re-analyze)

# ── Swing pivots ──────────────────────────────────────────────────────────────
PEAK_DISTANCE_BARS = 5      # min bar gap between swing pivots
SWING_PROMINENCE_ATR = 0.5  # a pivot must stand out by ≥ this many ATRs

# ── Horizontal support / resistance ───────────────────────────────────────────
# Measured against his own drawn bands, not chosen: OKTA "86.88 - 88.17" is 0.35
# ATR wide, SMCI "34.94 - 35.88" 0.43, OKE's two 0.30 and 0.23, MRNA's
# "59.37 - 59.54" 0.05. A single linkage step of 0.6 ATR was as wide as his
# WIDEST finished band, so one step could already overshoot him; 0.35 keeps a
# two-pivot cluster inside the range he actually draws.
CLUSTER_ATR_FACTOR = 0.35   # merge horizontal pivots within this many ATRs
# …but a cluster may never grow WIDER than this in total. Clustering is single-linkage
# (each pivot is compared to the last one admitted), so without a span cap a run of
# pivots each 0.59 ATR apart chains into one "level" of unlimited width: GTLB carried
# a level whose zone ran 28.33-37.83, i.e. 4.86 ATR, swallowing every real wall in
# between. Since `_edge()` quotes `zone_top` as the breakout price, a bloated zone
# both hides nearer resistance and overshoots the line. His own drawn bands measure
# 0.1 ATR (CRWD "553.93 - 555.81") to 0.6 ATR (GTLB "32.99 - 33.97").
#
# 1.0 was called "a generous ceiling"; measured over 404 of his posts run as of the
# day he posted, it was the binding constraint far too often — our bands came out a
# median 1.34 ATR wide against the 0.23-0.43 ATR of his four labelled ones. Since
# the stop is anchored under the band, a band 4x too wide is a stop 4x too wide,
# which is most of why our stop sat 1.50 ATR under the trigger where his sits 0.43.
# 0.6 is his measured MAXIMUM, so this is still a ceiling and not a target.
LEVEL_MAX_SPAN_ATR = 0.6
LEVEL_NEAR_ATR = 4          # only show levels within this many ATRs of price
LEVEL_STRONG_TOUCHES = 4    # always show levels with this many touches, even if far away
LEVEL_MAX_SHOW = 2          # max levels shown per side (resistance / support)
LEVEL_NEAR_BUCKET_ATR = 2.0  # levels this close sort ahead of everything else
MIN_LEVEL_TOUCHES = 2

SR_MERGE_ATR = 0.35         # merge a R+S pair into a zone if they are within this many ATRs
SR_KEEP_TOUCHES = 4         # but keep both lines if EITHER has this many touches (well-tested)
# …except when they are the SAME line. A price that clustered as both resistance and
# support is a flipped level, and a flipped level is the single thing he draws with
# most conviction — as ONE band. Keeping both because it is well-tested drew it
# twice: measured over 404 posts, 90% of charts carried a byte-identical duplicate
# and 31% of all horizontals were a redraw of a line already on the chart. That is
# most of the "too many S/R levels" complaint, and none of it was information.
SR_SAME_LINE_ATR = 0.15     # closer than this ⇒ one wall, merge whatever the touch count

ZONE_MIN_SPREAD_ATR = 0.18  # min cluster spread (ATRs) to draw as a two-line zone instead of one line
CONSOL_MIN_BARS = 8         # min consecutive bars to qualify as a consolidation zone
CONSOL_MAX_RANGE = 1.5      # max range of a consolidation (ATR multiples)
ABSORPTION_PCT = 0.65       # if this fraction of recent bars closed "through" a level → absorbed
BREAKOUT_LOOKFORWARD = 20   # bars ahead to score a historical breakout

# ── Trend geometry ────────────────────────────────────────────────────────────
NEAR_ATR = 0.7              # "close to a level" tolerance, in ATRs
EXTENDED_ATR = 2.0          # > this many ATRs above a broken level ⇒ extended
MIN_TREND_SLOPE_PCT = 0.03  # min |slope| (% of price per bar) to call a line "sloped"

# `_trend()`'s recent-window override. A pure full-window regression reads a
# severe-decline-then-strong-recovery chart as 'sideways' no matter how strong
# the recovery leg is — a straight line through a V is close to flat. MRNA:
# -73% then +150% off the low over the ~2yr display window reads 'sideways'
# under the full-window fit alone, even 8 months into a real uptrend. A clear
# recent read (its own two-sided pivot slope, past the same 0.02 threshold)
# now overrides the full-window one; an AMBIGUOUS recent read (too few pivots,
# or genuinely flat lately) still falls back to it — so the 2-year picture
# still governs whenever the last year hasn't made up its mind either way.
# Same window Fibonacci already uses for its rally base search (RALLY_LOOKBACK_
# BARS, defined below) — "how far back counts as the current story" is the same
# question there. Not a direct reference: that constant is defined later in this
# file and Python would raise NameError importing top-to-bottom.
TREND_RECENT_BARS = 252

# ── Micha-style segment trendlines / channels ─────────────────────────────────
# Micha's lines are pivot-snapped segments ("snap it with magnets — high to high to
# high, four, five highs"), anchored at the extreme of the CURRENT leg, and only
# drawn when today's price is actually interacting with them.
TL_TOUCH_TOL_ATR = 0.5      # within this many ATRs of the line counts as a touch
TL_MIN_TOUCHES = 3          # 2 pivots define a line, the 3rd makes it real
TL_MIN_SPAN_BARS = 15       # a line spanning less than this is noise, not a trend
TL_MAX_VIOLATION_BARS = 10  # older crossings invalidate the line; newer = a breakout
TL_RELEVANT_ATR = 3.0       # keep a line only if it passes this close to today's price
TRI_RELEVANT_ATR = 6.0      # triangle: BOTH lines must be this close to price (near apex)
CH_MIN_RAIL_TOUCHES = 2     # the parallel rail needs this many touches of its own
CH_MIN_WIDTH_ATR = 1.5      # rails closer than this are noise, not a channel

BULLFLAG_POLE_GAIN = 0.18   # pole must rise ≥ 18%
BULLFLAG_POLE_BARS = 35     # ...within this many bars
BULLFLAG_FLAG_BARS = 25     # flag/consolidation length

FIB_MIN_RISE_PCT = 0.15     # a "nice rise" is ≥ 15%
FIB_ZONE = (0.45, 0.66)     # current retracement inside this band ⇒ ripe (0.5–0.618)
# Micha measures the retracement of the RECENT rally, not an ancient IPO low. Bounding
# the base search to ~1 trading year before the peak makes the % match what he draws.
RALLY_LOOKBACK_BARS = 252

BOUNCE_LOOKBACK = 15        # bars to look back for an MA bounce
GAP_LOOKBACK = 60           # bars to look back for unfilled gaps

# ── Volatility + volume ───────────────────────────────────────────────────────
# Calibrated against Micha's actual watermark circles: PM 2.67%=🟢, NVDA 3.46%=🟡,
# LMND 6.5%=🔴, WGMI 9.2%=🔴 → green < 3, yellow 3-5, red ≥ 5.
ATR_PCT_LOW = 3.0           # ATR/price %: below this → calm volatility (green)
ATR_PCT_HIGH = 5.0          # ATR/price %: above this → high volatility (red)
VOL_SPIKE_FACTOR = 1.5      # breakout bar volume must be ≥ this × avg to be confirmed
VOL_AVG_PERIOD = 20         # bars used to compute average volume baseline
VOL_BREAKOUT_LOOKBACK = 60  # bars to scan for vol-confirmed resistance breakouts
# `breakout_markers()` above scans a full 60-bar (~3 month) window so the CHART can
# still show an old breakout arrow. But the verdict engine's "broke resistance —
# enter here" framing means something happening NOW — reading any marker in that
# whole 60-bar window as "currently broke out" let a 2-month-old event drive an
# "enter now" call today, long after the actual trigger. Bound to the same recency
# window the direction-change sequence itself uses.
BREAKOUT_FRESH_BARS = 15

# ── Micha-method thresholds (learned from his daily videos) ───────────────────
# "The 20 method" — distance from the 20MA is his overextension gauge. Once price
# runs too far above the 20MA ("too hard, too fast") he expects a snap-back and
# refuses to chase — he waits for the pullback / capitulation instead.
EXT20_STRETCHED_ATR = 4.0   # > this many ATRs above the 20MA ⇒ parabolic / don't chase
# …and the band below it, which he names separately and treats differently: "מתוחה
# קצת מהממוצע. אם השוק אוהב את הדיווח - אתם לא מאחרים" (AAPL — a caveat, not a veto),
# "כרגע קצת מתוחה אז זהירות עם הכניסה" (LUNR). Between here and STRETCHED it costs a
# little and says so; above STRETCHED it caps the letter.
EXT20_MILD_ATR = 2.5
GOLDEN_POCKET = (0.60, 0.68)  # the 61.8–66% "golden pocket" Fib zone — his premium value entry
MOMENTUM_RUN_DAYS = 5       # this many consecutive up-closes ⇒ a momentum run (getting extended)
CAPITULATION_VOL = 1.8      # a wash-out bar's volume vs the 20-day average
LONG_BASE_BARS = 25         # a consolidation this long is a "pressure-relief" base (bullish coil)
MIN_MARKET_CAP = 1_000_000_000  # Micha screens out sub-$1B names for the 150 method
ROUND_NEAR_ATR = 0.6        # a round number this close to price is a psychological level
EARNINGS_SOON_DAYS = 5      # earnings within this many days → defer new entries
STATION_MERGE_ATR = 0.6     # target "stations" closer than this merge into one
MAX_TARGET_STATIONS = 3     # the ladder Micha shows: next station → next → ATH

# ── How long a target actually takes, and how often it is reached ─────────────
# ATR is the right UNIT for distance ("כל יומיים כאלה זה יכול להיות 16%") but it is a
# RANGE measure, not net drift — the same trap already documented for the alert at
# ALERT_MAX_PCT. The old model read `days = gain% / ATR%`, i.e. one full average
# range of NET progress every single day, and produced "ONDS +20% ≈ 2.4 days" and
# "MSTR +30% ≈ 4.2 days, fast" on a stock graded F/"get out".
#
# Measured instead: 69 tickers × 5y daily, every bar with close > SMA150 (the
# method's own entry anchor), target set k×ATR above the close, first touch of the
# high within a 120-day horizon. n ≈ 690 ticker/k cells.
#   k(ATR)  1     2     3     4     6     8     12    16    20    25
#   days    4    12    20    28    42    52    66    78    82    83
#   hit%   91    83    75    68    54    42    27    17    12     7
# Reality is ~6-7× slower than the old model through the tradeable range (k≤8).
# The curve is close to the random-walk result (days ≈ 2k²) up to k≈4, then bends
# under survivorship: past k≈8 only the fast movers ever arrive inside the horizon,
# so `days` there is "when it works", which is why HIT_RATE must be shown with it.
TIME_TO_TARGET_K    = (1,   2,   3,   4,   6,   8,   12,  16,  20,  25)
TIME_TO_TARGET_DAYS = (4,   12,  20,  28,  42,  52,  66,  78,  82,  83)
TIME_TO_TARGET_HIT  = (.91, .83, .75, .68, .54, .42, .27, .17, .12, .07)
# Volatility tilts it slightly — a hot name covers the same ATR distance a little
# faster (k=4: calm 32d / mid 28d / hot 26d). Real, but small: keep it bounded so a
# volatile name can never look like a different asset class.
TIME_VOL_PIVOT_ATR_PCT = 3.5
TIME_VOL_SLOPE = 0.03
TIME_VOL_CLAMP = (0.88, 1.12)
# Pace bands, in REAL trading days (the old 5/12 thresholds were on the 6×-fast scale)
PACE_FAST_DAYS = 15
PACE_NORMAL_DAYS = 40
# How much the grade may move on time-to-target. Swing trading has two objectives —
# earn, and do not sit in it for a year — and the grade only ever scored the first.
# Two setups with identical structure and identical R/R are NOT equally good if one
# reaches its first station in 12 days and the other in 60.
#
# Deliberately small, and deliberately NOT a reward for raw volatility. High ATR
# earns more percent per day AND risks more percent per trade; measured, the two
# cancel to roughly a wash on a risk-adjusted basis (that is why the stop is judged
# in ATR, see STOP_WIDE_ATR). Paying points for ATR itself would be paying for risk.
# What is paid for here is DISTANCE TO THE FIRST TARGET IN ATR, which is what
# actually sets both the wait and the odds — and which R/R alone reads backwards,
# since a nearer target lowers R/R. The pair together say: tight stop, reachable
# target. That is the method's ideal, and neither term expresses it alone.
#
# Scored against the THESIS target (the top of the ladder — the same one `risk_reward`
# is measured to), not the first station: the first station is by construction the
# next nearby level, ~1 ATR out for every name, so it carries no information and
# scored full marks for every stock tested. Bands are the measured quantiles of
# days-to-thesis across 150 universe names (p25 14d / p50 25d / p90 56d), pivoting
# at the median so the term is a true ± around typical rather than a free bonus.
# Sanity checks on that sample: corr(days, ATR%) = -0.34 — volatile names do reach
# their thesis sooner, which is the effect being paid for, but far from a proxy for
# ATR itself; and corr(days, current grade) = +0.25, i.e. the grade today mildly
# FAVOURS slower theses, so this term corrects an existing tilt rather than
# amplifying one.
TIME_EFFICIENCY_MAX = 4.0      # ± points, out of a 100-point grade
TIME_FAST_DAYS = 14.0          # p25 — full bonus at/under
TIME_MEDIAN_DAYS = 25.0        # p50 — neutral
TIME_SLOW_DAYS = 56.0          # p90 — full penalty at/over

# ── Expectancy: what a setup is actually worth ───────────────────────────────
# `growth.hit_rate` answers "is the target reached inside 6 months" and IGNORES the
# stop, so it cannot rank a home-run setup against a safe one. This is the number
# that can: P(target touched BEFORE the stop), measured, and the expectancy in R
# that falls out of it.
#
# Measured: 60 tickers × 5y, every bar with close > SMA150, stop j ATR below entry,
# target j*R above, walked forward 120 days, first touch wins, same-bar ties given
# to the STOP. n = 39,589 per cell. P(win) by (stop ATR, R multiple):
#             R=1     1.5     2       3       4       5       7      10
#   stop 1.0  52.7%  43.6%  37.3%  28.9%  24.0%  20.8%  16.6%  12.4%
#   stop 1.5  53.8%  44.3%  37.9%  29.9%  25.2%  21.7%  16.0%  10.2%
#   stop 2.0  54.6%  45.1%  38.8%  31.0%  25.2%  20.6%  13.7%   7.5%
#   stop 2.5  55.0%  45.7%  39.9%  30.8%  23.8%  18.5%  11.0%   5.2%
#   stop 3.0  55.6%  46.7%  40.4%  29.2%  21.8%  15.8%   8.6%   3.7%
#
# The finding that matters: expectancy peaks at a HIGHER R the TIGHTER the stop —
# 1.0 ATR/10R = +0.40R, 2.0 ATR/5R = +0.32R, 3.0 ATR/3R = +0.29R. Tight stop plus
# far target is the highest-expectancy shape there is, at a ~12% win rate. That is
# "prefer home runs while minimising entry risk" stated in numbers, and it is why
# the grade's old `rr >= 3` ceiling had to go: it could not see the best zone.
# The mirror-image trap is real too — a WIDE stop with a far target times out 35% of
# the time and turns negative (3.0 ATR/10R = -0.25R): capital stuck, thesis unpaid.
#
# Caveat kept deliberately: this is the baseline edge of "above the 150" with NO
# setup-quality filter, so it is a floor the app's own setups should beat, not a
# claim about them. Re-run the study rather than hand-editing these knots.
EXPECTANCY_STOPS = (1.0, 1.5, 2.0, 2.5, 3.0)
EXPECTANCY_RS = (1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 7.0, 10.0)
EXPECTANCY_PWIN = (
    (.527, .436, .373, .289, .240, .208, .166, .124),   # stop 1.0 ATR
    (.538, .443, .379, .299, .252, .217, .160, .102),   # stop 1.5
    (.546, .451, .388, .310, .252, .206, .137, .075),   # stop 2.0
    (.550, .457, .399, .308, .238, .185, .110, .052),   # stop 2.5
    (.556, .467, .404, .292, .218, .158, .086, .037),   # stop 3.0
)


def _interp(x, xs, ys):
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    i = next(j for j in range(1, len(xs)) if xs[j] >= x)
    t = (x - xs[i - 1]) / (xs[i] - xs[i - 1])
    return ys[i - 1] + t * (ys[i] - ys[i - 1])


def expectancy(stop_atr: float | None, rr: float | None) -> tuple:
    """
    (P(target before stop), expectancy in R) for a setup with this stop width and
    this reward-to-risk. Bilinear over the measured grid above.

    E = p*R - (1-p), i.e. win R, lose 1 — the honest way to compare a 12%/10R
    home run against a 55%/1R scalp, which raw R/R and raw win-rate each get wrong
    on their own.
    """
    if stop_atr is None or rr is None or stop_atr <= 0 or rr <= 0:
        return None, None
    rows = [_interp(rr, EXPECTANCY_RS, row) for row in EXPECTANCY_PWIN]
    p = _interp(stop_atr, EXPECTANCY_STOPS, rows)
    p = min(max(p, 0.0), 1.0)
    return round(p, 4), round(p * rr - (1 - p), 4)


def time_to_target(gain_atr: float, atr_pct: float | None = None) -> tuple:
    """
    (median trading days, probability of getting there within ~6 months) for a move
    of `gain_atr` ATRs, from the table above. Linear interpolation between the
    measured knots; flat outside them.
    """
    k = max(0.0, float(gain_atr))
    ks, ds, hs = TIME_TO_TARGET_K, TIME_TO_TARGET_DAYS, TIME_TO_TARGET_HIT
    if k <= ks[0]:
        # below the smallest measured knot, scale the first cell down linearly —
        # a fifth of an ATR is not four days away
        f = k / ks[0]
        days, hit = ds[0] * max(f, 0.25), min(0.97, hs[0] + (1 - hs[0]) * (1 - f))
    elif k >= ks[-1]:
        days, hit = ds[-1], hs[-1]
    else:
        i = next(j for j in range(1, len(ks)) if ks[j] >= k)
        t = (k - ks[i - 1]) / (ks[i] - ks[i - 1])
        days = ds[i - 1] + t * (ds[i] - ds[i - 1])
        hit = hs[i - 1] + t * (hs[i] - hs[i - 1])
    if atr_pct:
        adj = 1.0 - TIME_VOL_SLOPE * (float(atr_pct) - TIME_VOL_PIVOT_ATR_PCT)
        days *= min(max(adj, TIME_VOL_CLAMP[0]), TIME_VOL_CLAMP[1])
    return round(days, 1), round(hit, 3)

# ── "שינוי כיוון" — the direction-change sequence ──────────────────────────────
# From the IGV community live, where he stops and dictates the checklist outright:
# "you'll now have three or four things you look at, and for every stock you'll know
# whether it meets the criterion or not". He is explicit that this is read on the
# WEEKLY candle ("שבועי. אני מדבר איתכם כרגע על שבועי") and that the two things that
# can't be faked are price and volume. The four stages, in his order:
#   1. ווליום ספייק  — "was there a volume SPIKE? a spike is not a rise of 0.1. If
#      there was no volume increase, the stock simply didn't interest anyone."
#   2. נר שינוי כיוון — a direction-change candle: a doji ("it will NOT necessarily
#      be green — sometimes it's red, and it's still a doji to me"), or a bullish
#      harami / inside candle "whose whole body sits in the middle".
#   3. שפלים עולים   — rising lows, connectable by a line: "that gives you greater
#      confidence" (IGV 79.27 → 79.71).
#   4. פריצה          — "the last stage, no less important: wait for a clear point
#      that says we have CONTINUITY, meaning a breakout" — of resistance ABOVE
#      price, "אף פעם לא מתחתיי" (never below me). This is his condition for
#      actually taking the trade; stages 1-3 only make it interesting.
DC_WEEKLY_BARS = 5          # daily bars aggregated into one weekly candle
DC_LOOKBACK_WEEKS = 14      # weekly window the sequence is read over
DC_VOL_SPIKE = 1.35         # weekly volume ≥ this × the weekly average ⇒ a real "spike"
DC_DOJI_BODY = 0.34         # |close-open| ≤ this × the week's range ⇒ a doji (red counts)
DC_RECENT_WEEKS = 3         # stages 1-2 must have happened within this many weeks

# ── The judgement layer (verdict.py) ──────────────────────────────────────────
# The three axes of the grade come straight from the shape of his own A-grade
# sentence, which always has exactly three clauses: "מעל נקודת הפריצה (trigger).
# מעל ממוצע 150 (setup). קרוב לממוצע (risk — the stop is right there). מה עוד נותר
# לבקש" (GEV). Risk carries as much weight as structure because what separates an
# excellent setup from a merely good one, in every post he writes, is that the
# invalidation sits close enough to be obvious.
# ── Headroom: how much room the trade has before the next hard wall ───────────
# PROVENANCE, stated plainly because everything else in this file carries a
# measurement and this does not: these numbers are REASONED FROM THE METHOD, not
# fitted to an outcome. "Room above" is one of the six features that separate his
# praise from his warnings (+7.4 lift, eee7b7a), and he states it constantly —
# "יש לה מקום לרוץ", "הבעיה זה ההתנגדויות מעל הראש" (CRWD). The owner asked for it
# explicitly and will validate it by hand against past charts. Until that happens
# these are a considered default, not a result. DO NOT cite them as measured.
#
# An attempt WAS made to measure this (2,591 as-of observations, 72 tickers,
# 2024-06..2026-07, forward 20-day return). It failed its own control: the
# existing grade did not reproduce its known A +4.88% → F -5.06% separation on
# that sample (it came out flat, C best), so the sample could not certify any
# term. Room looked cleanly monotone on RAW return and went to noise once SPY was
# subtracted — it was beta, not skill. The likely reason the sample is unfit: it
# is a mechanical grid over large caps every 15 bars, whereas the grade is built
# to rank the setups he actually posts about. Redo it against the Discord corpus
# (discord_harvest.py) before treating any of this as validated.
#
# This is NOT the "overhead congestion" penalty that was built, measured and
# removed at verdict.py's `_grade` (see the NOTE there). That one counted the
# WALLS BETWEEN entry and thesis, which charges a stock for having a target
# ladder at all — it took TEAM from A90 to B83 while F escaped. This counts the
# DISTANCE TO THE FIRST hard wall only. A healthy three-station ladder keeps its
# grade as long as station one is not sitting on top of the entry; the count of
# stations above it is deliberately never read.
# Kept deliberately SMALL. A wall overhead changes what you should DO far more than
# it changes how good the chart is: a well-built base with a hard wall 0.4 ATR above
# is still a well-built base, and grading it down to F would say the structure is
# bad when the structure is fine and only the timing is wrong. So the letter moves
# by about one band at most, and the whole weight of "not yet" is carried by the
# ACTION instead — `_state` routes these to `at_trigger`, i.e. his own "פריצה מעל X /
# להמתין לפריצה", rather than "enter". Owner's instruction, and it matches how he
# writes: he keeps praising the chart and still says wait.
HEADROOM_MAX = 4.0           # bounded ±, same size as the time adjustment. Never an axis.
# Calibrated against where the THESIS sits, which is the only thing that makes a
# distance mean anything: the target-odds measurement in `_grade` puts a reachable
# thesis at 4-6 ATR (72.7% hit) and the ladder's own stations run 2-6 ATR out. So a
# hard wall 1.5 ATR above the entry is not "room", it is the ceiling on most of the
# move — the first bands were set a full ATR too low and scored TXN's 10-touch wall
# at 1.49 ATR as neutral while the chart graded A 92.
HEADROOM_TIGHT_ATR = 0.75    # a hard wall this close ⇒ the move has nowhere to go
HEADROOM_CLOSE_ATR = 1.5     # still cramped — most of the thesis sits behind it
HEADROOM_OK_ATR = 2.5        # neutral above this
HEADROOM_CLEAR_ATR = 4.0     # real room to run; at/above this, or blue sky, pays full
# Only a WELL-DEFENDED level counts as a ceiling. A 2-touch high is not what he
# means by "התנגדות מעל הראש" — he names walls the price has been rejected from
# repeatedly. Weak levels still draw on the chart; they just do not close the road.
# Used ONLY for the break-bonus below (was a "here is our own definition of a
# real wall" the moment a wall was BROKEN, but the moment a wall is still AHEAD
# `_headroom()` now defers to res_levels' own MIN_LEVEL_TOUCHES bar instead — see
# its docstring for why keeping two thresholds was the AMAT bug).
HEADROOM_HARD_TOUCHES = 4    # matches LEVEL_STRONG_TOUCHES — a well-tested break
# Breaking a hard wall is the event his whole method is organised around
# ("פריצה משמעותית מעל"), and breaking a 2-touch high is not the same event.
# Paid on the setup axis, small, and only while the break is still fresh.
BREAK_HARD_BONUS = 4.0
BREAK_SOFT_BONUS = 1.5

# ── Potential: how big is the move if the thesis plays out ────────────────────
# Owner's explicit directive (2026-08-19), stated as the top-priority correction
# to this grade: a stock still far below its own highs, breaking out with a huge
# ladder ahead (MRNA: target reaches ~29 ATR / +167%) sat at a bare C, while a
# mature name a few percent from its all-time high with nowhere structurally
# left to run (GILD: target reaches ~2-4 ATR / +10% — its only target IS the
# ATH, since there is no resistance above one by definition) sat at A. HEADROOM
# already answers "is the row directly ahead clear" and correctly gave GILD full
# marks there; it does not answer "how big is the room past that", which is the
# separate question this pays for.
#
# PROVENANCE: reasoned from the directive above, not measured. A related idea
# (room to the first wall) was put through an actual forward-return study the
# same day and failed its own control — see HEADROOM_MAX. This is a different
# claim (size of the prize, not odds of collecting it soon) and the owner has
# directed it be scored regardless of that earlier result. Flagged exactly as
# HEADROOM_MAX was, so a future pass knows this rests on a directive, not a
# validated edge.
#
# Bucketed against the SAME quantile bands the time-adjustment's own 62k-level
# study already established (target-odds: 4-6 ATR reached 72.7% of the time,
# 6-9 ATR 53.0%, 9-13 ATR 24.8%, 13-20 ATR 6.2%) so this only pays once a target
# is BIGGER than what "normal and likely" already covers — the time term already
# pays for an ordinary one.
POTENTIAL_MAX = 10.0         # the full bonus, folded into `setup` — see HEADROOM_MAX
                              # for why this lives inside setup rather than as a 4th axis
POTENTIAL_REAL_ATR = 9.0     # beyond the 6-9 ATR band (53% hit) — a genuinely bigger prize
POTENTIAL_BIG_ATR = 13.0     # beyond the 9-13 ATR band (24.8% hit) — most targets never get here
POTENTIAL_HUGE_ATR = 20.0    # beyond the worst-odds band (13-20 ATR, 6.2%) — exceptional
# ATR-normalizing avoids rewarding raw VOLATILITY (the reason nothing else in
# this file scores in raw %) — but it breaks the other way for a stock calm
# enough that ATR itself is tiny. AES, ATR% 0.36 (a utility, the calmest name
# found in a 200-name sweep): an entirely ORDINARY +18% target landed 54 ATR
# out purely because the denominator is minuscule, earning the identical
# max bonus as MRNA's genuine +167%/29-ATR case. Every other name that earned
# a bonus in that sweep sat at 1.5-4% ATR; only the sub-1.5% names were the
# artifact. Below this floor, distance-in-ATR stops meaning "a big structural
# move" and starts meaning "the denominator collapsed" — gate potential on it
# rather than trying to tune a raw-%-gain floor that cannot cleanly separate a
# genuine case (FRT, ATR% 1.56, +22%) from the artifact (AES, +20%) since
# their raw gains sit a percentage point apart.
POTENTIAL_MIN_ATR_PCT = 1.5

# The raw-percent alternative path (OR'd with the ATR bands above, in `_grade`'s
# POTENTIAL block — whichever is more generous wins). Guards the mirror-image
# case to AES above: a genuinely volatile name's genuinely large move gets
# UNDER-credited by ATR-normalizing it, not over-credited. LRCX (measured
# 2026-08-20): +43% to its own ATH, the largest raw prize among that day's
# A-grades, at 7.15% ATR converts to only ~6 ATR — never reaches
# POTENTIAL_REAL_ATR (9). A 30%+/45%+/70%+ move to the farthest real target is a
# big prize on any stock regardless of how it happens to trade day to day.
# PROVENANCE: reasoned from the LRCX case, not measured — same status as the ATR
# bands themselves.
POTENTIAL_REAL_PCT = 30.0
POTENTIAL_BIG_PCT = 45.0
POTENTIAL_HUGE_PCT = 70.0

# What the trigger axis may pay in an ENTERING state when the engine has ALSO named
# a price overhead — i.e. it says "the trigger is happening right now" while its own
# `trigger` dict points at a wall that has not given yet. Both cannot be true, and
# the axis used to pay the full 30 regardless: measured, 42 of 42 entering states had
# an unbroken named trigger overhead while collecting full marks, and in 22 of them
# the FIRST target was that same wall. TXN is the case the owner caught — broke a
# level 0.05 ATR under spot, graded A 92 with a 10-touch wall 6.1% overhead.
#
# `at_hand` is NOT reduced: inside 1 ATR the break genuinely is in progress. Beyond
# that the decisive line is still ahead and the axis says so.
TRIGGER_ENTERING_OVERHEAD = {'near': 22.0, 'moderate': 15.0, 'far': 10.0}

# The mirror case TRIGGER_ENTERING_OVERHEAD does not cover: no NAMED wall stands
# in the way (`over` is False — nothing to quote a price/touch-count for), but
# there also isn't much of a thesis to collect once the break is bought — FOXA's
# breakout had no further identified wall AND its farthest target was +9.4%, yet
# still paid the full 30/30 "happening right now" because the reduction only
# ever fired off a NAMED obstacle. Owner's directive (2026-08-20): full trigger
# marks should require both the way being clear AND there being somewhere worth
# going. Gated on the SAME `potential` the setup axis computes (zero whenever the
# thesis never reaches POTENTIAL_REAL_ATR) so the two axes can't disagree about
# what "a real prize" means. Set near TRIGGER_ENTERING_OVERHEAD['near'] — a
# confirmed absence of upside is treated as seriously as a confirmed wall, just
# without a specific price to name.
TRIGGER_ENTERING_NO_PRIZE = 20.0

# Owner's directive (2026-08-20): "we always want to prefer the reward and
# willing to pay the risk" — the stop was being graded as heavily as the setup
# and the trigger combined, when a close/tight stop can lose to noise on a
# stock that's otherwise doing everything right, and the method's own doctrine
# is to take that trade anyway when the setup and the trigger earn it. Moved
# 10 points off risk onto setup and trigger — the things that answer "is there
# a real reason to be here" and "is it actually happening" — rather than "how
# comfortable is the stop," which the method treats as the price of admission,
# not the deciding factor.
#
# Every literal point value inside `_grade`'s risk and trigger sections is
# still written against the OLD 30-point scale each was designed and measured
# on (his stops sit a median 0.43 ATR, "ideal"=16/30, etc.) — retuning every
# one of those numbers by hand for a budget change risks introducing silent
# drift between them. Instead `_grade` rescales the finished trig/risk_score
# totals (AND every note filed under those axis names, so the why-sentence's
# numbers never stop matching the score they explain) by TRIGGER_MAX/30 and
# RISK_MAX/30 right before they're summed. Change the numbers here; nothing
# else needs to change to keep them in sync.
GRADE_BUDGET = {'setup': 45, 'trigger': 35, 'risk': 20}
GRADE_BANDS = [(4, 85.0), (3, 70.0), (2, 55.0), (1, 40.0), (0, 0.0)]
GRADE_BAND_RANGE = {4: (85.0, 99.0), 3: (70.0, 84.9), 2: (55.0, 69.9),
                    1: (40.0, 54.9), 0: (0.0, 39.9)}

# How far the named trigger price is, in ATR. "אין מה להיכנס לפני" — a pending
# trigger is an alert, never an entry, so this only grades how watchable it is.
TRIGGER_AT_HAND_ATR = 1.0
TRIGGER_NEAR_ATR = 2.5
TRIGGER_REACH_ATR = 5.0

# Resistances this close together are ONE wall, and he quotes the breakout as the
# band rather than a line: "קו הפריצה 85.8-86.5$" (LRCX), "התנגדות עשבו ב 477-484"
# (SPGI). Confirmed on his own charts, which draw the band and label its range —
# CRWD 2026-04-22 carries "553.93 - 555.81", "516.62 - 519.96", "454.00 - 455.59",
# and GTLB 2026-07-09 a "32.99 - 33.97" band under the caption "פריצה אחרי מחיר $34":
# **the price he names is the TOP of the band**, which is what this produces.
# Measured off those charts his bands run 0.1 ATR (CRWD) to 0.6 ATR (GTLB), so this
# matches CLUSTER_ATR_FACTOR rather than exceeding it — an earlier 1.0 here was a
# guess made before the charts were read, and merged walls he keeps separate.
TRIGGER_ZONE_ATR = 0.6

# …and the TOTAL width may never exceed it either. The line above is a per-step gap:
# absorption compares each wall to the last one ADMITTED, so walls 0.59 ATR apart
# chain indefinitely and the finished "band" is unbounded — the exact single-linkage
# failure LEVEL_MAX_SPAN_ATR was added to stop in `_cluster`, which the trigger path
# never got. The comment above already states the intent ("his bands run 0.1 ATR to
# 0.6 ATR"): 0.6 is a WIDTH read off his charts, not a step size.
#
# Measured over 124 names: 23% of trigger bands were wider than the 0.6 ATR cap the
# DISPLAY levels obey (p90 0.91, max 3.38), 16% quoted a trigger above a real
# intervening wall and 11% above a wall at least as strong as the one they named.
# Worst case IONQ: walls at 47.90 (20 touches), 49.03 (18) and 50.87 (13) chained
# into "the breakout zone 46.82-50.87", quoting a price 10.0% overhead — described
# with 47.90's touch count while naming 50.87's price, and skipping the two
# strongest walls on the way. Clearing the first wall of a cluster is not a
# breakout; declaring three separate walls one cluster is not a wall.
TRIGGER_MAX_SPAN_ATR = 0.6

# "קרוב לממוצע" is a clause of his A-grade sentence, and distance from it is a
# spectrum he grades explicitly: RDDT — "where it was last time: close to the
# average, not stretched / now: stretched and far from the average. Is this a
# suitable entry point right now — I'm not sure"; VRT — "above the 150 BUT NOT
# STRETCHED" said as praise; SHAK — "stretched from its averages… what is certain
# is you MUST put a stop"; LUNR — "a bit stretched so be careful with the entry".
# Measured (80 names x 5y, n=44k): being far above the 150 does NOT lower the
# R-multiple hit rate — but the drawdown you must sit through to get it grows from
# -12.2% (0-5% above) to -18.0% (25-40%) to -22.7% (40%+). So it is not a worse
# STOCK, it is a worse ENTRY, which is precisely the axis the grade scores.
FAR_FROM_MA_PCT = 0.35      # beyond this, "רחוקה מהממוצע" — a poor entry point
# "מתוחה" is declared off the 150 and the 200 only — never the 20, which measures a
# different thing (how fast the last few weeks went; `ran_hot` covers that) and
# routinely disagrees: CRWD/FTNT/PANW all sit at or under their 20MA while 40%+ above
# their 150. Below FAR it is "קצת מתוחה" (AAPL "אתם לא מאחרים"); above it, "מתוחה"
# (SHAK "חייבים לשים סטופ"); clear of the 200 by FAR_FROM_MA200_PCT as well and it is
# "מהממוצעים" — plural, both gone — the state he declines outright (RDDT).
MILD_FROM_MA_PCT = 0.15     # matches _near_ma's own "close to the average" threshold
FAR_FROM_MA200_PCT = 0.50

# Top reward marks require a thesis the market actually reaches, not just a big
# ratio scaled by poor odds. Measured (70 names x 5y, 62k levels): 4-6 ATR out is
# reached 72.7% of the time, 6-9 ATR 53.0%, 9-13 ATR 24.8%. Set between the 6-9 and
# 9-13 bands — a coin flip still qualifies for full marks, a 1-in-4 does not.
TARGET_ODDS_FLOOR = 0.40

# The rim of a cup is a price he names as the breakout even though it is a SINGLE
# pivot and therefore can never become a clustered level (MIN_LEVEL_TOUCHES=2):
# MMM "קאם אנד הנדל, פריצה פוטנציאלית מעל 177.5", LVS "cup … breakout above 55.66",
# GTLB "cup and handle, פריצה אחרי מחיר $34". With no candidate for it, `_trigger`
# fell through to the all-time high and the setup read as further away than he calls
# it. Gated on the SHAPE rather than on the pivot alone, or every ordinary pullback
# high qualifies:
#   • the decline after the rim must be deep enough to be a cup, not a shelf;
#   • price must have climbed back near the rim — from the bottom of the cup the rim
#     is not today's obstacle, it is a different trade entirely.
CUP_RIM_DEPTH_ATR = 3.0     # min drop from the rim to the trough behind it
CUP_RIM_NEAR_ATR = 3.0      # ...and how close price must be back to the rim now

# "הבעיה שלי זה שהיא רצה כל כך הרבה בימים האחרונים … 6 ימים רצופים של עליות" (CRWD).
# The short-term twin of the extension gauge: he refused a stock that had just
# reclaimed its 150 — a trigger by the method's own rules — because the run INTO the
# trigger was the move. Counted both ways he says it: consecutive up days, and the
# size of the recent run in ATRs (a 3-day gap-and-drift shows up in the second).
RUN_UP_LOOKBACK = 6
RUN_UP_DAYS = 6             # consecutive green days
RUN_UP_ATR = 3.0            # or this much ground covered in RUN_UP_LOOKBACK days

# (An OVERHEAD_WALL_PENALTY lived here and was removed after measurement — it charged
#  a stock for owning a target ladder and cost TEAM its A. See the note in
#  verdict._grade before considering anything like it again.)

# ── "מתקרב להכרעה. שימו התראה" — the alert band ───────────────────────────────
# A stock can be a clear "not now" and still sit one ordinary day's move from
# becoming a setup, and he tracks exactly those by name and by alert price:
# ONDS "מתקרב להכרעה. שימו התראה. כשהיא תקפוץ אני אעלה את הסט אפ", AMD "שימו התראה
# ותמתינו בסבלנות - כשתפרוץ אני מבטיח סט אפ", SMCI "קפצה התראה אז הנה", UPS "התראה
# מעל 111$", AZEK "שימו אותה למעקב + התראה".
#
# This is deliberately SEPARATE from the grade. The grade answers "is this a trade
# today" and must stay honest about a D; the alert answers "how far is it from
# becoming one", and the two are different questions. Measured in ATR, so it means
# the same thing on a 10%-ATR miner and a 2%-ATR mega-cap: fractions of an average
# day, not a percentage that flatters calm names.
ALERT_IMMINENT_ATR = 0.5    # under half an average daily range
ALERT_CLOSE_ATR = 1.0       # about one average daily range
ALERT_NEAR_ATR = 2.0        # a couple of ranges; beyond this it is not "soon"
# ATR is a RANGE measure, not net directional drift, so it cannot be the only gate:
# INTC's trigger sits 16.8% away, which on an 8.4%-ATR name computes to "2 average
# days" and reads as imminent. It is not. A move that large is a different thesis,
# whatever the volatility, so cap the alert in plain percent too.
ALERT_MAX_PCT = 8.0
# ...and a floor, because a trigger 0.2% overhead (ADBE) is not a decision point,
# it is the same price — it will be crossed and re-crossed by ordinary noise.
ALERT_MIN_ATR = 0.10
ALERT_MIN_PCT = 0.3

# "growth at a reasonable price — מה זה מחיר טוב? קרוב לממוצע". A value call is only
# a value call near the average; this is how far BELOW the 150 still counts.
VALUE_NEAR_150_ATR = 3.0
OFF_HIGH_VALUE_PCT = 25.0    # "מינוס 46% מהשיא", "45% ירידה מהשיא" — the discount
STOP_BUFFER = 0.005          # "המחירים שאני כותב — אלו גם איזורי הסטופ ±חצי אחוז"

# ── Stop quality ──────────────────────────────────────────────────────────────
# Micha's stops are TIGHT and always defined ("סטופ ±0.5%" under the level). Stop
# quality is the most method-faithful risk measure there is, and it was missing from
# the grade entirely — INTC measured a 40.3% stop while still being told "enter now".
# Two failure modes, and they need different tests:
#   • too WIDE in % terms — not a Micha trade at any R/R (INTC: 40.3%)
#   • too TIGHT vs ATR — will be stopped out by ordinary daily noise regardless of
#     how good the R/R looks on paper (ORCL: a 1.0% stop on an 8.4%-ATR name is
#     0.15 ATR, i.e. inside a single average day's range)
# DO NOT re-derive this from an R-multiple win rate. It was changed to (0.15, 1.0)
# on exactly that evidence and reverted the same hour, because the evidence was an
# artifact. Forward-labelling 317 of his calls at +2R gave:
#     <=0.5 ATR  win 65.4%   1.0-1.5  38.3%   1.5-2.5  47.4%
# which looks like a clean "tight stops pay". Re-scoring the SAME calls against a
# target that does not move with the stop (+1.5 ATR fixed) reverses it completely:
#     <=0.5 ATR  win 50.0%   1.0-1.5  59.3%   1.5-2.5  67.9%   2.5+  76.3%
# At 2R the target IS a multiple of the stop, so a tighter stop wins by definition
# and the number measures arithmetic, not trading. Any future change here needs a
# stop-independent outcome metric, and needs to survive both.
STOP_IDEAL_ATR = (0.75, 2.5)   # stop distance in ATR that is neither noise nor reckless

# Reference only — NOT a grade input, and tried as one. The thickness of the wall
# being broken (`trigger['floor']`) is a property of the chart, not of our plan, so
# unlike stop distance it CAN be measured cleanly. On forward 20-day return over 395
# of his posts:
#     <=0.15 ATR  n=209  +1.06%  win 44%      0.35-0.60  n=42  -0.34%  win 48%
#     0.15-0.35   n= 60  +5.82%  win 65%      >0.60      n=82  +2.22%  win 54%
# A real standalone signal, and 0.15-0.35 is exactly the width he draws. But scoring
# it in the risk axis made the LETTER worse — the A bucket's forward return fell from
# +4.88% to +3.65% and A/B/C became indistinguishable — because the information is
# already inside what that axis scores. It is drawn on the chart instead.
GRADE_BAND_IDEAL_ATR = (0.15, 0.35)
GRADE_BAND_HAIRLINE_ATR = 0.15
STOP_NOISE_ATR = 0.5           # tighter than this ⇒ likely stopped by noise
# Two widths, because he names both: "מעל 288 עם סטופ קרוב יחסית למי שבטרייד. מי
# שמחזיק לטווח ארוך - סטופ רחב יותר" (AAPL). A swing position gets more room —
# "לוודא שאתם לא חונקים את הסטופ" (KRE, a months-long trade).
STOP_POSITION_WIDEN = 1.6      # multiply the trade stop's distance for a position stop
# ATR is the primary unit, % only a far backstop. Judging stop width in % punishes
# volatility: ARM's stop measured 1.58 ATR — squarely sensible — yet 17.0% tripped a
# 15% ceiling, while INTC's genuinely reckless stop was 3.40 ATR / 40.3%. A 17% stop
# on a 9.2%-ATR name is 1.6 average days; the same 17% on a 2%-ATR name would be 8.
STOP_WIDE_ATR = 4.0            # beyond this many ATR ⇒ not a stop in this method
STOP_MAX_RISK_PCT = 30.0       # ...or this much of the position, where sizing breaks
# The other half of that argument: a wide-in-% stop is not forbidden, it is SMALLER.
# Risking this much of the account per trade, position size = budget / stop%, so a
# 16.8% stop (ONDS) is a 6% position and a 2.4% stop (NVDA) is a 42% one — same money
# at risk. Quoting the stop % without this makes the volatile name look untradeable.
STOP_RISK_BUDGET_PCT = 1.0
# A gap only works as a stop reference while it is still near price — FTNT's unfilled
# gap measured ~31% below, which is history, not a stop level.
GAP_STOP_MAX_ATR = 3.0


def jnum(x) -> Optional[float]:
    """numpy/pandas scalar → clean python float (or None for NaN/inf) for JSON."""
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) or math.isinf(v) else round(v, 4)
