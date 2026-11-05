# P0：peer（工作区身份）按 git origin 派生（2026-11-04）

> 来源：OpenViking 调研后的两条 P0 之一（另一条是知识库的目录摘要 sidecar，落在 `F:\demo-kb`）。

## 验证状态

**已实测**（本机，2026-11-04）：
- 真实库 625 个会话 → 补算 **254 个**有 peer（4 个 peer）；其余 371 个 cwd 已不存在**或不在 git 仓库里**，按设计无 peer；
- `F:\demo-base` → `path-demo-base-9e6c3de7`（该仓**没有 remote origin**，走路径回退）；
- `F:\hermes\hermes-agent` → `github.com-nousresearch-hermes-agent`（有 origin）；
- 测试：`test_peers.py` 覆盖 scp / https(带 token) / ssh(带端口) 三种 origin 写法 + 子目录 + worktree 归并 + 非仓库；
  `pytest tests -q` → **81 passed**。

**未验证**：跨机器一致性（`path-` 回退在换机后必然变，只有带 origin 的仓库跨机稳定）；Windows 以外的 git 行为。

## 为什么需要

两种实测过的失败模式：
1. **按 cwd 分桶** —— `F:\demo-base`、`F:\demo-base\work`、各 worktree 各成一家，同一件事拆成多条线；
2. **按 agent 分桶** —— 同一件事在 DSH 与 Codex 里各存一份，跨 agent 检索永远要人肉合并。

## 实现（`peers.py` + `store.py` + `cli.py`）

- `peers.normalize_remote()`：各种 origin 写法归一（scp 风格 / https 带 token / ssh 带端口 / 点号保留在主机名）；
- `peers.common_root()`：用 `git rev-parse --path-format=absolute --git-common-dir` 取**共同根**，
  所以主仓与 linked worktree 指向同一个 peer；老 git 回退 `--git-common-dir` + `--show-toplevel`；
- `peers.peer_for_cwd()`：origin 优先 → 无 origin 走 `path-<目录名>-<路径哈希8位>` → 非仓库返回空；
- `store.sessions.peer` 列 + 自动迁移（`ALTER TABLE`，老库不用重建索引）+ `idx_sessions_peer`；
- `ingest()` 默认用 `peer_for_cwd`（同 cwd 只算一次），且**已存在会话不重写** →
  存量靠 `store.backfill_peers()` / `cli.py peers --backfill` 补（幂等）；
- `search --peer <子串>` 过滤；`peers` 命令列出会话数/时间跨度/代表 cwd；`stats` 打印 peer 覆盖。

## 边界

- peer **不参与** FTS5 检索排序、不影响实体×意图打标，只做归属与过滤（避免把"检索"改成"分组"）；
- 非 git 目录（含临时目录、已删除目录）**没有 peer**，不猜；
- `path-` 回退只保证**本机**稳定（换机变），这是无 origin 时的固有限制，已写进 SKILL 的参考文档。
