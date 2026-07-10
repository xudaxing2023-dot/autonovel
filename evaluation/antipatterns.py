#!/usr/bin/env python3
"""
evaluation/antipatterns.py — 结构反模式检测器

跨体裁中文小说 AI 写作反模式检测。
所有检测基于统计特征，不依赖题材关键词。
参考: ANTI-PATTERNS.md + ANTI_PATTERNS_ZH.md
"""

import re
from typing import List, Dict

from core.pattern_registry import registry


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
            # 提取匹配行前后 30 字上下文
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
    - 「X、Y、Z」顿号三连（在文学性散文中过密）
    返回: {"count": int, "examples": [str]}
    """
    hits = []

    # 模式1: 连续三个句号分隔的短句 (< 20 字) 且具有重复结构
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    for para in paragraphs:
        sentences = registry.match("text.sentence_split", para).value
        sentences = [s.strip() for s in sentences if s.strip()]
        for i in range(len(sentences) - 2):
            s1, s2, s3 = sentences[i], sentences[i + 1], sentences[i + 2]
            if all(len(s) < 20 for s in (s1, s2, s3)):
                # 相似结尾 或 相似开头 = 同类项特征
                same_end = (s1[-2:] == s2[-2:] == s3[-2:] if all(len(s) >= 2 for s in (s1, s2, s3)) else False)
                same_start = (s1[:2] == s2[:2] == s3[:2] if all(len(s) >= 2 for s in (s1, s2, s3)) else False)
                if same_end or same_start:
                    hits.append(f"{s1}。{s2}。{s3}")
                    break  # 每段最多标记一次

    # 模式2: 顿号三连及以上（在叙事段落中，排除专名列举）
    dunhao_matches = re.findall(r'[\u4e00-\u9fff]+(?:、[\u4e00-\u9fff]+){2,}', text)
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
        l1, l2, l3 = lengths[i], lengths[i + 1], lengths[i + 2]
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
    breaks = re.findall(r'^(?:---|\*\*\*|___)\s*$', text, re.MULTILINE)
    count = len(breaks)
    return {"count": count, "excessive": count > 2}


# ============================================================================
# 7. 目录式思考检测 (CATALOGING-BY-THINKING)
# ============================================================================

# 已迁移到 Pattern Registry: antipattern.catalog_think


def detect_catalog_thinking(text: str) -> dict:
    """
    检测「他想到了 X。他想到了 Y。他想到了 Z。」模式。
    真正内心世界是混乱的，不是目录式的。
    返回: {"count": int, "per_1000_chars": float}
    """
    char_count = len(text.replace(" ", "").replace("\n", "")) or 1
    matches = registry.match("antipattern.catalog_think", text).value
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
            # 多种可能的统计键名，按优先级获取
            count = val.get("count",
                     val.get("per_1000_chars",
                     val.get("uniform_streak_ratio",
                     val.get("length_cv", "?"))))
            lines.append(f"  {key}: {count}")
    if audit["warning_count"] > 0:
        lines.append(f"⚠ 警告 ({audit['warning_count']} 项):")
        for w in audit["warnings"]:
            lines.append(f"  — {w}")
    else:
        lines.append("  ✓ 无显著结构反模式")
    return "\n".join(lines)