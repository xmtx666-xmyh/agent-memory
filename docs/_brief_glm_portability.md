# 请复核：agent-memory 技能「可移植化」改造

## 你的任务

只做**设计复核**，不执行命令、不改代码。指出：根本性错误 / 值得改 / 过度设计。
最后按纪律把结论写进 `F:\agent-memory\docs\_review_glm_portability.md`，回复只回一行 `WROTE <路径> <条目数>`。

## 硬性输出纪律

1. 需要材料之外信息才能判断的，必须写「待确认」并说明缺什么，不得当作缺陷上报。
2. 每条意见必须给理由/可达性论证（什么条件下会出问题），否则降级为「待确认」。
3. 允许读 `F:\agent-memory` 下的文件（只读），但**不要执行任何命令**。

## 背景

这是一个本地 Python 工具：把一台机器上多个编码 agent（DSH / Codex / Claude Code / Hermes）的
会话汇成可检索库，抽出「结论句」，判断旧结论里的路径是否已失效，并生成一个
`.agent-memory/context.md` 注入块给新会话读。

它已被打包成 DSH 技能（`F:\agent-memory\skill\agent-memory\`，安装到 `~/.dsh/skills/agent-memory/`）。

**用户的新问题**：如果把这个技能装到**另一台电脑**呢？那台电脑没有 `f:\demo-base`、
没有 `demo-kb` 这些实体（那些是本机项目名）。

## 改造前的问题（已实测审计）

技能目录里：17 处写死 `F:\agent-memory`、9 处写死 `.venv\Scripts\python.exe`、
4 处写死本机实体名（demo-kb/PageIndex/DEMO2021）、5+5 处写死 `f:\demo-base` / `f:\demo-wiki`。
代码里 `topics.py` 的 `ENTITIES` 整张同义词表也是本机专属。

## 改成了三层分离

| 层 | 内容 | 可移植 | 位置 |
|---|---|---|---|
| 工具 | cli.py / collectors / store / topics / premises / inject | 是 | 任意目录，`AGENT_MEMORY_HOME` 指定 |
| 数据 | `index/sessions.db`、`index/entities.json`、`index/targets.json` | 否，每机生成 | `<home>/index/`（gitignore） |
| 技能 | SKILL.md / references | 是 | `~/.dsh/skills/agent-memory/` |

关键改动：
1. 新增 `paths.py`：唯一决定 HOME（env > 本文件目录）、DATA（`<home>/index`）。
2. `topics.ENTITIES` 改为空表 + `load_entities(json)`；文件缺失时退化为「目录名即实体」。
   本机词典一次性迁到 `index/entities.json`（20 个实体，行为不变）。
3. 新增 `cli.py init`：从 `session_paths` 统计现存目录 → 生成 `entities.json`（每目录名自成一实体）
   → **只打印候选项目**，把 `targets.json` 写成**空表 + 填法说明**（不猜该给哪个项目生成注入块）。
   实测理由：按会话数排序会挑到 `f:\示例工具库`(21)，而真正想要的是 `f:\demo-base`(18)。
4. 新增 `install.ps1`：建 venv → 装 zstandard/pyyaml/pytest → ingest → topics → init → 打印本机实体。
5. 新增 `scripts/_resolve.ps1`：home 解析顺序 = `$env:AGENT_MEMORY_HOME` → 从脚本向上找 `cli.py`（6 层）
   → `%USERPROFILE%\agent-memory` → 报错。`am.ps1` / `refresh.ps1` 都改用它，删掉了 `F:\` 兜底。
6. `SKILL.md` 与 references 去掉全部绝对路径；实体名改成「用 `am.ps1 topics --top 20` 查本机的」。
7. 新增 `tests/conftest.py`：pytest 启动时从 `index/entities.json` 载入实体表。
   若该文件不存在（全新克隆），别名相关断言会失败——我认为这是"提示先跑 install"的合理行为。

## 请重点回答

1. 三层分离是否彻底？还有哪些**隐藏的机器相关性**我没处理（想想 collectors 的默认根、
   DB schema、意图标签表 INTENTS、`_PATH_DIR_NOISE` 那种硬编码名单）？
2. `cli.py init` **不猜** targets（写空表）是否过度保守？更好的折中是什么？
3. `entities.json` 放在 gitignore 的 `index/` 里合适吗？还是应该可版本化/可导出分享？
   注意：它承载"历代改名"这类**人工知识**，丢了要重建。
4. `install.ps1` 在「没有 uv、没有 Python 3.12、没有网络」的机器上会发生什么？值得为此加降级吗？
5. `tests/conftest.py` 依赖 `index/entities.json` 意味着**新克隆跑测试会失败**。这是设计缺陷吗？
   你会怎么改？
6. 用 `%USERPROFILE%\agent-memory` 作为默认安装位置合理吗？Windows 上有没有更合适的位置？
