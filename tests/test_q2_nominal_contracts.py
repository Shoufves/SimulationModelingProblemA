"""Nominal tariffs settle by year without giving investors future currency data."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tests'))
from energy_model.q2.annual import EnergyModel
from energy_model.q2.contracts import award_contract, settlement_price
from q2_cases import annual_case
from test_q2_contracts import award, offer, case


def conversions(config, factors=None):
    """Synthetic money units isolate the conversion arithmetic from real data."""
    config['model_currency'] = 'test_real_currency'
    template = deepcopy(config['policies'][0])
    template['operating_support_budget'] = 100.
    config['policies'] = []
    for year in range(config['start_year'], config['end_year'] + 1):
        policy = deepcopy(template)
        policy.update(id=f'currency_{year}', known_year=year, effective_year=year,
                      currency_conversions={'test_nominal_currency': dict(
                          factor=(factors or {}).get(year, .1), model_currency='test_real_currency',
                          conversion_year=year, known_year=year,
                          source_or_assumption='Synthetic year-end signal; no historical data claim')})
        config['policies'].append(policy)
    return config


class NominalContractTests(unittest.TestCase):
    def test_converted_total_tariff_equals_explicit_model_price_not_double_payment(self):
        base = case()
        base['end_year'] = 2024
        asset = next(a for a in base['assets'] if a['component'] == 'gas_power')
        asset['revenue_contract'] = award(price_mode='fixed_total_price', price_per_mwh=8.)
        indexed = conversions(deepcopy(base))
        nominal = next(a for a in indexed['assets'] if a['component'] == 'gas_power')['revenue_contract']
        nominal.update(price_per_mwh=80., nominal_currency='test_nominal_currency')
        a, b = EnergyModel(base).run(), EnergyModel(indexed).run()
        for key in ('annual', 'cash', 'operations'):
            self.assertEqual(a[key], b[key])
        self.assertAlmostEqual(b['annual'][0]['operating_support_paid'], 4.)

    def test_same_nominal_award_can_change_from_support_to_clawback(self):
        config = conversions(case(), {2024: .1, 2025: .05})
        config['end_year'] = 2025
        contract = next(a for a in config['assets'] if a['component'] == 'gas_power')['revenue_contract']
        contract.update(price_mode='fixed_total_price', price_per_mwh=80., end_year=2025,
                        nominal_currency='test_nominal_currency')
        result = EnergyModel(config).run()
        self.assertGreater(result['annual'][0]['operating_support_paid'], 0.)
        self.assertEqual(result['annual'][1]['operating_support_paid'], 0.)
        self.assertGreater(result['annual'][1]['operating_support_clawback'], 0.)
        self.assertTrue(all(abs(row['cash_residual']) < 1e-8 for row in result['annual']))
        self.assertEqual(contract['price_per_mwh'], 80.)

    def test_award_retains_nominal_units_and_expectation_uses_current_conversion(self):
        config = conversions(annual_case())
        option = config['investment_options'][0]
        option['economic_life'] = 4.
        option['revenue_contract'] = offer(price_mode='fixed_total_price', price_per_mwh=80.,
                                           nominal_currency='test_nominal_currency')
        contract = award_contract(option['revenue_contract'], 2024, 2026)
        self.assertEqual(contract['nominal_currency'], 'test_nominal_currency')
        self.assertEqual(contract['price_per_mwh'], 80.)
        model = EnergyModel(config)
        _, adjustment = model.expected_contract_cash(option, model.component('process', 'solar_power'),
                                                     model.visible_policy(), {'flows': []})
        self.assertEqual(adjustment, [2., 2., 0., 0.])

    def test_future_realized_conversion_cannot_change_earlier_investment_or_cash(self):
        config = conversions(annual_case())
        config['investment_options'][0]['revenue_contract'] = offer(
            price_mode='fixed_total_price', price_per_mwh=80., nominal_currency='test_nominal_currency')
        changed = deepcopy(config)
        for policy in changed['policies']:
            if policy['effective_year'] >= 2026:
                policy['currency_conversions']['test_nominal_currency']['factor'] = .2
        before, after = EnergyModel(config).run(), EnergyModel(changed).run()
        for key in ('annual', 'actions', 'cash', 'projects', 'assets', 'information', 'operations'):
            self.assertEqual([r for r in before[key] if r['year'] < 2026],
                             [r for r in after[key] if r['year'] < 2026])
        self.assertNotEqual(before['cash'], after['cash'])

    def test_missing_year_is_not_silently_forward_filled(self):
        config = conversions(case())
        config['end_year'] = 2025
        contract = next(a for a in config['assets'] if a['component'] == 'gas_power')['revenue_contract']
        contract.update(end_year=2025, nominal_currency='test_nominal_currency')
        config['policies'] = config['policies'][:1]
        model = EnergyModel(config)
        model.step()
        with self.assertRaisesRegex(ValueError, 'current-year currency conversion'):
            model.step()
        with self.assertRaisesRegex(ValueError, 'explicit current year'):
            settlement_price(contract, config['policies'][0])

    def test_wrong_target_missing_evidence_or_invalid_factor_rejected(self):
        config = conversions(case())
        contract = next(a for a in config['assets'] if a['component'] == 'gas_power')['revenue_contract']
        contract['nominal_currency'] = 'test_nominal_currency'
        for key, value in [('factor', 0.), ('factor', float('nan')), ('model_currency', 'wrong_currency'),
                           ('known_year', 2030), ('conversion_year', 2025), ('source_or_assumption', '')]:
            changed = deepcopy(config)
            changed['policies'][0]['currency_conversions']['test_nominal_currency'][key] = value
            with self.subTest(key=key, value=value):
                with self.assertRaises(ValueError):
                    EnergyModel(changed)
        del config['model_currency']
        with self.assertRaisesRegex(ValueError, 'explicit model_currency'):
            EnergyModel(config)
        contract['price_per_mwh'] = 1e308
        config['policies'][0]['currency_conversions']['test_nominal_currency']['factor'] = 2.
        with self.assertRaisesRegex(ValueError, 'converted contract price'):
            settlement_price(contract, config['policies'][0], 2024)

    def test_fiscal_cap_is_applied_after_currency_conversion(self):
        config = conversions(case())
        config['end_year'] = 2024
        config['policies'][0]['operating_support_budget'] = 1.
        contract = next(a for a in config['assets'] if a['component'] == 'gas_power')['revenue_contract']
        contract.update(price_mode='fixed_total_price', price_per_mwh=80., nominal_currency='test_nominal_currency')
        result = EnergyModel(config).run()
        self.assertAlmostEqual(result['annual'][0]['operating_support_paid'], 1.)
        self.assertAlmostEqual(result['annual'][0]['cash_residual'], 0.)


if __name__ == '__main__':
    unittest.main()
