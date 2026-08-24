"""
The trade thesis — the argument, assembled in one place.

Everything here already existed somewhere in the payload: the entry and stop on
the option, the break level on the signals, the invalidation in the report, the
supporting and conflicting evidence in `reasons.py`, the holding period in the
growth model. What did not exist was the ARGUMENT as a single object a reader
(or a future outcome study) could take apart: "why enter, where, where am I
wrong, what am I aiming at, what kills it, how long."

So this module composes; it does not compute. Every field is sourced from a
value the pipeline already produced, which is what keeps the thesis from
becoming a second opinion free to contradict the verdict it is supposed to
explain — the same rule `_grade_sentence` follows by building the grade's
sentence out of the grade's own notes rather than out of `reasons.py`.

The one thing it deliberately does NOT do is decide anything. If the verdict
says WAIT, the thesis describes the trade that is being waited FOR, and the
blocker lives in `gates.why_not` where it belongs.
"""

from __future__ import annotations

from typing import Optional

from config import jnum

# Reason stances (reasons.py): 'for' supports the thesis, 'against' contradicts
# it, 'note' is context that does neither.
_FOR, _AGAINST = 'for', 'against'

# How many items of each side to carry. The thesis is an argument, not a dump —
# past a handful the reader stops reading and the signal is lost in the list.
_MAX_SIDE = 6


def _setup_type(sig, state: str) -> str:
    """
    What KIND of trade this is, in one machine-readable token.

    Prefers the chart's own headline pattern (`micha._pattern`, which already
    encodes a priority order across the detectors) and falls back to the state
    when no pattern was named — a breakout with no recognised pattern is still
    a breakout, and returning None there would leave the most common setup in
    the system unlabelled.
    """
    codes = sig.codes or set()
    for code in ('vcp', 'cup_handle', 'bull_flag', 'triangle',
                 'rising_channel', 'descending_channel', 'bearish_to_bullish'):
        if code in codes:
            return code
    return state


def _collect(reasons: list, stance: str) -> list:
    """Flatten the seven reason groups into one stance-filtered list."""
    out = []
    for grp in reasons or []:
        for item in grp.get('items') or []:
            if item.get('stance') == stance:
                out.append({'group': grp.get('key'),
                            'en': item.get('en'), 'he': item.get('he')})
    return out[:_MAX_SIDE]


def _holding_period(growth: Optional[dict]) -> Optional[dict]:
    """
    How long the thesis expects to be in the trade, in TRADING days.

    Read from the growth model's measured curve rather than restated, and it
    carries `hit_rate` alongside `days` on purpose: the curve bends under
    survivorship past roughly 8 ATR, so beyond there `days` means "when it
    works" and is misleading without the odds printed next to it.
    """
    if not growth:
        return None
    return {
        'to_first_target_days': jnum(growth.get('first_days')),
        'to_first_target_hit_rate': jnum(growth.get('first_hit_rate')),
        'to_thesis_days': jnum(growth.get('days')),
        'to_thesis_hit_rate': jnum(growth.get('hit_rate')),
        'pace': growth.get('pace'),
    }


def build(sig, verdict: dict, reasons: list, best: Optional[dict],
          growth: Optional[dict] = None) -> Optional[dict]:
    """
    Assemble the thesis from what the pipeline already decided.

    Returns None for the states where there is no trade to describe — a broken
    or avoided chart has no thesis, and manufacturing one would put an argument
    for entering underneath a verdict that says stay away.
    """
    state = verdict.get('state')
    if state in ('broken', 'avoid', 'nothing_yet'):
        return None

    report = verdict.get('report') or {}
    hold = verdict.get('hold_level') or {}
    trigger = verdict.get('trigger') or {}
    r_plan = verdict.get('r_multiple') or {}

    # Invalidation: the price that ends the thesis, plus the report's own words
    # for it. Both, because the number alone does not say what it means and the
    # sentence alone cannot be compared against a quote.
    invalidation = []
    if hold.get('price') is not None:
        invalidation.append({
            'kind': 'level_lost',
            'price': jnum(hold.get('price')),
            'en': hold.get('label'), 'he': hold.get('label_he'),
        })
    if best and best.get('stop') is not None:
        invalidation.append({
            'kind': 'stop_hit',
            'price': jnum(best.get('stop')),
            'en': f"stop at {float(best['stop']):.2f} ({best.get('stop_what') or 'the structure'})",
            'he': f"סטופ ב-{float(best['stop']):.2f} ({best.get('stop_what_he') or 'המבנה'})",
        })
    if report.get('invalidation'):
        invalidation.append({
            'kind': 'reported',
            'price': None,
            'en': report.get('invalidation'), 'he': report.get('invalidation_he'),
        })

    return {
        'setup_type': _setup_type(sig, state),
        'state': state,
        'action': verdict.get('action'),
        # WHY: the chart's own read, which is the sentence describing what is
        # happening — not the grade's score, which is a different question
        'entry_reason': report.get('read'),
        'entry_reason_he': report.get('read_he'),
        # WHERE
        'entry_price': jnum((best or {}).get('entry')),
        'entry_kind': (best or {}).get('kind'),
        'break_level': jnum(sig.break_level if sig.break_level is not None
                            else trigger.get('price')),
        # WHERE I AM WRONG
        'stop_price': jnum((best or {}).get('stop')),
        'risk_per_share': r_plan.get('risk_per_share'),
        'risk_pct': r_plan.get('risk_pct'),
        'invalidation_conditions': invalidation,
        # WHAT I AM AIMING AT — the R-priced ladder, reused rather than rebuilt
        'targets': r_plan.get('targets') or [],
        'expected_value': verdict.get('expected_value'),
        # HOW LONG
        'expected_holding_period': _holding_period(growth),
        # THE EVIDENCE, both ways. Conflicting signals are carried deliberately:
        # a thesis that lists only what agrees with it is advocacy, not analysis.
        'supporting_signals': _collect(reasons, _FOR),
        'conflicting_signals': _collect(reasons, _AGAINST),
    }
