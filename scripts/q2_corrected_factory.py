"""Apply verified solar support years and run fixed-parameter full-history pairs.

This factory combines verified solar support duration and independent portfolio screening.
The original experiment remains reproducible against its own source hashes.
"""
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "src")]
from run_q2_revenue_recalibration import (preflight, save, sha, metrics, extract, training_loss,
                                         bio_inputs, cost_inputs)
from run_q2_historical_support import (scope_inputs, policy_inputs, NationalModel,
                                       add_initial_support, apply_announced_lifetime_limits)
from energy_model.q2_renewable_vintages import RenewableVintages
from energy_model.q2_exposure import AnnualExposure
from energy_model.q2_solar_entitlement import apply_solar_duration
from review_q2_revenue_candidate import review
from energy_model.q2_portfolio import PortfolioNationalModel


def verify_policy():
    folder = ROOT / "data/raw/q2_solar_entitlement"
    manifest = json.loads((folder / "source_manifest.json").read_text("utf-8"))[0]
    path = ROOT / manifest["path"]
    if not path.is_relative_to(folder) or hashlib.sha256(path.read_bytes()).hexdigest() != manifest["sha256"]:
        raise ValueError("Solar-duration policy original changed")
    text = path.read_text("utf-8")
    if any(phrase not in text for phrase in ("期限原则上为20年", "2014年1月1日及以后投运", "2013年8月26日")):
        raise ValueError("Solar-duration applicability was not verified")


def build(data, design, config, parameters, authority, *, end_year, include_bio=True, include_vintages=True):
    verify_policy()
    d, s, p, boundary, assumptions, source_paths = scope_inputs(data, design, parameters, recovery_share=.5)
    policy, cells, tax, prices, actual, _ = policy_inputs(d, s, cash_fraction=1, gas_price_factor=1,
        new_support=True, authority_multiple=authority)
    # New offers are configured before the model forms its first investment
    # expectation. Initial positions are adjusted before the first annual run.
    offer_changes = apply_solar_duration(policy)
    m = PortfolioNationalModel(d, s, p, 2014, revenue_policy=policy, operating_boundary=boundary, detail=True,
        generation_costs=cost_inputs(data, design),
        renewable_vintages=RenewableVintages(new_project_cf={t: parameters["new_"+t+"_cf"] for t in ("wind", "solar")},
                                            evidence="docs/sources/q2_revenue_recalibration.md") if include_vintages else None,
        bioenergy=bio_inputs(d, config, parameters) if include_bio else None,
        annual_exposure=AnnualExposure(**config["generator_annual_exposure"]))
    add_initial_support(m, actual)
    initial_changes = apply_solar_duration(m.revenue_policy)
    changes = []
    if end_year not in range(2015, 2025):
        raise ValueError("Expected a historical endpoint")
    for year in range(2015, end_year+1):
        if year >= 2021:
            changes.extend(apply_announced_lifetime_limits(m, zone="lower"))
        m.run(year)
    assumptions.update(portfolio_audit="shrink_failed_then_jointly_rescreen", solar_duration_rule="2013_1638_twenty_years_for_known_applicable_cohorts",
        pre2014_solar_approval_dates="unknown; prior entitlement reconstruction retained",
        solar_settlement_scope="aggregate central-style proxy; distributed self-consumption not separately reconstructed",
        policy_duration_changes=offer_changes+initial_changes,
        support_rates="unchanged historical aggregate effective spread; not 2013 tariff frozen for all years",
        commitment_authority_multiple_of_current_budget=authority,
        physical_solar_lifetime_years=25, solar_standard_eligibility_years=20,
        annual_exposure=m.annual_exposure.__dict__, extra_free_cash_or_assets=False)
    source_paths += ["data/raw/q2_solar_entitlement/ndrc_solar_2013_1638.html",
                     "data/raw/q2_solar_entitlement/source_manifest.json",
                     "src/energy_model/q2_solar_entitlement.py", "src/energy_model/q2_portfolio.py",
                     "scripts/q2_corrected_factory.py"]
    return m, assumptions, prices, changes, source_paths

