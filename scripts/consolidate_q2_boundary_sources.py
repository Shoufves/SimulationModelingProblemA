"""Consolidate four known byte-identical copies and preserve acquisition records."""
from pathlib import Path
import hashlib,json

ROOT=Path(__file__).resolve().parents[1]
PAIRS={
    "data/raw/q2_scope_components/cec2014_portal.txt":"data/raw/q2_capacity_detail/cec2014_portal.txt",
    "data/raw/q2_scope_components/nea_renewable_2024.txt":"data/raw/q2_capacity_detail/nea_renewable_2024.txt",
    "data/raw/q2_revenue/ndrc_gas_tariff_2014.html":"data/raw/q2_revenue/ndrc_gas_tariff_2014_3009.html",
    "data/raw/q2_revenue/ndrc_waste_tariff_2012.html":"data/raw/q2_revenue/ndrc_waste_tariff_2012_801.html",
}


def main():
    aliases_file=ROOT/"data/catalog/path_aliases.json"
    inventory_file=ROOT/"data/raw/q2_revenue/source_inventory.json"
    receipt_file=ROOT/"archive/q2_boundary_source_deduplication.json"
    aliases=json.loads(aliases_file.read_text("utf-8"))
    inventory=json.loads(inventory_file.read_text("utf-8"))
    records=[]
    for old,new in PAIRS.items():
        source,target=(ROOT/old).resolve(),(ROOT/new).resolve()
        if not source.is_relative_to(ROOT/"data/raw") or not target.is_relative_to(ROOT/"data/raw") or source==target:
            raise ValueError("Invalid fixed consolidation pair")
        raw=target.read_bytes()
        if source.exists() and source.read_bytes()!=raw:
            raise ValueError("Copies differ: "+old)
        if old in aliases and aliases[old]!=new:
            raise ValueError("Alias conflict")
        records.append(dict(duplicate=old,canonical=new,sha256=hashlib.sha256(raw).hexdigest(),
            acquisition_records=[r for r in inventory if r["path"]==old],
            reason="Byte-identical canonical original/derived text retained; no independent observation removed"))
        aliases[old]=new
    if receipt_file.exists():
        prior=json.loads(receipt_file.read_text("utf-8"))
        keys=lambda rows:[(r["duplicate"],r["canonical"],r["sha256"]) for r in rows]
        if keys(prior)!=keys(records):raise ValueError("Preservation receipt differs")
    else:
        receipt_file.write_text(json.dumps(records,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    aliases_file.write_text(json.dumps(aliases,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    inventory_file.write_text(json.dumps([r for r in inventory if r["path"] not in PAIRS],ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    for old in PAIRS:
        source=(ROOT/old).resolve()
        if source.exists():source.unlink()
    print("Consolidated four exact copies; retained canonical bytes and retrieval records")


if __name__=="__main__":main()
