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

# Tier 3: 结构层面检测
# — 连续 3+ 四字成语/形容词
FOUR_CHAR_PATTERN = re.compile(r'[\u4e00-\u9fff]{4}')
# — 破折号密度
EM_DASH_PATTERN = re.compile(r'——')
# — 对话标签重复 「说」「道」
DIALOG_TAG_PATTERN = re.compile(r'(?:说|道)[,，。！？\s]')


def slop_score_zh(text: str) -> dict:
    """
    中文机械 slop 检测。
    返回:
      - tier1_hits: list
      - tier2_hits: list
      - four_char_density: 连续 4 字词密度
      - em_dash_density: 破折号密度 (/千字)
      - slop_penalty: 0-10 惩罚分
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

    # 计算惩罚分
    penalty = 0.0
    penalty += sum(c for _, c in tier1_hits) * 0.5  # Tier 1: 每个 0.5 分
    penalty += sum(c for _, c in tier2_hits) * 0.2  # Tier 2: 每个 0.2 分
    if em_density > 3:
        penalty += (em_density - 3) * 0.5
    if dialog_ratio > 0.6:
        penalty += (dialog_ratio - 0.6) * 5
    penalty = min(10.0, penalty)

    return {
        "tier1_hits": tier1_hits,
        "tier2_hits": tier2_hits,
        "four_char_density": round(four_char_density, 2),
        "em_dash_density": round(em_density, 2),
        "sentence_cv": round(sentence_cv, 2),
        "dialog_tag_ratio": round(dialog_ratio, 2),
        "slop_penalty": round(penalty, 2),
    }


# ============================================================================
# 评估入口
# ============================================================================

def evaluate_foundation(max_tokens: int = 4096) -> str:
    """评估基础构建文档。"""
    cfg = config
    cfg.load()
    story = cfg.story_summary

    world_path = OUTPUT_DIR / "world.md"
    chars_path = OUTPUT_DIR / "characters.md"
    outline_path = OUTPUT_DIR / "outline.md"
    canon_path = OUTPUT_DIR / "canon.md"
    mystery_path = OUTPUT_DIR / "MYSTERY.md"

    world = world_path.read_text(encoding="utf-8") if world_path.exists() else ""
    chars = chars_path.read_text(encoding="utf-8") if chars_path.exists() else ""
    outline = outline_path.read_text(encoding="utf-8") if outline_path.exists() else ""
    canon = canon_path.read_text(encoding="utf-8") if canon_path.exists() else ""
    mystery = mystery_path.read_text(encoding="utf-8") if mystery_path.exists() else ""

    prompt = build_foundation_eval_prompt(
        story, world_text=world, characters_text=chars,
        outline_text=outline, canon_text=canon, mystery_text=mystery,
    )

    print("  [评估] 调用 LLM 裁判评估基础构建 ...", file=sys.stderr)
    result = call_judge(prompt, system=JUDGE_SYSTEM_PROMPT, max_tokens=max_tokens)

    # 记录日志
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = EVAL_LOGS_DIR / f"foundation_{ts}.json"
    log_path.write_text(json.dumps({
        "timestamp": ts,
        "phase": "foundation",
        "raw_output": result,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(result)
    return result


def evaluate_chapter(ch_num: int, max_tokens: int = 4096) -> str:
    """评估单个章节。"""
    ch_path = CHAPTERS_DIR / f"ch_{ch_num:02d}.md"
    if not ch_path.exists():
        print(f"  [评估] 章节 {ch_num} 不存在", file=sys.stderr)
        return "overall_score: 0.0\n"

    chapter_text = ch_path.read_text(encoding="utf-8")

    # 机械 slop 检测
    mech = slop_score_zh(chapter_text)
    print(f"  [机械检测] Tier1={len(mech['tier1_hits'])}, "
          f"Tier2={len(mech['tier2_hits'])}, "
          f"破折号密度={mech['em_dash_density']}, "
          f"slop_penalty={mech['slop_penalty']}", file=sys.stderr)

    # LLM 裁判
    outline_path = OUTPUT_DIR / "outline.md"
    outline = outline_path.read_text(encoding="utf-8") if outline_path.exists() else ""
    voice_path = OUTPUT_DIR / "voice.md"
    voice = voice_path.read_text(encoding="utf-8") if voice_path.exists() else ""
    canon_path = OUTPUT_DIR / "canon.md"
    canon = canon_path.read_text(encoding="utf-8") if canon_path.exists() else ""

    prompt = build_chapter_eval_prompt(
        ch_num, chapter_text,
        chapter_outline=outline, voice_text=voice, canon_text=canon,
    )

    print(f"  [评估] 调用 LLM 裁判评估第 {ch_num} 章 ...", file=sys.stderr)
    result = call_judge(prompt, system=JUDGE_SYSTEM_PROMPT, max_tokens=max_tokens)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = EVAL_LOGS_DIR / f"chapter_{ch_num:02d}_{ts}.json"
    log_path.write_text(json.dumps({
        "timestamp": ts, "phase": "chapter", "chapter": ch_num,
        "mechanical": mech, "raw_output": result,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(result)
    return result


def evaluate_full(max_tokens: int = 8192) -> str:
    """全文评估。"""
    chapter_files = sorted(CHAPTERS_DIR.glob("ch_*.md"))
    if not chapter_files:
        print("  [评估] 无章节文件", file=sys.stderr)
        return "novel_score: 0.0\n"

    manuscript = "\n\n---\n\n".join(
        f.read_text(encoding="utf-8") for f in chapter_files
    )

    outline_path = OUTPUT_DIR / "outline.md"
    outline = outline_path.read_text(encoding="utf-8") if outline_path.exists() else ""
    voice_path = OUTPUT_DIR / "voice.md"
    voice = voice_path.read_text(encoding="utf-8") if voice_path.exists() else ""

    prompt = build_full_novel_eval_prompt(
        manuscript, outline_text=outline, voice_text=voice,
    )

    print("  [评估] 调用 LLM 裁判评估全文 ...", file=sys.stderr)
    result = call_judge(prompt, system=JUDGE_SYSTEM_PROMPT, max_tokens=max_tokens)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = EVAL_LOGS_DIR / f"full_{ts}.json"
    log_path.write_text(json.dumps({
        "timestamp": ts, "phase": "full",
        "chapter_count": len(chapter_files),
        "raw_output": result,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(result)
    return result


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