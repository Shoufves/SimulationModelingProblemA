"""Freeze a new, explicitly conditional H01/policy protocol; never rewrite V2."""
from datetime import datetime, timezone
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from run_q2_national import load, dump, sha


def main():
    target = ROOT/"workflow/q3_inputs_v3.json"
    review_target = ROOT/"data/catalog/q3_transition_review.json"
    if target.exists() or review_target.exists():
        raise ValueError("Preserve the frozen protocol; use an explicitly versioned revision")
    previous = ROOT/"workflow/q3_inputs.json"
    config = load(previous)
    review = dict(owner="mmj",base_sha=config["base_sha"],team_approved=False,
        status="author_reviewed_conditional_protocol",reviewed_at_utc=datetime.now(timezone.utc).isoformat(),
        inherited_review=config["source_review"],inherited_review_sha256=config["source_review_sha256"],
        original_protocol_sha256=sha(previous),
        identity="No new empirical observation. Existing approved-use Q2 stocks/financial mechanisms are extended by explicit author-designed interventions.",
        permissions=["conditional_retirement_timing","fixed_application_replay","public_infrastructure_programmes","finite_policy_screening"],
        review=[
            dict(parameter="vR",unit="fraction_initial_coal_MW_per_year",use="early retirement authorisation; only initial reconstructed cohorts within 5 years of technical expiry",evidence="author hypothesis; not observed legal authorisation"),
            dict(parameter="vE",unit="share_eligible_device_renewal_and_expansion",use="existing Q2 adoption parameter; never replaces installed devices immediately",evidence="author grid; conditional on inherited relative-cost eligibility"),
            dict(parameter="L",unit="year",use="additional grid/storage/gas-release construction delay; no generation/device delay or overnight stock change",evidence="author grid"),
            dict(parameter="retention_cost",unit="2024_real_CNY_per_year",use="1% of retained book construction cost annually, paid public maintenance/capacity service; original technical expiry and 2060 deadline binding",evidence="author assumption; no legal life extension"),
            dict(parameter="budget",unit="fraction_2024_price_GDP",use="extra public appropriation ceiling .0005 annually, full capital reserved at approval; maintenance and retention consume same ceiling",evidence="author fiscal experiment, not forecast tax revenue"),
            dict(parameter="gas_release_capex",unit="2024_real_CNY_per_MW_thermal",use="1e6 with 2-year construction and 20-year life; throughput only, no added stock/tank/fuel/import capacity",evidence="author engineering hypothesis; factor sensitivity required before recommendation"),
            dict(parameter="grid_storage_capex_efficiency_life",unit="inherited_Q2_units",use="unchanged conditional Q2 technology/cost data; deployment support, no free technical breakthrough",evidence="inherits Q2 purpose and uncertainty"),
            dict(parameter="terminal_asset_value",unit="2024_real_CNY",use="straight-line residual construction value discounted to 2024; paired initial capital identical; report gross and net costs",evidence="accounting convention, not observed resale value"),
            dict(parameter="test_events",unit="conditional_event",use="existing deeper condition remains already seen; no blind-test or population probability claim",evidence="unchanged V2 stress values")],
        exclusions=["new empirical permit claims","automatic national reliability probability","new emissions forecast calibration","interprovincial congestion","AI/household/employment extensions"])
    dump(review_target,review)
    config.update(revision=3,frozen_at_utc=datetime.now(timezone.utc).isoformat(),
        revision_reason="Freeze H01 and paid policy protocol before first transition run; retain V2 inputs and stage evidence. Split material-input services by fuel to avoid false substitutability.",
        transition_review=review_target.relative_to(ROOT).as_posix(),transition_review_sha256=sha(review_target))
    config.pop("proposed_h01");config.pop("proposed_policy")
    config["transition"] = dict(
        vR=[.01,.03],vE=[0.,.6],delay_years=[0,3],fixed_vR=.01,fixed_vE=.6,
        rules=["fixed_schedule","cost_order","service_ready","anticipatory"],
        modes=["full_response","fixed_projects"],
        early_exit_window_years=5,information_horizon_years=3,epsilon_candidates=[.005,.01],
        annual_retention_cost_fraction=.01,annual_public_asset_maintenance_fraction=.01,
        public_budget_fraction_gdp=.0005,public_project_power_fraction=.01,
        gas_release_capex_cny_per_mw=1e6,gas_release_lead_years=2,gas_release_lifetime_years=20,
        gas_release_build_fraction=.02,channel_fraction=load(ROOT/config["source_review"])["trade"]["fraction"],
        evaluation_years=[2030,2060],
        information="Current assets, paid/fully funded committed queues, current growth expectations and frozen selection plateau; no future realised state or test-event values in rules",
        fixed_project_identity="Replay fixed_schedule full-response approved applications, revealed only in original decision years; all capital amounts, payment schedules, service-device mix and base permits identical; cash/finance failure invalidates fixed-set comparison",
        deadline="Early-exit cohorts may defer only to min(original technical exit,2060); no new technical life extension",
        planner_limit="Binding flags screen grid/storage action candidates. Conditional 24h plateau screen is separate from continuous-event outcome; unresolved fuel/device deficits remain risks.",
        fixed_rule_tie="Cost order uses avoidable holding cost per MW then technical expiry; homogeneous coal cohorts can tie exactly with fixed schedule; never invent unit-level heterogeneity")
    config["policy"] = dict(candidates=[
        dict(id="none",rule="fixed_schedule",actions=[]),
        dict(id="retain",rule="service_ready",actions=[]),
        dict(id="grid",rule="fixed_schedule",actions=["grid"]),
        dict(id="storage",rule="fixed_schedule",actions=["storage"]),
        dict(id="gas_release",rule="fixed_schedule",actions=["gas_release"]),
        dict(id="grid_storage",rule="fixed_schedule",actions=["grid","storage"]),
        dict(id="retain_storage",rule="service_ready",actions=["storage"]),
        dict(id="gas_release_storage",rule="fixed_schedule",actions=["gas_release","storage"])],
        scope="Finite alternatives, no continuous/global optimality claim; equal annual appropriation ceiling, not mandatory equal expenditure",
        carbon_limit_ratio=1.,gross_cost_limit_ratio=1.05,service_limit=.01,
        tradeoff_carbon_ratios=[.95,1.,1.05],tradeoff_cost_ratios=[1.,1.05,1.1],
        ranking=["worst_selection_service_fraction","net_resource_cost_cny","cumulative_combustion_co2_t","id"],
        no_feasible="Report none; sensitivity bounds never replace designated constraints",
        selection="All candidates evaluated against annual services plus S0/SG/SW/SGW in selection event at 2030 and 2060; lock before deeper event evaluation",
        test_identity=config["test_identity"])
    config["sensitivity"] = [
        dict(id="retention_half",target="transition.annual_retention_cost_fraction",multiplier=.5),
        dict(id="retention_double",target="transition.annual_retention_cost_fraction",multiplier=2.),
        dict(id="public_budget_half",target="transition.public_budget_fraction_gdp",multiplier=.5),
        dict(id="public_budget_double",target="transition.public_budget_fraction_gdp",multiplier=2.),
        dict(id="gas_release_cost_half",target="transition.gas_release_capex_cny_per_mw",multiplier=.5),
        dict(id="gas_release_cost_double",target="transition.gas_release_capex_cny_per_mw",multiplier=2.)]
    config["sensitivity_scope"] = "Run each single-factor change for ALL eight fixed policy candidates; independent ranking with original constraints, no new policy search or retuning on test events. vR/vE/L and epsilon already have H01 grids."
    config["compute_budget"] = dict(max_transition_annual_runs=116,max_years_per_run=36,
        rationale="6 unique H01 cells x (3 controls+2 epsilon values) x 2 modes=60; 8 policy candidates + 6 one-factor grids x 8=56. All deterministic, no agent parallelism.")
    config["work_packages"] = dict(six_scenarios="implemented",h01="frozen_before_execution",h02="implemented",policy="frozen_before_execution")
    dump(target,config)
    print(json.dumps(dict(config=str(target),review=str(review_target),sha256=sha(target))))


if __name__=="__main__":main()
