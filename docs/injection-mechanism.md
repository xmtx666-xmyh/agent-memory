# 注入机制：把「环境事实」压成 ~324 token 塞进会话开头

> 2026-11-03 ｜ 前置：`docs/staleness-design.md`（判定）、`docs/injection-value.md`（价值验证）。
> 本文记录注入块的**生成规则、怎么接进项目、以及压缩比**。

## 验证状态

**已实测**：40 条迁移条目压成 **3 条规则 / 519 字符 / 约 324 token**；
后继目录正确（`f:\demo-base` 而非字母序的 `f:\demo-wiki2`）；CLI 落盘可用；63 条测试通过。
**未实测**：真实 agent 拿到这个块之后的 token 收益（A/B 未做）。

## 一、注入块长这样（真实输出）

```markdown
<!-- agent-memory:auto-generated  check_at=2026-11-03T15:27:04 -->
## 环境事实（agent-memory 自动生成，勿手改；check_at=2026-11-03T15:27:04）

### 目录已改名（历史结论里的旧路径按下表换算）
- `f:\demo-wiki` → `f:\demo-base`（38 条历史结论引用；相对路径多数不变）
  - 在新位置没找到：`.pytest_tmp`
- `f:\demo-system` → `f:\demo-base`（2 条历史结论引用；同名文件可能也改名，需确认）
  - 在新位置没找到：`ollama_models`, `agents\master.py`
- `d:\demo-wiki` → `f:\demo-base`（1 条历史结论引用；同名文件可能也改名，需确认）

### 已确认失效（勿照做）
- `d:\demo-wiki-backup-20260617` 已不存在（2026-06-16 的结论基于它，需重新确认）
- `f:\cad2025` 已不存在（2026-10-28 的结论基于它，需重新确认）
```

## 二、压缩比：40 → 3

| | 条目 | 行数 | 字符 | 约 token |
|---|---|---|---|---|
| 逐条注入 | 40 🟡 + 2 🔴 | ~44 | ~1800 | ~1100 |
| **合并后** | **3 规则 + 2 失效** | **12** | **519** | **324** |

**合并维度是「旧目录」**：40 条里 38 条都是 `F:\demo-wiki\<不同文件>`，
真信息只有一句"旧目录换成 f:\demo-base，相对路径不变"。

## 三、三条硬规则（每条都对应一次实测踩坑）

### 3.1 后继目录必须按「最近还在用」排序

原实现按字母序 → 提示写「已迁移至 `f:\demo-next`, `f:\demo-wiki2`」，**而正确答案是 `f:\demo-base`**。
修法：按 `session_paths` 里该目录最后一次被工具调用的时间倒序。

**为什么关键**：注入一句错的后继，比不注入更糟——把 agent 引到也找不到的地方。

### 3.2 容器目录不能进规则表

`C:\Users\demo\.codex\x.json` 的 `project_dir` 是 `c:\users`，会产生
「`c:\users` → `f:\demo-base`」这种荒谬规则。已在 `_collapse` 里过滤。

### 3.3 整目录引用不算"可解析"

`F:\demo-wiki`（后面没有子路径）此前被算成 resolved，导致提示说"相对路径多数不变"。
修法：`rest` 为空时**不计入 resolved**，只算"引用了一次"。

## 四、怎么接进项目（一次性动作）

```powershell
# 生成
.\venv\Scripts\python.exe cli.py inject "demo-kb" --write .agent-memory/context.md
```

然后在**项目的 `AGENTS.md`** 里加一行（只需加一次）：

```markdown
开工前先读 `.agent-memory/context.md`（agent-memory 自动生成的环境事实）；
文件不存在则忽略，不要因此报错。
```

**为什么不直接写进 AGENTS.md**：AGENTS.md 是人写的规则，自动生成的内容混进去会
让"人改的"和"机器改的"分不清；而且它有 token 成本，需要能整体删除。

## 五、预算与降级

`--max-chars`（默认 1400 ≈ 500 token）。超预算时优先砍
「在新位置没找到：…」这类细节行，保留"旧目录→新目录"规则行。

## 六、诚实的天花板

1. **token 收益未量化**：本文只证明"注入块小且信息正确"，没证明"agent 因此少走了弯路"。
2. **`check_at` 是静态的**：块里的判定是生成时刻的快照。若目录又被改名，块会过期——
   所以块头必须带 `check_at`，让人/agent 自己判断可信度。
3. **只覆盖"有可验证前提"的 1.4%**（42/3173），其余 97% 结论无法这样注入。
4. 重复注入会叠加：若下游不按 `MARKER` 前缀替换，可能积多份。下游实现须按前缀去重。

## 七、复现

```powershell
.\venv\Scripts\python.exe cli.py premises demo-kb --top 5   # 先看判定
.\venv\Scripts\python.exe cli.py inject demo-kb             # 再生成块
.\venv\Scripts\python.exe -m pytest tests\test_inject.py -q    # 7 条契约
```
