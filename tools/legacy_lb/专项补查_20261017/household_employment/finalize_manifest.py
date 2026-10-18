"""Validate saved source formats and write aggregate-only reference tables."""
import csv
import hashlib
import json
from pathlib import Path
from collect_household_employment import BASE, JOBS

root=BASE.parents[1]
entries=json.loads((BASE/"sources_household_employment.json").read_text(encoding="utf-8"))
by_id={e["id"]:e for e in entries}
for job in JOBS:
    if job["id"] not in by_id:
        by_id[job["id"]]=job
for entry in by_id.values():
    p=root/entry["file"]
    if not p.exists():
        entry["status"]="failed"
        continue
    data=p.read_bytes()
    entry.update(bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
    if b"<title>Client Challenge</title>" in data[:2000]:
        entry.update(status="blocked_response",error="Client Challenge HTML, not the requested source")
    elif p.suffix==".zip" and not data.startswith(b"PK"):
        entry.update(status="blocked_response",error="Response is not ZIP")
    elif p.suffix==".pdf" and not data.startswith(b"%PDF"):
        entry.update(status="blocked_response",error="Response is not PDF")
    else:
        entry["status"]="saved"
    if entry["id"]=="ENERGY_INEQUALITY_SOURCEDATA":
        entry["download_method"]="Chrome公开下载；保存的是出版社ZIP原字节"
        entry["limitations"]+="；发现附件含家庭级行后，核实CFPS现行AI规定；后续云端使用限群体汇总，原附件不得继续由云端AI读取"
(BASE/"sources_household_employment.json").write_text(json.dumps(list(by_id.values()),ensure_ascii=False,indent=2),encoding="utf-8")
rows=[
("Extremely poor",2032,2040,2400,1180,1200,1440),
("Poor",2520,2400,3000,1200,1392,1800),
("Middle",2460,2640,2880,1380,1800,2000),
("Middle high",2483,2640,2900,1560,1800,2160),
("High",2400,2400,2760,1680,1800,2160),
("Rich",2400,2280,2480,1800,1960,2094)]
out=[]
for group,*values in rows:
    for residence,offset in (("Urban",0),("Rural",3)):
        for i,year in enumerate((2013,2015,2017)):
            out.append((year,residence,group,values[offset+i],"ENERGY_INEQUALITY_SI","Supplementary Table 2; Note 1"))
with (BASE/"data"/"household_energy_median_si_table2.csv").open("w",encoding="utf-8-sig",newline="") as f:
    writer=csv.writer(f)
    writer.writerow(["year","residence","author_income_group","median_annual_household_energy_bill_RMB","source_id","source_locator"])
    writer.writerows(out)
summary=list(csv.DictReader((BASE/"data"/"household_energy_by_author_group_unweighted.csv").open(encoding="utf-8-sig")))
lookup={(int(r["year"]),r["residence"],r["author_income_group"]):float(r["median_energy_cost_RMB"]) for r in summary}
mismatches=[r for r in out if lookup[r[:3]]!=r[3]]
print("SI Table 2 cross-check:",len(out),"values;",len(mismatches),"mismatches")
lines=["# 本专项独立来源清单","","2026-10-17核验。统计期与发布日期分开。blocked_response文件仅为下载失败证据，不计为有效原件。",""]
for e in by_id.values():
    lines.extend([f"## {e['id']}",f"- 标题：{e['title']}",f"- 机构：{e['agency']}",
                  f"- 发布日期：{e['publication_date']}",f"- 统计期：{e['statistical_period']}",
                  f"- 地域：{e['geography']}；单位：{e['unit']}",f"- URL：{e['url']}",
                  f"- 文件：{e['file']}；状态：{e['status']}",
                  f"- 字节：{e.get('bytes')}；SHA256：{e.get('sha256')}",
                  f"- 用途：{e['use']}",f"- 限制：{e['limitations']}",""])
(BASE/"01_来源清单.md").write_text("\n".join(lines),encoding="utf-8")
files=[]
for p in sorted((BASE/"data").glob("*.csv")):
    files.append(dict(file=str(p.relative_to(BASE)),bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
(BASE/"derived_files_manifest.json").write_text(json.dumps(files,ensure_ascii=False,indent=2),encoding="utf-8")
