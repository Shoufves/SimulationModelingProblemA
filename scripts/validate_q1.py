"""Run real engineering gates, independent Q1 reproduction and CLI failure probes."""
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from energy_model.q1 import read_json,sha,write_json


def main():
    records=[]
    # These commands intentionally rewrite their shared "latest" reports. Keep
    # historical baseline files byte-for-byte, embedding this run in Q1 evidence.
    latest_paths=["outputs/validation/tests.json","outputs/validation/workspace_audit.json",
                  "outputs/workflow/status.json","outputs/workflow/status.md","outputs/workflow/next_prompt.md"]
    previous={p:(ROOT/p).read_bytes() if (ROOT/p).exists() else None for p in latest_paths}
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
    tests=execute(["run.py","test"])
    audit=execute(["run.py","audit"])
    keys=execute(["scripts/scan_google_keys.py"])
    admission=execute(["scripts/workflow_status.py","--check-formal-inputs"])
    author=execute(["run.py","q1","--output-dir","outputs/q1/p1_mmj"])
    reproduction=execute(["run.py","q1","--output-dir","outputs/q1/review_mmj_validation"])
    outputs={}
    for name in ("p1_mmj","review_mmj_validation"):
        path=ROOT/"outputs/q1"/name/"run_manifest.json"
        outputs[name]=read_json(path) if path.is_file() else None
    a,b=outputs.values()
    same=bool(a and b and a["outputs"]==b["outputs"])
    # Fresh failure directories cannot accidentally retain a prior success manifest.
    fixture=ROOT/"tmp"/("q1-validation-"+uuid.uuid4().hex)
    fixture.mkdir(parents=True)
    contract=read_json(ROOT/"workflow/q1_inputs.json")
    contract["inputs"][0]["sha256"]="0"*64
    write_json(fixture/"tampered.json",contract)
    bad_output="outputs/q1/negative_"+fixture.name
    tamper=execute(["run.py","q1","--inputs",(fixture/"tampered.json").relative_to(ROOT).as_posix(),
                    "--output-dir",bad_output],1)
    missing=execute(["run.py","q1","--inputs",(fixture/"missing.json").relative_to(ROOT).as_posix(),
                     "--output-dir",bad_output],1)
    no_success=not (ROOT/bad_output).exists()
    (fixture/"tampered.json").unlink();fixture.rmdir()
    current_tests=read_json(ROOT/"outputs/validation/tests.json")
    current_audit=read_json(ROOT/"outputs/validation/workspace_audit.json")
    formal_inputs=read_json(ROOT/"outputs/workflow/status.json")["formal_input_check"]
    for p,data in previous.items():
        if data is None:
            (ROOT/p).unlink(missing_ok=True)
        else:
            (ROOT/p).write_bytes(data)
    diff=subprocess.run(["git","diff","--check"],cwd=ROOT,capture_output=True,
                        encoding="utf-8",errors="replace")
    def git(*args):
        return subprocess.check_output(["git",*args],cwd=ROOT,text=True,encoding="utf-8").strip()
    code_paths=["run.py","scripts/run_q1_assessment.py","scripts/prepare_q1_inputs.py",
        "scripts/validate_q1.py","src/energy_model/q1.py","tests/test_q1.py",
        "scripts/audit_workspace.py","scripts/scan_google_keys.py","scripts/build_workspace_catalog.py"]
    result=dict(scope="Engineering gate execution; scientific scope/peer approval recorded separately",
        passed=all(r["passed"] for r in records) and same and no_success and diff.returncode==0,
        executed_on="2026-10-18",python=sys.version,executable=sys.executable,
        code_commit_sha=git("rev-parse","HEAD"),dirty_worktree=bool(git("status","--porcelain")),
        code_hashes={p:sha(ROOT/p) for p in code_paths},
        input_manifest_sha256=sha(ROOT/"workflow/q1_inputs.json"),
        tests=current_tests,
        workspace_audit=current_audit,
        original_nine_subset_check=formal_inputs,
        latest_reports_preserved=list(previous),
        key_scan=json.loads(keys["stdout"]) if keys["passed"] else None,
        source_review=read_json(ROOT/"data/catalog/q1_evidence_review.json"),
        independent_reproduction=dict(passed=same,compared="All 10 scientific artifacts, including PNGs; runtime manifests separately retained",
            author_outputs=a["outputs"] if a else None,review_outputs=b["outputs"] if b else None),
        negative_cli_probes=dict(tampered_input_rejected=tamper["passed"],
            missing_manifest_rejected=missing["passed"],no_output_created=no_success),
        diff_check=dict(passed=diff.returncode==0,stdout=diff.stdout,stderr=diff.stderr),
        executions=records,
        scientific_status="Four scoped research sections implemented; 16 explicit gaps; A7 pending",
        limits=["2021-2024 price version remains quarantined",
                "2024 physical energy-carbon closure and complete operational state blocked",
                "new extractions need peer/shared-input confirmation",
                "restricted files: metadata only, no content hashes checked",
                "six external B/C historical duplicates excluded, no existence/content claim",
                "full test execution may require leaving Windows desktop sandbox due legacy tempfile ACLs",
                "not national initialization, calibration or forecast; no merge authorization"])
    out=ROOT/"outputs/validation/q1_mmj_validation.json"
    write_json(out,result)
    print(json.dumps(dict(passed=result["passed"],tests=result["tests"]["tests"],
        audit_checks=len(result["workspace_audit"]["checks"]),reproduction=same,
        no_false_success=no_success,evidence=out.relative_to(ROOT).as_posix()),ensure_ascii=False))
    return 0 if result["passed"] else 1


if __name__=="__main__":
    raise SystemExit(main())
