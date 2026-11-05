# 发布留档（releases）

> 每个**发布到平台的版本**一份 `v<版本>.md`，字段固定：版本号 / 条目数 / zip sha256 / 内容 sha256 /
> 打包时间 / 代码提交 / **平台 build id** / 上架说明原文 / 该版本 changelog。
> 目的：平台只显示一个 build id（`os_…`），本地只有一个 zip —— 两者靠这份留档对上，
> 事后才能回答「用户装的是不是这个包」「这版到底改了什么」。

## 索引

| 版本 | 状态 | 平台 build | zip sha256（前 12） | 日期 | 说明 |
|---|---|---|---|---|---|
| [v1.5.1](v1.5.1.md) | **待上传** | （待回填） | `839bab56083e` | 2026-11-05 | 包内真实名/路径已脱敏 + 打包私有词机检 |
| [v1.5.0](v1.5.0.md) | 已上架（**未脱敏**，被 1.5.1 取代） | （以平台为准） | `b9d31e75c705` | 2026-11-05 | doctor + 数据 schema 版本 + 随包 changelog |
| [v1.4.1](v1.4.1.md) | 未上架（内部） | — | 未留档 | 2026-11-04 | 未初始化提示 + 打包版本闸门；被 1.5.0 取代 |
| [v1.4.0](v1.4.0.md) | **已上架** | `os_e8ac2aed4e37d131` | 未留档（无记录机制） | 2026-11-04 | 6 个采集来源 + 连字符查询修复 |

## 怎么生成

```powershell
# 1) 先打包（pack 会写 dist/.last-package.json，含 version/content_sha256/zip_sha256/built_at）
powershell -NoProfile -ExecutionPolicy Bypass -File pack_platform.ps1
# 2) 生成当前版本的 release note（--note 会进"上架说明"）
.\.venv\Scripts\python.exe tools\release_note.py --note "<一句话卖点>"
# 3) 上传平台后，把平台 build id 回填（重新生成一次即可）
.\.venv\Scripts\python.exe tools\release_note.py --platform-build os_xxxxxxxx
```

## 约定

- **文件名 = 版本号**（`v1.5.0.md`），版本号以 `SKILL.md` 的 `version` 为准；
- 生成器的硬校验：戳里的版本 ≠ SKILL.md 版本 → 拒绝生成（先重新打包）；
- 未上架的版本也要留一份，标明"未上架"，否则以后看到版本号断层没人知道原因；
- 上传后**必须**回填平台 build id（这一步人工，生成器会留"待回填"字样提醒）。

## 为什么不做成自动发布

平台上传需要人工确认（发布是外部副作用），本仓只做"发布物可核对 + 留档"，不做自动上传。
详见 `docs/versioning.md`（调研四套做法 + 本仓缺口 + 发布 checklist）。
