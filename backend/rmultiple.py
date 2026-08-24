"""
The risk/reward layer: every reward expressed as a multiple of the risk taken.

Why this exists as its own module rather than more fields on the option dict:
the engine already carried `risk_reward` (to the farthest target) and
`risk_reward_first` (to the nearest), which answers "what is the ratio" for two
hand-picked rungs and says nothing about the ladder in between. A swing trader
scaling out needs the R at EVERY station, and a dollar distance cannot be
compared across two names — 7 points of reward is a different trade on a $40
stock than on a $400 one. R is the unit that makes the ladder comparable, so it
is computed once, here, and read everywhere else.

Nothing in this module decides anything. It converts prices the pipeline has
already chosen (an entry, a stop, a target ladder) into R space and reports
what that arithmetic says. The judgement layer stays in verdict.py.

── On the probability attached to expected value ────────────────────────────
`config.expectancy()` is a MEASURED surface (60 tickers x 5y, n≈39.6k per cell)
— but it is measured over "any bar above the SMA150", with no setup-quality
filter at all. Its own comment in config.py is explicit that this makes it a
FLOOR the app's setups should beat, not a claim about them. So the probability
it yields is real but UNCONDITIONED: it is not "how often did a VCP breakout
with this volume signature work", which is what a reader hears if the number is
labelled "historical". Everything here therefore reports

    probability_source = 'measured_baseline'

and never 'historical_analogs'. When a real per-setup outcome sample exists
(and clears its minimum-sample bar), that path can be added alongside — the
label is what keeps the two from being confused, so do not collapse them.
"""

from __future__ import annotations

from typing import Optional

from config import expectancy, jnum, time_to_target

# What each label means, so a reader (or a future calibration pass) is not
# guessing at the string:
#   measured_baseline — config.expectancy()'s measured grid, NOT conditioned on
#                       the setup. Honest floor, weak claim.
#   historical_analogs — reserved: an outcome sample of comparable setups that
#                       has cleared MIN_HISTORICAL_SAMPLES. Nothing emits this
#                       yet, deliberately; emitting it without the sample would
#                       be the exact fabrication the design forbids.
#   unavailable       — no priced plan, so no probability can be stated at all.
PROBABILITY_SOURCES = ('measured_baseline', 'historical_analogs', 'unavailable')


def r_multiple(entry: Optional[float], stop: Optional[float],
               target: Optional[float]) -> Optional[float]:
    """
    Reward to `target` as a multiple of the risk to `stop`.

    Returns None rather than a number whenever the arithmetic would be a lie:
    a stop at or above the entry is not a stop (risk would be zero or negative,
    making every R either infinite or sign-flipped), and a target at or below
    the entry is not a target. Callers must treat None as "cannot be priced",
    never as zero — a setup with no measurable R is not a setup with no reward.
    """
    if entry is None or stop is None or target is None:
        return None
    risk = float(entry) - float(stop)
    if risk <= 0:
        return None
    reward = float(target) - float(entry)
    if reward <= 0:
        return None
    return reward / risk


def build_plan(entry: Optional[float], stop: Optional[float], targets: list,
               atr: Optional[float] = None,
               atr_pct: Optional[float] = None) -> Optional[dict]:
    """
    The full ladder in R space.

    `targets` is micha's station ladder (price / label / source / touches), used
    as-is — the stations are chosen upstream by rank and merge rules that this
    layer has no business re-litigating. Each rung gains:

        r         reward as a multiple of risk
        atr       distance from entry in ATR (comparable across names)
        days      measured median trading days to a move that size
        hit_rate  measured odds of getting there inside the horizon

    `days`/`hit_rate` come from config.time_to_target's measured curve, so the
    ladder can say "T2 is 3.1R but the market reaches that distance 27% of the
    time" — the pair a single ratio cannot express, and the reason the farthest
    target is deliberately NOT treated as the best one.
    """
    if entry is None or stop is None:
        return None
    entry, stop = float(entry), float(stop)
    risk_per_share = entry - stop
    if risk_per_share <= 0:
        return None

    rungs = []
    for t in (targets or []):
        p = t.get('price')
        if p is None:
            continue
        p = float(p)
        # A station at or below THIS plan's entry is not a target of this plan.
        # The ladder is anchored on spot, the plan may not be: on a
        # `wait_trigger` setup the entry IS the breakout price, so the ladder's
        # first rung is frequently that exact price (ADBE: T1 286.845 against a
        # breakout entry of 286.845). Pricing it would yield a 0R or negative
        # "reward" and put a meaningless rung at the top of the ladder. Dropped
        # rather than kept-and-flagged because `micha`'s own `targets` list is
        # still published unfiltered — nothing is hidden, it is just not priced
        # against a plan it does not belong to. Numbering follows the surviving
        # rungs so T1 is always the first thing this trade is actually aiming at.
        if p <= entry:
            continue
        d_atr = (p - entry) / atr if atr else None
        days = hit = None
        if d_atr is not None and d_atr > 0:
            days, hit = time_to_target(d_atr, atr_pct)
        rungs.append({
            'n': len(rungs) + 1,
            'price': jnum(p),
            'label': t.get('label'),
            'label_he': t.get('label_he'),
            'source': t.get('source'),
            'touches': t.get('touches'),
            'pct': jnum((p / entry - 1) * 100),
            'atr': jnum(d_atr),
            'r': jnum(r_multiple(entry, stop, p)),
            'days': jnum(days),
            'hit_rate': jnum(hit),
        })

    return {
        'entry': jnum(entry),
        'stop': jnum(stop),
        'risk_per_share': jnum(risk_per_share),
        'risk_pct': jnum(risk_per_share / entry * 100) if entry else None,
        'risk_atr': jnum(risk_per_share / atr) if atr else None,
        'targets': rungs,
        # Convenience mirrors of the first three rungs, because the spec's own
        # framing ("target1_R = 2.0") reads them positionally. Derived from
        # `targets` above rather than recomputed, so they can never disagree.
        'target_rs': [rg['r'] for rg in rungs],
    }


def expected_value(plan: Optional[dict], stop_atr: Optional[float],
                   rr: Optional[float]) -> dict:
    """
    Expected value in R, with its probability provenance stated.

    Deliberately reuses the SAME `config.expectancy()` the reward axis already
    scores on rather than deriving a second opinion — two expectancy numbers on
    one payload that disagree is worse than one with a caveat.

    `downside_R` is -1.0 by construction whenever a plan exists: R is defined as
    the distance to the stop, so losing the trade at its stop costs exactly one
    R. It is stated explicitly rather than left implicit because the asymmetry
    (risk fixed at 1R, reward variable) is the entire point of the unit.
    """
    out = {
        'expected_R': None,
        'downside_R': None,
        'target_Rs': (plan or {}).get('target_rs') or [],
        'probability_source': 'unavailable',
        'p_win': None,
        'confidence': 'none',
    }
    if plan is None:
        return out
    out['downside_R'] = -1.0
    p, ev = expectancy(stop_atr, rr)
    if p is None or ev is None:
        return out
    out.update({
        'expected_R': jnum(ev),
        'p_win': jnum(p),
        'probability_source': 'measured_baseline',
        # Measured, but unconditioned on setup quality — see the module
        # docstring. 'low' is the honest ceiling for this source; a higher
        # confidence needs a per-setup sample that does not exist yet.
        'confidence': 'low',
    })
    return out
