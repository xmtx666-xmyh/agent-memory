# A/B 实证：注入「迁移提示」的效果与代价

> 2026-11-03 ｜ 前置：`docs/injection-mechanism.md`。
> 本文回答最后一问：**注入到底带来了什么？**（前面只证明了"块小且信息正确"，这里测真实行为）

## 验证状态

**已实测**：3 臂 × 3 轮 = 9 次运行，本地 `qwen3.5:9b`（`think=false`、`temperature=0`），结果**完全稳定**（3/3）。
**未验证**：其它任务类型、强模型（Codex/DSH 级别）、注入对无关任务的干扰。

## 一、实验设计

**同一个任务**：找到 `server/api/wiki.py` 并回答「该文件用什么创建路由对象？」
（真值：`router = APIRouter()`）

| 臂 | 提示差异 |
|---|---|
| `base` 基线 | 「上次结论：文件在 `F:\demo-wiki\server\api\wiki.py`」← **该目录已不存在** |
| `inject` 注入 | 同上 + agent-memory 生成的「环境事实」块 |
| **`fresh` 对照** | 直接给正确路径 `F:\demo-base\...`，**无**注入块 |

**为什么必须有 `fresh` 臂**：没有它就无法区分"基线失败是因为旧路径"还是"9B 本来就干不成"。
这是本实验最关键的设计——否则结论就是自欺。

自建最小 agent loop（`experiments/ab_injection.py`），工具：list / read / grep / answer，
最多 8 步，逐轮累计 prompt 字符。

## 二、结果（3 轮全稳定）

| 臂 | 步数 | prompt token | 首调失败 | 找到文件 | 答对 |
|---|---|---|---|---|---|
| `base` 基线 | **4** | 1,379 | **3/3** | **0/3** | **0/3** |
| `inject` 注入 | **2** | **1,578** | 0/3 | 3/3 | **3/3** |
| `fresh` 对照 | 2 | 1,443 | 0/3 | 3/3 | 3/3 |

### 三组的实际轨迹（同一次 rep 的 trace）

```
[base]   step1 read F:\demo-wiki\server\api\wiki.py   → ERROR 文件不存在
         step2 list F:\demo-wiki\server\api           → ERROR 目录不存在
         step3 list F:\demo-wiki                      → ERROR 目录不存在
         step4 answer「无法找到目标文件…路径及其父目录均不存在」

[inject] step1 read F:\demo-base\server\api\wiki.py   → OK
         step2 answer「router = APIRouter()」                    ✅

[fresh]  step1 read F:\demo-base\server\api\wiki.py   → OK
         step2 answer「router = APIRouter()」                    ✅
```

**基线是逐层沿旧路径探到底、三层全失败后才放弃**——这是"旧结论误导"的完整实证。

## 三、结论（含一条对我自己不利的）

1. **注入把 0/3 变成 3/3 正确**，步数 **4 → 2（−50%）**。
2. ⚠️ **token 没有减少，反而 +199（1,379 → 1,578，+14%）**。
   **所以"注入省 token"这个说法在本实验里不成立**——注入块本身要占 token。
   它省的是**步数与错误率**，不是本轮 token。
3. **`inject` ≈ `fresh`**（都是 2 步 3/3）：注入的效果**等价于"有人直接告诉你正确路径"**。
4. `inject` 比 `fresh` 多花 135 token —— 那是**自动化**的代价（不需要人工维护"正确路径"这件事）。

**换算成真实价值**：答错一次的代价（用户重问、agent 重跑、基于错路径改错文件）
远大于 199 token。但要诚实：**如果任务不依赖旧结论，注入就是纯 +199 token 的成本**。

## 四、一个重要的外推（未实测）

9B 在错路径上只探了 **3 层就放弃**（4 步）。
真实的 Codex / DSH 级别 agent 大概率会**全盘搜索**（grep 整个盘、逐个目录 list），
那样"错路径"的 token 代价会**十倍以上**于本实验，注入的相对收益会更大。

**但这条是外推，没有实测**（测它要花钱跑 Codex，本轮未做）。

## 五、实验的局限（必须说清）

1. **单任务**：只有一个 ghost path（`F:\demo-wiki\server\api\wiki.py`）。
2. **单模型**：本地 9B。强模型行为可能不同（见 §四）。
3. **单数据集**：`demo-kb` 一个项目。
4. **未测负作用**：任务若与迁移无关，注入是纯开销；
   且若注入块里的后继**恰好也错了**，会把 agent 引到另一个坑（这类风险靠 `check_at` + 人工抽验兜）。
5. 步数少也可能因为 9B 容易放弃（base 4 步就停了，而不是 8 步用满）。

## 六、复现

```powershell
cd F:\agent-memory
.\venv\Scripts\python.exe experiments\ab_injection.py --reps 3 --out experiments\ab_result.json
```

输出每轮三臂的 `步数 / prompt 字符 / 首调失败 / 找到 / 正确`，并落盘完整 trace。
单轮约 8 秒（本地免费）。

## 七、遗留

1. 用**强模型**（Codex）复测一次，验证 §四 的外推——这是唯一能验证"注入对强 agent 更值"的办法。
2. 测**无关任务**下注入的干扰（负作用）。
3. 多 ghost path 批量跑（现在只有 1 个任务）。
