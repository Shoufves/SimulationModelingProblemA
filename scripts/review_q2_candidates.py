"""Inventory existing public Q2 candidates and verify the GCB CSV transcription.

No original source/use contracts are changed. This is not national admission.
An existing Q2 contract is verified, never silently re-pinned by this command.
"""
import csv
import json
from pathlib import Path
from collections import defaultdict
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from run_q2 import sha,dump,csv_write,preflight


CANDIDATES = {
    "national_history":"data/processed/unified/nbs_history.csv",
    "nbs_lineage":"data/catalog/nbs_record_provenance.csv",
    "gcb_history":"data/processed/china_co2_gcb_annual.csv",
    "technology_parameters":"data/processed/technology_accounting_parameters.csv",
    "policy_targets":"data/processed/policy_target_reference.csv",
    "macro":"data/processed/china_macro_annual.csv",
    "sector_2023":"data/processed/nbs_sector_use_2023.csv",
    "q1_handoff":"outputs/q1/p1_yx/model_handoff.csv",
    "storage_nonfossil":"data/processed/q1/reviewed_2024_additions.csv",
    "generation_history":"data/observations/power_generation_2015_2024.json",
    "carbon_market":"data/processed/cea_market_annual.csv",
    "fuel_storage":"data/processed/fuel_storage_hydrogen_snapshots.csv",
}
SOURCE_KEYS = ["yx:GCB_GCB2025v15_MtCO2_flat","yx:IPCC_ENERGY_STATIONARY","yx:IRENA_COST_2024_PDF",
               "yx:POLICY_CARBON_2021","yx:POLICY_CARBON_2026","yx:NBS_2025_C09-02","yx:NBS_2025_C09-15"]


def read_csv(path):
    with path.open(encoding="utf-8-sig",newline="") as f:return list(csv.DictReader(f))


def main():
    folder = ROOT/"outputs/q2/p2_lb_input_review"
    folder.mkdir(parents=True,exist_ok=True)
    config_path = ROOT/"workflow/q2_inputs.json"
    # Guard before any report write so modified inputs cannot silently acquire new review hashes.
    if config_path.exists():preflight(json.loads(config_path.read_text(encoding="utf-8")))
    registry = json.loads((ROOT/"data/catalog/sources_unified.json").read_text(encoding="utf-8"))
    by_source = {r["source_key"]:r for r in registry}
    originals = []
    for key in SOURCE_KEYS:
        r = by_source[key]
        p = ROOT/r["canonical_path"]
        actual = sha(p)
        originals.append(dict(source_key=key,path=r["canonical_path"],actual_sha256=actual,
            catalog_sha256=r["sha256"],matches_catalog=actual==r["sha256"],
            review="identity only; numeric original-page verification not claimed except GCB rows below"))
    raw_path = ROOT/by_source["yx:GCB_GCB2025v15_MtCO2_flat"]["canonical_path"]
    raw = {int(r["Year"]):(i,r) for i,r in enumerate(read_csv(raw_path),start=2) if r["ISO 3166-1 alpha-3"] == "CHN"}
    checked = []
    for row in read_csv(ROOT/CANDIDATES["gcb_history"]):
        year = int(row["year"])
        if year not in range(2005,2025):continue
        line,source = raw[year]
        column = row["variable"]
        observed = source.get(column)
        equal = observed not in (None,"") and abs(float(observed)-float(row["value"])) < 1e-8
        checked.append(dict(year=year,variable=column,value=row["value"],unit=row["unit"],
            raw_path=raw_path.relative_to(ROOT).as_posix(),raw_row=line,raw_column=column,
            raw_value=observed,transcription_matches=equal,allowed_use="candidate_inventory_only",
            boundary="GCB territorial fossil/industry CO2; not total GHG or net removals; category definitions still require model bridge"))
    if not checked or not all(r["transcription_matches"] for r in checked):
        raise ValueError("GCB original/transcription mismatch; do not update contract")
    coverage = []
    for role,path in CANDIDATES.items():
        if not path.endswith(".csv") or role in {"q1_handoff","nbs_lineage"}:continue
        groups = defaultdict(list)
        for row in read_csv(ROOT/path):
            if str(row.get("year","")).isdigit() and 2015 <= int(row["year"]) <= 2024:
                groups[row.get("variable","unknown"),row.get("unit","unknown")].append(row)
        for (variable,unit),rows in sorted(groups.items()):
            years = sorted({int(r["year"]) for r in rows if r.get("value","") != ""})
            coverage.append(dict(dataset=role,path=path,variable=variable,unit=unit,years=years,
                training_years_present=sorted(set(years)&set(range(2015,2022))),
                evaluation_years_present=sorted(set(years)&{2022,2023,2024}),
                missing_2015_2024=sorted(set(range(2015,2025))-set(years)),
                status="candidate_not_national_admission"))
    gaps = [
        dict(id="G01_history_initial_state",available="2015全国规模和装机、GDP序列已存",required="2015部门设备/燃料用途/库存/在建资产、同口径主体现金与政策初态；不能倒用2024"),
        dict(id="G02_current_initial_state",available="2024全国规模、2021—2024新型储能功率能量、471条Q1交接",required="2024实际可用设备、期初SOC/库存、年龄及在建队列；功率能量不自动提供SOC"),
        dict(id="G03_cost_efficiency",available="风光CAPEX和部分IPCC默认因子；其他技术报告原文",required="逐技术统一价年CAPEX/OPEX、效率、寿命、融资；热值及用途匹配；不是继续增加LCOE表"),
        dict(id="G04_chronology",available="2018重建负荷和年度燃料/发电统计",required="明确代表窗口/同期供需/来水与进口提取约束的研究假设；年度进口量不能直接改小时能力"),
        dict(id="G05_policy_settlement",available="ETS年度交易和政策原文、2030/2060目标",required="历史可知覆盖、免费配额、净履约与真实结算；目标仅比较，不强迫模型达标"),
        dict(id="G06_calibration_design",available="总量/结构/装机/GCB候选历史；工程损失函数已实现",required="三人共同冻结误差尺度、权重、参数界、阈值与情景范围；合成配置不升级为正式设置"),
        dict(id="G07_primary_carbon_bridge",available="NBS一次电力及其他、2024初步非化石19.8%、GCB原始行已复核",required="一次能源官方折算与非化石口径桥接；总量/行业正排放与净移除同边界，物理MWh不直接比较官方占比"),
        dict(id="G08_future_paths",available="既有政策目标、技术报告和宏观历史",required="到2060的GDP/成本/净移除条件路径与合理范围：属于明确研究假设，不能等待或冒充未来实测"),
        dict(id="G09_model_extensions",available="本分支Mesa/LP工程闭环与反例",required="部门设备年龄退出、全国初态桥接、ETS/统计口径；多区/季节与CCUS未实现，不声称已满足"),
    ]
    csv_write(folder/"candidate_coverage.csv",coverage)
    csv_write(folder/"gcb_transcription_checks.csv",checked)
    csv_write(folder/"gaps_and_conflicts.csv",gaps)
    dump(folder/"source_identity_checks.json",originals)
    inputs = [dict(role=role,path=path,sha256=sha(ROOT/path),allowed_use="candidate_inventory_only",
        review="Existing candidate checked for schema/coverage; no national initialization/calibration admission. See outputs/q2/p2_lb_input_review.")
        for role,path in CANDIDATES.items()]
    inputs += [dict(role="original/"+r["source_key"],path=r["path"],sha256=r["actual_sha256"],allowed_use="candidate_inventory_only",
                    review=r["review"]) for r in originals]
    if not config_path.exists():
        dump(config_path,dict(schema_version=1,owner="p2/lb",base_sha="804ec15ee43874303986a7ad91b2cde05c65b124",
            mode="national_pending_review",warning="Candidate inventory only; Q1 contracts remain unchanged; no national defaults or automatic repinning",
            inputs=inputs,gaps=gaps,scientific_acceptance=False))
    else:
        existing = json.loads(config_path.read_text(encoding="utf-8"))
        if inputs != existing["inputs"] or gaps != existing["gaps"]:
            raise ValueError("Q2 inventory/design changed; explicit review required, existing contract retained")
    (folder/"report.md").write_text("# Q2 既有公开资料复核\n\n"
        f"复核 {len(inputs)} 个候选/原件文件；GCB 2005—2024 共 {len(checked)} 个转录值逐一与原CSV行列一致；形成 {len(coverage)} 组2015—2024覆盖记录。\n\n"
        "这解决文件身份和GCB转录准确性，不代表这些资料已适用于全部模型用途。NBS一次电力及其他不能直接当非化石消费占比；GCB化石与工业排放不是全国净排放。\n\n"
        "2015—2021训练、2022—2024已接触留出。工程夹具有损失/搜索/灵敏度功能，正式参数和数据仍需单独审查。\n\n"
        "| 缺口 | 可用部分 | 后续动作 |\n|---|---|---|\n"+
        "\n".join(f"| {g['id']} | {g['available']} | {g['required']} |" for g in gaps)+"\n",encoding="utf-8")
    dump(folder/"review_manifest.json",dict(status="candidate_inventory_checked_not_admitted",
        source_hashes={i["path"]:i["sha256"] for i in inputs},code_sha256=sha(Path(__file__)),
        outputs={p.name:sha(p) for p in sorted(folder.iterdir()) if p.is_file() and p.name != "review_manifest.json"},
        raw_numeric_check="GCB CSV rows only; other original pages are not newly numerically verified"))
    print(json.dumps(dict(candidate_files=len(inputs),gcb_cells=len(checked),coverage_groups=len(coverage)),ensure_ascii=False))


if __name__ == "__main__":main()
