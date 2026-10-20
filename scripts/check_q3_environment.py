"""Check the actual interpreter and numerical backend before Q3 experiments."""
import argparse
import importlib
import importlib.metadata
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]


def inspect_environment():
    from packaging.requirements import Requirement
    checks = [{"check": "python_at_least_3_11", "passed": sys.version_info >= (3, 11)}]
    packages = {}
    for filename in ("requirements-q2.txt", "requirements-q1.txt", "requirements-data.txt"):
        for line in (ROOT / filename).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            requirement = Requirement(line)
            try:
                version = importlib.metadata.version(requirement.name)
                passed = version in requirement.specifier
                packages[requirement.name] = version
            except importlib.metadata.PackageNotFoundError:
                version, passed = None, False
            checks.append(dict(check=filename + ":" + requirement.name,
                               expected=str(requirement.specifier), actual=version, passed=passed))
    try:
        from scipy.optimize import linprog
        from mesa import Model
        result = linprog([-1.0], bounds=[(0, 1)], method="highs")
        checks.append(dict(check="highs_actual_solve", passed=bool(result.success and abs(result.x[0]-1) < 1e-9)))
        checks.append(dict(check="mesa_actual_initialization", passed=Model(seed=12).running))
        for module in ("reportlab.pdfgen.canvas", "matplotlib", "openpyxl", "pandas", "pdfplumber"):
            importlib.import_module(module)
            checks.append(dict(check="import:" + module, passed=True))
    except Exception as exc:
        checks.append(dict(check="runtime_import_or_solver", passed=False, error=str(exc)))
    pip = subprocess.run([sys.executable, "-m", "pip", "check"], capture_output=True, text=True)
    checks.append(dict(check="pip_check", passed=pip.returncode == 0, detail=(pip.stdout+pip.stderr).strip()))
    return dict(checked_at_utc=datetime.now(timezone.utc).isoformat(), executable=sys.executable,
                python=sys.version, platform=platform.platform(), packages=packages,
                free_disk_bytes=shutil.disk_usage(ROOT).free, checks=checks,
                passed=all(c["passed"] for c in checks),
                scope="Environment readiness only; not Q3 scientific or team acceptance")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="outputs/validation/p3_mmj/environment.json")
    args = parser.parse_args()
    output = (ROOT / args.output).resolve()
    if not output.is_relative_to(ROOT / "outputs/validation"):
        parser.error("Environment evidence must be inside outputs/validation")
    report = inspect_environment()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
