# 复核结论（第 2 轮）— glm-5.3，2026-11-04

> 被复核方：DeepSeek 系模型。只读简报所列文件；未跑 ingest、未读 index/、未改任何其它文件。
> 每条判定附 `文件:行号` + 可达性论证；给不出可达性的一律降级「待确认」。

## 逐条判定

### 1. peer（工作区身份）按 git origin 派生

- **(a) 成立。** `peers.py:83-90`：主仓 common-dir = `<root>/.git` → `dirname` 得根；linked worktree 的 common-dir 指向主仓 `.git` → 同根 → `peer_for_cwd`（peers.py:97-100）在根上读 origin，主仓/worktree 必同 peer。老 git 两级回退：`--git-common-dir` 相对路径按 `join(cwd, rel)` 处理（peers.py:87-89），git 对相对输出以 cwd 为基准，正确；worktree 下 git 返回绝对路径，`join` 亦正确。测试可达：tests/test_peers.py:56-74（子目录 + worktree 归并）。
- **(b) 成立。** `peers.py:95-96` 非 dir/空 cwd 返回 ""；`peers.py:103-105` 无 origin 回退 `path-<目录名>-<sha1(root.lower())[:8]>`；小写哈希在 Windows 大小写不敏感路径下稳定。未猜盘符。测试可达：tests/test_peers.py:39-47。
- **(c) 成立。** 老库路径：`Store.__init__`（store.py:139）先 `executescript(SCHEMA)`——SCHEMA 里 `CREATE TABLE IF NOT EXISTS sessions`（store.py:26-43）对老表是 no-op，SCHEMA 内两个索引（store.py:44-45）不引用 peer 列，不崩；`_migrate`（store.py:147-159）先 `PRAGMA table_info` 判缺列再 ALTER，索引 `idx_sessions_peer` 只在 ALTER 之后建——若放 SCHEMA，老表无 peer 列时 `CREATE INDEX` 会 `no such column` 使 executescript 抛错，注释（store.py:156-157）的论断正确。幂等：重复 init 时列已存在、`CREATE INDEX IF NOT EXISTS`，均 no-op。
- **(d) 成立。** `store.py:311` `only_missing=True` 时 WHERE 限定 `peer IS NULL OR peer=''`，只补空值；`store.py:313-321` 按 cwd 缓存且异常收敛为 ""；幂等契约有测试钉住（tests/test_store.py:144-145）。附注：peer_fn 返回 "" 的会话每次 backfill 都会被重扫（scanned 计数含它们），下次可自愈，可接受。
- **(e) 部分成立。** 参数顺序正确：FTS 路 SQL 占位符顺序为 `MATCH ? / peer ? / LIMIT ?`（store.py:203-206, 225-227, 230），LIKE 路 `text ? / peer ? / LIMIT ?`（store.py:259-270），与 params 元组顺序一致。**但 FTS 路的 `AND s.peer LIKE ?`（store.py:225）没有 `ESCAPE '\'` 子句**，而参数侧用了 `_like_escape(peer)`（store.py:230）——转义在该路径无效（详见「发现」#1）。

### 2. WorkBuddy / CodeBuddy 采集器

- **(a) 行为成立，论证有一处不成立。** `extract_user_text`（workbuddy.py:57-67）先取 `<user_query>` 再剥 `<system-reminder>` 块，在 user 消息入口调用（workbuddy.py:108），测试钉住（tests/test_workbuddy.py:46-60）。**但"会被 `is_injected_context()` 整条丢掉"这一论证不成立**：workbuddy.py 的导入清单（workbuddy.py:27-29）不含 `is_injected_context`，整个 workbuddy/codebuddy/cli/store 管线中无任何调用点；且该函数的前缀 `<system-reminder>`（collectors/base.py:215-216）用 `startswith` 匹配，**匹配不了实测中带属性的形式 `<system-reminder data-role="x">`**（首字符序列是 `<system-reminder ` 空格而非 `>`）。行为对，依据错 → 过度自信（详见「发现」#2）。
- **(b) 成立。** `workbuddy.py:88-89` `if not meta.cwd and ev.get("cwd")` 对**任意事件类型**兜底（含 function_call，tests/test_workbuddy.py:30-32, 55 可达）；全文件无任何按 slug 反推路径的逻辑（slug 只出现在目录遍历 glob，workbuddy.py:46）。
- **(c) 成立。** `workbuddy.py:96-100` function_call 只 `tool_call_count += 1` + `path_dirs_from_args` 抽目录后 `continue`；`workbuddy.py:101-105` 非 message 类型与非 user/assistant 角色全部跳过。reasoning / function_call_result / file-history-snapshot 均不进 records。
- **(d) 机制成立，是否实际发生待确认。** 可达性：codebuddy.py:15 两个根（`~/.codebuddy/projects`、`~/.codebuddycn/projects`）→ `collect`（codebuddy.py:22-34）统一用 `AGENT="codebuddy"` → `session_key = "codebuddy:<uuid>"`（base.py:61-62）→ `store.upsert_session`（store.py:171-174）对已存在 session_key **直接 return False，不比对内容、不记日志**。即两份内容不同的文件只留 `find_sessions` 排序（workbuddy.py:47）后的第一份。是否真有同 id 不同内容的碰撞，需实际目录比对 → 待确认；但"静默"本身成立（cli.py:59-60 只把 skipped 计数，不区分原因）。是否应写进文档：是（见建议）。
- **(e) 代码层成立，量级数字待确认。** 坏行跳过：workbuddy.py:82-85；单文件异常不中断：workbuddy.py:133-138 / codebuddy.py:27-33 的 per-file try/except；超长内容由 `clean_text` 20000 截断兜底（base.py:186-196），87 KB 行只是被 json.loads 正常解析后截断，不会崩。「实测 87,136 字符」的量级需读原始数据才能核 → 待确认（非缺陷）。

### 3. search 的"宽松重试"

**部分成立（边界基本合理，两处需注意）。** 可达性：`store.search`（store.py:233-245）仅在 `sqlite3.OperationalError` 时走 `_relax_query`（store.py:110-125）；含 `[+\*^()"]` 任一即返回 None 报 `QueryError`（store.py:122-123, 107）；只含 `- : .` 的 whitespace 分词逐 token 包短语（store.py:124）；`relaxed == query` 时（无可宽松 token）仍报错（store.py:239）——即错误原因不在 `-:.` 时不会被吞。契约有测试（tests/test_store.py:91-97）。

- `qwen3.5:9b`：含 `.` `:` → 包成 `"qwen3.5:9b"` 短语，unicode61 分词后按相邻 token 匹配，可搜。
- **该报错却被吞的点**：触发条件是 OperationalError 而非"语法错误"——若错误实为 `database is locked` 等瞬态错误而查询恰含 `-`，宽松重试成功会掩盖真实故障（store.py:235-243）。低危。
- **另一处**：LIKE 回退 `_search_like` 把 OperationalError 吞成 `[]`（store.py:273-274）——回退路上的真错误（锁/IO）伪装成"没命中"。低危，与本轮改动同源。
- `a-b c`、中文+连字符、trigram 表上的短语行为：**待确认**（需内存 FTS5 实验验证 `-` 在无空格时的具体解析，超出本次只读材料范围，不当作缺陷报）。

### 4. 知识库目录 sidecar

- **① 成立（机制），风险可接受。** `lint.py:83` `glob("*.md")` + 显式 `not p.name.startswith(".")`——pathlib 的 glob 本就**能**匹配点文件，故显式排除是必要的；副作用是任何点开头的真实页面（如 `.foo.md`）确实永远逃过 lint（frontmatter/超长/出站链接检查）。可达性：lint.py:83 → check() 的 pages/known（lint.py:93-97）。但反向可见：其它页 `[[foo]]` 链它会被判断链（`foo` 不在 known，lint.py:129-131），且 SCHEMA.md:20 约定文件名必须小写连字符英文 slug——点开头命名本身违约。综合：低风险，建议在 SCHEMA.md 的 sidecar 条目里补一句"不要用点开头命名页面"即可。
- **② 成立（total_entries 口径一致；check_at 不参与判定）。** 三处计数同口径"非点 .md"：sidecar 写入 `pages_of`（sidecar.py:86）、sidecar `check()` 实际数（sidecar.py:164）、lint ⑧ 实际数（lint.py:183）。`total_entries = len(rows)`（sidecar.py:104, 114）。注意 `check_at` 只被写入（sidecar.py:113）而**从未被比较**——lint ⑧ 与 sidecar --check 都只比 total_entries（lint.py:179-187、sidecar.py:168-174）。「带 check_at」的表述易让人以为它参与新鲜度判定，属措辞略过度自信（详见「发现」#3 的连带项）。
- **③ 成立。** sidecar 写在四个页面目录（sidecar.py:143-150），而 raw 漂移扫描只扫 `raw/` 子树（lint.py:159），且扫描内再排除点文件（lint.py:160-161）。双重不命中，sidecar 不可能参与 sha256 漂移检查。

### 5. 技能同步方案（覆盖安装 + junction）

**基本稳妥，但有四个待确认点，其中两个足以阻塞执行。**

- **junction vs `AGENT_MEMORY_HOME`**：junction 确实更适合"DSH 宿主已启动"场景——`_resolve.ps1` 每次脚本执行都重新 `Test-Path`（skill/agent-memory/scripts/_resolve.ps1:33-34），文件系统 junction 对已运行进程立即可见；环境变量则要新进程才继承。结论：本场景 junction 优先，`AGENT_MEMORY_HOME` 留作显式覆盖档（_resolve.ps1:19-22 第 1 档本来就优先）。
- **解析路径可达性**：装仓库版 `skill\agent-memory\`（scripts\ 里无同级 cli.py）→ 第 2 档 `_resolve.ps1:24-25` 失败 → 第 3 档向上走 6 层（_resolve.ps1:28-32，`~/.dsh/skills/...` 上层无 cli.py）失败 → 第 4 档 `%USERPROFILE%\agent-memory`（_resolve.ps1:33-34）**靠 junction 命中 `F:\agent-memory\cli.py`**。链路成立。但注意：若装的是**平台包**（引擎在技能根，skill-overview.md:17-18），第 2 档直接命中技能目录、junction 不会被用到——两种安装物不要混。
- **待确认 a**：`Resolve-AmPython`（_resolve.ps1:38-46）优先找 `$amHome\.venv\Scripts\python.exe`——`F:\agent-memory` 下是否已有 .venv，材料无法判断；没有则退到 PATH 的 `python`，依赖是否齐未知。
- **待确认 b（阻塞）**：已安装目录里是否有**本机数据**需保留——skill-overview.md:18 说平台包数据落 `<skill>\index\`、skill-overview.md:99 说 `index/entities.json` 是每机生成的。"全量覆盖"如果含删除多余文件，会丢本机实体表/注入目标；纯文件覆盖（不删多余）则 index\ 会幸存。缺已安装目录的文件清单（不在可读材料内）→ 待确认，覆盖前必须先备份比对。
- **待确认 c（问题 4）**：DSH 读到旧文件的风险——脚本是按次执行的，无缓存问题；但 SKILL.md 的 description 进 skill catalog 做语义匹配（skill-overview.md:27-31），catalog 是否热加载、覆盖后要不要重启 DSH，材料内无信息 → 待确认。稳妥做法：覆盖后重启一次 DSH 宿主。
- **junction 的固有代价**（非缺陷）：机器本地魔法、`F:` 掉线时第 4 档 Test-Path 失败 → throw（_resolve.ps1:35，符合"不静默猜"的设计）；换机不可移植，与 `path-` peer 回退同病。

## 发现的错误或过度自信

1. **[低] FTS 路径的 peer 过滤缺 `ESCAPE` 子句，`_like_escape` 在该路径失效。**
   `store.py:225` `peer_sql = "AND s.peer LIKE ?"`（无 ESCAPE），而 `store.py:230` 传入的是 `_like_escape(peer)` 转义后的串。无 ESCAPE 时 `\` 是字面量、`_`/`%` 仍是通配符。触发路径：`cli.py:283-284` `search --peer path_demo` → `store.py:225,230` → 模式 `%path\_llm%` 被解释为"字面反斜杠 + 单字符通配 + llm"，**搜不到** `path-demo-base-…`（用户以为没数据）。影响面有限：归一化 peer 值本身只含 `[a-z0-9.-]`（peers.py:74-75），数据库侧无误配；仅用户输入含 `_ % \` 时语义错。修法：给 store.py:225 补 `ESCAPE '\\'`（与 store.py:259 对齐）。
2. **[低/文档] workbuddy 注释与 design.md 对 `is_injected_context()` 的引用是错误依据。**
   `workbuddy.py:14`、`docs/design.md:97` 声称不提取 user_query 就会被 `is_injected_context()` 整条丢掉。实际上：(i) 该函数未在本轮任何改动文件中被调用（workbuddy.py:27-29 导入清单、codebuddy.py、cli.py、store.py 均无调用点）；(ii) 即便调用，`_INJECT_PREFIXES` 的 `"<system-reminder>"`（base.py:216）用 `startswith` 匹配不了实测格式 `<system-reminder data-role="x">`（tests/test_workbuddy.py:24 里的正是带属性形式）。行为正确是 `extract_user_text` 本身的功劳，与该函数无关。若其它采集器（dsh/codex/claude/hermes，不在可读清单）依赖它剥带属性的 reminder，那里才可能有真问题 → 待确认。
3. **[低] `.overview.md` 不在任何校验范围内。**
   `write_all` 分别写 `.abstract.md` 与 `.overview.md`（sidecar.py:149-150），但 lint ⑧ 只读 `.abstract.md`（lint.py:176）、sidecar `check()` 也只读 `.abstract.md`（sidecar.py:163）。`.overview.md` 写失败/被删/过期均检测不到，而 lint 仍报"新鲜"。触发路径：`python _meta/lint.py` → lint.py:174-187。修法：⑧ 里对 `.overview.md` 做存在性检查即可（内容可比 total_entries 行）。
4. **[info] CN/AI 双根同 id 静默去重无任何告警。** 见逐条 2(d)：`store.py:171-174` 跳过时不区分"完全相同的镜像"与"内容不同的两份"，调用方只看到 skipped +1（cli.py:59）。机制层面成立；是否造成实际丢内容待确认，故不计缺陷，但至少应打一行"同 key 不同 message_count，留 first"的警告。

（问题 2 的补充回答：peer LIKE 子串语义下 `demo-base` 确会命中 `demo-base-old` 一类前缀相同的 peer——机制在 `store.py:225` 的 `%…%`；这是 store.py:219 明示的取舍（"子串匹配，便于只写仓库名"），**可接受非缺陷**，`--peer` help（cli.py:284）已写"子串匹配"。）

（问题 3 的回答：**不建议**改成"内容不同则两者都留"。代价：破坏 ingest 幂等契约（tests/test_peers.py 无关，tests/test_store.py:53-58 钉死"重跑 added=0"）；镜像目录（若两根是同一会话的两份拷贝）会翻倍入库，timeline/检索出现双份噪音；session_key 不再是稳定主键。更小的改法：碰撞时比对 message_count 或正文哈希，不同则打警告（见建议 #3）。）

## 待确认

1. **FTS5 组合语义**（逐条 3）：`a-b c` 无空格 `-` 是否本就解析为 NOT 而不报错（若是，则宽松重试根本不触发、结果静默偏差）；中文+连字符；trigram 表上宽松短语的命中行为。缺：内存 FTS5 实验结果（本次约束禁跑，只读材料无法判定）。
2. **`is_injected_context` 的真实调用方**（发现 #2）：dsh/codex/claude/hermes 采集器是否调用它、以及它们遇到的 reminder 是否带属性。缺：这四个文件不在可读清单。
3. **CN/AI 双根是否实际存在同 session_id 且内容不同的文件**（逐条 2(d)）。缺：`~/.codebuddy` 与 `~/.codebuddycn`（及 workbuddy 两根）的目录比对。
4. **技能方案**（逐条 5）：a) `F:\agent-memory` 是否已有 `.venv`；b) `~/.dsh/skills/agent-memory/` 现有文件清单（是否有本机 `index\entities.json` 等需保留物）；c) DSH skill catalog 是否热加载（覆盖后要不要重启宿主）。三者都在可读材料之外。
5. **87,136 字符的实测量级**（逐条 2(e)）：需读原始 JSONL，本次禁读数据目录；代码路径本身不依赖该数字成立。

## 建议的下一步

1. `store.py:225` 补 `ESCAPE '\\'`，与 `_search_like`（store.py:259）对齐；顺带补一条 `--peer path_demo` 的契约测试。
2. 修正 `workbuddy.py:11-14` 与 `docs/design.md:96-97` 里 `is_injected_context()` 的错误引用；同时核实该函数在 dsh/codex 采集器里的调用与带属性 reminder 的匹配问题（待确认 #2）。
3. `upsert_session` 碰撞（store.py:171-174）时比对 message_count，不同则 print 一行警告，保住幂等的同时消灭"静默"。
4. lint ⑧（lint.py:174-187）给 `.overview.md` 加存在性检查；SCHEMA.md 的 sidecar 条目补"页面文件不得以点开头命名"。
5. 技能覆盖前：先备份 `~/.dsh/skills/agent-memory\` 并 diff 出本机数据（尤其 `index\`）；确认 `F:\agent-memory\.venv` 存在；覆盖后重启一次 DSH 宿主以刷新 catalog（待确认 #4 全部落地后再执行）。
