# 复核结论：agent-memory 检索与「是否继续深度开发」四条结论

> 复核者：glm-5.3（非同源）。日期：2026-11-04。
> 范围：仅简报所列文件（store.py / topics.py / premises.py / inject.py / timeline.py / cli.py /
> docs/skill-overview.md / docs/design.md / 外部 openviking.md）。
> 本会话 Bash 与 PowerShell 均被权限拒绝，**未做任何运行时验证**；凡需运行才能定的，一律列「待确认」。
> 条目计数：判定 4 + 发现 7 + 待确认 8 + 建议 5 = **24**。

## 逐条判定

### 结论 A（战略收窄）—— 部分成立

- **A1「不应往上下文数据库方向加深」：材料内成立。** 依据：openviking.md:14-17（官方定位语
  "Unify Agent Memory, Knowledge RAG and Skills"）、:41（向量召回 + rerank 检索管线）、:24（41,475 stars，
  2026-11-04 当天仍 push）——对比本仓 store.py:53-58 纯 FTS5 双索引。「重叠区打不过」是战略判断而非
  代码可证的事实，但材料支撑方向。
- **A2「premises 是唯一不可替代」：在材料口径内成立，但「唯一」过强。** 依据：openviking.md:39-40 的
  freshness 是**摘要新鲜度**元数据（sidecar 是否该重算），不是「结论前提现在还算不算数」；全页无前提失效
  三档判定机制描述。premises.py:139-173 `judge_path`（alive / dead_with_successor / dead_no_successor）+
  inject.py:32-94 的规则压缩确为本仓独有实现。但「唯一」漏了**跨 4 agent 历史回溯采集**：openviking.md:56
  的 DSH 插件只**前向**捕获 DSH 事件流，而 cli.py:38-40 注册 dsh/codex/claude/hermes 四个回溯采集器
  （design.md:43-65 有四来源实测格式）——OpenViking 材料内无对应物。见 F7。
  ⚠️ 整个 A2 判断建立在外部文档口径上（openviking.md:95-96 自述 `verified: no`、本机未装），见 T7。
- **A3 优先级（premises 覆盖率 > 召回）：判断题，材料只能部分支撑。** 支撑面：覆盖率 1~2% 有文档出处
  （skill-overview.md:84「97% 结论无可验证前提」），且机制一致——premises.py:219-223 把无路径/端口的结论
  全部路由到 UNVERIFIED；注入块有 A/B 量化数据（skill-overview.md:73-75）而检索召回改进无量化。
  反面：检索是核心能力 1（skill-overview.md:65），转述词零命中（skill-overview.md:81）拖累所有下游功能。
  材料不足以裁定排序，**排序本身待产品决策**（不判为缺陷）。
- **A4 停止项：材料内无矛盾**；但收窄边界漏了「会话开头注入通道」与 OpenViking DSH 插件的重叠，见 F5。

**可达性**：premises 全链 = cli.py:252-256 → cli.py:163-188 → premises.py:192-243 → judge_path:139-173；
inject 全链 = cli.py:258-262 → cli.py:191-204 → inject.py:97-147 → premises.check_conclusions:99。

### 结论 B（零模型检索）—— 成立（代价面表述不完整，见 F1/F3）

逐条核实：

- store.py:54（`tokenize='unicode61'`）/ :57（`tokenize='trigram'`）——引用行号准确。
- store.py:118-136 `search()` 确为 `WHERE {t} MATCH ? ORDER BY rank`（MATCH 在 :128，rank 在 :129）。
  **「ORDER BY rank 默认是 BM25」成立**：FTS5 内置 rank 默认为 BM25（k1=1.2, b=0.75），且更优匹配数值更低，
  `ORDER BY rank` 升序即最优在前——store.py:129 的用法正确。此为 SQLite 文档化行为，非本会话实测（T1 同源）。
- topics.py 打标零模型：INTENTS 固定词典 topics.py:84-122；ASCII 词边界正则 :168-177（`_kw_matcher`，
  边界排除集含 `_`）；命中强度阈值 :225-259（`label_session`，≥2 次或具体词）。
- 其它检索路径同样零模型：`topics --entity` = store.py:220-241 `sessions_for`（纯 SQL，表结构 :61-77）；
  `timeline` = timeline.py:130-152 `extract_conclusions`（正则 :38-52）；`premises` = premises.py:55-82
  （PATH_RE :38 / PORT_RE :39）+ os.path.exists（:151）。**唯一未验路径**：`topics --build` 经
  cli.py:111 `from topic_build import build` 进入 topic_build.py——该文件不在材料清单（T2）；
  `init` 经 cli.py:93 进 init_cmd.py，同样未读（T2）。
- 「34k 条 6.3 ms」：与 skill-overview.md:8「2~7 ms（624 会话 / 3.5 万条）」相符，单点数字本会话不可复测（T6）。
- 代价面缺口：**1~2 字中文查询在两个索引上均无法命中**——依据 SQLite 文档：trigram 只索引 3 字符滑动窗，
  <3 字符的 MATCH 查询不产生任何 trigram；unicode61 把 CJK 连续段当作**单一 token**（不切分），子串查询
  无法命中。此条与 store.py:5-6 注释「按单字/二元切分」的机制描述矛盾（F1/F2，实测复现见 T1）。

**可达性**：检索主路径 = cli.py:224-228（search 子命令，`--trigram` 在 :227）→ cli.py:71-83 `cmd_search` →
store.py:118-136 → messages_fts（store.py:53-55）/ messages_trgm（:56-58）。

### 结论 C（默认关闭的语义第三路）—— 部分成立

- **方向成立**：不替换 FTS5、默认关闭，保住零依赖路径，与仓内纪律一致（design.md:29「索引与搜索不调
  LLM」；timeline.py:4-6 的可复核理由）。embedding 不是 LLM，但 RRF 融合后的排序不再能由
  `WHERE MATCH` 完整解释——与「可复核」纪律有张力，结论 C 未提及（低）。
- **问题 2 的回答**：RRF 是排名加法（Σ 1/(k+rank)），一路为空只是该项贡献为 0，**数学上不需要权重/归一化
  处理**；但「FTS5 命中为 0 才启用」的触发模式下**只剩一路，根本没有融合发生**——「RRF 融合」只在实际
  双路并存（显式 `--semantic`）时成立。表述上应区分（F4①）。
- **成本评估有缺口**：① 按需触发 + Ollama 不在时同查询「时有时无」，无回退语义定义（F4②）；
  ② 体积估算 35~140 MB 假定约每消息一个向量，但单条正文上限 20000 字符（store.py:7），长消息分块后
  向量数可为消息数的数倍，上限可能低估（F4③，实测分布见 T5）；③ ~50 ms 查询延迟假定 Ollama 热常驻
  （冷加载是秒级），未验证（T8）；④ 一次性嵌入 34k 条的计算耗时与后续 ingest 的增量嵌入成本未计。
- 「同构于 F:\demo-base 的 rrf.py」不可验（T4）。

### 结论 D（注入块价值量级）—— 部分成立

- 数字有文档出处且引用准确：skill-overview.md:73-75（「16 次工具调用 vs 2 次（−87.5%）」；
  「本地 9B 0/3 → 3/3」）。
- 但这是 **n=1 个任务（Codex 找文件）+ n=3 个问题（9B）** 的一次性 A/B。skill-overview.md:73 以
  「实测价值——」呈现、无量级外推限定；作为结论 D 的「价值量级判断依据」证据强度不足，存在被过度引用
  的风险（F6）。实验文档（skill-overview.md:4 引用的 ab-injection-result.md / ab-codex-replication.md）
  不在材料清单，任务选取与对照设置不可核（T3）。

## 发现的错误或过度自信

- **F1（中）结论 B 代价面遗漏：1~2 字中文查询双索引零命中。** trigram 需 ≥3 字符；unicode61 下 CJK 连续段
  为单一 token，中文子串查询默认路径基本不命中（这正是 skill-overview.md:54「中文必须 --trigram」的成因，
  但该文档也没说 trigram 的 3 字符下限）。依据 SQLite 官方文档；本会话无运行权限复现（T1）。
  可达性：cli.py:227 `--trigram` → store.py:120 表选择 → :128 MATCH。
- **F2（低）store.py:5-6 注释机制描述疑误。**「普通 FTS5 对连续中文按单字/二元切分」与 SQLite 文档不符
  （unicode61 不切分 CJK，整段为一个 token）；结论（需 trigram）对、机制错。可达性：该 docstring 描述的
  正是 store.py:53-55 建的 messages_fts。
- **F3（低）FTS5 查询语法错误被静默吞掉。** store.py:132-135 `except sqlite3.OperationalError: return []`——
  含引号/特殊语法的查询（如 `C++`、未闭合引号）返回零命中，「查询非法」与「真的没有」不可区分，会放大
  F1 的误判。可达性：cli.py:74 → store.search → :134。
- **F4（中）结论 C 成本/设计三缺口。** ① FTS5=0 触发模式下 RRF 实际不参与（单路退化，见 C 判定）；
  ② Ollama 缺席时无回退语义，结果「时有时无」且无提示；③ 体积估算未计长消息分块（正文上限 20000 字符，
  store.py:7）。可达性：①的触发条件即结论 C 自身的设计；③ 影响所有经 store.py:110-113 入库的消息。
- **F5（中）结论 A 收窄边界遗漏「注入通道」重叠。** OpenViking DSH 插件已在会话开始注入记忆画像 + 技能
  清单（openviking.md:55），与本仓 inject（cli.py:258-262 → inject.py:97-147）使用同一通道；差异化只在
  内容（前提失效），不在通道。停止清单未处置共存/冲突。可达性：两条注入路径均作用于 DSH 会话开头。
- **F6（低）结论 D 数据被过度引用。** skill-overview.md:73-75 把单任务 A/B 写成「实测价值——」，无量级
  限定（详见 D 判定）。可达性：该数字即结论 D 的全部依据。
- **F7（低）结论 A 两处措辞过度。** ①「唯一不可替代」漏了跨 4 agent 回溯采集（openviking.md:56 仅 DSH
  前向捕获；cli.py:38-40 四采集器）；②「OpenViking 存的是你们说过什么」不准确——openviking.md:43-44 是
  VLM 抽取的提炼式记忆（profile/entities/experiences…），非原话存储。

## 待确认

- **T1** SQLite unicode61 / trigram 对 1~2 字中文查询的运行时行为（F1/F2 的实测复现）。缺：运行权限
  （本会话 Bash/PowerShell 均被拒），需放开一段内存内 sqlite 测试或人工执行。
- **T2** topic_build.py（cli.py:111 引用）与 init_cmd.py（cli.py:93 引用）不在材料清单——`topics --build`
  与 `init` 全链路是否零模型，待读这两个文件。
- **T3** docs/ab-injection-result.md 与 docs/ab-codex-replication.md（skill-overview.md:4 引用）——结论 D
  的任务选取、对照设置、样本量。
- **T4** F:\demo-base\rrf.py 的加权融合实现——结论 C「同构」的依据。
- **T5** 34k 条消息的实际长度分布与 embedding 分块策略（F4③ 体积复核的前提；需查 index 库，本会话禁跑命令）。
- **T6** 「6.3 ms / 34k 条」单点数字（与 skill-overview.md:8 的 2~7 ms / 3.5 万条相符，本会话不可复测）。
- **T7** OpenViking 的实际运行行为（openviking.md:95-96 自述 verified: no、本机未装）——A 的「功能不重叠」
  判断仅基于官方文档口径。
- **T8** Ollama 本机 embedding 查询延迟（~50 ms 假定）与常驻资源占用——需实测。

## 我建议的下一步

1. 放开一次内存内 SQLite 行为测试钉死 T1，随后修 store.py:5 注释，并在 skill-overview 的检索边界补
   「1~2 字中文在两个索引上都查不到」。
2. store.py:134 给 FTS5 查询语法错误加可见报错，区分「零命中」与「查询非法」（配合 F1/F3）。
3. 语义第三路落地前：定义 Ollama 缺席的回退与提示语义；FTS5=0 触发模式下不称 RRF（单路无融合）；
   体积估算按分块策略重算（T5）。
4. skill-overview.md:73-75 的 A/B 数字加「单任务、n=1 / n=3」限定，避免被当通用增益引用。
5. 收窄边界补一条：注入通道与 OpenViking DSH 插件的共存 / 让位策略（F5）。
