"""Extract source text and report dataset structure without changing raw files."""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd
from lxml import html
from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
DATA = ROOT / "data"
parser = argparse.ArgumentParser()
parser.add_argument("--ids", nargs="*")
args = parser.parse_args()
sources = json.loads((DATA / "catalog/sources.json").read_text(encoding="utf-8"))
for source in sources:
    if args.ids and source["id"] not in args.ids:
        continue
    file = DATA / source["path"]
    if not file.exists():
        continue
    print("\nSOURCE", source["id"])
    suffix = source["format"]
    if suffix in {"html", "pdf"}:
        if suffix == "html":
            encoding = "gb18030" if "yearbook" in file.name else "utf-8"
            doc = html.fromstring(file.read_bytes(), parser=html.HTMLParser(encoding=encoding))
            for node in doc.xpath("//script|//style"):
                node.drop_tree()
            text = "\n".join(t.strip() for t in doc.text_content().splitlines() if t.strip())
        else:
            reader = PdfReader(file)
            text = "\n\n".join(f"[PDF page {i}]\n{p.extract_text()}" for i, p in enumerate(reader.pages, 1))
        target = DATA / "extracted" / (source["id"].lower() + ".txt")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        print(text[:1400])
    elif suffix == "json":
        doc = json.loads(file.read_text(encoding="utf-8"))
        if isinstance(doc, dict) and "files" in doc:
            print("TITLE", doc.get("metadata", {}).get("title"))
            for f in doc["files"]:
                print(f["key"], f["size"], f["links"]["self"])
        elif isinstance(doc, list):
            print("metadata", doc[0])
    elif suffix == "xlsx":
        book = pd.ExcelFile(file)
        for name in book.sheet_names:
            frame = pd.read_excel(book, sheet_name=name, header=None)
            print("SHEET", name, frame.shape)
            print(frame.iloc[:9, :8].to_string(index=False, header=False))
    elif suffix == "csv":
        frame = pd.read_csv(file)
        print("shape", frame.shape)
        print(frame.head(3).to_string(index=False))
