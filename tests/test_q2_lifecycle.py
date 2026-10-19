import sys
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src')); sys.path.insert(0, str(ROOT/'tests'))
from energy_model.q2.annual import EnergyModel
from q2_cases import annual_case


def life(years=80, permit=None, exits=None):
    return {'technical_life_years': years, 'permit_valid_through': permit,
            'initial_loss_years': 0, 'exit_rule': exits,
            'maintenance_factors': {'operating': 1., 'standby': .5, 'mothballed': .1, 'retired': 0.}}


class Q2LifecycleTests(unittest.TestCase):
    def config(self):
        c = annual_case()
        c['mechanisms']['investment'] = False
        for asset in c['assets']:
            asset['lifecycle'] = life()
        for option in c['investment_options']:
            option['lifecycle'] = life()
        return c

    def test_service_capacity_and_ownership_must_match(self):
        c = self.config(); c['investment_options'][1]['replacement_ratio'] = .2
        with self.assertRaisesRegex(ValueError, 'conserve rated service'): EnergyModel(c)
        c = self.config(); c['investment_options'][1]['owner'] = 'generation'
        c['agents'][1]['initial_margins']['heat_upgrade'] = 0.
        with self.assertRaisesRegex(ValueError, 'same-owner'): EnergyModel(c)

    def test_technical_end_stops_operation_without_inventing_retirement(self):
        c = self.config()
        asset = next(a for a in c['assets'] if a['component']=='gas_power')
        asset['lifecycle'] = life(years=1)
        r = EnergyModel(c).run()
        rows = [a for a in r['assets'] if a['id']==asset['id']]
        self.assertEqual(rows[0]['state'], 'operating')
        self.assertTrue(all(a['state']=='mothballed' for a in rows[1:]))
        self.assertTrue(all(a['quantity']==1 for a in rows))
        self.assertGreater(r['annual'][1]['service_shortfalls']['building'], 0)

    def test_permit_expiry_and_known_paid_extension_are_distinct(self):
        c = self.config()
        a = next(a for a in c['assets'] if a['component']=='gas_power')
        a['lifecycle'] = life(years=1, permit=2024)
        event = {'id':'extension', 'asset':a['id'], 'known_year':2025, 'effective_year':2025,
                 'new_state':'operating','permit_granted':True,'technical_end_year':2030,
                 'permit_valid_through':2030, 'cost':7.}
        c['asset_events'] = [event]
        r = EnergyModel(c).run()
        self.assertEqual(r['annual'][1]['lifecycle_resource_cost'], 7.)
        self.assertTrue(all(a['state']=='operating' for a in r['assets'] if a['id']==event['asset']))
        # A later announcement cannot authorize earlier operation or spending.
        event['known_year'] = 2026
        r = EnergyModel(c).run()
        a2025 = next(a for a in r['assets'] if a['id']==event['asset'] and a['year']==2025)
        self.assertEqual(a2025['state'],'mothballed')
        self.assertEqual(r['annual'][1]['lifecycle_resource_cost'],0.)

    def test_unfunded_extension_does_not_resume_operation(self):
        c = self.config()
        a = next(a for a in c['assets'] if a['component']=='gas_power')
        a['lifecycle'] = life(years=1)
        c['asset_events'] = [{'id':'extension','asset':a['id'],'known_year':2024,'effective_year':2025,
                              'new_state':'operating','permit_granted':True,'technical_end_year':2030,'cost':1e9}]
        r = EnergyModel(c).run()
        self.assertTrue(any(a.get('reason')=='lifecycle_action_unfunded' for a in r['actions']))
        self.assertEqual(next(a for a in r['assets'] if a['id']=='gas_power_asset' and a['year']==2025)['state'],'mothballed')

    def test_losses_generate_next_year_mothball_then_permitted_retirement(self):
        c = self.config()
        a = next(a for a in c['assets'] if a['component']=='gas_power')
        a['fixed_om_per_unit'] = 1.
        a['lifecycle'] = life(exits={'known_year':2024,'permit_effective_year':2024,
            'mothball_after_loss_years':1,'retire_after_loss_years':2,
            'retirement_permitted':True,'retirement_cost_per_unit':2.})
        c['policies'][0]['node_prices']['electricity'] = 0.
        r = EnergyModel(c).run()
        states = [a['state'] for a in r['assets'] if a['id']=='gas_power_asset']
        self.assertEqual(states,['operating','mothballed','retired','retired','retired'])
        self.assertEqual(r['annual'][2]['lifecycle_resource_cost'],2.)
        self.assertTrue(all(abs(row['cash_residual'])<1e-8 for row in r['annual']))
        a['lifecycle']['exit_rule']['retirement_permitted'] = False
        r = EnergyModel(c).run()
        self.assertFalse(any(a['state']=='retired' for a in r['assets'] if a['id']=='gas_power_asset'))

    def test_competing_projects_cannot_reserve_same_old_equipment(self):
        c = self.config(); model = EnergyModel(c)
        option = model.config['investment_options'][1]
        other = deepcopy(option); other['id']='heat_upgrade_2'
        model.config['investment_options'].append(other)
        model.config['cost_decline']['heat_upgrade_2'] = 0.
        old = next(a for a in model.assets if a['id']==option['replaces'])
        old['quantity'] = .002
        proposals = [{'owner':o['owner'],'option':o['id'],'quantity':1.,'benefit_per_cost':1.} for o in (option,other)]
        model.approve(proposals,model.visible_policy())
        self.assertAlmostEqual(sum(p['replacement_units'] for p in model.projects),.002)
        self.assertEqual(len(model.projects),1)

    def test_national_scope_cannot_omit_ages(self):
        c = annual_case(); c['scope']='national_q2'
        with self.assertRaisesRegex(ValueError,'explicit lifecycle'): EnergyModel(c)


if __name__ == '__main__': unittest.main()
