import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from energy_model.research_diagnostics import (
    pooled_source_exposure, factorial_attribution, deployment_signature, text_profile,
    verify_evidence_claims)


def trade(values):
    return [dict(year='2024',destination='China',origin=k,value=v,unit='bcm GCV40',
                 source_id='same_source',sheet='same_sheet',cell='B2',row_type='origin')
            for k,v in values.items()] + [dict(year='2024',destination='China',
                origin='Total imports',value=sum(values.values()),unit='bcm GCV40',
                source_id='same_source',sheet='same_sheet',cell='B3',row_type='total')]


class ResearchDiagnosticsTests(unittest.TestCase):
    def test_shared_country_cross_term(self):
        result=pooled_source_exposure({'pipe':trade({'A':30,'B':20}),'lng':trade({'A':10,'C':40})})
        self.assertAlmostEqual(result['named_country_hhi_lower'],3600)
        self.assertAlmostEqual(result['omitted_common_origin_cross_term'],600)
        self.assertEqual(result['conservative_country_hhi_upper'],result['named_country_hhi_lower'])

    def test_disjoint_modes_have_no_shared_origin_term(self):
        result=pooled_source_exposure({'pipe':trade({'A':50}),'lng':trade({'B':50})})
        self.assertEqual(result['omitted_common_origin_cross_term'],0)

    def test_unidentified_bucket_bound_allows_overlap(self):
        result=pooled_source_exposure({'pipe':trade({'A':50}),'lng':trade({'B':40,'Other Region':10})})
        # Worst allocation puts the unknown volume into A: .6^2+.4^2.
        self.assertAlmostEqual(result['conservative_country_hhi_upper'],5200)
        self.assertAlmostEqual(result['named_country_hhi_lower'],4100)
        self.assertAlmostEqual(result['single_origin_exposure_upper'],.6)

    def test_wrong_unit_rejected(self):
        a=trade({'A':1});b=trade({'B':1});b[0]['unit']='tonnes'
        with self.assertRaisesRegex(ValueError,'mismatch'):
            pooled_source_exposure({'a':a,'b':b})

    def test_missing_trade_volume_rejected(self):
        a=trade({'A':1});a[-1]['value']=2
        with self.assertRaisesRegex(ValueError,'reconcile'):
            pooled_source_exposure({'a':a,'b':trade({'B':1})})

    def test_duplicate_origin_rejected(self):
        a=trade({'A':1});a.insert(0,dict(a[0]))
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            pooled_source_exposure({'a':a,'b':trade({'B':1})})

    def test_negative_or_nonfinite_trade_rejected(self):
        for bad in (-1,float('nan'),float('inf')):
            with self.subTest(bad=bad),self.assertRaises(ValueError):
                pooled_source_exposure({'a':trade({'A':bad}),'b':trade({'B':1})})

    def test_shapley_synergy_and_dummy(self):
        players=('A','B','C');v={}
        for bits in range(8):
            s=frozenset(p for i,p in enumerate(players) if bits & (1<<i))
            v[s]=5*('A' in s)+3*('B' in s)+4*({'A','B'}<=s)
        result=factorial_attribution(v,players)
        self.assertAlmostEqual(result['shapley']['A'],7)
        self.assertAlmostEqual(result['shapley']['B'],5)
        self.assertEqual(result['shapley']['C'],0)
        self.assertAlmostEqual(result['efficiency_residual'],0)
        self.assertEqual(result['anchored_interactions']['A+B'],4)

    def test_shapley_symmetric_players(self):
        v={frozenset():0,frozenset('A'):2,frozenset('B'):2,frozenset('AB'):8}
        r=factorial_attribution(v,('A','B'))
        self.assertEqual(r['shapley'],{'A':4,'B':4})

    def test_incomplete_factorial_is_not_silently_filled(self):
        with self.assertRaises(ValueError):
            factorial_attribution({frozenset():0},('A','B'))

    def test_same_cost_different_lead_is_not_equivalent(self):
        row=dict(year=2025,action='storage',capacity_mw=10,decision=2025,online=2027,amount_cny=20)
        later=dict(row,online=2028)
        self.assertNotEqual(deployment_signature([row]),deployment_signature([later]))

    def test_commitment_order_does_not_create_false_difference(self):
        a=dict(year=2025,action='storage',capacity_mw=10,decision=2025,online=2027,amount_cny=20)
        b=dict(a,action='gas')
        self.assertEqual(deployment_signature([a,b]),deployment_signature([b,a]))

    def test_repetition_is_not_an_ai_probability(self):
        text='这段文字明确报告模型输入和实际验证的内容。'*2
        r=text_profile(text,{})
        self.assertEqual(r['repeated_sentence_rate']['numerator'],1)
        self.assertEqual(r['repeated_sentence_rate']['denominator'],2)
        self.assertIsNone(r['formal_aigc_detector_percent'])
        self.assertIsNone(r['true_ai_authorship_percent'])
        self.assertIsNone(r['external_plagiarism_percent'])

    def test_local_overlap_locations_are_auditable(self):
        text='甲方报告已经明确交代测量数据的来源和用途。'
        r=text_profile(text,{'old.md':text})
        self.assertEqual(r['local_12gram_overlap']['percent'],100)
        self.assertIn('old.md',r['overlap_locations'][0]['sources'])

    def test_empty_prose_rejected(self):
        with self.assertRaises(ValueError):
            text_profile('# 只有标题',{})

    def test_anchor_metric_does_not_claim_source_verification(self):
        r=text_profile('该实验的完整参数设置包括12个时间段以及固定的初始库存[E1]。',{})
        self.assertEqual(r['numeric_sentence_explicit_anchor_rate']['percent'],100)
        self.assertIn('not proof',r['interpretation'])

    def test_numeric_anchor_rejects_wrong_result(self):
        claim=dict(id='E1',manuscript='a',phrase='结果为12.50[E1]',
            values=[dict(source={'key':'x'},format='.2f',rendered='12.50')])
        with self.assertRaisesRegex(ValueError,'numeric mismatch'):
            verify_evidence_claims([claim],{'a':'结果为12.50[E1]'},lambda s:15)
        result=verify_evidence_claims([claim],{'a':'结果为12.50[E1]'},lambda s:12.5)
        self.assertEqual(result[0]['values'][0]['raw'],12.5)

    def test_evidence_rejects_unregistered_anchor(self):
        with self.assertRaisesRegex(ValueError,'Undeclared'):
            verify_evidence_claims([],{'a':'没有登记的结论[E9]'},lambda s:0)

    def test_evidence_rejects_changed_manuscript_phrase(self):
        claim=dict(id='E1',manuscript='a',phrase='结果为12.50[E1]',values=[])
        with self.assertRaisesRegex(ValueError,'missing'):
            verify_evidence_claims([claim],{'a':'结果为125.0[E1]'},lambda s:0)


if __name__=='__main__':
    unittest.main()
