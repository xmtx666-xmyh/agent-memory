"""话题归并：把会话打上「实体 × 意图」标签。

## 为什么要归并（实测依据，见 tools/mine_entities.py）

在 616 个会话里按裸名统计：
  demo-wiki **307** 会话 ｜ demo-base **27** 会话  ← 同一个系统的前后两个名字
  DEMO2021 **48** 会话 ｜ 示例园区 **28** 会话        ← 同一个项目（DEMO2021-SH090 = 示例客户项目三期）
不做归并，同一件事会被拆成两个"话题"，时间线也就画不成一条。

另外：**路径挖掘不可靠**（`F:\\xxx` 形式的候选里最高的只有 7 个会话），
所以实体靠「种子词 + 同义词表」，而不是从路径里猜。

## 三个口径的取舍（对应 docs/next.md 的待定项）

1. **实体词典**：手维护 canonical → aliases（下表），并用 `tools/mine_entities.py`
   定期核对会话数——发现新名字再加，而不是让模型自由生成。
2. **意图标签**：**固定清单**（`INTENTS`）+ 关键词规则，**不用 LLM 自由打标**。
   理由：自由打标会产出"看起来对"的标签，无法复核；固定标签可用测试钉住。
3. **结论冲突**：不在本模块判断（属第二阶段的演变时间线），这里只打标签。

## 多标签

一个会话可以有**多个实体**（跨系统讨论）和**多个意图**。
权重用命中次数归一（避免长会话仅因为字数多就占满标签）。
"""
from __future__ import annotations

import collections
import re
from typing import Iterable

# ── 实体：canonical → 同义词（全部小写匹配） ──────────────────────────────
#: ⚠️ 这里**不写死任何项目名**。实体同义词表是**每台机器自己的数据**，
#: 存在 `<DATA>/entities.json`（`paths.ENTITIES_FILE`），由 `cli.py init` 生成、用户按需加别名。
#: 原先写死在代码里（demo-wiki / demo-base / DEMO2021 / 示例街道A…）导致换台电脑直接失效。
#: 匹配时按「长别名优先」，避免 "kb" 吃掉 "demo-next"。
ENTITIES: dict[str, tuple[str, ...]] = {}

#: 以下三个由 load_entities() 重建，调用方不要直接改
_ENTITY_LOOKUP: list[tuple[str, str]] = []
_ALIAS_TO_CANON: dict[str, str] = {}
_ENTITY_MATCHERS: list[tuple] = []


def load_entities(path: str | None = None) -> int:
    """从 JSON 载入实体同义词表，返回载入的 canonical 数量。

    文件格式：`{"entities": {"canonical": ["别名1", "别名2", ...]}}`
    缺文件时退化为「每个目录名自成一实体」（`entities_from_paths` 的默认行为）。
    """
    global _ENTITY_LOOKUP, _ALIAS_TO_CANON, _ENTITY_MATCHERS
    import json as _json
    import os as _os
    if path is None:
        try:
            from paths import ENTITIES_FILE as path
        except Exception:                                  # noqa: BLE001
            path = ""
    ENTITIES.clear()
    if path and _os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                doc = _json.load(fh)
            for canon, aliases in (doc.get("entities") or {}).items():
                ENTITIES[canon] = tuple(str(a).lower() for a in aliases if a)
        except Exception as e:                             # noqa: BLE001
            # 这个文件是**要求人手工编辑**的（加历代改名别名），打错一个逗号就会静默失效：
            # 所有别名归并消失、按旧名查询全空且无一字提示。必须喊出来。
            import sys as _sys
            _sys.stderr.write("[agent-memory] 警告：实体表解析失败，已退化为"
                              "「目录名即实体」：%s（%s: %s）\n"
                              % (path, type(e).__name__, e))
    _ENTITY_LOOKUP = sorted(
        ((a, c) for c, aliases in ENTITIES.items() for a in aliases),
        key=lambda kv: -len(kv[0]))
    _ALIAS_TO_CANON = {a: c for a, c in _ENTITY_LOOKUP}
    _ENTITY_MATCHERS = [(_kw_matcher(a), c) for a, c in _ENTITY_LOOKUP]
    return len(ENTITIES)

# ── 意图：固定清单（label → 关键词，全部小写匹配） ──────────────────────
#: ⚠️ 纪律：**意图关键词里不要放实体名**（codex / workbuddy / pageindex / hermes…）。
#: 实体名一出现就会给意图加分，等于同一件事被算了两次（实测 `codex` 让
#: 「agent 协作」虚高到 129 会话）。实体由 ENTITIES 负责，这里只描述"在干什么"。
INTENTS: dict[str, tuple[str, ...]] = {
    # 检索
    "检索与排序": ("检索", "召回", "rerank", "精排", "rrf", "top-k", "树导航",
                "向量检索", "embedding", "检索质量", "bm25", "打分"),
    "评测与金标准": ("评测", "金标", "golden", "基线", "正确率", "eval",
                 "关键词命中", "mrr", "回归集", "哨兵"),
    # 文档处理（原「文档解析与切分」拆四份）
    "文档解析": ("解析", "抽取器", "结构化", "表格提取", "docx", "pdf 解析", "页码"),
    "OCR与扫描件": ("ocr", "扫描件", "识别率", "tesseract", "paddle", "图片转文字"),
    "分块与切分": ("chunk", "分块", "切分", "重叠", "overlap", "切片", "段落合并"),
    "大纲与目录树": ("大纲", "目录树", "章节", "页眉", "合并章节", "bloated", "页面结构"),
    # 数值（原「数值与字段抽取」拆两份）
    #: ⚠️ 「字段」「抽取」「单位」这类 2 字泛词必须**短语化**：实测
    #: 「16G内存可用14.2G」会话里的「字段」指的是 SMBIOS 字段，被误判成字段抽取。
    "字段抽取": ("字段抽取", "字段归属", "字段错", "字段归一", "抽取字段", "字段值",
             "numerics", "正则提取", "值域", "单位换算", "单位错"),
    "投标数值": ("预算", "保证金", "质保", "交付期", "合同金额", "控制价", "最高限价"),
    # 会话（原「会话与上下文」拆两份）
    "上下文压缩": ("压缩", "compaction", "上下文窗口", "上下文预算", "截断", "摘要压缩"),
    "会话记录": ("会话记录", "对话记录", "resume", "恢复会话", "会话检索", "历史会话"),
    # 架构/部署/接口
    "架构与选型": ("架构", "选型", "技术栈", "迁移", "重构", "替代方案", "方案对比"),
    "部署与性能": ("部署", "性能瓶颈", "性能下降", "性能测试", "耗时", "延迟", "gpu",
              "cuda", "显存", "并发", "服务启动", "启动服务", "端口", "吞吐",
              "prefill", "tok/s"),
    "服务端接口": ("接口", "端点", "restful", "fastapi", "uvicorn", "flask", "api 设计"),
    "Web前端": ("前端", "ui", "界面", "按钮", "webui", "页面渲染", "样式"),
    # 协作（原「agent 协作」拆两份，且剔除实体名）
    "多agent委派": ("subagent", "委派", "teammate", "spawn", "并行代理", "多智能体"),
    "外部复核": ("复核", "reviewer", "交叉验证", "审阅", "第三方评审", "glm"),
    # 其它
    "数据与库": ("sqlite", "数据库", "索引重建", "倒排索引", "建表", "schema", "数据迁移",
             "备份"),
    #: ⚠️ 「风险」「安全」会命中**硬件风险 / 内存安全**等无关语境（实测），必须短语化。
    "合规与风险": ("合规", "废标", "无效标", "审计发现", "安全漏洞", "权限控制", "越权",
              "合规风险", "法律风险", "废标风险"),
    "投标业务": ("投标", "招标", "标书", "竞争性磋商", "竞争性谈判", "询价", "采购人",
             "评分标准", "评分办法"),
}

#: 路径目录名 → 不算实体的"容器/公共"目录（实测 F:\demo-main 是 DSH 默认工作区、与话题无关）
_PATH_DIR_NOISE = {"demo-main", "dp", "tmp", "temp", "work", "workspace", "docs", "src", "dist",
                   "build", "node_modules", "users", "desktop", "documents",
                   "downloads", "projects", "appdata", "program", "windows"}


def entities_from_paths(tool_dirs) -> list[tuple[str, int]]:
    """从「工具调用碰过的目录」推出实体（**这是比正文提及更硬的归属信号**）。

    为什么需要：实测有会话在 `cwd=F:\\demo-kb` 里干活，但产出的是 `F:\\agent-memory`
    新项目，正文又大量讨论 demo-base 的检索 —— 只看正文会把它归成「demo-kb」。
    工具路径直接是"动过哪些文件"，最能说明这个会话属于哪个项目。

    规则：目录名若命中 ENTITIES 的别名 → 用 canonical（demo-wiki → demo-kb）；
    否则用目录名本身当实体（如 agent-memory）。公共容器目录丢弃。
    """
    out: list[tuple[str, int]] = []
    seen: set[str] = set()
    for item in tool_dirs or ():
        d, hits = item if isinstance(item, (tuple, list)) else (item, 1)
        ds = str(d).replace("/", "\\").rstrip("\\").lower()
        # 用户主目录根本身不是项目（`C:\Users\demo` 实测让 "demo" 成了 56 个会话的实体）
        if ds.startswith("c:\\users\\") and ds.count("\\") == 2:
            continue
        name = ds.rsplit("\\", 1)[-1]
        if not name or name in _PATH_DIR_NOISE:
            continue
        canon = _ALIAS_TO_CANON.get(name, name)
        if canon in seen:
            continue
        seen.add(canon)
        out.append((canon, int(hits)))
    return out[:3]


def _is_ascii_word(kw: str) -> bool:
    """纯 ASCII 的短词要做**词边界**匹配，否则会命中别的英文单词内部。

    实测教训：意图 `接口与前端` 里放了 "ui"/"api"，子串匹配会命中
    b[ui]ld / req[ui]rement / cap[it]al…，直接把它顶成第一大意图（330 会话）。
    """
    return kw.isascii() and all(c.isalnum() or c in "-_." for c in kw)


def _kw_matcher(kw: str):
    """返回 (text) -> bool。ASCII 词用**词边界**，中文用子串。

    下划线也要算进边界排除集：否则 `session` 会命中代码里的 `session_key`、
    `token` 命中 `token_count` —— 实测这两者分别污染了 212 / 134 个会话的标签。
    """
    if _is_ascii_word(kw):
        rx = re.compile(r"(?<![a-z0-9_])%s(?![a-z0-9_])" % re.escape(kw), re.IGNORECASE)
        return lambda low: bool(rx.search(low))
    return lambda low: kw in low


#: 预编译全部匹配器，避免每次逐条消息都重建正则（3.5 万条 × 90 个关键词）
_MATCHERS: dict[tuple[str, str], object] = {
    (label, kw): _kw_matcher(kw)
    for label, kws in INTENTS.items() for kw in kws
}

# 实体匹配器不在这里初始化 —— 见 load_entities()（它依赖数据文件，可能延迟加载）


def _is_specific(kw: str) -> bool:
    """判断关键词是否"足够具体"，具体词命中 1 次即可打标，泛词要 2 次。

    依据：泛词（字段/风险/性能/解析，2 字）在本语料里到处出现，
    出现一次就代表话题会被大量误判（实测「16G内存」会话因一次「字段」被打成
    「字段抽取」）。而 `compaction`/`上下文压缩`/`bloated` 这类长词基本只在本话题出现。
    """
    kw = kw.strip()
    if not kw:
        return False
    if " " in kw or "-" in kw:          # 组合词（api 设计 / top-k）天然具体
        return True
    return len(kw) >= 4                 # 中文 4 字或 ASCII 4 字符以上视为具体


def detect_entities(text: str) -> list[str]:
    """返回文本里出现的 canonical 实体（去重、保出现顺序）。"""
    low = (text or "").lower()
    found: list[str] = []
    for mt, canon in _ENTITY_MATCHERS:
        if canon not in found and mt(low):
            found.append(canon)
    return found


def detect_intents(text: str) -> list[str]:
    """返回文本命中的意图标签（去重、按命中次数降序，最多 4 个）。"""
    low = (text or "").lower()
    hits = collections.Counter()
    for label, kws in INTENTS.items():
        for kw in kws:
            if _MATCHERS[(label, kw)](low):
                hits[label] += 1
    return [label for label, _n in hits.most_common(4)]


def label_session(texts: Iterable[str]) -> tuple[list[str], list[str]]:
    """给一个会话（多条消息正文）打标签，**按命中次数计分并设阈值**。

    为什么不"出现一次就打标"（实测教训）：
      「16G内存可用14.2G是否被虚拟占用」这个会话只是正文里出现过一次「字段」
      就被打上「字段抽取」，一次「风险」→「合规与风险」，一次「性能」→「部署与性能」。
      泛词（字段/风险/性能/解析）在本语料里到处出现，出现一次不足以说明话题。

    规则：
      · 实体：按出现次数计分，保留 **≥2 次**的（若一个都没有则保留最高分的 1 个，
        避免短会话无标签），最多 3 个（主次之分）。
      · 意图：按命中次数计分，保留 **≥2 次**的，最多 4 个。
    """
    ent_hits: collections.Counter = collections.Counter()
    intent_hits: collections.Counter = collections.Counter()
    intent_strong: set[str] = set()
    for t in texts:
        low = (t or "").lower()
        if not low:
            continue
        for mt, canon in _ENTITY_MATCHERS:
            if mt(low):
                ent_hits[canon] += 1
        for (label, kw), mt in _MATCHERS.items():
            if mt(low):
                intent_hits[label] += 1
                if _is_specific(kw):
                    intent_strong.add(label)

    ents = [e for e, n in ent_hits.most_common(3) if n >= 2]
    if not ents and ent_hits:
        ents = [ent_hits.most_common(1)[0][0]]
    intents = [lb for lb, n in intent_hits.most_common()
               if n >= 2 or lb in intent_strong][:4]
    return ents, intents


def label_session_scored(texts: Iterable[str],
                         tool_dirs=None) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
    """同 `label_session`，但返回 (标签, 命中次数)，供写库排序用。

    **实体归属优先级：工具路径 > 正文提及。**
    工具路径比正文硬得多（正文会为了背景介绍而大量提及别的项目；
    实测有会话在 cwd=F:\\demo-kb 里干活、产出 F:\\agent-memory，正文却在聊 demo-base）。
    没有工具路径时才退回正文统计。
    """
    texts = list(texts)
    intent_hits: collections.Counter = collections.Counter()
    intent_strong: set[str] = set()
    for t in texts:
        low = (t or "").lower()
        if not low:
            continue
        for (label, kw), mt in _MATCHERS.items():
            if mt(low):
                intent_hits[label] += 1
                if _is_specific(kw):
                    intent_strong.add(label)

    ents = entities_from_paths(tool_dirs)
    if not ents:
        ent_hits: collections.Counter = collections.Counter()
        for t in texts:
            low = (t or "").lower()
            if not low:
                continue
            for mt, canon in _ENTITY_MATCHERS:
                if mt(low):
                    ent_hits[canon] += 1
        ents = [(e, n) for e, n in ent_hits.most_common(3) if n >= 2]
        if not ents and ent_hits:
            ents = [ent_hits.most_common(1)[0]]

    intents = [(lb, n) for lb, n in intent_hits.most_common()
               if n >= 2 or lb in intent_strong][:4]
    return ents, intents
