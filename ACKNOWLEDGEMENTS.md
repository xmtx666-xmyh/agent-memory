# 参考与致谢

本项目为**独立实现**，仓库内**不包含任何第三方项目的源代码**（也没有 `vendor/` /
`third_party/` 目录或第三方版权头）。下列项目仅作为**设计、接口约定或机制**的参考，
出处已在 `docs/` 与代码注释中标注。

| 项目 | 许可 | 参考了什么 | 是否有代码复用 |
|---|---|---|---|
| [OpenViking](https://github.com/volcengine/OpenViking)（火山引擎） | AGPL-3.0 | ① peer（工作区身份）命名约定 `github.com-owner-repo`；② `doctor` 自检的产品形态；③「包版本 / 数据版本分开管」的思路 | **无**。命名约定是接口约定、非代码；`normalize_remote` 等实现为本仓独立编写 |
| [recall-agents](https://pypi.org/project/recall-agents/) | MIT | 跨 agent 会话检索 / 笔记 / 溯源的产品形态（其官方明示 Windows 不支持，本仓未采用其实现） | 无 |
| Hermes（开源 agent） | — | `session_search` 的检索体验、单条正文长度上限的经验值 | 无 |
| [Helm](https://helm.sh/) / [npm](https://www.npmjs.com/) | Apache-2.0 / Artistic-2.0 | 包版本与数据 schema 版本分离、发布通道（dist-tag）思路 | 无 |

补充说明：

- 本仓全部提交均在本仓历史中产生（`git log` 可查），不是从任何上游仓库导入的 fork。
- `collectors/` 只是**读取**各 agent 在本地写下的会话文件（DSH / Codex / Claude Code /
  Hermes / WorkBuddy / CodeBuddy），不包含这些产品的代码或 SDK。
- 如果你认为本仓某处应补充署名，请开 issue，我们会补上。
