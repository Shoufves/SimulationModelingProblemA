"""Append the complete PR13 repair evidence without replacing R0-R9 history."""
from pathlib import Path
import argparse
import gzip
import hashlib
import json

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',default='tmp/n2/pr13_review2')
    parser.add_argument('--output',default='outputs/research_n2/pr13_review2')
    args=parser.parse_args();source=ROOT/args.source;dest=ROOT/args.output
    result=json.loads((source/'primary/final_acceptance.json').read_text('utf-8'))
    checks=json.loads((source/'review_checks.json').read_text('utf-8'))
    if not result['n2_internal_empirical_candidate'] or not checks['passed']:
        raise ValueError('Repair verification incomplete')
    dest.mkdir(parents=True,exist_ok=False)
    records=[]
    def archive(relative,blob,compress=False):
        target=dest/relative
        if compress:target=target.with_suffix('.json.gz')
        target.parent.mkdir(parents=True,exist_ok=True)
        stored=gzip.compress(blob,compresslevel=9,mtime=0) if compress else blob
        target.write_bytes(stored)
        records.append(dict(path=target.relative_to(dest).as_posix(),sha256=hashlib.sha256(stored).hexdigest(),
                            uncompressed_sha256=hashlib.sha256(blob).hexdigest(),
                            stored_bytes=len(stored),uncompressed_bytes=len(blob)))
    for path in sorted(source.rglob('*')):
        if path.is_file() and path.suffix in ('.json','.py','.log','.sha256'):
            archive(path.relative_to(source),path.read_bytes(),path.suffix=='.json' and '__' in path.name)
    archive(Path('final_acceptance.json'),(source/'primary/final_acceptance.json').read_bytes())
    for path in sorted((ROOT/'scripts').glob('*n2*.py')):
        archive(Path('verifier_sources')/path.name,path.read_bytes())
    manifest=dict(records=records,scope='All 77 declared review-2 rerun paths and repair checks; historical archive unchanged')
    (dest/'archive_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(files=len(records),stored_bytes=sum(r['stored_bytes'] for r in records))))


if __name__=='__main__':main()
