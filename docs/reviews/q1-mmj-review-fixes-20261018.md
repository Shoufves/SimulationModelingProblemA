# mmj Q1：yx评审修复与两轮自检

对象为PR #4，修复起点`8e05bb1df991c1cd110395e9439acacc33a788b6`；共同base仍为`7a65d068d19eea2f7dd8161a618a3ad8d66f98b8`。依据2026-10-18 yx本地评审中C1、C2、M2，以及`.gitattributes`流程意见。历史自查和旧结果保留，本文件接续记录，不改写旧检查。

## 修改与范围

|意见|处理|验证依据|
|---|---|---|
|C1 / R1：非化石直接证据遗漏|从共同base已有中国NDC2035报告物理p5/印刷p3提取2024初步19.8%；登记源版本/地域/初步状态，增加独立history、指标和Q2结构核对候选|原PDF文本与完整页渲染核对；源指纹保持；不与NBS一次电力及其他合并，不回填其他年份|
|C2：价格定义断点|归档工作簿Description!B12保留欧洲2015年4月切换；2015混合年原值可追溯但排除2016/2015变化，2016—2020计算四个变化；其余五系列同定义五变化|Description逐系列定义检查、混合年度/跨定义/缺年反例、独立标准库重算|
|M2 / R3：缺可安装依赖|新增requirements-q1.txt固定matplotlib 3.10.8；运行文档给出安装命令，manifest记录渲染依赖|干净环境安装与实际Q1复跑；科学数据一致，跨环境PNG不作字节保证|
|换行属性流程|撤回本候选新增.gitattributes，Q1 PR不统一仓库属性|本地core.autocrlf=false；新克隆先关闭转换；相对base无属性文件新增，保护原件不规范化。保留目录表原CRLF，暂存空白检查以core.whitespace的cr-at-eol识别CRLF，其他空白规则保留|

源文件均来自原基线，没有新增外部原始大文件。`ndc_2024.csv`和`prices_scoped.csv`进入统一目录、实质用途审查及快照绑定，原九子集契约不变。五份细化提取仍为mmj候选增量，等待两位评审核对及Issue共同输入确认，不代替正式全国模型准入。

## 验证状态

两轮均已实际完成；当前修复不构成A7批准。Q1科学覆盖仍保留缺口，PR保持Draft，修复后更新同一个PR，不合并。

|检查|第一轮：原开发环境|第二轮：新建环境|
|---|---|---|
|解释器|Python 3.12.14|Python 3.12.14|
|依赖准备|原开发venv，matplotlib 3.10.8|先仅安装requirements-q1.txt并成功复跑；完整门禁前再安装requirements-data.txt，pip check通过|
|显式输入重建|捆绑环境执行29项实质检查，18组输入|新环境重新执行同一提取脚本，29项检查通过；输入清单及审查字节与第一轮一致|
|run.py test|172项，0失败/错误/跳过|172项，0失败/错误/跳过|
|run.py audit|14项通过|14项通过|
|密钥格式扫描及原九子集|通过，限定范围|通过，限定范围|
|两次本轮Q1命令及实际哈希|两个输出目录的10份产物一致，身份/哈希通过|两个输出目录的10份产物一致，身份/哈希通过|
|缺清单/坏指纹|返回1，不输出虚假成功|返回1，不输出虚假成功|

成功命令分别使用对应环境的Python，参数相同：

```powershell
python -B -X utf8 scripts/validate_q1.py --evidence outputs/validation/q1_mmj_reviewfix_round1.json
python -B -X utf8 scripts/validate_q1.py --evidence outputs/validation/q1_mmj_reviewfix_round2.json
```

上述两命令分别完整执行test、audit、扫描、原九子集检查、两次q1及负例。跨两种环境的8份CSV/JSON/Markdown与2张PNG此次也全部逐字节一致；这次观测不构成任意平台PNG一致保证。

额外独立来源和交付检查19项通过：NDC及WB原件与base字节相同、NDC直接初步值、Description定义日期、36个采用价格原值未改、欧洲同定义标准差独立重算、两轮代码/输入指纹对应当前字节、跨环境结果、五份旧latest恢复、原三份契约保持及属性文件撤回。结果见[独立核对](../../outputs/validation/q1_mmj_reviewfix_source_checks.json)。欧洲同定义结果为`0.4016027718890919`，有效对为2016–2017、2017–2018、2018–2019、2019–2020；混合2015原值保留但不进入上述变化。

两轮均产出882条历史、169条指标、12类角色、325条交接及16条缺口/残差。新增NDC记录仅有2024一年，继续保留初步测算和候选身份；2015—2023历史仍缺。储能、条件成本及GDP外生驱动原修复均保留，没有提前实施Q2。

## 如实保留的未通过尝试

- [沙箱首次尝试](../../outputs/validation/q1_mmj_reviewfix_sandbox_attempt.json)：172项中12个既有测试因Windows临时目录ACL出现错误；同命令移至沙箱外后第一轮全部通过，未删减测试。
- [只安装Q1清单的环境](../../outputs/validation/q1_mmj_reviewfix_q1_only_environment.json)：Q1两次成功、10份产物一致，审计/扫描/原九子集和负例通过；完整测试因原附件模块未安装openpyxl而失败。按现有数据依赖清单补齐后，第二轮全部通过。没有将该次完整测试记成成功，也没有将数据准备依赖伪装为Q1运行必需。

机器证据：[第一轮](../../outputs/validation/q1_mmj_reviewfix_round1.json)、[第二轮](../../outputs/validation/q1_mmj_reviewfix_round2.json)。两轮运行时HEAD为修复起点`8e05bb1df991c1cd110395e9439acacc33a788b6`且dirty=true；清单如实记录实际代码、输入、配置及产物哈希。独立核对另确认这些哈希与待提交的当前字节一致，不声称运行时已处于未来提交的干净工作树。后续评审仍须固定上传后的最终SHA，在自己的独立目录验证。
