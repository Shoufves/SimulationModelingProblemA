"""Offline audit of original waste fossil-CO2 and LHV sources; no model edits."""
from pathlib import Path
import csv
import hashlib
import html
import json
import re

ROOT = Path(__file__).resolve().parent
OLD = ROOT.parent / "q2_scope_components"

sources = [
    (OLD / "ma_2024_radiocarbon.pdf", "https://link.springer.com/article/10.1007/s44246-024-00162-9",
     "PDF p7 section2.6 Eq7; p11 section3.3 Fig5b; p14 conclusions"),
    (OLD / "ma_2024_supplement.docx", "https://link.springer.com/article/10.1007/s44246-024-00162-9",
     "Tables S1-S4; S3 gas flow and waste throughput; S4 fossil-carbon fractions"),
    (ROOT / "bourtsalas_2020_publisher.html", "https://link.springer.com/article/10.1007/s42768-019-00026-8",
     "Abstract, first paragraph: China MSW LHV 4-7 MJ/kg"),
    (ROOT / "bourtsalas_2021_correction_publisher.html", "https://link.springer.com/article/10.1007/s42768-021-00078-9",
     "Correction title: Missing Conflict of Interest statements"),
]
manifest = []
for p, url, locator in sources:
    blob = p.read_bytes()
    manifest.append(dict(file=str(p.relative_to(ROOT.parent)), sha256=hashlib.sha256(blob).hexdigest(),
                         bytes=len(blob), url=url, locator=locator, retrieved="2026-10-20"))
    if p.suffix == ".html":
        text = re.sub(r"<script\b[^>]*>.*?</script>", "", blob.decode("utf-8"), flags=re.S)
        text = re.sub(r"<style\b[^>]*>.*?</style>", "", text, flags=re.S)
        text = html.unescape(re.sub(r"<[^>]+>", " ", text))
        text = re.sub(r"\s+", " ", text)
        p.with_suffix(".txt").write_text(text, encoding="utf-8")
(ROOT / "source_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

# Cross-study envelope is an explicit sensitivity assumption, not paired observations.
# kg CO2/t waste / (MJ/kg == GJ/t) => kg/GJ; multiply .0036 for t/MWh.
assumptions = dict(
    status="cross_study_sensitivity_only_not_national_observation",
    direct_fossil_kg_per_t_waste=[249.0,445.0],
    direct_basis="Ma2024 untreated-gas MethodIV; combustion before gas cleanup",
    lhv_mj_per_kg_waste=[4.0,7.0],
    lhv_basis="Bourtsalas2020 original comparative plant study, publisher abstract",
    fossil_ef_t_per_mwh_fuel=[249*.0036/7,445*.0036/4],
    fossil_ef_kg_per_gj_fuel=[249/7,445/4],
    scenario_center_rule="arithmetic midpoint of waste-mass EF and LHV, not estimated national mean",
    scenario_center_t_per_mwh_fuel=((249+445)/2)*.0036/((4+7)/2),
    post_cleanup_ma_method_v_kg_per_t=[233.0,405.0],
    post_cleanup_derived_envelope_t_per_mwh_fuel=[233*.0036/7,405*.0036/4],
    cautions=[
        "No Ma2024 LHV measured for the same sampled waste was found.",
        "The rectangular combination of two studies is deliberately conservative and has no measured joint distribution.",
        "Ma2024 seven plants/eight conditions sampled 2022-11 to 2023-11, not national annual 2014-2024.",
        "Do not treat flue-gas carbon fraction as waste mass, energy, or electricity fraction.",
        "Apply only to separately declared waste fuel energy; not all biomass and not recovered industrial heat.",
        "Combustion before gas cleanup and stack emission after gas cleanup are different physical boundaries.",
        "Not a life-cycle EF: no avoided grid emissions or indirect upstream emissions included.",
        "Ma abstract upper untreated value446 differs from body and conclusion445; use body445 consistently.",
    ])
(ROOT / "sensitivity_range.json").write_text(json.dumps(assumptions, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(assumptions, ensure_ascii=False, indent=2))
