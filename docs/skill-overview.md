# agent-memory 技能：触发条件与功能说明

> 2026-11-03 ｜ 本文是给"使用者"看的速查，设计取舍见 `docs/design.md`、`docs/staleness-design.md`、
> `docs/injection-mechanism.md`、`docs/ab-injection-result.md`、`docs/ab-codex-replication.md`。

## 验证状态

**已实测**：检索延迟 2~7 ms（1281 会话 / 4.5 万条消息，2026-11-04）；`inject`/`premises` 各约 0.9 s；
`ingest` 6 个来源合计约 90 s（其中 WorkBuddy 194 会话 36 s、CodeBuddy 462 会话 9 s）；
`topics --build` 约 20 s；注入块 40 条压成 3 条（519 字符 / 约 324 token）；
A/B 与 Codex 复测数字见各自文档。
**平台包已实测（2026-11-04）**：`dist/agent-memory.zip` 解压到空目录后 `scripts\bootstrap.ps1`
exit 0（建 venv → 装依赖 → ingest 555 会话 → topics → init），5 个查询命令全部 exit 0。
过程中修掉 4 处缺陷（bootstrap 假定 `python` 在 PATH、SKILL.md 指向包里不存在的 `install.ps1`、
`refresh.ps1` 注释写死盘符、`inject` 把还存在的目录报成"已失效"），详见
`docs/pack-platform-cleanroom.md`。
**平台包结构**：平台只接受两级目录（`根/一级目录/文件`），所以引擎 `cli.py` 与 `collectors\` 放在
**zip 根**、包装脚本放 `scripts\`、数据落 `<skill>\index\`；`pack_platform.ps1` 内置机检
「任一条目层级 > 2 直接失败」+「**版本号未变而内容变了直接失败**」（防止一个版本号对应两份内容）。
**未安装时的行为（v1.4.1）**：找不到 `cli.py` 或 venv 时**退出码 3**，报错正文直接给三种修法
（设 `AGENT_MEMORY_HOME` / 工程跑 `install.ps1` / 包内跑 `scripts\bootstrap.ps1`）——
旧版只抛一句英文 `home not found`，装完没跑 bootstrap 的人会卡在这里。
**平台真实安装环境仍未验证。**
**未实测**：按"实体×意图"话题覆盖真实工作流的完整度；跨机器合并（本机 ↔ 另一台）未做。

## 一、触发条件

### 1. 语义匹配（主方式）

DSH 把 `SKILL.md` 的 `description` 放进 skill catalog，**模型按语义判断**是否加载，不是关键词硬命中：

> 检索本机多个编码 agent（DSH / Codex / Claude Code / Hermes）的历史会话结论，
> 判断旧结论是否已失效，并生成「环境事实」注入块。
> 触发词：上次怎么决定的、之前讨论过什么、这个项目不同 agent 说过什么、
> 旧路径还有效吗、为什么改成这样、agent-memory

### 2. 典型句式（`examples_zh`）

- 上次我们为什么把某个默认值从 60 改成 15？
- 这个项目在 Codex 和 DSH 里分别讨论过什么？
- 结论里提到的那条路径还能用吗？

### 3. 显式点名

「用 agent-memory 查一下…」「查一下历史会话里…」。

### 4. 不该用它的时候

| 想干的事 | 该用什么 | 原因 |
|---|---|---|
| 看当前代码是什么样 | `read` / `grep` | 它只回答"过去怎么说过" |
| 还有什么没做完（待办） | 项目的 `docs/接续清单.md` | **它不认识"未完成"状态** |
| 查外部资料/最新信息 | `web_search` | 只读本机会话 |

## 二、功能（10 个命令）

| 命令 | 作用 | 实测耗时 |
|---|---|---|
| `search "<词>" --trigram` | 全库检索历史会话（**中文必须 `--trigram`**；1~2 字中文自动回退 LIKE；`--peer 仓库名` 只查某个工作区） | 2~15 ms（回退时约 100~150 ms） |
| `timeline "<实体>" ["<意图>"]` | 话题演变：结论按时间排 + 4 种状态 + 跨会话冲突 | 秒级 |
| `premises "<实体>"` | 前提校验：旧路径现在是「活 / 已改名 / 真失效」 | ~0.9 s |
| `inject "<实体>" --write` | 生成 `.agent-memory/context.md` 注入块 | ~0.9 s |
| `topics --build` | 话题归并（实体 × 意图 打标） | ~2 s |
| `topics --entity X` | 单实体下的会话时间线 | 秒级 |
| `peers [--backfill]` | 工作区身份（按 cwd 的 git origin 派生）列表 / 补算存量 | 秒级（首次补算 ~10 s） |
| `doctor` | 环境自检：工程/Python/依赖/索引库/**数据 schema 版本**/会话数/peer/最近入库/技能版本 | 秒级，退出码 0/1 |
| `ingest` | 采集 6 个 agent 的会话（DSH / Codex / Claude Code / Hermes / WorkBuddy / CodeBuddy，**只读**原始数据） | ~90 s |
| `init` / `stats` | 换机初始化 / 统计 | 秒级 |

### 核心能力只有三件

1. **找回"过去怎么说的"**：跨 agent 统一检索，带会话标题、日期、角色
2. **看"怎么演变的"**：结论按时间排开，标 `decision / verified / superseded_candidate / experiment`
3. **判"还成立吗"**：三档 —— 🟢 前提通过 ｜ 🟡 **项目已改名**（换算新路径，结论可能仍有效）
   ｜ 🔴 **真失效**（勿照做）。⚠️ **不要把 🟡 说成"失效"**，那会误杀仍有效的经验

### 产物

- 终端输出（检索 / 时间线 / 判定表）
- **`context.md` 注入块**：6~12 行环境事实，被新会话自动读取。实测价值——
  Codex 在中立 cwd 下找同一文件：**16 次工具调用 vs 2 次**（−87.5%，output token −73%）；
  本地 9B 在旧路径上直接**答错**（0/3），读了它 3/3 正确。
  ⚠️ **限定**：这是**单任务** A/B（n=1 个 ghost path、n=3 轮 9B），不是通用增益；
  且 **token 没有减少**——9B 实验里注入臂反而 **+14%**（1,379→1,578），省的是**步数与错误率**。
  详见 `docs/ab-injection-result.md`、`docs/ab-codex-replication.md`。

## 三、四条边界

| 边界 | 后果 |
|---|---|
| **不认简称** | `Q38`/`资料未提供` 能命中；`脱窗`/`拒答`（我转述时造的）零命中 → 用**稳定 ID 或当时的原话** |
| **1~2 字中文走回退** | trigram 只索引 3 字滑窗，`质保`/`预算` 这类两字词查不到；实现自动回退 **LIKE 全表扫描**（输出标 `索引=like`，约 100~150 ms）。要快就用 3 字以上的词 |
| **语法字符会报错** | `+ - * ^ : " ( )` 是 FTS5 语法字符（`C++`、未闭合引号）：报错 exit 2 并说明，**不会**伪装成"没命中" |
| **索引是快照** | `ingest` 之后的新对话不在里面；注入块带 `check_at`，目录再变就过期 |
| **不是待办系统** | 没有"未完成"状态，只答"过去说过什么" |
| **97% 结论无可验证前提** | 只有 1~2% 能机械判"是否失效"，其余标"未验证" |

## 四、安装与换机

- 工程：`F:\agent-memory`（可用 `AGENT_MEMORY_HOME` 覆盖）
- 技能：`~/.dsh/skills/agent-memory/`（9 个文件；`.ps1` 全部纯 ASCII，避开 PowerShell 5.1 的 GBK 解码坑）
- **换机三步**：① 跑 `install.ps1`（建 venv、装依赖、采集、生成**本机**实体表与目标）
  ② 用 `topics --top 20` 看本机有哪些实体（**别照搬别台的 `demo-kb`**）
  ③ 按需编辑 `index/entities.json` 补"旧名→新名"，**之后必须重跑 `topics --build`**
- 三层分离：工具层（可移植，代码不含项目名/盘符）/ 数据层（`index/`，每机生成，gitignore）/ 技能层（通用）

## 五、刻意**不**注册定时任务（2026-11-03 决定）

`refresh.ps1` 可以注册成 Windows 计划任务，但**决定不注册**，理由：

- 注入块的价值在于"新会话开始时是新的"，而会话是**随机时间**开始的 —— 每天 06:30 跑一次，
  白天目录改名就滞后了；实测单跑 `inject` 只要 **0.9 秒**，**按需现算**才对。
- `ingest + topics`（约 45 秒）才适合周期性，但它只影响"能查到多少历史"，
  不影响"路径是否还有效"；按需在查之前跑一次即可。
- 注入块带 `check_at`，注入时按日期判断可信度；过期就重跑一条命令，不需要后台常驻。

因此：**注入块按需刷新、索引按需重建，不依赖任何计划任务。**
