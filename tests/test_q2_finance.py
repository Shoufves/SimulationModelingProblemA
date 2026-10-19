import sys
import unittest
from copy import deepcopy
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT/'tests'))
from energy_model.q2.annual import EnergyModel
from energy_model.q2.finance import project_value
from q2_cases import annual_case


class Q2FinanceTests(unittest.TestCase):
    def option(self):
        o=deepcopy(annual_case()['investment_options'][0])
        o.update(discount_rate=.1,economic_life=2.,construction_fractions=[.25,.75],
                 fixed_om_per_unit=3.,expected_terminal_value_per_unit=20.)
        return o

    def test_dated_cashflows_and_escrow_opportunity_cost_hand_calculation(self):
        v=project_value(self.option(),100.,63.)
        costs=25.+75./1.1
        operation=60./1.1**2+60./1.1**3
        terminal=20./1.1**4
        self.assertAlmostEqual(v['construction_present_value'],costs)
        self.assertAlmostEqual(v['project_npv_before_funding_lock'],operation+terminal-costs)
        self.assertAlmostEqual(v['investment_npv'],operation+terminal-100.)
        self.assertAlmostEqual(v['funding_lock_opportunity_cost'],100.-costs)

    def test_late_spending_does_not_fake_return_on_nonremunerated_escrow(self):
        front=self.option();back=deepcopy(front)
        front['construction_fractions']=[1.,0.];back['construction_fractions']=[0.,1.]
        a=project_value(front,100.,63.);b=project_value(back,100.,63.)
        self.assertGreater(b['project_npv_before_funding_lock'],a['project_npv_before_funding_lock'])
        self.assertAlmostEqual(a['investment_npv'],b['investment_npv'])

    def test_construction_delay_can_reverse_investment_decision(self):
        short=self.option();short.update(lead_years=1,construction_fractions=[1.],expected_terminal_value_per_unit=0.)
        long=deepcopy(short);long.update(lead_years=5,construction_fractions=[.2]*5)
        # Same two years' operating profit, but much later receipts cannot use
        # an immediate annuity charge to conclude the same investment decision.
        self.assertGreater(project_value(short,100.,63.)['investment_npv'],0.)
        self.assertLess(project_value(long,100.,63.)['investment_npv'],0.)

    def test_zero_discount_and_negative_terminal_disposal_value(self):
        o=self.option();o.update(discount_rate=0.,expected_terminal_value_per_unit=-10.)
        v=project_value(o,100.,63.)
        self.assertEqual(v['investment_npv'],10.)
        self.assertEqual(v['funding_lock_opportunity_cost'],0.)

    def test_invalid_or_missing_cashflow_schedule_is_not_inferred(self):
        for field,value in [('construction_fractions',[1.]),('construction_fractions',[.5,.6]),
                            ('construction_fractions',[1.1,-.1]),('economic_life',1.5),
                            ('expected_terminal_value_per_unit',float('nan')),
                            ('funding_convention','free_credit')]:
            with self.subTest(field=field,value=value):
                o=self.option();o[field]=value
                with self.assertRaises(ValueError):project_value(o,100.,63.)
        o=self.option();del o['expected_terminal_value_per_unit']
        with self.assertRaises(KeyError):project_value(o,100.,63.)

    def test_construction_transfers_follow_approved_schedule_and_commission_later(self):
        c=annual_case();c['end_year']=2026
        for o in c['investment_options']:o['construction_fractions']=[.25,.75]
        r=EnergyModel(c).run()
        p=next(p for p in r['projects'] if p['id']=='solar_build@2024' and p['year']==2026)
        payments=[t for t in r['cash'] if t['reference']==p['id'] and t['reason']=='construction_progress']
        self.assertEqual([t['year'] for t in payments],[2024,2025])
        self.assertAlmostEqual(payments[0]['amount'],p['cost']*.25)
        self.assertAlmostEqual(payments[1]['amount'],p['cost']*.75)
        self.assertEqual(p['online_year'],2026);self.assertEqual(p['remaining_cost'],0.)
        self.assertAlmostEqual(sum(t['amount'] for t in payments),p['cost'])
        for row in r['annual']:
            actual=sum(t['amount'] for t in r['cash'] if t['year']==row['year'] and t['reason']=='construction_progress')
            self.assertAlmostEqual(row['construction_resource_cost'],actual)
            self.assertAlmostEqual(row['committed_cash'],row['accounts']['escrow'])
        self.assertFalse(any(t['reason'] in ('funding_lock_opportunity_cost','terminal_value') for t in r['cash']))

    def test_initial_project_unpaid_schedule_must_match_escrow(self):
        c=annual_case();m=EnergyModel(c);o=c['investment_options'][0]
        m.approve([{'owner':o['owner'],'option':o['id'],'quantity':1.,'benefit_per_cost':1.}],m.visible_policy())
        c['start_year']=2025;c['initial_projects']=deepcopy(m.projects)
        c['other_accounts']['escrow']=m.accounts['escrow']
        EnergyModel(c)
        c['initial_projects'][0]['remaining_cost']+=.01
        c['other_accounts']['escrow']+=.01
        with self.assertRaisesRegex(ValueError,'unpaid construction schedule'):EnergyModel(c)

    def test_valuation_cannot_assume_unpermitted_operating_horizon(self):
        from test_q2_lifecycle import life
        c=annual_case();c['investment_options'][0]['lifecycle']=life(years=30,permit=2030)
        r=EnergyModel(c).run()
        proposals=[a for a in r['actions'] if a.get('option')=='solar_build' and 'investment_npv' in a]
        self.assertTrue(proposals)
        self.assertTrue(all(not a['proposed'] and not a['permission_covers_valued_operation'] for a in proposals))
        self.assertFalse(any(p['option']=='solar_build' for p in r['projects']))
        c['investment_options'][0]['lifecycle']=life(years=1)
        with self.assertRaisesRegex(ValueError,'exceeds declared technical life'):EnergyModel(c)


if __name__=='__main__':unittest.main()
