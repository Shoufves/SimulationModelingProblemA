"""Explicitly review existing trade cells and freeze a conditional Q3 proposal.

This command is never called automatically by the experiment runner. Revisions
require a new configuration filename; an existing frozen proposal is preserved.
"""
import argparse
import csv
from datetime import datetime, timezone
import json
from math import isclose
from pathlib import Path
import sys

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from run_q2_national import preflight, INPUTS, sha, dump

BASE = "500436ffe8a9ecdf0ebcad3cdae87ef9deddbf93"
TRADE = ["data/processed/lb/trade_alternatives/pipeline_gas_china_2024.csv",
         "data/processed/lb/trade_alternatives/lng_china_2024.csv"]
WORKBOOK = "data/raw/lb/trade_alternatives/ei_2025_data.xlsx"


def review_trade():
    workbook = openpyxl.load_workbook(ROOT/WORKBOOK, read_only=True, data_only=True)
    checked, totals, selected = [], [], 0.0
    try:
        for rel in TRADE:
            rows = list(csv.DictReader((ROOT/rel).open(encoding="utf-8-sig", newline="")))
            sheet = workbook[rows[0]["sheet"]]
            cells = {c.coordinate: c.value for row in sheet.iter_rows(max_row=30, max_col=24) for c in row if hasattr(c, "coordinate")}
            values = []
            for row in rows:
                value = cells[row["cell"]]
                assert isinstance(value, (int, float)) and isclose(float(row["value"]), value, rel_tol=1e-12)
                assert row["year"] == "2024" and row["destination"] == "China"
                assert row["unit"] == "billion cubic metres; GCV 40 MJ/m3"
                column = ''.join(c for c in row["cell"] if c.isalpha())
                header = 3 if "pipeline" in row["sheet"] else 4
                origin = str(cells.get(column+str(header))).strip()
                if header == 4 and cells.get(column+"3") is not None:
                    origin = str(cells[column+"3"]).strip()+" "+origin
                assert origin == row["origin"]
                row_number = int(''.join(c for c in row["cell"] if c.isdigit()))
                assert cells["A"+str(row_number)] == "China"
                if row["row_type"] == "origin":
                    values.append(value)
                    if row["origin"] == "Russian Federation":
                        selected += value
                else:
                    assert row["row_type"] == "total"
                    totals.append(value)
                checked.append(dict(table=rel, sheet=row["sheet"], cell=row["cell"], value=value,
                                    origin=row["origin"], unit=row["unit"], row_type=row["row_type"]))
            assert isclose(sum(values), totals[-1], rel_tol=1e-10)
    finally:
        workbook.close()
    return dict(workbook=WORKBOOK, workbook_sha256=sha(ROOT/WORKBOOK), cells=checked,
                selected_origin="Russian Federation", selected_bcm_gcv=selected,
                total_import_bcm_gcv=sum(totals), fraction=selected/sum(totals),
                use="dimensionless 2024 import composition reference only",
                new_q3_assumption="Apply this fraction to Q2's CONDITIONAL aggregate gas delivery envelope; equal quality conversion and source costs. No bcm-to-LHV conversion or hourly capacity observation is asserted.",
                excluded_uses=["observed hourly deliverability", "historical outage", "event probability", "route-level causal attribution"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="workflow/q3_inputs.json")
    args = parser.parse_args()
    path = (ROOT/args.config).resolve()
    review_path = ROOT/"data/catalog/q3_input_review.json"
    if path.exists() or review_path.exists():
        raise ValueError("Frozen proposal already exists; preserve it and explicitly version revisions")
    if path.parent != ROOT/"workflow":
        raise ValueError("Configuration must be in workflow")
    preflight()  # Revalidate upstream evidence and restricted-use exclusions.
    trade = review_trade()
    review = dict(owner="mmj", base_sha=BASE, status="author_reviewed_conditional_proposal",
                  team_approved=False, reviewed_at_utc=datetime.now(timezone.utc).isoformat(),
                  inherited_q2_review="data/catalog/q2_national_input_review.json",
                  inherited_use="unchanged Q2 initialization/calibrated parameters/conditional annual model; no new empirical validation claim",
                  trade=trade, source_hashes={p:sha(ROOT/p) for p in [*TRADE, WORKBOOK]},
                  permissions=["conditional_annual_scenarios", "conditional_event_composition", "conditional_event_shape", "h02_battery_response_freeze"],
                  event_basis="author-designed stress grid; no historical disaster or country interruption likelihood claimed",
                  physical_scope="single node; repeated 24h input SHAPES over continuous noncyclic state; same restored terminal inventories")
    dump(review_path, review)
    config = dict(schema_version=1, owner="p3/mmj", base_sha=BASE,
                  status="author_frozen_conditional_proposal", team_approved=False,
                  frozen_at_utc=datetime.now(timezone.utc).isoformat(),
                  source_review="data/catalog/q3_input_review.json",
                  source_review_sha256=sha(review_path),
                  input_hashes={p:sha(ROOT/p) for p in [*INPUTS, *TRADE, WORKBOOK,
                      "outputs/q2/p2_lb_national/calibration.json", "outputs/q2/p2_lb_national/baseline_path.csv"]},
                  initial_year=2024, end_year=2060, snapshot_year=2030,
                  calibration_policy="reuse locked Q2 best parameters; never refit per event",
                  cost_price_year=2024, random_seed=12,
                  scope="conditional_mainland_aggregate_not_official_forecast",
                  information=dict(annual="Q2 contemporaneous announced information and paid queues",
                                   event="same finite whole-window perfect foresight for all scenarios; optimistic information assumption"),
                  scenarios=dict(S0={}, SP=dict(carbon_price_multiplier=1.4, public_year=2024, effective_year=2025),
                                 SG=dict(change="selected_import_gas_capacity_only"),
                                 ST=dict(storage_new_project_cost_multiplier=.75, public_year=2024, effective_year=2025),
                                 SW=dict(change="wind_solar_availability_and_hydro_energy_only"),
                                 SGW=dict(change="exact_SG_plus_SW")),
                  parameter_identity="All SP/ST multipliers and event timing/severity are author conditional hypotheses, not empirically estimated policy or disaster parameters",
                  events=[dict(id="selection_moderate", split="selection", window_days=9, start_hour=24,
                               duration_hours=96, recovery_hours=48, gas_channel_loss=.6, renewable_loss=.4),
                          dict(id="test_deeper", split="test", window_days=11, start_hour=24,
                               duration_hours=120, recovery_hours=48, gas_channel_loss=1.0, renewable_loss=.65)],
                  event_rationale="Finite two-point mechanism exercise: moderate selection and longer/deeper held-out conditional stress. Separate versions required for changes after viewing results; no probabilistic coverage claimed.",
                  safety=dict(relative_shortage_tolerance=1e-8, absolute_shortage_tolerance_mwh=.001,
                              recovery_periods=4, critical_service_limit=.01,
                              service_priority="retain Q2 priorities; report each service separately",
                              threshold_identity="author comparison bounds, not statutory reliability criteria"),
                  numerical=dict(relative_comparison_tolerance=1e-10, absolute_comparison_tolerance=1e-6,
                                 cash_balance_absolute_cny=.01,
                                 cash_balance_relative=1e-12,
                                 basis="Q2 settle() existing currency-balance tolerance; numerical policy fixed before Q3 results"),
                  h02=dict(frozen_response="battery discharge cannot exceed matched S0 dispatch in each period",
                           retained="same physical assets, stocks, service requests, source envelopes and calendar",
                           interpret="only this specified storage response contribution, not all multi-energy propagation"),
                  work_packages=dict(six_scenarios="implementing", h01="pending", h02="implementing", policy="pending"),
                  proposed_h01=dict(vR=[.01,.03], vE=[0,.6], extra_delay_years=[0,3],
                                    rules=["fixed_schedule","cost_order","service_ready","anticipatory"],
                                    information_horizon_years=3, authorized_early_exit_window_years=5,
                                    identity="conditional proposal; execution configuration still to be reviewed before H01 experiments"),
                  proposed_policy=dict(public_budget_fraction_gdp=.0005,
                                       scope="finite single actions and necessary pairs; implement actors, financing and construction before experiments",
                                       identity="not yet executed or accepted; no efficacy claim"))
    dump(path, config)
    print(json.dumps(dict(config=str(path), cells_checked=len(trade["cells"]), channel_fraction=trade["fraction"],
                          status=config["status"]), ensure_ascii=False))


if __name__ == "__main__":
    main()
