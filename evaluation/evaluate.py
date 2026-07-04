#!/usr/bin/env python3
"""
evaluation/evaluate.py — 中文小说评估器

双模评估：
1. 机械式：中文 AI 写作痕迹检测（不需要 LLM）
2. LLM 裁判：调用 API 进行语义级评分

用法：
  python evaluate.py --phase=foundation    # 评估基础构建文档
  python evaluate.py --chapter=5           # 评估第 5 章
  python evaluate.py --full                # 评估全文
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from core.config import config, OUTPUT_DIR, CHAPTERS_DIR, EVAL_LOGS_DIR
from core.api_client import call_judge
from prompts.eval_judge_prompts import (
    build_foundation_eval_prompt,
    build_chapter_eval_prompt,
    build_full_novel_eval_prompt,
    JUDGE_SYSTEM_PROMPT,
)


# ============================================================================
# JSON 解析（三级回退）
# ============================================================================

def _parse_json_response(text: str) -> dict:
    """从 LLM 响应中提取 JSON 对象。

    三级回退策略：
      1. 剥除 ```json ... ``` markdown 代码块 → json.loads()
      2. 从首个 { 开始直接 json.loads()
      3. 花括号深度匹配（处理 LLM 在 JSON 后追加额外文本的情况）
    """
    if not text or not text.strip():
        return {}

    text = text.strip()

    # 第1层：剥除 markdown 代码块标记
    if text.startswith("```"):
        text = re.sub(r'^```\w*\n?', '', text)
        text = re.sub(r'\n?```$', '', text)
        text = text.strip()

    # 第2层：从第一个 { 开始直接解析
    start = text.find('{')
    if start == -1:
        start = text.find('[')
    if start == -1:
        return {}

    try:
        return json.loads(text[start:], strict=False)
    except json.JSONDecodeError:
        pass

    # 第3层：花括号深度匹配
    depth = 0
    in_string = False
    escape = False
    open_char = text[start]
    close_char = '}' if open_char == '{' else ']'

    for i in range(start, len(text)):
        c = text[i]
        if escape:
            escape = False
            continue
        if c == '\\' and in_string:
            escape = True
            continue
        if c == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == open_char:
            depth += 1
        elif c == close_char:
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1], strict=False)
                except json.JSONDecodeError:
                    break

    try:
        return json.loads(text[start:], strict=False)
    except json.JSONDecodeError:
        return {}


# ============================================================================
# 中文 AI 写作痕迹检测规则
# ============================================================================

# Tier 1: 高频 AI 套话（检测到就减分）
TIER1_CHINESE_SLOP = [
    "宛如一幅.*画卷", "如同一首.*交响乐",
    "在这个.*的时代",
    "值得一提的是", "不得不说", "不得不承认",
    "令人惊叹的是", "值得注意的是",
    "从此，", "这一切，",
    "不仅仅是.*更是",
]

# Tier 2: 中等频率 AI 模式
TIER2_CHINESE_SLOP = [
    "他感到一阵", "她感到一阵",
    "眼中闪过一丝", "眼中闪过一抹",
    "嘴角微微上扬", "嘴角勾起一抹",
    "深深地吸了一口气", "深吸一口气",
    "心里/脑海中浮现出",
    "一股.*涌上心头",
    "心中.*莫名",
    "心头一",
]

# ——— P3-12: 小说 AI 套话（体裁无关，语义级 AI 痕迹） ———
FICTION_AI_TELLS_ZH = [
    # 感官/情绪套话 — 不绑定任何题材
    r"一阵\S{0,3}的感觉",
    r"一种\S{1,4}的感觉",
    r"不禁感到",
    r"不由得",
    r"空气中弥漫着",
    r"瞪大了眼睛",
    r"睁大了双眼",
    r"一阵\S{0,5}(?:涌上|袭来|席卷)",
    r"一股\S{0,5}(?:涌上|袭来)",
    r"一丝\S{0,3}(?:涌上|掠过)",
    # 心跳/呼吸套话
    r"心(?:脏)?(?:在胸腔里)?狂跳",
    r"心脏剧烈(?:地)?跳动",
    r"(?:长长地|缓缓地)?吐出一口气",
    # 发型/外貌套话 — 适配所有时代/类型
    r"(?:乌黑|黑色|棕色|银白|花白)的?(?:长发|短发|发丝|头发)\S{0,5}(?:散落|倾泻|垂落|披散)",
    # 眼神套话
    r"锐利的目光",
    r"深邃的眼眸",
    r"眼神中(?:闪过|透出|带着)\S{1,6}",
    # 笑容套话
    r"会心一笑",
    r"意味深长的(?:笑|笑容|微笑)",
    # 情感波动套话
    r"(?:他|她|它|他们|她们)(?:感到|觉得)\S{0,3}(?:一阵|一股|一丝)\S{1,6}",
    # 沉默/寂静套话
    r"(?:沉默|寂静|安静)(?:沉重|压抑|令人窒息|蔓延)",
    r"(?:谁也没有说话|没有人开口)",
    # 涌动/苏醒套话
    r"(?:某种|什么东西|一丝\S{0,3})(?:在体内|在心里|在心底)(?:涌动|苏醒|蔓延|升起)",
    # 松了口气套话
    r"(?:暗自|悄悄|终于)(?:松了口气|松了一口气|放下心来)",
]

# ——— P3-12: 结构修辞公式（论说文式论证出现在叙事中 = AI 铁证） ———
STRUCTURAL_AI_TICS_ZH = [
    # "我不是说X，我是说Y"
    r"(?:我)?不是(?:说|指|要|在)\S{1,20}(?:而是|我是)(?:说|指|要|在)\S{1,20}",
    # "这意味着要么X，要么Y"
    r"这意味着(?:要么|要不|不是)\S{1,20}(?:要么|就是|便是)\S{1,20}",
    # "这是有区别的" 收尾公式
    r"(?:这|那)(?:是|就是|才是)(?:有区别|有差别的|两回事|不同的)",
    # "那是两回事"
    r"那(?:是|就是)两回事",
    # "不仅仅是X，更是Y"（增强版）
    r"不仅仅(?:是|在于)\S{1,20}(?:更是|更是为了|而是在于|而是|更是因为)",
    # "不是因为X，而是因为Y" — 叙事中的论证句式
    r"不是因为\S{1,30}(?:而是因为|而是)",
    # "说到底" / "归根结底" 收尾公式
    r"(?:说到底|归根结底|总而言之|综上所述)",
]

# ——— P3-12: 说教式情感（show-don't-tell 检测，体裁无关） ———
TELLING_EMOTION_LABELS = [
    "愤怒", "悲伤", "高兴", "害怕", "紧张", "兴奋", "嫉妒",
    "内疚", "焦虑", "孤独", "绝望", "恐惧", "得意", "痛苦",
    "困惑", "松了一口气", "厌恶", "羞愧", "骄傲", "苦涩",
    "挫败", "失落", "欣慰", "感动", "震惊", "慌张", "烦躁",
    "不安", "期待", "满足",
]
TELLING_ADVERBS = [
    "愤怒地", "悲伤地", "高兴地", "紧张地", "兴奋地",
    "绝望地", "恐惧地", "焦虑地", "内疚地", "苦涩地",
    "疲惫地", "痛苦地", "不安地", "欣慰地", "烦躁地",
]
TELLING_PATTERNS_ZH = (
    [rf"(?:他|她|它|他们|她们|我|你)\S{{0,4}}(?:感到|觉得|显得|看起来)\S{{0,4}}(?:{'|'.join(TELLING_EMOTION_LABELS)})"]
    + [rf"(?:{'|'.join(TELLING_ADVERBS)})"]
)

# ——— P3-12: 段落开头过渡词滥用 ———
TRANSITION_OPENERS_ZH = [
    "然而", "但是", "不过", "可是", "却",
    "此外", "而且", "况且", "再说",
    "与此同时", "另一方面", "与此相对",
    "换言之", "换句话说", "也就是说",
    "事实上", "实际上", "其实",
    "显然", "毫无疑问", "不可否认",
    "当然", "诚然", "的确",
    "毕竟", "终究",
]

# Tier 3: 结构层面检测
# — 连续 3+ 四字成语/形容词
FOUR_CHAR_PATTERN = re.compile(r'[\u4e00-\u9fff]{4}')
# — 破折号密度
EM_DASH_PATTERN = re.compile(r'——')
# — 对话标签重复 「说」「道」
DIALOG_TAG_PATTERN = re.compile(r'(?:说|道)[,，。！？\s]')


def slop_score_zh(text: str) -> dict:
    """
    中文机械 slop 检测。所有检测体裁无关，适用于任何类型的中文小说。

    返回:
      - tier1_hits: list — 高频 AI 套话
      - tier2_hits: list — 中等频率 AI 模式
      - fiction_ai_tells: list — 小说 AI 套话 (P3-12)
      - structural_ai_tics: list — 修辞公式检测 (P3-12)
      - telling_violations: int — 说教式情感计数 (P3-12)
      - four_char_density: float — 四字词密度 (/百字)
      - em_dash_density: float — 破折号密度 (/千字)
      - sentence_cv: float — 句子长度变异系数
      - transition_opener_ratio: float — 过渡词开头的段落比例 (P3-12)
      - dialog_tag_ratio: float — 对话标签比例
      - slop_penalty: float — 综合惩罚分 0-10
    """
    char_count = len(text.replace(" ", "").replace("\n", "")) or 1
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    # Tier 1
    tier1_hits = []
    for pattern in TIER1_CHINESE_SLOP:
        matches = re.findall(pattern, text)
        if matches:
            tier1_hits.append((pattern[:30], len(matches)))

    # Tier 2
    tier2_hits = []
    for pattern in TIER2_CHINESE_SLOP:
        matches = re.findall(pattern, text)
        if matches:
            tier2_hits.append((pattern[:30], len(matches)))

    # 四字词密度
    four_char_matches = FOUR_CHAR_PATTERN.findall(text)
    four_char_sets = set(four_char_matches)
    four_char_density = len(four_char_matches) / (char_count / 100) if char_count else 0

    # 破折号密度
    em_count = len(EM_DASH_PATTERN.findall(text))
    em_density = (em_count / char_count) * 1000 if char_count else 0

    # 对话标签重复度
    dialog_tags = len(DIALOG_TAG_PATTERN.findall(text))
    dialog_ratio = dialog_tags / max(len(paragraphs), 1)

    # 句子长度变化系数
    sentences = re.split(r'[。！？.!?]+', text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 3]
    if len(sentences) > 2:
        lengths = [len(s) for s in sentences]
        mean_len = sum(lengths) / len(lengths)
        variance = sum((l - mean_len) ** 2 for l in lengths) / len(lengths)
        std_len = variance ** 0.5
        sentence_cv = std_len / mean_len if mean_len > 0 else 0
    else:
        sentence_cv = 0.5

    # ——— P3-12: 小说 AI 套话检测 ———
    fiction_tells = []
    for pattern in FICTION_AI_TELLS_ZH:
        matches = re.findall(pattern, text)
        if matches:
            fiction_tells.append((pattern[:40], len(matches)))
    fiction_tell_count = sum(c for _, c in fiction_tells)

    # ——— P3-12: 结构修辞公式检测 ———
    structural_tics = []
    for pattern in STRUCTURAL_AI_TICS_ZH:
        matches = re.findall(pattern, text)
        if matches:
            structural_tics.append((pattern[:40], len(matches)))
    structural_tic_count = sum(c for _, c in structural_tics)

    # ——— P3-12: 说教式情感 (show-don't-tell) 检测 ———
    telling_count = 0
    for pattern in TELLING_PATTERNS_ZH:
        telling_count += len(re.findall(pattern, text))

    # ——— P3-12: 段落开头过渡词比例 ———
    transition_starts = 0
    for para in paragraphs:
        stripped = para.lstrip("　 ")  # 中文全角空格
        first_chars = stripped[:4] if len(stripped) >= 4 else stripped
        if any(first_chars.startswith(opener) for opener in TRANSITION_OPENERS_ZH):
            transition_starts += 1
    transition_ratio = transition_starts / len(paragraphs) if paragraphs else 0

    # ——— 计算惩罚分 ———
    penalty = 0.0
    penalty += sum(c for _, c in tier1_hits) * 0.5  # Tier 1: 每个 0.5 分
    penalty += sum(c for _, c in tier2_hits) * 0.2  # Tier 2: 每个 0.2 分
    if em_density > 3:
        penalty += (em_density - 3) * 0.5
    if dialog_ratio > 0.6:
        penalty += (dialog_ratio - 0.6) * 5
    # P3-12 新增
    penalty += min(fiction_tell_count * 0.3, 2.0)
    penalty += min(structural_tic_count * 0.5, 2.0)
    penalty += min(telling_count * 0.2, 1.5)
    if transition_ratio > 0.3:
        penalty += min(transition_ratio * 2, 1.0)
    if sentence_cv < 0.3:
        penalty += 1.0
    penalty = min(10.0, penalty)

    return {
        "tier1_hits": tier1_hits,
        "tier2_hits": tier2_hits,
        "fiction_ai_tells": fiction_tells,
        "structural_ai_tics": structural_tics,
        "telling_violations": telling_count,
        "four_char_density": round(four_char_density, 2),
        "em_dash_density": round(em_density, 2),
        "sentence_cv": round(sentence_cv, 2),
        "transition_opener_ratio": round(transition_ratio, 2),
        "dialog_tag_ratio": round(dialog_ratio, 2),
        "slop_penalty": round(penalty, 2),
    }


def _resolve_outline_path(chapter_num: int | None = None) -> tuple:
    """卷感知大纲路径解析。

    为评估函数提供正确的大纲文件路径：
    — chapter_num 有值 → 优先 outline_volume{N}.md → 回退 outline.md
    — chapter_num 为 None → 优先 outline.md → 回退合并所有 outline_volume*.md

    Returns:
        (path, label): path 为 None 表示无任何大纲文件或需手动合并；label 供日志使用。
    """
    if chapter_num is not None:
        cfg = config
        cfg.load()
        ch_per_vol = max(cfg.chapters_per_volume, 1)
        vol_num = (chapter_num - 1) // ch_per_vol + 1

        vol_path = OUTPUT_DIR / f"outline_volume{vol_num}.md"
        if vol_path.exists():
            return (vol_path, f"outline_volume{vol_num}.md（第 {vol_num} 卷章级大纲）")

        # 回退到合并版
        fallback = OUTPUT_DIR / "outline.md"
        if fallback.exists():
            return (fallback, "outline.md（回退：卷级大纲未找到）")

        return (None, "")

    # 全局评估：优先合并版
    merged = OUTPUT_DIR / "outline.md"
    if merged.exists():
        return (merged, "outline.md（合并版）")

    # 回退：手动合并所有卷级大纲
    vol_files = sorted(OUTPUT_DIR.glob("outline_volume*.md"))
    if vol_files:
        return (None, f"outline_volume*.md × {len(vol_files)}（回退：合并版未找到）")

    return (None, "")


def _load_outline(chapter_num: int | None = None) -> str:
    """加载大纲文本（卷感知）。

    Args:
        chapter_num: 章节编号。有值时优先加载对应卷的大纲；None 时加载全局大纲。

    Returns:
        大纲文本字符串。无任何大纲文件时返回空字符串。
    """
    path, _label = _resolve_outline_path(chapter_num)
    if path is not None:
        return path.read_text(encoding="utf-8")

    # 回退合并模式：拼接所有 outline_volume*.md
    vol_files = sorted(OUTPUT_DIR.glob("outline_volume*.md"))
    if vol_files:
        parts = []
        for vf in vol_files:
            parts.append(vf.read_text(encoding="utf-8"))
        return "\n\n".join(parts)

    return ""


# ============================================================================
# 评估入口
# ============================================================================

def evaluate_foundation(
    max_tokens: int = 4096,
    retries: int = 3,
    max_total_time: int = None,
) -> str:
    """评估基础构建文档。"""
    cfg = config
    cfg.load()
    story = cfg.story_summary

    world_path = OUTPUT_DIR / "world.md"
    chars_path = OUTPUT_DIR / "characters.md"
    canon_path = OUTPUT_DIR / "canon.md"
    mystery_path = OUTPUT_DIR / "MYSTERY.md"

    world = world_path.read_text(encoding="utf-8") if world_path.exists() else ""
    chars = chars_path.read_text(encoding="utf-8") if chars_path.exists() else ""
    outline = _load_outline()  # 卷感知：优先 outline.md（合并版），回退合并所有 outline_volume*.md
    canon = canon_path.read_text(encoding="utf-8") if canon_path.exists() else ""
    mystery = mystery_path.read_text(encoding="utf-8") if mystery_path.exists() else ""

    prompt = build_foundation_eval_prompt(
        story, world_text=world, characters_text=chars,
        outline_text=outline, canon_text=canon, mystery_text=mystery,
    )

    print("  [评估] 调用 LLM 裁判评估基础构建 ...", file=sys.stderr)
    result = call_judge(
        prompt, system=JUDGE_SYSTEM_PROMPT, max_tokens=max_tokens,
        retries=retries, max_total_time=max_total_time,
    )

    # 记录日志
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = EVAL_LOGS_DIR / f"foundation_{ts}.json"
    parsed = _parse_json_response(result)
    log_path.write_text(json.dumps({
        "timestamp": ts,
        "phase": "foundation",
        "raw_output": result,
        **parsed,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(result)
    return result


def evaluate_chapter(
    ch_num: int,
    max_tokens: int = 4096,
    retries: int = 3,
    max_total_time: int = None,
) -> str:
    """评估单个章节。

    上下文对齐原版 evaluate_chapter(): 传入 voice + world + characters +
    canon + chapter_outline + prev_chapter_tail + chapter_text，共 7 项。
    """
    ch_path = CHAPTERS_DIR / f"ch_{ch_num:02d}.md"
    if not ch_path.exists():
        print(f"  [评估] 章节 {ch_num} 不存在", file=sys.stderr)
        return "overall_score: 0.0\n"

    chapter_text = ch_path.read_text(encoding="utf-8")

    # 机械 slop 检测
    mech = slop_score_zh(chapter_text)
    print(f"  [机械检测] Tier1={len(mech['tier1_hits'])}, "
          f"Tier2={len(mech['tier2_hits'])}, "
          f"Fiction={len(mech['fiction_ai_tells'])}, "
          f"StructTic={len(mech['structural_ai_tics'])}, "
          f"Telling={mech['telling_violations']}, "
          f"Transition={mech['transition_opener_ratio']}, "
          f"slop_penalty={mech['slop_penalty']}", file=sys.stderr)

    # ★ 对齐原版：加载评估所需的全部上下文（7 项）
    outline = _load_outline(chapter_num=ch_num)  # 卷感知：优先 outline_volume{N}.md
    voice_path = OUTPUT_DIR / "voice.md"
    voice = voice_path.read_text(encoding="utf-8") if voice_path.exists() else ""
    canon_path = OUTPUT_DIR / "canon.md"
    canon = canon_path.read_text(encoding="utf-8") if canon_path.exists() else ""

    # ★ 新增：world.md（对齐原版）
    world_path = OUTPUT_DIR / "world.md"
    world_text = world_path.read_text(encoding="utf-8") if world_path.exists() else ""

    # ★ 新增：characters.md（对齐原版）
    chars_path = OUTPUT_DIR / "characters.md"
    characters_text = chars_path.read_text(encoding="utf-8") if chars_path.exists() else ""

    # ★ 新增：前章末尾 3000 字（对齐原版 prev_chapter_tail）
    prev_tail = ""
    if ch_num > 1:
        prev_path = CHAPTERS_DIR / f"ch_{ch_num - 1:02d}.md"
        if prev_path.exists():
            prev_full = prev_path.read_text(encoding="utf-8")
            prev_tail = prev_full[-3000:] if len(prev_full) > 3000 else prev_full
    else:
        prev_tail = "（第一章，无前章）"

    prompt = build_chapter_eval_prompt(
        ch_num, chapter_text,
        chapter_outline=outline, voice_text=voice, canon_text=canon,
        world_text=world_text,
        characters_text=characters_text,
        prev_chapter_tail=prev_tail,
    )

    print(f"  [评估] 调用 LLM 裁判评估第 {ch_num} 章 ...", file=sys.stderr)
    result = call_judge(
        prompt, system=JUDGE_SYSTEM_PROMPT, max_tokens=max_tokens,
        retries=retries, max_total_time=max_total_time,
    )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = EVAL_LOGS_DIR / f"chapter_{ch_num:02d}_{ts}.json"
    parsed = _parse_json_response(result)

    # ★ 对齐原版：机械 slop 扣分到 overall_score
    if "overall_score" in parsed and isinstance(parsed.get("overall_score"), (int, float)):
        raw_score = parsed["overall_score"]
        slop_penalty = mech.get("slop_penalty", 0)
        adjusted = max(0, raw_score - slop_penalty)
        parsed["raw_judge_score"] = raw_score
        parsed["overall_score"] = round(adjusted, 2)
        parsed["slop_penalty_applied"] = slop_penalty

    log_path.write_text(json.dumps({
        "timestamp": ts, "phase": "chapter", "chapter": ch_num,
        "mechanical": mech, "raw_output": result,
        **parsed,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(result)
    return result


def evaluate_full(
    max_tokens: int = 8192,
    retries: int = 3,
    max_total_time: int = None,
) -> str:
    """全文评估。"""
    chapter_files = sorted(CHAPTERS_DIR.glob("ch_*.md"))
    if not chapter_files:
        print("  [评估] 无章节文件", file=sys.stderr)
        return "novel_score: 0.0\n"

    manuscript = "\n\n---\n\n".join(
        f.read_text(encoding="utf-8") for f in chapter_files
    )

    outline = _load_outline()  # 卷感知：优先 outline.md（合并版），回退合并所有 outline_volume*.md
    voice_path = OUTPUT_DIR / "voice.md"
    voice = voice_path.read_text(encoding="utf-8") if voice_path.exists() else ""

    # ★ 对齐原版：全文评估需传入 world + characters
    world_path = OUTPUT_DIR / "world.md"
    world_text = world_path.read_text(encoding="utf-8") if world_path.exists() else ""

    chars_path = OUTPUT_DIR / "characters.md"
    characters_text = chars_path.read_text(encoding="utf-8") if chars_path.exists() else ""

    prompt = build_full_novel_eval_prompt(
        manuscript, outline_text=outline, voice_text=voice,
        world_text=world_text,
        characters_text=characters_text,
    )

    print("  [评估] 调用 LLM 裁判评估全文 ...", file=sys.stderr)
    result = call_judge(
        prompt, system=JUDGE_SYSTEM_PROMPT, max_tokens=max_tokens,
        retries=retries, max_total_time=max_total_time,
    )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = EVAL_LOGS_DIR / f"full_{ts}.json"
    parsed = _parse_json_response(result)
    log_path.write_text(json.dumps({
        "timestamp": ts, "phase": "full",
        "chapter_count": len(chapter_files),
        "raw_output": result,
        **parsed,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(result)
    return result


# ============================================================================
# Slop 惩罚分提取（供 pipeline 决策使用）
# ============================================================================

def get_last_slop_penalty(ch_num: int) -> float:
    """读取最近一次章节评估的 slop_penalty。

    从 EVAL_LOGS_DIR/chapter_{ch_num:02d}_*.json 中提取
    mechanical.slop_penalty，供 pipeline 决策使用。

    体裁无关 — slop_penalty 基于 ANTI-SLOP_ZH 通用套话检测，
    不依赖题材关键词。
    """
    logs = sorted(EVAL_LOGS_DIR.glob(f"chapter_{ch_num:02d}_*.json"))
    if not logs:
        return 0.0
    with open(logs[-1], "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("mechanical", {}).get("slop_penalty", 0.0)


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="中文小说评估器")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--phase", type=str, choices=["foundation"],
                       help="评估基础构建阶段")
    group.add_argument("--chapter", type=int, help="评估指定章节")
    group.add_argument("--full", action="store_true", help="全文评估")

    args = parser.parse_args()

    EVAL_LOGS_DIR.mkdir(parents=True, exist_ok=True)

    if args.phase == "foundation":
        evaluate_foundation()
    elif args.chapter:
        evaluate_chapter(args.chapter)
    elif args.full:
        evaluate_full()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()