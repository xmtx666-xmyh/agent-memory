# 复核任务（第 2 轮）：agent-memory 今日改动 + 知识库 sidecar + 技能更新方案

> 复核者：glm-5.3（非同源：被复核方是 DeepSeek 系模型）。日期：2026-11-04。
> 只读代码、只写一份评审 md。**不要改任何代码/测试/文档/技能**。

## 一、待复核的改动（请逐条判定「成立 / 部分成立 / 不成立」，并给可达性论证）

### 1. peer（工作区身份）按 git origin 派生
文件：`F:\agent-memory\peers.py`、`F:\agent-memory\store.py`（sessions 表 + `_migrate` + `upsert_session` +
`backfill_peers` + `search(peer=)`）、`F:\agent-memory\cli.py`（`peers` 命令、`search --peer`、ingest 自动补算）。

待复核的具体判断：
- (a) `common_root()` 用 `git rev-parse --path-format=absolute --git-common-dir` 取父目录，能保证
  **主仓与 linked worktree 同 peer**；老 git 的两级回退也正确；
- (b) 无 origin 时用 `path-<目录名>-<路径哈希8位>`；非仓库/不存在目录返回空串 —— 不猜盘符是对的；
- (c) `_migrate()` 的 ALTER TABLE + 索引创建顺序对**老库**安全且幂等（索引不能放 SCHEMA，否则老表缺列会崩）；
- (d) `backfill_peers()` 只补空值、幂等、按 cwd 缓存；
- (e) `search(peer=)` 用 `s.peer LIKE ?` 且 `_like_escape` 已转义；与 LIKE 回退组合时参数顺序正确。

### 2. 新增 WorkBuddy / CodeBuddy 采集器
文件：`F:\agent-memory\collectors\workbuddy.py`、`collectors/codebuddy.py`、`cli.py`（COLLECTORS 注册）、
`tests/test_workbuddy.py`。

待复核的具体判断：
- (a) user 正文必须先取 `<user_query>` 再退化"剥 `<system-reminder>` 块"，否则会被
  `is_injected_context()` 整条丢掉或把系统提示灌进索引；
- (b) cwd 从"任意事件"兜底（message 可能没有），且**不按 slug 反推路径**；
- (c) 只索引 user/assistant 正文，function_call 只计 `tool_call_count` 与抽 `tool_dirs`；
- (d) 同一 session_id 在 CN/AI 两套目录重复时，靠 `session_key` 幂等去重 —— 会不会**静默丢内容**
  （两份文件内容不同却只留第一份）？这是不是一个应写进文档的真实风险；
- (e) 行超长（实测 87 KB）、坏行跳过、单文件异常不中断整批，这三条是否真的成立。

### 3. `search` 的"宽松重试"（本轮顺手修的回归）
文件：`F:\agent-memory\store.py`（`_relax_query`、`search`）、`cli.py`（`last_query_relaxed` 提示）。

- 背景：`-` 在 FTS5 是运算符，`search "agent-memory"` 原来直接报 `no such column: reminder`。
- 现逻辑：遇 `OperationalError` → 若查询不含 `+ * ^ ( ) "`，把含 `- : .` 的 token 包成短语后重试；
  仍失败才抛 `QueryError`；成功后置 `last_query_relaxed`。
- 待复核：这个"只对 `- : .` 宽松、对 `+*(^")` 仍报错"的边界是否合理？有没有**该报错却被吞**或
  **该能搜却被拒**的组合（例如 `a-b c`、`qwen3.5:9b`、中文+连字符、trigram 表上的短语）？

### 4. 知识库目录 sidecar（另一仓库，只读）
文件：`F:\demo-kb\_meta\sidecar.py`、`_meta\lint.py`（`page_files` 排除点文件、第 ⑧ 项新鲜度）、
`SCHEMA.md`（Conventions 新增一条）。

- 待复核：① lint 用 `glob("*.md")` 排除点开头文件，是否会让**以点开头的真实页面**（若有人这样命名）
  永远逃过 lint？② sidecar 的 `check_at`/`total_entries` 与 lint 第 ⑧ 项是否口径一致
  （都用"非点文件"计数）？③ sidecar 自己会不会被当成 raw 源参与 sha256 漂移检查？

### 5. 技能同步方案（请指出风险）
已安装技能 `~\.dsh\skills\agent-memory\` 是 v1.1.0（缺 bootstrap.ps1、旧 SKILL.md）。
计划：把仓库 `F:\agent-memory\skill\agent-memory\` 全量覆盖过去；并在 `%USERPROFILE%\agent-memory`
建一个 **junction** 指向 `F:\agent-memory`，让 `_resolve.ps1` 的第 4 档兜底（`$env:USERPROFILE\agent-memory`）
能解析到工程（否则 DSH 里跑技能会 throw）。

- 待复核：这个方案是否稳妥？junction 与 `AGENT_MEMORY_HOME` 环境变量相比，哪个更适合"DSH 宿主已启动、
  改环境变量要重启才生效"的场景？覆盖安装时**要不要保留**已安装目录里的东西（例如用户改过的配置）？

## 二、可读材料（只读这些，禁止全库扫描）

- `F:\agent-memory\peers.py`、`store.py`、`cli.py`、`collectors\workbuddy.py`、`collectors\codebuddy.py`
- `F:\agent-memory\tests\test_peers.py`、`tests\test_workbuddy.py`、`tests\test_store.py`
- `F:\agent-memory\docs\peers-p0.md`、`docs\design.md`（§七 新来源）、`docs\skill-overview.md`
- `F:\agent-memory\skill\agent-memory\scripts\_resolve.ps1`（解析顺序）
- `F:\demo-kb\_meta\sidecar.py`、`F:\demo-kb\_meta\lint.py`、`F:\demo-kb\SCHEMA.md`
- 不要跑 `ingest`（会写索引）；不要读 `index/`（数据，40+ MB）。

## 三、复核要回答的问题

1. 上述 5 组判断里，哪些**不成立或过度自信**？逐条给 `文件:行号` + 可达性论证。
2. peer 的 LIKE 过滤在**子串**语义下会不会误配（例如 `demo-base` 命中 `demo-base-old`）？这算缺陷还是可接受？
3. 采集器把 `session_id` 当主键、跨 CN/AI 去重，是否应改成"内容不同则两者都留"？代价是什么？
4. 技能覆盖安装 + junction，有没有**让 DSH 读到旧文件**的风险（例如缓存/skill catalog 热加载）？

## 四、硬性要求（必须遵守）

1. **需要材料之外的信息时，必须写「待确认」并说明缺什么，不得当作缺陷报。**
2. **每一条发现必须给出可达性论证**（`文件:行号` + 调用点/触发路径）；给不出则降级为「待确认」。
3. **结论落盘**：写到 `F:\agent-memory\docs\_review_glm_round2.md`，回复只回一行：
   `WROTE F:\agent-memory\docs\_review_glm_round2.md <条目数>`
4. 评审文件结构：`## 逐条判定`（5 组）/ `## 发现的错误或过度自信`（带严重度+证据）/
   `## 待确认` / `## 建议的下一步`（≤5 条）。
5. 只写这一个 md 文件，不要改其它任何文件。
