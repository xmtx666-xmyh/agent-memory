# agent-memory

把本机多个 AI agent 的**会话历史**汇成一份可检索的库，并在此之上提供
**话题归并 / 演变时间线 / 旧结论前提校验 / 环境事实注入**。

一句话：让新会话先问一句「这件事以前定过没有、当时的前提现在还成立吗」，
而不是让每个 agent 从零重来一遍。

> **文档里的实体名与路径都是占位示例**（`demo-kb`、`demo-base`、`F:\demo-main`、`示例街道A` …）。
> 实体名是**每台机器各自的会话数据**，由 `cli.py init` 生成，换机器自然不同。

## 为什么做这个

同一个项目往往被多个 agent 接手过（DSH / Codex / Claude Code / WorkBuddy …），
但它们的记忆互不可见：人在 DSH 里定下的结论，Codex 下一次会话完全不知道；
项目改过名、搬过盘之后，旧结论里的路径已经失效，agent 却还在照着旧路径干活。

这个项目把「人说过什么、agent 下过什么结论」抽成可检索的语料，再解决三件事：

1. **同一个东西的多个名字要归并**（`demo-wiki` / `demo-base` / `demo-kb` 是一条线）；
2. **结论的前提要能验**（路径还在吗？项目改名了吗？——"迁移"不等于"失效"）；
3. **给新会话注入最小事实块**（几 KB，而不是把几十条旧结论全塞进上下文）。

## 快速开始（Windows）

```powershell
git clone https://github.com/xmtx666-xmyh/agent-memory.git agent-memory
cd agent-memory

# 建 .venv、装依赖、采集本机会话（只读）、建索引、生成本机实体表
powershell -NoProfile -ExecutionPolicy Bypass -File install.ps1
```

装好后用技能包装脚本调用（它会自己找到工程目录与 venv）：

```powershell
.\skill\agent-memory\scripts\am.ps1 topics --top 20          # 本机有哪些实体（先看这个）
.\skill\agent-memory\scripts\am.ps1 search "关键词" --trigram  # 检索（中文短语必须 --trigram）
.\skill\agent-memory\scripts\am.ps1 timeline "demo-kb" --per 3
.\skill\agent-memory\scripts\am.ps1 premises "demo-kb" --top 5
.\skill\agent-memory\scripts\am.ps1 inject "demo-kb" --write .agent-memory\context.md
```

也可以直接用引擎：

```powershell
.\.venv\Scripts\python.exe cli.py ingest
.\.venv\Scripts\python.exe cli.py search "PageIndex" --trigram
.\.venv\Scripts\python.exe cli.py stats
```

## 命令一览

| 命令 | 作用 |
|---|---|
| `ingest` | 采集各 agent 会话入库（幂等；只读原始数据） |
| `search` | 全文检索（双 FTS5 索引：`unicode61` + `trigram`） |
| `peers` | 工作区身份（按 git origin 派生），用于按仓库过滤 |
| `topics` | 话题归并：实体 × 意图标签（`--build` 重建） |
| `timeline` | 某实体（可选某意图）的演变时间线 |
| `premises` | 旧结论前提三路判定：🟢 通过 ／ 🟡 项目已改名 ／ 🔴 真失效 |
| `inject` | 生成「环境事实」块，写入项目 `.agent-memory/context.md` |
| `init` | 为本机生成本机实体同义词表与目标项目表 |
| `doctor` | 自检：工程目录 / Python / 依赖 / 索引 / schema 版本 / 最近入库 |

## 一次实测（约 600 会话的机器）

| agent | 会话 | 入库消息 | 来源 |
|---|---|---|---|
| dsh | 314 | 13,872 | `~/.dsh/sessions/**/session.v4.jsonl.zstd`（多帧 zstd） |
| codex | 108 | 11,002 | `~/.codex/sessions/**/rollout-*.jsonl` |
| claude | 123 | 9,133 | `~/.claude/projects/**/*.jsonl` |
| hermes | 71 | 788 | `hermes sessions export --format md` 的导出目录 |
| **合计** | **616** | **34,795** | |

检索延迟 **2.4–6.5 ms**（trigram 索引，索引命中；1~2 字中文回退 LIKE 约 100–150 ms）。

## 设计要点

1. **只索引 user / assistant 正文**，丢掉 reasoning 与工具输出 —— 工具输出是噪音大头，
   跨会话回忆要的是「人说了什么、agent 下了什么结论」。
2. **过滤 agent 注入的伪 user 消息**（`<system-reminder>`、`Current runtime context.`、
   `# AGENTS.md instructions`、`<app-context>`）—— 它们不是人说的话。
3. **双 FTS5 索引**：`unicode61` + `trigram`。中文短语必须用 `--trigram`
   （普通 FTS5 对连续中文短语不可靠）。
4. **0 次 LLM 调用**：标签靠固定清单 + 关键词与路径规则，可复现、可用测试钉住。
5. **实体同义词表是数据不是代码**（`index/entities.json`，由 `cli.py init` 生成），
   换机器不需要改代码。
6. **"迁移 ≠ 失效"**：旧路径若后继目录存在，判 🟡 并给出换算，而不是 🔴 劝退。

详见 [`docs/design.md`](docs/design.md)、[`docs/topics-a.md`](docs/topics-a.md)、
[`docs/injection-mechanism.md`](docs/injection-mechanism.md)、[`docs/staleness-design.md`](docs/staleness-design.md)。

## 目录

```
collectors/        六个来源的采集器（DSH / Codex / Claude Code / Hermes / WorkBuddy / CodeBuddy）
store.py           SQLite + FTS5 + trigram 索引（含 peer 列：工作区身份按 git origin 派生）
cli.py             命令入口
topics.py          实体归并 + 意图标签
timeline.py        结论抽取与演变时间线
premises.py        前提三路判定
inject.py          「环境事实」块压缩与落盘
skill/agent-memory/  可安装的 DSH 技能包（SKILL.md + 包装脚本 + 参考文档）
docs/              设计与验证留档（含复核记录、A/B 实验、发布留档）
tools/             探查脚本、打包与预览工具
tests/             95 条契约测试（真实样本片段做夹具；真实索引不可用时相关用例显式 skip）
index/             索引库（gitignore，可随时重建）
```

## 隐私与脱敏

本仓公开的代码与文档里**不含任何真实客户名、私有项目名或内部绝对路径**——
统一用 `demo-*` / `示例*` / `F:\demo-main` 这类占位示例。

打包/发布前的机检流程（防止再泄漏）：

```powershell
# 1) 复制词表模板并按本机实际填写（词表本身永不进仓）
Copy-Item .private-terms.example.txt .private-terms.txt

# 2) 扫描打包 stage（或 --zip 扫已产出的 zip），命中即 PACK FAIL
.\.venv\Scripts\python.exe tools\check_private_terms.py
```

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest -q      # 95 条
```

CI（GitHub Actions，Windows）覆盖 Python 3.10 / 3.11 / 3.12。
依赖真实索引库（`index/sessions.db`）的用例在全新克隆上显式 skip，不会误红。

## 边界（明确不做）

- **不调用 LLM** 做摘要 / 打标。
- **不改各 agent 的原始数据**（采集全程只读）。
- 不做「自动替你做决定」的总结 —— 只提供可核对的结论与前提状态。

## 参考与致谢

本仓为独立实现，**不含任何第三方源代码**；设计上参考过的项目（OpenViking、recall-agents、
Hermes、Helm/npm）与各自许可、参考点见 [ACKNOWLEDGEMENTS.md](ACKNOWLEDGEMENTS.md)。

## License

MIT，见 [LICENSE](LICENSE)。
