"""Causal, chronology, source-targeting and failure counterexamples for Q3."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
AVAILABLE=all(importlib.util.find_spec(x) for x in ('mesa','scipy'))
if AVAILABLE:
    import run_q3
    from energy_model.q2_national import operate_national
    from energy_model.q2_operations import operate,Q2Error
    from energy_model.q3_transition import TransitionModel
    from energy_model.q3_events import run_event,service_metrics,severity,fingerprint,interaction
    from test_q2_operations import dispatch_case


@unittest.skipUnless(AVAILABLE,'Install requirements-q2.txt')
class Q3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c,cls.data,cls.design,cls.theta,_=run_q3.preflight(ROOT/'workflow/q3_inputs.json')
        cls.model=TransitionModel(cls.data,cls.design,cls.theta,cls.c).run(2030)
        cls.snapshot=cls.model.snapshots[2030]

    def model(self,**kw):
        return TransitionModel(self.data,self.design,self.theta,self.c,**kw)

    def test_sg_changes_only_designated_import_and_never_domestic(self):
        before=deepcopy(self.snapshot)
        base=run_event(before,self.c,'S0');shock=run_event(before,self.c,'SG')
        self.assertEqual(before,self.snapshot)
        for x,y in zip(base['rows']['sources'],shock['rows']['sources']):
            self.assertEqual(x['domestic_mw'],y['domestic_mw'])
            self.assertEqual(x['other_import_mw'],y['other_import_mw'])
        self.assertLess(min(x['available_mw'] for x in shock['rows']['sources']),min(x['available_mw'] for x in base['rows']['sources']))

    def test_continuous_soc_at_every_day_boundary_and_no_year_weight(self):
        r=run_event(self.snapshot,self.c,'SGW');s=r['rows']['storage']
        self.assertEqual(len(s),self.c['event']['days']*4)
        for a,b in zip(s,s[1:]):self.assertAlmostEqual(a['closing_mwh'],b['opening_mwh'],places=5)
        self.assertLess(r['max_residual'],self.c['acceptance']['physical_residual_mwh'])
        day=sum(sum(d['service_mwh']) for d in self.snapshot['operation']['demands'].values())
        self.assertAlmostEqual(sum(x['requested'] for x in r['metrics'])/day,self.c['event']['days'],places=6)

    def test_frozen_gas_cannot_invent_fuel_or_dispatch(self):
        base=run_event(self.snapshot,self.c,'S0')
        frozen=run_event(self.snapshot,self.c,'SGW',frozen_gas=base['gas_response'])
        self.assertEqual(base['snapshot_hash'],frozen['snapshot_hash'])
        for old,new in zip(base['gas_response'],frozen['gas_response']):self.assertLessEqual(new,old+.001)
        self.assertGreaterEqual(frozen['gas_min_inventory_mwh'],-.001)

    def test_no_shock_is_exact_identity_and_input_not_mutated(self):
        c=deepcopy(self.c);c['event'].update(gas_loss_fraction=0,wind_factor=1,solar_factor=1,hydro_factor=1)
        a=run_event(self.snapshot,c,'S0');b=run_event(self.snapshot,c,'SGW')
        self.assertEqual(a['rows']['demand'],b['rows']['demand'])
        self.assertEqual(a['rows']['storage'],b['rows']['storage'])

    def test_censored_recovery_and_zero_demand_are_not_fabricated(self):
        rows=[dict(sector='A',period=i,requested_service_mwh=1,unmet_service_mwh=1 if i>=2 else 0) for i in range(6)]
        rows += [dict(sector='zero',period=i,requested_service_mwh=0,unmet_service_mwh=0) for i in range(6)]
        values={r['service']:r for r in service_metrics(rows,18,self.c)}
        self.assertEqual(values['A']['longest_interruption_hours'],24)
        self.assertIsNone(values['A']['recovery_hours'])
        self.assertEqual(values['A']['recovery_status'],'right_censored_not_recovered')
        self.assertIsNone(values['zero']['loss_fraction'])

    def test_future_event_calendar_does_not_enter_annual_actions(self):
        c=deepcopy(self.c);c['event']['gas_start_day']=100
        a=TransitionModel(self.data,self.design,self.theta,self.c).run(2026)
        b=TransitionModel(self.data,self.design,self.theta,c).run(2026)
        self.assertEqual(a.behavior,b.behavior);self.assertEqual(a.paths,b.paths)

    def test_public_infrastructure_never_online_in_decision_year(self):
        m=TransitionModel(self.data,self.design,self.theta,self.c,policy=('grid','storage','gas')).run(2025)
        public=[p for p in m.grid.queue if p.get('q3_public')]
        # The ordinary grid request may already exhaust construction capacity;
        # an authorised budget must not guarantee extra physical construction.
        self.assertTrue(public)
        self.assertTrue({p['kind'] for p in public}.issubset({'grid','storage'}))
        for kind in ('grid','storage'):
            used=sum(p['power'] for p in m.grid.queue if p['decision']==2025 and p['kind']==kind)
            limit=m.grid.initial_power*m.a[kind+'_build_fraction']*m.gdp/m.gdp0
            self.assertLessEqual(used,limit+.001)
        self.assertTrue(all(p['online']>p['decision'] and p['remaining']>0 for p in public))
        self.assertEqual(m.event_diversification,0)
        self.assertLessEqual(m.annual_public_spend(2025),m.paths[-1]['q3_public_budget_cny']+.1)
        for p in m.public_ledger:
            self.assertAlmostEqual(p['treasury_transfer_cny']+p['escrow_transfer_cny'],0)

    def test_storage_cost_change_has_no_free_initial_capacity_or_efficiency(self):
        a=TransitionModel(self.data,self.design,self.theta,self.c)
        b=TransitionModel(self.data,self.design,self.theta,self.c,scenario='ST')
        self.assertEqual(a.storage_cohorts,b.storage_cohorts)
        self.assertEqual(a.storage_soc,b.storage_soc)
        self.assertEqual(a.a['storage_roundtrip_efficiency'],b.a['storage_roundtrip_efficiency'])
        b.run(2027)
        self.assertAlmostEqual(b.a['storage_capex_cny_per_mwh'],a.original_storage_capex*.7)

    def test_source_diversification_without_paid_contract_has_no_effect(self):
        m=TransitionModel(self.data,self.design,self.theta,self.c,policy=()).run(2030)
        self.assertIsNone(m.gas_contract);self.assertEqual(m.snapshots[2030]['diversified_fraction'],0)

    def test_free_terminal_is_opt_in_and_default_behavior_unchanged(self):
        c=dispatch_case();default=operate(c)
        explicit=deepcopy(c);explicit['storage']['terminal_rule']='fixed'
        self.assertEqual(default,operate(explicit))
        bad=deepcopy(c);bad['storage']['terminal_rule']='free'
        with self.assertRaises(Q2Error):operate(bad)
        c['cyclic']=False;c['storage']['terminal_rule']='free'
        r=operate(c);self.assertEqual(r['status'],'optimal')

    def test_infeasible_and_solver_failure_are_separate(self):
        c=dispatch_case();c['cyclic']=False;c['storage']['power_mw']=0;c['storage']['terminal_mwh']=1
        with self.assertRaises(Q2Error) as exc:operate(c)
        self.assertEqual(exc.exception.status,'infeasible')
        from types import SimpleNamespace
        with self.assertRaises(Q2Error) as exc:operate(dispatch_case(),solver=lambda *a,**k:SimpleNamespace(success=False,status=4,message='injected'))
        self.assertEqual(exc.exception.status,'solver_failure')

    def test_invalid_calendar_rejected(self):
        with self.assertRaises(Q2Error):run_event(self.snapshot,self.c,'SG',gas_offset=-10)
        with self.assertRaises(Q2Error):run_event(self.snapshot,self.c,'SG',channel_share=1.1)

    def test_h01_explicit_retirement_cannot_exceed_natural_exit_or_deadline(self):
        m=TransitionModel(self.data,self.design,self.theta,self.c,h01=dict(vR=.04,vE=.25,delay=1,rule='rolling_guard')).run(2033)
        decisions=[r for r in m.retirement_log if r['action']=='decision']
        self.assertTrue(decisions)
        for r in decisions:
            self.assertLessEqual(r['exit'],r['deadline']);self.assertLessEqual(r['exit'],r['natural_exit'])
            self.assertLessEqual(r['deadline']-r['request_year'],3)

    def test_missing_hash_and_withdrawn_purpose_fail_preflight(self):
        original=run_q3.load
        def altered(path):
            result=original(path)
            if str(path).endswith('q3_inputs.json'):result['review_sha256']='0'*64
            return result
        with patch.object(run_q3,'load',side_effect=altered),self.assertRaises(Q2Error):run_q3.preflight(ROOT/'workflow/q3_inputs.json')
        def revoked(path):
            result=original(path)
            if str(path).endswith('q3_input_review.json'):result['allowed_uses']=[]
            return result
        with patch.object(run_q3,'load',side_effect=revoked),self.assertRaises(Q2Error):run_q3.preflight(ROOT/'workflow/q3_inputs.json')

    def test_pairwise_difference_is_per_service(self):
        arms={s:dict(metrics=[dict(service='one',unmet=u),dict(service='two',unmet=0)]) for s,u in zip(('S0','SG','SW','SGW'),(1,3,4,10))}
        self.assertEqual(interaction(arms),{'one':4,'two':0})

    def test_failed_attempt_invalidates_old_success_before_input_check(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);old=root/'outputs/q3/case';old.mkdir(parents=True)
            (old/'run_manifest.json').write_text(json.dumps(dict(owner='p3/yx',run_id='previous',status='success_conditional_study')))
            (old/'old-result.txt').write_text('preserve me')
            with patch.object(run_q3,'ROOT',root):
                status=run_q3.main(['--config','missing.json','--output-dir','outputs/q3/case'])
                self.assertEqual(status,1)
                latest=json.loads((root/'outputs/q3/case.latest-attempt.json').read_text())
                self.assertFalse(latest['valid'])
                self.assertEqual(latest['status'],'failed')
                self.assertTrue((root/'outputs/q3/case.attempts/previous/old-result.txt').exists())
                with self.assertRaises(Q2Error):run_q3.verify_latest(old)

    def test_fixed_generation_set_retains_same_projects_across_delays(self):
        cases=[]
        for delay in (0,3):
            m=TransitionModel(self.data,self.design,self.theta,self.c,
                h01=dict(vR=.02,vE=.25,delay=delay,rule='schedule'),fixed_pipeline=True).run(2028)
            self.assertTrue(all(p['initial_reconstruction'] for p in m.projects))
            cases.append({p['id']:(p['tech'],p['capacity_mw'],p['cost']) for p in m.projects})
        self.assertEqual(cases[0],cases[1])

    def test_ranking_ignores_solver_tail_noise(self):
        a=run_q3.rank_key(.4+1e-14,1e12,'a');b=run_q3.rank_key(.4,1e12,'b')
        self.assertLess(a,b)


if __name__=='__main__':unittest.main()
