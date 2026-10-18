# 本地多能源仿真实验台

日期：2026-10-17。载体为Python模型内核与Streamlit界面；界面只调用已有计算机制，不替代数据核验、历史校准和科研验收。

逐步操作见[带截图的用户手册](<13_workbench_user_manual.md>)及[Word版](<../outputs/manuals/多能源仿真实验台操作手册.docx>)。本轮操作验收与修复见[网站测试记录](<../outputs/data_review/review_workbench_site_20261017.md>)。

## 运行

当前项目专用环境为`.venv-workbench/`，不随作品提交；`requirements-workbench.txt`记录界面直接依赖，本次主要包版本记录在实验台审查中。模型标准库入口不依赖Streamlit；最终提交前仍需在干净环境锁定完整间接依赖并复现。

```powershell
.\run_workbench.ps1
# 默认地址 http://127.0.0.1:8501；占用时指定其他端口
.\run_workbench.ps1 -Port 8502
```

在其他Python环境安装并运行：

```powershell
python -m venv .venv-workbench
.\.venv-workbench\Scripts\python.exe -m pip install -r requirements-workbench.txt
.\run_workbench.ps1
```

脚本仅绑定本机127.0.0.1，关闭浏览器遥测，不安装依赖、不自动开放外网。当前Python环境复用宿主已有pandas/numpy；另机独立环境由依赖清单安装。停止服务可在启动终端按Ctrl+C。

## 已接入的工作区

|入口|实际行为|结果边界|
|---|---|---|
|主体反馈实验|碳价、可再生成本、进口能力及送出能力可调；三组机制从同一配置运行；展示容量、设备份额、价格、缺供及决策日志|抽象步和EU/SU/CU；非全国历史或2030/2060预测|
|连续储能实验|选择连续窗口，调整储能功率/容量、负荷、碳价和送出能力；有/无储能共享同一需求、电源和线路|MW/MWh为合成程序单位；不外推全年风险，不与年度投资自动耦合|
|官方数据与进度|现场运行证据和原件检查；展示候选/限定用途准入、年份、来源、原始观测、脚注和工作流|只读；不批准数据；正式证据失败时所有已核验标识撤销|

参数表通过运行按钮提交；查看图表和切换主体日志不会重新采样或修改配置。切换工作区保留已运行参数，页面同时显示结果实际使用参数；未提交编辑不作为运行配置保存。主体展示机制统一控制顶部指标、轨迹及决策日志。已运行参数以结果包中的`parameters`及`configuration`为准；“恢复默认”重置对应参数并重新运行。运行失败清除旧结果，避免后续误用。

配置和结果保留在当前浏览器会话，刷新或断开后可能丢失；需要留存时使用页面下载。界面不自动覆盖`outputs/prototype/`中的标准对照，也不改写观测、审查、来源登记或正式输入清单。页面导出文件名带synthetic、模型种类和运行标识。

## 导出与复算

下载包包含完整实际配置、调参值、全部对照轨迹与摘要、配置及代码SHA256、时间（Asia/Shanghai）和合成边界。运行标识由配置、计算代码和对照种类共同生成；相同输入/代码复跑标识一致，生成时间另存。

主体配置可直接传入`energy_model.agents.simulate`，分别设置`substitution`和`investment`重跑三个对照。窗口配置可传入`simulate_operation_window`，分别开/关储能。下载包不包括Python全部间接依赖、界面代码或全国原始数据，因此不是最终提交复现包；W8仍待验收。

## 验证

```powershell
# 标准库模型与接口测试
python -B -X utf8 -m unittest discover -s tests -q
# 界面交互测试：需要专用环境依赖
.\.venv-workbench\Scripts\python.exe -B -X utf8 -m unittest discover -s tests/ui -v
```

接口测试检验参数作用、对照共享配置、导出配置重跑、运行标识、零容量储能、非法参数、观察文件路径边界、只读及证据失效撤销标识。界面测试覆盖初始化、提交、恢复默认、跨页参数保留、机制指标/日志一致性、异常清理、窗口选择和现场核验。浏览器另检查桌面/手机布局及导航、图表渲染、实际点击和下载；最新结果记于`outputs/data_review/review_workbench_site_20261017.md`，首次搭建记录保留。

## 后续科研优先级

本轮载体已可操作，但没有增加官方观测或完成全国校准。下一步仍按docs/11_calibration_input_contract.md推进消费/GDP/装机已有十年表的原表复核及分模块校准，随后耦合年度投资和运行约束。界面不能成为继续扩展合成案例而推迟真实模型的理由。
