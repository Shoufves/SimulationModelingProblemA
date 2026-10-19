"""Activity changes service before dispatch; no fuel or GDP double counting."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tests'))
from energy_model.q2.annual import EnergyModel
from q2_cases import annual_case


def activity_case():
    model = annual_case()
    series = dict(id='test_mobility_activity', unit='passenger_km', boundary='declared_test_group',
        base_year=2024, information_role='realized_current_year_operation_only',
        records=[dict(year=y, value=v, unit='passenger_km', boundary='declared_test_group',
                      status='scenario_assumption', source_or_assumption='hand-solvable test activity')
                 for y, v in zip(range(2024, 2029), [100., 200., 0., 150., 100.])])
    model['demand_drivers']['mobility'] = dict(activity_series=series, annual_intensity_improvement=0.)
    return model


def demanded(result, year):
    op = next(r['input'] for r in result['operations'] if r['year'] == year)
    return next(s['demand'][0] for s in op['services'] if s['id'] == 'mobility')


class ActivityDriverTests(unittest.TestCase):
    def test_activity_changes_service_and_explicit_zero_is_not_missing(self):
        result = EnergyModel(activity_case()).run()
        self.assertEqual([demanded(result, y) for y in range(2024, 2029)], [2., 4., 0., 3., 2.])
        signals = [r['realized_activity_signals']['mobility'] for r in result['information']]
        self.assertEqual([r['value'] for r in signals], [100., 200., 0., 150., 100.])
        self.assertTrue(all('records' not in r for r in signals))

    def test_gdp_not_applied_again_to_explicit_activity(self):
        model = activity_case()
        for name, driver in model['demand_drivers'].items():
            if name != 'mobility':
                driver['gdp_elasticity'] = 0.
        original = EnergyModel(model).run()
        model['gdp_growth'] = {y: .5 for y in model['gdp_growth']}
        self.assertEqual(EnergyModel(model).run(), original)
        model['demand_drivers']['mobility']['gdp_elasticity'] = 1.
        with self.assertRaisesRegex(ValueError, 'do not multiply both'):
            EnergyModel(model)

    def test_device_efficiency_does_not_reduce_desired_service_twice(self):
        model = activity_case()
        model['demand_drivers']['mobility']['annual_intensity_improvement'] = .1
        before = EnergyModel(model).run()
        next(d for d in model['operation']['devices'] if d['id'] == 'car')['service_per_mwh'] = 2.
        after = EnergyModel(model).run()
        self.assertEqual(demanded(before, 2025), demanded(after, 2025))
        self.assertAlmostEqual(demanded(after, 2025), 3.6)
        def fuel(result):
            op = next(r['result'] for r in result['operations'] if r['year'] == 2025)
            return sum(r['value'] for r in op['flows'] if r['kind'] == 'device' and r['id'] == 'car')
        self.assertAlmostEqual(fuel(after) * 2, fuel(before))

    def test_future_activity_does_not_change_past_full_ledgers(self):
        model = activity_case()
        base = EnergyModel(model).run()
        for row in model['demand_drivers']['mobility']['activity_series']['records']:
            if row['year'] >= 2027:
                row['value'] *= 2
        changed = EnergyModel(model).run()
        for field in ('annual', 'assets', 'projects', 'actions', 'information', 'cash', 'operations'):
            self.assertEqual([r for r in base[field] if r['year'] < 2027],
                             [r for r in changed[field] if r['year'] < 2027], field)
        self.assertNotEqual(demanded(base, 2027), demanded(changed, 2027))

    def test_missing_duplicate_and_mixed_boundaries_are_rejected(self):
        for mode in ('missing', 'duplicate', 'unit', 'boundary', 'source', 'status', 'base_year', 'record', 'none'):
            model = activity_case()
            series = model['demand_drivers']['mobility']['activity_series']
            if mode == 'missing': series['records'].pop(1)
            elif mode == 'duplicate': series['records'].append(deepcopy(series['records'][0]))
            elif mode in ('unit', 'boundary'): series['records'][1][mode] = 'another_definition'
            elif mode == 'source': series['records'][1]['source_or_assumption'] = ''
            elif mode == 'status': series['records'][1]['status'] = 'unknown'
            elif mode == 'base_year': series['base_year'] = 2023
            elif mode == 'record': series['records'][1] = None
            else: model['demand_drivers']['mobility']['activity_series'] = None
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                EnergyModel(model)

    def test_invalid_numbers_zero_base_and_normalization_overflow_rejected(self):
        for value in (True, -1., float('nan'), float('inf'), 0., 5e-324):
            model = activity_case()
            rows = model['demand_drivers']['mobility']['activity_series']['records']
            rows[0]['value'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                EnergyModel(model)

    def test_training_prefix_may_retain_unread_future_activity_records(self):
        model = activity_case()
        whole = EnergyModel(model).run()
        model['end_year'] = 2025
        prefix = EnergyModel(model).run()
        for field in ('annual', 'actions', 'information', 'cash', 'operations'):
            self.assertEqual(prefix[field], [r for r in whole[field] if r['year'] <= 2025])

    def test_reported_rail_activity_drives_a_separate_synthetic_service(self):
        # Actual passenger-km; synthetic 2-unit service scale and device. This
        # tests plumbing, never establishes a national rail fuel intensity.
        series = json.loads((ROOT / 'data/processed/q2/transport_activity_series.json').read_text(encoding='utf-8'))['C16-06:rail']
        model = annual_case()
        model.update(start_year=2014, end_year=2024,
                     gdp_growth={str(y): 0. for y in range(2015, 2025)})
        for asset in model['assets']:
            asset['online_year'] = 2014
        for option in model['investment_options']:
            for key in ('known_year', 'permit_known_year', 'permit_effective_year', 'cost_reference_year'):
                option[key] = 2014
        for policy in model['policies']:
            policy.update(known_year=2014, effective_year=2014)
        model['demand_drivers']['mobility'] = dict(activity_series=series, annual_intensity_improvement=0.)
        result = EnergyModel(model).run()
        for row in series['records']:
            self.assertAlmostEqual(demanded(result, row['year']), 2. * row['value'] / 11241.9)
        self.assertLess(demanded(result, 2020), demanded(result, 2019))
        self.assertGreater(demanded(result, 2024), demanded(result, 2019))


if __name__ == '__main__':
    unittest.main()
