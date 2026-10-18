"""Run real engineering gates, independent Q1 reproduction and CLI failure probes."""
import argparse
import json
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from energy_model.q1 import inside,read_json,sha,write_json

LATEST_PATHS=["outputs/validation/tests.json","outputs/validation/workspace_audit.json",
              "outputs/workflow/status.json","outputs/workflow/status.md","outputs/workflow/next_prompt.md"]
ARTIFACTS={"history.csv","indicators.csv","energy_roles.csv","model_handoff.csv",
           "gaps_and_conflicts.csv","regional.csv","static_balance.json","report.md",
           "overview.png","regional.png"}
RUN_CODE_PATHS=["run.py","scripts/run_q1_assessment.py","scripts/prepare_q1_inputs.py",
                "src/energy_model/q1.py","requirements-q1.txt"]


@contextmanager
def preserve_reports(root, paths):
    """Restore historical reports even if a child launch or JSON read raises."""
    previous={p:(root/p).read_bytes() if (root/p).exists() else None for p in paths}
    try:
        yield
    finally:
        for p,data in previous.items():
            if data is None:
                (root/p).unlink(missing_ok=True)
            else:
                (root/p).parent.mkdir(parents=True,exist_ok=True)
                (root/p).write_bytes(data)


def expected_run_identity(root):
    contract=read_json(root/"workflow/q1_inputs.json")
    return dict(schema_version=1,candidate="p1/mmj",success=True,
        base_sha=contract["base_sha"],
        code_commit_sha=subprocess.check_output(
            ["git","rev-parse","HEAD"],cwd=root,text=True,encoding="utf-8").strip(),
        input_manifest=dict(path="workflow/q1_inputs.json",sha256=sha(root/"workflow/q1_inputs.json")),
        input_hashes={r["path"]:sha(inside(root,r["path"])) for r in contract["inputs"]},
        source_hashes={k:r["sha256"] for k,r in contract["sources"].items()},
        evidence_review=contract["evidence_review"],
        code_hashes={p:sha(root/p) for p in RUN_CODE_PATHS},
        configuration=contract["assumptions"])


def inspect_run(root, directory, execution_passed, expected):
    """Require a successful current command and verify the bytes it published."""
    detail=dict(passed=False,errors=[],actual_outputs={},manifest=None)
    if not execution_passed:
        detail["errors"].append("Q1 command did not succeed in this validation run")
    try:
        folder=inside(root,directory)
        manifest=read_json(folder/"run_manifest.json")
        if not isinstance(manifest,dict):
            raise ValueError("Run manifest must be a JSON object")
        detail["manifest"]=manifest
        for key,value in expected.items():
            if manifest.get(key)!=value:
                detail["errors"].append("Run identity mismatch: "+key)
        if set(manifest["outputs"])!=ARTIFACTS:
            detail["errors"].append("Expected exactly the 10 scientific artifacts")
        else:
            for name in sorted(ARTIFACTS):
                actual=sha(inside(folder,name))
                detail["actual_outputs"][name]=actual
                if actual!=manifest["outputs"][name]:
                    detail["errors"].append("Artifact fingerprint mismatch: "+name)
    except (OSError,ValueError,KeyError,TypeError) as exc:
        detail["errors"].append(type(exc).__name__+": "+str(exc))
    detail["passed"]=not detail["errors"]
    return detail


def run_checks(execute):
    with preserve_reports(ROOT,LATEST_PATHS):
        execute(["run.py","test"])
        execute(["run.py","audit"])
        keys=execute(["scripts/scan_google_keys.py"])
        execute(["scripts/workflow_status.py","--check-formal-inputs"])
        expected=expected_run_identity(ROOT)
        author=execute(["run.py","q1","--output-dir","outputs/q1/p1_mmj"])
        reproduction=execute(["run.py","q1","--output-dir","outputs/q1/review_mmj_validation"])
        a=inspect_run(ROOT,"outputs/q1/p1_mmj",author["passed"],expected)
        b=inspect_run(ROOT,"outputs/q1/review_mmj_validation",reproduction["passed"],expected)
        same=bool(a["passed"] and b["passed"] and a["actual_outputs"]==b["actual_outputs"])
        # Fresh failure directories cannot retain a prior success manifest.
        fixture=ROOT/"tmp"/("q1-validation-"+uuid.uuid4().hex)
        fixture.mkdir(parents=True)
        try:
            contract=read_json(ROOT/"workflow/q1_inputs.json")
            contract["inputs"][0]["sha256"]="0"*64
            write_json(fixture/"tampered.json",contract)
            bad_output="outputs/q1/negative_"+fixture.name
            tamper=execute(["run.py","q1","--inputs",(fixture/"tampered.json").relative_to(ROOT).as_posix(),
                            "--output-dir",bad_output],1)
            missing=execute(["run.py","q1","--inputs",(fixture/"missing.json").relative_to(ROOT).as_posix(),
                             "--output-dir",bad_output],1)
            no_success=not (ROOT/bad_output).exists()
        finally:
            (fixture/"tampered.json").unlink(missing_ok=True)
            fixture.rmdir()
        current_tests=read_json(ROOT/"outputs/validation/tests.json")
        current_audit=read_json(ROOT/"outputs/validation/workspace_audit.json")
        formal_inputs=read_json(ROOT/"outputs/workflow/status.json")["formal_input_check"]
        return dict(
            checks_passed=same and no_success and current_tests["passed"] and
                          current_audit["passed"] and formal_inputs["passed"],
            tests=current_tests,workspace_audit=current_audit,
            original_nine_subset_check=formal_inputs,
            key_scan=json.loads(keys["stdout"]) if keys["passed"] else None,
            independent_reproduction=dict(passed=same,
                compared="Current successful runs; all 10 actual artifacts and current code/input/configuration identities",
                author_outputs=a["actual_outputs"],review_outputs=b["actual_outputs"],
                runs={"p1_mmj":a,"review_mmj_validation":b}),
            negative_cli_probes=dict(tampered_input_rejected=tamper["passed"],
                missing_manifest_rejected=missing["passed"],no_output_created=no_success))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence",default="outputs/validation/q1_mmj_validation.json")
    args=parser.parse_args()
    out=inside(ROOT,args.evidence)
    if not out.is_relative_to((ROOT/"outputs/validation").resolve()) or out.suffix!=".json":
        parser.error("--evidence must be a JSON file under outputs/validation/")
    if out in {(ROOT/p).resolve() for p in LATEST_PATHS}:
        parser.error("--evidence cannot replace a protected historical latest report")
    records=[]
    def execute(arguments,expected=0):
        start=time.perf_counter()
        proc=subprocess.run([sys.executable,"-B","-X","utf8",*arguments],
                            cwd=ROOT,capture_output=True,encoding="utf-8",errors="replace")
        record=dict(command=["python","-B","-X","utf8",*arguments],
            returncode=proc.returncode,expected_returncode=expected,
            passed=proc.returncode==expected,seconds=round(time.perf_counter()-start,3),
            stdout=proc.stdout,stderr=proc.stderr)
        records.append(record)
        print(f"{'PASS' if record['passed'] else 'FAIL'}: {' '.join(arguments)}",flush=True)
        return record
    try:
        checks=run_checks(execute)
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as exc:
        checks=dict(checks_passed=False,validation_error=type(exc).__name__+": "+str(exc))
    diff=subprocess.run(["git","diff","--check"],cwd=ROOT,capture_output=True,
                        encoding="utf-8",errors="replace")
    def git(*args):
        return subprocess.check_output(["git",*args],cwd=ROOT,text=True,encoding="utf-8").strip()
    code_paths=["run.py","scripts/run_q1_assessment.py","scripts/prepare_q1_inputs.py",
        "scripts/validate_q1.py","src/energy_model/q1.py","tests/test_q1.py",
        "scripts/audit_workspace.py","scripts/scan_google_keys.py","scripts/build_workspace_catalog.py",
        "requirements-q1.txt"]
    result=dict(scope="Engineering gate execution; scientific scope/peer approval recorded separately",
        passed=all(r["passed"] for r in records) and checks["checks_passed"] and diff.returncode==0,
        executed_on=datetime.now().astimezone().isoformat(),python=sys.version,executable=sys.executable,
        code_commit_sha=git("rev-parse","HEAD"),dirty_worktree=bool(git("status","--porcelain")),
        code_hashes={p:sha(ROOT/p) for p in code_paths},
        input_manifest_sha256=sha(ROOT/"workflow/q1_inputs.json"),
        **checks,
        latest_reports_preserved=LATEST_PATHS,
        source_review=read_json(ROOT/"data/catalog/q1_evidence_review.json"),
        diff_check=dict(passed=diff.returncode==0,stdout=diff.stdout,stderr=diff.stderr),
        executions=records,
        scientific_status="Q1 scientific coverage partial; explicit gaps remain; Draft, A7 pending",
        limits=["2021-2024 price version remains quarantined",
                "2024 physical energy-carbon closure and complete operational state blocked",
                "new extractions need peer/shared-input confirmation",
                "restricted files: metadata only, no content hashes checked",
                "six external B/C historical duplicates excluded, no existence/content claim",
                "full test execution may require leaving Windows desktop sandbox due legacy tempfile ACLs",
                "not national initialization, calibration or forecast; no merge authorization"])
    write_json(out,result)
    print(json.dumps(dict(passed=result["passed"],tests=result.get("tests",{}).get("tests"),
        audit_checks=len(result.get("workspace_audit",{}).get("checks",[])),
        reproduction=result.get("independent_reproduction",{}).get("passed",False),
        no_false_success=result.get("negative_cli_probes",{}).get("no_output_created",False),
        error=result.get("validation_error"),evidence=out.relative_to(ROOT).as_posix()),ensure_ascii=False))
    return 0 if result["passed"] else 1


if __name__=="__main__":
    raise SystemExit(main())
