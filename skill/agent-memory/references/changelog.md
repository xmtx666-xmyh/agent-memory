# 变更日志（agent-memory 技能 / 引擎）

> 版本号规范（借鉴 Helm 与 npm）：**包版本 = 技能与引擎的版本**，与「数据 schema 版本」
> 分开记（后者存在索引库 `PRAGMA user_version`，`am.ps1 doctor` 会同时报出两者）。
> 改动**必须**先改这里的条目、再升 `SKILL.md` 的 `version`，否则 `pack_platform.ps1` 会拒绝打包。

## [1.5.1] — 2026-11-05

### 修复
- **包内不再含真实项目/客户名与内部路径**：实测 v1.4.0/v1.5.0 的上传包 14/28 个文件命中
  （真实客户名 5 处、自有项目名 66 处、内部绝对路径 12 处）。本次把注释、docstring、示例、
  帮助文本里的真名统一换成通用示例（`demo-kb` / `demo-base` / `示例客户项目(DEMO2021)` /
  `F:\demo-main` 等）。**代码语义未变**，95 条测试全绿。
- 打包新增**私有词机检**：词表 `.private-terms.txt`（gitignore，不进包、不进公开仓）+
  `tools/check_private_terms.py`；命中任一即 `PACK FAIL` 并逐条打印 `文件: 词`。

## [1.5.0] — 2026-11-04

### 新增
- `am.ps1 doctor` / `cli.py doctor`：环境自检（工程目录、Python、依赖、索引库、数据 schema 版本、
  会话/消息数、peer 覆盖、最近入库、技能版本），退出码 0/1 —— 装完没跑通时先跑它。
- 索引库 `PRAGMA user_version`（当前 **1**）：包版本 ≠ 数据版本；库比代码新时**直接拒绝**运行，
  防止旧代码读新结构给出错答案。
- `references/changelog.md`（本文件）：随包分发，用户能自己看"这版改了什么"。

### 借鉴来源
Helm 的 `version` 与 `appVersion` 分离、`openviking-server doctor`、npm 的 dist-tag/`npm doctor` 思路。

## [1.4.1] — 2026-11-04

### 修复
- **未安装时的报错不可操作**：原来只抛 `agent-memory home not found. Set AGENT_MEMORY_HOME ...`。
  现在退出码 **3**，并直接给三种修法（设 `AGENT_MEMORY_HOME` / 工程 `install.ps1` / 包内 `bootstrap.ps1`）。
- `python not found` 同样给修法，而不是只说结论。
- 打包新增闸门：**版本号未变但内容变了 → 拒绝打包**（1.4.0 曾对应两份不同内容）。

## [1.4.0] — 2026-11-04

### 新增
- 采集来源 4 → **6**：WorkBuddy（CN/AI）与 CodeBuddy（`collectors/workbuddy.py`、`codebuddy.py`）。
  处理三个坑：`<system-reminder>` 包裹（单行最大 87 KB）、`<user_query>` 提取、cwd 只挂在非 message 事件。

### 修复
- `search "agent-memory"` 因 `-` 是 FTS5 运算符直接报错 → 现在自动包成短语重试（`C++` 仍按语法错误报出）。
- 同 key 会话碰撞时比对 `message_count` 并打印警告（CN/AI 实测 22 个同名 session）。

## [1.3.0] — 2026-11-04

### 新增
- `peers` 命令 + `search --peer`：工作区身份按 **git origin** 派生（无 origin 回退 `path-<名>-<hash8>`），
  主仓与 linked worktree 归同一 peer；`ingest` 自动补算，`peers --backfill` 补存量。

## [1.2.0] — 2026-11-04

### 修复
- 1~2 字中文查不到（trigram 只索引 3 字滑窗）→ 自动 **LIKE 回退**，输出标 `索引=like`。
- FTS5 语法错误被静默吞成"零命中" → 抛错并 exit 2（`C++` 等）。
- A/B 数字加限定：单任务、n=1/n=3，**token 未减少**（9B 实验 +14%），省的是步数与错误率。

## [1.1.1] — 2026-11-04

### 修复
- 平台包按「两级目录」规则重排（引擎放到 zip 根，去掉 `scripts\engine\` 嵌套）。
- `bootstrap.ps1` 改为真实源文件并加解释器探测（uv → py → python → 常见目录）；
  `SKILL.md` 不再让人去跑包里不存在的 `install.ps1`。
- `inject` 不再把仍存在的目录报成「已确认失效（勿照做）」。

## [1.1.0] — 2026-11-03

### 新增
- 话题归并（实体 × 意图）、演变时间线、前提校验（premises）、环境事实注入块（inject）、
  DSH 技能包装（`SKILL.md` + `references/` + `templates/`）。

## [1.0.0] — 2026-11-02

### 新增
- 四个来源（DSH / Codex / Claude Code / Hermes）会话采集 + SQLite FTS5 双索引（unicode61 + trigram）
  + 检索（毫秒级、零模型）。
