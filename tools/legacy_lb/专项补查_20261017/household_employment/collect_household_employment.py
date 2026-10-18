"""Preserve public household energy and employment research sources."""
import concurrent.futures
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE.parents[1] / "scripts"))
from collect import fetch

def job(id, title, agency, date, period, region, unit, url, filename, use, limits):
    return dict(id=id,title=title,agency=agency,publication_date=date,
                statistical_period=period,geography=region,unit=unit,url=url,
                file=str(Path("专项补查_20261017/household_employment/originals")/filename),
                use=use,limitations=limits)

NATURE = "https://media.springernature.com/original/springer-static/esm/art%3A10.1038%2Fs41560-023-01193-z/MediaObjects/"
JOBS = [
job("CFPS_PUBLIC_ACCESS","CFPS公开数据申请指南","北京大学中国社会科学调查中心","网页未标发布日期；2026-10-17核验","现行访问规则","CFPS公开数据","审核3工作日","https://www.isss.pku.edu.cn/cfps/sjzx/gksj/index.htm","cfps_public_access.html","核实注册登录与审核要求","本次未注册、未登录、未申请或取得CFPS数据库"),
job("CFPS_AI_RULES","CFPS数据使用中的人工智能工具管理规定","北京大学中国社会科学调查中心","网页未标发布日期；2026-10-17核验","现行使用规则","CFPS公开及限制数据","不适用","https://www.isss.pku.edu.cn/cfps/sjzx/AIsyglgd/index.htm","cfps_ai_rules.html","微观数据与云端AI使用边界","禁止云端AI访问家庭/个人微观及衍生数据；允许公开文档、元数据与不识别个体的群体汇总"),
job("GULIANHE_TRANSITION_2025","古莲河矿业公司：从黑色矿山到绿色高地的转型之路","大兴安岭林业集团公司；国家林草局发布","2025-10-15","近年来，截止报道日","黑龙江古莲河矿业","株；公顷；规划产值","https://www.forestry.gov.cn/c/www/dmxagzdt/645296.jhtml","gulianhe_transition_2025.html","实际生态产业转型案例","未披露实际转岗人数；百万株、520公顷、3000万元均为未来规划"),
job("SX_CENSUS_2023","山西省第五次全国经济普查公报（第三号）","山西省统计局","2025-04-11","2023年末","山西","万人；个","https://tjj.shanxi.gov.cn/tjsj/tjgb/jjpcgb/202504/t20250411_9807690.shtml","shanxi_census_2023.html","煤炭采洗就业存量","企业法人单位；年末存量不是年度净失业；表为图片"),
job("SX_CENSUS_TABLE32","山西五经普表3-2","山西省统计局","2025-04-11","2023年末","山西","万人；个","https://tjj.shanxi.gov.cn/tjsj/tjgb/jjpcgb/202504/W020250411648609028043.png","shanxi_table32.png","提取煤炭采洗人数","需人工读图"),
job("NM_CENSUS_2023","内蒙古第五次全国经济普查公报（第三号）","内蒙古统计局；玉泉区政府转载","2025-03-18原文；2025-05-21转载","2023年末","内蒙古","万人；个","http://www.yuquan.gov.cn/zfxxgkpt/fdzdgknr/tjxxnew/tjgb/202505/t20250521_1892348.html","neimenggu_census_2023.html","煤炭采洗19.9万人、1077企业","全区企业法人单位，不是仅玉泉区；不是2024/25就业"),
job("CFPS_PKU_RESEARCH","能源消费的时空差异文献介绍","北京大学中国社会科学调查中心","2024-07-12","2011—2017费用；2012—2018调查轮次","中国CFPS样本","比例；能源负担","https://www.isss.pku.edu.cn/cfps/xzyj/wxzsm/1201867cfps1378557.htm","cfps_research_intro.html","研究背景和城乡负担","发布年不是观测年；文章介绍不替代微观样本"),
job("ENERGY_INEQUALITY_PAPER","Examining energy inequality under the rapid residential energy transition in China through household surveys","Wang et al.; Nature Energy","2023-02-16","2013—2017","中国CFPS样本","分组费用和负担见附件","https://www.nature.com/articles/s41560-023-01193-z","energy_inequality_paper.html","原论文公开摘要、数据声明、附件","正文订阅；不绕过付费；微观数据需CFPS平台申请及遵守条款"),
job("ENERGY_INEQUALITY_SI","Supplementary Information","Wang et al.; Nature Energy","2023-02-16","2013—2017","中国CFPS样本","多种；见表头",NATURE+"41560_2023_1193_MOESM1_ESM.pdf","energy_inequality_si.pdf","收入组定义、样本及费用口径","历史样本不能初始化2024；分组不自动等同NBS五等份"),
job("ENERGY_INEQUALITY_SUPDATA","Supplementary Data 1","Wang et al.; Nature Energy","2023-02-16","2013—2017","中国CFPS样本","多种；见工作表",NATURE+"41560_2023_1193_MOESM3_ESM.zip","energy_inequality_suppdata.zip","补充图2—7源数据","图表源数据不等于CFPS原始微观数据"),
job("ENERGY_INEQUALITY_SOURCEDATA","Source Data Figs. 1–6","Wang et al.; Nature Energy","2023-02-16","2013—2017","中国CFPS样本","多种；见工作表",NATURE+"41560_2023_1193_MOESM4_ESM.zip","energy_inequality_source_data.zip","收入分组能源支出与负担可用历史值","图表源数据不等于CFPS原始微观数据"),
]

def main():
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        entries=list(pool.map(fetch,JOBS))
    (BASE/"sources_household_employment.json").write_text(json.dumps(entries,ensure_ascii=False,indent=2),encoding="utf-8")
    for e in entries:
        print(e["id"],e["status"],e.get("bytes",e.get("error")),flush=True)
if __name__=="__main__":
    main()
