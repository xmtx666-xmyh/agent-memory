# 检索边界修正：1~2 字中文与 FTS5 语法字符（2026-11-04）

> 起因：`glm-5.3` 独立复核（`docs/_review_glm_am_strategy.md`）指出三处问题，本文记**修法与实测证据**。
> 复核简报：`docs/_brief_glm_am_strategy.md`。

## 验证状态

**已实测**（本机，2026-11-04，内存 FTS5 + 真实索引库 34k 条）：
- `unicode61` **不切分 CJK**：任何中文子串都查不到（`招标`/`保证金` 全 0 命中，连 3 字也不中）；
- `trigram` 只索引 3 字滑窗：**1~2 字中文命不中**（`质保`=0，`质保期`=1）；
- 语法字符 `C++` → `fts5: syntax error near "+"`，旧实现静默返回 `[]`。

**未实测**：其它分词器（`porter` 等）；LIKE 回退在超大库（>100 万条）上的耗时外推。

## 三处修法

### 1. 注释写错了机制（`store.py` 模块 docstring）

原文「普通 FTS5 对连续中文按单字/二元切分，短语匹配差」——**错**。`unicode61` 把一段连续中文当作
**一个 token**，所以不是"匹配差"，是**根本命中不了**。已改为实测表述，并写明 trigram 的 3 字下限。

### 2. 语法错误被当成"零命中"（`store.py` + `cli.py`）

- 新增 `store.QueryError`：`OperationalError` 不再 `return []`，而是抛出，带原错误与提示
  （`+ - * ^ : " ( )` 是 FTS5 语法字符，请加引号或换词）；
- `cli.py` 捕获后写 stderr 并 **exit 2**；空查询仍返回 `[]`（不算错误）。

### 3. 1~2 字中文查不到（`store.py` 的 LIKE 回退）

`search()` 在 **FTS 零命中且查询含中日韩字符**时回退 `LIKE '%词%'` 全表扫描，
并用 `Store.last_search_via = "like"` 标记；CLI 输出里显示 `索引=like` 并打印一行警告。
**不静默**：回退必须如实报出来，不能伪装成索引命中。

## 实测数字（真实库 555 会话 / 34k 消息）

| 查询 | 路径 | 命中 | 耗时 |
|---|---|---|---|
| `质保` + `--trigram` | 回退 LIKE | 3 | **135.4 ms** |
| `保证金` + `--trigram` | trigram | 2 | **15.1 ms** |
| `PageIndex` | unicode61 | 2 | ~6 ms |
| `C++` | 语法错误 | — | **exit 2** + stderr |

结论：回退比索引慢 1~2 个数量级，但把"查不到"变成"查得到且明说"，对两字词（招投标语料里高频）值得。

## 回归测试

`tests/test_store.py` 新增 3 条：语法错误必须抛 `QueryError`；两字中文必须回退且标 `via=like`；
不加 `--trigram` 的中文也回退、英文仍走索引。全量 `pytest tests -q` → **71 passed**。

## 复现

```powershell
cd F:\agent-memory
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe cli.py search "质保" --trigram --limit 3     # 索引=like
.\.venv\Scripts\python.exe cli.py search "C++"                          # exit 2 + stderr
```

## 仍未修（复核提出但我判断先不做的）

- **F5**：注入通道与 OpenViking DSH 插件重叠 —— 属产品决策（共存/让位），不需要改代码；
- **F4②③**：语义第三路的 Ollama 缺席回退、分块后的向量数与体积 —— 属那条路落地前的设计前提，未开工；
- **T4/T5/T8**：`demo-base/rrf.py` 是否"同构"、消息长度分布、Ollama 延迟 —— 均为待确认，不做断言。
