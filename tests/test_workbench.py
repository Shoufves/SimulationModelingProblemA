import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from energy_model.agents import simulate
from energy_model.operations import simulate_operation_window
from energy_model.workbench import (
    AGENT_DEFAULTS, OPERATION_DEFAULTS, read_observation, run_agent_experiment,
    run_operation_experiment, workspace_snapshot,
)


class WorkbenchAdapterTests(unittest.TestCase):
    def test_agent_controls_apply_to_each_mechanism_and_export_replays(self):
        result = run_agent_experiment({
            "carbon_multiplier": 2, "renewable_capex_multiplier": 0.5,
            "import_capacity_multiplier": 0, "grid_capacity_multiplier": 0.5,
        })
        config = result["configuration"]
        self.assertEqual(config["policy"]["carbon_price_by_step"][-1], 10)
        self.assertEqual(config["generation"]["renewable"]["capex"], 8)
        self.assertTrue(all(p["import_limit"] == 0 for p in config["fuels"].values()))
        self.assertEqual(config["grid"]["generation_transfer_limit"], 50)
        self.assertEqual(result["cases"]["full_feedback"], simulate(config))
        self.assertEqual(result["cases"]["frozen_equipment"], simulate(config, substitution=False))
        self.assertEqual(result["cases"]["frozen_generation_investment"], simulate(config, investment=False))
        self.assertEqual(result["mode"], "synthetic")
        self.assertIsNone(result["national_forecast"])
        json.dumps(result, allow_nan=False)

    def test_operation_controls_keep_windows_comparable_and_export_replays(self):
        result = run_operation_experiment("grid_bottleneck", {
            "storage_capacity_mwh": 60, "charge_limit_mw": 30,
            "discharge_limit_mw": 10, "load_multiplier": 1.2,
            "carbon_multiplier": 2, "grid_capacity_multiplier": 0.8,
        })
        config = result["configuration"]
        self.assertEqual(list(config["windows"]), ["grid_bottleneck"])
        self.assertEqual(config["storage"]["initial_energy_mwh"], 0)
        self.assertEqual(config["storage"]["capacity_mwh"], 60)
        self.assertAlmostEqual(config["windows"]["grid_bottleneck"]["steps"][0]["demand_mw"], 36)
        for label, enabled in (("with_storage", True), ("without_storage", False)):
            self.assertEqual(result["cases"][label],
                             simulate_operation_window(config, "grid_bottleneck", storage_enabled=enabled))
        self.assertIsNone(result["annual_reliability"])
        self.assertIsNone(result["historical_calibration"])

    def test_run_identity_is_stable_and_changes_with_experiment(self):
        reference = run_agent_experiment()
        repeat = run_agent_experiment(dict(AGENT_DEFAULTS))
        changed = run_agent_experiment({"carbon_multiplier": 0})
        self.assertEqual(reference["run_id"], repeat["run_id"])
        self.assertEqual(reference["configuration_sha256"], repeat["configuration_sha256"])
        self.assertNotEqual(reference["run_id"], changed["run_id"])
        self.assertNotEqual(run_operation_experiment()["run_id"],
                            run_operation_experiment("persistent_low_wind_solar")["run_id"])

    def test_zero_storage_capacity_equals_disabled_storage(self):
        result = run_operation_experiment(parameters={"storage_capacity_mwh": 0})
        self.assertEqual(result["cases"]["with_storage"]["rows"], result["cases"]["without_storage"]["rows"])

    def test_invalid_or_unknown_controls_rejected(self):
        for function, parameters in (
            (run_agent_experiment, {"nation": "China"}),
            (run_agent_experiment, {"carbon_multiplier": float("nan")}),
            (run_agent_experiment, {"renewable_capex_multiplier": 0}),
            (run_agent_experiment, {"import_capacity_multiplier": -1}),
            (run_operation_experiment, {"storage_capacity_mwh": 121}),
            (run_operation_experiment, {"load_multiplier": True}),
        ):
            with self.assertRaises(ValueError):
                function(parameters=parameters)
        with self.assertRaises(ValueError):
            run_operation_experiment("unknown")

    def test_workspace_badges_fail_closed_when_evidence_check_fails(self):
        reference = workspace_snapshot()
        report = reference["report"]
        report["formal_input_check"]["passed"] = False
        report["formal_input_check"]["errors"] = ["synthetic evidence failure"]
        with patch("energy_model.workbench.make_report", return_value=report):
            failed = workspace_snapshot()
        self.assertEqual(failed["reviewed_measurements"], 0)
        self.assertFalse(any(item["review_id"] for item in failed["datasets"]))
        self.assertTrue(any(item["admission"] == "evidence_check_failed" for item in failed["datasets"]))

    def test_read_only_operations_preserve_research_files(self):
        paths = [
            "examples/synthetic_agents.json", "examples/synthetic_operation_windows.json",
            "data/sources.json", "data/evidence_reviews.json", "workflow/model_inputs.json",
            "workflow/state.json", "outputs/prototype/agent_runs.json",
            "outputs/prototype/operations/window_runs.json",
        ]
        before = {path: (ROOT / path).read_bytes() for path in paths}
        run_agent_experiment()
        run_operation_experiment(parameters=dict(OPERATION_DEFAULTS))
        snapshot = workspace_snapshot()
        self.assertTrue(snapshot["report"]["formal_input_check"]["passed"])
        self.assertEqual(before, {path: (ROOT / path).read_bytes() for path in paths})

    def test_observation_reader_cannot_open_code_or_escape_workspace(self):
        dataset = read_observation("data/observations/power_official_release_2024.json")
        self.assertEqual(dataset["source_id"], "S17")
        for path in ("src/energy_model/agents.py", "workflow/state.json", "../outside.json"):
            with self.assertRaises(ValueError):
                read_observation(path)


if __name__ == "__main__":
    unittest.main()
