"""Finite deployment envelopes, information boundaries and fixed-limit controls."""
import sys
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
sys.path.insert(0, str(ROOT/'tests'))
sys.path.insert(0, str(ROOT/'scripts'))
from energy_model.q2.annual import EnergyModel
from energy_model.q2.deployment import frontier_rows
from test_q2_investment_groups import grouped_case
import build_q2_deployment_candidate as candidate


def frontier_case(construction='technology_frontiers', connection='technology_frontiers'):
    config = grouped_case()
    config['investment_options'] = [o for o in config['investment_options'] if o['kind']=='process']
    config['investment_groups'][0]['maximum_total_units'] = 100.
    policy = config['policies'][0]
    policy.update(construction_units_limit=.25, connection_limit=.5,
                  deployment_limit_rules={'construction':construction, 'connection':connection})
    return config


class DeploymentTests(unittest.TestCase):
    def test_shared_cohorts_are_counted_once_and_policy_not_mutated(self):
        model = EnergyModel(frontier_case())
        policy = model.visible_policy()
        self.assertEqual(policy['construction_units_limit'], 3.)
        self.assertEqual(policy['connection_limit'], 3.)
        self.assertEqual(len(policy['deployment_frontier_snapshot']), 1)
        self.assertEqual(model.config['policies'][0]['construction_units_limit'], .25)
        self.assertEqual(policy['deployment_reference_limits']['connection_limit'], .5)

    def test_queue_never_expands_productive_construction_capacity(self):
        model = EnergyModel(frontier_case())
        policy = model.visible_policy()
        model.approve([{'option':'solar_build','owner':'generation','quantity':3.,'benefit_per_cost':1.}], policy)
        row = frontier_rows(model)[0]
        self.assertEqual(row['annual_limit_MW'], 3.)
        self.assertEqual(row['remaining_total_headroom_MW'], 96.)
        asset = next(a for a in model.assets if a['component']=='solar_power')
        asset['quantity'] = 5.
        self.assertEqual(frontier_rows(model)[0]['annual_limit_MW'], 10.)
        asset['state'] = 'mothballed'
        self.assertEqual(frontier_rows(model)[0]['annual_limit_MW'], 3.)

    def test_future_knowledge_or_permit_does_not_expand_connection_frontier(self):
        for field in ('known_year', 'permit_known_year', 'permit_effective_year'):
            config = frontier_case()
            option = next(o for o in config['investment_options'] if o['id']=='solar_vintage2')
            option['connection_per_unit'] = 100.
            option[field] = 2025
            model = EnergyModel(config)
            self.assertEqual(model.visible_policy()['connection_limit'], 3.)
            model.year = 2025
            self.assertEqual(model.visible_policy()['connection_limit'], 300.)

    def test_empty_eligible_set_means_finite_zero_capacity(self):
        config = frontier_case()
        for option in config['investment_options']: option['permit_effective_year'] = 2030
        model = EnergyModel(config)
        policy = model.visible_policy()
        self.assertEqual(policy['construction_units_limit'], 0.)
        self.assertEqual(policy['connection_limit'], 0.)
        self.assertEqual(policy['deployment_frontier_snapshot'], [])

    def test_one_fixed_constraint_cannot_be_bypassed_by_changing_other(self):
        proposals = [{'option':'solar_build','owner':'generation','quantity':3.,'benefit_per_cost':1.}]
        for construction, connection, expected in (
                ('technology_frontiers','fixed_global',.5),
                ('fixed_global','technology_frontiers',.25),
                ('technology_frontiers','technology_frontiers',3.)):
            model = EnergyModel(frontier_case(construction, connection))
            model.approve(proposals, model.visible_policy())
            self.assertEqual(sum(p['quantity'] for p in model.projects), expected)
            self.assertAlmostEqual(model.accounts['escrow'], sum(p['remaining_cost'] for p in model.projects))

    def test_cash_total_headroom_and_permit_remain_binding(self):
        config = frontier_case()
        config['investment_groups'][0]['maximum_total_units'] = 1.1
        model = EnergyModel(config)
        self.assertAlmostEqual(model.visible_policy()['construction_units_limit'], .1)
        next(o for o in model.config['investment_options'] if o['id']=='solar_build')['permit_effective_year'] = 2030
        proposals = [{'option':'solar_build','owner':'generation','quantity':3.,'benefit_per_cost':1.}]
        model.approve(proposals, model.visible_policy())
        self.assertFalse(model.projects)
        model = EnergyModel(frontier_case())
        model.sectors['generation'].cash = .01
        model.approve(proposals, model.visible_policy())
        self.assertAlmostEqual(sum(p['quantity'] for p in model.projects), .1)

    def test_invalid_modes_mixed_units_and_unshared_cohorts_fail(self):
        config = frontier_case(); config['policies'][0]['deployment_limit_rules']['construction'] = 'infinite'
        with self.assertRaisesRegex(ValueError, 'deployment rules'): EnergyModel(config)
        config = grouped_case(); config['policies'][0]['deployment_limit_rules'] = {
            'construction':'technology_frontiers','connection':'technology_frontiers'}
        with self.assertRaisesRegex(ValueError, 'unit-MW'): EnergyModel(config)
        config = frontier_case(); config['investment_groups'] = []
        for option in config['investment_options']: option.pop('investment_group')
        with self.assertRaisesRegex(ValueError, 'cohorts'): EnergyModel(config)

    def test_legacy_policy_has_identical_snapshot(self):
        config = grouped_case()
        self.assertEqual(EnergyModel(config).visible_policy(), config['policies'][0])

    def test_frozen_candidate_has_no_new_parameters_or_changed_initial_state(self):
        _, parent, selected = candidate.load_parent()
        result = candidate.build()
        control = parent['structural_models'][selected['structure']]
        self.assertEqual(result['structural_models']['v6_control'], control)
        self.assertEqual(result['experiment']['parameters'], [])
        for name, model in result['structural_models'].items():
            for key in ('assets','initial_projects','agents','other_accounts','investment_options','investment_groups','gdp_growth','cost_decline'):
                self.assertEqual(model[key], control[key], (name,key))
        self.assertEqual(result['observations'], parent['observations'])
        self.assertEqual(result['acceptance'], parent['acceptance'])


if __name__ == '__main__': unittest.main()
