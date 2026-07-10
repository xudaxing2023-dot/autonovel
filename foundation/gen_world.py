#!/usr/bin/env python3
"""
foundation/gen_world.py — 世界观生成器

从故事梗概 + voice.md 调用 LLM 生成完整的 world.md。
"""

import sys
from pathlib import Path

from core.config import config, OUTPUT_DIR, TEMPLATES_DIR
from core.api_client import call_writer
from core.state_manager import step, backup_snapshot
from prompts.world_prompts import (
    build_world_prompt,
    build_world_improve_prompt,
    WORLD_SYSTEM_PROMPT)


def generate_world(previous_output: str = "", eval_feedback: str = "") -> None:
    """生成 world.md 并写入 output/ 目录。

    Args:
        previous_output: 上一轮迭代的 world.md 内容（增量改进模式）。
        eval_feedback: 评估裁判对该步骤的改进建议（增量改进模式）。
                       两个参数均为空字符串时，使用 from_scratch 模式（迭代 1 行为不变）。
    """
    cfg = config
    cfg.load()

    # 读取模板
    template_path = TEMPLATES_DIR / "world.md"
    template = template_path.read_text(encoding="utf-8-sig") if template_path.exists() else ""

    # 读取 seed / voice
    story = cfg.story_summary
    voice_path = OUTPUT_DIR / "voice.md"
    voice = voice_path.read_text(encoding="utf-8-sig") if voice_path.exists() else ""

    # ── 增量改进模式 vs from_scratch 模式 ──
    if previous_output and eval_feedback:
        # 迭代 2+：基于上一轮输出 + 评估反馈做针对性改进
        step("使用增量改进模式生成世界观（基于上一轮输出 + 评估反馈）...")
        prompt = build_world_improve_prompt(
            previous_output=previous_output,
            eval_feedback=eval_feedback,
            story=story,
            voice_part2=(voice if voice else ""))
    else:
        # 迭代 1：从头生成（现有逻辑不变）
        prompt = build_world_prompt(story, voice_part2=(voice if voice else ""))

    step("调用 LLM 生成世界观 ...")
    result = call_writer(prompt, system=WORLD_SYSTEM_PROMPT)

    # 保存到 output/world.md
    world_path = OUTPUT_DIR / "world.md"
    world_path.write_text(result, encoding="utf-8")
    step(f"世界观已保存: {world_path}")


if __name__ == "__main__":
    generate_world()