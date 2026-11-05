# 演变时间线：PageIndex

- 会话 9 个 ｜ 抽到结论 4 个
- 时间跨度：2026-06-15 → 2026-10-02

## 2026-06-15 ｜ claude ｜ Thoroughly trace the complete import pipeline in F:\
- `decision` PDF（第 18-52 行）：`pdfplumber` 优先，回退到 `PyMuPDF find_tables()`。
- `decision` 如果提取失败，回退到平铺单元格文本。

## 2026-06-16 ｜ claude ｜ Thoroughly audit the current demo-next system at F:\kb
- `decision` PyMuPDF 文本提取，如果文本少于 500 字符，则回退到 OCR
- `decision` 7.  History of Dimension Mismatch -- "xinglin-cuoshang.doc" 因 1792 vs float 维度冲突而无法导入；一个早期导入运行改为使用 float 维度删除了旧表（日志："dropping old table"）

## 2026-06-16 ｜ claude ｜ Very thoroughly explore F:\demo-next and identify whic
- `decision` 将 FTS5 模式更改为页面级（每行一个 wiki 页面，带 YAML 元数据）而不是基于分块的知识库。
- `decision` 结论：高度可重用的概念，过度设计的实现。

## 2026-10-02 ｜ dsh ｜ 你是只读审计员。**禁止修改
- `decision` ⑤ 坑：`check_json` 只看结构不看语义（空标题也能过）；评分覆盖率仅靠提示词；作者自承编号"即使提示了也常从 1 重来"，才改为程序重编号。
- `verified` 4. 实测（OpenRouter/gemini-2.5-flash）：首次 `prompt_tokens 19349, cached 0, cost 0.0058047`；第二次 `prompt_tokens 19737, cached 19442, cost 0.00067176` → 约 1/9，降幅 90%+。
