"""Required provenance and actual-use bindings for the national Q2 candidate.

This is an execution contract, not evidence that a source has been reviewed.
The separate review must explicitly admit every required operation.
"""
import math
from .q2_statistics import SCOPE_EVIDENCE

DISPATCH_EVIDENCE = {
    "data/raw/q2_scope/ndrc_renewable_purchase_2016_625.html": dict(
        url="https://zfxxgk.ndrc.gov.cn/web/iteminfo.jsp?id=19721",
        locator="2016 NDRC 625, articles 2-4, 8 and 15; eligibility, safety, biomass purchase and priority",
        phrases=["生物质能", "最高优先调度等级", "暂时不参与市场竞争"]),
    "data/raw/q2_scope/ndrc_renewable_purchase_2024_order15.html": dict(
        url="https://zfxxgk.ndrc.gov.cn/web/iteminfo.jsp?id=20348",
        locator="2024 Order15, articles 3-6 and 24; guaranteed/market volumes, exclusions, effective 2024-04-01",
        phrases=["市场交易电量", "不计入全额保障性收购范围", "2024年4月1日起施行"]),
}

STRUCTURE_EVIDENCE = {
    "data/raw/q2_structure/howitt_positive_mathematical_programming_1995.pdf": dict(
        url="https://watershed.ucdavis.edu/sites/g/files/dgvnsk8531/files/products/2021-12/Positive%20Math%20Programing.pdf",
        locator="AJAE 77(2), pp329-342; opening calibration/nonlinear response method",
        review="Read methodological motivation for base-allocation calibration. Agriculture paper does not estimate Chinese electricity frictions; implementation is a disclosed PMP-inspired convex allocation score, not a replication or measured welfare cost."),
    "data/raw/q2_structure/iea_china_power_system_transformation_2019.pdf": dict(
        url="https://iea.blob.core.windows.net/assets/fd886bb9-27d8-4d5d-a03f-38cb34b77ed7/China_Power_System_Transformation.pdf",
        locator="Printed pp14-15; fair/economic dispatch and gas allocation in IEA scenarios",
        review="Read historical institutional/scenario discussion. Supports rejecting universal perfect substitutability as the only model; does not identify current hourly allocations, justify hard gas minima or certify the assumed score curvature."),
}

SOURCE_REQUIREMENTS = {'data/raw/batch1_national/nbs_2025_C09-02.jpg': {'allowed_use': 'energy_observations_and_initial_scale',
                                                  'operations': ['initialization',
                                                                 'calibration',
                                                                 'evaluation',
                                                                 'target_comparison'],
                                                  'metrics': ['consumption_10ktce',
                                                              'consumption_coal_pct',
                                                              'consumption_gas_pct',
                                                              'consumption_oil_pct',
                                                              'consumption_primary_electricity_other_pct'],
                                                  'row_use': 'observation'},
 'data/raw/batch1_national/nbs_2025_C09-15.jpg': {'allowed_use': 'capacity_observations_and_initial_scale',
                                                  'operations': ['initialization',
                                                                 'calibration',
                                                                 'evaluation'],
                                                  'metrics': ['hydro_capacity_mw',
                                                              'nuclear_capacity_mw',
                                                              'other_capacity_mw',
                                                              'solar_capacity_mw',
                                                              'thermal_capacity_mw',
                                                              'total_capacity_mw',
                                                              'wind_capacity_mw'],
                                                  'row_use': 'observation'},
 'data/raw/batch1_national/owid_energy_data.csv': {'allowed_use': 'generation_observations_initial_decomposition_crosscheck',
                                                   'operations': ['initialization',
                                                                  'calibration',
                                                                  'evaluation'],
                                                   'metrics': ['biofuel_electricity_mwh',
                                                               'coal_electricity_mwh',
                                                               'electricity_demand_mwh',
                                                               'electricity_generation_mwh',
                                                               'gas_electricity_mwh',
                                                               'hydro_electricity_mwh',
                                                               'net_elec_imports_mwh',
                                                               'nuclear_electricity_mwh',
                                                               'oil_electricity_mwh',
                                                               'solar_electricity_mwh',
                                                               'wind_electricity_mwh'],
                                                   'row_use': 'observation'},
 'data/raw/batch1_national/wdi_china_macro_2005_2025.json': {'allowed_use': 'constant_GDP_ratios_and_CPI_deflation',
                                                             'operations': ['historical_driver',
                                                                            'price_conversion',
                                                                            'target_comparison'],
                                                             'metrics': ['cpi', 'real_gdp'],
                                                             'row_use': 'observation'},
 'data/raw/lb/base/reports/china_btr1_2024.pdf': {'allowed_use': 'CO2_calibration_sparse_years_and_conditional_bridge',
                                                  'operations': ['calibration',
                                                                 'conditional_carbon_path',
                                                                 'conditional_peak_bridge',
                                                                 'target_comparison'],
                                                  'metrics': ['btr_combustion_co2_t',
                                                              'btr_net_co2_t',
                                                              'btr_positive_co2_t',
                                                              'btr_process_co2_t',
                                                              'btr_removals_co2_t',
                                                              'btr_waste_co2_t'],
                                                  'row_use': 'observation'},
 'data/raw/batch1_national/GCB2025v15_MtCO2_flat.csv': {'allowed_use': 'external_diagnostic_and_conditional_peak_bridge',
                                                        'operations': ['external_diagnostic',
                                                                       'conditional_peak_bridge'],
                                                        'metrics': ['gcb_positive_co2_t'],
                                                        'row_use': 'external_diagnostic_and_conditional_peak_bridge'},
 'data/raw/lb/ai_social/nbs_bulletin_2024.txt': {'allowed_use': '2024_currency_conversion',
                                                 'operations': ['price_conversion'],
                                                 'metrics': ['cny_per_usd'],
                                                 'row_use': 'observation'},
 'data/raw/lb/base/reports/iea_oecd_generation_cost_2020.pdf': {'allowed_use': 'technical_reference_not_observed_2024_fleet',
                                                                'operations': ['technical_reference'],
                                                                'metrics': [],
                                                                'row_use': 'observation'},
 'data/raw/batch3_scenarios/irena_power_costs_2024.pdf': {'allowed_use': 'wind_solar_capex_new_project_reference',
                                                          'operations': ['technical_reference'],
                                                          'metrics': [],
                                                          'row_use': 'observation'},
 'data/processed/technology_accounting_parameters.csv': {'allowed_use': 'IPCC and IRENA source-located '
                                                                        'reference cells',
                                                         'operations': ['technical_reference'],
                                                         'metrics': [],
                                                         'row_use': 'observation'},
 'data/processed/q1/cost_method_parameters.csv': {'allowed_use': 'Q1 reviewed O&M cells; new Q2 conditional '
                                                                 'use',
                                                  'operations': ['technical_reference'],
                                                  'metrics': [],
                                                  'row_use': 'observation'},
 'data/processed/q1/reviewed_2024_additions.csv': {'allowed_use': 'Q1 reviewed 2024 storage power/energy and '
                                                                  'nonfossil anchor, new scoped Q2 use',
                                                   'operations': ['initialization', 'statistical_bridge'],
                                                   'metrics': [],
                                                   'row_use': 'observation'},
 'data/raw/official/S28_qinshan_design_life_capture.txt': {'allowed_use': 'First Chinese nuclear unit grid '
                                                                          'date 1991-12-15; restrict '
                                                                          'reconstructed nuclear age; not a '
                                                                          'national licence database',
                                                           'operations': ['initialization'],
                                                           'metrics': [],
                                                           'row_use': 'observation'},
 'data/raw/batch3_scenarios/ipcc_2006_stationary_combustion.pdf': {'allowed_use': 'IPCC default NCV '
                                                                                  'emission-factor reference',
                                                                   'operations': ['technical_reference'],
                                                                   'metrics': [],
                                                                   'row_use': 'observation'},
 'data/processed/fuel_storage_hydrogen_snapshots.csv': {'allowed_use': 'reported snapshots, not inferred '
                                                                       'inventory',
                                                        'operations': ['initialization'],
                                                        'metrics': [],
                                                        'row_use': 'observation'},
 'data/processed/cea_market_annual.csv': {'allowed_use': '2024 annual turnover/volume, not universal '
                                                         'compliance price',
                                          'operations': ['policy_reference'],
                                          'metrics': [],
                                          'row_use': 'observation'},
 'data/raw/lb/international/cn_ets_allocation_2026.pdf': {'allowed_use': 'output-based allocation design, '
                                                                         'effective information after '
                                                                         'publication only',
                                                          'operations': ['policy_reference'],
                                                          'metrics': [],
                                                          'row_use': 'observation'},
 'data/raw/lb/international/cn_ets_notice.txt': {'allowed_use': 'publication date 2026-09-02; no '
                                                                'retrospective information',
                                                 'operations': ['policy_reference'],
                                                 'metrics': [],
                                                 'row_use': 'observation'},
 'data/processed/policy_target_reference.csv': {'allowed_use': 'source-specific target comparison only, no '
                                                               'forced attainment',
                                                'operations': ['target_comparison'],
                                                'metrics': [],
                                                'row_use': 'observation'}}

# These metrics alone enter the frozen training/evaluation loss. Adding a target
# requires an explicit source-use review, not just a new name in the design.
for _path in SCOPE_EVIDENCE:
    SOURCE_REQUIREMENTS[_path] = dict(allowed_use="statistical_category_and_conversion_method_review",
        operations=["statistical_bridge", "target_comparison"],metrics=[],row_use="reference_only")
for _path in DISPATCH_EVIDENCE:
    SOURCE_REQUIREMENTS[_path] = dict(allowed_use="nonfossil_priority_policy_motivation_and_scope_limit",
        operations=["policy_reference"],metrics=[],row_use="reference_only")
for _path in STRUCTURE_EVIDENCE:
    SOURCE_REQUIREMENTS[_path] = dict(allowed_use="aggregate_dispatch_method_motivation_not_measured_parameters",
        operations=["method_reference"],metrics=[],row_use="reference_only")
for _path in ("data/raw/batch1_national/nbs_2025_C09-02.jpg","data/raw/batch1_national/owid_energy_data.csv"):
    SOURCE_REQUIREMENTS[_path]["operations"].append("statistical_bridge")
    SOURCE_REQUIREMENTS[_path]["operations"].append("conditional_nonpower_identification")

CALIBRATION_METRICS = {
    "consumption_10ktce", "consumption_primary_electricity_other_pct",
    "total_capacity_mw", "wind_capacity_mw", "solar_capacity_mw", "hydro_capacity_mw", "nuclear_capacity_mw",
    "electricity_generation_mwh", "btr_combustion_co2_t",
    "consumption_coal_pct", "consumption_oil_pct", "consumption_gas_pct",
    "coal_electricity_mwh", "oil_electricity_mwh", "gas_electricity_mwh", "biofuel_electricity_mwh",
    "hydro_electricity_mwh", "nuclear_electricity_mwh", "wind_electricity_mwh", "solar_electricity_mwh",
}


def validate_admission(review, rows, design):
    sources = review.get("sources", [])
    indexed = {s["path"]:s for s in sources}
    if len(indexed) != len(sources) or set(indexed) != set(SOURCE_REQUIREMENTS):
        raise ValueError("Missing, duplicate or unexpected required national source")
    for path,required in SOURCE_REQUIREMENTS.items():
        source = indexed[path]
        if source.get("status") != "author_scoped_review_not_team_approval":
            raise ValueError("Source use pending or withdrawn: "+path)
        if source.get("allowed_use") != required["allowed_use"]:
            raise ValueError("Source allowed_use does not cover execution: "+path)
        if set(source.get("allowed_operations", [])) != set(required["operations"]):
            raise ValueError("Source operations do not cover execution: "+path)
        if not source.get("review") or not source.get("locator"):
            raise ValueError("Missing scoped review evidence: "+path)
    seen_metrics = set()
    for row in rows:
        path = row["source_path"]
        if path not in indexed:
            raise ValueError("Observation uses undeclared source: "+path)
        required,source = SOURCE_REQUIREMENTS[path],indexed[path]
        if row["source_sha256"] != source["sha256"] or row["metric"] not in required["metrics"]:
            raise ValueError("Observation/source lineage or metric mismatch: "+row["metric"])
        if row["use"] != required["row_use"] or not math.isfinite(float(row["value"])):
            raise ValueError("Observation use/value not admitted: "+row["metric"])
        seen_metrics.add(row["metric"])
    if seen_metrics != {m for spec in SOURCE_REQUIREMENTS.values() for m in spec["metrics"]}:
        raise ValueError("Missing required observation metric")
    if review.get("observations") != len(rows):
        raise ValueError("Observation count differs from scoped review")
    required_targets={fuel+"_share":"consumption_"+fuel+"_pct" for fuel in ("coal","oil","gas")}
    if design.get("model_revision",0)>=10:
        required_targets.update({t+"_capacity_mw":t+"_capacity_mw" for t in ("hydro","nuclear")})
        required_targets.update({t+"_generation_mwh":("biofuel" if t=="biomass" else t)+"_electricity_mwh"
                                 for t in ("coal","oil","gas","biomass","hydro","nuclear","wind","solar")})
    indexed_targets={t["metric"]:t for t in design["targets"]}
    if len(indexed_targets)!=len(design["targets"]) or any(indexed_targets.get(k,{}).get("observation")!=v for k,v in required_targets.items()):
        raise ValueError("Required calibration target absent or remapped")
    for target in design["targets"]:
        metric = target["observation"]
        if metric not in CALIBRATION_METRICS:
            raise ValueError("Metric not admitted to calibration: "+metric)
        for path,spec in SOURCE_REQUIREMENTS.items():
            if metric in spec["metrics"] and "calibration" not in indexed[path]["allowed_operations"]:
                raise ValueError("Calibration source use withdrawn: "+path)
