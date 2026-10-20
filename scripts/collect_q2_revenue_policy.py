"""Acquire immutable policy originals; never turn a download into model admission."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "data/raw/q2_revenue"
SOURCES = {
    "nea_full_purchase_2007_25.html": "https://gzb.nea.gov.cn/dtyw/tzgg/202308/t20230821_3250.html",
    "nea_clean_dispatch_2015_518.html": "https://www.nea.gov.cn/2015-04/09/c_134136821.htm",
    "ndrc_biomass_tariff_2010.html": "https://www.ndrc.gov.cn/xxgk/zcfb/tz/201007/t20100728_964666.html",
    "ndrc_waste_tariff_2012_801.html": "https://www.ndrc.gov.cn/xxgk/zcfb/tz/201204/t20120410_964415.html",
    "ndrc_gas_tariff_2014_3009.html": "https://www.ndrc.gov.cn/xxgk/zcfb/tz/201501/t20150114_963735.html",
    "ndrc_renewable_parity_2021.html": "https://www.ndrc.gov.cn/xxgk/zcfb/tz/202106/t20210611_1283088.html",
    "ndrc_renewable_market_2025.html": "https://www.ndrc.gov.cn/xwdt/tzgg/202502/t20250209_1396067.html",
    "mof_vat_2018.html": "https://szs.mof.gov.cn/zhengcefabu/201804/t20180404_2862283.htm",
    "mof_vat_2019.html": "https://m.mof.gov.cn/czxw/201903/t20190320_3200168.htm",
    "mof_subsidy_lifetime_2020_426.html": "https://m.mof.gov.cn/zcfb/202010/t20201015_3604104.htm",
    "mof_levy_2013.html": "https://zhs.mof.gov.cn/zhengcefabu/201310/t20131009_996652.htm",
    "mof_levy_2016.html": "https://www.mof.gov.cn/gkml/caizhengwengao/wg2016/wg201602/201606/t20160601_2118609.htm",
    "mof_subsidy_budget_rules_2020.html": "https://jjs.mof.gov.cn/zhengcefagui/202001/t20200122_3463379.htm",
}


def fetch(item):
    name, url = item
    path = DEST / name
    if path.exists():
        raw = path.read_bytes()
    else:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=35) as response:
            raw = response.read()
        if len(raw) < 1000 or b"<html" not in raw.lower():
            raise ValueError("Unexpected response: " + name)
        path.write_bytes(raw)
    return dict(path=path.relative_to(ROOT).as_posix(), url=url,
                sha256=hashlib.sha256(raw).hexdigest(),
                retrieved_at=datetime.now(timezone.utc).isoformat(),
                admitted=False, status="original_saved_review_pending")


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    inventory = DEST / "source_inventory.json"
    prior = json.loads(inventory.read_text(encoding="utf-8")) if inventory.exists() else []
    records = {r["path"]: r for r in prior}
    failed = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        tasks = {name: pool.submit(fetch, (name, url)) for name, url in SOURCES.items()}
        for name, task in tasks.items():
            try:
                row = task.result()
                # Preserve original retrieval provenance on an idempotent rerun.
                records.setdefault(row["path"], row)
                print("saved", name, flush=True)
            except Exception as exc:
                failed.append(dict(name=name, error=str(exc)))
                print("failed", name, type(exc).__name__, flush=True)
    inventory.write_text(json.dumps(list(records.values()), ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    if failed:
        raise RuntimeError(failed)


if __name__ == "__main__":
    main()
