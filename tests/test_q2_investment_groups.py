"""Construction limits are shared across vintages, funded, and state-based."""
import sys
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src')); sys.path.insert(0, str(ROOT / 'tests'))
from energy_model.q2.annual import EnergyModel
from q2_cases import annual_case


def grouped_case():
    c = annual_case()
    solar = next(o for o in c['investment_options'] if o['id'] == 'solar_build')
    solar['investment_group'] = 'solar'
    other = deepcopy(solar); other['id'] = 'solar_vintage2'
    c['investment_options'].append(other)
    c['cost_decline'][other['id']] = c['cost_decline'][solar['id']]
    next(a for a in c['agents'] if a['id'] == 'generation')['initial_margins']['solar_vintage2'] = 0.
    next(a for a in c['assets'] if a['component'] == 'solar_power')['quantity'] = 1.
    c['investment_groups'] = [{'id': 'solar', 'kind': 'process', 'components': ['solar_power'],
                               'annual_installation_floor': 3., 'stock_expansion_rate': 2., 'maximum_total_units': 4.}]
    return c


class Q2InvestmentGroupTests(unittest.TestCase):
    def test_two_vintages_share_limit_and_pending_headroom(self):
        m = EnergyModel(grouped_case()); policy = m.config['policies'][0]
        proposals = [{'option': identity, 'owner': 'generation', 'quantity': 2., 'benefit_per_cost': 1.}
                     for identity in ('solar_build', 'solar_vintage2')]
        m.approve(proposals, policy)
        self.assertEqual(sum(p['quantity'] for p in m.projects), 3.)
        self.assertEqual(m.group_limits(m.config['investment_groups'][0]), (3., 0.))
        self.assertAlmostEqual(m.accounts['escrow'], sum(p['remaining_cost'] for p in m.projects))
        # A second approval pass cannot reserve beyond the shared total ceiling.
        m.approve(proposals, policy)
        self.assertEqual(sum(p['quantity'] for p in m.projects), 3.)

    def test_only_productive_stock_expands_capacity(self):
        m = EnergyModel(grouped_case()); group = m.config['investment_groups'][0]
        asset = next(a for a in m.assets if a['component'] == 'solar_power')
        asset['quantity'] = 2.
        self.assertEqual(m.group_limits(group), (4., 2.))
        asset['state'] = 'mothballed'
        self.assertEqual(m.group_limits(group), (3., 2.))
        asset['state'] = 'retired'
        self.assertEqual(m.group_limits(group), (3., 4.))

    def test_cash_and_connection_still_bind_shared_groups(self):
        c = grouped_case(); c['policies'][0]['connection_limit'] = .25
        out = EnergyModel(c).run()
        for year in range(c['start_year'], c['end_year'] + 1):
            self.assertLessEqual(sum(a.get('approved_units', 0.) for a in out['actions'] if a['year'] == year), .25 + 1e-8)
        self.assertTrue(all(abs(r['cash_residual']) < 1e-8 for r in out['annual']))

    def test_options_cannot_bypass_or_overlap_groups(self):
        c = grouped_case(); c['investment_options'][0].pop('investment_group')
        with self.assertRaisesRegex(ValueError, 'bypass'): EnergyModel(c)
        c = grouped_case(); g = deepcopy(c['investment_groups'][0]); g['id'] = 'duplicate'
        c['investment_groups'].append(g)
        with self.assertRaisesRegex(ValueError, 'Overlapping'): EnergyModel(c)
        c = grouped_case(); c['investment_options'][0]['investment_group'] = 'missing'
        with self.assertRaisesRegex(ValueError, 'incompatible'): EnergyModel(c)

    def test_proposal_order_cannot_change_group_allocation(self):
        proposals = [{'option': identity, 'owner': 'generation', 'quantity': 2., 'benefit_per_cost': 1.}
                     for identity in ('solar_build', 'solar_vintage2')]
        a, b = EnergyModel(grouped_case()), EnergyModel(grouped_case())
        a.approve(proposals, a.config['policies'][0])
        b.approve(list(reversed(proposals)), b.config['policies'][0])
        self.assertEqual(a.projects, b.projects)
        self.assertEqual(a.cash_ledger, b.cash_ledger)


if __name__ == '__main__':
    unittest.main()
