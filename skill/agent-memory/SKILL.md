---
name: agent-memory
slug: agent-memory
display_name: 智能体会话记忆
display_name_en: Agent Session Memory
description: >-
  检索本机多个编码 agent（DSH / Codex / Claude Code / Hermes / WorkBuddy / CodeBuddy）的历史会话结论，
  判断旧结论是否已失效，并生成「环境事实」注入块。触发词：上次怎么决定的、
  之前讨论过什么、这个项目不同 agent 说过什么、旧路径还有效吗、为什么改成这样、
  agent-memory。
description_zh: 把一台机器上多个 agent 的会话汇成可检索库，查历史结论、看话题演变、验前提是否失效。
description_en: Unify session history across coding agents on one machine; search past conclusions, trace topic evolution, and verify whether old premises are still valid.
allowed-tools: Bash, Read, Grep, Glob
version: "1.5.1"
examples_zh:
  - "上次我们为什么把某个默认值从 60 改成 15？"
  - "这个项目在 Codex 和 DSH 里分别讨论过什么？"
  - "结论里提到的那条路径还能用吗？"
examples_en:
  - "Why did we change that default from 60 to 15?"
  - "What has this project discussed across Codex and DSH?"
  - "Is the path mentioned in old conclusions still valid?"
author: demo
---

# 智能体会话记忆

把本机多个 agent 的会话当**同一个项目的集体记忆**来查。核心用途是**少走弯路**：
别人（或另一个 agent）已经试过的方案、踩过的坑、改掉的路径，不用再试一遍。

## 环境（换机器会变，别写死）

- 工程目录由环境变量 `AGENT_MEMORY_HOME` 决定；未设时包装脚本会自己往上找 `cli.py`。
- **一律通过包装脚本调用**，不要手拼解释器路径：
  ```
  <skill>/scripts/am.ps1 <子命令> [参数]
  ```
  它负责解析工程目录、venv 与数据目录。**新机器首次使用先跑 `scripts\bootstrap.ps1`。**

## 首次使用（新机器必做）

平台包形态（本包：`SKILL.md` 在根，Python 引擎 `cli.py` 与 `collectors\` 也在根，
包装脚本在 `scripts\`；**平台只允许一级子目录**）：
```
powershell -NoProfile -ExecutionPolicy Bypass -File <skill>\scripts\bootstrap.ps1
```
它会：建 venv → 装依赖（**首次需联网**）→ 采集本机会话（约 45 秒）→ 打话题标签 →
生成本机 `index/entities.json` 与 `index/targets.json` → 打印**本机的实体名列表**。

- 解释器自动发现顺序：`uv` → `py` 启动器 → PATH 上的 `python` → 常见安装目录；都找不到会明确报错退 1。
- 数据落在 `<skill>\index\`（本机数据；会话原文不出本机）。
- 若拿到的是 **git 工程形态**（`cli.py` 在工程根、技能在 `skill\agent-memory`），
  首次安装改用工程根的 `install.ps1`——本包不含它。

## 什么时候用

| 用户在问 | 跑什么 |
|---|---|
| 「上次某件事怎么定的」「之前讨论过什么」 | `am.ps1 search` |
| 「这个方案是怎么一步步变成现在这样的」 | `am.ps1 timeline` |
| 「结论里那条路径/命令还能用吗」 | `am.ps1 premises` |
| 要给新会话准备环境事实 | `am.ps1 inject` |

**不要**用它回答"当前代码是什么样"——那是 `read`/`grep` 的活。它只回答"过去怎么看这件事"。

## 执行步骤

1. **先确认本机有哪些实体**（每台机器不同，不能猜）：
   ```
   <skill>\scripts\am.ps1 topics --top 20
   ```
   输出里的「实体 TOP」就是本机可用的话题名。**换台机器名字可能完全不同。**
2. **检索历史**（中文必须加 `--trigram`）：
   ```
   <skill>\scripts\am.ps1 search "<关键词>" --trigram --limit 8
   ```
   - 索引命中 2~15 ms。**1~2 字的中文词**（`质保`/`预算`）trigram 命不中，会自动回退 `LIKE` 扫描
     （输出标 `索引=like`，约 100~150 ms）——**回退结果要如实说明**，不要说成"索引命中"。
   - 查询里含 `+ - * ^ : " ( )`（如 `C++`）会**报错退 2**（FTS5 语法字符），不是"没有历史记录"。
3. **看演变**：
   ```
   <skill>\scripts\am.ps1 timeline "<实体>" ["<意图>"] --per 3
   ```
   意图标签是通用的（不随机器变）：检索与排序 / 评测与金标准 / 文档解析 / OCR与扫描件 /
   分块与切分 / 大纲与目录树 / 字段抽取 / 投标数值 / 上下文压缩 / 会话记录 /
   架构与选型 / 部署与性能 / 服务端接口 / Web前端 / 多agent委派 / 外部复核 /
   数据与库 / 合规与风险 / 投标业务
4. **引用旧结论里的路径/命令前先验**：
   ```
   <skill>\scripts\am.ps1 premises "<实体>" --top 5
   ```
5. **生成环境事实块**：
   ```
   <skill>\scripts\am.ps1 inject "<实体>" --write <项目>\.agent-memory\context.md
   ```

## 报告纪律（很重要）

- **区分「过去这么认为」和「现在仍成立」**：引用旧结论必须说明时间与状态，不要讲成当前事实。
- **`premises` 三种结果含义不同**：
  🟢 前提通过 ｜ 🟡 **项目已改名**（旧路径换算成新路径，结论可能仍有效）｜ 🔴 **真失效**（勿照做）。
  **不要把 🟡 说成"失效"**——那会把仍有效的经验误杀。
- **97% 的结论没有可验证前提**，无法机械判定是否过时；引用时标注"未验证"。
- 说"上次结论说 X"必须能给**会话标题与日期**，不能只给一句转述。

详见 `@references/cli.md`（命令与参数）与 `@references/verdicts.md`（判定语义与局限）；
**版本与变更**见 `@references/changelog.md`（每次发版先写条目再升 `version`）。

## 失败处理

- **先跑 `am.ps1 doctor`**：它一次报全（工程目录 / Python / 依赖 / 索引库 / 数据 schema 版本 /
  会话消息数 / peer 覆盖 / 最近入库 / 技能版本），退出码 0=能用、1=有阻塞问题。
- 索引不存在/报错 → 跑一次 `am.ps1 ingest`（约 6 个来源合计 90 秒；**只读各 agent 原始数据**）。
- 查询无结果 → 换同义词/英文术语再试；仍无结果就如实说"没有历史记录"，**不要编**。
- 实体名不确定 → 跑 `am.ps1 topics --top 20` 看本机实际有哪些。
- **报 "agent-memory is NOT initialised" 且退出码 3** → 这台机器还没装工程（技能只是壳，库与 venv 在工程目录里）。
  按报错里的 fix A/B/C 三选一：① `$env:AGENT_MEMORY_HOME = '<含 cli.py 的目录>'`
  （或在 `%USERPROFILE%\agent-memory` 建 junction 指向工程）；② git 工程跑工程根 `install.ps1`；
  ③ 平台包跑技能里的 `scripts\bootstrap.ps1`。
- **报 "python not found"（退出码也是 3）** → 同上，先跑一次 `install.ps1` / `bootstrap.ps1` 建 venv。
- 报 "dependency install failed" → 首次装依赖要联网；配好源后重跑同一条命令即可（已建好的 venv 会复用）。
