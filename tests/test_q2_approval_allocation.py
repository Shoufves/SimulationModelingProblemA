"""Hand-checkable constrained allocation and exact legacy behavior."""
from copy import deepcopy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tests'))
from energy_model.q2.annual import EnergyModel
from energy_model.q2.deployment import allocate_requests
from test_q2_deployment import frontier_case


def case():
    config = frontier_case('fixed_global', 'fixed_global')
    config['policies'][0].update(approval_allocation='proportional_requests',
        construction_units_limit=2., connection_limit=2.)
    for o in config['investment_options']:
        o.update(known_year=2024, permit_known_year=2024, permit_effective_year=2024,
                 capex_per_unit=.1, connection_per_unit=1.)
    return config


def requests():
    return [dict(option=name, owner='generation', quantity=q, benefit_per_cost=b)
            for name, q, b in [('solar_build', 3., 9.), ('solar_vintage2', 1., 1.)]]


class ApprovalAllocationTests(unittest.TestCase):
    def test_group_and_shared_caps_preserve_proportion_and_funding(self):
        model = EnergyModel(case())
        proposals = requests()
        saved = deepcopy(proposals)
        allocated, audit = allocate_requests(model, proposals, model.visible_policy(), {})
        # Four requests -> shared technology cap3 -> common cap2, so1.5/.5.
        self.assertEqual([p['quantity'] for p in allocated], [1.5, .5])
        self.assertEqual([a['feasible_request_units'] for a in audit], [2.25, .75])
        self.assertEqual(proposals, saved)
        model.approve(proposals, model.visible_policy())
        self.assertEqual(sum(p['quantity'] for p in model.projects), 2.)
        self.assertTrue(all(p['online_year'] > model.year for p in model.projects))
        self.assertAlmostEqual(model.accounts['escrow'], sum(p['remaining_cost'] for p in model.projects))

    def test_binding_connection_coefficients_are_not_ignored(self):
        config = case()
        config['investment_options'][0]['connection_per_unit'] = 2.
        model = EnergyModel(config)
        allocated, _ = allocate_requests(model, requests(), model.visible_policy(), {})
        by_id = {o['id']: o for o in config['investment_options']}
        self.assertAlmostEqual(sum(p['quantity'] * by_id[p['option']]['connection_per_unit'] for p in allocated), 2.)
        self.assertAlmostEqual(allocated[0]['quantity'] / allocated[1]['quantity'], 3.)

    def test_owner_funds_shared_across_requests(self):
        model = EnergyModel(case())
        model.sectors['generation'].cash = .1
        allocated, _ = allocate_requests(model, requests(), model.visible_policy(), {})
        self.assertAlmostEqual(sum(p['quantity'] for p in allocated), 1.)
        self.assertAlmostEqual(allocated[0]['quantity'], .75)

    def test_blocked_and_future_requests_do_not_consume_common_budget(self):
        for mode in ('blocked', 'future'):
            model = EnergyModel(case())
            blocked = {'solar_build': {}} if mode == 'blocked' else {}
            if mode == 'future':
                next(o for o in model.config['investment_options'] if o['id'] == 'solar_build')['permit_known_year'] = 2025
            allocated, _ = allocate_requests(model, requests(), model.visible_policy(), blocked)
            self.assertEqual([p['quantity'] for p in allocated], [0., 1.])

    def test_default_is_exact_passthrough_and_unsupported_rule_rejected(self):
        config = case()
        del config['policies'][0]['approval_allocation']
        model = EnergyModel(config)
        proposals = requests()
        result, audit = allocate_requests(model, proposals, model.visible_policy(), {})
        self.assertIs(result, proposals)
        self.assertEqual(audit, [])
        config['policies'][0]['approval_allocation'] = 'allocate_from_future_target'
        with self.assertRaisesRegex(ValueError, 'allocation rule'):
            EnergyModel(config)

    def test_duplicate_requests_cannot_bypass_group_cap(self):
        model = EnergyModel(case())
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            allocate_requests(model, requests() + requests()[:1], model.visible_policy(), {})

    def test_application_order_does_not_change_approved_projects(self):
        forward, backward = EnergyModel(case()), EnergyModel(case())
        forward.approve(requests(), forward.visible_policy())
        backward.approve(list(reversed(requests())), backward.visible_policy())
        self.assertEqual(forward.projects, backward.projects)
        self.assertEqual(forward.cash_ledger, backward.cash_ledger)


if __name__ == '__main__':
    unittest.main()
