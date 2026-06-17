#!/usr/bin/env python3
"""
foundation/gen_characters.py — 角色注册表生成器

从故事梗概 + world.md 调用 LLM 生成完整的 characters.md。
"""

import sys
from pathlib import Path

from core.config import config, OUTPUT_DIR
from core.api_client import call_writer
from core.state_manager import step
from prompts.character_prompts import build_character_prompt


CHARACTER_SYSTEM_PROMPT = """你是一位精通角色设计的创作者，深谙：
— 创伤/欲望/需求/谎言 因果链
— Sanderson 三滑块画像
— 对话独特性（8 维度）
你创造的角色有矛盾、有秘密、有可听见的说话方式。
你的汉语写作简洁直接，不使用 AI 套话词汇。"""


def generate_characters(max_tokens: int = 16000) -> None:
    """生成 characters.md 并写入 output/ 目录。"""
    cfg = config
    cfg.load()

    story = cfg.story_summary
    world_path = OUTPUT_DIR / "world.md"
    world = world_path.read_text(encoding="utf-8") if world_path.exists() else ""
    voice_path = OUTPUT_DIR / "voice.md"
    voice = voice_path.read_text(encoding="utf-8") if voice_path.exists() else ""

    prompt = build_character_prompt(story, world_text=world, voice_part2=voice)

    step("调用 LLM 生成角色注册表 ...")
    result = call_writer(prompt, system=CHARACTER_SYSTEM_PROMPT, max_tokens=max_tokens, max_total_time=300)

    char_path = OUTPUT_DIR / "characters.md"
    char_path.write_text(result, encoding="utf-8")
    step(f"角色注册表已保存: {char_path}")


if __name__ == "__main__":
    generate_characters()