"""
Hard gates and the "why not" blocker report.

The invariant under test throughout: a gate that APPLIED but did not move the
letter must never be reported as the reason for the outcome. That distinction
(`bound`) is the whole difference between an explanation and a plausible-sounding
guess, and it is the one thing most likely to regress silently.
"""

from __future__ import annotations

import gates as gt


def _cap(key, bound, label='because reasons'):
    return {'key': key, 'label': label, 'label_he': 'סיבה', 'bound': bound}


class TestValidityGates:
    def test_no_plan(self):
        out = gt.validity_gates(None, [{'price': 1}])
        assert [g.reason_code for g in out] == ['no_plan']
        assert out[0].passed is False

    def test_valid_plan_raises_nothing(self):
        out = gt.validity_gates(
            {'entry': 100, 'stop': 90}, [{'price': 120}])
        assert out == []

    def test_stop_above_entry_is_caught(self):
        out = gt.validity_gates({'entry': 100, 'stop': 110}, [{'price': 120}])
        codes = [g.reason_code for g in out]
        assert 'stop_above_entry' in codes
        g = next(x for x in out if x.reason_code == 'stop_above_entry')
        assert g.metrics == {'entry': 100, 'stop': 110}

    def test_missing_stop_is_caught(self):
        out = gt.validity_gates({'entry': 100, 'stop': None}, [{'price': 120}])
        assert 'invalid_stop' in [g.reason_code for g in out]

    def test_no_target_is_caught(self):
        out = gt.validity_gates({'entry': 100, 'stop': 90}, [])
        assert 'no_target' in [g.reason_code for g in out]

    def test_validity_gates_never_claim_to_be_binding(self):
        # they describe unpriceable arithmetic, not a grade ceiling — `_grade`
        # already forfeits the reward axis for this, and binding here too would
        # charge the same fact twice
        out = gt.validity_gates({'entry': 100, 'stop': None}, [])
        assert all(g.bound is False for g in out)


class TestFromCaps:
    def test_bound_blocking_vs_limiting(self):
        caps = [_cap('stop_wide', True), _cap('stretched', True)]
        ceilings = {'stop_wide': 1, 'stretched': 3}
        out = gt.from_caps(caps, ceilings)
        by = {g.reason_code: g for g in out}
        # clamped to D -> the case is failing
        assert by['stop_wide'].severity == gt.SEVERITY_BLOCKING
        # clamped to B -> a real caveat the setup survives
        assert by['stretched'].severity == gt.SEVERITY_LIMITING

    def test_unbound_cap_is_advisory_whatever_its_ceiling(self):
        out = gt.from_caps([_cap('stop_wide', False)], {'stop_wide': 1})
        assert out[0].severity == gt.SEVERITY_ADVISORY
        assert out[0].bound is False

    def test_missing_ceiling_degrades_safely(self):
        # unknown ceiling must not crash and must not claim 'blocking'
        out = gt.from_caps([_cap('mystery', True)], {})
        assert out[0].severity == gt.SEVERITY_LIMITING

    def test_empty(self):
        assert gt.from_caps(None, {}) == []
        assert gt.from_caps([], {}) == []


class TestWhyNot:
    def test_enter_reports_no_blocker(self):
        """An ENTER has nothing blocking it; inventing a blocker to fill the
        field would be exactly the after-the-fact narration to avoid."""
        gates = gt.from_caps([_cap('stretched', True)], {'stretched': 3})
        assert gt.why_not('enter', gates) is None

    def test_bound_gate_outranks_unbound_one(self):
        gates = gt.from_caps(
            [_cap('stretched_far', False), _cap('stop_wide', True)],
            {'stretched_far': 2, 'stop_wide': 1})
        wn = gt.why_not('wait_trigger', gates)
        assert wn['primary_blocker'] == 'stop_wide'

    def test_harshest_ceiling_wins_among_bound(self):
        gates = gt.from_caps(
            [_cap('earnings', True), _cap('broken', True)],
            {'earnings': 3, 'broken': 0})
        wn = gt.why_not('out', gates)
        assert wn['primary_blocker'] == 'broken'

    def test_unbound_gate_is_listed_but_never_primary(self):
        gates = gt.from_caps([_cap('stretched_far', False)], {'stretched_far': 2})
        wn = gt.why_not('wait_trigger', gates)
        codes = [b['reason_code'] for b in wn['blockers']]
        assert 'stretched_far' in codes          # still reported as contributing
        assert wn['blockers'][0]['bound'] is False

    def test_no_fired_gates_yields_none(self):
        assert gt.why_not('watch', []) is None

    def test_positives_are_passed_through(self):
        gates = gt.from_caps([_cap('stop_wide', True)], {'stop_wide': 1})
        wn = gt.why_not('wait_trigger', gates, ['rising highs and lows'])
        assert wn['still_going_for_it'] == ['rising highs and lows']


class TestGatesOnRealPayloads:
    """Against the frozen sample, so the wiring is exercised end to end."""

    def test_entering_names_have_no_why_not(self, analyses):
        for tk, r in analyses.items():
            m = r['micha']
            if m['action'] == 'enter':
                assert m['why_not'] is None, f'{tk} is an ENTER but reported a blocker'

    def test_non_entering_names_name_a_primary_blocker_when_capped(self, analyses):
        for tk, r in analyses.items():
            m = r['micha']
            bound = [c for c in m['grade_breakdown']['caps'] if c['bound']]
            if m['action'] != 'enter' and bound:
                wn = m['why_not']
                assert wn is not None, f'{tk} was capped but reported no why_not'
                assert wn['primary_blocker'] in {c['key'] for c in bound}, (
                    f"{tk}: primary blocker {wn['primary_blocker']!r} is not among "
                    f"the caps that actually bound")

    def test_every_gate_is_serializable(self, analyses):
        import json
        for tk, r in analyses.items():
            json.dumps(r['micha']['hard_gates'])
            json.dumps(r['micha']['why_not'])
