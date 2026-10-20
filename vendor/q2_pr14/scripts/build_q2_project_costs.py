"""Reconstruct fixed/variable O&M from two official utilisation cases.

No publisher workbook is rewritten. These are 2025 technical-reference costs
in 2018 USD, NOT annual observations of China's existing generating fleet.
"""
from pathlib import Path
import hashlib
import json
import posixpath
from xml.etree import ElementTree as ET
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "data/raw/q2_project_costs/iea_projected_costs_2020_data.xlsx"
HASH = "74782355333e065462b1cd3b2468643bebebad0db0ae42d2c8996926aaa3881a"
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
PAIRS = {
    "gas": ("3.11.a.b", "3.20a.b", 24, "N", "CCGT", "3.2.a.b", "F24"),
    "coal": ("3.12", "3.21", 22, "N", "Ultra-supercritical", "3.3", "F22"),
    "nuclear": ("3.13.a.b1.b2", "3.22.a.b1.b2", 13, "M", "LWR", "3.4.a.b", "E13"),
}


def cells(path):
    with ZipFile(path) as z:
        strings = ["".join(t.text or "" for t in s.findall(".//s:t", NS))
                   for s in ET.fromstring(z.read("xl/sharedStrings.xml"))]
        targets = {r.attrib["Id"]: posixpath.normpath("xl/"+r.attrib["Target"])
                   for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
        result = {}
        for sheet in ET.fromstring(z.read("xl/workbook.xml")).findall("s:sheets/s:sheet", NS):
            rid = sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
            rows = {}
            for c in ET.fromstring(z.read(targets[rid])).findall("s:sheetData/s:row/s:c", NS):
                v = c.find("s:v", NS)
                if v is not None and v.text is not None:
                    rows[c.attrib["r"]] = strings[int(v.text)] if c.attrib.get("t") == "s" else float(v.text)
            result[sheet.attrib["name"]] = rows
        return result


def extract():
    if hashlib.sha256((ROOT/SOURCE).read_bytes()).hexdigest() != HASH:
        raise ValueError("Cost source changed: review the original before use")
    book = cells(ROOT/SOURCE)
    result = {}
    for tech, (high, low, row, col, technology, capital_sheet, capital_cell) in PAIRS.items():
        for sheet, cf in ((high, 85), (low, 50)):
            c = book[sheet]
            if f"{cf}% capacity factor" not in c["B3"] or c[f"B{row}"] != "China" or c[f"C{row}"] != technology:
                raise ValueError("Cost table country/technology/utilisation changed")
            if c[f"D{row}"] != book[high][f"D{row}"] or c[f"E{row}"] != book[high][f"E{row}"]:
                raise ValueError("Cost cases are not the same net-capacity plant")
        a, b = book[high][f"{col}{row}"], book[low][f"{col}{row}"]
        fixed = (b-a)/(1/(8760*.50)-1/(8760*.85))
        variable = a-fixed/(8760*.85)
        if fixed < 0 or variable < 0:
            raise ValueError("Invalid fixed/variable reconstruction")
        result[tech] = dict(fixed_usd_2018_per_net_mw_year=fixed,
            variable_om_usd_2018_per_net_mwh=variable,
            nuclear_fuel_usd_2018_per_net_mwh=book[high][f"L{row}"] if tech == "nuclear" else 0,
            overnight_usd_2018_per_net_kw=book[capital_sheet][capital_cell],
            source_cells={f"{high}!{col}{row}": a, f"{low}!{col}{row}": b,
                          f"{capital_sheet}!{capital_cell}": book[capital_sheet][capital_cell]},
            recovered_at_85=variable+fixed/(8760*.85),
            recovered_at_50=variable+fixed/(8760*.50))
    return dict(source=SOURCE, source_sha256=HASH,
        scope="China submitted hypothetical new plants commissioning 2025; net capacity and net output",
        status="derived_technical_reference_not_historical_observation",
        method="OM(cf)=variable + fixed/(8760*cf); same plant at 85% and 50% utilisation",
        parameters=result)


def main():
    p=ROOT/"data/processed/q2/project_costs/iea_fixed_variable.json"
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(extract(),ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(p.relative_to(ROOT))


if __name__ == "__main__":
    main()
