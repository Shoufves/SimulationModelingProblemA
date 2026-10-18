"""Publication-style SVG figures using ReportLab standard chart objects."""
from reportlab.graphics.shapes import Drawing, String, Rect
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.charts.barcharts import HorizontalBarChart
from reportlab.graphics.charts.legends import Legend
from reportlab.graphics import renderSVG
from reportlab.lib.colors import HexColor

COLORS=[HexColor('#087f8c'),HexColor('#c56a24'),HexColor('#7752a3')]


def canvas(title,subtitle):
    d=Drawing(760,410)
    d.add(Rect(0,0,760,410,fillColor=HexColor('#ffffff'),strokeColor=None))
    d.add(String(34,376,title,fontName='Helvetica-Bold',fontSize=19,fillColor=HexColor('#17324a')))
    d.add(String(34,352,subtitle,fontSize=10,fillColor=HexColor('#526577')))
    return d


def lines(title,subtitle,series,labels,xmin,xmax,xstep,ymin,ymax,ystep,note):
    d=canvas(title,subtitle)
    chart=LinePlot();chart.x=74;chart.y=83;chart.width=620;chart.height=235
    chart.data=series;chart.joinedLines=1
    chart.xValueAxis.valueMin=xmin;chart.xValueAxis.valueMax=xmax;chart.xValueAxis.valueStep=xstep
    chart.yValueAxis.valueMin=ymin;chart.yValueAxis.valueMax=ymax;chart.yValueAxis.valueStep=ystep
    chart.xValueAxis.labelTextFormat='%d';chart.yValueAxis.labelTextFormat='%d'
    for n,color in enumerate(COLORS[:len(series)]):
        chart.lines[n].strokeColor=color;chart.lines[n].strokeWidth=2.6
    chart.yValueAxis.visibleGrid=True;chart.yValueAxis.gridStrokeColor=HexColor('#e5eaef')
    chart.xValueAxis.labels.fontSize=10;chart.yValueAxis.labels.fontSize=10
    d.add(chart)
    legend=Legend();legend.x=83;legend.y=53;legend.fontName='Helvetica';legend.fontSize=10
    legend.alignment='right';legend.columnMaximum=1;legend.dx=11;legend.deltax=195
    legend.colorNamePairs=list(zip(COLORS,labels));d.add(legend)
    d.add(String(34,17,note,fontSize=8.5,fillColor=HexColor('#526577')))
    return d


def build(out,indicators,regions,prices):
    def val(name,year):return next(r['value'] for r in indicators if r['indicator_id']==name and r['year']==year)
    series=[[(y,val(k,y)/val(k,2015)*100) for y in range(2015,2025)] for k in ('energy_total','coal_allocated_tce','real_gdp_index')]
    d=lines('Demand growth and structural change','2015 = 100 | NBS same-vintage history; mainland China',series,
        ['Energy consumption','Coal consumption (tce)','Real GDP'],2015,2024,1,90,170,20,
        'Coal tce is derived from total consumption x coal share; it is not physical coal tonnage.')
    renderSVG.drawToFile(d,str(out/'demand_trends.svg'))
    d=lines('Financing changes the cost comparison','2018 USD/MWh | CF 85%; 2020 report projected commissioning in 2025',
        [[(r,val(f'LCOE_{tech}_CF85_r{r}',2025)) for r in (3,7,10)] for tech in ('CCGT','Coal_USC','Nuclear_LWR')],
        ['CCGT (30 years)','Coal USC (40 years)','Nuclear LWR (60 years)'],3,10,1,0,100,20,
        'X: real discount rate (%) | IEA/NEA tables 3.11a-3.13a; not 2024 actual or reliability-adjusted costs.')
    renderSVG.drawToFile(d,str(out/'cost_sensitivity.svg'))
    names={'广东':'Guangdong','浙江':'Zhejiang','江苏':'Jiangsu','山东':'Shandong','北京':'Beijing',
           '内蒙古':'Inner Mongolia','云南':'Yunnan','山西':'Shanxi','四川':'Sichuan','新疆':'Xinjiang'}
    rows=sorted(regions,key=lambda r:r['share_difference_pp']);chosen=rows[:5]+rows[-5:]
    d=canvas('Where generation and consumption differ','2024 | generation share minus consumption share (percentage points)')
    b=HorizontalBarChart();b.x=146;b.y=73;b.width=540;b.height=251
    b.data=[[r['share_difference_pp'] for r in chosen]]
    b.categoryAxis.categoryNames=[names[r['region']] for r in chosen]
    b.categoryAxis.labels.fontSize=10;b.categoryAxis.labels.dx=-25;b.categoryAxis.labels.boxAnchor='e'
    b.valueAxis.valueMin=-2.5;b.valueAxis.valueMax=3.5;b.valueAxis.valueStep=1
    b.valueAxis.visibleGrid=True;b.valueAxis.gridStrokeColor=HexColor('#e5eaef')
    b.bars[0].fillColor=COLORS[0];b.bars[0].strokeColor=None
    b.categoryAxis.joinAxis=b.valueAxis;b.categoryAxis.joinAxisMode='value';b.categoryAxis.joinAxisPos=-2.5
    d.add(b)
    d.add(String(34,36,'Five most negative and five most positive shares; all 31 provinces are in regional_comparison.csv.',fontSize=9))
    d.add(String(34,17,'NBS tables 9-14 and 9-19. These differences are not measured interprovincial power flows.',fontSize=8.5,fillColor=HexColor('#526577')))
    renderSVG.drawToFile(d,str(out/'regional_shares.svg'))
    keys=['Coal, Australian','Crude oil, Brent','Natural gas, Europe']
    price_series=[]
    for key in keys:
        observations={r['year']:r['_value'] for r in prices if r['variable']==key and 2015<=r['year']<=2024}
        price_series.append([(year,value/observations[2020]*100) for year,value in sorted(observations.items())])
    d=lines('International fuel price shocks','Selected annual nominal benchmarks | 2020 = 100 | World Bank releases',price_series,
        ['Australian coal','Brent crude','European natural gas'],2015,2024,1,0,1400,200,
        'Europe 2024 annual cell rejected; line stops at 2023. These are not Chinese delivered prices.')
    renderSVG.drawToFile(d,str(out/'price_trends.svg'))
