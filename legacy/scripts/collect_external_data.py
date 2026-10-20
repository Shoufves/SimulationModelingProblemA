"""Archive public source files with reproducible retrieval metadata."""

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
DATA = ROOT / "data"
CATALOG = DATA / "catalog"


def stamp():
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def collect(source):
    target = DATA / source["path"]
    target.parent.mkdir(parents=True, exist_ok=True)
    entry = dict(source)
    entry["retrieved_at"] = stamp()
    if target.exists() and target.stat().st_size:
        content = target.read_bytes()
        entry.update(status="downloaded_cached", bytes=len(content),
                     sha256=hashlib.sha256(content).hexdigest())
        return entry
    for attempt in range(2):
        try:
            request = Request(
                source["url"],
                headers={"User-Agent": "Mozilla/5.0 (compatible; academic-data-preparation/1.0)"},
            )
            with urlopen(request, timeout=35) as response:
                content = response.read()
                final_url = response.url
                content_type = response.headers.get("Content-Type", "")
                last_modified = response.headers.get("Last-Modified", "")
            if len(content) < 100:
                raise ValueError("Response is too short to be a source file")
            expected = source.get("format", "")
            if expected == "pdf" and not content.startswith(b"%PDF"):
                raise ValueError("Expected PDF signature was not returned")
            if expected == "xlsx" and not content.startswith(b"PK"):
                raise ValueError("Expected XLSX ZIP signature was not returned")
            if expected in {"csv", "json"} and b"<html" in content[:500].lower():
                raise ValueError("Received HTML instead of structured data")
            target.write_bytes(content)
            entry.update(
                status="downloaded_unchecked", bytes=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                final_url=final_url,
                content_type=content_type,
                http_last_modified=last_modified,
            )
            return entry
        except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
            entry.update(status="download_failed", error=str(exc))
            if attempt == 0:
                time.sleep(1)
    return entry


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids", nargs="*")
    args = parser.parse_args()
    CATALOG.mkdir(parents=True, exist_ok=True)
    sources = json.loads((CATALOG / "sources.json").read_text(encoding="utf-8"))
    manifest_path = CATALOG / "retrieval_manifest.json"
    entries = {}
    if manifest_path.exists():
        entries = {r["id"]: r for r in json.loads(manifest_path.read_text(encoding="utf-8"))}
    chosen = [s for s in sources if not args.ids or s["id"] in args.ids]
    for source in chosen:
        entry = collect(source)
        entries[source["id"]] = entry
        manifest_path.write_text(
            json.dumps(list(entries.values()), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(source["id"], entry["status"], entry.get("bytes", entry.get("error", "")), flush=True)


if __name__ == "__main__":
    main()
