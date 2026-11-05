# 设计复核：技能「可移植化」改造（_brief_glm_portability.md）

复核方法：只读 F:\agent-memory 全部相关源码与技能文件，逐条核对 brief 的声明；
无法从材料判断的一律标「待确认」。未执行任何命令、未改任何代码。

**总评：无根本性错误。三层分离（工具/数据/技能）方向正确，主体执行到位；
但有一处 brief 自己点名要查的隐藏机器相关性确实漏了（hermes 默认根），
一处测试设计缺陷会在「任何非原机的机器」上暴露（比 brief 自述的更严重），
另有若干执行残留。**

条目统计：值得改 7 ｜ 过度设计 1 ｜ 待确认 3 ｜ 根本性错误 0

---

## 一、根本性错误：无

论证：三层边界与依赖方向正确——代码只依赖 `paths.py` 取位置；每机数据
（db / entities / targets）全部落在 `<home>/index/`；技能层通过 `am.ps1`
间接寻址且报错带指路（`_resolve.ps1:27`）。`_resolve.ps1` 对 env 分支还做了
`cli.py` 存在性校验，防止 env 指向数据目录的误用。发现的问题全部在执行层
（残留硬编码、测试耦合、流程提示缺口），不动摇架构。

## 二、值得改（7 条）

### W1. hermes 采集器默认根写死 `F:\hermes-export\sessions`（Q1 直接命中）
- 证据：`collectors/hermes.py:35` `return r"F:\hermes-export\sessions"`。
  对照：dsh/codex/claude 三个采集器都是 `~/.xxx`（home 相对，可移植 ✓）。
- 触发条件：换机后跑 `ingest`——hermes 的 `find_sessions` 返回空列表，
  `cmd_ingest` 只打印「新增 0」，**不报错**。hermes 的历史在新机器上静默缺失，
  用户以为没记录。
- 建议：默认改 `~/hermes-export/sessions`（或 `~/.hermes/sessions`），
  并允许 env 覆盖（如 `AGENT_MEMORY_HERMES_ROOT`）。这正是 brief 问题 1
  里「collectors 的默认根」那一问，答案是这个确实漏了。

### W2. `templates/daily-refresh.ps1` 未迁移：代码级 `F:\` 兜底 + 整体过时
- 证据：`skill/agent-memory/templates/daily-refresh.ps1:22`
  `else { 'F:\agent-memory' }`（可执行代码，不是注释）；`:11` 的 schtasks
  示例也是 `F:\...` 绝对路径。且该模板还在用占位符 targets 数组（`:44-46`），
  是 `targets.json` 出现之前的旧设计，功能上已被 `scripts/refresh.ps1` 取代。
- 触发条件：新机器用户照 `verdicts.md` §五 的建议（「见 @templates/daily-refresh.ps1」）
  注册计划任务 → 找不到 `F:\agent-memory` 直接 throw；若那台机恰好有同名目录，
  则**静默用错 home**。brief 声明「删掉了 F:\ 兜底」对 am.ps1/refresh.ps1 成立，
  对这个模板不成立。
- 建议：删除该模板，`verdicts.md:54` 改指向 `scripts/refresh.ps1`（已读 targets.json、
  已走 `_resolve.ps1`）。保留两份做同一件事只会让其中一份烂掉——现在就是这样。

### W3. 测试套件与本机数据耦合：任何非原机的机器装完 install 仍失败（详 Q5）
- 证据：`tests/conftest.py:24` 载入 `<repo>/index/entities.json`（每机不同）；
  `tests/test_topics.py:27-33` 断言钉死本机 canonical 名（`demo-kb`、
  `示例客户项目(DEMO2021)`）；`tests/test_inject.py:19-20,82-108` 四个测试
  直接读本机真库 `index/sessions.db` 且断言 `f:\demo-base` 后继。
- 触发条件：brief 的辩护是「失败提示先跑 install」——这只在**原机**成立。
  新机器跑完 install 后，`entities.json` 是新机器的目录名实体，不含
  `demo-base→demo-kb`，`test_system_aliases_merge` 照样失败；真库更没有
  `demo-kb` 实体。测试对新机器是**永久性失败**，不是安装顺序问题。
- 建议：见 Q5 答案（fixture 固化 + 真库测试打标隔离）。

### W4. `cli.py` 的 DEFAULT_DB 绕过 `paths.py`，存在 split-brain
- 证据：`cli.py:23` 自行拼 `dirname(__file__)/index/sessions.db`；而
  `init_cmd.py:23` 用 `paths.ENTITIES_FILE/TARGETS_FILE`（= env 优先的 HOME）。
  `paths.py` 自称「唯一决定工程在哪、数据在哪的地方」，此声明不成立。
- 触发条件：`AGENT_MEMORY_HOME` 指向的目录 ≠ 正在运行的 cli.py 所在目录
  （这是 `_resolve.ps1` 支持的合法配置；直接 `python cli.py` 或计划任务不经
  `_resolve` 校验）。此时 ingest 写 `<代码目录>/index/sessions.db`，而 init
  读写 `<env>/index/entities.json`——库和词典分家，实体表对不上库。
- 建议：`cli.py` 改用 `paths.DB_FILE`（一行），消除第二真相源。

### W5. install.ps1 缺「编辑 entities.json 后需重跑 topics --build」提示
- 证据：`install.ps1:65` 的 Next 只说 review/merge renames；SKILL.md 亦无此句。
  标签是**打标时刻**固化的（`topic_build.build` 把 label 写进 `session_topics`），
  别名后加不会自动生效。
- 触发条件：新机器用户照 Next 指引手工加了 `旧名→新名` 别名，然后跑
  `am.ps1 timeline "新名"` → 空（会话还挂在旧目录名标签下），直到重跑
  `topics --build`。用户会误以为工具坏了或没记进去。
- 附带核实：装机顺序本身没问题——fresh 机上 init 生成的实体名==目录名，
  与先跑的 `topics --build`（无词典，目录名即实体）恰好一致；
  问题只出现在**事后加别名**这一步。
- 建议：install.ps1 的 Next 和 SKILL.md 首次使用一节各加一句。

### W6. `load_entities` 解析失败被静默吞掉
- 证据：`topics.py:66-67` `except Exception: pass`。
- 触发条件：`entities.json` 是设计上**要求用户手工编辑**的文件（init_cmd 的
  `_comment` 明说「别名请手工加」）。手编 JSON 打错一个逗号 → 静默退化成
  空表 → 所有别名归并失效、timeline/premises 按旧 canonical 名查询全空，
  全程无一字提示。对必手编的文件，坏文件必须喊出来。
- 建议：解析失败时向 stderr 打一行警告（文件路径 + 异常摘要）。

### W7. 遗留小项合集（各一处，顺手清）
- `inject.py:138` 与 `timeline.py:235`：直跑入口的默认实体还是 `demo-kb`
  （cli 路径不受影响，但违背「代码里不允许再出现具体项目名」的自定纪律，
  `paths.py:14`）。
- `init_cmd.py:26-28` 的 `_NOISE` 是 `topics._PATH_DIR_NOISE`（`topics.py:120`）
  的手工拷贝，注释靠「保持一致」维系。两表漂移时：一边加的噪音目录，
  另一边会把它当实体。改成 import。
- `scripts/refresh.ps1:9,13`：注释里的手工运行/schtasks 示例仍是 `F:\agent-memory\...`
  绝对路径。新机器照抄注册的任务指向不存在的路径。改成 `<home>` 占位写法。
- `references/verdicts.md:19,25` 与 `templates/context-block.md` 含本机路径
  作示例。已有顶部免责声明（「都是本机示例」），可接受；但 brief 声明
  「去掉全部绝对路径」严格说不成立，宜把措辞放宽或把示例换成 `<旧目录>`。

## 三、过度设计（1 条）

### O1.（微）`paths.python()` 与 `_resolve.ps1` 的非 Windows venv 分支
- 证据：`paths.py:35`、`_resolve.ps1:33-34` 都探查 `.venv/bin/python`。
- 论证：整套包装/安装/定时任务全部是 PowerShell（PS 5.1、schtasks、
  `c:\users` 特判见 `topics.py:141`），非 Windows 上无入口可达该分支。
  为不存在的场景写的代码，且 `_resolve.ps1` 与 `paths.py` 各写一份。
- 处置：二选一即可——删掉分支，或注释一句「Windows-only，分支仅为万一」。
  量级很小，不值得更多动作。

## 四、待确认（3 条）

### P1. INTENTS 是否需要数据化
`INTENTS`（`topics.py:79-117`）的关键词是**用户业务域**词汇（投标/招标/评标、
RAG 检索），不是机器相关——同一用户换机它依然有效，因此不违反「机器可移植」
目标，保留在代码里（可版本化、可被测试钉住）是合理取舍。**但它是否算缺陷
取决于可移植的目标范围**：若技能要发给其他用户/其他业务域的人用，INTENTS
就得像 ENTITIES 一样变成数据。brief 未说明目标用户范围——缺这个信息，判不了。

### P2. skill 装进 `~/.dsh/skills/` 的机制
brief 说技能「安装到 `~/.dsh/skills/agent-memory/`」，但 `install.ps1` 五步
里没有复制/链接 skill 目录这一步。是另有安装流程、还是手工复制？
若是手工复制，还存在 repo 副本与安装副本的同步问题（改了 SKILL.md 忘了拷，
两机行为发散）。缺：技能的实际分发方式。

### P3. entities.json 入版本库的隐私前提
Q3 的建议（见下）把它放进 git，前提是仓库可见范围可接受暴露项目名
（`demo-kb`、`DEMO2021`、投标项目名等）。缺：仓库是私有还是可公开。

## 五、六问直答

**Q1 三层分离是否彻底？还有哪些隐藏机器相关性？**
主体彻底，四点保留：① **hermes 默认根写死 F:\**（W1，确实漏了）；
② DB schema 无机器相关 ✓（纯结构，路径只作数据行存在）；
③ INTENTS 是用户域不是机器域，见 P1；④ `_PATH_DIR_NOISE` 通用 ✓
（`dp` 是 DSH 默认工作区，属工具相关而非机器相关，合理），
但 `init_cmd` 那份拷贝要改成 import（W7）。另：`c:\users\` 前缀特判
（`topics.py:141`、`init_cmd.py:45`）是 Windows 假设——整套工具本就是
Windows/PowerShell-only，一致，可接受。`skill/install_persona_hint.py:25`
写死 `C:\Users\demo\...`，但它在 skill/ 根而非随技能分发的
`skill/agent-memory/` 内，属本机一次性配置脚本，不算技能可移植性缺陷。

**Q2 init 不猜 targets 是否过度保守？**
不过度保守，是对的。理由：inject 经 refresh 每天**自动写**用户项目目录，
猜错不是一次性损失而是持续静默写错地方；且排序信号被实测证明不可靠
（`示例工具库` 21 > `demo-base` 18，见 `init_cmd.py:70-71`）；空表 + howto +
候选打印的恢复成本约 30 秒。可选折中（非必要）：把候选写进 targets.json 的
`_suggested` 字段（refresh.ps1 只读 `targets` 数组，零风险），省得用户回头
翻终端输出。仅此而已，不建议更激进的猜测。

**Q3 entities.json 放 gitignore 的 index/ 里合适吗？**
不合适，且有内在矛盾：`paths.py:23` 自己注释 DATA「**可随时删除重建**」，
而 entities.json 恰恰是唯一不可重建的东西（人工改名史）——把最不耐删的文件
放进宣称可随时删的目录。建议：`.gitignore` 的 `index/` 改为
`index/*` + `!index/entities.json`（注意 git 无法 re-include 被目录级忽略
包裹的文件，必须先放开目录级）；或把 entities.json 上移到 `<home>/` 根。
与现有逻辑的兼容性已核实：`init_cmd.py:58` 只在文件缺失时生成，clone 带来的
旧机别名表不会被覆盖，新机器从第一天就能把 `demo-base` 归并成 `demo-kb`。
前置条件是 P3（仓库可见范围）。

**Q4 install.ps1 在无 uv / 无 Python 3.12 / 无网络的机器上会怎样？值得降级吗？**
逐分支推演（基于 `install.ps1` 源码，未执行）：
- 无 python 且无 uv：`& python -m venv` 抛 CommandNotFound，`ErrorActionPreference='Stop'`
  即停，报错可读。可接受。
- 有 uv 无网络：`uv venv --python 3.12` 尝试下载解释器失败 → throw
  "failed to create .venv"；uv 的原始错误走 stderr 可见。尚可。
- 无 uv、有系统 python、无网络：venv 建成；`pip install` 失败但**没有
  `$LASTEXITCODE` 检查**（`:43`）→ 一路走到 ingest → zstandard ImportError →
  throw "ingest failed"。**根因被埋了两跳**，用户看到的是误导性报错。
  这是唯一值得修的降级点：pip 后检查退出码 + 一行提示
  （「离线？先在有网机器 pip download，或用内网 index-url」）。
- Python 3.12 并非硬依赖：无 uv 时用系统 python，代码全带
  `from __future__ import annotations`，3.8+ 语法层面兼容，无需为此加检测。
- 完整离线方案（vendored wheels）属于过度设计：个人工具、一次性安装，
  不值得为此增加仓库体积和维护。

**Q5 conftest 依赖 index/entities.json 是设计缺陷吗？**
是，且实际比 brief 描述的更严重（论证见 W3）：不是「新克隆失败、跑完 install
就好」——是**除原机之外的任何机器，装完 install 也失败**，因为断言钉的是
原机的 canonical 名和真库内容，而 install 生成的是新机器自己的数据。
「提示先跑 install」的辩护只在原机这台成立。改法（契约与数据分离）：
1. conftest 改载 checked-in 的 `tests/fixtures/entities.json`（把现
   `index/entities.json` 中测试所需的最小别名集固化进版本库）；
2. `test_inject.py` 的 4 个真库测试改用 tmp_path 合成库（`Store`+`ingest`
   的 helper 在 `test_topics.py:120-126` 已有现成模式），或打自定义 marker
   （如 `machine_data`）在真库/实体缺席时 skip；
3. 「本机数据是否健康」另立 `tools/selfcheck_machine.py`（repo 已有
   `tools/selfcheck_collectors.py` 先例），不属于 pytest 套件职责。

**Q6 %USERPROFILE%\agent-memory 作为默认安装位置合理吗？**
合理，保持。论证：该 fallback 只在「skill 装在 `~/.dsh/skills`、向上 6 层找不到
cli.py」时被用到，此时除了用户主目录没有别的可猜位置；找不到时的 throw
自带指路（`_resolve.ps1:27`），任何选择都可恢复。备选方案比较：
`%LOCALAPPDATA%\agent-memory` 更「Windows 规范」，但这是 git clone 的开发
工具，位置即克隆位置，规范目录无实际收益；`%USERPROFILE%\.agent-memory`
与 `~/.dsh`、`~/.codex` 风格一致，但会和各项目里的 `.agent-memory/`
注入目录产生名字混淆。唯一建议：把「把仓库克隆到
`%USERPROFILE%\agent-memory`，或设 `AGENT_MEMORY_HOME`」写进 SKILL.md
「首次使用」一节——现在这句话只在报错里出现。

## 附：brief 声明核对表（已验证部分）

| brief 声明 | 核对结果 |
|---|---|
| paths.py 唯一决定 HOME/DATA | 基本成立，但 `cli.py:23` 绕过（W4） |
| ENTITIES 空表 + load_entities，缺文件退化为目录名即实体 | 成立（`topics.py:37,45-73`） |
| 本机词典迁 20 个实体 | 成立（`index/entities.json` 实数 20） |
| init 只打印候选、targets 写空表+填法说明 | 成立（`init_cmd.py:68-79`） |
| _resolve.ps1 解析顺序 env→上溯 6 层→USERPROFILE→报错；删掉 F:\ 兜底 | 对 am.ps1/refresh.ps1 成立；**对 templates/daily-refresh.ps1 不成立**（W2） |
| SKILL.md 与 references 去掉全部绝对路径 | SKILL.md 成立；references 的示例路径残留但有免责声明（W7 末条） |
| conftest 从 index/entities.json 载入 | 成立，但其「合理行为」辩护不成立（W3/Q5） |
| 意图标签表不随机器变 | 成立（用户域而非机器域，边界见 P1） |
