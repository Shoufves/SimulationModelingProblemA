from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT/'tests'))
from energy_model.q2.annual import EnergyModel
from q2_cases import annual_case
sys.path.insert(0,str(ROOT/'scripts'))
import build_q2_permit_candidate as builder
import run_q2_historical_candidate as runner


def block(year=2024):
    return {'id':f'no_new_solar_{year}','year':year,'option':'solar_build',
            'basis':'realized_administrative_outcome','evidence':'synthetic counterexample'}


class ApprovalBlockTests(unittest.TestCase):
    def test_reviewed_candidate_changes_only_three_annual_approval_outcomes(self):
        _,parent,selected=builder.load_parent()
        old=deepcopy(parent['structural_models'][selected['structure']])
        new=builder.build()['model']
        events=new.pop('approval_blocks')
        self.assertEqual(old,new)
        self.assertEqual([e['year'] for e in events],[2016,2017,2018])
        self.assertEqual({e['option'] for e in events},{'nuclear_build'})

    def test_holdout_targets_do_not_select_approval_response_rule(self):
        import contextlib,io
        a=builder.build();b=deepcopy(a)
        for r in b['observations']:
            if r['year']>=2022:r['value']*=1000
        with contextlib.redirect_stdout(io.StringIO()):
            left,right=runner.train_candidates(a),runner.train_candidates(b)
        self.assertEqual(left,right)
        self.assertEqual(len(left),3)

    def test_block_rejects_new_commitment_but_allows_other_technology(self):
        c=annual_case();c['approval_blocks']=[block()]
        result=EnergyModel(c).run()
        rejected=[a for a in result['actions'] if a.get('event')==block()['id']]
        self.assertTrue(rejected)
        self.assertTrue(all(a['approved_units']==0 and a['requested_units']>0 for a in rejected))
        self.assertFalse(any(p['option']=='solar_build' and p['applied_year']==2024 for p in result['projects']))
        self.assertFalse(any(r['reference']=='solar_build@2024' for r in result['cash']))
        self.assertTrue(all(abs(r['cash_residual'])<1e-8 for r in result['annual']))
        # Submit a separate positive application explicitly: the natural fixture
        # need not find a heat upgrade profitable in this particular year.
        model=EnergyModel(c)
        model.approve([{'option':'heat_upgrade','owner':'industrial','quantity':1.,'benefit_per_cost':1.}],
                      model.visible_policy())
        self.assertTrue(any(p['option']=='heat_upgrade' for p in model.projects))

    def test_later_outcome_does_not_change_earlier_actions_or_queue(self):
        c=annual_case();original=EnergyModel(c).run()
        c['approval_blocks']=[block(2025)];changed=EnergyModel(c).run()
        for field in ('annual','actions','information','cash','operations'):
            self.assertEqual([r for r in original[field] if r['year']<2025],
                             [r for r in changed[field] if r['year']<2025])
        old=next(p for p in original['projects'] if p['id']=='solar_build@2024')
        new=next(p for p in changed['projects'] if p['id']==old['id'])
        self.assertEqual(old,new)
        self.assertTrue(any(a['year']==2026 and a['component']=='solar_power' and a['quantity']>0
                            for a in changed['assets']))

    def test_empty_or_out_of_horizon_blocks_preserve_full_result(self):
        c=annual_case();base=EnergyModel(c).run()
        for events in ([],[block(2030)]):
            c['approval_blocks']=events
            self.assertEqual(base,EnergyModel(c).run())

    def test_block_expires_without_inventing_future_permission(self):
        c=annual_case();c['approval_blocks']=[block(2024)]
        result=EnergyModel(c).run()
        self.assertTrue(any(p['option']=='solar_build' and p['applied_year']==2025 for p in result['projects']))
        # The original option permission is still required after the block ends.
        c['investment_options'][0]['permit_effective_year']=2030
        self.assertFalse(any(p['option']=='solar_build' for p in EnergyModel(c).run()['projects']))

    def test_bad_or_ambiguous_outcomes_rejected(self):
        for key,val in [('year',True),('year',2024.5),('option','absent'),('evidence',''),('basis','forecast')]:
            with self.subTest(field=key):
                c=annual_case();e=block();e[key]=val;c['approval_blocks']=[e]
                with self.assertRaises(ValueError):EnergyModel(c)
        c=annual_case();e=block();other=deepcopy(e);other['id']='second'
        c['approval_blocks']=[e,other]
        with self.assertRaises(ValueError):EnergyModel(c)


if __name__=='__main__':unittest.main()
