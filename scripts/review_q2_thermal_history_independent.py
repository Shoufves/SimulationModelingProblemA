"""Save independent historical-source checks after PDF visual inspection."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    manifest = json.loads((ROOT / "data/raw/q2_thermal_efficiency_history/source_manifest.json").read_text("utf-8"))
    for source in manifest:
        assert sha256((ROOT / source["path"]).read_bytes()).hexdigest() == source["sha256"], source["id"]
    receipt = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "passed_with_scope_limits",
        "original_sources_hash_verified": len(manifest),
        "visually_reviewed_pdf_pages": {
            "IEA2010": [55, 57, 105, 206],
            "IEA2015": [19, 40, 41],
        },
        "china_technical_references": {
            "IEA2010_coal_net_lhv": 0.46,
            "IEA2010_ccgt_net_lhv": 0.58,
            "IEA2010_assumed_commissioning_year": 2015,
            "IEA2015_coal_net_lhv": 0.45,
            "IEA2015_ccgt_net_lhv": 0.55,
            "IEA2015_assumed_commissioning_year": 2020,
        },
        "official_policy_2014": {
            "new_coal_supply_standard_coal_g_per_kwh_ceiling": 300,
            "implied_net_efficiency_floor": 3.6 / (.300 * 29.3076),
            "scope": "design/entry policy, not observed vintage performance",
        },
        "official_statistics_2015": {
            "supply_standard_coal_g_per_kwh": 315,
            "implied_group_net_efficiency": 3.6 / (.315 * 29.3076),
            "publication_date": "2016-01-15",
            "scope": "6000kW+ group aggregate, not new-vintage or pure-coal panel",
        },
        "qualifications": [
            "IEA2010 China sample was independently collected in 2009 from construction projects; it is not an official national census",
            "IEA2015 China records use public-source/survey collection, not an official Chinese submission",
            "IEA2015 publication cannot be part of a 2014 information snapshot",
            "Cross-edition technical samples cannot identify a monotonic efficiency trend",
            "Early technology availability does not establish typical actual 2015 vintage efficiency or historical national fleet costs",
            "No official historical gas vintage efficiency panel was acquired",
            "2014 fleet own-use bridge remains an assumption for gross conversion",
        ],
        "source_sha256": {s["path"]: s["sha256"] for s in manifest},
        "default_inputs_changed": False,
        "scientific_acceptance": False,
        "documentation": "docs/sources/q2_thermal_efficiency_history.md",
    }
    out = ROOT / "outputs/validation/thermal_efficiency_history_independent_review_20261020.json"
    if out.exists():
        raise ValueError("Preserve an existing receipt")
    out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(out.relative_to(ROOT).as_posix())


if __name__ == "__main__":
    main()
