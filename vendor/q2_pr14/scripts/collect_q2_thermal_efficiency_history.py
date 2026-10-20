"""Preserve historical technical references without changing model parameters."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "data/raw/q2_thermal_efficiency_history"
SOURCES = [
    ("iea_nea_projected_costs_2010", "https://iea.blob.core.windows.net/assets/6a568ef2-46b7-44f4-b917-89316cb961b8/projected_costs.pdf", "pdf", "IEA/NEA", "2010"),
    ("iea_nea_projected_costs_2015", "https://www.oecd.org/content/dam/oecd/en/publications/reports/2015/09/projected-costs-of-generating-electricity-2015_g1g5a8b1/cost_electricity-2015-en.pdf", "pdf", "IEA/NEA (OECD host)", "2015"),
    ("nea_coal_upgrade_2014", "https://www.nea.gov.cn/2014-09/22/c_133661923.htm", "html", "国家能源局", "2014-09-22"),
    ("nea_power_statistics_2015", "https://www.nea.gov.cn/2016-01/15/c_135013789.htm", "html", "国家能源局", "2016-01-15"),
]


def main():
    FOLDER.mkdir(parents=True, exist_ok=True)
    target = FOLDER / "source_manifest.json"
    old = {r["id"]: r for r in json.loads(target.read_text("utf-8"))} if target.exists() else {}
    rows = []
    for key, url, extension, publisher, published in SOURCES:
        path = FOLDER / (key+"."+extension)
        if not path.exists():
            with urlopen(Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=45) as response:
                raw = response.read()
            if len(raw) < 3000 or (extension == "pdf" and not raw.startswith(b"%PDF")):
                raise ValueError("Incomplete or invalid original: "+key)
            path.write_bytes(raw)
        digest = sha256(path.read_bytes()).hexdigest()
        if key in old and digest != old[key]["sha256"]:
            raise ValueError("Archived original changed: "+key)
        rows.append(dict(id=key, url=url, path=path.relative_to(ROOT).as_posix(),
                         publisher=publisher, publication_date_or_year=published,
                         retrieved_at=old.get(key, {}).get("retrieved_at", datetime.now(timezone.utc).isoformat()),
                         sha256=digest, bytes=path.stat().st_size,
                         scope="historical technical-reference/policy evidence; no default model admission",
                         default_model_admission=False))
        target.write_text(json.dumps(rows, ensure_ascii=False, indent=2)+"\n", "utf-8")
    print(json.dumps(dict(sources=len(rows), original_bytes=sum(r["bytes"] for r in rows)), ensure_ascii=False))


if __name__ == "__main__":
    main()
