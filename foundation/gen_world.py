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
from prompts.world_prompts import build_world_prompt, WORLD_SYSTEM_PROMPT


def generate_world(max_tokens: int = 16000) -> None:
    """生成 world.md 并写入 output/ 目录。"""
    cfg = config
    cfg.load()

    # 读取模板
    template_path = TEMPLATES_DIR / "world.md"
    template = template_path.read_text(encoding="utf-8") if template_path.exists() else ""

    # 读取 seed / voice
    story = cfg.story_summary
    voice_path = OUTPUT_DIR / "voice.md"
    voice = voice_path.read_text(encoding="utf-8") if voice_path.exists() else ""

    # 构建 prompt
    prompt = build_world_prompt(story, voice_part2=(voice if voice else ""))

    step("调用 LLM 生成世界观 ...")
    result = call_writer(prompt, system=WORLD_SYSTEM_PROMPT, max_tokens=max_tokens, max_total_time=300)

    # 保存到 output/world.md
    world_path = OUTPUT_DIR / "world.md"
    world_path.write_text(result, encoding="utf-8")
    step(f"世界观已保存: {world_path}")


if __name__ == "__main__":
    generate_world()