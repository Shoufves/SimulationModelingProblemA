# 17 · 三人 Git 协作规则（A 题）

> 适用对象：yx、mmj、lb 三人共同在 A 题仓库上并行攻关。
> 目标：**三个人同时做同一个问题 → 谁先做好谁提 PR → 评审通过才合并 → 未合并的方案要么放弃、要么作为“补丁 PR”叠加**，并且任何时刻 `main` 都是可运行、可复现、可提交的状态。
>
> 本文不是 Git 教程，而是“我们这个仓库该怎么用 Git”的作业规程。第 2 章补心智模型，第 9 章是事故手册，第 12 章是可直接抄的模板。

---

## 0. 一页速查（先看这里）

**三条铁律**

1. `main` 只能通过 PR 合并进入，任何人不得直接 `git push origin main`。
2. 每轮问题开工前，三人从**同一个 commit** 切分支；分支命名 `p<轮次>/<人名>`，例如 `p1/yx`。
3. 合并前必须由**另外两人**在本地复跑验证脚本并留下评审记录；先提 PR ≠ 先赢。

**每轮五步**

| 步 | 谁 | 动作 | 产出 |
|---|---|---|---|
| 0 | 主持人（轮值） | 锁定起跑线 commit，开 Issue | Issue 里记录 base SHA |
| 1 | 三人各自 | 从 base 切分支，独立开发，早提交早 push | 三条并行分支 |
| 2 | 先完成者 | 提 Draft PR → 自检通过后转 Ready | 第一个方案 PR |
| 3 | 另外两人 | 本地 checkout 该分支，复跑脚本，留评审意见 | ✅ / ⚠️ / ❌ 结论 |
| 4 | 主持人 | 达成一致 → squash 合并；不一致 → 见 §5.3 决策矩阵 | `main` 前进一格 |
| 5 | 全体 | 写 ROUND_LOG，10 分钟内进下一个问题 | 决策留痕 |

**每天开工只记三个命令**

```powershell
cd 'D:\仿真建模资料\2026年仿真建模挑战赛赛题\A题'
git fetch --prune
git status -sb
```

---

## 1. 我们现在这个仓库的事实清单

写规则之前先把事实摆清楚，后面所有命令都基于它：

| 项 | 现状 |
|---|---|
| 真正的 Git 仓库根 | `D:\仿真建模资料\2026年仿真建模挑战赛赛题\A题`（**不是**上一层的“赛题”目录） |
| 远端 | `origin` = `git@github.com:Shoufves/SimulationModelingProblemA.git`（SSH 方式） |
| 分支 | 只有 `main`，跟踪 `origin/main` |
| 当前基线 commit | 开工前运行 `git rev-parse --short origin/main` 查询，并在本轮 Issue 中记录 |
| 已跟踪文件 | 约 1136 个，合计约 **395 MB**（最大单文件 `data/raw/batch3_scenarios/irena_power_costs_2024.pdf` ≈ 49.1 MB） |
| `.gitignore` | `__pycache__/`、`*.py[cod]`、`tmp/*`（保留 `tmp/README.md`）、`.venv-workbench/`、`.venv/`、`.pytest_cache/` |
| 无 `.gitattributes` | 换行符没有统一约定，跨系统协作时要小心（见 §7.4） |
| 仓库内规则文件 | `AGENTS.md`（工程约束）、`WORKFLOW.md`（F0–F7 阶段）、`README.md`（入口与常用命令） |
| 验证入口 | `run.py audit / test / attachments / verify / prototype / catalog / reproduce-lb`，以及 `scripts/scan_google_keys.py` |

**由此推出的三条隐含要求**

- 仓库已经很大（395 MB），所以**任何人不要往 Git 里塞新的原始大文件**（新 PDF/大 CSV 请留在本地或放共享盘，只在 `data/catalog` 里登记路径与哈希说明）。GitHub 单文件 ≥50 MB 会警告、≥100 MB 直接拒收。
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

问题在于：三人同时改同一个分支，Git 无法判断“谁改的算数”，只能报冲突或者覆盖，最后变成“谁最后 push 谁赢”，而赢的那个方案未必是最好的。

分支协作把它换成：

```text
                       ┌── p1/yx    （方案一）
origin/main ←──────────┼── p1/mmj   （方案二）
   （唯一主干）         └── p1/lb    （方案三）
        ↑
   只有“评审通过”的才允许合回来
```

**关键点：分支是免费的。** 开一个分支就是写一个 40 字节的文件，随便开。真正的成本是“三个方案要合并起来”的那一步，所以我们用 PR + 评审来控制它。

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
| repository / repo | 仓库 | 带历史的项目目录，就是 `A题` 这个文件夹（含隐藏的 `.git`） |
| clone | 克隆 | 把远端仓库完整复制到本地，**每人做一次，且只有一次** |
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

### 3.1 选择部署方式（二选一，先定下来）

**方式 A（推荐）：三人三台电脑，各自 clone 同一个 GitHub 仓库**

```powershell
cd D:\
git clone git@github.com:Shoufves/SimulationModelingProblemA.git A题-yx
```

每人本地目录可以不同名（`A题-yx`、`A题-mmj`、`A题-lb`），但**都指向同一个 origin**。

**方式 B：三人共用一台电脑（或共用同一个大目录）**

绝对不要三个人在**同一个文件夹**里敲命令 —— 工作区只有一个，A 切分支会连带把 B 的文件改掉。正确做法是用 `git worktree`：一份 `.git`，三个独立工作目录。

```powershell
cd 'D:\仿真建模资料\2026年仿真建模挑战赛赛题\A题'
git config extensions.worktreeConfig true
git worktree add ..\A题-yx -b p1/yx origin/main
git worktree add ..\A题-mmj -b p1/mmj origin/main
git worktree add ..\A题-lb -b p1/lb origin/main
```

> 注意：`worktree` 里三个目录共享同一个 `.git`，因此 `user.name` 会互相覆盖。必须给每个工作目录单独的身份：
>
> ```powershell
> cd ..\A题-yx;  git config --worktree user.name 'yx';  git config --worktree user.email 'yx@example.com'
> cd ..\A题-mmj; git config --worktree user.name 'mmj'; git config --worktree user.email 'mmj@example.com'
> cd ..\A题-lb;  git config --worktree user.name 'lb';  git config --worktree user.email 'lb@example.com'
> ```

**方式 C：三人各用自己的电脑写，但 Git 操作全集中在一个人机器上**

这是最容易变成"又退回网盘"的模式，必须额外做归因处理，详见 §3.5。

### 3.2 配置自己的身份（否则三个人都叫 Shoufves）

当前这台机器的全局身份是 `Shoufves / 3144589869@qq.com`。三人共用的话，**必须**在各自仓库里用 `--local` 覆盖，让历史里能看出是谁提交的：

```powershell
cd 'D:\...\A题-yx'
git config --local user.name  'yx'
git config --local user.email 'yx@example.com'
git config --local core.autocrlf false      # 见 §7.4，避免换行符抖出大量假改动
git config --local pull.rebase true         # 习惯：pull 用变基，避免无意义的合并提交
git config --local push.default current     # 只推自己的分支，防止误推
```

核对：

```powershell
git config --local --list
git log -1 --format='%an <%ae>'
```

### 3.3 配好 SSH 免密（只需一次）

远端是 SSH 地址（`git@github.com:...`），所以每台机器都需要一把 key 并加到自己的 GitHub 账号：

```powershell
ssh-keygen -t ed25519 -C 'yx@example.com'         # 一路回车
Get-Content $env:USERPROFILE\.ssh\id_ed25519.pub  # 复制全文
# 粘贴到 GitHub → Settings → SSH and GPG keys → New SSH key
ssh -T git@github.com                              # 出现 "Hi <用户名>! You've successfully authenticated" 即成功
```

同时，三个人都必须被加进仓库的协作者名单：**GitHub → 仓库 → Settings → Collaborators → Add people**（否则能 clone 不能 push）。

### 3.4 三条自检命令（每次换机器都跑一遍）

```powershell
git remote -v                    # 确认 origin 指向 SimulationModelingProblemA
git rev-parse --abbrev-ref HEAD  # 确认当前在自己的分支，不是 main
git status -sb                    # 确认工作区干净（没有意外改动）
```

### 3.5 Git 操作集中在一个人机器上时：作者 ≠ 提交者

**场景**：三人各在自己的电脑上写代码/文档，但所有文件汇到**一台机器**上，由同一个人执行 `git commit` / `git push`。

**先回答一个常见疑问：这台机器还要再 clone 一份吗？**

> **不需要。** `A题` 这个目录本身就是那份 clone（`origin` 已配置、`main` 已跟踪 `origin/main`）。再 clone 只会多出第二份 395 MB 的工作区，而且容易出现"我在另一份里改的"这种分裂。**一份工作区 + 三条分支**就够了（推荐用下面的做法一，一份 `.git` + 三个目录）。

**必须先理解：Git 记录两个身份**

| 字段 | 含义 | 由谁决定 |
|---|---|---|
| `author`（作者） | 真正写这段内容的人 | `user.name/user.email`，或命令行 `--author` |
| `committer`（提交者） | 敲 `git commit` 的人 | 固定是本机配置的那个人 |

默认两者相同。集中在操作机上提交时，如果不干预，三个人的所有提交都会显示成 `Shoufves` —— 几轮下来没人分得清哪个方案是谁做的，评审判断失去依据，`git log`/`git blame` 也彻底失效。**这不是洁癖问题，而是协作能否成立的问题。**

**做法一（推荐）：操作机上用 worktree 分三个工作区，各自带身份**

```powershell
cd 'D:\仿真建模资料\2026年仿真建模挑战赛赛题\A题'
git config extensions.worktreeConfig true
git worktree add ..\A题-yx  -b p1/yx  origin/main
git worktree add ..\A题-mmj -b p1/mmj origin/main
git worktree add ..\A题-lb  -b p1/lb  origin/main

cd ..\A题-yx;  git config --worktree user.name 'yx';  git config --worktree user.email 'yx@example.com'
cd ..\A题-mmj; git config --worktree user.name 'mmj'; git config --worktree user.email 'mmj@example.com'
cd ..\A题-lb;  git config --worktree user.name 'lb';  git config --worktree user.email 'lb@example.com'
```

好处：①身份天然正确；②谁的文件进谁的目录，不会串分支；③**切换分支不用来回换出 395 MB 的文件**（每个 worktree 是独立工作区）。

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
# 期望：作者=yx  提交者=Shoufves
```

作者写错的补救（仅限未推送时）：`git commit --amend --author='yx <yx@example.com>'`。

**这种模式必须额外遵守三条**

1. **一人一分支，绝不串。** 绝不把 yx 的文件提交到 `p1/mmj` 分支上。串一次，PR 的 diff 就归错人，评审结论也就不成立。
2. **中转文件放 `tmp/incoming/<人名>/`**（`tmp/` 已被 `.gitignore` 忽略）。队友把文件传过来先落这里，操作者确认内容后再搬进正式路径 —— 防止把压缩包、临时图、队友本机绝对路径、`.venv` 一起提交上去。
3. **评审环节绝不能省。** 提交权集中在一个人手上，最容易退化成"一个人说了算"。另外两人仍然必须在 GitHub PR 页面留下 ✅/⚠️/❌ 结论 —— 这是三人协作**唯一**的共识证据，比任何口头约定都硬。

**长期建议**：这个模式跑 1–2 轮可以接受，但 `committer` 永远是同一个人、队友看不到自己的提交、出问题时也说不清"是谁把哪个文件改坏的"。等流程跑顺，让另两人各自装一次 Git + 生成一把 SSH key（各约 10 分钟，见 §3.3），切成 §3.1 方式 A，协作质量会明显提升。

---

## 4. 分支、提交与文件约定

### 4.1 分支规范

| 分支 | 用途 | 谁能写 | 是否可以强推 |
|---|---|---|---|
| `main` | 唯一主干，永远可运行 | **只有 PR 合并** | ❌ 永远不行 |
| `p1/yx`、`p1/mmj`、`p1/lb` | 第 1 个问题的三个并行方案 | 各自本人 | ✅ 可以（用 `--force-with-lease`） |
| `p1/mmj-supplement` | 第 1 轮的“补强 PR”分支 | 本人 | ✅ 可以 |
| `fix/...`、`docs/...` | 与具体问题无关的杂项修复 | 任何人 | ✅ 可以 |

规则：

- 分支名一律 `p<轮次>/<人名>`，轮次从 1 开始。**分支名里不要写方案名**（方案会变，分支名不好改）。
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
- 验证：python -B -X utf8 run.py test（128 项通过）
```

前缀用：`p1:`（问题一轮）、`docs:`、`fix:`、`chore:`、`data:`。**不要**提交 `update`、`修改`、`wip`、`111` 这类信息。

一次提交只做一件事。三人并行时，**小步提交是减少冲突的唯一有效手段**。

### 4.3 最重要的一条防冲突规则：文件隔离

三个人做同一个问题，几乎一定会改到同一批文件（`run.py`、`README.md`、`docs/02_model_design.md`……），这时 Git 冲突会淹没你。所以约定：

> **每个方案写进自己新建的文件；共享文件只在“合并那一刻”由合并者改。**

具体落地：

| 类型 | 路径约定 | 谁改 |
|---|---|---|
| 方案正文 | `docs/solutions/p1-yx.md`、`docs/solutions/p1-mmj.md` | 各自新建，互不覆盖 |
| 新增代码模块 | `src/energy_model/<方案专属新文件>.py` | 各自新建 |
| 实验产物 | `outputs/prototype/p1_yx_*.json` | 各自新建，文件名带自己名字 |
| 共享入口（`run.py`、`README.md`、`docs/` 下的编号文档、`workflow/*.json`） | —— | **只有合并后的赢家改**，且在自己的 PR 里改一次 |

这样三条分支的 diff 几乎不重叠，PR 合并时冲突接近零；落选分支也能干净地保留下来当证据。

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
git ls-files -s | Select-String '\.venv'   # 空输出最好
```

---

## 5. 每轮标准流程（Round Protocol）

一轮 = 一个问题。**一轮只解决一个问题，绝不并行开两轮。**

### 5.0 阶段 0：锁定起跑线（主持人，5 分钟）

主持人（建议轮值：yx → mmj → lb）做三件事：

1. 确认 `main` 是干净且最新的：

```powershell
git switch main
git pull --ff-only origin main
git rev-parse HEAD      # ← 记下这个 SHA，全组本轮唯一基点
python -B -X utf8 run.py test
```

2. 在 GitHub 开一个 Issue，标题 `P1: <问题一句话>`，正文粘贴：

```markdown
## 本轮问题
<要解决什么，验收标准是什么>

## 起跑线
base commit: <上一步的 SHA>
开工时间: YYYY-MM-DD HH:MM
截止时间: YYYY-MM-DD HH:MM（建议 24h）

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

- **每 2 小时** `git fetch origin` 一次，看一眼队友分支动向（`git log --oneline origin/p1/mmj -5`）。
- 绝不 `git merge origin/main` 到自己的方案分支里“顺手同步” —— 那会把主干的历史混进你的 diff。要同步就 rebase（§6.2），而且只在**合并前**做一次。
- 卡住了就在 Issue 里说一句“我这个方向可能走不通，原因是 X”，**这比最后交一个坏方案有价值**。
- 到截止时间仍未自检通过 → 主动在 Issue 里标记“本轮放弃”，不要拖着不提 PR 也不说话。

### 5.2 阶段 2：提 PR（先完成者）

先完成的人提 PR。**先提 PR 不等于赢**，只是抢占“优先评审权”。

步骤：

1. 本地自检（这就是 PR 描述里要贴的证据）：

```powershell
git fetch origin
git rebase origin/main          # 把自己的提交搬到最新主干上（先做，冲突早暴露）
python -B -X utf8 run.py test
python -B -X utf8 run.py audit
python -B -X utf8 scripts/scan_google_keys.py
git push --force-with-lease
```

2. GitHub 网页：`Compare & pull request`，base 选 `main`，compare 选 `p1/yx`。
   - 标题：`[P1][方案A] yx: 一句话说清方案核心`
   - 先建 **Draft**（草稿），自检贴完再点 `Ready for review`。
   - 描述用 §12.1 的模板（必须写：做了什么、为什么这么选、怎么验证、改了哪些文件、已知风险）。
   - 关联 Issue：正文写 `Refs #<issue号>`（**不要写 `Closes`**，因为这一轮未必要合并它）。

3. 在 Issue 里回一条：`PR #12 已就绪，请 @mmj @lb 评审，本轮我的结论是 X。`

> 没有 `gh` CLI 也没关系，全部操作都能在网页完成。想用命令行以后装 `gh` 即可。

### 5.3 阶段 3：交叉评审（另外两人，硬性要求）

**评审不是点个赞。** 每个评审人必须：

```powershell
git fetch origin
git switch --detach origin/p1/yx      # 在独立位置检出对方分支（不动自己的工作区）
python -B -X utf8 run.py test
python -B -X utf8 run.py audit
python -B -X utf8 run.py prototype    # 或该方案对应的入口
git switch -                          # 回到自己的工作区
```

然后按 §12.2 的检查清单在 PR 里留意见。意见必须**给证据**（哪一行、哪个文件、哪个输出数字不对），不许只说“感觉不太行”。

三种评审结论（在 PR 评论第一行写清楚）：

| 结论 | 含义 | 后续动作 |
|---|---|---|
| ✅ 采纳 | 这个方案能解决问题，我不需要再争 | 我的 PR 关闭，分支打 tag `alt/p1-<我>` |
| ⚠️ 补强 | 方向对，但缺 X（我的分支正好补 X） | 我按 §5.5 提**补强 PR**，叠在它后面 |
| ❌ 另起 | 方案有硬伤（说明：数据不可溯源 / 违反 AGENTS.md / 结论不成立） | 我继续推自己的 PR，并写明差异点 |

评审时限：**24 小时内必须回应**（可以只回“⏳ 我在看，明天中午前给结论”）。超时不回应视为弃权，由主持人裁决。

### 5.4 阶段 4：裁决与合并（主持人）

**决策矩阵**（三人：提案人 P，另两人 A、B）

| A 的意见 | B 的意见 | 动作 |
|---|---|---|
| ✅ | ✅ | **合并 P**。squash merge，删除分支（先打 tag 留档） |
| ✅ | ⚠️ | 先合并 P，再由 B 提补强 PR（一个小 PR，快速评审后合并） |
| ✅ | ❌ | 主持人裁决：让 B 说明硬伤是否成立。成立 → P 的 PR 挂起，B 的 PR 走评审；不成立 → 合并 P |
| ⚠️ | ⚠️ | 提案人先按两条意见补完（仍在同一个 PR 上追加提交），再评一轮 |
| ❌ | ❌ | 三个方案都不合格 → 本轮标记“未解决”，写成 `docs/history/p1_failure.md` 记录踩坑，重开一轮（不硬合并） |

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

4. 在 Issue 里写结论，然后 `Close issue`。

> **不许自己合并自己的 PR。** 三人小团队里最容易被忽略的规则：提案人只能改、只能解释，点合并的必须是主持人（或另一位评审人）。

### 5.5 阶段 5：补强 PR 怎么提（“我的方案能补全它”）

这是你最初设想里最关键的一环，也是最容易做错的一环。

**错误做法**：在旧分支上 `git merge origin/main`，然后提一个包含“全部旧方案 + 主干”的巨型 PR。评审人根本看不出你补了什么，而且 squash 合并后必然冲突。

**正确做法**：从新主干上开一个**全新分支**，只摘取“差额”那几个 commit。

```powershell
# 1. 主干已经包含别人的方案了，先同步
git fetch origin
git switch -C p1/mmj-supplement origin/main

# 2. 看自己旧分支上有哪些 commit 是主干没有的
git log --oneline origin/main..p1/mmj

# 3. 只摘取真正是“补充”的 commit（跳过已被主干覆盖的部分）
git cherry-pick <commit1> <commit2>

# 4. 如果某些改动其实主干里已经有了，用交互式方式把它们从 commit 里剔除
#    （或者直接新写：往往比重放旧 commit 更快、更干净）
python -B -X utf8 run.py test
git push -u origin p1/mmj-supplement
```

然后在网页开 PR，标题写 `[P1][补强] mmj: 在方案A基础上补 X`，正文写清：

- 方案A 里哪一点不足（引用它的文件/行）
- 我补了什么（自己的文件路径）
- 补完之后验证结果的变化（跑出来的数字，必须能溯源到 `outputs/` 下的文件）
- **不改**方案A已有的结论，只做增量

补强 PR 的评审可以放宽：**一人 Approve 即可合并**（因为主体方案已经被严格评审过），但合并后仍要 `run.py test` 全绿。

> 实用提示：因为 §4.3 要求“各自新文件”，补强 PR 的 diff 通常就是 `新增 1 个文件 + 改 1 个入口`，评审 5 分钟就能过。这就是文件隔离带来的红利。

### 5.6 阶段 6：留痕并进入下一轮

每轮结束，主持人在 Issue 关闭前把结论追加到 `docs/ROUND_LOG.md`（§12.3），内容至少包含：

- 本轮问题、起跑线 SHA、参与分支
- 最终合并的 PR 号、合并后的 commit
- 被放弃/挂起的方案及一句话原因
- 学到的教训（下次要避免什么）

然后才开下一轮 Issue。**没有留痕就不算一轮结束** —— 三周后没人记得当初为什么否掉某个方案，这个记录是唯一答案。

---

## 6. 冲突、同步与变基

### 6.1 冲突是什么、什么时候出现

冲突只在**同一文件的同几行被两边都改过**时出现。它不是“操作失误”，是不可避免的；我们的策略是**降低概率**（文件隔离）而不是消灭它。

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

### 6.2 同步主干的唯一正确姿势：rebase

```powershell
git fetch origin
git switch p1/yx
git rebase origin/main
# 若冲突：手工编辑文件 → 删掉 <<<<<<< ======= >>>>>>> 标记，保留正确内容
git add <冲突文件>
git rebase --continue           # 逐个小步走完
git rebase --abort              # 想放弃，一键回到 rebase 之前
```

rebase 完成后，因为 commit SHA 变了，必须强推自己的分支（**只有自己的分支可以**）：

```powershell
git push --force-with-lease
# 为什么不直接 --force？--force-with-lease 会在远端有你不知道的新提交时拒绝执行，救你一命
```

**禁止**对 `main` 或别人的分支 rebase/强推。

### 6.3 接手别人的改动 / 想试别人的版本

```powershell
# 只想看/跑别人的分支，不想建本地分支 → 检出到游离 HEAD
git switch --detach origin/p1/mmj
python -B -X utf8 run.py test
git switch -            # 回来

# 只想把别人某个 commit 的改动搬到自己分支
git cherry-pick <sha>
```

### 6.4 换行符（Windows 特有坑）

仓库没有 `.gitattributes`。**实测**：当前工作区所有文件（`README.md`、`run.py`、`docs/*.md`）都是 **LF** 换行，索引里的 blob 也是 LF；但**系统级**配置 `core.autocrlf=true`（来源 `D:/Git/etc/gitconfig`），Git 会在下次签出时把这些文件转成 CRLF，并提示：

```text
warning: in the working copy of '<文件>', LF will be replaced by CRLF ...
```

这就是典型的“我什么都没改，`git status` 却显示几十个文件被修改”的来源：只要某人的编辑器按 LF 保存，而 Git 期望 CRLF，两边就会互相抖。

对策（每人本地设一次，与当前磁盘现状一致，设完 `git status` 应当变干净）：

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

⚠️ 加 `.gitattributes` 会导致一次大规模的“换行符规范化”提交，**必须单独一个 PR、单独一次评审**，不要混在方案 PR 里。

### 6.5 仓库很大（395 MB）带来的实操注意

- 首次 clone 会比较慢；之后只要不反复 `git clean -xdf` 就还好。
- `git status` 慢是正常的（1 千多个文件 + 大体积），别慌。
- 不要为了“干净”去 `git clean -xdf`，那会删掉 `outputs/` 里没提交的实验结果，可能就是你本轮唯一的证据。要清理用 `git clean -xdfn`（`n` = 先干跑看看）。
- 别频繁整体 `switch`（每次切换要换出/换入几百 MB）。评审时优先用 `--detach` 只读检视。

---

## 7. 常用命令速查（按场景）

所有命令默认在**自己的仓库目录**执行，例如 `cd 'D:\...\A题-yx'`。

### 7.1 每天开工

```powershell
git fetch --prune                       # 取回远端最新状态，清掉已删除的远端分支
git status -sb                          # 我在哪个分支、有没有未提交改动
git switch main; git pull --ff-only     # 看一眼主干（可选）
git switch p1/yx                        # 回到自己的分支
```

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
git rebase origin/main
python -B -X utf8 run.py test
python -B -X utf8 run.py audit
python -B -X utf8 scripts/scan_google_keys.py
git diff --stat origin/main             # 确认改动范围合理
git push --force-with-lease
```

### 7.4 评审别人

```powershell
git fetch origin
git switch --detach origin/p1/mmj
python -B -X utf8 run.py test
git diff main...origin/p1/mmj --stat    # 重点看改了哪些文件
git log --oneline origin/main..origin/p1/mmj
git switch -
```

### 7.5 一轮结束后清理

```powershell
git switch main
git pull --ff-only origin main
git log --oneline -5
git branch -D p1/yx                     # 旧分支已合并/已打 tag，可以删本地
git tag -a alt/p1-yx -m '留档' origin/p1/yx; git push origin alt/p1-yx
```

---

## 8. 事故手册（出事了先查这里）

**总原则：出事先别敲命令，先 `git status` 和 `git reflog` 看清现状。已推送到远端的共享历史永远用 `revert` 撤销，未推送的才用 `reset`。**

| 症状 | 判断 | 正确做法 |
|---|---|---|
| 提交到了 `main`（还没 push） | 本地可以随便改 | `git switch -c p1/yx`（把提交带过去），再 `git switch main; git reset --hard origin/main` |
| 提交到了 `main` 并且已经 push | 历史已经共享 | **不要 reset**。立刻告诉全组，用 `git revert <sha>` 生成反向提交，然后走 PR 修正 |
| `git push` 被拒：`non-fast-forward` | 远端比本地新 | `git fetch origin && git rebase origin/<分支>` 后再 push；**不要 `--force`** |
| push 时提示 lease 失败 | 别人动了你的分支 | 先 `git fetch` 看差异，别强推；你可能是 rebase 前忘了 fetch |
| 冲突太多想退出 | —— | `git rebase --abort` 或 `git merge --abort`，回到操作前 |
| 冲突解错了 | —— | `git checkout --ours <文件>` / `--theirs <文件>`，或 `git rebase --abort` 重来 |
| 忘了切分支就开始改 | —— | `git stash` → `git switch -c p1/yx` → `git stash pop` |
| 改坏了想回到上次提交 | —— | `git restore <文件>`（丢弃单个文件改动） |
| 提交后想改 commit 信息 | 未推送 | `git commit --amend` |
| 想撤销最近一次提交但保留改动 | 未推送 | `git reset --soft HEAD~1` |
| 提交了不该提交的文件（未推送） | —— | `git rm --cached <文件>` 再 `--amend`；同时补 `.gitignore` |
| 提交了密钥（已推送） | **安全事故** | 立刻通知全组 → 到对应平台**吊销/轮换该 key** → 再讨论是否清历史 |
| 误删了分支 / 找不到提交 | —— | `git reflog`（本地 90 天内都能找回）→ `git switch -c rescue <sha>` |
| 有人强推覆盖了你的分支 | —— | `git reflog`/远端备份找回；并在群里把“不许强推公共分支”再讲一次 |
| 工作区莫名多出大量改动 | 换行符或脚本产物 | `git diff --stat` 确认；换行符见 §6.4；脚本产物用 `git restore outputs/` 丢弃 |
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
| 1 | `python -B -X utf8 run.py test` 全部通过（现有 128 项） | 本地跑 |
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

1. **加协作者**：Settings → Collaborators → 添加 yx/mmj/lb，权限给 `Write`（不要给 `Admin`）。
2. **保护 main**：Settings → Branches → Add branch protection rule，分支名 `main`，勾选：
   - ✅ Require a pull request before merging（Required approvals: **1**，三人团队设 2 会僵住）
   - ✅ Dismiss stale pull request approvals when new commits are pushed
   - ✅ Require conversation resolution before merging
   - ✅ Do not allow bypassing the above settings
   - ❌ 不要勾 Allow force pushes / Allow deletions
3. **模板**（可选但强烈建议）：把 §12.1 / §12.2 的内容存成仓库里的
   - `.github/pull_request_template.md`
   - `.github/ISSUE_TEMPLATE/round.md`
   这样每次开 PR/Issue 自动带出格式，不会有人漏写验证证据。
4. **开 Issues**：Settings → General → Features → Issues 打勾（一轮一个 Issue，是本规程的“看板”）。
5. **不装 `gh` 也能全流程**：所有操作都有网页入口。以后想用命令行可以装 GitHub CLI（`winget install GitHub.cli`，然后 `gh auth login`），但**不是必须**。

---

## 11. 如果只记住十条

1. `main` 神圣：只有 PR 合并能进，永不强推。
2. 每轮从**同一个 SHA** 切分支，分支名 `p<轮>/<人名>`。
3. 方案写进**自己的新文件**，共享文件留到合并时改。
4. 小步提交、精确 `git add`，绝不 `git add -A`。
5. 早 push（半成品也推），让别人看得见你的方向。
6. 先提 PR ≠ 赢；**评审通过才是赢**。
7. 评审必须本地检出对方分支**复跑验证脚本**，意见必须给证据。
8. 已合并用 `revert`，未推送用 `reset`；自己的分支强推用 `--force-with-lease`。
9. 每轮结束必须写 `docs/ROUND_LOG.md`，落选分支打 `alt/` tag 留档。
10. 出事先 `git status` + `git reflog`，别急着敲命令。

**补充（仅在用 §3.5 集中提交模式时）**：提交必须带 `--author='<人名> <邮箱>'`，或按人分 `worktree`。否则三人的历史会糊成同一个人，评审和追溯全部失效。

---

## 12. 模板（可直接复制）

### 12.1 PR 描述模板

```markdown
## 本轮
问题：P1 —— <一句话>
Issue：Refs #<issue>
起跑线 commit：<base SHA>

## 我做了什么
- <改动点 1：文件 + 一句话>
- <改动点 2>

## 为什么这样做（方案取舍）
<和另外两种思路比，为什么选这个；不选的那条路我试过/评估过，问题是……>

## 怎么验证的（必须贴真实输出）
```powershell
python -B -X utf8 run.py test          # 128 passed
python -B -X utf8 run.py audit         # OK
python -B -X utf8 scripts/scan_google_keys.py   # no hits
```
关键产物：`outputs/prototype/p1_yx_annual_balance.json`（关键数字：<数值>，来源：<脚本+输入>）

## 改了哪些文件
`git diff --stat origin/main` 粘贴在此

## 已知局限 / 风险
- <例如：未覆盖 2030/2060 外推；样本仅 2015–2021>

## 自检清单
- [ ] run.py test 通过
- [ ] run.py audit 通过
- [ ] 密钥扫描无命中
- [ ] 未改动 只读工作区/
- [ ] 未混入 B/C 题内容
- [ ] 新增数据已在 data/catalog 登记
```

### 12.2 评审清单模板（评审人贴在 PR 评论里）

```markdown
## 评审结论：✅ 采纳 / ⚠️ 补强 / ❌ 另起

复跑环境：<机器/日期>
复跑结果：
- run.py test → <通过/失败，失败项>
- run.py audit → <通过/失败>
- 方案入口（如 run.py prototype）→ <输出摘要>

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

我的处理：<关闭我的 PR 并打 tag / 我将提补强 PR 补第 1 点 / 我继续争取我的方案，差异在……>
```

### 12.3 `docs/ROUND_LOG.md` 模板

```markdown
# 攻关轮次日志

## P1 · <问题标题>（YYYY-MM-DD ~ YYYY-MM-DD）
- 起跑线：`<base SHA>`
- 参与分支：p1/yx、p1/mmj、p1/lb
- 先提 PR：#12（yx，方案A）
- 评审：mmj ✅、lb ⚠️（缺 X）
- 结果：**合并 #12**（squash → `<merge SHA>`），补强 #15 随后合并
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

- `AGENTS.md`：**优先级最高**的工程约束（只做 A 题、只读工作区不动、数据准入、不用合成结果冒充真实预测）。本规程不覆盖它，只补充“怎么用 Git 落实它”。
- `WORKFLOW.md`：F0–F7 阶段划分与验收证据要求。每轮的“问题”应能映射到某个 F 阶段。
- `docs/RUNNING.md`：环境与命令，PR 自检时按它跑。
- `docs/DATA_GUIDE.md`：新增数据的登记与去重规则，新数据类 PR 必读。
