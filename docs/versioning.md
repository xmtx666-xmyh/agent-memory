# 版本与发布策略（调研 + 本仓做法）· 2026-11-04

> 触发：技能上架平台后出现了「安装 2 / 调用 28」，同时暴露两个现实问题：
> ① 一个版本号（1.4.0）先后对应两份不同内容；② 用户装完没初始化时只看到一句英文报错。
> 于是去看别人怎么做版本更新，挑能直接用的落进本仓（有差距的记在最后一节）。

## 一、调研到的四套做法（按可借鉴度排序）

| 来源 | 做法 | 可借鉴点 |
|---|---|---|
| **Helm**（[Charts 文档](https://helm.sh/docs/topics/charts/)） | 包必须带 SemVer `version`，且**包名 = `name-version`**；另有 `appVersion` 表示里面装的应用版本，"informational，不影响 chart 版本计算"；弃用用 `deprecated: true` **并同时升版本** | **包版本与内容版本分离**：一个号不能盖两份内容；弃用要显式标记且升号；版本号要能被机器当成"发布标记"用 |
| **OpenViking**（[版本管理指南](https://docs.openviking.ai/zh/guides/15-snapshot)） | 对**数据**做 git-oxide 快照：`commit / log / show / restore`；restore 是**正向恢复**（在当前 HEAD 之上追加提交，不改写历史），先 `dry_run` 预览；`.ovgitignore` 排除不该进快照的路径 | **包版本与数据版本分开管**；恢复要可预览、可追溯、不改写历史；用 ignore 规则把"派生数据"排除在版本之外 |
| **Claude Code 插件市场**（[host-marketplace](https://code.claude.com/docs/en/plugins/host-marketplace)） | 市场条目带 `version`；宿主可配 `autoUpdate`；**从本地路径 in-place 加载的插件不受版本控制** | 市场按版本分发 + 可自动更新；但"就地加载"会绕开版本，所以**版本必须来自包内文件**而不是安装位置 |
| **npm**（[dist-tag](https://docs.npmjs.com/cli/v11/commands/npm-dist-tag)，registry 实测） | `latest` / `next` 等 dist-tag 做发布通道；每个包带 **SLSA provenance 证明**与签名（本次查 `@openviking/dsh-memory-plugin` 的 registry 元数据里就能看到 attestations） | 需要灰度/预发布时用通道而不是只改版本号；发布物带哈希/来源证明，便于核对"装的是不是我发的那个包" |

## 二、本仓的缺口（对照上面四条）

| 缺口 | 证据 | 后果 |
|---|---|---|
| 版本号与内容不绑定 | 1.4.0 对应过 `ebc8019` 与 `aa5ebbb` 两份内容 | 平台只有一个 1.4.0，回滚/对比/"用户装的是哪版"失去依据 |
| 数据版本没有显式标记 | 只靠 `CREATE TABLE IF NOT EXISTS` + `ALTER TABLE` 临时补 | 旧代码读新库时无法判断，可能给出错答案 |
| 没有用户可查的变更日志 | 改动只在 `log.md` / commit message 里 | 装的人不知道这版修了什么，也不知道该不该升 |
| 没有自检入口 | 只有 `bootstrap`（一次性） | "装了但没跑通"只能靠用户猜（平台已有人装但未初始化） |
| 包内含真实项目/客户名 | v1.4.0/v1.5.0 上传包 14/28 文件命中（客户名 5、自有项目名 66、内部路径 12） | 工作信息随包外泄 |
| 发布物没有哈希记录 | 只有 `dist/agent-memory.zip` 文件本身 | 平台 build id 与本地包无法对应（只能靠时间猜） |

## 三、已经落地的（v1.4.1 / v1.5.0）

1. **包版本闸门（Helm 思路）**：`pack_platform.ps1` 计算分阶段内容的 SHA256，与
   `dist/.last-package.json` 里的 `content_sha256` 比对；**同版本不同内容 → 拒绝打包**，
   并提示"先把 SKILL.md 的 version 升一位"。同版本同内容（重复打包）放行。
2. **数据 schema 版本（OpenViking 思路：包与数据分开）**：索引库写 `PRAGMA user_version`
   （当前 1）；库版本 > 代码支持版本时**直接拒绝运行**（"旧代码读新库比崩溃更危险"）。
   `doctor` 同时报"库 vN / 代码 vM"。
3. **`doctor` 自检（openviking-server doctor / npm doctor）**：工程目录、Python、依赖、
   索引库、schema 版本、会话/消息数、peer 覆盖、最近入库、技能版本 —— 退出码 0/1。
4. **随包变更日志**：`references/changelog.md` 进包；每次发版先写条目再升版本。
5. **发布物哈希**：`dist/.last-package.json` 记录 `version / content_sha256 / zip_sha256 / built_at`，
   平台 build id 可以对着本地记录核。

## 四、暂未做（记录理由，避免下次重复讨论）

- **发布通道（`beta`/`next`）**：现在只有一条线、用户只有个位数，加通道的收益低于维护成本；
  等需要灰度时再加（届时用"版本号 + 通道 tag"两个字段，而不是再造一套包）。
- **包签名 / provenance**：本地单人发布，`content_sha256` 已能核对"装的是不是这个包"；
  真要做供应链证明，成本在 CI 侧，不在包里。
- **数据快照 / 回滚**：索引库是**可重建**的（`rmdir index` + `ingest` 90 秒），
  不像 OpenViking 那样存不可再生内容，所以不引入 git 快照；真要回滚就重建。
- **自动更新（autoUpdate）**：平台侧是否支持未知（待确认）；若支持，优先用平台通道，
  包内不做自更新（自更新会绕过平台审计）。

## 五、发布 checklist（每次发版照做）

1. 改代码/文档 → 跑 `pytest tests -q`（当前 95 条）；
2. 写 `references/changelog.md` 新条目 + 升 `SKILL.md` 的 `version`（SemVer：修复 +0.0.1，
   新能力 +0.1.0，破坏性改动 +1.0.0）；
3. `powershell -File pack_platform.ps1` → 必须 `PACK OK`：层级、SKILL 根、forbidden、
   版本闸门、**私有词机检**（`.private-terms.txt` + `tools\check_private_terms.py`）全过；
   发布前再核一次成品：`python tools\check_private_terms.py --zip`；
4. 干净目录跑 `scripts\bootstrap.ps1` → `am.ps1 doctor` 应 exit 0；
5. 更新本机已安装技能（`~\.dsh\skills\agent-memory`，旧版先备份）；
6. 生成 release note：`python tools\release_note.py --note "<一句话>"` → 产出 `docs/releases/v<版本>.md`；
7. 上传平台，贴该文件里的「上架说明」段 + `zip_sha256` 前 12 位；
8. 上传后**回填平台 build id**（`--platform-build os_xxx` 重新生成一次）并提交。
