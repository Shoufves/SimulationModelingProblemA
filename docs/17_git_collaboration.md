# 17 · 三人 Git 协作规则（A 题）

> 适用对象：yx、mmj、lb 三人共同在 A 题仓库上并行攻关。
> 目标：**三个人用各自的 AI 同时完整解决同一个问题 → 谁先完成并自检通过谁先提 PR → 三人认可后合并，停止重复开发并进入下一题 → 有明确增量价值的部分另提补强 PR**，并且任何时刻 `main` 都是可运行、可复现、可提交的状态。
>
> 本文是“我们这个仓库该怎么用 Git”的作业规程。第 2 章补心智模型，第 8 章是事故手册，第 12 章是可直接复制的模板。
>
> 共享原文为仓库内的 `docs/17_git_collaboration.md`。每位成员的本地目录名、磁盘位置、操作系统和 Agent 可以不同；不要复制其他成员的本机路径或身份配置。

---

## 0. 一页速查（先看这里）

**三条铁律**

1. `main` 只能通过 PR 合并进入，任何人不得直接 `git push origin main`。
2. 每轮问题开工前，三人从**同一个 commit** 切分支；分支命名 `p<轮次>/<人名>`，例如 `p1/yx`。
3. 合并前必须由**另外两人明确评审并批准同一个最终提交**，复现要求见 §5.3。先提先评，满足验收并获认可后才停止重复开发。

**每轮六步**

| 步 | 谁 | 动作 | 产出 |
|---|---|---|---|
| 0 | 主持人（轮值） | 锁定起跑线、输入范围和验收标准，开 Issue | 同一份任务说明和 base SHA |
| 1 | 三人各自 | 从 base 切分支，独立开发，早提交早 push | 三条并行分支 |
| 2 | 先完成者 | 提 Draft PR → 自检通过后转 Ready | 第一个方案 PR |
| 3 | 另外两人 | 优先评审候选方案，在独立目录核验结果 | 认可 / 需修改 / 可补强 / 另起 |
| 4 | 非提案人的合并者 | 三人认可 → squash 合并；有分歧 → 见 §5.4 | `main` 前进一格 |
| 5 | 全体 | 停止已被覆盖的开发，简记结论后进入下一题 | 备选留档，有价值的增量另提 PR |

**编号区分**：`P0` 是首次开工准备，用来建立共享规程、任务 Issue、输入范围和验收标准；本轮的“阶段 0”也承担同样的开工确认职责。第一次开发轮次为 `P1`，本轮对应赛题问题一 `Q1`，个人分支为 `p1/yx`、`p1/mmj`、`p1/lb`，不为准备工作创建三条 `p0/*` 方案分支。`F0—F7` 是研究实施阶段，含义见 `WORKFLOW.md`，不与 P/Q 编号混用。

首次准备及问题一任务说明见 [P0 → P1/Q1 开工单](rounds/P0_P1_Q1.md)。开工单可能仍处于准备状态；**只有 Issue 明确标注“已锁定”、给出完整 base SHA，且共享资料已在该提交中可获取后，才开始三人开发**。不要从本文的旧示例或本机未提交文件推断起跑线。

**每天开工：在自己的仓库或 worktree 内执行**

```powershell
git rev-parse --show-toplevel   # 确认这是自己本次任务的工作目录
git fetch --prune
git status -sb
```

**路径与命令约定**：正文中的 `README.md`、`docs/`、`outputs/` 等均相对于 Git 仓库根目录，不是相对于本文件所在的 `docs/`。目录可以叫 `A题`、`A题-mmj` 或其他名称；根目录应有 `AGENTS.md`、`run.py` 和 `只读工作区/final.md`。在仓库内执行 `git rev-parse --show-toplevel` 获取实际根目录；从子目录运行 Python 入口前先进入该根目录。如果当前目录不在 Git 仓库中，先定位已有 clone，不要直接 `git init` 或覆盖现有文件。

示例采用 PowerShell，Git 参数与仓库内路径尽量使用 `/`。其他 shell 由 Agent 转换变量、目录切换等语法；Python 入口应使用按 `docs/RUNNING.md` 配好的本机解释器。`p1/yx`、邮箱、评审目录名均为示例，须按本人、轮次与目标替换。命令块是分步说明，不是批量执行脚本：先替换 `<base-SHA>` 等占位内容，逐条检查成功后再继续。出现冲突或检查失败就先处理，不继续提交、推送或合并。

### 0.1 三人给 AI 的共同任务约定

三人各自负责一套完整方案，不按“一个人写代码、一个人找数据、一个人写文档”拆分本轮问题。开始时向各自 AI 提供同一份任务说明：

- 本轮问题、共同 base SHA、必须完成的功能及明确不做的范围。
- `只读工作区/final.md`、`AGENTS.md` 和本轮允许使用的数据、统计口径；试验对照使用共同配置和随机种子清单。
- 验收命令、关键约束、应交付的结果及其来源证据；“内容很多、解释完整”不等于通过验收。
- 自己的身份、分支和工作目录，以及允许 Agent 执行到哪一步（本地修改、commit、push、创建 PR、评审或合并）。已获得的明确授权继续有效，无需每条命令重复确认；阅读本文本身不授予 GitHub 权限或发布授权。

有人先提 PR 后，另外两人优先评审，可保留手头进度；在三人认可并合并前，不把“已经有人提 PR”当作停止条件。评审可以借助 AI，但人要核对实际运行、原始来源和约束，不能只转述 AI 的认可。

### 0.2 Agent 开工检查与交接

Agent 开始每项任务时按以下顺序执行；已有信息从本轮 Issue、用户指令及当前仓库读取，不反复询问：

1. **读规则**：先读 `AGENTS.md`、`README.md`、`只读工作区/final.md`、`docs/IMPLEMENTATION_ROADMAP.md`、`WORKFLOW.md` 和本文；环境看 `docs/RUNNING.md`，涉及数据再读 `docs/DATA_GUIDE.md`。保护官方附件 1—4 与 `只读工作区/`，只处理 A 题，先完成 final 主线再考虑可选创新。
2. **查现场**：确认实际仓库根目录、`origin`、当前分支、已有修改、worktree 和有效提交身份，保留用户及其他任务的未提交内容。不要因目录名不同而重新 clone，也不要为本任务修改全局 Git 配置。
3. **对齐任务**：确定本人是 yx/mmj/lb 中哪位、本轮 Issue、共同完整 base SHA、验收标准及授权范围。确认 base 提交可在本地解析；缺失时先 fetch，仍无法取得再说明情况。没有共同 base 时不能自行用当前 `main` 替代。
4. **选择动作**：本人分支已存在就核对其基线、归属和已有进度后继续；不存在才从约定 SHA 创建。已有分支不要重建或用 `-C` 覆盖。评审用独立目录；一个工作目录同一时间只交给一个修改代码的 Agent。
5. **验证后交接**：只报告真实执行的检查和结果；提交前检查暂存差异，push 前确认远端与目标分支，创建 PR 前确认 base 为 `main`、compare 为本人的方案分支。交接写清分支、完整 SHA、实际检查、证据路径、PR 地址（已创建时）及下一位成员要做什么。

现场检查可使用：

```powershell
git rev-parse --show-toplevel
git remote -v
git branch --show-current
git status --short
git worktree list
git var GIT_AUTHOR_IDENT
git var GIT_COMMITTER_IDENT
```

提交身份尚未配置时，先按 §3.2 设置本人信息；身份检查失败不影响继续只读检查。涉及 GitHub 的操作使用本人账号的已认证工具，不能仅凭 SSH 连接成功就推断 PR 工具也已认证。工具或权限不可用时，完成可做的本地工作并报告具体阻碍，不能把未创建的 PR、未获得的批准或未完成的推送写成成功。遇到缺失的关键任务信息，只询问缺失项；开发和评审提示词见 §12.5、§12.6。

---

## 1. 共享仓库约定与现场状态

以下区分共享约定与各机器需现场核对的状态，不以某台机器的目录、分支列表或旧提交作为三人的默认环境：

| 项 | 现状 |
|---|---|
| 真正的 Git 仓库根 | 在自己的 clone/worktree 内用 `git rev-parse --show-toplevel` 获取；不要以文件夹名称或上层“赛题”目录判断 |
| 远端 | `origin` 指向 `Shoufves/SimulationModelingProblemA`；SSH 地址 `git@github.com:Shoufves/SimulationModelingProblemA.git`，也可使用该仓库的 HTTPS 地址与本人认证 |
| 分支 | 共享主干为 `main`；个人方案分支按轮次创建，实际列表以 fetch 后的 `git branch -a` 为准 |
| 本轮基线 commit | 主持人 fetch 并验证主干后，用 `git rev-parse HEAD` 获取完整 SHA，写入本轮 Issue；三人使用同一个 SHA |
| 仓库规模 | 含官方附件与研究原件，克隆和签出需要相应空间；文件数量、大小以当前版本为准 |
| `.gitignore` | 以当前文件为准；忽略规则不会自动移除已跟踪文件，提交前仍要检查 |
| 换行符 | 开工时检查是否已有 `.gitattributes`，避免跨系统转换破坏原件字节（见 §6.4） |
| 仓库内规则文件 | `AGENTS.md`（工程约束）、`WORKFLOW.md`（F0–F7 阶段）、`README.md`（入口与常用命令） |
| 验证入口 | `run.py audit / test / attachments / verify / prototype / catalog / reproduce-lb`，以及 `scripts/scan_google_keys.py` |

**由此推出的三条隐含要求**

- 仓库含较多原件，**任何人不要往 Git 里直接塞新的原始大文件**。需要新增时先约定共享位置，并在 `data/catalog` 登记获取方式、版本与哈希；不能只留在作者本机而让评审无法取得。
- **每次合并前必须跑 `scripts/scan_google_keys.py`**，这条是硬门禁。
- 跑脚本会改动 `outputs/`，这个目录是**被跟踪**的，所以提交时必须逐个确认文件，不许 `git add -A` 无脑加。

---

## 2. 心智模型：Git 不是网盘

### 2.1 网盘用法 vs 分支协作

你之前“当云盘用”，本质是这样的：

```text
本地文件夹  ←──push/pull──→  云端文件夹
（所有人共用一条主线，谁先谁后不知道，冲突时互相覆盖）
```

问题在于：三人直接在同一条共享分支上提交，方案边界和评审责任容易混在一起。普通 push 通常会拒绝覆盖远端已有的新提交；不能靠反复覆盖文件或强推来决定采用哪个方案。

分支协作把它换成：

```text
                       ┌── p1/yx    （方案一）
origin/main ←──────────┼── p1/mmj   （方案二）
   （唯一主干）         └── p1/lb    （方案三）
        ↑
   只有“评审通过”的才允许合回来
```

**关键点：分支很轻。** 三个方案可以分别保留，最终只合入通过验收的方案及有价值的增量，不要求把三套实现全部拼起来。

### 2.2 一个文件从改到上云，经过四层

```text
工作区(Working Tree)   你看到的文件夹，随意改
      ↓ git add         选中要提交的改动（暂存区 Index）
暂存区(Staging Area)   本次提交的清单
      ↓ git commit      打包成一个不可变的快照
本地仓库(.git)         提交历史，此时还没上云
      ↓ git push        推送到 GitHub
远端(origin)           别人能看到了
```

新手最容易错的点：**`git commit` 不等于“同步到云盘”**。commit 只在本地。要让另外两个人看到，必须 `push`。

### 2.3 必须认识的术语（中英对照）

| 术语 | 中文 | 一句话理解 |
|---|---|---|
| repository / repo | 仓库 | 带历史的项目目录；普通 clone 的 `.git` 是目录，worktree 的 `.git` 通常是指向共享元数据的文件 |
| clone | 克隆 | 将远端仓库复制到本地；每人通常只需一份，已有可用 clone 就直接使用 |
| branch | 分支 | 一条独立的开发时间线；本质是指向某个 commit 的可移动指针 |
| commit | 提交 | 一次快照 + 说明 + 作者 + 父提交，用 SHA 唯一标识 |
| HEAD | 当前指针 | 你现在站在哪个分支/哪个提交上 |
| remote / origin | 远端 | GitHub 上那份仓库副本的代号，默认叫 `origin` |
| fetch | 抓取 | 把远端最新状态取回本地（**不动你的工作区**，安全） |
| pull | 拉取 | `fetch` + `merge`（或 `rebase`）到当前分支，会动你的工作区 |
| push | 推送 | 把本地提交送到远端分支 |
| merge | 合并 | 把另一条分支的改动并入当前分支，会生成“合并提交” |
| rebase | 变基 | 把你的一串提交“搬”到新的基点上，历史更直；**会改写 commit SHA** |
| conflict | 冲突 | 两个人改了同一处，Git 不敢替你决定，要你手工选 |
| PR / Pull Request | 拉取请求 | 在 GitHub 网页上说“请把我这条分支合进 main”，并附带讨论与逐行评审 |
| review | 评审 | 在 PR 里逐行看 diff、提意见、点 Approve / Request changes |
| squash merge | 压缩合并 | 把一个 PR 里的多个 commit 压成 1 个合入 main，主干历史干净 |
| tag | 标签 | 给某个 commit 起个固定名字，如 `alt/p1-yx`，用来长期保存落选方案 |
| stash | 贮藏 | 把还没提交的改动临时收起来，工作区变干净 |
| cherry-pick | 摘取 | 只把某个/某几个 commit 搬到当前分支（补强 PR 的主力工具） |
| reset | 重置 | 把分支指针挪回去；**已推送的内容用它会害到别人** |
| revert | 反向提交 | 生成一个“抵消某次提交”的新提交，安全地撤销已合并内容 |
| reflog | 引用日志 | Git 的“后悔药账本”，记录了 HEAD 的每次移动 |

### 2.4 必须建立的直觉：只有“推送到远端的分支”才是共享的

- 本地分支、本地 commit、`stash`、`reflog` 都是**你自己机器上**的东西，别人完全看不见。
- 一旦 `push`，别人能看见，也可能基于它工作 —— 所以**已推送的公共分支永远不要 rebase / 强推**；只有你自己的 `p1/yx` 这种私有分支可以（并且要用 `--force-with-lease`）。
- `main` 是所有人共享的，属于“只许前进”的分支。

---

## 3. 一次性准备（每人只做一次，约 20 分钟）

### 3.1 选择部署方式（三选一，先定下来）

**方式 A（推荐）：三人三台电脑，各自 clone 同一个 GitHub 仓库**

只在尚无本地 clone 时执行。在终端进入自己选择的存放目录后运行，下面以 yx 为例，另外两人替换目录名：

```powershell
git clone --config core.autocrlf=false git@github.com:Shoufves/SimulationModelingProblemA.git A题-yx
Set-Location -LiteralPath './A题-yx'
```

每人本地目录可以不同名（`A题-yx`、`A题-mmj`、`A题-lb`），但**都指向同一个远端仓库**。首次签出即关闭自动换行转换，保护按原字节核验的材料。已有 clone 不执行这一段，按 §0.2 核对后复用。

**方式 B：三人共用一台电脑（或共用同一个大目录）**

绝对不要三个人在**同一个文件夹**里敲命令 —— 工作区只有一个，A 切分支会连带把 B 的文件改掉。正确做法是用 `git worktree`：一份 `.git`，三个独立工作目录。

由负责准备共享环境的人在已有仓库根目录执行一次。先由主持人确定本轮 base SHA，三个目录都从该 SHA 创建；目录或分支已存在时先核对，不重复执行：

```powershell
git fetch origin
git config --local core.autocrlf false
git config extensions.worktreeConfig true
git worktree add -b p1/yx '../A题-yx' <base-SHA>
git worktree add -b p1/mmj '../A题-mmj' <base-SHA>
git worktree add -b p1/lb '../A题-lb' <base-SHA>
```

> 示例在仓库旁创建目录；位置不足或不可写时选择其他未占用的位置，不把新 worktree 建在当前仓库内部。路径变化时同步替换下方命令。
>
> `worktree` 共享仓库级配置；已启用 `extensions.worktreeConfig` 后，用 `--worktree` 设置各自身份。将示例邮箱替换为本人 GitHub 已验证邮箱或隐私邮箱，再在原仓库根目录执行：
>
> ```powershell
> git -C '../A题-yx' config --worktree user.name 'yx'
> git -C '../A题-yx' config --worktree user.email 'yx@example.com'
> git -C '../A题-mmj' config --worktree user.name 'mmj'
> git -C '../A题-mmj' config --worktree user.email 'mmj@example.com'
> git -C '../A题-lb' config --worktree user.name 'lb'
> git -C '../A题-lb' config --worktree user.email 'lb@example.com'
> ```

身份配置不会隔离同一操作系统账号下的 GitHub 登录凭据。三人若共用机器，优先使用各自的系统账号或独立 clone 与认证；不要把共享 worktree 误认为三个独立的 GitHub 账号。后续轮次在各自目录从新 base 切分支即可，不需要每轮重复创建这些目录。

**方式 C：三人各用自己的电脑写，但 Git 操作全集中在一个人机器上**

这是最容易变成"又退回网盘"的模式，必须额外做归因处理，详见 §3.5。

### 3.2 配置自己的提交身份

每人在自己的独立 clone 根目录配置本人身份，下面以 yx 为例。姓名可以是协作昵称，邮箱使用本人 GitHub 已验证邮箱或 GitHub 提供的隐私邮箱；不要照抄示例邮箱或其他成员的配置。共用对象库的 worktree 身份按 §3.1 用 `--worktree` 设置，不用下面两条 `--local user.*` 覆盖共享配置。

```powershell
git config --local user.name  'yx'
git config --local user.email 'yx@example.com'
git config --local core.autocrlf false      # 见 §6.4，避免换行符抖出大量假改动
git config --local pull.ff only             # pull 只允许快进；分叉时先检查，见 §6.2
git config --local push.default current     # 默认推送当前分支，仍须核对目标，不能在 main 上 push
```

核对：

```powershell
git var GIT_AUTHOR_IDENT
git var GIT_COMMITTER_IDENT
```

两条命令显示本次新提交实际会用的身份；`git log` 显示的是旧提交作者，不能用来确认新提交身份。身份归因与 GitHub 登录权限分别核对。

### 3.3 配好本人远端认证（每台机器核对一次）

采用 SSH 地址（`git@github.com:...`）时，使用本人的 SSH key 并将公钥加入本人 GitHub 账号。先检查现有配置；仅在确实需要新 key 时生成，不能覆盖已有私钥。下面邮箱是示例，上传时只复制 `.pub` 公钥：

```powershell
ssh-keygen -t ed25519 -C 'yx@example.com'
Get-Content -LiteralPath (Join-Path $HOME '.ssh/id_ed25519.pub')
# 粘贴到 GitHub → Settings → SSH and GPG keys → New SSH key
ssh -T git@github.com   # 核对提示中的用户名；GitHub 不提供 shell，成功认证也可能返回非零退出码
```

`$HOME` 是 PowerShell 的当前用户主目录；其他 shell 使用对应的主目录语法。已有多账号或自定义 key 时沿用本人配置，不强行改为默认 key。选择 HTTPS 的成员使用本人的凭据管理器等认证方式，不必再配置 SSH，也不将凭据写进远端 URL 或工程文件。

管理员邀请另外两人的真实 GitHub 账号成为 **Collaborators（协作者）**，并由本人接受邀请，才能按本文方式直接推送仓库内的个人分支；`Contributors` 是贡献记录展示，不是授权入口。不要假定仓库新建后已继承旧邀请，也不要根据能 clone 就认定能 push（私有仓库 clone 同样需要读取权限）。

### 3.4 三条自检命令（每次换机器都跑一遍）

```powershell
git remote -v                    # 确认 origin 指向 SimulationModelingProblemA
git rev-parse --abbrev-ref HEAD  # 确认当前在自己的分支，不是 main
git status -sb                    # 确认工作区干净（没有意外改动）
```

### 3.5 Git 操作集中在一个人机器上时：作者 ≠ 提交者

**场景**：三人各在自己的电脑上写代码/文档，但所有文件汇到**一台机器**上，由同一个人执行 `git commit` / `git push`。

**先回答一个常见疑问：这台机器还要再 clone 一份吗？**

> **已有正确 clone 就不需要重复克隆。** 按 §0.2 核对根目录和远端，复用已有仓库；多个 Agent 同时修改时使用独立工作目录。只有一份工作目录时只能串行处理三人的分支。

**必须先理解：Git 记录两个身份**

| 字段 | 含义 | 由谁决定 |
|---|---|---|
| `author`（作者） | 真正写这段内容的人 | `user.name/user.email`，或命令行 `--author` |
| `committer`（提交者） | 敲 `git commit` 的人 | 固定是本机配置的那个人 |

默认两者相同。集中提交时若不记录实际作者，三人的提交都会显示为操作机配置的身份，难以追踪各方案归属。提交者保留实际操作者身份；提交内容属于队友时用 `--author` 明确记录作者。

**做法一（推荐）：操作机上用 worktree 分三个工作区，各自带身份**

目录创建命令复用 §3.1 方式 B，不重复建三套目录。由各成员亲自提交时配置各自身份；若实际由同一位操作者集中提交，各目录保留操作者身份，并使用下面的 `--author` 标记真实作者。worktree 隔离分支和文件，不会替代作者归因或 GitHub 认证。

**做法二：只用一个工作区，靠 `--author` 显式归因**

```powershell
git switch p1/yx
git add docs/solutions/p1-yx.md src/energy_model/annual_balance.py
git commit --author='yx <yx@example.com>' -m 'p1: 年度燃料账本打通连续 SOC'
git push
```

提交后核对（**每次都要看**）：

```powershell
git log --format='%h  作者=%an  提交者=%cn  %s' -3
# 期望：作者=yx；提交者为实际操作人
```

作者写错的补救（仅限未推送时）：`git commit --amend --author='yx <yx@example.com>'`。

**这种模式必须额外遵守三条**

1. **一人一分支，绝不串。** 绝不把 yx 的文件提交到 `p1/mmj` 分支上。串一次，PR 的 diff 就归错人，评审结论也就不成立。
2. **中转文件放 `tmp/incoming/<人名>/`**（`tmp/` 已被 `.gitignore` 忽略）。队友把文件传过来先落这里，操作者确认内容后再搬进正式路径 —— 防止把压缩包、临时图、队友本机绝对路径、`.venv` 一起提交上去。
3. **评审环节绝不能省。** 另外两人仍按 §5.3 用各自 GitHub 账号评审同一最终 SHA；统一使用“认可 / 需修改 / 可补强 / 另起”，不能由操作者代替两人批准。

**长期建议**：优先转为 §3.1 方式 A，各自提交和认证。集中模式下，队友仍能看到已推送的提交；额外成本在于文件转交、身份归因与独立评审。

---

## 4. 分支、提交与文件约定

### 4.1 分支规范

| 分支 | 用途 | 谁能写 | 是否可以强推 |
|---|---|---|---|
| `main` | 唯一主干，永远可运行 | **只有 PR 合并** | ❌ 永远不行 |
| `p1/yx`、`p1/mmj`、`p1/lb` | 第 1 个问题的三个并行方案 | 各自本人 | 仅本人进阶操作，见 §6.2 |
| `p1/mmj-supplement` | 第 1 轮的“补强 PR”分支 | 本人 | 仅本人进阶操作，见 §6.2 |
| `fix/...`、`docs/...` | 与具体问题无关的杂项修复 | 该分支负责人 | 仅本人进阶操作，见 §6.2 |

规则：

- 本轮方案分支名为 `p<轮次>/<人名>`，轮次从 1 开始；补强加后缀，杂项修复用表中的 `fix/...` 或 `docs/...`。
- 一个分支只服务一个 PR。合并或放弃后**不要复用**，下一轮从新的 `origin/main` 重新切。
- 落选的方案分支**不要删**：打一个 tag 再删分支，既留档又不污染分支列表：

```powershell
git tag -a alt/p1-yx -m '第1轮备选方案：年度主体+连续储能（未合并）' p1/yx
git push origin alt/p1-yx
```

### 4.2 提交信息规范

一行标题 ≤ 50 字，说清“做了什么”；空一行后写“为什么/验证方式”。

```text
p1: 接入 F2 年度燃料账本并打通连续 SOC

- 新增 src/energy_model/annual_balance.py，实现共燃份额与年际反馈
- run.py prototype 输出新增 outputs/prototype/annual_balance.json
- 验证：python -B -X utf8 run.py test（填写本次真实结果）
```

前缀用：`p1:`（问题一轮）、`docs:`、`fix:`、`chore:`、`data:`。**不要**提交 `update`、`修改`、`wip`、`111` 这类信息。

一次提交围绕一个明确目的。小步提交、控制改动范围和明确接口都能减少合并与评审的负担。

### 4.3 方案边界与完整交付

三个人做同一个问题，可以在各自分支修改同一批文件（`run.py`、`README.md`、`workflow/*.json` 等）。每个候选方案都应能独立运行和验收：

> **方案说明和实验产物区分路径；代码沿用现有工程结构，必要入口、配置、测试与说明在候选 PR 中一起交齐。**

具体落地：

| 类型 | 路径约定 | 谁改 |
|---|---|---|
| 方案正文 | `docs/solutions/p1-yx.md`、`docs/solutions/p1-mmj.md` | 各自新建，互不覆盖 |
| 代码模块与测试 | 沿用现有模块；确有需要时新增 | 各自在自己的分支修改 |
| 实验产物 | `outputs/prototype/p1_yx_*.json` | 各自新建，文件名带自己名字 |
| 共享入口（`run.py`、`README.md`、编号文档、`workflow/*.json`） | 仅改本轮必要部分 | 各自随候选 PR 交付，评审完整集成后的行为 |

不要为了区分作者而复制三套正式模块。候选方案择一合并；补强方案从合并后的主干重新提取增量。冲突出现时按 §6 处理，不能用遗漏必要集成的方式换取“没有冲突”。

### 4.4 不许提交的东西

- `.venv/`、`.venv-workbench/`、`__pycache__/`、`.pytest_cache/`（`.gitignore` 已挡，别用 `git add -f` 绕过）
- `tmp/` 下的临时产物（已忽略）
- 任何 `sk-...`、`AIza...`、`.env`、`credentials*.json` —— 不应提交到版本历史。
- 单个 ≥50 MB 的新文件（GitHub 会警告/拒收；需要用大文件就先问全组）
- 个人本机的绝对路径、本机配置

提交前 30 秒自检：

```powershell
git status -sb            # 看清单
git diff --stat           # 看统计，确认没混进 outputs 里的无关产物
git diff                  # 看内容，确认没有密钥、没有别人机器路径
git diff --cached         # 同时检查已暂存、将进入本次提交的内容
git ls-files -s | Select-String '\.venv'   # 空输出最好
```

---

## 5. 每轮标准流程（Round Protocol）

一轮 = 一个问题，三人同题并行。**当前候选通过验收并合并后，三人停止已被覆盖的开发，从新的共同基线进入下一轮。** 尚未完成的可选补强单独登记；若下一轮依赖它，应先合并并重新锁定基线。

### 5.0 阶段 0：锁定起跑线与验收（主持人）

**首次 P0 的顺序**：先准备协作文档和本轮开工单 → 通过独立的准备分支/PR 评审入库 → 验证合并后的 `main` → 把该提交的完整 SHA 和锁定状态写入本轮 Issue → 三人从同一 SHA 开工。准备 PR 仍遵守两人批准、非作者合并；不能以“只是初始化流程”为由直接推 `main`。后续轮次已有规程时，直接按下面步骤冻结新的本轮输入与验收即可。

尚未发布的文档、仅在本机存在的输入、待合并的准备 PR 都不能算已共享的起跑条件。可以先开准备状态的 Issue，记录当前远端参考提交、完整任务和待办，但此时 `base SHA` 应写“待锁定”。准备资料合并后，由主持人在同一 Issue 正文补上正式 base，无需新开重复 Issue；若需调整已锁定的 base 或共同输入，先保留旧约定与变更原因并通知三人重新确认。

主持人（建议轮值：yx → mmj → lb）做三件事：

1. 确认 `main` 是干净且最新的：

```powershell
git switch main
git pull --ff-only origin main
python -B -X utf8 run.py test
git rev-parse HEAD      # 验证通过后记下完整 SHA，全组本轮唯一基点
```

执行前先检查并妥善保存当前工作，不携带未提交内容切换 `main`。若 `main` 已在另一个 worktree 检出，在那个目录执行，或另建独立目录检查 `origin/main`；不要强行解除占用。核对完当前主干才确定本轮基线，不以本文示例中的任意提交代替。

2. 在 GitHub 开一个 Issue，标题 `P1: <问题一句话>`，正文粘贴：

```markdown
## 本轮问题
<要解决什么，哪些功能必须完成，哪些明确不做>

## 共同输入与验收
- 对应 final 的步骤：
- 数据范围、年份、单位及准入限制：
- 共同配置、随机种子清单（如适用）：
- 必需交付物、关键约束、通过条件：
- 从本轮输入生成结果的运行命令：

## 起跑线
状态：准备中 / 已锁定（只能二选一；准备中不得正式开工）
base commit: <上一步的 SHA>
开工时间: YYYY-MM-DD HH:MM
截止时间: YYYY-MM-DD HH:MM（按任务约定，不固定为 24h）
评审响应时间: <三人约定>

## 参与者分支
- [ ] p1/yx
- [ ] p1/mmj
- [ ] p1/lb

## 验收门槛（全组一致）
- python -B -X utf8 run.py test   通过
- python -B -X utf8 run.py audit  通过
- python -B -X utf8 scripts/scan_google_keys.py  无命中
- 结论可溯源到 outputs/ 下的实际产物文件
```

3. 在群里 @ 全员，贴出 base SHA。

> **为什么要锁 SHA？** 三人如果从不同 commit 出发，diff 里会混进别人的改动，评审时根本分不清谁做了什么。锁死 SHA 是全部协作纪律的地基。

### 5.1 阶段 1：各自开发（三人并行）

```powershell
# 从同一条起跑线切自己的分支（注意：用 SHA，不用 main，防止 main 已被别人推进）
git fetch origin
git switch -c p1/yx <base-SHA>

# 开发……每做完一小块就提交
git add src/energy_model/annual_balance.py docs/solutions/p1-yx.md
git commit -m 'p1: 年度燃料账本打通连续 SOC'

# 尽早推上去（半成品也推，用 Draft PR 的思路：让队友看到你在哪个方向）
git push -u origin p1/yx
```

开发期纪律：

- 开工、有人通知提 PR、准备提 PR 时 `git fetch origin`；不按固定两小时等待。
- 同一轮从共同基线开发；如果主干实际有更新，提 PR 前按 §6.2 同步并重新验证。普通 merge 可以使用，不把 rebase 和强推当作日常必做步骤。
- 卡住了就在 Issue 里说一句“我这个方向可能走不通，原因是 X”，**这比最后交一个坏方案有价值**。
- 到截止时间仍未自检通过 → 主动在 Issue 里标记“本轮放弃”，不要拖着不提 PR 也不说话。

### 5.2 阶段 2：提 PR（先完成者）

先完成且自检通过的人先提 PR，获得优先评审。无需等另外两套方案都完成；如果同时有多个候选，就按就绪顺序检查，采用最先获得三人认可且满足验收的方案。

步骤：

1. 本地自检（这就是 PR 描述里要贴的证据）：

```powershell
git fetch origin
git branch --show-current      # 确认在自己的方案分支
git merge origin/main          # 没有新主干提交时会提示 Already up to date；冲突处理见 §6.2
python -B -X utf8 run.py test
python -B -X utf8 run.py audit
python -B -X utf8 scripts/scan_google_keys.py
# 再运行本轮 Issue 指定的功能/仿真入口，并检查关键结果
git diff origin/main...HEAD --stat
git status -sb
git push                       # 本分支首次推送用 git push -u origin p1/yx
```

自检会更新部分 `outputs/validation/` 文件；确认哪些是本轮需要保存的证据，必要时精确暂存并提交后再 push。提交前后检查差异；不要把未提交的实现、旧结果或本机偶然存在的输入当作 PR 的成果。

2. GitHub 网页：`Compare & pull request`，base 选 `main`，compare 选 `p1/yx`。
   - 标题：`[P1][方案A] yx: 一句话说清方案核心`
   - 先建 **Draft**（草稿），自检贴完再点 `Ready for review`。
   - 描述用 §12.1 的模板（必须写：做了什么、为什么这么选、怎么验证、改了哪些文件、已知风险）。
   - 关联 Issue：正文写 `Refs #<issue号>`（**不要写 `Closes`**，因为这一轮未必要合并它）。

3. 在 Issue 里回一条：`PR #12 已就绪，请 @mmj @lb 评审，本轮我的结论是 X。`

> 没有 `gh` CLI 也没关系，全部操作都能在网页完成。想用命令行以后装 `gh` 即可。

### 5.3 阶段 3：交叉评审（另外两人，硬性要求）

另外两人都要给出针对具体提交 SHA 的结论。至少一人独立复跑全部基础检查和本轮关键入口，另一人重点核对方法、数据口径、关键约束与结果证据，并按疑点追加验证；重大模型或数据口径变更由两人分别核验。无需让两人机械重复整套耗时实验。

下面是 mmj 评审 yx 的示例：在当前开发目录执行，另建独立评审目录。另一位评审人换一个目录名。

```powershell
git fetch origin
$reviewSha = git rev-parse origin/p1/yx
git worktree add --detach '../A题-review-p1-yx-by-mmj' $reviewSha
Push-Location -LiteralPath '../A题-review-p1-yx-by-mmj'
git rev-parse HEAD                  # 将这个 SHA 写进评审记录
# 首次使用评审目录时，先按 docs/RUNNING.md 配置运行环境
python -B -X utf8 run.py test
python -B -X utf8 run.py audit
python -B -X utf8 scripts/scan_google_keys.py
# 运行本轮 Issue 指定的功能/仿真入口；纯文档改动核对内容和命令即可
git diff origin/main...HEAD --stat
git status --short
Pop-Location                       # 回到原开发目录，原分支和文件未被切换
```

上述目录名只是示例，可按本机可写位置调整；每位评审人用自己的目录。`git switch --detach` 仍会替换当前工作目录的文件；只有另建 clone/worktree 才能隔离开发与评审。worktree 不复制未跟踪的虚拟环境或本地输入，应按运行指南准备，不能因缺本机文件而篡改准入条件。评审目录可以暂留；删除前先保存必要证据并检查其中改动，不用 `--force` 清理。作者更新提交后，评审目录仍是旧快照，须重新检出最新 SHA 并复核；不要拿旧目录的运行结果批准新提交。

然后按 §12.2 在 PR 里留意见，注明提交 SHA、实际执行的检查和证据。未经运行的部分明确写“未复跑”，不能由 AI 补写成功记录。

四种评审结论（在 PR 评论第一行写清楚）：

| 结论 | 含义 | 后续动作 |
|---|---|---|
| 认可 | 已满足本轮验收 | Approve；三人认可并合并后停止重复开发 |
| 需修改 | 必需功能、正确性或关键验证尚有缺口 | Request changes；在当前 PR 修复后复核 |
| 可补强 | 当前已可验收，但另有明确增量价值 | 可 Approve；合并后按 §5.5 另提补强 PR |
| 另起 | 当前方向存在难以局部修复的问题 | 给出证据，转评其他候选；不据此否定所有方案 |

按 Issue 约定时间回应。暂时无法评审就说明预计时间；未回应不等于认可，主持人不能以超时为由跳过必要批准。

### 5.4 阶段 4：裁决与合并（主持人）

**合并条件**：提案人确认已就绪，另外两人批准当前最终提交，所有必需检查通过，没有未解决的阻塞意见。与同一份验收标准比较，不凭完成速度或代码数量裁决。

评审后如果作者更新提交，或主干已有新改动影响本方案，先同步、重跑受影响的检查，再由两位评审人确认最新提交；旧 SHA 的批准不能直接沿用。

| 评审情况 | 动作 |
|---|---|
| 两人认可，或认可当前验收并提出可选补强 | 合并候选；停止重复开发，登记可选补强 |
| 任一人指出验收缺口或正确性问题 | 先修当前 PR，再复核；不先合并再补必需功能 |
| 当前候选被否决 | 评审另外的候选，或调整当前方案；不等于三个方案都不合格 |
| 所有已提交候选经核验都不满足要求 | 记录未解决的具体缺口，继续本轮或经三人同意调整范围，不硬合并 |

**合并操作**（主持人，网页上做即可）：

1. PR 页面点 `Squash and merge`，合并信息用 PR 标题 + 关键结论。
2. 合并后立刻本地同步并验证主干：

```powershell
git switch main
git pull --ff-only origin main
python -B -X utf8 run.py test        # main 必须是绿的
git log --oneline -3
```

3. 给落选分支打 tag 并删远端分支（保留证据，不留垃圾）：

```powershell
git tag -a alt/p1-mmj -m '第1轮备选：xxx 未合并' origin/p1/mmj
git push origin alt/p1-mmj
git push origin --delete p1/mmj        # 可选，也可先留着
```

4. 三人停止已被合并方案覆盖的开发，关闭重复 PR，保存备选价值；记录 §5.6 的结论后关闭 Issue。没有可用成果的分支不要求为了留档而提交空内容。

> **不许自己合并自己的 PR。** 三人小团队里最容易被忽略的规则：提案人只能改、只能解释，点合并的必须是主持人（或另一位评审人）。

### 5.5 阶段 5：补强 PR 怎么提（“我的方案能补全它”）

这是你最初设想里最关键的一环，也是最容易做错的一环。

补强先说清：当前已合并方案缺少什么、这一点是否值得增加、怎样验证改善。若缺口属于当前验收的必需项，应在原 PR 合并前补齐。

从合并后的主干开新分支，只带入有价值的增量。不要把另一套完整实现整体覆盖到主干；一般优先重新应用少量必要修改。

```powershell
# 1. 主干已经包含别人的方案了，先同步
git fetch origin
git switch -c p1/mmj-supplement origin/main

# 2. 查看旧方案中与补强有关的具体文件（差异用于阅读，不能整份直接套用）
git diff origin/main p1/mmj -- src/energy_model/

# 3. 在新分支只实现已约定的补强，包含必要入口、配置、测试与说明

# 4. 验证后精确暂存本次文件，检查暂存差异并提交，再推送
python -B -X utf8 run.py test
python -B -X utf8 run.py audit
python -B -X utf8 scripts/scan_google_keys.py
# 再运行本次补强对应的入口；git add <本次文件> 后执行以下两行
git diff --cached
git commit -m 'p1: 补充方案A的具体功能'
git push -u origin p1/mmj-supplement
```

分支名已存在时，小写 `-c` 会拒绝创建；检查原分支后换新名字，不用大写 `-C` 覆盖它。squash 合并会生成新的提交，所以 `origin/main..旧分支` 中列出的 commit 不等于“尚未合入的功能”。只有确认某个旧 commit 独立且内容确为所需增量时，才考虑 `cherry-pick`，之后仍需检查最终差异并验证。

然后在网页开 PR，标题写 `[P1][补强] mmj: 在方案A基础上补 X`，正文写清：

- 方案A 里哪一点不足（引用它的文件/行）
- 我补了什么（自己的文件路径）
- 补完之后验证结果的变化（跑出来的数字，必须能溯源到 `outputs/` 下的文件）
- 如实说明对已有结论的影响；若新证据改变结论，同步修正，不能为了保留旧说法而隐瞒变化

补强 PR 仍由另外两人批准最终提交。检查范围可以按改动缩小，但基础门禁和本次行为验证不能因“只是补强”而省略。

> 对已经由 AI 完成的整套备选方案，只提取能说明增量价值的部分。已有完整代码不构成必须合入的理由。

### 5.6 阶段 6：留痕并进入下一轮

每轮结束，主持人在 Issue 关闭前把结论追加到 `docs/ROUND_LOG.md`（§12.3），内容至少包含：

- 本轮问题、起跑线 SHA、参与分支
- 最终合并的 PR 号、合并后的 commit
- 被放弃/挂起的方案及一句话原因
- 学到的教训（下次要避免什么）

记录几行即可，不要求另写长报告；注明“本轮验收已满足、停止重复实现”，以及哪些补强延期、是否影响下一轮基线，再进入下一题。

---

## 6. 冲突、同步与变基

### 6.1 冲突是什么、什么时候出现

冲突常见于同一文件的相邻内容被分别修改，也可能来自删除、重命名等操作。发现冲突时比较双方意图，再验证合并后的行为，不按“保留我的全部内容”处理。

冲突信号：

```text
Auto-merging docs/02_model_design.md
CONFLICT (content): Merge conflict in docs/02_model_design.md
Automatic merge failed; fix conflicts and then commit the result.
```

冲突文件里会出现：

```text
<<<<<<< HEAD
我方这一段
=======
对方那一段
>>>>>>> origin/main
```

### 6.2 同步主干：默认 merge，rebase 为进阶选项

同一轮主干没有更新时，无需反复同步。主干更新后，在自己的方案分支、确认没有未保存的改动时执行：

```powershell
git fetch origin
git switch p1/yx
git status -sb
git merge origin/main
```

若有冲突，先编辑冲突文件、保留正确内容，再 `git add <已解决的文件>` 和 `git commit` 完成合并；若要退出本次合并，用 `git merge --abort`。完成后重跑相关检查，再普通 `git push`。使用 merge 不会强迫你改写已推送的提交。

已经熟悉 Git、且确认没有队友基于该分支继续开发时，可以在自己的方案分支改用 `git rebase origin/main`。遇到冲突时解决后用 `git rebase --continue`，放弃则用 `git rebase --abort`。如果改写了已推送的提交，才需要：

```powershell
git push --force-with-lease
```

`--force-with-lease` 会校验远端引用，但不是所有误覆盖的保险。它只限本人分支、已核对远端状态的历史改写；不作为本流程的默认命令。**禁止**对 `main` 或别人的分支 rebase/强推。merge 或 rebase 后都应重新验证，并让评审人确认最终提交。

### 6.3 接手别人的改动 / 想试别人的版本

```powershell
git fetch origin
# 新建独立目录，保留当前开发工作区；具体运行与证据记录见 §5.3
git worktree add --detach '../A题-review-p1-mmj-by-yx' origin/p1/mmj

# 已核对内容，只想搬入某个独立 commit 时才用；在自己的开发分支执行
git cherry-pick <sha>
```

### 6.4 换行符（Windows 特有坑）

先检查当前版本是否已有 `.gitattributes`；有则阅读其约定。不同机器的 Git 和编辑器设置可能不同；例如 `core.autocrlf=true` 时，签出和暂存会对识别为文本的文件做换行转换，可能出现以下提示：

```text
warning: in the working copy of '<文件>', LF will be replaced by CRLF ...
```

换行转换与编辑器保存方式不一致时，可能产生大量与本轮无关的差异。不能仅凭提示断定文件损坏，也不能靠批量覆盖来消除提示。

当前工程按文件字节核验原件；每人先在本地设置并检查实际差异，设置不会自动恢复已改变的字节：

```powershell
git config --local core.autocrlf false
git config --show-origin --get-all core.autocrlf   # 确认来源：local 覆盖掉 system 的 true
```

如果确实要统一下来（建议时机：某次专门的小 PR），加一个 `.gitattributes`：

```text
* text=auto eol=lf
*.ps1 text eol=crlf
*.bat text eol=crlf
*.xlsx binary
*.pdf binary
*.doc binary
*.docx binary
```

上述规则仅作示例。不要对官方原件、`只读工作区/` 和有哈希契约的数据盲目规范化。新增属性或执行重新规范化前要检查影响，并**单独一个 PR、单独一次评审**，不要混在方案 PR 里。

### 6.5 含较多研究原件的仓库：实操注意

- 首次 clone 和新 worktree 签出需要时间与磁盘空间；worktree 共享 Git 对象库，但各有一套工作文件。
- `git status` 关注工作目录的变更，不等于每次重新传输整个仓库。
- 不要为了“干净”去 `git clean -xdf`，那会删掉 `outputs/` 里没提交的实验结果，可能就是你本轮唯一的证据。要清理用 `git clean -xdfn`（`n` = 先干跑看看）。
- 分支切换更新需要变化的文件，不会固定重写全部资料。评审仍优先用独立 worktree，以隔离分支和运行产物。

---

## 7. 常用命令速查（按场景）

所有命令默认在**自己的仓库或 worktree 根目录**执行，实际位置按 §0.2 确认，不依赖目录名称。涉及 `git switch main` 的示例只适用于工作区干净且 main 未被其他 worktree 占用的情况；否则使用已有 main 工作目录或独立评审目录。

### 7.1 每天开工

```powershell
git fetch --prune                       # 取回远端最新状态，清掉已删除的远端分支
git status -sb                          # 我在哪个分支、有没有未提交改动
```

日常查看主干用 `git log --oneline origin/main -5` 即可。需要更新自己的方案时按 §6.2 操作；不必为查看进度来回切分支。

### 7.2 开发中

```powershell
git status -sb                          # 改了哪些文件
git diff                                # 未暂存的具体改动
git add docs/solutions/p1-yx.md         # 精确添加（不要 -A）
git commit -m 'p1: 说明'                # 提交
git push                                # 推上去
git stash push -m '半成品'              # 暂时收起来
git stash pop                           # 取回来
```

### 7.3 提 PR 前自检

```powershell
git fetch origin
git branch --show-current              # 确认是自己的方案分支
git merge origin/main                  # 主干无更新时不产生新提交
python -B -X utf8 run.py test
python -B -X utf8 run.py audit
python -B -X utf8 scripts/scan_google_keys.py
# 运行本轮 Issue 的关键入口，保存必要证据并提交本轮实际改动
git diff origin/main...HEAD --stat
git diff --cached
git status -sb
git push
```

### 7.4 评审别人

```powershell
git fetch origin
$reviewSha = git rev-parse origin/p1/mmj
git worktree add --detach '../A题-review-p1-mmj-by-yx' $reviewSha
Push-Location -LiteralPath '../A题-review-p1-mmj-by-yx'
git rev-parse HEAD                      # 评审意见注明这个 SHA
# 按 docs/RUNNING.md 确认本目录可用的解释器、依赖和输入
python -B -X utf8 run.py test
python -B -X utf8 run.py audit
python -B -X utf8 scripts/scan_google_keys.py
# 运行本轮关键入口，核对数据、约束与结果
git diff origin/main...HEAD --stat
Pop-Location
```

目录已存在时先核对其 SHA 和未提交改动，或换一个目录名，不覆盖旧评审证据。详见 §5.3。

### 7.5 一轮结束后清理

```powershell
git switch main
git pull --ff-only origin main
git log --oneline -5
# 先对本地方案分支留档，确认标签推送成功，再考虑删分支
git tag -a alt/p1-yx -m '第1轮方案留档' p1/yx
git push origin alt/p1-yx
```

确认 PR 和标签已保留需要的成果后才删除本地分支。squash 合并后 `git branch -d` 可能仍提示未合并；不要直接改用 `-D`，先核对差异与标签。不确定时保留分支即可。

---

## 8. 事故手册（出事了先查这里）

**总原则：出事先别敲命令，先 `git status` 和 `git reflog` 看清现状。已推送到远端的共享历史永远用 `revert` 撤销，未推送的才用 `reset`。**

| 症状 | 判断 | 正确做法 |
|---|---|---|
| 提交到了 `main`（还没 push） | 提交先保留 | `git switch -c p1/yx` 保存到自己的分支，不推 main；主干指针的修正单独处理，不复制执行硬重置 |
| 提交到了 `main` 并且已经 push | 历史已经共享 | **不要 reset**。立刻告诉全组，用 `git revert <sha>` 生成反向提交，然后走 PR 修正 |
| `git push` 被拒：`non-fast-forward` | 本地与远端有分叉 | 先 `git fetch origin`，检查双方提交；在本人分支按 §6.2 合并所需更新，再验证和 push；不要强推覆盖 |
| push 时提示 lease 失败 | 别人动了你的分支 | 先 `git fetch` 看差异，别强推；你可能是 rebase 前忘了 fetch |
| 冲突太多想退出 | —— | `git rebase --abort` 或 `git merge --abort`，回到操作前 |
| 冲突解错了 | 先保留现场 | 退出当前操作：merge 用 `git merge --abort`，rebase 用 `git rebase --abort`；不要盲选整个 ours/theirs |
| 忘了切分支就开始改 | —— | `git stash` → `git switch -c p1/yx` → `git stash pop` |
| 改坏了想回到上次提交 | —— | `git restore <文件>`（丢弃单个文件改动） |
| 提交后想改 commit 信息 | 未推送 | `git commit --amend` |
| 想撤销最近一次提交但保留改动 | 未推送 | `git reset --soft HEAD~1` |
| 提交了不该提交的文件（未推送） | —— | `git rm --cached <文件>` 再 `--amend`；同时补 `.gitignore` |
| 提交了密钥（已推送） | **安全事故** | 立刻通知全组 → 到对应平台**吊销/轮换该 key** → 再讨论是否清历史 |
| 误删了分支 / 找不到提交 | 引用日志可能仍有记录 | `git reflog` 查找 → `git switch -c rescue <sha>`；保留期受设置和清理影响，不能保证一定可恢复 |
| 有人强推覆盖了你的分支 | —— | `git reflog`/远端备份找回；并在群里把“不许强推公共分支”再讲一次 |
| 工作区莫名多出大量改动 | 可能是换行符或脚本产物 | 用 `git diff --stat` 和具体文件差异确认，见 §6.4；先保存有效实验证据，仅对已确认可丢弃的具体文件使用 restore |
| 不确定这是不是危险操作 | —— | `git status`；或先在**另一个目录** clone 一份做实验，别在主目录试 |

**严禁清单（写在墙上）**

1. ❌ `git push --force` 到 `main` 或别人的分支
2. ❌ 在 `main` 上直接 commit / 直接改文件
3. ❌ `git reset --hard` 在别人的分支或共享分支上
4. ❌ `git add -A` / `git add .`（会带进无关产物）
5. ❌ 手工编辑 `.git/` 里的任何东西；删 `.git/index.lock` 之前先确认没有 Git 进程在跑
6. ❌ 用微信/网盘传压缩包来“同步代码”（一旦这样，Git 历史就断了，评审无从谈起）

---

## 9. 本仓库特有的硬约束（PR 合并门禁）

这些不是 Git 通用规则，是这个项目自己的、写在 `AGENTS.md` 和 `README.md` 里的约束。**评审人必须逐条核对**：

| # | 门禁 | 怎么查 |
|---|---|---|
| 1 | `python -B -X utf8 run.py test` 全部通过 | 本地跑；报告当前版本的真实数量，不照抄旧结果 |
| 2 | `python -B -X utf8 run.py audit` 通过 | 本地跑 |
| 3 | `python -B -X utf8 scripts/scan_google_keys.py` 无命中 | 本地跑 |
| 4 | 未改动 `只读工作区/`（原文路径与字节需保持不变） | `git diff --stat origin/main -- '只读工作区'` 应为空 |
| 5 | 未把 B 题/C 题的数据或方法混进来 | `git diff --name-only origin/main` 人工看路径 |
| 6 | `data/restricted/` 未被默认纳入读取逻辑 | 看 diff 里相关代码与文档 |
| 7 | 新增数据在 `data/catalog` 有登记（来源、用途、去重、冲突记录） | 看 `data/catalog/` 的 diff |
| 8 | 结论可溯源：文档里每个数字都能对应 `outputs/` 下的真实产物 | 抽查 3 个关键数字 |
| 9 | 没有把合成/合成原型结果说成“全国真实预测” | 读结论段 |
| 10 | diff 体积合理：没有引入 ≥50 MB 新文件，没有 `venv`/缓存 | `git diff --stat` |

**任一条过不了，就不合并**，在 PR 里写清哪一条、证据是什么。这是硬性规定，不是“最好这样”。

---

## 10. GitHub 侧一次性设置（约 30 分钟，管理员做）

1. **加协作者**：管理员在 Settings → Collaborators 邀请另外两人的真实 GitHub 用户名，并确认本人已接受；yx/mmj/lb 是协作代号，不假定等于账号名。个人仓库邀请 Collaborators；若将来转入组织，分配完成开发所需的 `Write` 权限即可。不要把 Contributors 统计当作权限配置。
2. **保护 main**：Settings → Branches → Add branch protection rule，分支名 `main`，勾选：
   - ✅ Require a pull request before merging（Required approvals: **2**，与另外两人认可的约定一致）
   - ✅ Dismiss stale pull request approvals when new commits are pushed
   - ✅ Require conversation resolution before merging
   - ✅ Do not allow bypassing the above settings
   - ❌ 不要勾 Allow force pushes / Allow deletions
3. **模板**（可选但强烈建议）：将 §12.1 的 PR 模板，以及 §5.0 的 Issue 正文分别存成仓库里的
   - `.github/pull_request_template.md`
   - `.github/ISSUE_TEMPLATE/round.md`
   这样每次开 PR/Issue 自动带出格式，不会有人漏写验证证据。
4. **开 Issues**：Settings → General → Features → Issues 打勾（一轮一个 Issue，是本规程的“看板”）。
5. **选择 GitHub 操作工具**：网页可完成 PR、评审与合并。Agent 使用当前环境中可用且已认证的 GitHub 工具；使用 GitHub CLI 时先核对 `gh auth status`，未配置时由本人登录。安装和登录方式按各自系统选择，不假定三人都装有 `gh`、`winget` 或浏览器自动化工具。

本流程假定三人分别使用自己的 GitHub 账号，以便另外两人正式批准 PR。集中提交也要由两位评审人各自操作账号；`--author` 只记录作者，不能代替独立评审账号。若当前仓库套餐不支持所需保护设置，仍按 PR 中的两人明确批准人工执行，不将“设置不可用”当作放宽验收的理由。

---

## 11. 如果只记住十条

1. `main` 神圣：只有 PR 合并能进，永不强推。
2. 每轮从**同一个 SHA** 切分支，分支名 `p<轮>/<人名>`。
3. 每份候选完整交付，必要入口、配置、测试随 PR 一起评审。
4. 小步提交、精确 `git add`，绝不 `git add -A`。
5. 早 push（半成品也推），让别人看得见你的方向。
6. 先提先评，三人认可并合并后停止重复开发，有价值的部分再补强。
7. 在独立目录评审，记录 SHA 和证据；必需缺口先修，可选改进另提 PR。
8. 默认 merge 同步、普通 push；rebase 与强推仅作进阶操作，保护共享历史。
9. 每轮结束必须写 `docs/ROUND_LOG.md`，落选分支打 `alt/` tag 留档。
10. 出事先 `git status` + `git reflog`，别急着敲命令。

**补充（仅在用 §3.5 集中提交模式时）**：实际操作者代队友提交时必须用 `--author='<人名> <邮箱>'` 记录真实作者；worktree 只隔离目录，仍需核对作者与提交者。两位评审人使用各自账号批准。

---

## 12. 模板（可直接复制）

### 12.1 PR 描述模板

````markdown
## 本轮
问题：P1 —— <一句话>
Issue：Refs #<issue>
起跑线 commit：<base SHA>
本次待评审 commit：<最终 SHA>

## 验收对照
- 必需交付物：<逐项对应 Issue，已完成/未完成及证据>
- 共用数据、配置与种子：<路径或标识>
- 是否满足本轮全部验收：<是/否；否则保持 Draft>

## 我做了什么
- <改动点 1：文件 + 一句话>
- <改动点 2>

## 为什么这样做（方案取舍）
<实现选择、约束及已实际比较的方案；没有运行过的对照不要写成实测>

## 怎么验证的（必须贴真实输出）
```powershell
python -B -X utf8 run.py test          # 填本次真实数量与结果
python -B -X utf8 run.py audit         # 填本次真实结果
python -B -X utf8 scripts/scan_google_keys.py   # 填本次真实结果
# 本轮功能/仿真的实际运行命令和结果
```
关键产物：`outputs/prototype/p1_yx_annual_balance.json`（关键数字：<数值>，来源：<脚本+输入>）

## 改了哪些文件
`git diff origin/main...HEAD --stat` 粘贴在此

## 已知局限 / 风险
- <例如：未覆盖 2030/2060 外推；样本仅 2015–2021>

## 自检清单
- [ ] run.py test 通过
- [ ] run.py audit 通过
- [ ] 密钥扫描无命中
- [ ] 未改动 只读工作区/
- [ ] 未混入 B/C 题内容
- [ ] 新增数据已在 data/catalog 登记
- [ ] 结果来自本次配置与代码，未复跑的部分已说明
````

### 12.2 评审清单模板（评审人贴在 PR 评论里）

```markdown
## 评审结论：认可 / 需修改 / 可补强 / 另起

评审 commit：<完整 SHA；作者更新后重新确认>
复跑环境：<机器/日期>
本次分工：<独立复跑 / 方法与数据核验 / 两者均做>
复跑结果：
- run.py test → <通过/失败，失败项>
- run.py audit → <通过/失败>
- 方案入口（如 run.py prototype）→ <输出摘要>
- 未复跑的项目及理由：<如实填写>

逐项检查：
- [ ] 结论可溯源到 outputs/ 真实产物（抽查了：<文件>）
- [ ] 未改动 只读工作区/
- [ ] 未混入 B/C 题
- [ ] data/catalog 已登记新数据
- [ ] 没有夸大结论（合成 ≠ 真实全国预测）
- [ ] diff 无无关文件、无大文件、无密钥

具体意见：
1. `docs/solutions/p1-yx.md:42` —— <问题>，建议 <改法>
2. ...

阻塞本次合并的问题：<无 / 必需修复项>
不阻塞验收的可选补强：<无 / 明确增量与验证办法>
我的处理：<批准此 SHA / 请求修改 / 提供其他候选>；三人认可并合并后关闭重复 PR、停止已覆盖的开发。
```

### 12.3 `docs/ROUND_LOG.md` 模板

```markdown
# 攻关轮次日志

## P1 · <问题标题>（YYYY-MM-DD ~ YYYY-MM-DD）
- 起跑线：`<base SHA>`
- 参与分支：p1/yx、p1/mmj、p1/lb
- 先提 PR：#12（yx，方案A）
- 评审：mmj 认可、lb 认可并建议可选补强 X（如为必需缺口，应先修再合并）
- 结果：**合并 #12**（squash → `<merge SHA>`），补强 #15 随后合并
- 验收：<关键证据与两位评审人的最终批准>
- 重复开发：<已停止；未合入方案的价值和去向>
- 可选补强：<无 / 延期项；是否影响下一轮共同基线>
- 落选：`alt/p1-mmj`、`alt/p1-lb`（原因：<一句话>）
- 教训：<下次要避免什么>

## P2 · ...
```

### 12.4 每日 30 秒状态同步（贴群里）

```text
[P1][yx] 分支 p1/yx 已 push（3 commits）
进度：年度账本打通，SOC 连续窗口还差 4h
今天计划：补 2015–2021 回算 + 跑 test
风险：附件 3 的单位口径还没确认
```

### 12.5 交给开发 Agent 的提示词

先替换尖括号中的内容。模板授权开发、commit、push 和创建 PR；只想本地开发时，将授权行改为“仅本地修改和验证，暂不 commit、push 或创建 PR”。已有明确授权仍然有效，不要求为每个 Git 命令单独确认。

```text
请先阅读仓库根目录的 AGENTS.md、README.md、只读工作区/final.md、
docs/IMPLEMENTATION_ROADMAP.md、WORKFLOW.md，以及 docs/17_git_collaboration.md。
按协作文档 §0.2 检查当前环境；按 docs/RUNNING.md 准备运行环境。

我是 <yx/mmj/lb 中的本人代号>，我的 GitHub 账号是 <账号名>。
本轮是 P<轮次>，Issue 为 <地址或编号；无法读取时附完整正文>。
三人共同的完整 base SHA 是 <完整 SHA>。
我的分支是 <p轮次/本人代号>；本次任务是 <任务、输入范围和验收要求>。

请在当前机器定位正确 clone/worktree，保留已有修改，核对分支归属后继续；
分支不存在时从指定 base 创建，不替换成当前 main，不覆盖已有分支。
三人各自完整解决同一问题，遵守 final 主线和数据约束。
允许你为本任务修改文件、运行验证、精确暂存、commit、普通 push 到我的分支，
并创建以 main 为 base 的 PR、填写真实自检证据、请求另外两人评审。
本次不授权合并 PR、直接推 main、强推或删除他人的分支。
只在关键任务信息缺失或权限确实阻碍后续时说明需要补充什么。
完成后交接分支、完整 SHA、验证结果、证据路径、PR 地址及待评审事项。
```

### 12.6 交给评审 Agent 的提示词

```text
请先按 docs/17_git_collaboration.md §0.2 阅读规则并检查环境。
我是 <评审人代号>，本轮 Issue 为 <地址或正文>，待评审 PR 为 <地址或编号>。
请保留我的开发工作区，在独立目录按 §5.3 核对 PR 当前最终完整 SHA，
检查实现、数据口径、关键约束、结果证据，并执行我承担的复现检查：
<独立复跑全部基础检查和关键入口 / 方法与数据核验及针对性验证>。

允许获取远端状态、创建独立评审目录、运行检查并写本地评审记录。
本次不授权在 GitHub 发布评论或批准，不授权修改候选分支或合并 PR。
请按 §12.2 给出“认可 / 需修改 / 可补强 / 另起”的建议与真实证据，
注明所评审的完整 SHA、未执行的检查、阻塞问题和可选补强，供我确认。
```

需要 Agent 代为发布评审时，评审人可明确补充“允许以我的已认证账号发布评论和最终评审”。每人只代表自己的认可；两位评审人须分别批准同一最终 SHA。合并另按 §5.4 的条件和实际授权执行。

---

## 附录 A：从“网盘思维”迁移过来的对照

| 你以前的网盘做法 | 换成 Git 后应该做 |
|---|---|
| 把整个 `A题` 文件夹上传覆盖 | `git add` 具体文件 → `git commit` → `git push` |
| 每天拉一次最新，谁快谁赢 | 各自分支开发，PR 评审后合并 |
| 冲突了就把对方文件覆盖掉 | 冲突要手工合并，两边内容都要看 |
| “我这版是最终版_final_v2” | 分支 + commit 历史 + tag，天然多版本 |
| 想知道谁改的 → 问人 | `git log --oneline -- <文件>`、`git blame <文件>` |
| 想回到上周的版本 | `git log` 找到 SHA → `git switch --detach <SHA>`（或建恢复分支） |
| 把实验结果也一起传上去 | 小体积结论进 `outputs/`（可溯源），大文件/临时产物不进 Git |

## 附录 B：本规程与仓库既有文档的关系

- `AGENTS.md`：仓库工程约束（只做 A 题、只读工作区不动、数据准入、不用合成结果冒充真实预测）。本规程补充“怎么用 Git 落实它”；遵守当前会话中的用户授权及适用的上层指令，不因读取本文自行扩大授权。
- `WORKFLOW.md`：F0–F7 阶段划分与验收证据要求。每轮的“问题”应能映射到某个 F 阶段。
- `docs/RUNNING.md`：环境与命令，PR 自检时按它跑。
- `docs/DATA_GUIDE.md`：新增数据的登记与去重规则，新数据类 PR 必读。
