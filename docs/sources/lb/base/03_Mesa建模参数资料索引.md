# Mesa建模参数资料索引

暂按Python + Mesa组织。下表是参数取数入口，尚不是已校准参数表。每个正式参数应保留：名称、Agent类型、值、单位、价格年/统计年、地区、来源页码、区间、处理方法。

|参数组|本地来源|使用方法|
|---|---|---|
|需求、GDP、人口、行业弹性|[9-2 能源消费总量及构成](<../../../../data/raw/batch1_national/nbs_2025_C09-02.jpg>)；[3-4 国内生产总值指数](<../../../../data/raw/lb/base/nbs/yearbook2025/C03-04.jpg>)|年鉴能源消费与GDP指数；先估计历史需求弹性，人口/行业细分回到原表|
|技术初始装机与新增/退役|[Renewable Capacity Statistics 2026](<../../../../data/raw/lb/base/reports/irena_capacity_2026.pdf>)；[2025年全国电力统计数据](<../../../../data/raw/batch1_national/nea_electricity_2025.html>)；[2025年可再生能源并网运行情况](<../../../../data/raw/batch1_national/nea_renewable_2025.html>)|IRENA容量报告中国行；官方电力统计；退役不能直接由净增装机推得|
|可再生投资/运维与学习曲线|[Renewable Power Generation Costs in 2024完整报告](<../../../../data/raw/batch3_scenarios/irena_power_costs_2024.pdf>)；[Renewable power generation costs in 2025 Executive Summary](<../../../../data/raw/lb/base/reports/irena_cost_2025_summary.pdf>)|各技术总安装成本、LCOE、容量因子章节；全球均值与中国数值分开|
|核电/常规发电经济参数|[Projected Costs of Generating Electricity 2020](<../../../../data/raw/lb/base/reports/iea_oecd_generation_cost_2020.pdf>)|核电、煤气、水电等技术章节；2020历史基准须更新价格与融资条件|
|储能与氢能|[中国新型储能发展报告2025](<../../../../data/raw/lb/base/reports/storage_2025.pdf>)；[中国氢能发展报告2025](<../../../../data/raw/batch3_scenarios/nea_hydrogen_2025.pdf>)；[氢能产业发展中长期规划2021-2035](<../../../../data/raw/lb/base/policies/hydrogen_plan_2035.pdf>)|装机、时长、技术路线和应用场景；能量/功率、效率、利用率分开|
|燃料和碳排放|[2006 IPCC Guidelines Volume 2 Chapter 2 Stationary Combustion](<../../../../data/raw/batch3_scenarios/ipcc_2006_stationary_combustion.pdf>)；[2023年电力二氧化碳排放因子](<../../../../data/raw/batch2_mechanisms/mee_electricity_co2_factors_2023.pdf>)|IPCC默认热值/排放因子及不确定性；中国电力因子用于相应核算边界|
|CCUS、碳汇与残余排放|[Opportunities for Hydrogen Production with CCUS in China](<../../../../data/raw/lb/base/reports/iea_hydrogen_ccus_china_2022.pdf>)；[中华人民共和国气候变化第一次双年透明度报告](<../../../../data/raw/lb/base/reports/china_btr1_2024.pdf>)|CCUS路径及能耗；国家清单和土地利用/林业章节；存量与流量分开|
|燃料价格与供给安全|[World Bank Pink Sheet历史年度商品价格](<../../../../data/raw/batch1_national/wb_commodity_prices_annual.xlsx>)；[中国油气勘探开发发展报告2026](<../../../../data/raw/lb/base/reports/oilgas_2026.pdf>)|国际基准价格与油气供需；汇率、运输和税费另行处理|
|碳市场、电价、容量收益|[全国碳市场发展报告2025](<../../../../data/raw/lb/base/reports/carbon_market_2025.pdf>)；[2025年度中国电力市场发展报告](<../../../../data/raw/lb/base/reports/power_market_2025.pdf>)；[深化新能源上网电价市场化改革通知](<../../../../data/raw/lb/base/policies/renewable_price_136_2025.html>)；[关于完善发电侧容量电价机制的通知2026年第114号](<../../../../data/raw/lb/base/policies/capacity_price_2026.html>)|市场机制及实施时间；2023煤电容量政策须结合2026更新使用|
|政策约束与情景目标|[国务院关于印发2030年前碳达峰行动方案的通知](<../../../../data/raw/lb/base/policies/carbon_peak_2030.html>)；[2035年中国国家自主贡献报告](<../../../../data/raw/lb/base/reports/china_ndc_2035.pdf>)；[新型能源体系建设十五五规划全文](<../../../../data/raw/lb/base/policies/energy_plan_15.pdf>)|作为情景输入或外部比较标准；不能先强制达标再将结果称为预测|
|气候冲击与供电可靠性|[2025年中国气候公报](<../../../../data/raw/lb/base/reports/climate_2025.pdf>)；[2024年全国电力可靠性年度报告](<../../../../data/raw/lb/base/reports/power_reliability_2024.pdf>)|历史灾害、设备可靠性；需把报告统计映射成冲击概率/损失区间|
|投资主体行为与交互|[Financing the Transition Toward Carbon Neutrality—An Agent-Based Approach to Modeling Investment Decisions in the Electricity System](<../../../../data/raw/lb/base/literature/abm_investment_2021.html>)；[Agent based modeling of energy consuming rights trading for low carbon transition](<../../../../data/raw/lb/base/literature/abm_energy_rights_2025.html>)|参考方法与机制设计；论文参数不能未经校准直接移植中国全能源系统|

实施顺序建议：先跑通全国年度能源平衡，再加入区域差异、企业投资与政策反馈；基准情景和至少三个对照情景使用同一历史校准参数集，仅调整明确列出的外生假设。成本、排放、供需平衡和安全指标应同时输出。
