"""Portable, transparent JSON representation of verified parsed model inputs.

This mode reruns the unchanged model from reviewed extracted inputs. It never
claims to have rechecked omitted original PDFs in the compact package.
AI-assisted: OpenAI Codex/GPT-6, 2026-10-20; public release date unavailable.
"""
from pathlib import Path
from copy import deepcopy
import importlib
import hashlib
import json

ROOT=Path(__file__).resolve().parents[1]
ALLOWED={
    "energy_model.q2_support_investment.SupportOffer",
    "energy_model.q2_boundary.InheritedOperatingBoundary",
    "energy_model.q2_revenue.AnnualRevenuePolicy",
    "energy_model.q2_support_investment.NewProjectSupport",
    "energy_model.q2_subsidies.SubsidyFund",
    "energy_model.q2_project_costs.GenerationCosts"}
READERS=("verify_policy","verified_costs","verify_history","scope_inputs","policy_inputs","cost_inputs")


def encode(x):
    if x is None or type(x) in (str,int,float,bool):return x
    if isinstance(x,dict):return {"type":"dict","items":[[encode(k),encode(v)] for k,v in x.items()]}
    if type(x) in (list,tuple,set):return {"type":type(x).__name__,"items":[encode(v) for v in x]}
    name=type(x).__module__+"."+type(x).__name__
    if name not in ALLOWED:raise ValueError("Unapproved snapshot type: "+name)
    return {"type":"object","class":name,"state":encode(vars(x))}


def decode(x):
    if not isinstance(x,dict):return x
    kind=x["type"]
    if kind=="dict":return {decode(k):decode(v) for k,v in x["items"]}
    if kind in ("list","tuple","set"):
        return {"list":list,"tuple":tuple,"set":set}[kind](decode(v) for v in x["items"])
    if kind!="object" or x["class"] not in ALLOWED:raise ValueError("Unapproved object type")
    module,name=x["class"].rsplit(".",1);cls=getattr(importlib.import_module(module),name)
    obj=cls.__new__(cls);obj.__dict__.update(decode(x["state"]));return obj


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(p):return json.loads(Path(p).read_text("utf-8"))
def save(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,separators=(",",":"),allow_nan=False)+"\n","utf-8")


def export(run):
    import q2_current_factory as factory
    from run_q2_national import preflight
    source_hashes=load(run/"source_snapshot.json")
    mismatches=[p for p,h in source_hashes.items() if sha(ROOT/p)!=h]
    if mismatches:raise ValueError(mismatches)
    data,design,_=preflight();config=load(run/"design.json")
    records={};original={n:getattr(factory,n) for n in READERS}
    for mode,authority in [("net58",25),("net58",5),("net58",100),("net55",25)]:
        src=ROOT/config["historical_runs"][mode]
        experiment=load(src/"design.json");theta=load(src/"training_selection.json")["scenarios"][str(authority)]["parameters"]
        captured={}
        for n,fn in original.items():
            def wrapper(*a,_fn=fn,_n=n,**k):
                if _n in captured:raise ValueError("Unexpected repeated reader")
                value=_fn(*a,**k)
                captured[_n]=deepcopy(value)
                return value
            setattr(factory,n,wrapper)
        try:factory.build(data,design,experiment,theta,authority)
        finally:
            for n,fn in original.items():setattr(factory,n,fn)
        records[f"{mode}/{authority}"]=encode(dict(data=data,design=design,config=experiment,parameters=theta,readers=captured))
    dest=ROOT/"data/processed/q2_delivery";dest.mkdir(parents=True,exist_ok=True)
    save(dest/"parsed_inputs.json",records)
    keep={"sensitivity","opening_uncertainty","uncertain_authority","thermal_reference"}
    scenarios=[s for s in config["scenarios"] if s["name"]=="S0" or s.get("kind") in keep]
    save(dest/"q2_design.json",dict(scenarios=scenarios,scope="Question 2 only",start_year=2025,end_year=2060))
    code_paths=set(source_hashes)
    code_hashes={p:sha(ROOT/p) for p in sorted(code_paths) if p.endswith(".py")}
    for p in ("scripts/q2_delivery_snapshot.py","scripts/run_q2_portable.py"):
        code_hashes[p]=sha(ROOT/p)
    save(dest/"manifest.json",dict(mode="verified_parsed_inputs_snapshot_not_original_pdf_revalidation",
        source_run=run.relative_to(ROOT).as_posix(),original_source_sha256=source_hashes,
        source_results_sha256=sha(run/"results.json"),source_verification_at_export=True,
        inputs_sha256=sha(dest/"parsed_inputs.json"),design_sha256=sha(dest/"q2_design.json"),code_sha256=code_hashes,
        scope="All actual model logic unchanged; only pure evidence readers supplied from exported reviewed returns. No future paths in inputs.",
        raw_provenance="Full originals and original preflight remain in the complete research archive; compact archive carries extracted datasets and selected source evidence."))
    print(dest)


def build_snapshot(record,authority,options):
    import q2_current_factory as factory
    original={n:getattr(factory,n) for n in READERS}
    used=[]
    for n in READERS:
        def reader(*a,_n=n,**k):
            used.append(_n)
            if _n=="scope_inputs" and a[2]!=record["parameters"]:raise ValueError("Parameters differ from extracted inputs")
            if _n=="policy_inputs" and k.get("authority_multiple")!=authority:raise ValueError("Authority mismatch")
            return deepcopy(record["readers"][_n])
        setattr(factory,n,reader)
    try:
        model,assumptions,sources=factory.build(record["data"],record["design"],record["config"],record["parameters"],authority,opening_variant=options)
        if sorted(used)!=sorted(READERS):raise ValueError("Factory evidence reader contract changed")
        return model,assumptions,sources
    finally:
        for n,fn in original.items():setattr(factory,n,fn)
