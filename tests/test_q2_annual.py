import sys
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src')); sys.path.insert(0,str(ROOT/'tests'))
from energy_model.q2.annual import EnergyModel
from q2_cases import annual_case


class Q2AnnualTests(unittest.TestCase):
    def test_real_mesa_agents_and_queued_commissioning(self):
        from mesa import Agent, Model
        model = EnergyModel(annual_case())
        self.assertIsInstance(model,Model)
        self.assertEqual(len(model.agents),7)
        self.assertTrue(all(isinstance(a,Agent) for a in model.agents))
        result = model.run()
        self.assertTrue(result['projects'])
        for p in result['projects']:
            self.assertGreater(p['online_year'],p['applied_year'])
        first = [a for a in result['assets'] if a['component']=='solar_power' and a['quantity']>0]
        self.assertEqual(min(a['year'] for a in first),2026)
        self.assertTrue(all(abs(r['cash_residual'])<1e-8 for r in result['annual']))

    def test_mechanism_switch_changes_future_operation(self):
        c = annual_case(); enabled=EnergyModel(c).run()
        c['mechanisms']['investment']=False; disabled=EnergyModel(c).run()
        self.assertEqual(enabled['annual'][0]['gross_energy_co2_t'],disabled['annual'][0]['gross_energy_co2_t'])
        self.assertLess(enabled['annual'][-1]['gross_energy_co2_t'],disabled['annual'][-1]['gross_energy_co2_t'])
        self.assertFalse(disabled['projects'])

    def test_future_policy_cannot_change_past_actions_or_operations(self):
        c = annual_case(); base=EnergyModel(c).run()
        future=deepcopy(c['policies'][0]); future.update(id='future',known_year=2027,effective_year=2027,carbon_price_per_t=500.)
        c['policies'].append(future); changed=EnergyModel(c).run()
        for field in ('annual','actions','information','cash','operations'):
            self.assertEqual([r for r in base[field] if r['year']<2027],[r for r in changed[field] if r['year']<2027])

    def test_permanent_exit_cannot_be_reversed(self):
        c=annual_case()
        c['asset_events']=[{'id':'retire','asset':'gas_power_asset','known_year':2024,'effective_year':2025,'new_state':'retired','permit_granted':True},
                           {'id':'restart','asset':'gas_power_asset','known_year':2024,'effective_year':2026,'new_state':'operating','permit_granted':True}]
        with self.assertRaisesRegex(ValueError,'cannot be reversed'): EnergyModel(c).run()

    def test_unknown_permit_prevents_approval(self):
        c=annual_case()
        for o in c['investment_options']: o['permit_known_year']=2030
        result=EnergyModel(c).run()
        self.assertFalse(result['projects'])

    def test_cash_commitment_and_connection_are_joint_limits(self):
        c=annual_case(); c['policies'][0]['connection_limit']=.25
        result=EnergyModel(c).run()
        approvals=[a for a in result['actions'] if a.get('approved_units',0)>0]
        for year in range(2024,2029):
            self.assertLessEqual(sum(a['approved_units'] for a in approvals if a['year']==year),.25+1e-8)
        for r in result['annual']:
            self.assertAlmostEqual(r['committed_cash'],r['accounts']['escrow'])
            self.assertTrue(all(v>=-1e-8 for v in r['agent_cash'].values()))

    def test_nonzero_lead_and_all_agent_roles_required(self):
        c=annual_case(); c['investment_options'][0]['lead_years']=0
        with self.assertRaises(ValueError): EnergyModel(c)
        c=annual_case(); c['agents'].pop()
        with self.assertRaises(ValueError): EnergyModel(c)

    def test_order_of_agents_does_not_allocate_shared_resources(self):
        c=annual_case(); a=EnergyModel(c).run()
        c['agents'].reverse(); b=EnergyModel(c).run()
        self.assertEqual(a,b)


if __name__=='__main__': unittest.main()
