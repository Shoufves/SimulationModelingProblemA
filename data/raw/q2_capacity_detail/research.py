"""Archive public capacity-detail research; offline run rebuilds auditable rows."""
from pathlib import Path
from html.parser import HTMLParser
from urllib.request import Request, urlopen
from urllib.parse import urljoin
from datetime import datetime, timezone
import csv, hashlib, json, re, sys, os

ROOT=Path(__file__).resolve().parent
OLD=ROOT.parent/"q2_technology_scope"

class Page(HTMLParser):
    def __init__(self,text):
        super().__init__();self.rows=[];self.links=[];self.text=[];self.row=None;self.cell=None;self.href=None;self.label=[];self.skip=0
        self.feed(text)
    def handle_starttag(self,t,a):
        if t in ("script","style"):self.skip+=1
        if t=="tr":self.row=[]
        if t in ("td","th") and self.row is not None:self.cell=[]
        if t=="a":self.href=dict(a).get("href");self.label=[]
    def handle_data(self,s):
        if self.skip:return
        self.text.append(s)
        if self.cell is not None:self.cell.append(s)
        if self.href is not None:self.label.append(s)
    def handle_endtag(self,t):
        if t in ("script","style"):self.skip=max(0,self.skip-1)
        if t in ("td","th") and self.cell is not None:
            self.row.append(re.sub(r"\s+"," ","".join(self.cell)).strip());self.cell=None
        if t=="tr" and self.row is not None:self.rows.append(self.row);self.row=None
        if t=="a" and self.href is not None:self.links.append((self.href,"".join(self.label).strip()));self.href=None

def parse(path):
    raw=path.read_bytes()
    for enc in ("utf-8","gb18030"):
        try:return Page(raw.decode(enc))
        except UnicodeDecodeError:pass
    raise ValueError(path)

def fetch(url,path):
    if not path.exists():
        with urlopen(Request(url,headers={
            "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0.0.0 Safari/537.36",
            "Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language":"zh-CN,zh;q=0.9,en;q=0.8"}),timeout=45) as r:path.write_bytes(r.read())
        print("saved",path.name,flush=True)

def main():
    online="--download" in sys.argv
    sources=[
      dict(file="cec_2009_portal.html",url="https://chinaenergyportal.org/2009-2008-detailed-electricity-statistics/",kind="CEC_unofficial_reprint",year=2009),
      dict(file="cec_2021_preliminary.html",url="https://chinaenergyportal.org/2021-electricity-other-energy-statistics-preliminary/",kind="CEC_unofficial_reprint_preliminary",year=2021),
      dict(file="nbs_gdp_energy_method.html",url="https://www.stats.gov.cn/zs/tjws/zytjzbqs/dwgn/202410/t20241025_1957172.html",kind="official_method",year=None),
      dict(file="nbs_energy_definitions.html",url="https://www.stats.gov.cn/sj/zbjs/202302/t20230202_1897102.html",kind="official_definition",year=None),
      dict(file="nbs_energy_2021_definitions.html",url="https://www.stats.gov.cn/sj/ndsj/2021/html/zb09.htm",kind="official_definition",year=2021),
      dict(file="nbs_recovered_generation_definition.html",url="https://tjj.sjz.gov.cn/columns/8905b1d7-42ba-4a0c-8013-bdf3c0aa7539/202201/19/f4b70955-4bca-4ef9-93f6-dfd8b1c1874f.html",kind="official_reprint_definition",year=2021),
      dict(file="cec_2019_detail_jan2021.html",url="https://chinaenergyportal.org/2019-detailed-electricity-statistics-update-of-jan-2021/",kind="CEC_unofficial_reprint_revised",year=2019),
      dict(file="gas_2021_cec_reprint_tnpc.html",url="https://www.tnpjvc.com.cn/tnpjvc/c102309/2022-02/24/content_14e28a9f72de45eb9eaf24d17fb08210.shtml",kind="SOE_NEA_reprint",year=2021),
      dict(file="gas_2024_industry_map.html",url="https://gdshe.org/article/23719.html",kind="industry_association_reprint",year=2024),
      dict(file="gas_2024_cec_cited_analysis.html",url="https://www.escn.com.cn/news/show-2123605.html",kind="industry_analysis_CEC_cited",year=2024),
    ]
    # Reuse the previously frozen original instead of downloading it again.
    sources.append(dict(file="../q2_technology_scope/cec2014_portal.html",url="https://chinaenergyportal.org/2014-detailed-electricity-statistics/",kind="CEC_unofficial_reprint",year=2014))
    oldmanifest=json.loads((OLD/"source_manifest.json").read_text("utf-8"))["sources"]
    for needle,year in (("nea_biomass_2014_reply.html",2014),("nea_biomass2021.html",2021),("nea_renewable_2024.html",2024)):
        source=next(s for s in oldmanifest if s["path"].endswith(needle))
        path=ROOT.parents[2]/source["path"]
        sources.append(dict(file=os.path.relpath(path,ROOT).replace("\\","/"),url=source["url"],kind="official_NEA_existing",year=year))
    oldpage=parse(OLD/"cec2014_portal.html")
    for year in range(2010,2020):
        if year==2014:continue
        matches=[urljoin("https://chinaenergyportal.org/2014-detailed-electricity-statistics/",h) for h,t in oldpage.links if t.strip()==str(year)]
        assert matches,(year,"No explicit year link")
        sources.append(dict(file=f"cec_{year}_portal.html",url=matches[0],kind="CEC_unofficial_reprint",year=year))
    manifest=[]; tables=[]; selected=[]; anchors=[]
    for source in sources:
        path=ROOT/source["file"]
        if not path.exists() and path.resolve().parent!=ROOT:
            raise ValueError("Missing reused original; never write outside this evidence directory")
        if online and not path.exists():fetch(source["url"],path)
        page=parse(path)
        text="\n".join(s.strip() for s in page.text if s.strip())
        outfile=ROOT/(path.stem+".txt")
        outfile.write_text(text+"\n",encoding="utf-8")
        manifest.append(dict(**source,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
          fetched_utc=datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).isoformat(),
          text_file=outfile.name,
          original_links=[urljoin(source["url"],h) for h,t in page.links if "cec.org.cn" in h]))
        tables.append(dict(source_file=source["file"],url=source["url"],year=source["year"],rows=page.rows))
        section=""; coverage=""; metric=""
        for i,row in enumerate(page.rows,1):
            label=" ".join(row)
            compact=re.sub(r"\s+","",label)
            if row and row[0]:
                section=row[0]
                if "新增" in section and "MW" in row:
                    coverage="national_all_scope";metric="capacity_additions"
                elif "6000" in section:
                    coverage="power_plants_ge_6MW"
                    metric="capacity" if "MW" in row else "generation" if "GWh" in row else ""
                elif "发电装机容量" in section or section=="非化石能源发电装机容量":
                    coverage="national_all_scope";metric="capacity"
                elif re.search(r"[一二三四五六七八九十][、。].*发电量",section) or section=="非化石能源发电量":
                    coverage="national_all_scope";metric="generation"
                else:coverage="";metric=""
            relevant=any(s in compact for s in ("燃气","燃油","煤层气","生物质","秸秆","垃圾","余温","余热","Gas","Oil","Biomass","Waste","Straw"))
            if relevant:
                selected.append(dict(year=source["year"],source_file=source["file"],url=source["url"],tr_ordinal_1based=i,row=row))
            if relevant and coverage and metric and "CEC_" in source["kind"]:
                unit="MW" if metric in {"capacity","capacity_additions"} else "GWh"
                if unit not in row:continue
                unit_i=row.index(unit)
                if unit_i+2>=len(row):continue
                value=row[unit_i+2]
                row_label="".join(row[:unit_i]).strip()
                status="candidate_reprint"
                if source["year"]==2009 and metric=="generation":status="quarantine_inconsistent_with_2010_reprint"
                if source["year"]==2018 and row_label=="生物质发电" and metric=="capacity":status="quarantine_source_error_explicit_note"
                anchors.append(dict(year=source["year"],source_vintage=source["file"],metric=metric,
                    coverage=coverage,row_label=row_label,unit=unit,value=value,status=status,
                    section=section,tr_ordinal_1based=i,url=source["url"]))
    (ROOT/"source_manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (ROOT/"normalized_tables.json").write_text(json.dumps(tables,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (ROOT/"selected_rows.json").write_text(json.dumps(selected,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    prose_specs=[
        ("gas_2021_cec_reprint_tnpc.html",2021,"capacity","燃气","MW",108590,"气电10859万千瓦","SOE reprints NEA; national capacity paragraph"),
        ("gas_2024_industry_map.html",2024,"capacity","燃气","MW",143670,"气电14367万千瓦","industry association reprint, cites 中国电力知库"),
        ("gas_2024_cec_cited_analysis.html",2024,"generation","燃气","GWh",317100,"年发电量约3171亿千瓦时","CEC-cited industry analysis; approximate; gross/net unspecified"),
        ("../q2_technology_scope/cec2014_portal.html",2014,"capacity","生物质含垃圾","MW",10300,"生物质发电2014年底装机容量1030万千瓦","CEC reprint footnote4"),
        ("../q2_technology_scope/cec2014_portal.html",2014,"generation","生物质含垃圾","GWh",47400,"2014年发电量474亿千瓦时","CEC reprint footnote4"),
    ]
    for needle,year,metric,unit,value,phrase in [
        ("nea_biomass_2014_reply.html",2014,"capacity","MW",9480,"生物质发电装机948万千瓦"),
        ("nea_biomass2021.html",2021,"capacity","MW",37980,"累计装机达3798万千瓦"),
        ("nea_biomass2021.html",2021,"generation","GWh",163700,"生物质发电量1637亿千瓦时"),
        ("nea_renewable_2024.html",2024,"capacity","MW",45990,"生物质发电装机容量达到4599万千瓦"),
        ("nea_renewable_2024.html",2024,"generation","GWh",208300,"生物质发电量2083亿千瓦时"),
    ]:
        source=next(s for s in sources if s["file"].endswith(needle))
        prose_specs.append((source["file"],year,metric,"生物质官方分类",unit,value,phrase,"official NEA; preserve source vintage"))
    for file,year,metric,label,unit,value,phrase,qualification in prose_specs:
        page=parse(ROOT/file);text="".join(page.text);assert phrase in text,(file,phrase)
        anchors.append(dict(year=year,source_vintage=file,metric=metric,coverage="national_all_scope_reported",
            row_label=label,unit=unit,value=value,status="candidate_prose_anchor",
            section=qualification+"; original phrase: "+phrase,tr_ordinal_1based="",url=next(s["url"] for s in sources if s["file"]==file)))
    with (ROOT/"annual_technology_anchors.csv").open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(anchors[0]));w.writeheader();w.writerows(anchors)
    method=parse(ROOT/"nbs_gdp_energy_method.html")
    phrases=("在核算能源消费总量过程中，一次能源、二次能源不能重复计算。",
             "消费量合计 ＝ 加工转换投入 － 加工转换产出 ＋ 终端消费量 ＋ 损失量",
             "［3］回收能指企业反复循环使用的能源")
    lines=[s.strip() for s in method.text if s.strip()]
    extracts=[]
    for phrase in phrases:
        matches=[line for line in lines if phrase in line]
        assert matches,phrase
        extracts.append(dict(url=next(s["url"] for s in sources if s["file"]=="nbs_gdp_energy_method.html"),
            source_file="nbs_gdp_energy_method.html",locator=phrase,original_text=matches[0]))
    (ROOT/"nbs_method_anchors.json").write_text(json.dumps(extracts,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    for s in selected: print(s["year"],s["tr_ordinal_1based"],s["row"])

if __name__=="__main__":main()
