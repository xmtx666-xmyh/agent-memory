# 设计说明

## 一、为什么要做

本机同期在跑 6 个 agent（DSH / Codex / Claude Code / Hermes / WorkBuddy / CodeBuddy），同一件事常被反复讨论。
实测（2026-11-02 首轮 4 个来源；2026-11-04 扩到 6 个来源，见 §七）：

| 话题 | Codex | Claude | Hermes | DSH |
|---|---|---|---|---|
| PageIndex | 65 | 40 | — | 未解压 |
| 投标 | 58 | 67 | — | — |
| demo-wiki | 73 | 14 | — | — |
| 知识图谱 | 19 | 58 | — | — |
| ontology | 13 | 62 | 10（同一话题血缘） | — |

所以"把这堆会话归纳成话题、并画出演变"是真实需求。本项目只做**第一层**（采集 + 索引 + 检索），
把后面的话题归并建在可靠的地基上。

## 二、调研过的现成方案（避免重复造轮子）

| 项目 | 与需求的关系 | 结论 |
|---|---|---|
| [recall](https://pypi.org/project/recall-agents/)（MIT） | 几乎就是这个需求：跨 Claude Code/Codex/Cursor 的聊天检索 + 每晚生成 markdown 笔记 + 项目泳道 + `recall why` 溯源 | **借鉴设计，不直接用**：官方明示 **Windows 不支持**（file locking / 调度 / 密钥存储需适配） |
| [Mem0 / Zep-Graphiti / Letta / Cognee / Hindsight](https://vectorize.io/articles/best-ai-agent-memory-systems) | agent 长期记忆框架 | 是"给未来召回用的记忆"，不是"回溯挖历史会话"；且都是"为未来服务"，与本项目"为归纳服务"目标不同 |
| Great Grave: Versioned Context Units (ACM) | "版本化上下文单元"，演变的形式化 | 第二阶段做时间线时可参照 |

**从 recall 学到的、已落到本项目的**：
- 笔记/结论必须**可溯源**（每条带 sources 回链）——预留字段；
- **索引与搜索不调 LLM**，只有"写笔记"用 LLM；
- 内容必须设上限，否则单个工具输出能撑爆一次上下文。

**从 Hermes `session_search`（实测其四模式）学到的**：
- 中文要 **trigram 索引**（普通 FTS5 对连续中文短语不可靠）；
- 隐藏/降权"非用户"来源（子代理、cron、工具）；
- 按 **lineage（血缘）去重**——压缩续接、`/new` 会让同一话题散在多行。

**明确不学的**：Hermes 把只读检索工具与凭证池/YAML 配置强耦合（实测 import 就拉进
`credential_pool`）；本项目采集器彼此独立、`store.py` 零第三方依赖（除 zstandard 解压）。

## 三、数据来源与格式（全部实测，非推断）

### DSH
`~/.dsh/sessions/<slug>/<uuid>/session.v4.jsonl.zstd`，多帧 zstd 的 JSONL：
- `{"type":"session", id, createdAt, cwd, origin, parentSession}`
- `user/message` → `data.content[{type:"text",text}]`
- `assistant/message` → `data.message.content[{type:"text"|"reasoning"}]`
- `request/context` → provider / model
- 314 个会话

### Codex
`~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`：
- `session_meta` → session_id / cwd / model_provider
- `response_item` + `payload.type=="message"` → role + content blocks

### Claude Code
`~/.claude/projects/<slug>/**/*.jsonl`（**有嵌套子目录**，必须递归，否则漏 3/4）：
- `type` ∈ user/assistant，`message.content[{type:"text"|"thinking"|"tool_use"}]`
- 噪音类型 `queue-operation` / `summary` 跳过

### Hermes
`hermes sessions export <dir> --format md --redact --source <src>` 的产物：
- YAML frontmatter（session_id/title/source/created_at/model/cwd/message_count）
- `### User — <ISO>` / `### Assistant — <ISO>` 分节
- 注意：**导出里 assistant 的纯文本常常为空**（Hermes 多轮靠工具调用推进），
  所以 71 个会话只入库 788 条正文——这不是 bug，是它的对话形态决定的。

## 四、索引设计

```sql
sessions(session_key PK, agent, session_id, title, cwd, started_at, ended_at,
         model, provider, parent_session, origin, source_path, message_count, tool_call_count)
messages(id PK, session_key, agent, role, ts, seq, text)
messages_fts  TEXT content='messages' tokenize='unicode61'   -- 英文/数字
messages_trgm TEXT content='messages' tokenize='trigram'     -- 中文短语
```

`session_key = "<agent>:<session_id>"` 作为跨来源的稳定主键（`parent_session` 字段留作血缘归并用）。

## 五、第二阶段（未做）的接口预想

1. **话题身份**：实体词典（`demo-base` / `demo-wiki` / `demo-next` / `demo-kb` 视为同一实体）
   + 意图标签；**不先上向量聚类**——会产生"看起来对"的假结论。
2. **演变时间线**：同一 (实体 × 意图) 下按时间排，检测**结论冲突**（同一问题不同答案 → 后者可能推翻前者）。
3. **结论状态**：每条结论标 `active / superseded / experiment`——
   这是"不把废弃方案当现状"的唯一办法（llama-server 那次就是反例）。

## 七、2026-11-04 扩到 6 个来源：WorkBuddy / CodeBuddy

**格式**（实测 686 个 JSONL）：`<root>/<project-slug>/<uuid>.jsonl`，逐行一个事件；
`type=message` 的正文在 `content:[{type:"input_text"|"output_text", text}]`，
其余 `reasoning / function_call / function_call_result / file-history-snapshot / custom-title` 是工具与噪音。

**三个坑（采集器 `collectors/workbuddy.py` 已处理）**：

1. **user 正文被 `<system-reminder>` 包住**：身份文件（SOUL/IDENTITY/USER）、项目快照、automation 说明
   单行最大实测 **87,136 字符**；真正的提问在 `<user_query>` 里。不提取就等于把系统提示当人话灌进索引。
   ⚠️ **不要指望 `base.is_injected_context()` 兜底**：本采集器不调用它；而且它按 `startswith("<system-reminder>")`
   精确匹配，**匹配不了带属性的 `<system-reminder data-role="x">`**（第 2 轮 glm-5.3 复核纠正）。
2. **cwd 可能只挂在非 message 事件上**（workbuddy-ai 实测 20 条 message 缺 cwd）→ 扫全文件任意事件兜底；
   **不要按目录 slug 反猜路径**（slug 把 `\` 与 `-` 混在一起，不可逆）。
3. **message 之间夹着工具与 reasoning**：只索引 user/assistant 正文，工具调用只用来抽 `tool_dirs`
   （实体归属信号）。

**实测收益**：WorkBuddy 194 会话 / 8,925 条（36 s），CodeBuddy 462 会话 / 1,253 条（9 s）；
库从 625 会话涨到 **1281 会话 / 45,060 条**，peer 覆盖从 254 涨到 **582**（6 个 peer）。
CodeBuddy 每会话平均消息少（2.7 条）—— 它以一次性 CLI 任务为主，不是长对话，这是事实不是缺陷。

**取舍**：两套是同一家族格式，`collectors/codebuddy.py` 只换根目录与 agent 标签，
解析逻辑单一来源在 `workbuddy.py`，避免两份实现漂移（`tests/test_workbuddy.py` 钉住）。