"""Preserve verified public originals and a separate provenance manifest."""
import concurrent.futures
import hashlib
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE.parents[1] / "scripts"))
from collect import fetch

def item(id, title, agency, date, years, url, filename, use, limits):
    return dict(id=id, title=title, agency=agency, publication_date=date,
                data_years=years, url=url,
                file=str(Path("补充收集_20261017/ai_social/originals") / filename),
                use=use, limitations=limits)

JOBS = [
    item("CN_DC_POLICY_2024", "数据中心绿色低碳发展专项行动计划", "国家发展改革委等四部门", "2024-07-03（成文）；2024-07-23（发布）", "政策目标2025/2030",
         "https://www.gov.cn/zhengce/zhengceku/202407/P020240724272072479001.pdf", "cn_dc_green_plan_2024.pdf",
         "数据中心PUE、上架率、绿电、选址与存量改造约束", "目标不是实际达成值；可再生能源利用率年均增长10%不得误写为每年加10个百分点"),
    item("CN_DC_POLICY_NOTICE", "印发数据中心绿色低碳发展专项行动计划的通知", "国家发展改革委", "2024-07-23", "2024政策",
         "https://www.ndrc.gov.cn/xwdt/tzgg/202407/t20240723_1391895_ext.html", "cn_dc_green_notice_2024.html",
         "核对发文字号与成文日期", "政策通知，非统计"),
    item("CN_DC_2025_OBSERVATION", "如何让数字经济的心脏跳得更绿色、更可持续", "国家发展改革委网站", "2026-07-27", "2025",
         "https://www.ndrc.gov.cn/wsdwhfz/202607/t20260727_1406700_ext.html", "ndrc_dc_2025_observation.html",
         "2025算力设施用电规模交叉验证", "官网转载，数值表述为据相关机构统计，不能冒充官方统计调查；算力基础设施不等于AI"),
    item("CAICT_DC_DEFINITION", "数字基础设施评估体系研究报告（2024年）", "中国信息通信研究院", "2024-04（文件路径2024-04-30）", "2024方法",
         "https://www.caict.ac.cn/english/research/whitepapers/202404/P020240430629700007503.pdf", "caict_digital_infrastructure_2024.pdf",
         "可计量数据中心用电量统计定义", "定义与指标体系，非全国实际用电观测"),
    item("IEA_ENERGY_AI_2025", "Energy and AI", "IEA", "2025-04-10", "历史2024及前瞻2030/2035",
         "https://iea.blob.core.windows.net/assets/de9dea13-b07d-42c5-a398-d1b3ae17d866/EnergyandAI.pdf", "iea_energy_ai_2025.pdf",
         "中国/全球数据中心用电、PUE、IT负载、效率反弹情景", "国际机构估计/预测；必须提取中国图表并保留定义，全球增长率不可当中国参数"),
    item("IEA_ENERGY_AI_2026", "Key Questions on Energy and AI", "IEA", "2026-04-16", "2025及前瞻；2026为估计",
         "https://iea.blob.core.windows.net/assets/3179f7f8-01f6-4dd6-bffa-c9f7b73f1dc9/KeyQuestionsonEnergyandAI.pdf", "iea_key_questions_energy_ai_2026.pdf",
         "更新算力扩张、效率与电网瓶颈假设", "非中国官方统计；前瞻值仅作情景依据"),
    item("NBS_HOUSEHOLD_2024", "2024年居民收入和消费支出情况", "国家统计局", "2025-01-17", "2024",
         "https://www.stats.gov.cn/sj/zxfb/202501/t20250117_1958325.html", "nbs_household_2024.html",
         "城乡居民收入/消费初始化、调查口径", "居住支出包含租金等；不能等同能源支出"),
    item("NBS_HOUSEHOLD_2025", "2025年居民收入和消费支出情况", "国家统计局", "2026-01-19", "2025",
         "https://www.stats.gov.cn/sj/zxfb/202601/t20260119_1962321.html", "nbs_household_2025.html",
         "居民收入/消费校验与更新", "消费八大类不直接提供收入组能源账单"),
    item("NBS_QUINTILES_2024", "2024年国民经济和社会发展统计公报", "国家统计局", "2025-02-28", "2024",
         "https://www.stats.gov.cn/zwfwck/sjfb/202502/t20250228_1958817.html", "nbs_bulletin_2024.html",
         "全国收入五等份组收入、分组定义", "五等份按调查户排序；不是收入分位点或等人口组；不得与城乡组简单交叉"),
    item("NBS_QUINTILES_2025", "2025年国民经济和社会发展统计公报（中国信息报版）", "国家统计局/中国信息报", "2026-03-02（报纸版）", "2025",
         "https://www.stats.gov.cn/zs/tjwh/tjkw/tjqk/zgxxb/202603/P020260302324456612328.pdf", "nbs_bulletin_2025_newspaper.pdf",
         "2025五等份收入更新", "公报初步统计；报纸排版PDF"),
    item("WB_CHINA_CCDR", "China Country Climate and Development Report", "World Bank Group", "2022-10-12", "历史与2060情景",
         "https://documents1.worldbank.org/curated/en/099615111222222299/pdf/P1775720ebd1a10f30a0240925eda4ecac2.pdf", "wb_china_ccdr_2022.pdf",
         "煤炭地区就业集中、地区财政与社会支持机制", "报告情景不是现实预测；煤炭采矿与煤电岗位口径不同"),
    item("WB_SHANXI_PID_2019", "Shanxi Energy Transition and Green Growth Development Policy Operation: Concept PID", "World Bank", "2019（PDF内日期复核）", "2018",
         "https://documents1.worldbank.org/curated/en/609661563417538196/pdf/Concept-Program-Information-Document-PID-Shanxi-Energy-Transition-and-Green-Growth-Development-Policy-Operation-P170663.pdf", "wb_shanxi_pid_2019.pdf",
         "山西煤矿就业历史量级与地区转型机制", "项目概念文件非实施效果；2018人数不可初始化2024"),
    item("WB_COAL_CLOSURE_2018", "Managing Coal Mine Closure: Achieving a Just Transition for All", "World Bank", "2018-11（报告）；2018-12-12（发布页）", "历史案例",
         "https://documents1.worldbank.org/curated/en/484541544643269894/pdf/130659-REVISED-PUBLIC-Managing-Coal-Mine-Closure-Achieving-a-Just-Transition-for-All-November-2018-final.pdf", "wb_managing_coal_closure_2018.pdf",
         "关闭、转岗、社会保护及社区衍生就业机制", "跨国案例可支撑机制；不可移植失业率/转岗率"),
    item("ILO_CHINA_RESTRUCTURING", "Employment impacts of enterprise restructuring in the transition to the green economy", "ILO / 全国总工会研究团队", "2016-01-04（发布页）", "报告历史企业案例",
         "https://www.ilo.org/sites/default/files/wcmsp5/groups/public/@asia/@ro-bangkok/documents/publication/wcms_490811.pdf", "ilo_china_restructuring_2016.pdf",
         "中国能源等八企业重组就业与培训案例", "小样本案例，非全国代表性；年份较旧"),
]

def main():
    corrections = {
        "CN_DC_2025_OBSERVATION": ("2026-07-27（网页）；2026-07-21（报纸原文）", "国家发展改革委网站；原发布者中国发展改革报社《中国经济导报》"),
        "CAICT_DC_DEFINITION": ("2024-03（封面）；2024-04-30（文件路径）", None),
        "IEA_ENERGY_AI_2025": ("2025-04（PDF）", None),
        "IEA_ENERGY_AI_2026": ("2026-04（PDF末页排印日期；具体日未核实）", None),
        "WB_CHINA_CCDR": ("2022-10（封面）", None),
        "WB_SHANXI_PID_2019": ("2019-07-17（封面Prepared/Updated）", None),
        "WB_COAL_CLOSURE_2018": ("2018-11（报告封面）", None),
        "ILO_CHINA_RESTRUCTURING": ("2016（版权页First published）", None),
    }
    for job in JOBS:
        if job["id"] in corrections:
            date, agency = corrections[job["id"]]
            job["publication_date"] = date
            if agency:
                job["agency"] = agency
        if job["id"].startswith("IEA_"):
            job["limitations"] += "；China含香港，2026版印刷p121；不得直接用于中国大陆校准"
        if job["id"] == "IEA_ENERGY_AI_2026":
            job["data_years"] = "2023-2025估计及2030/2035情景"
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        entries = list(pool.map(fetch, JOBS))
    (BASE / "sources_ai_social.json").write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# AI用能与社会转型来源清单", "", "保存日期：2026-10-17。PDF正文已提取核验，HTML保留原字节及文本。发布日期以原件为准；未核实具体日的只记年月。", ""]
    for e in entries:
        lines += [f"## {e['id']}：{e['title']}", "",
                  f"- 机构：{e['agency']}", f"- 发布日期：{e['publication_date']}；数据年份：{e['data_years']}",
                  f"- URL：{e['url']}", f"- 本地文件：{e['file']}",
                  f"- 状态：{e['status']}；字节：{e.get('bytes')}；SHA256：{e.get('sha256')}",
                  f"- 用途：{e['use']}", f"- 限制：{e['limitations']}", ""]
    (BASE / "01_来源清单.md").write_text("\n".join(lines), encoding="utf-8")
    for entry in entries:
        print(entry["id"], entry["status"], entry.get("bytes", entry.get("error")), flush=True)

if __name__ == "__main__":
    main()
