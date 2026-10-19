import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT/'scripts'))
from energy_model.q2.io import AdmissionError, digest, dump, load_bundle, local_path, sha, verify_source_records
import run_q2


class Q2AdmissionTests(unittest.TestCase):
    def test_fixture_is_explicit_and_pinned(self):
        config=json.loads((ROOT/'examples/q2_engineering.json').read_text(encoding='utf-8'))
        data=load_bundle(ROOT,config)
        self.assertEqual(data['model_bundle']['historical']['scope'],'synthetic_engineering_only')
        bad=deepcopy(config);bad['inputs'][0]['sha256']='0'*64
        with self.assertRaisesRegex(AdmissionError,'fingerprint'):load_bundle(ROOT,bad)

    def test_formal_config_rejects_declared_scientific_gaps(self):
        config={'scope':'national_q2','unresolved_required_inputs':[{'id':'carbon_boundary'}]}
        with self.assertRaises(AdmissionError) as error:load_bundle(ROOT,config)
        self.assertIn('carbon_boundary',{g['id'] for g in error.exception.gaps})

    def test_path_escape_and_restricted_inputs_rejected(self):
        for path in ('../outside.json','data/restricted/household/secret.csv',str(ROOT/'run.py')):
            with self.assertRaises(ValueError):local_path(ROOT,path)

    def test_scoped_source_review_allows_only_unrelated_registry_additions(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            original=root/'original.txt';original.write_text('actual source bytes',encoding='utf-8')
            record={'id':'reviewed','path':'original.txt','sha256':sha(original),'published_year':2010}
            binding=[{'path':'registry.json','id':'reviewed','record_sha256':digest(record)}]
            dump(root/'registry.json',[record,{'id':'unrelated','path':'not-used.txt'}])
            verify_source_records(root,binding)
            revised={**record,'published_year':2020}
            dump(root/'registry.json',[revised])
            with self.assertRaisesRegex(ValueError,'record changed'):verify_source_records(root,binding)
            dump(root/'registry.json',[record,record])
            with self.assertRaisesRegex(ValueError,'duplicated'):verify_source_records(root,binding)
            dump(root/'registry.json',[record])
            original.write_text('changed original',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'original changed'):verify_source_records(root,binding)

    def test_source_binding_cannot_be_empty_duplicate_or_missing(self):
        for bindings in ([],[{'path':'x','id':'y'}]*2):
            with self.assertRaisesRegex(ValueError,'Unique nonempty'):
                verify_source_records(ROOT,bindings)
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);dump(root/'registry.json',[])
            with self.assertRaisesRegex(ValueError,'record changed'):
                verify_source_records(root,[{'path':'registry.json','id':'missing','record_sha256':'0'*64}])

    def test_missing_input_after_old_success_does_not_relabel_old_outputs(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);out=root/'outputs/q2/previous';out.mkdir(parents=True)
            dump(out/'run_manifest.json',{'owner':'p2/yx','status':'engineering_success','run_id':'old'})
            (out/'baseline_path.csv').write_text('old scientific bytes',encoding='utf-8')
            dump(root/'workflow/q2_inputs.json',{'scope':'national_q2','unresolved_required_inputs':[{'id':'missing'}]})
            with patch.object(run_q2,'ROOT',root):
                code=run_q2.execute('workflow/q2_inputs.json','outputs/q2/previous')
            self.assertNotEqual(code,0)
            self.assertEqual((out/'baseline_path.csv').read_text(encoding='utf-8'),'old scientific bytes')
            latest=json.loads((root/'outputs/q2/previous.latest-attempt.json').read_text(encoding='utf-8'))
            self.assertFalse(latest['output_valid_for_this_attempt'])
            self.assertNotEqual(latest['run_id'],'old')
            self.assertFalse(latest['national_acceptance'])


if __name__=='__main__':unittest.main()
