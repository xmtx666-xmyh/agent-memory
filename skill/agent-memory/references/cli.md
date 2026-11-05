# CLI 参考（全部命令与参数）

> 本文出现的**实体名与项目路径都是本机示例**（每台机器不同）；换机器请先用 `am.ps1 topics --top 20` 查本机实际有哪些实体。


> 工程目录 `<工程目录>`，Python 用 `.venv\Scripts\python.exe`。
> 所有命令都是**只读**（`ingest` 只写自己的索引库，不改各 agent 的原始数据）。

## search — 检索历史会话

```powershell
am.ps1 search "<关键词>" [--limit 10] [--trigram] [--peer 仓库名]
```

| 参数 | 说明 |
|---|---|
| `--trigram` | **中文必须加**：`unicode61` 索引不切分 CJK（整段中文是一个 token，任何中文子串都查不到） |
| `--limit` | 返回条数，默认 10 |
| `--peer` | 只查某个工作区身份（按 cwd 的 git origin 派生，子串匹配，如 `demo-base`） |

**两条实测边界（2026-11-04 内存 FTS5 验证）**：

- **1~2 字的中文词**（`质保`、`预算`）在 trigram 上也查不到（trigram 只索引 3 字滑窗）。
  实现会自动**回退 LIKE 全表扫描**，输出里标 `索引=like`（约 100~150 ms，比索引慢 1~2 个数量级）；
  要快就换成 3 字以上的词或当时的原话。
- **查询里的 `+ - * ^ : " ( )` 是 FTS5 语法字符**（如 `C++`、未闭合引号）。这类查询会**报错退出（exit 2）**并说明原因，
  **不会**伪装成"零命中"；搜它们请加引号或换词。

输出：每条命中带 `agent ｜ 会话标题 ｜ 日期 ｜ 角色 ｜ 片段`。索引命中延迟 2~15 ms。

## timeline — 话题演变时间线

```powershell
am.ps1 timeline "<实体>" ["<意图>"] [--per 3] [--out 路径]
```

- **实体**（项目/系统）：`demo-kb`、`PageIndex`、`示例客户项目(DEMO2021)`、`示例街道A`、`Codex`…
- **意图**（可选）：`检索与排序`、`评测与金标准`、`文档解析`、`OCR与扫描件`、`分块与切分`、
  `大纲与目录树`、`字段抽取`、`投标数值`、`上下文压缩`、`会话记录`、`架构与选型`、
  `部署与性能`、`服务端接口`、`Web前端`、`多agent委派`、`外部复核`、`数据与库`、
  `合规与风险`、`投标业务`
- 每条结论带状态：`decision` / `verified` / `superseded_candidate` / `experiment`
- 会列出**跨会话冲突**（同一参数出现不同取值）

## premises — 前提校验（旧路径/端口还有效吗）

```powershell
am.ps1 premises "<实体>" [--top 10] [--limit N]
```

输出三档 + 清单：

| 判定 | 含义 | 处置 |
|---|---|---|
| 🟢 `alive` | 引用的路径存在 | 前提通过 |
| 🟡 `dead_with_successor` | 路径不存在，但**该实体仍有存活目录** | **项目已改名**，把旧路径换算成新路径；结论可能仍有效 |
| 🔴 `dead_no_successor` | 路径不存在且**该实体已无存活目录** | 真失效，勿照做 |
| ⚪ `unverified` | 无可验证前提（97%） | 无法机械判定，标"未验证" |

**端口不进失效判定**：没有监听测的是"存活"不是"存在"（服务没启动是常态）。

## inject — 生成「环境事实」注入块

```powershell
am.ps1 inject "<实体>" [--max-chars 1400] [--write <项目>\.agent-memory\context.md]
```

- 把 premises 的结果**压缩**成可粘贴的几行（实测 40 条 → 3 条规则，约 324 token）
- 块头带 `check_at`：**存在性是检验时刻的函数**，目录再改名这块就过期

## topics — 话题归并（实体 × 意图打标）

```powershell
am.ps1 topics --build          # 重算全部会话标签（约 2 秒，幂等）
am.ps1 topics --entity PageIndex --top 8   # 单实体的会话时间线
```

标签来源：**工具调用碰过的文件路径**（比 cwd 与正文提及都硬）。

## ingest / stats — 采集与统计

```powershell
am.ps1 ingest          # 采集 6 个 agent 的会话（约 90 秒；幂等，已存在的跳过）
am.ps1 stats           # 会话数/消息数/按 agent 分布 + peer 覆盖
```

来源（全部只读）：DSH `~/.dsh/sessions`、Codex `~/.codex/sessions`、Claude Code `~/.claude/projects`、
**WorkBuddy** `~/.workbuddy[-ai]/projects`、**CodeBuddy** `~/.codebuddy[cn]/projects`；
Hermes 没有固定导出目录，默认找 `~/hermes-export/sessions` 或 `~/.hermes/sessions`，
放在别处就设 `AGENT_MEMORY_HERMES_ROOT=<导出目录>`（否则 Hermes 会静默缺失）。
`--agent` 可单独跑某一个：`am.ps1 ingest --agent workbuddy`。

## peers — 工作区身份（同一仓库的 clone / worktree 归一家）

```powershell
am.ps1 peers                  # 列出 peer（会话数、时间跨度、代表 cwd）
am.ps1 peers --backfill       # 给已入库但 peer 为空的会话补算（幂等，按 cwd 缓存）
```

规则（照 OpenViking）：**git origin URL 优先**（`git@github.com:owner/repo.git` →
`github.com-owner-repo`），无 origin 回退 `path-<目录名>-<路径哈希8位>`；**不在 git 仓库里就没有 peer**
（不按盘符猜）。`ingest` 会给新会话算；存量会话要靠 `peers --backfill`（`ingest` 不覆盖已存在会话）。

## doctor — 环境自检（装完先跑它）

```powershell
am.ps1 doctor        # 退出码 0=能用（允许 warn）／1=有阻塞问题
```

一次报全：工程目录、Python 版本、依赖（zstandard / pyyaml）、索引库是否存在、
**数据 schema 版本（库 vN / 代码 vM）**、会话与消息数、peer 覆盖、最近入库时间、技能版本。
`库 vN > 代码 vM` 会直接报 ERROR —— 旧代码读新库比崩溃更危险（会给出错答案）。

## 版本与变更

- **包版本**：`SKILL.md` 的 `version`（SemVer），每次发版必须升；`references/changelog.md` 记变更。
- **数据版本**：索引库 `PRAGMA user_version`（当前 1），与包版本**分开**；`doctor` 会对账。
- 打包机检：同版本不同内容 → `pack_platform.ps1` 拒绝打包；发布物哈希记在 `dist/.last-package.json`。

## 退出码与异常

- 全部命令成功返回 0；参数错或库缺失会打印中文提示。
- **退出码 3 = 未安装/未初始化**（找不到 `cli.py`，或找不到 venv 里的 python）。报错正文直接给出三种修法：
  ① 设 `AGENT_MEMORY_HOME` 指向含 `cli.py` 的目录（或在 `%USERPROFILE%\agent-memory` 建 junction）；
  ② git 工程：跑工程根的 `install.ps1`；③ 平台包：跑技能里的 `scripts\bootstrap.ps1`。
- `search` 遇到 FTS5 语法字符（`C++` 等）返回 **2** 并说明原因，**不伪装成零命中**。
- 索引库损坏/缺失：删掉 `index/` 再 `ingest` 重建（原始会话不会被改动）。
- 库是 2026-11-04 之前建的：首次跑会自动 `ALTER TABLE` 补 `peer` 列，不用重建索引。
