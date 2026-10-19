import sys
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tests'))
from energy_model.q2.operations import OperationError, solve_operation
from q2_cases import empty, source, process, service, device, store, shared_gas, storage_window


def flow(r, kind, identity, step=0):
    return next(v['value'] for v in r['flows'] if (v['kind'],v['id'],v['step']) == (kind,identity,step))


class Q2OperationTests(unittest.TestCase):
    def test_shared_gas_and_lexicographic_service_priority(self):
        r = solve_operation(shared_gas())
        self.assertAlmostEqual(flow(r, 'source', 'gas_supply'), 10.)
        self.assertAlmostEqual(flow(r, 'device', 'gas_heat'), 6.)
        self.assertAlmostEqual(flow(r, 'process', 'gas_power'), 2.)
        self.assertAlmostEqual(r['service_shortfalls']['building'], 3.)
        self.assertAlmostEqual(r['service_shortfalls']['industry'], 0.)
        self.assertAlmostEqual(r['totals']['gross_energy_co2_t'], 2.)

    def test_intertemporal_storage_avoids_greedy_future_shortfall(self):
        c = storage_window()
        r = solve_operation(c)
        self.assertAlmostEqual(r['service_shortfalls']['load'], 0.)
        self.assertAlmostEqual(flow(r, 'process', 'gas_power', 0), 10.)
        self.assertAlmostEqual(flow(r, 'stock', 'battery', 0), 10.)
        self.assertAlmostEqual(r['closing_stocks']['battery'], 0.)
        c['stores'] = []
        self.assertAlmostEqual(solve_operation(c)['service_shortfalls']['load'], 10.)

    def test_duration_efficiency_and_one_service_conversion(self):
        c = empty([2., 2.])
        c['sources'] = [source('solar', 'electricity', [20., 0.], nonfossil=True)]
        c['services'] = [service('heat', [0., 64.8])]
        c['devices'] = [device('heat_device', 'electricity', 'heat', efficiency=2.)]
        c['stores'] = [store(cap=40., power=20., efficiency=.9)]
        r = solve_operation(c)
        self.assertAlmostEqual(flow(r, 'charge', 'battery'), 40.)
        self.assertAlmostEqual(flow(r, 'stock', 'battery'), 36.)
        self.assertAlmostEqual(flow(r, 'discharge', 'battery', 1), 32.4)
        self.assertAlmostEqual(r['service_shortfalls']['heat'], 0.)

    def test_source_budget_is_not_per_step_budget(self):
        c = empty([1., 1.])
        c['sources'] = [source('hydro', 'electricity', [10., 10.], nonfossil=True)]
        c['sources'][0]['window_budget_mwh'] = 12.
        c['services'] = [service('load', [10., 10.])]
        c['devices'] = [device('load_device', 'electricity', 'load')]
        r = solve_operation(c)
        self.assertAlmostEqual(r['service_shortfalls']['load'], 8.)

    def test_shared_hydrogen_input_and_grid_losses(self):
        c = empty([1.]); c['nodes'] += ['hydrogen', 'delivered_electricity']
        c['sources'] = [source('power', 'electricity', [10.])]
        c['processes'] = [process('grid', {'electricity': 1.}, {'delivered_electricity': .9}, 10., [1.]),
                          process('electrolyser', {'electricity': 1.}, {'hydrogen': .7}, 10., [1.])]
        c['services'] = [service('industry', [3.5], 0), service('building', [9.], 1)]
        c['devices'] = [device('hydrogen_device', 'hydrogen', 'industry'),
                        device('electric_device', 'delivered_electricity', 'building')]
        r = solve_operation(c)
        self.assertAlmostEqual(flow(r, 'process', 'electrolyser'), 5.)
        self.assertAlmostEqual(r['service_shortfalls']['building'], 4.5)
        self.assertTrue(all(abs(x['residual_mwh']) < 1e-8 for x in r['balances']))

    def test_capture_requires_energy_and_storage(self):
        c = empty([1.]); c['sources'] = [source('fuel', 'gas', [20.])]
        p = process('capture_plant', {'gas': 2.5}, {'electricity': 1.}, 10., [1.], co2=.5)
        p['captured_co2_t_per_mwh'] = .4
        c['processes'] = [p]; c['capture_storage_budget_t'] = 2.
        c['services'] = [service('load', [10.])]
        c['devices'] = [device('load_device', 'electricity', 'load')]
        r = solve_operation(c)
        self.assertAlmostEqual(flow(r, 'process', 'capture_plant'), 5.)
        self.assertAlmostEqual(flow(r, 'source', 'fuel'), 12.5)
        self.assertAlmostEqual(r['totals']['captured_co2_t'], 2.)
        self.assertAlmostEqual(r['totals']['positive_energy_co2_t'], .5)

    def test_cyclic_weights_do_not_multiply_soc(self):
        c = storage_window(); c['stock_boundary'] = 'cyclic'; c['annual_weights'] = [100., 100.]
        r = solve_operation(c)
        self.assertAlmostEqual(flow(r, 'stock', 'battery'), 10.)
        self.assertAlmostEqual(r['totals']['primary_mwh'], 2000.)
        c['annual_weights'] = [100., 200.]
        with self.assertRaises(OperationError): solve_operation(c)

    def test_minimum_output_and_storage_exclusivity_are_real_constraints(self):
        c = empty([1.]); c['spill_nodes'] = []
        c['sources'] = [source('fuel', 'gas', [100.])]
        p = process('must_run', {'gas': 1.}, {'electricity': 1.}, 10., [1.])
        p['minimum_fraction'] = [1.]; c['processes'] = [p]
        c['stores'] = [store(initial=10., cap=10., efficiency=.5)]
        with self.assertRaises(OperationError) as cm: solve_operation(c)
        self.assertEqual(cm.exception.status, 'infeasible')

    def test_ramp_and_prior_output_limit(self):
        c = shared_gas(); c['processes'][0]['ramp_mw_per_hour'] = 1.
        r = solve_operation(c)
        self.assertAlmostEqual(flow(r, 'process', 'gas_power'), 1.)
        self.assertAlmostEqual(r['service_shortfalls']['building'], 4.)

    def test_transfers_not_counted_in_resource_cost(self):
        c = shared_gas(); c['carbon_price_per_t'] = 100.
        r = solve_operation(c)
        self.assertAlmostEqual(r['totals']['resource_cost'], 10.)
        self.assertAlmostEqual(r['totals']['compliance_transfer'], 200.)

    def test_missing_nonfinite_negative_and_unknown_inputs_fail(self):
        mutations = [lambda c: c.pop('capture_storage_budget_t'),
                     lambda c: c['hours'].__setitem__(0, float('nan')),
                     lambda c: c['sources'][0].__setitem__('window_budget_mwh', -1.),
                     lambda c: c['devices'][0].__setitem__('node', 'unknown')]
        for mutate in mutations:
            c = shared_gas(); mutate(c)
            with self.assertRaises(OperationError) as cm: solve_operation(c)
            self.assertEqual(cm.exception.status, 'invalid_input')

    def test_solver_failure_is_not_zero_deficit(self):
        from types import SimpleNamespace
        with patch('energy_model.q2.operations.linprog', return_value=SimpleNamespace(success=False, status=1, message='time limit')):
            with self.assertRaises(OperationError) as cm: solve_operation(shared_gas())
        self.assertEqual(cm.exception.status, 'solver_failed')


if __name__ == '__main__': unittest.main()
