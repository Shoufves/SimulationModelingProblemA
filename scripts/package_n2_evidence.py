"""Archive every completed declared research run, including failed hypotheses.

Large per-case JSON records use lossless gzip with a fixed mtime. This script
does not choose successful cases or overwrite earlier evidence packages.
"""
from pathlib import Path
import argparse
import gzip
import hashlib
import json
import shutil

ROOT=Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',default='outputs/research_n2');args=p.parse_args()
    dest=ROOT/args.output;dest.mkdir(parents=True,exist_ok=False)
    sources={'r1':'tmp/n2/r1_complete','r2':'tmp/n2/r2','r3':'tmp/n2/r3','r4':'tmp/n2/r4',
             'r5':'tmp/n2/r5','r6':'tmp/n2/r6','r7':'tmp/n2/r7','r8':'tmp/n2/r8',
             'r9':'tmp/n2/r9','r9_fixed':'tmp/n2/r9_fixed','r9_reproduction':'tmp/n2/r9_reproduction'}
    records=[]
    for label,source in sources.items():
        for path in sorted((ROOT/source).rglob('*')):
            if not path.is_file() or path.suffix not in ('.json','.py','.log','.sha256'):continue
            relative=Path(label)/path.relative_to(ROOT/source)
            data=path.read_bytes()
            compressed=path.suffix=='.json' and '__' in path.name
            target=dest/relative
            if compressed:target=target.with_suffix('.json.gz')
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(gzip.compress(data,compresslevel=9,mtime=0) if compressed else data)
            records.append(dict(path=target.relative_to(dest).as_posix(),
                uncompressed_sha256=hashlib.sha256(data).hexdigest(),sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
                uncompressed_bytes=len(data),stored_bytes=target.stat().st_size))
    for name in ['baseline_export.json','literature-search.json','author-sources.json','legacy_tests.json','research_tests.json',
                 'research_tests.log','research_tests_fixture_failure.json','research_tests_fixture_failure.log','final_acceptance.json']:
        source=ROOT/'tmp/n2'/name
        if source.exists():shutil.copyfile(source,dest/name)
    folders=sorted((ROOT/'tmp/n2/pr14/outputs/q2_portable').glob('*'))
    for folder in folders:
        if (folder/'verification.json').exists():
            (dest/'r0').mkdir(exist_ok=True)
            shutil.copyfile(folder/'verification.json',dest/'r0/verification.json')
            break
    present={r['path'] for r in records}
    for path in sorted(dest.rglob('*')):
        if path.is_file() and path.relative_to(dest).as_posix() not in present:
            blob=path.read_bytes();digest=hashlib.sha256(blob).hexdigest()
            records.append(dict(path=path.relative_to(dest).as_posix(),uncompressed_sha256=digest,sha256=digest,
                uncompressed_bytes=len(blob),stored_bytes=len(blob)))
    (dest/'archive_manifest.json').write_text(json.dumps(dict(records=records,
        scope='All declared R0-R9 evidence, not a success-only selection; R1 initial engineering failures described separately.'),
        ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Archived',len(records),'files;',sum(r['stored_bytes'] for r in records),'bytes')


if __name__=='__main__':main()
