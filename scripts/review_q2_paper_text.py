"""Record a limited read-only Q2 paper review against the frozen computed run."""
from datetime import datetime,timezone
from hashlib import sha256
from pathlib import Path
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"scripts"),str(ROOT/"src")]
PAPER=ROOT/"outputs/question2_delivery_20261020/问题二答题稿.md"
RUN=ROOT/"outputs/q2_current_delivery/20261020T004752442611Z"


def portable_review():
    from q2_delivery_snapshot import decode,READERS
    def load(p):return json.loads(p.read_text("utf-8"))
    def sha(p):return sha256(p.read_bytes()).hexdigest()
    folder=ROOT/"data/processed/q2_delivery"
    manifest=load(folder/"manifest.json")
    assert sha(folder/"parsed_inputs.json")==manifest["inputs_sha256"]
    assert sha(folder/"q2_design.json")==manifest["design_sha256"]
    assert not [p for p,h in manifest["code_sha256"].items() if sha(ROOT/p)!=h]
    # Originals remain locally available during this review. This additional
    # check is not claimed to occur inside the small package at runtime.
    assert not [p for p,h in manifest["original_source_sha256"].items() if sha(ROOT/p)!=h]
    assert manifest["original_source_sha256"]==load(RUN/"source_snapshot.json")
    assert manifest["source_results_sha256"]==sha(RUN/"results.json")
    records=load(folder/"parsed_inputs.json")
    record_summaries={}
    for name,raw in records.items():
        record=decode(raw)
        assert set(record)=={"data","design","config","parameters","readers"}
        assert set(record["readers"])==set(READERS)
        years=sorted({k[0] for k in record["data"] if isinstance(k,tuple) and isinstance(k[0],int)})
        assert max(years)<=2024
        scoped=record["readers"]["scope_inputs"]
        scoped_years=sorted({k[0] for k in scoped[0] if isinstance(k,tuple) and isinstance(k[0],int)})
        assert max(scoped_years)<=2024
        mode,authority=name.split("/")
        selection=load(ROOT/load(RUN/"design.json")["historical_runs"][mode]/"training_selection.json")
        assert record["parameters"]==selection["scenarios"][authority]["parameters"]
        assert scoped[3].initial_year==2014
        record_summaries[name]=dict(data_year_min=min(years),data_year_max=max(years),
            scoped_data_year_max=max(scoped_years),readers=sorted(record["readers"]),
            future_model_paths_in_record=False)
    design=load(folder/"q2_design.json")
    expected={s["name"] for s in design["scenarios"]}
    assert len(expected)==24
    output=ROOT/"outputs/q2_portable/20261020T010519930750Z"
    verification=load(output/"verification.json")
    assert verification["status"]=="passed" and verification["cases"]==24
    assert {r["name"] for r in verification["results"]}==expected
    matches=[]
    for name in sorted(expected):
        computed=load(output/(name+".json"))
        full=load(RUN/(name+".json"))
        reference=load(folder/"reference_paths"/(name+".json"))
        assert computed["paths"]==reference["paths"]==full["paths"],name
        assert computed["targets"]==reference["targets"]==full["targets"],name
        assert computed["peak"]==reference["peak"]==full["peak"],name
        assert computed["reference_exact_match"]
        matches.append(name)
    return dict(status="read_only_snapshot_and_full_result_comparison_complete",
        original_source_hashes_checked_here=len(manifest["original_source_sha256"]),
        portable_runtime_rechecks_originals=False,
        records=record_summaries,exact_matches_to_full_run=matches,
        snapshot_manifest_sha256=sha(folder/"manifest.json"),
        verification_sha256=sha(output/"verification.json"),
        information_scope="Snapshot supplies immutable reader returns and historical training parameters; the unchanged factory constructs all 2025+ state and forecasts. Reference paths are used only after simulation for comparison.",
        finding="No material future-output injection or changed-model-logic issue found in the inspected adapter.")


def main():
    raw=PAPER.read_bytes()
    text=raw.decode("utf-8")
    case=json.loads((RUN/"S0.json").read_text("utf-8"))
    idx={p["year"]:p for p in case["paths"]}
    expected={}
    for year in (2030,2060):
        p=idx[year]
        expected[str(year)]=dict(
            energy_100m_tce=f'{p["primary_energy_tce"]/1e8:.2f}',
            nonfossil_pct=f'{p["nonfossil_share"]*100:.2f}',
            positive_co2_gt=f'{p["positive_co2_t"]/1e9:.2f}',
            net_co2_gt=f'{p["net_co2_t"]/1e9:.2f}',
            neutralisation_pct=f'{p["neutralisation_ratio"]*100:.2f}',
            capacity_tw=f'{p["total_capacity_mw"]/1e6:.2f}')
    presence={y:{k:v in text for k,v in values.items()} for y,values in expected.items()}
    findings=[
        dict(priority=2,topic="annual chronology",
            old_text_present="各主体申请投资；共同预算和抵押/现金约束审核；年内求解能源平衡" in text,
            issue="Original paragraph placed proposals and approval before current operation and cash settlement.",
            correction="Drivers, maturity/retirement, operation, settlement and debt service precede learning/proposals, approval and construction payment.",
            source="src/energy_model/q2_national.py:NationalModel.step"),
        dict(priority=2,topic="recursive changing-elasticity demand",
            old_text_present="D(a,t)=D(a,0)×GDP(t)^ε(a,t)×(1−g_eff)^t" in text,
            issue="A current elasticity applied to cumulative GDP is not the implemented sequence of changing annual elasticities.",
            correction="D_t=D_(t-1)*(GDP_t/GDP_(t-1))^epsilon_t*(1-g_eff), with device composition treated separately.",
            source="src/energy_model/q2_national.py:NationalModel.drivers"),
        dict(priority=2,topic="private project versus system increment",
            old_text_present="施工能力与净增供能约束" in text,
            issue="Competitive entrant profitability uses allocated finite LP sales, including sales displaced from incumbents; it is not positive incremental sector profit or additional system output.",
            correction="Describe own project NPV and shared finite saleable output, construction, finance and pending projects.",
            source="src/energy_model/q2_project_competition.py:ProjectCompetitionModel.project_economics"),
        dict(priority=2,topic="price-year versus observed-price provenance",
            explicit_correction_present=all(s in text for s in (
                "电价与厂用电率采用2018观测延续代理","未替换为2024中国实际到厂价",
                "不表示每项都来自2024观测")),
            issue="A 2024 real-price unit must not imply observed 2024 national tariff or delivered fuel prices.",
            correction="State 2019-2024 tariff and auxiliary fractions persist 2018 nominal observations; fuel prices are fixed technical/reference assumptions, all expressed in 2024 CNY.",
            source="scripts/run_q2_historical_support.py:policy_inputs; src/energy_model/q2_national.py:NationalModel.__init__"),
    ]
    gas=dict(scope="Answer to the parent's implementation-scope question, not an additional Q3 review",
        implemented="gas supplier.price multiplied by 1.3; both domestic and imported offer costs rise, imported premium remains 5%",
        public_text_needed="A national common-gas supply price pressure affecting domestic and imported supply; not an import-cost-only shock.",
        source="src/energy_model/q2_forward_current.py:ForwardModel.drivers; src/energy_model/q2_national.py:NationalSupplier.offer")
    old_remaining=[f["topic"] for f in findings if f.get("old_text_present",False)]
    assert not old_remaining
    assert findings[-1]["explicit_correction_present"]
    assert all(v for checks in presence.values() for v in checks.values())
    result=dict(status="final_Q2_text_and_portable_review_complete",created_utc=datetime.now(timezone.utc).isoformat(),
        scope="Only the four required Q2 tasks; Q1 reused and Q3 review stopped per latest instruction.",
        reviewed_paper_sha256=sha256(raw).hexdigest(),
        frozen_S0_sha256=sha256((RUN/"S0.json").read_bytes()).hexdigest(),
        required_coverage={
            "Q2_1_agents":"Present: 18 aggregate agents with attributes, information and actions.",
            "Q2_2_rules_calibration_validation":"Present: rules, fiscal/physical interaction, 2015-2021 selection and honestly labelled already-seen 2022-2024 evaluation; corrected annual chronology, recursive demand and private project NPV match implementation.",
            "Q2_3_current_baseline_outputs":"Present: independent 2024 opening, 2030/2060 consumption/share/emissions, peak/time/value, two intensity reductions, R/P and remaining emissions.",
            "Q2_4_sensitivity":"Present: GDP growth +/-1 percentage point, cost decline 2/4%, carbon price x0.5/1.5, plus disclosed initial-state uncertainty."},
        expected_rounded_baseline_values=expected,rounded_value_presence_checks=presence,
        numerical_finding="No material baseline number mismatch found in the reviewed copy. Presence checks supplement manual table-to-result comparison; they do not verify every prose occurrence.",
        reviewed_target=PAPER.relative_to(ROOT).as_posix(),
        corrected_original_findings=findings,unresolved_material_findings=[],
        gas_price_scope={**gas,"Q2_paper_scope":"Gas stress scenario removed together with Q3; national fuel-price sensitivities remain."},
        portable_review=portable_review(),
        conclusion="The Q2-only paper covers all four required tasks, the four previously identified descriptions are corrected, and the 24 portable cases exactly reproduce full-run paths, targets and peak. No new mechanism or accuracy gate was introduced.",
        subsequent_regeneration="Findings and exact matches refer to the paper and input hashes in this receipt.")
    out=ROOT/"outputs/validation/q2_paper_review_20261020.json"
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n","utf-8")
    print(out)
    print(json.dumps(dict(hash=result["reviewed_paper_sha256"],
        baseline_values_present=all(v for checks in presence.values() for v in checks.values()),
        old_text_still_present={f["topic"]:f.get("old_text_present") for f in findings}),ensure_ascii=False,indent=2))


if __name__=="__main__":main()
