# Codex 复测：强 agent 在旧路径上到底多花多少成本？

> 2026-11-03 ｜ 前置：`docs/ab-injection-result.md`（本地 9B 的 A/B）。
> 目的：验证那里的**外推**——"9B 只探 3 层就放弃，强 agent 会全盘搜索，代价更大"。

## 验证状态

**已实测**：4 次 Codex 真实调用（2 臂 × 2 种 cwd），从 rollout 日志提取工具调用序列与 token。
**未验证**：其它任务类型；多轮对话场景（这里都是单轮一次性任务）。

## 一、实验设计

同上一份的任务（找到 `server/api/wiki.py`，回答它用什么创建路由对象），两臂：

- **base**：只给旧结论里的路径 `F:\demo-wiki\server\api\wiki.py`（**该目录已不存在**）
- **inject**：同上 + agent-memory 生成的迁移块（`f:\demo-wiki` → `f:\demo-base`）

关键改进：**cwd 分两种**，因为上一份实验暴露了"cwd 直接就是正确答案"的缺陷。

| cwd | 含义 |
|---|---|
| `F:\demo-base` | agent 已经在正确的项目里（现实中的常态） |
| `F:\` | 中立根目录，必须自己定位项目 |

Codex 配置：`sandbox=read-only`、`approval-policy=never`，单轮调用。

## 二、结果：**四臂全答对，但成本差 8 倍**

| 臂 | cwd | 工具调用 | input tok | **output tok** | 答对 |
|---|---|---|---|---|---|
| base | `F:\demo-base` | **5** | 35,208 | 162 | ✅ |
| inject | `F:\demo-base` | **2** | 34,698 | 178 | ✅ |
| **base** | **`F:\`** | **16** | 31,929 | **945** | ✅ |
| **inject** | **`F:\`** | **2** | 27,795 | **258** | ✅ |

⚠️ **input token 不作为判据**：四次调用的 prompt 缓存命中率差异很大
（同前缀的第二次调用缓存高），跨调用不可比。
**工具调用次数与 output token 是干净的**（生成量不受缓存影响）。

### 2.1 轨迹对比（从中立 cwd 开始，这是最有说服力的一组）

**base 花了 16 次工具调用**：
```
 1 读 F:\demo-wiki\server\api\wiki.py            → 失败
 2 Test-Path 旧路径                              → 不存在
 3 Test-Path 旧根 + 列 F:\ 目录                  → 开始找
 4 试 4 个候选目录（demo-base/demo-wiki2/demo-next/demo-deploy） → 找到
 5~16 反复验证答案（Select-String / 读第12行 / 读字节 / findstr /
      Get-Content -Raw / git rev-parse / git grep / safe.directory…）
```

**inject 只花 2 次**：
```
 1 读旧路径 → 失败
 2 直接读 F:\demo-base\server\api\wiki.py → 成功 → 回答
```

## 三、结论

1. **外推成立，但方向要修正**：
   - 我说"强 agent 会全盘搜索" —— **没有发生**（Codex 只探了 4 个候选目录，未 recurse 全盘）。
   - 但**成本确实暴涨**：中立 cwd 下 **16 次工具调用 vs 2 次（−87.5%）**，output token **945 vs 258（−73%）**。
2. **强 agent 不会因旧路径答错**（四臂全对），它们会自己找到并纠正——
   所以注入的价值**不是"救错误"，而是"省探索"**。
3. **注入的价值取决于 cwd**：
   - cwd 已在正确项目 → base 也只 5 次 → 注入省 3 次（−60%），但 output token 无改善（162 vs 178）
   - cwd 不在正确项目 → base 16 次 → 注入省 14 次（−87.5%），output token −73%
4. **最意外的发现**：base@中立根在**已经找到文件之后**又花了 12 次验证。
   说明"路径不可靠"会**污染后续的可信度**——agent 找到文件后仍不放心，反复确认。
   这类"信任成本"在 token 统计里看不见，但它是真实的。

## 四、与本地 9B 结论的对照

| | 本地 9B | Codex |
|---|---|---|
| base 是否答对 | **0/3** | **2/2 ✅** |
| base 成本 | 4 步 / 1,379 tok | 5 或 16 次调用 / 162~945 output tok |
| inject 效果 | 0/3 → 3/3 正确 | 省 3~14 次工具调用 |
| **注入的价值** | **救错误**（模型能力不足，认死路径） | **省探索 + 省信任成本** |

⇒ **同一个注入，对不同能力的 agent 价值不同**：弱 agent 靠它避免答错，强 agent 靠它少绕路。

## 五、局限

1. **单任务**（1 个 ghost path）、单项目、单轮。
2. input token 不可比（缓存污染），只能看工具调用与 output token。
3. base@中立根那 16 次里后 12 次是"验证"，可能与该文件的**中文内容 + PowerShell 编码**有关
   （它试了 ReadAllBytes / findstr / git grep），不完全是路径问题。
4. 成本：4 次调用合计约 12.8 万 input（大部分命中缓存），实际花费在**几毛钱**量级。

## 六、复现

```powershell
# 工具调用与 token 提取
.\venv\Scripts\python.exe tools\codex_tool_calls.py
.\venv\Scripts\python.exe tools\codex_token_usage.py
```
（两个脚本按 thread id 从 `~/.codex/sessions/**/rollout-*.jsonl` 定位对应调用）
