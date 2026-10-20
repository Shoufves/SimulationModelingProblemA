"""Capture selected public official sources without changing their registry or approval."""
import argparse
import hashlib
import json
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from workflow_status import official_url_allowed

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", nargs="+", required=True)
    args = parser.parse_args()
    sources = json.loads((ROOT / "data/sources.json").read_text(encoding="utf-8"))["sources"]
    domains = [x["domain"] for x in json.loads(
        (ROOT / "workflow/source_domains.json").read_text(encoding="utf-8"))["domains"]]
    registry = {s["source_id"]: s for s in sources}
    logs = []
    for sid in args.sources:
        item = registry[sid]
        url = item["url"]
        record = {"source_id": sid, "official_url": url,
                  "attempted_at": datetime.now().astimezone().isoformat(timespec="seconds")}
        try:
            if not official_url_allowed(url, domains):
                raise ValueError("Not a registered official domain")
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(request, timeout=20) as response:
                final_url = response.geturl()
                if not official_url_allowed(final_url, domains):
                    raise ValueError("Redirect left the permitted official domains")
                content = response.read(20_000_001)
                if not content or len(content) > 20_000_000:
                    raise ValueError("Empty response or exceeds capture size limit")
                suffix = Path(urlsplit(url).path).suffix.lower()
                if suffix == ".jpg":
                    from PIL import Image
                    import io
                    with Image.open(io.BytesIO(content)) as picture:
                        picture.verify()
                digest = hashlib.sha256(content).hexdigest()
                destination = ROOT / "data/raw/official" / f"{sid}_{digest[:12]}{suffix}"
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists() and destination.read_bytes() != content:
                    raise ValueError("Unexpected capture filename collision")
                destination.write_bytes(content)
                record.update(status="captured_not_reviewed", final_url=final_url,
                              path=destination.relative_to(ROOT).as_posix(),
                              sha256=digest, bytes=len(content),
                              content_type=response.headers.get("Content-Type"))
        except Exception as exc:
            record.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        logs.append(record)
        print(json.dumps(record, ensure_ascii=False), flush=True)
    folder = ROOT / "outputs/data_review"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    (folder / f"capture_{stamp}.json").write_text(
        json.dumps(logs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if all(r["status"] == "captured_not_reviewed" for r in logs) else 2


if __name__ == "__main__":
    sys.exit(main())
