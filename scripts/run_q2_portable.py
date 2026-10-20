"""Question 2 offline re-execution from verified extracted input snapshots.

This is a new explicitly scoped adapter, not a bypass of the original runner's
raw-source checks. The compact mode verifies its own input/code hashes; complete
raw-document checks use run_q2_current_delivery.py in the full archive.
AI-assisted: OpenAI Codex/GPT-6, 2026-10-20; release date unavailable.
"""
from pathlib import Path
from datetime import datetime,timezone
import argparse
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"scripts"),str(ROOT/"src")]
from q2_delivery_snapshot import load,save,sha,decode,build_snapshot
from energy_model.q2_forward_current import activate_forward,forward_summary
from run_q2_national import targets,csv_write


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--only",nargs="*");p.add_argument("--end-year",type=int,default=2060);p.add_argument("--verify-reference",action="store_true");args=p.parse_args()
    data=ROOT/"data/processed/q2_delivery";manifest=load(data/"manifest.json")
    for rel,h in manifest["code_sha256"].items():
        if sha(ROOT/rel)!=h:raise ValueError("Code hash mismatch: "+rel)
    if sha(data/"parsed_inputs.json")!=manifest["inputs_sha256"] or sha(data/"q2_design.json")!=manifest["design_sha256"]:raise ValueError("Input snapshot mismatch")
    raw=load(data/"parsed_inputs.json");specs=load(data/"q2_design.json")["scenarios"]
    if args.only is not None:
        missing=set(args.only)-{s["name"] for s in specs}
        if missing:raise ValueError("Unknown Q2 cases: "+str(missing))
        specs=[s for s in specs if s["name"] in args.only]
    if not specs:raise ValueError("No cases selected")
    output=ROOT/"outputs/q2_portable"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ");output.mkdir(parents=True)
    print(output.relative_to(ROOT),flush=True);results=[]
    for original in specs:
        spec=dict(original);name=spec["name"];mode=spec.pop("thermal_mode","net58");authority=spec.pop("authority",25)
        opening=spec.pop("opening_variant",{})
        record=decode(raw[f"{mode}/{authority}"])
        model,assumptions,_=build_snapshot(record,authority,opening)
        activate_forward(model,record["config"],spec,end_year=args.end_year);model.run(args.end_year)
        tar,peak=targets(model.paths,model.data,model.design) if args.end_year==2060 else ([],{})
        result=dict(name=name,paths=model.paths,targets=tar,peak=peak,summary=forward_summary(model),
            evidence_mode=manifest["mode"],assumptions={**assumptions,**model.forward_assumptions})
        reference_path=ROOT/"data/processed/q2_delivery/reference_paths"/(name+".json")
        if args.verify_reference:
            ref=load(reference_path);expected=[r for r in ref["paths"] if r["year"]<=args.end_year]
            if result["paths"]!=expected:raise ValueError("Portable path differs: "+name)
            if args.end_year==2060 and (result["targets"]!=ref["targets"] or result["peak"]!=ref["peak"]):raise ValueError("Portable targets differ: "+name)
            result["reference_exact_match"]=True
        save(output/(name+".json"),result);csv_write(output/(name+"_path.csv"),model.paths)
        results.append(dict(name=name,status="success",reference_exact_match=result.get("reference_exact_match"),summary=result["summary"]))
        print(name,"success",flush=True)
    save(output/"verification.json",dict(status="passed",cases=len(results),results=results,input_manifest_sha256=sha(data/"manifest.json"),raw_originals_reverified=False))
    print("COMPLETE",len(results),flush=True)


if __name__=="__main__":main()
