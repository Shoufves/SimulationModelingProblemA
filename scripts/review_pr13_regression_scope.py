"""Verify that the reviewed Q1/Q2 regression evidence remains applicable.

This rechecks recorded dependencies and results; it does not rerun Q1/Q2.
"""
import hashlib
import json
from pathlib import Path
import subprocess
from run_q3 import ROOT, dump, load, sha

REVIEWED = 'bf8590809004466d2f595407eb61ddd2b6b7e5a2'
OUT = ROOT / 'outputs/q3_review'


def review():
    dependencies = {}
    receipts = {}
    errors = []
    for kind in ('q1', 'q2'):
        name = f'outputs/q3_review/{kind}_regression_manifest.json'
        original = subprocess.check_output(['git', 'show', REVIEWED + ':' + name], cwd=ROOT)
        manifest = json.loads(original)
        if sha(ROOT / name) != hashlib.sha256(original).hexdigest():
            errors.append(kind + ' historical manifest changed')
        expected = dict(manifest['code_hashes'])
        if kind == 'q1':
            expected[manifest['config_path']] = manifest['config_sha256']
            expected.update({r['path']: r['sha256'] for r in manifest['inputs']})
        else:
            expected.update(manifest['input_hashes'])
        direct_dependencies = len(expected)
        if kind == 'q1':
            for source in manifest['sources'].values():
                expected.update({a['path']: a['sha256'] for a in source['artifacts']})
            original_config = subprocess.check_output(
                ['git', 'show', REVIEWED + ':' + manifest['config_path']], cwd=ROOT)
            if hashlib.sha256(original_config).hexdigest() != manifest['config_sha256']:
                raise ValueError('Historical Q1 configuration differs from regression')
            evidence = json.loads(original_config)['evidence_review']
            expected[evidence['path']] = evidence['sha256']
        else:
            review_path = 'data/catalog/q2_national_input_review.json'
            original_review = json.loads(subprocess.check_output(
                ['git', 'show', REVIEWED + ':' + review_path], cwd=ROOT))
            expected.update({s['path']: s['sha256'] for s in original_review['sources']})
        for path, digest in expected.items():
            if sha(ROOT / path) != digest:
                errors.append('Changed regression dependency: ' + path)
            if path in dependencies and dependencies[path] != digest:
                errors.append('Contradictory historical hash: ' + path)
            dependencies[path] = digest
        result = load(OUT / f'{kind}_regression.json')
        if not result['passed']:
            errors.append(kind + ' artifact comparison failed')
        fresh = ROOT / result['fresh']
        if sha(fresh / 'run_manifest.json') != hashlib.sha256(original).hexdigest():
            errors.append(kind + ' stored regression run changed')
        for row in result['hashes']:
            if sha(fresh / row['file']) != row['reproduced']:
                errors.append(kind + ' historical reproduced artifact changed: ' + row['file'])
            if sha(ROOT / result['reference'] / row['file']) != row['base']:
                errors.append(kind + ' original artifact changed: ' + row['file'])
        receipts[kind] = dict(run_id=manifest['run_id'],
            historical_manifest_sha256=hashlib.sha256(original).hexdigest(),
            comparison_sha256=sha(OUT / f'{kind}_regression.json'),
            verified_dependencies=direct_dependencies,
            verified_sources_and_review=len(expected)-direct_dependencies,
            verified_scientific_artifacts=len(result['hashes']))
    return dict(passed=not errors, reviewed_sha=REVIEWED,
        unchanged_q1_q2_code_and_inputs=dependencies, historical_receipts=receipts,
        statement='PR13修复轮复用原提交已执行的Q1/Q2完整回归；本轮重新核验其代码、输入及科学产物指纹，重新执行320项测试及两套完整Q3。未在本轮重新训练Q2或重新生成Q1。',
        errors=errors, checker_sha256=sha(Path(__file__)))


if __name__ == '__main__':
    destination = OUT / 'review13_regression_scope.json'
    dump(destination, dict(passed=False, status='running'))
    try:
        result = review()
    except Exception as exc:
        result = dict(passed=False, error=str(exc))
    dump(destination, result)
    print(json.dumps({k: v for k, v in result.items() if k != 'unchanged_q1_q2_code_and_inputs'}, ensure_ascii=False))
    raise SystemExit(0 if result['passed'] else 1)
