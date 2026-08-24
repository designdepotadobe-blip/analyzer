"""
Hard gates — the blockers, stated as data instead of buried in a score.

The design principle this serves: a trade with unacceptable risk must not become
attractive merely because its structure and reward scored well. The engine
already enforced that — `verdict._grade`'s ceilings clamp the LETTER regardless
of the raw score, and a `stop_wide` chart cannot reach a B no matter how good
the base is. What was missing was not the enforcement, it was the ARTICULATION:
the blockers existed only as bilingual display strings inside the grade
breakdown, so nothing downstream could ask "what is blocking this, and by how
much" without parsing prose.

So this module does not re-implement the gate conditions. Re-deriving them here
would create a second opinion free to drift from the one that actually sets the
letter — the same failure the codebase already avoids by composing the grade
sentence from the grade's own arithmetic rather than from `reasons.py`. It reads
what `_grade` already decided and gives it a machine-readable shape, plus the
few VALIDITY gates that genuinely had no home before (a plan whose stop, entry
or targets are not usable at all).

`GateResult.passed` is False when the gate FIRED, i.e. when it blocked something.
Reading it as "the check succeeded" inverts every meaning in this file.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

# Severity is about what the gate DOES to the letter, not how alarming it sounds.
#   blocking  — clamped the grade to D or worse: the case is failing, not flawed.
#   limiting  — clamped to B/C: a real caveat, the setup survives it.
#   advisory  — the condition applied but did not move the letter (see `bound`).
SEVERITY_BLOCKING = 'blocking'
SEVERITY_LIMITING = 'limiting'
SEVERITY_ADVISORY = 'advisory'

# Ceiling index (verdict.GRADES is ['F','D','C','B','A']) at or below which a
# fired gate is calling the whole case off rather than qualifying it.
_BLOCKING_CEILING = 1


@dataclass
class GateResult:
    """One blocker, with the numbers that produced it."""
    passed: bool
    reason_code: str
    explanation: str
    explanation_he: str = ''
    severity: str = SEVERITY_ADVISORY
    # Whether this gate is what actually SET the letter, as opposed to having
    # applied without moving it. A gate that applied but did not bind explains
    # nothing about the grade and must never be reported as the primary blocker.
    bound: bool = False
    metrics: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _severity(ceiling: Optional[int], bound: bool) -> str:
    if not bound:
        return SEVERITY_ADVISORY
    if ceiling is not None and ceiling <= _BLOCKING_CEILING:
        return SEVERITY_BLOCKING
    return SEVERITY_LIMITING


def validity_gates(best: Optional[dict], targets: Optional[list]) -> list:
    """
    The gates that ask whether a plan is priceable at all.

    Distinct from every other gate in this file: the rest describe a real plan
    that is unattractive, these describe arithmetic that cannot be performed.
    They had no representation before because the engine simply emitted `None`
    for the affected numbers and the reader was left to notice the blanks.

    Deliberately NOT a grade ceiling. `_grade` already handles an unpriceable
    plan by forfeiting the reward axis outright (a live state with no priced
    plan zeroes the biggest axis on the board), and adding a second penalty for
    the same fact would charge it twice.
    """
    out: list[GateResult] = []
    if not best:
        out.append(GateResult(
            passed=False, reason_code='no_plan',
            explanation='no entry plan could be priced for this chart',
            explanation_he='לא ניתן לתמחר תוכנית כניסה לגרף הזה',
            severity=SEVERITY_ADVISORY, bound=False, metrics={}))
        return out

    entry, stop = best.get('entry'), best.get('stop')
    if entry is None or float(entry) <= 0:
        out.append(GateResult(
            passed=False, reason_code='invalid_entry',
            explanation='the entry price is undefined or not a positive price',
            explanation_he='מחיר הכניסה לא מוגדר או אינו מחיר חיובי',
            metrics={'entry': entry}))
    if stop is None or float(stop) <= 0:
        out.append(GateResult(
            passed=False, reason_code='invalid_stop',
            explanation='no stop price is defined — the risk cannot be measured',
            explanation_he='לא מוגדר מחיר סטופ — אי אפשר למדוד את הסיכון',
            metrics={'stop': stop}))
    elif entry is not None and float(stop) >= float(entry):
        # Not a rounding quibble: a stop at or above the entry makes every R
        # multiple in the payload either infinite or sign-flipped, so the whole
        # reward ladder silently becomes nonsense rather than merely wrong.
        out.append(GateResult(
            passed=False, reason_code='stop_above_entry',
            explanation=(f'the stop ({float(stop):.2f}) sits at or above the entry '
                         f'({float(entry):.2f}) — that is not a stop'),
            explanation_he=(f'הסטופ ({float(stop):.2f}) נמצא בגובה הכניסה או מעליה '
                            f'({float(entry):.2f}) — זה לא סטופ'),
            metrics={'entry': entry, 'stop': stop}))
    if not targets:
        out.append(GateResult(
            passed=False, reason_code='no_target',
            explanation='no target above the entry — there is nothing to measure the trade against',
            explanation_he='אין יעד מעל הכניסה — אין מול מה למדוד את הטרייד',
            metrics={'targets': 0}))
    return out


def from_caps(caps: Optional[list], ceilings: Optional[dict] = None) -> list:
    """
    The grade's own ceilings, as structured gates.

    `caps` is `grade_breakdown['caps']` — the list `_grade` already built, in the
    order it applied them. `ceilings` optionally maps reason_code -> the grade
    index that cap clamps to, which is what separates "this failed" from "this
    is a caveat"; without it every fired gate reports as `limiting`, which is
    the safe direction to be wrong in.
    """
    out: list[GateResult] = []
    for c in caps or []:
        key = c.get('key')
        bound = bool(c.get('bound'))
        ceiling = (ceilings or {}).get(key)
        out.append(GateResult(
            passed=False,
            reason_code=key,
            explanation=c.get('label') or '',
            explanation_he=c.get('label_he') or '',
            severity=_severity(ceiling, bound),
            bound=bound,
            metrics={'ceiling': ceiling} if ceiling is not None else {},
        ))
    return out


def why_not(action: str, gates: list, positives: Optional[list] = None) -> Optional[dict]:
    """
    Why this is not an ENTER, with the primary blocker named.

    Only produced for a non-entering action — on an `enter` call there is no
    blocker to report, and inventing one to fill the field would be exactly the
    after-the-fact narration this codebase refuses elsewhere.

    "Primary" is chosen by what actually moved the letter, never by what sounds
    worst: a BOUND gate outranks an unbound one, and among bound gates the one
    with the lowest ceiling (the harshest clamp) wins. A gate that applied
    without binding is listed as a contributing blocker but is never promoted to
    primary, because it did not set the outcome.
    """
    if action == 'enter':
        return None
    fired = [g for g in gates if not g.passed]
    if not fired:
        return None

    def severity_rank(g: GateResult) -> tuple:
        # bound first, then harshest ceiling, then blocking over limiting
        ceiling = g.metrics.get('ceiling')
        return (0 if g.bound else 1,
                ceiling if ceiling is not None else 99,
                0 if g.severity == SEVERITY_BLOCKING else 1)

    ordered = sorted(fired, key=severity_rank)
    primary = ordered[0]
    return {
        'action': action,
        'primary_blocker': primary.reason_code,
        'primary_explanation': primary.explanation,
        'primary_explanation_he': primary.explanation_he,
        'blockers': [g.to_dict() for g in ordered],
        # what the chart still has going for it — read from the grade's own
        # positive notes, so this cannot praise something the score did not credit
        'still_going_for_it': list(positives or []),
    }
