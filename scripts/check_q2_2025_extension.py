"""Post-freeze 2025 crosscheck, never a calibration or selection target."""
import csv
import hashlib
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]


def main():
    from run_q2_national import verify_latest
    folder=ROOT/"outputs/q2/p2_lb_national"
    manifest=verify_latest(folder)
    with (folder/"baseline_path.csv").open(encoding="utf-8") as f:
        model=next(r for r in csv.DictReader(f) if r["year"]=="2025")
    review=json.loads((ROOT/"data/catalog/q2_national_2025_check.json").read_text(encoding="utf-8"))
    for s in review["sources"]:
        if hashlib.sha256((ROOT/s["path"]).read_bytes()).hexdigest()!=s["sha256"]:
            raise ValueError("Changed reviewed 2025 original")
    text=re.sub(r"<[^>]+>"," ",(ROOT/review["sources"][1]["path"]).read_text(encoding="utf-8"))
    if not re.search(r"全年能源消费总量\s*61\.7\s*亿吨标准煤",text):
        raise ValueError("2025 energy original passage differs")
    results=[]
    for r in review["observations"]:
        observed=r["raw_value"]*r["multiplier"]
        predicted=float(model[r["metric"]])
        results.append(dict(**r,observed=observed,model=predicted,relative_error=predicted/observed-1))
    out=ROOT/"outputs/q2_review/p2_lb_national/extension_2025.json"
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(dict(identity=review["identity"],run_id=manifest["run_id"],
        used_for_fitting=False,limits=review["limits"],observations=results,
        review_sha256=hashlib.sha256((ROOT/"data/catalog/q2_national_2025_check.json").read_bytes()).hexdigest()),ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(results,ensure_ascii=False))


if __name__=="__main__":main()
