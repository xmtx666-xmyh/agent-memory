# 平台包干净目录验收（2026-11-04）

> 起因：上一轮交付了 `dist/agent-memory.zip`，当时**明确标注两条未实测**：
> ① bootstrap 需要联网装依赖；② 打包路径分支没在干净环境跑过。
> 本轮把包解压到**空目录**（`F:\tmp\am-cleanroom\`，无 venv / 无 index / 不继承工程环境）实跑，
> 补齐验收；随后平台上传被拒（目录层级超限），又按平台规则重排布局并**重跑全套验收**。

## 验证状态

- **已实测（本机，2026-11-04）**：干净目录解压 24 条目 → `bootstrap.ps1` exit 0（建 venv、装依赖、
  ingest 555 会话、topics、init、打印实体）→ `am.ps1` 的 `stats / search / premises / timeline / inject`
  全部 exit 0。**两轮**：修复 4 处代码/文档缺陷后一轮，平台布局重排后再一轮。
- **平台层**：第一版（`scripts\engine\...`）被拒，报
  `解析失败：目录层级超限 — Skill 包仅支持两级目录结构（根目录/二级目录/文件），请移除子目录嵌套`。
  按此规则重排为「引擎在 zip 根 + 一级子目录」并加机检断言；**尚未拿到第二次上传结果**。
- **仍未验证**：真实沙箱环境里的执行策略、路径长度、升级替换行为；离线安装（无降级方案）。

## 一、干净目录实测暴露并修掉的 4 个缺陷

### D1 `bootstrap.ps1` 假定 `python` 在 PATH（致命，装不上）

- 现象：`& python -m venv` → `The term 'python' is not recognized`，exit 1。
- 本机事实：PATH 上**没有** `python`；有 `uv`（`…\hermes\bin\uv.exe`）与 `py` 启动器。
  工程里的 `install.ps1` 有 uv 分支所以一直没事，**打包时把这段健壮逻辑丢了**。
- 修法：`bootstrap.ps1` 改为真实源文件（`skill/agent-memory/scripts/bootstrap.ps1`），解释器发现
  顺序 `uv → py 启动器 → PATH 上的 python → 常见安装目录`，都没有则明确 `throw`；
  uv 建的 venv **不带 pip**，故依赖安装走 `uv pip install --python <venvPy>`（实测 `pip.exe` 不存在）。
  另把 `$PSScriptRoot` 解析成绝对路径——`-File scripts\bootstrap.ps1` 时它是相对路径。
- 证据：修后 `EXIT=0`，ingest 输出 555 会话。

### D2 SKILL.md 让用户去跑包里**不存在**的 `install.ps1`（致命，文档误导）

- 平台包里没有 `install.ps1`（它在 git 工程根），但 `SKILL.md`「首次使用」写着它，用户照做必失败。
- 修法：改指 `scripts\bootstrap.ps1`，并补解释器顺序、数据位置、失败处理三条。

### D3 `refresh.ps1` 注释里写死 `F:\agent-memory`

- 与「代码不含盘符/项目名」的可移植承诺自相矛盾，复制到别的机器就是错的命令。
- 修法：改成 `<skill>\scripts\refresh.ps1`。

### D4 `inject` 把**还存在**的目录写成「已确认失效（勿照做）」（真误导）

- 现象：注入块出现 `- c:\users 已不存在`，而 `C:\Users` 明明存在。
- 根因两层：① 一条结论只要任一路径消失就标 dead，渲染时把该结论 `paths[:3]` **全部**写成"已不存在"；
  ② `project_dir_of()` 按设计只取前两段，把 `C:\Users\demo\.codex` 折成容器 `c:\users`。
- 修法：抽出 `inject._render_dead(items)`——路径本身存在则跳过；折出的项目目录是容器
  （`_CONTAINERS`）或仍存在也跳过；没有任何真实条目就不输出该小节。
- 证据：修后 `c:\users` 命中 **0**，条目 4 → 3（其余三条确实不存在）。
- 回归：`tests/test_inject.py` 新增 3 条；`pytest tests -q` → **68 passed**。

## 二、平台拒绝：目录层级超限（本轮主要变更）

### 规则（来自平台报错原文，不是猜测）

> 仅支持两级目录结构（根目录/二级目录/文件）

即：文件只能在 **zip 根** 或 **根下一级子目录** 里；`scripts\engine\cli.py` 已超限，
`scripts\engine\collectors\base.py` 更超。参考已通过审核的包（`tender-decode.zip`、
`bid-risk-check.zip`）也是这个形状：`SKILL.md` + `requirements.txt` + `scripts\*.py`。

### 新布局（22 → 现行）

```
agent-memory.zip            （24 条目 / 57.9 KB / 最大层级 2）
├── SKILL.md                ← zip 根
├── requirements.txt
├── cli.py, paths.py, store.py, topics.py, topic_build.py,
│   premises.py, inject.py, timeline.py, init_cmd.py    ← 引擎放根
├── collectors\             ← 一级目录（collectors\base.py）
├── references\, templates\ ← 各一级
└── scripts\                ← am.ps1 / bootstrap.ps1 / refresh.ps1 / _resolve.ps1
```

为什么这样最省：仓库根**本来**就是引擎目录（`cli.py` + `collectors\` 都在仓库根），
所以包树 = 仓库子集，**零改写、零 import 变换**，打包物即被测物。

配套改动：
- `_resolve.ps1` 的平台分支从「`scripts\engine\cli.py` 是子目录」改为「`scripts\` 的**上一级**有 `cli.py`」；
- `bootstrap.ps1` 的 venv/依赖/`cli.py` 全部按 `<skill>` 根计算（`.venv` 与 `index\` 落在技能根）；
- `pack_platform.ps1` 删掉两处「打包时改写源文件」的步骤（frontmatter 补 slug、`_resolve.ps1` 插 engine 分支），
  源文件即最终物；新增机检：**任何条目层级 > 2 直接 `throw`**。

### 重排后的验收（第二遍，干净目录 `agent-memory4`）

```
Expand-Archive dist\agent-memory.zip → F:\tmp\am-cleanroom\agent-memory4   # 24 文件，最大层级 2
scripts\bootstrap.ps1  → EXIT=0（建 venv → uv 装依赖 → ingest 555 → topics → init → 打印实体）
scripts\am.ps1 stats   → exit 0（555 会话 / 34,370 条）
scripts\am.ps1 search PageIndex --trigram --limit 2 → exit 0，6.6 ms
scripts\am.ps1 premises demo-wiki --top 2 → exit 0
scripts\am.ps1 timeline demo-wiki 检索与排序 --per 1 → exit 0
scripts\am.ps1 inject demo-wiki --write <项目>\.agent-memory\context.md → exit 0，c:\users 命中 0
```

## 三、遗留（取舍，不是缺陷）

1. **首次装要联网**：`zstandard` / `pyyaml` 要下载；没做离线 wheel 兜底（体积翻几倍）。
2. **数据写在技能目录内**：`<skill>\index\`（本机 555 会话库约 117 MB）。平台升级若整目录替换，
   索引会丢——重建 `ingest` 约 45 秒。想换位置设 `AGENT_MEMORY_HOME` 指向技能根。
3. `refresh.ps1` 在**平台布局下的完整跑通**未单独实测（解析逻辑与 `am.ps1` 共用，
   但 `schtasks` 注册示例只在本机工程布局跑过；本项目本来就决定不注册定时任务）。
4. 平台第二次上传结果未拿到（见「验证状态」）。
