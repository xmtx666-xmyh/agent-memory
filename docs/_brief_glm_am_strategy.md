# 复核任务：agent-memory 的检索与「是否继续深度开发」结论

> 这是一份**复核简报**，不是文档；复核者只读代码、只写一份评审 md。
> 复核者：glm-5.3（非同源：被复核方是 DeepSeek 系模型）。日期：2026-11-04。

## 一、待复核的四条结论（请逐条判定「成立 / 部分成立 / 不成立」，并给依据）

### 结论 A —— 战略：agent-memory 该继续，但必须收窄
给定事实：字节/火山引擎开源的 **OpenViking**（41,475 stars / 3,377 forks / 1,234 open issues，
主体 AGPL-3.0，Python，2026-01 建仓、当天仍在 push）是「面向 AI Agent 的上下文数据库」，
统一 Resource/Memory/Skill，带 `viking://` 文件系统、L0/L1/L2 目录摘要、embedding 向量召回 + 可选 rerank、
会话 commit 后 VLM 抽记忆，官方还提供 DeepSeek Harness 记忆插件。

被复核的判断：
1. agent-memory **不应**往「Agent 记忆平台 / 上下文数据库」方向继续加深（重叠区打不过，也不必要）；
2. 它唯一不可替代的是 **前提失效判定**（`premises`：旧路径/命令/端口现在还算不算数，三档：活 / 改名 / 真失效），
   这是「OpenViking 存的是你们说过什么，agent-memory 判的是那些话现在还算不算数」；
3. 因此继续开发的三条优先级：① 提高 premises 的可机械验证覆盖率（现状约 1~2%）② 量化注入块价值 ③ 修跨 agent 检索的召回短板（转述词零命中）；
4. 停止项：话题归并继续深化、知识库 RAG、多模态、服务化、SDK、多租户。

### 结论 B —— 现有检索是「零模型」的
判断：agent-memory 的检索不依赖任何模型（LLM / embedding / VLM）。依据：
- `F:\agent-memory\store.py` L54/L57：两个 FTS5 索引，`tokenize='unicode61'` 与 `tokenize='trigram'`；
- `store.py` L118-131：`search()` 就是 `WHERE {table} MATCH ? ORDER BY rank`，FTS5 的 `rank` 默认 BM25；
- `topics.py`：实体/意图打标是手写词典 + ASCII 词边界正则 + 命中强度阈值，无 LLM；
- 实测 34k 条消息上 6.3 ms（`am.ps1 search PageIndex --trigram`）。
判断的代价面：字面/子串匹配，**同义、转述、跨语言查不到**；排序无语义相似度。

### 结论 C —— 若补语义，应该是「默认关闭的第三路」
建议：不替换 FTS5，新增一路**本地 Ollama embedding**，与 FTS5 结果用 **RRF 融合**（同构于本机
`F:\demo-base` 的 `rrf.py` 对 tree/graph/fts5 的加权融合）；只在 FTS5 命中为 0 或用户显式 `--semantic` 时启用，
保住「零依赖 + 毫秒级」默认路径。代价评估：查询延迟 2~7 ms → ~50 ms；索引 +35~140 MB；
多一个 Ollama 常驻依赖。

### 结论 D —— 注入块的价值量级
判断依据（本仓已有 A/B 数据）：Codex 在中立 cwd 找同一文件 **16 次工具调用 vs 2 次**（读注入块后，−87.5%）；
本地 9B 模型在旧路径上 **0/3 答对**，读了注入块 **3/3 答对**。

## 二、可读材料（**只读这些，不要全库扫描**）

- `F:\agent-memory\store.py`（重点 L40-60 建表、L112-136 检索、L154-267 话题/路径）
- `F:\agent-memory\topics.py`（实体/意图词典与匹配规则）
- `F:\agent-memory\premises.py`（三路判定 `judge_path`、`check_conclusions`、`_NON_ASSET_RE`）
- `F:\agent-memory\inject.py`（注入块压缩 `_collapse` / `_render_dead`、预算）
- `F:\agent-memory\timeline.py`（结论抽取与状态）
- `F:\agent-memory\docs\skill-overview.md`（能力、8 条命令、验证状态与四条边界）
- `F:\agent-memory\docs\design.md`（设计取舍）
- `F:\agent-memory\cli.py`（命令入口与参数）
- 外部事实（OpenViking）：`F:\demo-kb\entities\openviking.md`（已按官方文档 + GitHub API + npm registry 核过）
- **不要**改代码、测试、README、cli；**不要**跑 ingest（会写 index）。

## 三、复核要回答的具体问题

1. 结论 B 的表述是否**准确且完整**：`tokenize='trigram'` 与 `unicode61` 在中文上的实际行为差别，
   以及「`ORDER BY rank` 默认是 BM25」这个说法在 FTS5 上是否成立？有无被漏掉的检索路径（如 `topics --entity`、
   `timeline`、`premises` 是否也依赖某种模型）？
2. 结论 C 的成本与收益是否被**低估或高估**：34k 条消息做本机 embedding 的实际工作量与索引体积、
   RRF 融合在「只有两路且一路可能为空」时是否需要权重/归一化处理、按需触发是否会引入不可解释的「时有时无」结果。
3. 结论 A 的**优先级判断**是否成立：`premises` 覆盖率真的比「检索召回质量」更该优先吗？
   收窄边界里有没有漏掉「OpenViking 短期内会吃掉、而 agent-memory 现在还在维护」的功能。
4. 是否存在**结论 D 的数据被过度引用**（那是特定任务的一次 A/B，不是通用增益）？

## 四、硬性要求（必须遵守）

1. **需要材料之外的信息时，必须写「待确认」并说明缺什么，不得当作缺陷报。**
2. **每一条发现必须给出可达性论证**（具体文件:行号 + 调用点/触发路径）。给不出可达性论证的，降级为「待确认」。
3. **结论落盘**：写到 `F:\agent-memory\docs\_review_glm_am_strategy.md`，然后在回复里只回一行：
   `WROTE F:\agent-memory\docs\_review_glm_am_strategy.md <条目数>`
4. 评审文件结构：
   - `## 逐条判定`：A/B/C/D 各给「成立 / 部分成立 / 不成立」+ 依据（文件:行号）+ 可达性论证
   - `## 发现的错误或过度自信`：每条带「严重度（高/中/低）」+ 证据 + 可复现路径
   - `## 待确认`：写清缺什么材料
   - `## 我建议的下一步`（不超过 5 条）
5. 只写这一个 md 文件；不要动仓库里任何其它文件。
