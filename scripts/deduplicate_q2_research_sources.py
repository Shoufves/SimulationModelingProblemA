"""Consolidate two verified duplicate downloads without changing original bytes."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PAIRS={
    "data/raw/q2_technology_scope/nea_renewable_2024.html":"data/raw/batch1_national/nea_renewable_2024.html",
    "data/raw/q2_technology_scope/biomass_2024_people.html":"data/raw/q1/bio_industry_interview.html",
}


def main():
    alias_file=ROOT/"data/catalog/path_aliases.json"
    aliases=json.loads(alias_file.read_text(encoding="utf-8"))
    manifest=json.loads((ROOT/"data/raw/q2_technology_scope/source_manifest.json").read_text(encoding="utf-8"))
    evidence=[]
    for old,new in PAIRS.items():
        source,target=(ROOT/old).resolve(),(ROOT/new).resolve()
        if not source.is_relative_to(ROOT/"data/raw/q2_technology_scope") or not target.is_relative_to(ROOT/"data/raw") or source==target:
            raise ValueError("Invalid consolidation target")
        raw=target.read_bytes()
        if source.exists() and source.read_bytes()!=raw:
            raise ValueError("Sources are not byte-identical: "+old)
        if old in aliases and aliases[old]!=new:
            raise ValueError("Existing alias conflict")
        aliases[old]=new
        evidence.append(dict(duplicate=old,canonical=new,sha256=hashlib.sha256(raw).hexdigest(),
            acquisition_records=[r for r in manifest["sources"] if r["path"]==old],
            reason="Exact bytes already retained in the canonical source; no source or independent observation lost"))
    record=ROOT/"archive/q2_research_source_deduplication.json"
    if not record.exists():
        record.write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    else:
        previous=json.loads(record.read_text(encoding="utf-8"))
        if [(r["duplicate"],r["canonical"],r["sha256"]) for r in previous]!=[(r["duplicate"],r["canonical"],r["sha256"]) for r in evidence]:
            raise ValueError("Preservation evidence differs")
    alias_file.write_text(json.dumps(aliases,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    for old in PAIRS:
        path=ROOT/old
        if path.exists():path.unlink()
    print("Two exact duplicate copies consolidated; canonical originals unchanged")


if __name__=="__main__":
    main()
