import sys
import unittest
from copy import deepcopy
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT/'tests'))
from energy_model.q2.annual import EnergyModel
from energy_model.q2.contracts import award_contract, validate_contract
from energy_model.q2.finance import project_value
from q2_cases import annual_case
from test_q2_lifecycle import life


def award(**changes):
    return {'id':'test_award','known_year':2023,'start_year':2024,'end_year':2024,
            'output_carrier':'electricity','price_mode':'premium','price_per_mwh':10.,
            'payer':'government','source_or_assumption':'Synthetic contract, no Chinese policy claim',**changes}


def offer(**changes):
    terms=dict(application_from_year=2024,application_through_year=2025,
               commission_by_year=2026,support_years=2)
    terms.update(changes)
    return {k:v for k,v in award(**terms).items()
            if k not in ('start_year','end_year')}


def case():
    c=annual_case();c['mechanisms']['investment']=False
    c['policies'][0]['operating_support_budget']=100.
    next(a for a in c['assets'] if a['component']=='gas_power')['revenue_contract']=award()
    return c


class Q2ContractTests(unittest.TestCase):
    def test_contract_changes_cash_not_resource_cost_and_expires(self):
        c=case();r=EnergyModel(c).run()
        base=deepcopy(c)
        for a in base['assets']:a.pop('revenue_contract',None)
        b=EnergyModel(base).run()
        paid=[t for t in r['cash'] if t['reason']=='operating_contract_support']
        self.assertEqual(len(paid),1);self.assertEqual(paid[0]['year'],2024)
        self.assertAlmostEqual(paid[0]['amount'],20.)
        self.assertEqual(paid[0]['asset'],'gas_power_asset')
        for a,z in zip(r['annual'],b['annual']):
            self.assertAlmostEqual(a['total_resource_cost'],z['total_resource_cost'])
            self.assertAlmostEqual(a['gross_energy_co2_t'],z['gross_energy_co2_t'])
            self.assertAlmostEqual(a['cash_residual'],0.)
        self.assertEqual(r['annual'][1]['operating_support_paid'],0.)

    def test_fixed_total_price_does_not_pay_full_tariff_twice(self):
        c=case();a=next(a for a in c['assets'] if a['component']=='gas_power')
        a['revenue_contract']=award(price_mode='fixed_total_price',price_per_mwh=8.)
        r=EnergyModel(c).run()
        payment=sum(t['amount'] for t in r['cash'] if t['reason']=='operating_contract_support')
        self.assertAlmostEqual(payment,2.*(8.-6.))
        a['revenue_contract']['price_per_mwh']=4.
        r=EnergyModel(c).run()
        self.assertAlmostEqual(sum(t['amount'] for t in r['cash'] if t['reason']=='operating_contract_clawback'),4.)
        self.assertEqual(r['annual'][0]['operating_support_paid'],0.)

    def test_fiscal_budget_and_cohort_entitlement_are_physical_flow_constraints(self):
        c=case();c['policies'][0]['operating_support_budget']=5.
        r=EnergyModel(c).run()
        self.assertAlmostEqual(r['annual'][0]['operating_support_paid'],5.)
        self.assertAlmostEqual(r['annual'][0]['service_shortfalls']['building'],4.5)
        c=case();copy=deepcopy(next(a for a in c['assets'] if a['component']=='gas_power'))
        copy['id']='new_without_award';copy.pop('revenue_contract');c['assets'].append(copy)
        r=EnergyModel(c).run()
        self.assertAlmostEqual(r['annual'][0]['operating_support_paid'],10.)

    def test_known_offer_is_awarded_only_inside_application_and_commission_windows(self):
        o=offer()
        self.assertIsNone(award_contract(o,2023,2025))
        self.assertIsNone(award_contract(o,2026,2028))
        self.assertIsNone(award_contract(o,2025,2027))
        a=award_contract(o,2024,2026)
        self.assertEqual((a['start_year'],a['end_year']),(2026,2027))
        o['known_year']=2025
        self.assertIsNone(award_contract(o,2024,2026))

    def test_contract_present_value_uses_only_eligible_operating_years(self):
        c=annual_case();c['policies'][0]['operating_support_budget']=100.
        o=c['investment_options'][0];o['economic_life']=4.;o['discount_rate']=.1
        o['revenue_contract']=offer(price_mode='fixed_total_price',price_per_mwh=8.)
        m=EnergyModel(c);policy=m.visible_policy();result={'flows':[]}
        contract,adjustments=m.expected_contract_cash(o,m.component('process','solar_power'),policy,result)
        self.assertEqual(adjustments,[2.,2.,0.,0.])
        v=project_value(o,1.,3.,operating_adjustments=adjustments)
        self.assertAlmostEqual(v['known_contract_present_value'],2./1.1**2+2./1.1**3)
        self.assertEqual(v['expected_operating_cash_by_operating_year'],[5.,5.,3.,3.])
        r=m.run()
        p=next(p for p in r['projects'] if p['id']=='solar_build@2024')
        self.assertEqual(p['revenue_contract']['end_year'],2027)
        for a in r['assets']:
            if a['id']=='solar_build@2024':self.assertEqual(a['revenue_contract']['end_year'],2027)
        payments=[t for t in r['cash'] if t.get('asset')=='solar_build@2024']
        self.assertTrue(payments)
        self.assertTrue(all(2026<=t['year']<=2027 for t in payments))
        for adjustments in ([1.], [1.,2.,float('nan'),0.]):
            with self.assertRaises(ValueError):project_value(o,1.,3.,operating_adjustments=adjustments)

    def test_unknown_future_contract_cannot_change_past_decisions(self):
        c=annual_case();c['policies'][0]['operating_support_budget']=100.
        base=EnergyModel(c).run()
        c['investment_options'][0]['revenue_contract']=offer(known_year=2027,price_per_mwh=10000.,
                                                           application_through_year=2030,commission_by_year=2035)
        changed=EnergyModel(c).run()
        for key in ('annual','actions','cash','projects'):
            self.assertEqual([r for r in base[key] if r['year']<2027],
                             [r for r in changed[key] if r['year']<2027])
        self.assertTrue(any('expected_revenue_contract' in a for a in changed['actions'] if a['year']==2027))

    def test_exit_loss_history_includes_only_own_cohort_contract_income(self):
        c=case();a=next(a for a in c['assets'] if a['component']=='gas_power')
        a['fixed_om_per_unit']=10.;a['lifecycle']=life(years=30)
        a['lifecycle']['exit_rule']={'mothball_after_loss_years':1,'retire_after_loss_years':2,
            'retirement_permitted':False,'known_year':2024,'permit_effective_year':2024,'retirement_cost_per_unit':0.}
        r=EnergyModel(c).run()
        action=next(r for r in r['actions'] if r.get('asset')=='gas_power_asset' and 'settled_asset_margin' in r)
        self.assertAlmostEqual(action['settled_asset_margin'],14.)
        self.assertEqual(action['consecutive_loss_years'],0)

    def test_incomplete_contract_or_missing_fiscal_budget_rejected(self):
        c=case();del c['policies'][0]['operating_support_budget']
        with self.assertRaises(KeyError):EnergyModel(c)
        c=case();a=next(a for a in c['assets'] if a['component']=='gas_power')
        for field,value in [('price_per_mwh',-1.),('price_mode','ambiguous_tariff'),
                            ('known_year',2030),('output_carrier','gas'),('payer','generation')]:
            changed=deepcopy(c)
            next(a for a in changed['assets'] if a['component']=='gas_power')['revenue_contract'][field]=value
            with self.subTest(field=field):
                with self.assertRaises(ValueError):EnergyModel(changed)

    def test_missing_contract_dates_fail_explicitly(self):
        for is_offer, record, fields in [(False, award(), ('start_year','end_year')),
                (True, offer(), ('application_from_year','application_through_year','commission_by_year','support_years'))]:
            for field in fields:
                changed=deepcopy(record);del changed[field]
                with self.subTest(field=field):
                    with self.assertRaisesRegex(ValueError,'Integer contract'):
                        validate_contract(changed,offer=is_offer)

    def test_initial_queue_requires_deadline_and_cannot_keep_missed_award(self):
        c=annual_case();c['mechanisms']['investment']=False
        c['policies'][0]['operating_support_budget']=100.
        p={'id':'opening_solar','option':'solar_build','owner':'generation','kind':'process',
           'component':'solar_power','quantity':1.,'applied_year':2023,'online_year':2025,
           'lead_years':2,'cost':.1,'remaining_cost':.05,'construction_fractions':[.5,.5],
           'state':'building','replaces':None,'fixed_om_per_unit':0.,'replacement_units':0.,
           'revenue_contract':award(start_year=2025,end_year=2026)}
        c['initial_projects']=[p];c['other_accounts']['escrow']=.05
        with self.assertRaisesRegex(ValueError,'explicit commissioning deadline'):EnergyModel(c)
        p['revenue_contract']['commission_by_year']=2025
        r=EnergyModel(c).run()
        self.assertTrue(any(t.get('asset')=='opening_solar' for t in r['cash']))
        m=EnergyModel(c);m.step()
        # A caller attempting to resume commissioning after the award deadline
        # must not silently retain the old entitlement.
        m.year=2026
        with self.assertRaisesRegex(ValueError,'missed awarded contract deadline'):
            m.run()


if __name__=='__main__':unittest.main()
