#!/usr/bin/env python3
"""
foundation/feedback_extractor.py — 评估反馈提取器

从 eval_logs/ 中加载最新的 foundation 评估 JSON，
提取评分 ≤ 阈值的维度的 fix 建议，拼接为增量改进指导文本。

用于 Foundation 增量改进架构：
  迭代 1: 从头生成
  迭代 2+: 加载上一轮的输出 + 评估反馈 → 传给 gen 函数做针对性改进
"""

import json
from pathlib import Path
from typing import Optional

from core.config import EVAL_LOGS_DIR


# ============================================================================
# 维度 → 步骤 映射表
# ============================================================================

# 将评估维度映射到 Foundation 生成步骤，用于 map_feedback_to_step()
_DIMENSION_TO_STEP: dict[str, str] = {
    # LORE & WORLDBUILDING → world
    "power_system_or_social_structure": "world",
    "world_history_or_era_context":    "world",
    "geography_and_culture":           "world",
    "lore_interconnection":            "world",
    "iceberg_depth":                   "world",

    # CHARACTER → characters
    "character_depth":            "characters",
    "character_distinctiveness":  "characters",
    "character_secrets":          "characters",

    # STRUCTURE → outline / outline_volume / outline_part2
    "outline_completeness":   "outline",
    "foreshadowing_balance":  "outline_part2",

    # CRAFT → canon / voice
    "internal_consistency":  "canon",
    "originality":           "voice",
    "ai_purity":             "voice",
}


# ============================================================================
# 公共 API
# ============================================================================

def load_latest_foundation_eval() -> Optional[dict]:
    """加载 eval_logs/ 中最新的 foundation_*.json。

    按文件名排序（时间戳格式 YYYYMMDD_HHMMSS），取最后一个。

    Returns:
        解析后的评估 JSON dict；目录不存在或无匹配文件时返回 None。
    """
    if not EVAL_LOGS_DIR.exists():
        return None

    candidates = sorted(EVAL_LOGS_DIR.glob("foundation_*.json"))
    if not candidates:
        return None

    latest = candidates[-1]
    try:
        return json.loads(latest.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return None


def extract_feedback(eval_json: dict, min_score: int = 7) -> str:
    """从评估 JSON 中提取所有 ≤ min_score 维度的 fix 建议。

    遍历 eval_json 中的维度（可能在顶层或 'dimensions' 子键中），
    对每个 score ≤ min_score 的维度，提取其 weakness + fix 信息，
    拼接为一段可用于改进指导的文本。

    Args:
        eval_json: 评估 JSON（来自 load_latest_foundation_eval()）。
        min_score: 分数阈值，≤ 此值的维度会被提取反馈。

    Returns:
        拼接后的改进指导文本；无反馈时返回空字符串。
    """
    if not eval_json:
        return ""

    # 定位维度数据：可能在顶层直接是维度，也可能在 'dimensions' 子键中
    dims = _find_dimensions(eval_json)
    if not dims:
        return ""

    feedback_parts: list[str] = []

    for dim_name, dim_data in dims.items():
        if not isinstance(dim_data, dict):
            continue

        score = _extract_score(dim_data)
        if score is None or score > min_score:
            continue

        weakness = _extract_field(dim_data, ["weakness", "最大弱点", "issue", "problem"])
        fix = _extract_field(dim_data, ["fix", "改进方案", "improvement", "suggestion", "recommendation"])

        dim_label = _dimension_label(dim_name)

        part = f"【{dim_label}】(评分 {score}/10)"
        if weakness:
            part += f"\n  弱点: {weakness}"
        if fix:
            part += f"\n  改进建议: {fix}"
        feedback_parts.append(part)

    if not feedback_parts:
        return ""

    header = (
        "以下是根据评估裁判反馈提取的改进建议，"
        f"共 {len(feedback_parts)} 个维度需要改进（评分 ≤ {min_score}）：\n\n"
    )
    return header + "\n\n".join(feedback_parts)


def map_feedback_to_step(eval_json: dict, step_name: str) -> str:
    """按步骤名筛选相关反馈。

    根据预定义的维度→步骤映射表，从评估 JSON 中提取与指定步骤
    相关的维度的 fix 建议。

    Args:
        eval_json: 评估 JSON。
        step_name: 步骤名，如 'world', 'characters', 'outline', 'canon', 'voice',
                   'outline_volume', 'outline_part2'。

    Returns:
        该步骤相关的反馈文本；无相关反馈时返回空字符串。
    """
    if not eval_json:
        return ""

    dims = _find_dimensions(eval_json)
    if not dims:
        return ""

    relevant_parts: list[str] = []

    for dim_name, dim_data in dims.items():
        if not isinstance(dim_data, dict):
            continue

        mapped_step = _DIMENSION_TO_STEP.get(dim_name)
        if mapped_step != step_name:
            continue

        score = _extract_score(dim_data)
        weakness = _extract_field(dim_data, ["weakness", "最大弱点", "issue", "problem"])
        fix = _extract_field(dim_data, ["fix", "改进方案", "improvement", "suggestion", "recommendation"])

        dim_label = _dimension_label(dim_name)

        part = f"【{dim_label}】"
        if score is not None:
            part += f" (评分 {score}/10)"
        if weakness:
            part += f"\n  弱点: {weakness}"
        if fix:
            part += f"\n  改进建议: {fix}"
        relevant_parts.append(part)

    if not relevant_parts:
        return ""

    return "\n\n".join(relevant_parts)


# ============================================================================
# 内部辅助
# ============================================================================

def _find_dimensions(eval_json: dict) -> dict:
    """在评估 JSON 中定位维度数据。

    尝试多种常见结构：
    1. eval_json["dimensions"] — 显式 dimensions 子键
    2. eval_json 本身 — 顶层直接是维度（排除已知的元数据键）
    """
    # 路径 1: 显式 dimensions 子键
    if "dimensions" in eval_json and isinstance(eval_json["dimensions"], dict):
        return eval_json["dimensions"]

    # 路径 2: 顶层直接是维度（排除元数据键）
    meta_keys = {
        "timestamp", "phase", "raw_output", "overall_score",
        "lore_score", "character_score", "structure_score", "craft_score",
        "top_3_revisions", "ai_patterns_detected", "overall_assessment",
    }
    dims = {}
    for key, val in eval_json.items():
        if key not in meta_keys and isinstance(val, dict):
            # 检查是否像维度数据（包含 score 或 weakness 等字段）
            if any(k in val for k in ("score", "weakness", "最大弱点", "fix", "改进方案")):
                dims[key] = val
    return dims


def _extract_score(dim_data: dict) -> Optional[int]:
    """从维度数据中提取数值评分。"""
    for key in ("score", "评分", "rating"):
        val = dim_data.get(key)
        if val is not None:
            try:
                return int(val)
            except (ValueError, TypeError):
                try:
                    return int(float(val))
                except (ValueError, TypeError):
                    pass
    return None


def _extract_field(dim_data: dict, candidates: list[str]) -> str:
    """尝试多个候选键名提取字段值。"""
    for key in candidates:
        val = dim_data.get(key)
        if val and isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _dimension_label(dim_name: str) -> str:
    """将维度英文键名转为可读中文标签。"""
    _LABELS: dict[str, str] = {
        "power_system_or_social_structure": "核心规则/社会结构",
        "world_history_or_era_context":     "世界历史/时代背景",
        "geography_and_culture":            "地理与文化",
        "lore_interconnection":             "设定互联性",
        "iceberg_depth":                    "冰山深度",
        "character_depth":                  "角色深度",
        "character_distinctiveness":        "角色区分度",
        "character_secrets":                "角色秘密",
        "outline_completeness":             "大纲完整度",
        "foreshadowing_balance":            "伏笔平衡",
        "internal_consistency":             "内部一致性",
        "originality":                      "原创性",
        "ai_purity":                        "AI痕迹检测",
    }
    return _LABELS.get(dim_name, dim_name)
