"""Extract one complete EI vintage without changing existing production inputs.

Uses only the Python standard library. Read cached source values, never rewrite
or recalculate the publisher's workbook. Growth/share columns are not years.
"""
import csv
import hashlib
import json
from math import fsum, isfinite
from pathlib import Path
import posixpath
from xml.etree import ElementTree as ET
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/raw/q2_technology_scope/ei_2025_original.xlsx"
DEST = ROOT / "data/processed/q2/electricity_scope"
MD5 = "99805119256ece8c0b5b24181295b66d"
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
SHEETS = {
    "total": "Electricity Generation - TWh",
    "coal": "Coal inputs - Elec generation ",
    "gas": "Gas inputs - Elec generation",
    "oil": "Oil inputs - Elec generation ",
    "hydro_primary": "Hydro Generation - TWh",
    "nuclear": "Nuclear Generation - TWh",
    "wind": "Wind Generation - TWh",
    "solar": "Solar Generation - TWh",
    "geothermal_biomass_other_renewables": "Geo Biomass Other - TWh",
    "other_unallocated": "Other inputs - Elec generation",
}


def workbook_cells(path):
    """Read values and exact coordinates from a published XLSX ZIP."""
    with ZipFile(path) as archive:
        shared = ET.fromstring(archive.read("xl/sharedStrings.xml"))
        # Plain/rich strings: keep text runs only, excluding phonetic metadata.
        strings = ["".join(n.text or "" for n in si.findall(".//m:t", NS))
                   for si in shared.findall("m:si", NS)]
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {r.attrib["Id"]: posixpath.normpath("xl/" + r.attrib["Target"])
                   for r in rels}
        book = ET.fromstring(archive.read("xl/workbook.xml"))
        result = {}
        for sheet in book.findall("m:sheets/m:sheet", NS):
            name = sheet.attrib["name"]
            if name not in {*SHEETS.values(), "Definitions", "Elec generation by fuel"}:
                continue
            rid = sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
            cells = {}
            xml = ET.fromstring(archive.read(targets[rid]))
            for cell in xml.findall("m:sheetData/m:row/m:c", NS):
                value = cell.find("m:v", NS)
                if value is None or value.text is None:
                    continue
                if cell.attrib.get("t") == "s":
                    parsed = strings[int(value.text)]
                elif cell.attrib.get("t") in {"e", "str", "b"}:
                    parsed = value.text
                else:
                    parsed = float(value.text)
                cells[cell.attrib["r"]] = parsed
            result[name] = cells
        return result


def column(index):
    text = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        text = chr(65 + remainder) + text
    return text


def extract(path=SOURCE):
    if hashlib.md5(path.read_bytes()).hexdigest() != MD5:
        raise ValueError("EI workbook differs from reviewed OWID snapshot; review new vintage")
    book = workbook_cells(path)
    if book["Definitions"]["A50"] != "\u2020 Mainland China":
        raise ValueError("Mainland China definition changed")
    rows = []
    source_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    for category, sheet in SHEETS.items():
        cells = book[sheet]
        if cells.get("A3") != "Terawatt-hours":
            raise ValueError("Generation units changed: " + sheet)
        countries = [ref[1:] for ref, value in cells.items()
                     if ref.startswith("A") and ref[1:].isdigit() and value == "China"]
        if len(countries) != 1:
            raise ValueError("Expected exactly one Mainland China row")
        start = int(cells["B3"])
        for year in range(2005, 2025):
            col = column(2 + year - start)
            if cells.get(col + "3") != year:
                raise ValueError("Noncontiguous annual columns")
            ref = col + countries[0]
            value = cells.get(ref)
            if not isinstance(value, (int, float)) or not isfinite(value) or value < 0:
                raise ValueError(f"Missing/invalid observation {sheet}!{ref}")
            rows.append(dict(year=year, category=category, value_twh=value,
                unit="TWh", geographic_scope="mainland_China", output_basis="gross",
                sheet=sheet, cell=ref, source_path=SOURCE.relative_to(ROOT).as_posix(),
                source_sha256=source_sha, status="reviewed_extraction_not_production_admitted"))
    data = {(r["year"], r["category"]): r["value_twh"] for r in rows}
    checks = []
    for year in range(2005, 2025):
        parts = fsum(data[year, c] for c in SHEETS if c != "total")
        residual = parts - data[year, "total"]
        if abs(residual) > 1e-7:
            raise ValueError(f"Same-vintage generation does not close: {year}: {residual}")
        checks.append(dict(year=year, component_sum_twh=parts,
                           reported_total_twh=data[year, "total"], residual_twh=residual))
    # Independent cross-tab controls, not an independent statistical source.
    annual = book["Elec generation by fuel"]
    for year, columns in [(2023, "BCDEFHI"), (2024, "JKLMNPQ")]:
        for key, col in zip(["oil", "gas", "coal", "nuclear", "hydro_primary",
                             "other_unallocated", "total"], columns):
            if abs(data[year, key] - annual[col + "44"]) > 1e-8:
                raise ValueError("Cross-tab mismatch")
    notes = {sheet: {ref: value for ref, value in book[sheet].items()
                     if ref.startswith("A") and isinstance(value, str)
                     and ("gross" in value.lower() or "uncategorized" in value.lower())}
             for sheet in SHEETS.values()}
    return rows, dict(source_md5=MD5, source_sha256=source_sha,
        same_vintage_closure=checks, notes=notes, team_approved=False,
        allowed_use=["generation_category_review", "same_vintage_crosscheck"],
        excluded_use=["other_is_all_oil", "other_is_all_pumped_storage",
                      "geothermal_biomass_other_is_pure_biomass", "fuel_input_measurement"],
        limitations=["Other includes statistical differences and multiple physical sources",
            "Sheet names containing inputs still report electricity OUTPUT in TWh",
            "Physical dispatch/primary energy need an explicit decomposition or uncertainty bounds",
            "No replacement of the existing national model input or its prior admission contract"])


def main():
    rows, audit = extract()
    DEST.mkdir(parents=True, exist_ok=True)
    with (DEST / "ei2025_china_generation.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    old_path = ROOT / "data/raw/batch1_national/owid_energy_data.csv"
    with old_path.open(encoding="utf-8-sig", newline="") as stream:
        old = {int(r["year"]): r for r in csv.DictReader(stream)
               if r["iso_code"] == "CHN" and 2005 <= int(r["year"]) <= 2024}
    data = {(r["year"], r["category"]): r["value_twh"] for r in rows}
    comparison = []
    for y in range(2005, 2025):
        original = float(old[y]["oil_electricity"])
        pure = data[y, "oil"]
        other = data[y, "other_unallocated"]
        comparison.append(dict(year=y, frozen_owid_oil_label_twh=original,
            ei_pure_oil_twh=pure, ei_other_unallocated_twh=other,
            frozen_label_minus_ei_oil_and_other_twh=original-pure-other))
    audit["legacy_oil_label_comparison"] = comparison
    audit["legacy_source_sha256"] = hashlib.sha256(old_path.read_bytes()).hexdigest()
    (DEST / "extraction_review.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps(dict(observations=len(rows), closure_years=len(audit["same_vintage_closure"]),
                         production_modified=False, oil_2024_twh=data[2024,"oil"],
                         other_2024_twh=data[2024,"other_unallocated"])))


if __name__ == "__main__":
    main()
