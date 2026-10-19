"""Run fresh Q2 engineering checks and Q1 regression; never grant scientific acceptance."""
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from run_q2 import sha,load,dump,verify_latest,CODE


def main():
    evidence = ROOT/"outputs/q2_review/p2_lb"
    evidence.mkdir(parents=True,exist_ok=True)
    report = dict(passed=False,status="running",q2_scientific_complete=False,checks=[],commands=[])
    dump(evidence/"verification.json",report)
    start = time.perf_counter()
    # Existing Q1/global receipts remain historical; copy fresh evidence here then restore only our own writes.
    preserve = [ROOT/"outputs/validation/tests.json",ROOT/"outputs/validation/workspace_audit.json"]
    preserve += [ROOT/"outputs/workflow"/name for name in ("status.json","status.md","next_prompt.md")]
    before = {p:p.read_bytes() for p in preserve if p.exists()}
    protected = ["data/sources.json","data/evidence_reviews.json","workflow/model_inputs.json"]
    protected += [p.relative_to(ROOT).as_posix() for p in (ROOT/"只读工作区").iterdir() if p.is_file()]
    contract_before = {p:sha(ROOT/p) for p in protected}
    q1folder = ROOT/"outputs/q1/p1_yx"
    q1_before = {p.relative_to(q1folder).as_posix():sha(p) for p in q1folder.rglob("*") if p.is_file()}
    def check(name,passed,detail):
        report["checks"].append(dict(name=name,passed=bool(passed),detail=detail))
        if not passed:raise ValueError(name+": "+str(detail))
    def command(label,args,expected=0):
        r = subprocess.run([sys.executable,"-B","-X","utf8",*args],cwd=ROOT,capture_output=True,text=True,encoding="utf-8")
        (evidence/(label+".log")).write_text(r.stdout+r.stderr,encoding="utf-8")
        report["commands"].append(dict(label=label,args=args,returncode=r.returncode,expected=expected))
        check(label,r.returncode==expected,(r.stdout+r.stderr)[-1200:])
        return r
    try:
        command("all_tests",["run.py","test"])
        fresh_tests = load(ROOT/"outputs/validation/tests.json")
        dump(evidence/"tests.json",fresh_tests)
        check("q2_tests_not_skipped",fresh_tests["skipped"] == 0,fresh_tests)
        command("audit",["run.py","audit"])
        dump(evidence/"workspace_audit.json",load(ROOT/"outputs/validation/workspace_audit.json"))
        command("key_scan",["scripts/scan_google_keys.py"])
        command("nine_original_subsets",["scripts/workflow_status.py","--check-formal-inputs"])
        command("candidate_review",["scripts/review_q2_candidates.py"])
        command("q1_regression",["run.py","q1","--output-dir","outputs/q1/q2_lb_regression"])
        comparison = ROOT/"outputs/q1/q2_lb_regression"
        q1_manifest = load(q1folder/"run_manifest.json")
        names = list(q1_manifest["outputs"])
        check("q1_scientific_outputs_unchanged",len(names)==18 and all(sha(q1folder/p)==sha(comparison/p) for p in names),names)
        command("national_expected_block",["run.py","q2","--config","workflow/q2_inputs.json","--output-dir","outputs/q2/p2_lb"],2)
        latest = load(ROOT/"outputs/q2/p2_lb.latest-attempt.json")
        check("national_status_honest",latest["status"]=="blocked_national_inputs" and not latest["output_valid_for_this_attempt"],latest)
        command("engineering",["run.py","q2","--config","examples/q2/config.json","--output-dir","outputs/q2/p2_lb_engineering"])
        engineering = ROOT/"outputs/q2/p2_lb_engineering"
        m = verify_latest(engineering)
        command("engineering_reproduction",["run.py","q2","--config","examples/q2/config.json","--output-dir","outputs/q2/p2_lb_reproduction"])
        replica = ROOT/"outputs/q2/p2_lb_reproduction"
        other = verify_latest(replica)
        check("engineering_outputs_identical",m["outputs"] == other["outputs"],list(m["outputs"]))
        check("engineering_not_national_acceptance",not m["q2_scientific_complete"] and m["status"]=="success_engineering",m["status"])
        bad_path = ROOT/"tmp/q2-bad-config.json"
        bad = load(ROOT/"examples/q2/config.json")
        bad["inputs"][0]["sha256"] = "0"*64
        dump(bad_path,bad)
        old_digest = sha(replica/"run_manifest.json")
        command("changed_input_expected_failure",["run.py","q2","--config","tmp/q2-bad-config.json","--output-dir","outputs/q2/p2_lb_reproduction"],2)
        check("old_success_preserved",sha(replica/"run_manifest.json")==old_digest,old_digest)
        rejected = False
        try:verify_latest(replica)
        except ValueError:rejected = True
        check("stale_success_rejected",rejected,"Latest failure invalidates preserved success")
        command("missing_input_expected_failure",["run.py","q2","--config","tmp/q2-config-does-not-exist.json","--output-dir","outputs/q2/p2_lb_reproduction"],2)
        check("protected_contracts_unchanged",contract_before=={p:sha(ROOT/p) for p in protected},contract_before)
        check("original_q1_folder_untouched",q1_before=={p.relative_to(q1folder).as_posix():sha(p) for p in q1folder.rglob("*") if p.is_file()},len(q1_before))
        report.update(passed=True,status="engineering_passed_national_blocked")
    except Exception as exc:
        report["status"] = "verification_failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        for p,content in before.items():p.write_bytes(content)
        report["seconds"] = time.perf_counter()-start
        report["code_hashes"] = {p:sha(ROOT/p) for p in CODE+["tests/test_q2.py","tests/test_q2_national.py","src/energy_model/q2_national.py","src/energy_model/q2_finance.py","scripts/review_q2_candidates.py","scripts/review_q2_delivery.py"]}
        report["dependencies"] = {p:importlib.metadata.version(p) for p in ("mesa","scipy","numpy","pandas","matplotlib","reportlab")}
        report["evidence_hashes"] = {p.name:sha(p) for p in sorted(evidence.iterdir()) if p.is_file() and p.name != "verification.json"}
        dump(evidence/"verification.json",report)
    print(json.dumps(dict(passed=report["passed"],status=report["status"],checks=len(report["checks"]),error=report.get("error"),
                         q2_scientific_complete=False),ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":raise SystemExit(main())
