"""
The trade thesis.

The property under test is mostly NEGATIVE: the thesis must not invent anything.
Every field has to trace back to a value the pipeline already produced, and the
places where it declines to answer (a broken chart has no thesis) matter as much
as the places where it does.
"""

from __future__ import annotations

import pytest

import thesis


class TestDeclinesWhereThereIsNoTrade:
    @pytest.mark.parametrize('state', ['broken', 'avoid', 'nothing_yet'])
    def test_dead_states_have_no_thesis(self, state):
        """Manufacturing a thesis here would put an argument FOR entering
        underneath a verdict that says stay away."""
        v = {'state': state, 'action': 'out', 'report': {}, 'r_multiple': {}}
        assert thesis.build(_sig(), v, [], {'entry': 1, 'stop': 0.5}) is None


class TestAssemblesFromExistingOutput:
    def test_core_fields_are_sourced_not_invented(self, analyses):
        for tk, r in analyses.items():
            m = r['micha']
            t = m['trade_thesis']
            if t is None:
                assert m['state'] in ('broken', 'avoid', 'nothing_yet')
                continue
            # entry/stop must be the SAME numbers as the option the reader is
            # pointed at — a thesis quoting a different plan is the mismatch
            # `_best_option` exists to prevent
            rmp = m['r_multiple'] or {}
            assert t['entry_price'] == rmp.get('entry'), f'{tk} entry disagrees'
            assert t['stop_price'] == rmp.get('stop'), f'{tk} stop disagrees'
            assert t['targets'] == (rmp.get('targets') or []), f'{tk} ladder disagrees'
            # the read is the report's own sentence, not a new one
            assert t['entry_reason'] == m['report']['read']

    def test_state_and_action_match_the_verdict(self, analyses):
        for tk, r in analyses.items():
            m, t = r['micha'], r['micha']['trade_thesis']
            if t is None:
                continue
            assert t['state'] == m['state']
            assert t['action'] == m['action']

    def test_every_target_carries_an_r_multiple(self, analyses):
        for tk, r in analyses.items():
            t = r['micha']['trade_thesis']
            if not t:
                continue
            for rung in t['targets']:
                assert rung['r'] is not None, f'{tk} T{rung["n"]} has no R'
                assert rung['r'] > 0

    def test_carries_both_sides_of_the_argument(self, analyses):
        """A thesis listing only supporting evidence is advocacy. At least one
        name in the sample must carry conflicting signals, or the field is not
        actually being populated."""
        with_conflict = [tk for tk, r in analyses.items()
                         if (r['micha']['trade_thesis'] or {}).get('conflicting_signals')]
        assert with_conflict, 'no thesis carried a conflicting signal — check wiring'

    def test_invalidation_is_present_for_a_live_trade(self, analyses):
        for tk, r in analyses.items():
            m, t = r['micha'], r['micha']['trade_thesis']
            if not t or m['action'] != 'enter':
                continue
            assert t['invalidation_conditions'], (
                f'{tk} is an ENTER with no stated invalidation — "where am I '
                f'wrong" must always be answerable on a live trade')

    def test_serializable(self, analyses):
        import json
        for r in analyses.values():
            json.dumps(r['micha']['trade_thesis'])


def _sig():
    from verdict import Signals
    return Signals()
