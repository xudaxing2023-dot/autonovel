#!/usr/bin/env python3
"""
foundation/gen_outline.py — 大纲生成器 (Part 1)

从故事梗概 + world.md + characters.md 调用 LLM 生成 outline.md（节拍 + 章节结构）。
"""

import sys
from pathlib import Path

from core.config import config, OUTPUT_DIR
from core.api_client import call_writer
from core.state_manager import step
from prompts.outline_prompts import build_outline_prompt


OUTLINE_SYSTEM_PROMPT = """你是一位小说结构架构师，深谙：
— Save the Cat 节拍表
— Dan Harmon 故事圈（分形应用）
— Sanderson 的许诺-进展-回报原则
— MICE 商数（Milieu/Inquiry/Character/Event 嵌套关闭）
— try-fail 循环设计
你构建的大纲让作者可以直接起草，无需现场发明结构。
每一章都有节拍、情感弧线、try-fail 类型。
你的汉语写作简洁直接，不使用 AI 套话。"""


def generate_outline(max_tokens: int = 16000) -> None:
    """生成 outline.md Part 1 并写入 output/ 目录。"""
    cfg = config
    cfg.load()

    story = cfg.story_summary
    world_path = OUTPUT_DIR / "world.md"
    world = world_path.read_text(encoding="utf-8") if world_path.exists() else ""
    chars_path = OUTPUT_DIR / "characters.md"
    chars = chars_path.read_text(encoding="utf-8") if chars_path.exists() else ""
    mystery_path = OUTPUT_DIR / "MYSTERY.md"
    mystery = mystery_path.read_text(encoding="utf-8") if mystery_path.exists() else ""
    voice_path = OUTPUT_DIR / "voice.md"
    voice = voice_path.read_text(encoding="utf-8") if voice_path.exists() else ""

    prompt = build_outline_prompt(
        story, world_text=world, characters_text=chars,
        mystery_text=mystery, voice_part2=voice,
    )

    step("调用 LLM 生成大纲 ...")
    result = call_writer(prompt, system=OUTLINE_SYSTEM_PROMPT, max_tokens=max_tokens, max_total_time=300)

    outline_path = OUTPUT_DIR / "outline.md"
    outline_path.write_text(result, encoding="utf-8")
    step(f"大纲已保存: {outline_path}")


if __name__ == "__main__":
    generate_outline()