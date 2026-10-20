"""Independently verify the thermal training contract without fitting evaluation."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
from q2_thermal_configured_factory import build
from run_q2_revenue_recalibration import preflight, training_loss


def read(path):
    return json.loads((ROOT / path).read_text("utf-8"))


def main():
    previous = read("workflow/q2_corrected_recalibration.json")
    original = read("workflow/q2_national_design.json")
    configs = {mode: read(f"workflow/q2_thermal_{mode}_recalibration.json") for mode in ("net55", "net58")}
    stripped = [{k: v for k, v in c.items() if k != "thermal_mode"} for c in configs.values()]
    assert stripped[0] == stripped[1]
    for mode, config in configs.items():
        assert config["thermal_mode"] == mode
        assert config["training_years"] == list(range(2015, 2022))
        assert config["evaluation_years"] == [2022, 2023, 2024]
        assert config["authority_scenarios"] == [5, 25, 100]
        assert config["blocks"][:3] == previous["blocks"]
        assert config["blocks"][3] == {key: original["parameter_grid"][key]
                                        for key in ("expectation_rate", "investment_response")}
        assert {k: v for k, v in config.items() if k not in
                {"model_factory", "thermal_mode", "warm_start_run", "design_rationale", "blocks"}} == {
                    k: v for k, v in previous.items() if k not in
                    {"model_factory", "thermal_mode", "warm_start_run", "design_rationale", "blocks"}}
    source = (ROOT / "scripts/run_q2_thermal_recalibration.py").read_text("utf-8")
    assert "end_year=2021" in source
    assert 'item["loss"] < bests[authority]["loss"]' in source
    assert source.index('save(folder / "training_selection.json"') < source.index('end_year=2024')
    assert '("without_municipal_composition", dict(include_bio=False))' in source
    assert 'for authority, best in chosen.items()' in source
    data, design, _ = preflight()
    expected_targets = deepcopy(design["targets"])
    # The existing reviewed scope bridge names total hydro including pumped
    # storage explicitly; the thermal entry must preserve that earlier fix.
    for target in expected_targets:
        if target["metric"] == "hydro_capacity_mw" and target["observation"] == "hydro_capacity_mw":
            target["metric"] = "hydro_including_pumped_capacity_mw"
    selection = read(Path(configs["net55"]["warm_start_run"]) / "training_selection.json")
    checked = []
    for mode, config in configs.items():
        for authority in config["authority_scenarios"]:
            params = selection["scenarios"][str(authority)]["parameters"]
            model, assumptions, *_ = build(data, design, config, params, authority, end_year=2021)
            assert [r["year"] for r in model.paths] == list(range(2015, 2022))
            assert assumptions["thermal_mode"] == mode
            assert model.design["targets"] == expected_targets
            before = training_loss(model)
            # Exercise the actual scorer with deliberately corrupted holdout
            # observations: those records must not contribute to training.
            model.data = deepcopy(model.data)
            for key in list(model.data):
                if isinstance(key, tuple) and key[0] in (2022, 2023, 2024):
                    model.data[key] *= 1000
            assert training_loss(model) == before
            checked.append({"mode": mode, "authority": authority, "train_loss": before[0],
                            "holdout_data_perturbation_score_invariant": True})
    paths = ["scripts/run_q2_thermal_recalibration.py", "scripts/q2_thermal_configured_factory.py",
             "scripts/q2_thermal_factory.py", "scripts/run_q2_revenue_recalibration.py",
             "scripts/run_q2_national.py", "workflow/q2_thermal_net55_recalibration.json",
             "workflow/q2_thermal_net58_recalibration.json", "workflow/q2_corrected_recalibration.json",
             "workflow/q2_national_design.json", "scripts/review_q2_thermal_training_entry_independent.py"]
    out = ROOT / "outputs/validation/thermal_training_entry_independent_review_20261020.json"
    assert not out.exists()
    receipt = dict(created_at=datetime.now(timezone.utc).isoformat(), status="passed_entry_contract",
                   checked_actual_training_models=checked,
                   original_three_blocks_preserved=True, original_formal_expectation_investment_grid_preserved=True,
                   original_targets_and_thresholds_preserved=True,
                   selection_saved_before_evaluation=True, all_authority_and_composition_cases_reported=True,
                   technical_mode_fixed_before_training=True,
                   limitations=["Entry review does not certify eventual completed searches or results",
                                "Finite coordinate search does not prove global optimality",
                                "Evaluation remains already seen and cannot support blind validation claims"],
                   source_sha256={p: sha256((ROOT / p).read_bytes()).hexdigest() for p in paths})
    out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"receipt": out.relative_to(ROOT).as_posix(), "actual_training_models": len(checked)}))


if __name__ == "__main__":
    main()
