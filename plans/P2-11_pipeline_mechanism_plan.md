# P2-11 Pipeline 机制补充 — 详细实施计划

## 设计原则（体裁无关）

三条规则确保对所有中文小说类型通用（言情、悬疑、历史、现实主义、科幻、武侠等）：

1. **slop 检测规则已体裁无关**：现有 [`slop_score_zh()`](evaluation/evaluate.py:67) 的 Tier1/Tier2/Tier3 全部是中文 AI 通用套话（「眼中闪过一丝」「嘴角微微上扬」「深深地吸了一口气」等），与题材无关。本轮只增加 **结构型** 反模式检测（过度解释、三连罗列、段落均匀化等），同样是跨体裁的。

2. **反模式注入走独立模块**：不从 [`ANTI_PATTERNS_ZH.md`](reference/ANTI_PATTERNS_ZH.md:1) 机械复制文本做 prompt 注入，而是编写**体裁无关的结构检测器**（统计段落长度 CV、否定句式密度、比喻频次等），不依赖题材关键词。

3. **所有阈值可通过 `core/config.py` 配置**，不硬编码特定类型的期望值。

---

## 总体架构

```
┌─────────────────────────────────────────────────────────────┐
│                  pipeline_orchestrator.py                    │
│                                                             │
│  run_foundation()                                           │
│    └─ generate_canon()                                      │
│    └─ ★ NEW: _validate_canon_size()  ← 子项 A              │
│                                                             │
│  run_drafting()                                             │
│    └─ for ch in chapters:                                   │
│         └─ draft_chapter()                                  │
│         └─ evaluate_chapter()  → slop_score_zh() (已有)     │
│         └─ ★ NEW: _run_post_draft_checks() ← 子项 B/C      │
│              ├─ slop_penalty > 阈值 → 强制重写              │
│              └─ 结构反模式检测 → 生成警告报告               │
│                                                             │
│  ★ NEW: evaluation/antipatterns.py  ← 子项 C               │
│    ├─ detect_over_explain()     过度解释检测               │
│    ├─ detect_triadic_listing()  三连罗列检测               │
│    ├─ detect_negative_assertions() 否定断言密度            │
│    ├─ detect_simile_crutch()    比喻拐杖检测               │
│    ├─ detect_paragraph_uniformity() 段落均匀化             │
│    ├─ detect_section_break_abuse() 分隔符滥用              │
│    └─ run_structural_audit()    汇总入口                   │
└─────────────────────────────────────────────────────────────┘
```

---

## 子项 A：canon 400+ 门槛验证

### 目标
[`gen_canon.py`](foundation/gen_canon.py:62) 的 prompt 要求"目标：400+ 条事实"，但 [`run_foundation()`](pipeline_orchestrator.py:106) 从未验证是否达标。

### 修改文件

#### 1. `foundation/gen_canon.py`

新增函数 `count_canon_entries()`：

```python
def count_canon_entries(canon_path: Path = None) -> dict:
    """
    统计 canon.md 中各节事实条目数。
    条目 = 以「—」开头的行（排除空行和标题行）。
    返回: {"total": N, "world": N, "character": N, "timeline": N, "rules": N}
    """
    if canon_path is None:
        canon_path = OUTPUT_DIR / "canon.md"
    if not canon_path.exists():
        return {"total": 0, "world": 0, "character": 0, "timeline": 0, "rules": 0}

    text = canon_path.read_text(encoding="utf-8")
    sections = {"一、世界观": 0, "二、角色": 0, "三、时间线": 0, "四、规则": 0}
    current_section = None

    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        # 检测节标题
        for key in sections:
            if key in line and line.startswith("##"):
                current_section = key
                break
        # 统计条目
        if current_section and line.startswith("—"):
            sections[current_section] += 1

    total = sum(sections.values())
    return {
        "total": total,
        "world": sections["一、世界观"],
        "character": sections["二、角色"],
        "timeline": sections["三、时间线"],
        "rules": sections["四、规则"],
    }
```

**体裁无关性**：该计数器纯粹统计 `—` 开头的条目行，不依赖任何题材关键词。400 条门槛适用于所有类型——言情需要人物关系事实、历史需要时代细节事实、科幻需要科技设定事实，都需要足够的信息密度。

#### 2. `pipeline_orchestrator.py` → `run_foundation()`

在 L108（`generate_canon()` 之后）插入验证逻辑：

```python
# 5. 生成正典
step("生成正典 canon.md ...")
from foundation.gen_canon import generate_canon, count_canon_entries
generate_canon(max_tokens=max_tokens)

# ★ NEW: 验证正典规模
canon_counts = count_canon_entries()
canon_total = canon_counts["total"]
canon_threshold = getattr(cfg, "canon_min_entries", 400) if cfg.loaded else 400

step(f"正典条目数: {canon_total} "
     f"(世界观{canon_counts['world']} + 角色{canon_counts['character']} "
     f"+ 时间线{canon_counts['timeline']} + 规则{canon_counts['rules']})")

if canon_total < canon_threshold:
    step(f"⚠ 警告: 正典条目 {canon_total} < {canon_threshold}，"
         f"信息密度不足，将在评估中体现")
    # 可选: 如果 < 200 则强制重生成
    if canon_total < 200:
        step("正典严重不足 (<200)，将使用更大 token 预算重试…")
        # 不中断，但记录到 state 中供后续迭代参考
```

#### 3. `core/config.py`

新增可选配置属性（与已有模式一致）：

```python
canon_min_entries: int = 400  # 正典最低条目数门槛
```

### 验证方式
- 运行 `run_foundation()` 后检查控制台输出是否打印了条目计数
- 手动创建一个 < 400 条的 canon.md 确认警告触发
- 单元测试：`test_count_canon_entries()` 覆盖各节计数逻辑

---

## 子项 B：起草后 slop 扫描闭环

### 目标
现有 [`evaluate_chapter()`](evaluation/evaluate.py:204) 调用了 [`slop_score_zh()`](evaluation/evaluate.py:67) 但结果仅输出到 stderr。需将 slop_penalty 纳入 [`run_drafting()`](pipeline_orchestrator.py:163) 的保留/丢弃决策。

### 修改文件

#### 1. `evaluation/evaluate.py` → `evaluate_chapter()`

修改返回值，使 slop 检测结果可被调用方获取。方案：在 eval log JSON 中已保存 mechanical 字段（L234），只需新增一个便捷函数提取 slop_penalty：

```python
def get_last_slop_penalty(ch_num: int) -> float:
    """读取最近一次章节评估的 slop_penalty。"""
    import json
    logs = sorted(EVAL_LOGS_DIR.glob(f"chapter_{ch_num:02d}_*.json"))
    if not logs:
        return 0.0
    with open(logs[-1], "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("mechanical", {}).get("slop_penalty", 0.0)
```

#### 2. `pipeline_orchestrator.py` → `run_drafting()`

在 L208 评估结果之后插入 slop 检查（与 LLM 评分并列作为决策依据）：

```python
# 评估
eval_result = evaluate_chapter(ch)
score = parse_score(eval_result, "overall_score")

# ★ NEW: 获取 slop 惩罚分
from evaluation.evaluate import get_last_slop_penalty
slop_penalty = get_last_slop_penalty(ch)
slop_threshold = getattr(cfg, "slop_penalty_threshold", 3.0) if cfg.loaded else 3.0

step(f"第 {ch} 章评分: {score}  (slop_penalty: {slop_penalty})")

# ★ NEW: slop 过高时强制重写（即使 LLM 评分达标）
slop_fail = slop_penalty > slop_threshold

if score >= threshold and not slop_fail:
    # 通过 — 保留
    ...
elif slop_fail and score >= threshold:
    step(f"⚠ LLM 评分达标 ({score}) 但 slop_penalty 过高 "
         f"({slop_penalty} > {slop_threshold})，触发反套话重写…")
    # 不保留此版本，直接 continue 进入下一次 attempt
    # 可选: 在下一次 draft 时注入更严格的 anti-slop system prompt
    if ch_file.exists():
        ch_file.unlink()
    continue  # 进入下一次尝试
else:
    # 原有逻辑: 评分不达标，丢弃
    ...
```

**体裁无关性**：`slop_score_zh()` 的 Tier1/Tier2 规则已完全体裁无关（全都是中文 AI 通用套话，不属于任何题材）。阈值 3.0 是一个合理的起跑线——允许少量 AI 痕迹（如写古风文偶尔出现的成语堆砌），但惩罚过度模式化的输出。阈值可在 config 中按需调整。

#### 3. `core/config.py`

```python
slop_penalty_threshold: float = 3.0  # slop_penalty 超过此值触发强制重写
```

### 验证方式
- 构造一段高 slop 文本（包含多个 Tier1 匹配），确认触发重写
- 正常草拟一章节，确认 slop_penalty 被打印且参与决策
- 边界测试：slop_penalty = 0（完全干净）时不应触发重写

---

## 子项 C：反模式注入（结构型检测器）

### 目标
英文原版 [`ANTI-PATTERNS.md`](ANTI-PATTERNS.md:1) 定义了 12 种结构反模式，中文版 [`ANTI_PATTERNS_ZH.md`](reference/ANTI_PATTERNS_ZH.md:1) 适配了 8 种。当前这些知识**完全未被代码引用**。需创建体裁无关的结构检测器，在起草后对每章运行。

### 新增文件: `evaluation/antipatterns.py`

全部检测规则从统计特征出发，不使用题材关键词，适用于所有类型的中文小说。

```python
#!/usr/bin/env python3
"""
evaluation/antipatterns.py — 结构反模式检测器

跨体裁中文小说 AI 写作反模式检测。
所有检测基于统计特征，不依赖题材关键词。
参考: ANTI-PATTERNS.md + ANTI_PATTERNS_ZH.md
"""

import re
from typing import List, Dict


# ============================================================================
# 1. 过度解释检测 (OVER-EXPLAIN)
# ============================================================================

# 情感/状态展示后紧跟的"解释性"句式
OVER_EXPLAIN_PATTERNS = [
    r'(?:这|那)\s*(?:意味着|说明|表明|代表着|表示)\s*',
    r'(?:换句话|简单来|直白地?)\s*说',
    r'(?:说白了|说白了就是|也就是说)',
    r'他(?:终于)?\s*(?:明白|意识到|懂了|领悟到|知道了)',
    r'她(?:终于)?\s*(?:明白|意识到|懂了|领悟到|知道了)',
    r'(?:原因|答案)\s*(?:是|在于|很简单)',
]

def detect_over_explain(text: str) -> dict:
    """
    检测过度解释模式。
    在场景已展示情感/状态后，叙述者又用文字复述一遍。
    返回: {"count": int, "examples": [str]}
    """
    hits = []
    for pattern in OVER_EXPLAIN_PATTERNS:
        for match in re.finditer(pattern, text):
            # 提取匹配行前后 60 字上下文
            start = max(0, match.start() - 30)
            end = min(len(text), match.end() + 30)
            ctx = text[start:end].replace("\n", " ")
            hits.append(ctx)
    return {"count": len(hits), "examples": hits[:5]}


# ============================================================================
# 2. 三连罗列检测 (TRIADIC LISTING)
# ============================================================================

def detect_triadic_listing(text: str) -> dict:
    """
    检测三连罗列模式:
    - 「X。Y。Z。」连续三个短句
    - 「X 和 Y 和 Z」同类项堆砌
    - 「X、Y、Z」顿号三连（在文学性散文中过密）
    返回: {"count": int, "examples": [str]}
    """
    hits = []

    # 模式1: 连续三个句号分隔的短句 (< 15 字)
    # 在段落内逐句检测
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    for para in paragraphs:
        sentences = re.split(r'[。！？]', para)
        sentences = [s.strip() for s in sentences if s.strip()]
        for i in range(len(sentences) - 2):
            s1, s2, s3 = sentences[i], sentences[i+1], sentences[i+2]
            if all(len(s) < 20 for s in (s1, s2, s3)):
                # 检查是否有重复结构（同类项特征）
                if (s1[-2:] == s2[-2:] == s3[-2:] or  # 相似结尾
                    all(s.startswith(s1[:2]) for s in (s2, s3))):  # 相似开头
                    hits.append(f"{s1}。{s2}。{s3}")
                    break  # 每段最多标记一次

    # 模式2: 顿号三连及以上（在叙事段落中）
    dunhao_matches = re.findall(r'[\u4e00-\u9fff]+(?:、[\u4e00-\u9fff]+){2,}', text)
    # 过滤掉明显是专有名词列举的（如姓名、地名、章节标题等）
    for dm in dunhao_matches[:10]:
        if len(dm) < 30 and not re.search(r'[第章回节卷]', dm):
            hits.append(dm)

    return {"count": len(hits), "examples": hits[:5]}


# ============================================================================
# 3. 否定式断言密度 (NEGATIVE-ASSERTION)
# ============================================================================

NEGATIVE_PATTERN = re.compile(
    r'(?:他|她|它|他们|她们|我|你)\s*没有\s*[\u4e00-\u9fff]+'
)

def detect_negative_assertions(text: str) -> dict:
    """
    检测「他没有回头」「她没有说出…」等否定式断言。
    每章 > 5 次即为 tic。
    返回: {"count": int, "per_1000_chars": float, "examples": [str]}
    """
    char_count = len(text.replace(" ", "").replace("\n", "")) or 1
    matches = NEGATIVE_PATTERN.findall(text)
    unique = list(set(matches))
    return {
        "count": len(matches),
        "per_1000_chars": round(len(matches) / char_count * 1000, 2),
        "examples": unique[:5],
    }


# ============================================================================
# 4. 比喻拐杖检测 (SIMILE CRUTCH)
# ============================================================================

SIMILE_PATTERN = re.compile(
    r'(?:像|如同|仿佛|好比|好似|宛如|犹如|俨然|恍如)'
)

def detect_simile_crutch(text: str) -> dict:
    """
    检测比喻词密度。
    中文 AI 倾向每 200 字一个比喻。人类作者变化更多。
    返回: {"count": int, "per_1000_chars": float}
    """
    char_count = len(text.replace(" ", "").replace("\n", "")) or 1
    matches = SIMILE_PATTERN.findall(text)
    return {
        "count": len(matches),
        "per_1000_chars": round(len(matches) / char_count * 1000, 2),
    }


# ============================================================================
# 5. 段落长度均匀化检测 (PARAGRAPH UNIFORMITY)
# ============================================================================

def detect_paragraph_uniformity(text: str) -> dict:
    """
    检测段落长度均匀化。
    AI 段落大多 4-6 句。检查连续 3 段长度相近的比例。
    返回: {"uniform_streak_ratio": float, "length_cv": float, "median_len": int}
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip() and len(p.strip()) > 20]
    if len(paragraphs) < 5:
        return {"uniform_streak_ratio": 0.0, "length_cv": 0.0, "median_len": 0}

    lengths = [len(p) for p in paragraphs]
    mean_len = sum(lengths) / len(lengths)
    std_len = (sum((l - mean_len) ** 2 for l in lengths) / len(lengths)) ** 0.5
    cv = std_len / mean_len if mean_len > 0 else 0

    # 连续 3+ 段长度差 < 20%
    uniform_streaks = 0
    i = 0
    while i < len(lengths) - 2:
        l1, l2, l3 = lengths[i], lengths[i+1], lengths[i+2]
        avg = (l1 + l2 + l3) / 3
        if avg > 0 and all(abs(l - avg) / avg < 0.20 for l in (l1, l2, l3)):
            uniform_streaks += 1
            i += 3
        else:
            i += 1

    return {
        "uniform_streak_ratio": round(uniform_streaks / max(len(lengths) / 3, 1), 2),
        "length_cv": round(cv, 2),
        "median_len": sorted(lengths)[len(lengths) // 2],
    }


# ============================================================================
# 6. 分隔符滥用检测 (SECTION BREAK ABUSE)
# ============================================================================

def detect_section_break_abuse(text: str) -> dict:
    """
    检测「---」或「***」分隔符使用。
    每章 > 2 个为过度。
    返回: {"count": int, "excessive": bool}
    """
    # 匹配 Markdown 分隔线
    breaks = re.findall(r'^(?:---|\*\*\*|___)\s*$', text, re.MULTILINE)
    count = len(breaks)
    return {"count": count, "excessive": count > 2}


# ============================================================================
# 7. 目录式思考检测 (CATALOGING-BY-THINKING)
# ============================================================================

CATALOG_THINK_PATTERN = re.compile(
    r'(?:他|她)\s*(?:想|思考|思索|琢磨|盘算|回忆).*?(?:了|着|到)'
)

def detect_catalog_thinking(text: str) -> dict:
    """
    检测「他想到了 X。他想到了 Y。他想到了 Z。」模式。
    真正内心世界是混乱的，不是目录式的。
    返回: {"count": int, "per_1000_chars": float}
    """
    char_count = len(text.replace(" ", "").replace("\n", "")) or 1
    matches = CATALOG_THINK_PATTERN.findall(text)
    return {
        "count": len(matches),
        "per_1000_chars": round(len(matches) / char_count * 1000, 2),
    }


# ============================================================================
# 8. 批量检测入口
# ============================================================================

def run_structural_audit(text: str) -> dict:
    """
    运行全部结构反模式检测，返回汇总报告。
    所有检测体裁无关，适用于任何中文小说类型。
    """
    results = {
        "over_explain": detect_over_explain(text),
        "triadic_listing": detect_triadic_listing(text),
        "negative_assertions": detect_negative_assertions(text),
        "simile_crutch": detect_simile_crutch(text),
        "paragraph_uniformity": detect_paragraph_uniformity(text),
        "section_break_abuse": detect_section_break_abuse(text),
        "catalog_thinking": detect_catalog_thinking(text),
    }

    # 汇总警告
    warnings = []
    if results["over_explain"]["count"] >= 3:
        warnings.append(f"过度解释: {results['over_explain']['count']} 处")
    if results["triadic_listing"]["count"] >= 2:
        warnings.append(f"三连罗列: {results['triadic_listing']['count']} 处")
    if results["negative_assertions"]["count"] > 5:
        warnings.append(f"否定断言过多: {results['negative_assertions']['count']} 次")
    if results["simile_crutch"]["per_1000_chars"] > 2.5:
        warnings.append(f"比喻密度过高: {results['simile_crutch']['per_1000_chars']}/千字")
    if results["paragraph_uniformity"]["uniform_streak_ratio"] > 0.5:
        warnings.append(f"段落均匀化: ratio {results['paragraph_uniformity']['uniform_streak_ratio']}")
    if results["section_break_abuse"]["excessive"]:
        warnings.append(f"分隔符过多: {results['section_break_abuse']['count']} 个")
    if results["catalog_thinking"]["per_1000_chars"] > 1.5:
        warnings.append(f"目录式思考: {results['catalog_thinking']['per_1000_chars']}/千字")

    results["warnings"] = warnings
    results["warning_count"] = len(warnings)
    return results


def format_audit_report(audit: dict) -> str:
    """格式化结构审计为可读字符串。"""
    lines = ["[结构反模式审计]"]
    for key, val in audit.items():
        if key in ("warnings", "warning_count"):
            continue
        if isinstance(val, dict):
            count = val.get("count", val.get("per_1000_chars", "?"))
            lines.append(f"  {key}: {count}")
    if audit["warning_count"] > 0:
        lines.append(f"⚠ 警告 ({audit['warning_count']} 项):")
        for w in audit["warnings"]:
            lines.append(f"  — {w}")
    else:
        lines.append("  ✓ 无显著结构反模式")
    return "\n".join(lines)
```

#### 体裁无关性设计要点

| 检测器 | 为什么体裁无关 |
|---|---|
| `detect_over_explain` | 解释性句式（「这意味着」「说白了」）在言情、悬疑、历史文中同样泛滥——AI 在所有体裁中都倾向于"展示后又解释一遍" |
| `detect_triadic_listing` | 三连罗列是 AI 的底层生成偏好，与题材设定无关。言情文中「他的眼神。他的呼吸。他的沉默。」= 历史文中「刀光。血影。马蹄声。」 |
| `detect_negative_assertions` | 「他没有…」是中文 AI 在任何叙事中的万能回避句式 |
| `detect_simile_crutch` | 「像/如同/仿佛」频率过高是所有体裁 AI 文本的共同问题 |
| `detect_paragraph_uniformity` | 段落长度 CV 是纯统计量，完全与内容无关 |
| `detect_section_break_abuse` | `---` 分隔符计数是结构特征，与题材无关 |
| `detect_catalog_thinking` | 「他想到了 X」在任何题材（言情/悬疑/历史）中都是同一模式 |

### 修改文件: `pipeline_orchestrator.py` → `run_drafting()`

在 L219 voice fingerprint 检查之后（或与之合并），插入结构反模式审计：

```python
# ★ NEW: 结构反模式审计（每章起草后）
try:
    from evaluation.antipatterns import run_structural_audit, format_audit_report
    audit = run_structural_audit(chapter_text)
    if audit["warning_count"] > 0:
        step(f"⚠ 结构反模式警告 (第 {ch} 章):")
        for w in audit["warnings"]:
            step(f"  — {w}")
        # 如果警告 ≥ 4，触发强制重写
        if audit["warning_count"] >= 4:
            step(f"结构反模式过多 ({audit['warning_count']} 项)，触发重写…")
            if ch_file.exists():
                ch_file.unlink()
            continue
    else:
        step(f"结构反模式: ✓")
except Exception as e:
    step(f"结构反模式审计跳过: {e}")
```

#### `core/config.py` 新增

```python
antipattern_max_warnings: int = 4  # 每章最多容忍的反模式警告数
```

### 验证方式
- 单元测试：使用已知 AI slop 文本和人类写作文本跑 `run_structural_audit()`，确认检测器区分度
- 边界测试：空文本、极短文本（< 100 字）、纯对话文本
- 集成测试：运行 `run_drafting()` 起草一章，确认审计结果打印到控制台

---

## 修改文件总览

| 文件 | 操作 | 内容 |
|---|---|---|
| `evaluation/antipatterns.py` | **新建** | 7 个结构反模式检测器 + `run_structural_audit()` 入口 |
| `foundation/gen_canon.py` | **修改** | 新增 `count_canon_entries()` 函数 |
| `evaluation/evaluate.py` | **修改** | 新增 `get_last_slop_penalty()` 便捷函数 |
| `pipeline_orchestrator.py` | **修改** | `run_foundation()` 插入 canon 验证；`run_drafting()` 插入 slop 闭环 + 反模式审计 |
| `core/config.py` | **修改** | 新增 `canon_min_entries`、`slop_penalty_threshold`、`antipattern_max_warnings` |

---

## 实施顺序

```
Step 1: 创建 evaluation/antipatterns.py（独立模块，可单独测试）
Step 2: 修改 foundation/gen_canon.py + count_canon_entries()
Step 3: 修改 evaluation/evaluate.py + get_last_slop_penalty()
Step 4: 修改 core/config.py — 增加 3 个新配置属性
Step 5: 修改 pipeline_orchestrator.py:
        5a: run_foundation() — canon 验证
        5b: run_drafting() — slop 闭环
        5c: run_drafting() — 反模式审计
Step 6: 编写单元测试 (_test_unit.py 扩展或新建 _test_antipatterns.py)
Step 7: 端到端验证（运行 run_foundation + run_drafting 各 1 章）
```

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| 反模式检测误报（人类好文本被标记） | 阈值设为偏高（warning_count ≥ 4 才强制重写），单次警告只输出不拦截 |
| slop_penalty 阈值对不同长度的章节不公平 | 使用每千字归一化的密度指标，短章节（< 500 字）降低阈值 |
| canon 计数方式不准确（条目格式不一致） | 日志打印分节明细，允许人工目测确认；后续可加 fuzzy 匹配 |
| 检测器性能影响起草速度 | 全部是 regex + 统计计算，无 LLM 调用，< 100ms/章 |