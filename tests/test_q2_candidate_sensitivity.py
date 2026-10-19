"""Scientific response settings retain chronology, budgets and physical units."""
import sys
import unittest
from copy import deepcopy
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import run_q2_candidate_sensitivity as response


class Q2CandidateSensitivityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _,data=response.history.load_frozen(ROOT/'workflow/q2_candidates/v5/manifest.json')
        cls.model=data['model']
        cls.baseline={'gdp_growth_multiplier':1.,'cost_decline_multiplier':1.,'carbon_price_USD2008_per_t':0.}

    def test_identity_setting_preserves_all_state_and_does_not_mutate(self):
        original=deepcopy(self.model)
        changed=response.perturb(self.model,self.baseline)
        self.assertEqual(changed,original);self.assertEqual(self.model,original)
        changed['assets'][0]['quantity']=12345
        self.assertEqual(self.model,original)

    def test_perturbation_preserves_chronology_and_relative_technology_trends(self):
        changed=response.perturb(self.model,{**self.baseline,'gdp_growth_multiplier':.8,'cost_decline_multiplier':1.5})
        for y,v in self.model['gdp_growth'].items():self.assertEqual(changed['gdp_growth'][y],v*.8)
        for k,v in self.model['cost_decline'].items():self.assertEqual(changed['cost_decline'][k],v*1.5)
        for key in ('seed','assets','agents','other_accounts','initial_projects','investment_options'):
            self.assertEqual(changed[key],self.model[key])

    def test_carbon_price_uses_million_currency_and_settles_without_creating_cash(self):
        changed=response.perturb(self.model,{**self.baseline,'carbon_price_USD2008_per_t':50.})
        changed['end_year']=2014
        row=response.history.EnergyModel(changed).run()['annual'][0]
        self.assertEqual(changed['policies'][0]['carbon_price_per_t'],.00005)
        self.assertAlmostEqual(row['compliance_transfer'],row['gross_energy_co2_t']*.00005,delta=1e-6)
        self.assertAlmostEqual(row['cash_residual'],0.,delta=1e-6)

    def test_bad_units_or_nonfinite_levels_fail(self):
        for value in (float('nan'),float('inf'),-1.,True):
            with self.assertRaises(ValueError):response.perturb(self.model,{**self.baseline,'gdp_growth_multiplier':value})
        with self.assertRaises(ValueError):response.perturb(self.model,{**self.baseline,'cost_decline_multiplier':100.})
        with self.assertRaises(ValueError):response.perturb(self.model,{**self.baseline,'carbon_price_CNY_per_t':50.})


if __name__=='__main__':unittest.main()
