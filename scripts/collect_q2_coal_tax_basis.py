"""Archive public valuation-report evidence, without changing admitted prices."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "data/raw/q2_coal_tax_basis"
SOURCES = [
    ("yunnan_valuation_20190807", "https://dnr.yn.gov.cn/uploadfile/dnr_old/manage/ewebeditor/uploadfile/20190807141900305.pdf"),
    ("yunnan_valuation_20200325", "https://dnr.yn.gov.cn/uploadfile/dnr_old/manage/ewebeditor/uploadfile/20200325171714163.pdf"),
]


def main():
    FOLDER.mkdir(parents=True, exist_ok=True)
    old = FOLDER / "source_manifest.json"
    previous = json.loads(old.read_text("utf-8")) if old.exists() else []
    records = []
    for sid, url in SOURCES:
        path = FOLDER / (sid + ".pdf")
        if not path.exists():
            payload = urlopen(Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=90).read()
            if not payload.startswith(b"%PDF"):
                raise ValueError("Expected PDF: " + url)
            path.write_bytes(payload)
        payload = path.read_bytes()
        record = dict(id=sid, url=url, path=path.relative_to(ROOT).as_posix(),
            sha256=sha256(payload).hexdigest(), bytes=len(payload),
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            host="云南省自然资源厅", source_level="publicly hosted valuation report; not automatically an NDRC original",
            default_model_admission=False)
        found = next((r for r in previous if r["id"] == sid), None)
        if found:
            assert found["sha256"] == record["sha256"]
            record = found
        records.append(record)
        print(sid, len(payload), flush=True)
    old.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", "utf-8")


if __name__ == "__main__":
    main()
