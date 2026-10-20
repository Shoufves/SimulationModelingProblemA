"""Independent project competition boundaries, including actual ETS settlement."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts"), str(ROOT / "tests")]
from test_q2_project_competition import ProjectCompetitionTests
from energy_model.q2_renewable_vintages import RenewableVintages
from energy_model.q2_exposure import AnnualExposure
from q2_corrected_factory import preflight
from q2_competition_factory import build
from q2_thermal_factory import build as previous_build


def main():
    paths = ["src/energy_model/q2_project_competition.py", "tests/test_q2_project_competition.py",
             "scripts/q2_competition_factory.py", "docs/sources/q2_project_competition.md",
             "scripts/review_q2_project_competition_independent.py"]
    hashes = {p: sha256((ROOT / p).read_bytes()).hexdigest() for p in paths}
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ProjectCompetitionTests)
    test_result = unittest.TextTestRunner(verbosity=1).run(suite)
    fixture = ProjectCompetitionTests()
    fixture.setUpClass()
    actual = fixture.model(renewable_vintages=RenewableVintages(
        new_project_cf={"wind": .3, "solar": .2}, evidence="independent fixture"),
        annual_exposure=AnnualExposure(.5, "independent fixture"))
    issue = None
    try:
        actual.run(2024)
    except ValueError as exc:
        issue = str(exc)
    data, design, _ = preflight()
    config = json.loads((ROOT / "workflow/q2_thermal_net58_recalibration.json").read_text("utf-8"))
    selected = json.loads((ROOT / config["warm_start_run"] / "training_selection.json").read_text("utf-8"))
    params = selected["scenarios"]["25"]["parameters"]
    switched_off = build(data, design, config, params, 25, end_year=2024, project_competition=False)[0]
    prior = previous_build(data, design, config, params, 25, end_year=2024, thermal_mode="net58")[0]
    fields = ["paths", "finance", "behavior", "operations", "projects", "assets", "balances", "thermal_fuel_ledger"]
    assert all(getattr(switched_off, field) == getattr(prior, field) for field in fields)
    assert switched_off.year_end_operation() == prior.year_end_operation()
    assert all(sha256((ROOT / p).read_bytes()).hexdigest() == digest for p, digest in hashes.items()), "Sources changed during review"
    receipt = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "blocked_by_actual_settlement_error" if issue else "passed_with_scope_limits",
        "specialized_tests": {"run": test_result.testsRun, "failures": len(test_result.failures), "errors": len(test_result.errors)},
        "actual_2015_2024_run": {"completed": issue is None, "error": issue,
                                "last_completed_year": actual.paths[-1]["year"] if actual.paths else None},
        "factory_switch_off_2015_2024_authority25_net58_exact": fields + ["year_end_operation"],
        "review": {
            "candidate_sales": "Actual LP total partitioned by effective thermal MW or renewable available output; does not require sector incremental sales",
            "thermal_fuel": "Candidate fuel calculated using candidate efficiency; physical total still harmonic by common utilisation",
            "support": "Thermal quote receives candidate own annualised hours and explicit support fraction; renewable screening receives own hours",
            "incumbents": "Remaining LP sales allocated to incumbents; actual cohort operating accounts expose lower incumbent revenue without charging it to candidate",
            "joint_screen": "Inherited finite shrink/remove/rescreen remains in force with revised project economics",
            "finance": "Representative sector cash/debt pool remains; no separate firm property rights or independent entrant finance is inferred",
        },
        "identified_boundary": "Original sector ledger uses ETS cash inflows positive (negative payment); project ETS transfer must use the same sign and profit must add the transfer",
        "limits": [
            "Cohort records before support do not themselves attribute support cash received or debt service to independent firms",
            "Within-technology common utilisation cannot represent efficient-unit merit order",
            "First positive operating-year forecast is extended by PV assumption; it does not model later entrant competition over the entire plant life",
        ],
        "source_sha256": hashes,
    }
    out = ROOT / "outputs/validation" / ("project_competition_independent_review_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".json")
    out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"receipt": out.relative_to(ROOT).as_posix(), "status": receipt["status"], "actual_error": issue}))


if __name__ == "__main__":
    main()
