"""
R-multiple arithmetic, including the cases where refusing to answer is correct.

The edge cases matter more than the happy path here: an R multiple computed off
a non-stop (at or above the entry) is not merely inaccurate, it silently flips
sign or runs to infinity and poisons every downstream number that reads it.
"""

from __future__ import annotations

import pytest

import rmultiple as rm


class TestRMultiple:
    def test_basic(self):
        # the spec's own worked example: entry 184, stop 177 -> risk 7
        assert rm.r_multiple(184, 177, 198) == pytest.approx(2.0)
        assert rm.r_multiple(184, 177, 205) == pytest.approx(3.0)

    def test_fractional(self):
        assert rm.r_multiple(100, 90, 115) == pytest.approx(1.5)

    @pytest.mark.parametrize('entry,stop,target', [
        (100, 100, 120),    # stop AT entry — zero risk, R is undefined not infinite
        (100, 110, 120),    # stop ABOVE entry — not a stop at all
    ])
    def test_refuses_non_stop(self, entry, stop, target):
        assert rm.r_multiple(entry, stop, target) is None

    @pytest.mark.parametrize('target', [100, 90])
    def test_refuses_target_at_or_below_entry(self, target):
        # not a target; returning a negative R would read as "a losing trade"
        # when the truth is "this is not a reward"
        assert rm.r_multiple(100, 90, target) is None

    def test_refuses_none_inputs(self):
        assert rm.r_multiple(None, 90, 120) is None
        assert rm.r_multiple(100, None, 120) is None
        assert rm.r_multiple(100, 90, None) is None


class TestBuildPlan:
    def _targets(self):
        return [
            {'price': 115, 'label': 'next resistance', 'source': 'resistance', 'touches': 4},
            {'price': 130, 'label': 'prior high (ATH)', 'source': 'ath', 'touches': None},
        ]

    def test_rungs_carry_r_and_source(self):
        plan = rm.build_plan(100, 90, self._targets(), atr=5.0, atr_pct=5.0)
        assert plan['risk_per_share'] == pytest.approx(10.0)
        assert plan['risk_pct'] == pytest.approx(10.0)
        assert plan['risk_atr'] == pytest.approx(2.0)
        rungs = plan['targets']
        assert [r['n'] for r in rungs] == [1, 2]
        assert rungs[0]['r'] == pytest.approx(1.5)
        assert rungs[1]['r'] == pytest.approx(3.0)
        assert rungs[0]['source'] == 'resistance'
        assert rungs[0]['touches'] == 4
        assert plan['target_rs'] == [rungs[0]['r'], rungs[1]['r']]

    def test_atr_distance_and_odds_present(self):
        plan = rm.build_plan(100, 90, self._targets(), atr=5.0, atr_pct=5.0)
        r1 = plan['targets'][0]
        assert r1['atr'] == pytest.approx(3.0)
        # measured curve: a farther target must not be reported as MORE likely
        assert plan['targets'][1]['hit_rate'] <= r1['hit_rate']
        assert plan['targets'][1]['days'] >= r1['days']

    def test_no_atr_still_prices_r(self):
        # ATR is optional context; R is the primary unit and must survive without it
        plan = rm.build_plan(100, 90, self._targets(), atr=None)
        assert plan['targets'][0]['r'] == pytest.approx(1.5)
        assert plan['targets'][0]['atr'] is None

    @pytest.mark.parametrize('entry,stop', [(None, 90), (100, None), (100, 100), (100, 110)])
    def test_unpriceable_plan_is_none(self, entry, stop):
        assert rm.build_plan(entry, stop, self._targets(), atr=5.0) is None

    def test_empty_ladder_is_a_plan_with_no_rungs(self):
        # distinct from an unpriceable plan: the risk IS known, there is just
        # nothing above to aim at
        plan = rm.build_plan(100, 90, [], atr=5.0)
        assert plan is not None
        assert plan['targets'] == []
        assert plan['risk_per_share'] == pytest.approx(10.0)


class TestExpectedValue:
    def test_no_plan_reports_unavailable_not_zero(self):
        ev = rm.expected_value(None, 1.0, 2.0)
        assert ev['expected_R'] is None
        assert ev['probability_source'] == 'unavailable'
        assert ev['confidence'] == 'none'

    def test_downside_is_exactly_one_r(self):
        plan = rm.build_plan(100, 90, [{'price': 120}], atr=5.0)
        ev = rm.expected_value(plan, 1.0, 2.0)
        # by construction — R is defined as the distance to the stop
        assert ev['downside_R'] == -1.0

    def test_never_claims_historical_provenance(self):
        """
        The guard that matters most: `config.expectancy` is measured but NOT
        conditioned on setup quality, so labelling it 'historical_analogs' would
        overstate what the number knows. Nothing may emit that label until a
        real per-setup sample exists.
        """
        plan = rm.build_plan(100, 90, [{'price': 120}], atr=5.0)
        ev = rm.expected_value(plan, 1.0, 2.0)
        assert ev['probability_source'] == 'measured_baseline'
        assert ev['probability_source'] != 'historical_analogs'
        assert ev['confidence'] == 'low'
        assert ev['probability_source'] in rm.PROBABILITY_SOURCES
