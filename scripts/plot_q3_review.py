"""Render a readable comparison from verified Q3 results without changing a run.

The original frozen report/scatterplot is retained. This is postprocessing only;
its separate receipt binds the source run, CSV inputs, script and exported figure.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from run_q3 import verify_latest

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", default="outputs/q3/p3_mmj_v5")
    parser.add_argument("--output-dir", default="outputs/validation/p3_mmj/figures")
    args = parser.parse_args()
    source, out = (ROOT / args.input_dir).resolve(), (ROOT / args.output_dir).resolve()
    if not out.is_relative_to(ROOT) or out == source or out.is_relative_to(source):
        raise ValueError("Use a separate repository output directory; preserve the frozen run")
    manifest = verify_latest(source)
    rows = read(source / "policy_results.csv")
    if len(rows) != 8 or any(row["status"] != "completed" for row in rows):
        raise ValueError("This eight-candidate view requires eight completed policy cases")
    base = next(row for row in rows if row["policy_id"] == "none")
    out.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.size": 10, "figure.dpi": 150,
                         "axes.spines.top": False, "axes.spines.right": False})
    fig, axes = plt.subplots(1, 3, figsize=(15, 5.6), sharey=True, layout="constrained")
    labels = [row["policy_id"] for row in rows]
    positions = list(range(len(rows)))
    panels = [
        ([100 * float(row["worst_test_service_fraction"]) for row in rows],
         "Worst test service shortage", "% of that service's demand", "%.2f", "#b95036"),
        ([(float(row["net_resource_cost_cny"]) - float(base["net_resource_cost_cny"])) / 1e12 for row in rows],
         "Change in net resource cost", "Trillion CNY (2024 prices)", "%+.4f", "#326a93"),
        ([(float(row["cumulative_combustion_co2_t"]) - float(base["cumulative_combustion_co2_t"])) / 1e9 for row in rows],
         "Change in combustion CO2", "Gt, cumulative 2025-2060", "%+.4f", "#737341"),
    ]
    for ax, (values, title, unit, fmt, color) in zip(axes, panels):
        bars = ax.barh(positions, values, height=.58, color=color)
        ax.bar_label(bars, fmt=fmt, padding=4, fontsize=9)
        ax.set(title=title, xlabel=unit)
        ax.set_xlim(0, max(values) * 1.28 if max(values) > 0 else 1)
        ax.grid(axis="x", alpha=.15)
        ax.set_axisbelow(True)
    axes[0].set_yticks(positions, labels)
    axes[0].invert_yaxis()
    limit = 100 * json.loads((source / "frozen_config.json").read_text(encoding="utf-8"))["policy"]["service_limit"]
    axes[0].axvline(limit, color="#272727", linestyle="--", linewidth=1.2, label=f"Service limit: {limit:g}%")
    axes[0].legend(loc="lower right", fontsize=9)
    fig.suptitle("Q3 finite policy comparison: no candidate meets the designated common constraints", fontsize=13)
    fig.supxlabel("Cost and CO2 changes are relative to 'none'. Net cost deducts terminal assets; feasibility uses gross cost.", fontsize=10)
    output = out / "policy_comparison.png"
    fig.savefig(output)
    plt.close(fig)
    receipt = {
        "kind": "postprocessing_only", "run_id": manifest["run_id"],
        "source_manifest_sha256": sha(source / "run_manifest.json"),
        "source_files": {name: sha(source / name) for name in ("policy_results.csv", "frozen_config.json")},
        "script_sha256": sha(__file__), "outputs": {output.name: sha(output)},
        "original_run_modified": False,
        "reason": "Separate panels remove overlapping labels in the original frozen scatterplot."
    }
    (out / "plot_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    verify_latest(source)
    print(json.dumps({"figure": output.relative_to(ROOT).as_posix(), "run_id": manifest["run_id"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
