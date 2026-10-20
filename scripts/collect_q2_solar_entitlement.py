"""Save and verify the original 2013 solar tariff-duration policy."""
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "data/raw/q2_solar_entitlement"
URL = "https://www.ndrc.gov.cn/xxgk/zcfb/tz/201308/t20130830_963934.html"


class Text(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts = []

    def handle_data(self, data):
        if data.strip(): self.parts.append(data.strip())


def main():
    FOLDER.mkdir(parents=True, exist_ok=True)
    path = FOLDER / "ndrc_solar_2013_1638.html"
    if not path.exists():
        with urlopen(Request(URL, headers={"User-Agent": "Mozilla/5.0"}), timeout=45) as response:
            body = response.read()
        if len(body) < 5000:
            raise ValueError("Incomplete official response")
        path.write_bytes(body)
    parser = Text(); parser.feed(path.read_bytes().decode("utf-8"))
    text = "\n".join(parser.parts)
    required = ["期限原则上为20年", "2014年1月1日及以后投运", "每千瓦时0.42元", "除享受中央财政投资补贴之外", "2013年8月26日"]
    if any(phrase not in text for phrase in required):
        raise ValueError("Policy text or applicability was not verified")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path = FOLDER / "source_manifest.json"
    if manifest_path.exists():
        old = json.loads(manifest_path.read_text("utf-8"))[0]
        if old["sha256"] != digest:
            raise ValueError("Original differs from acquisition manifest")
    else:
        manifest_path.write_text(json.dumps([dict(id="ndrc_solar_2013_1638", url=URL,
            path=path.relative_to(ROOT).as_posix(), publisher="国家发展和改革委员会",
            title="关于发挥价格杠杆作用促进光伏产业健康发展的通知（发改价格〔2013〕1638号）",
            signed_date="2013-08-26", published_date="2013-08-30", sha256=digest,
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            notes="Historical entitlement duration and central/distributed settlement distinction; not current universal tariff or national eligibility list")], ensure_ascii=False, indent=2)+"\n", "utf-8")
    (FOLDER / "text.txt").write_text(text+"\n", "utf-8")
    facts = dict(source_sha256=digest, qualification="solar stations commissioned on/after 2014-01-01; older projects require approval-date evidence",
        standard_support_years=20, plant_lifetime_years_not_changed=25,
        central_support_basis="regional benchmark tariff minus local coal reference",
        distributed_basis="full generation subsidy; surplus sold at local coal reference; self-consumption is not a grid sale",
        distributed_initial_rate_nominal_vat_inclusive_cny_per_kwh=.42,
        blocked_uses=["apply 2013 rate unchanged through 2024", "backdate eligibility for older projects without approval dates",
                      "equate a standard eligibility period with actual cash collection", "treat aggregate solar as an identified distributed/central mixture"])
    (FOLDER / "evidence.json").write_text(json.dumps(facts, ensure_ascii=False, indent=2)+"\n", "utf-8")
    print(json.dumps(facts, ensure_ascii=False))


if __name__ == "__main__": main()
