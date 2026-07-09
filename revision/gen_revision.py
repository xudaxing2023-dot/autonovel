#!/usr/bin/env python3
"""
revision/gen_revision.py — 章节修订重写

根据修订摘要 (brief) 重写指定章节。
用法: python gen_revision.py <章节号> <摘要文件路径>
"""

import re
import sys
from pathlib import Path

from core.config import OUTPUT_DIR, CHAPTERS_DIR
from core.api_client import call_writer
from core.state_manager import step
from prompts.revision_prompts import build_revision_prompt, REVISION_SYSTEM_PROMPT


def revise_chapter(
    ch_num: int,
    brief_file: str,
    retries: int = 3,
    max_total_time: int = None) -> None:
    """根据修订摘要重写章节。"""
    brief_path = Path(brief_file) if isinstance(brief_file, str) else brief_file
    brief_text = brief_path.read_text(encoding="utf-8-sig") if brief_path.exists() else ""

    voice_path = OUTPUT_DIR / "voice.md"
    world_path = OUTPUT_DIR / "world.md"
    chars_path = OUTPUT_DIR / "characters.md"

    voice = voice_path.read_text(encoding="utf-8-sig") if voice_path.exists() else ""
    world = world_path.read_text(encoding="utf-8-sig") if world_path.exists() else ""
    chars = chars_path.read_text(encoding="utf-8-sig") if chars_path.exists() else ""

    old_path = CHAPTERS_DIR / f"ch_{ch_num:02d}.md"
    old_text = old_path.read_text(encoding="utf-8-sig") if old_path.exists() else ""

    prev_path = CHAPTERS_DIR / f"ch_{ch_num - 1:02d}.md"
    next_path = CHAPTERS_DIR / f"ch_{ch_num + 1:02d}.md"
    prev_tail = prev_path.read_text(encoding="utf-8-sig")[-2000:] if prev_path.exists() else "(第一章)"
    next_head = next_path.read_text(encoding="utf-8-sig")[:1500] if next_path.exists() else "(最后一章)"

    # ★ 提取本章大纲条目，防止多次修订后偏离大纲结构
    outline_text = ""
    outline_path = OUTPUT_DIR / "outline.md"
    if outline_path.exists():
        outline_raw = outline_path.read_text(encoding="utf-8-sig")
        # 匹配 "### 第N章" 到下一个 "### " 或全文结束
        pattern = rf"###\s*第\s*{ch_num}\s*章\s*\n(.*?)(?=\n###\s|\n---|\n##\s*整体|$)"
        m = re.search(pattern, outline_raw, re.DOTALL)
        if m:
            outline_text = m.group(0).strip()

    prompt = build_revision_prompt(
        ch_num, brief_text, voice_text=voice,
        world_text=world, characters_text=chars,
        old_chapter_text=old_text,
        prev_chapter_tail=prev_tail,
        next_chapter_head=next_head,
        outline_text=outline_text)

    step(f"按摘要重写第 {ch_num} 章 ...")
    result = call_writer(
        prompt, system=REVISION_SYSTEM_PROMPT,
        retries=retries, max_total_time=max_total_time)

    old_path = CHAPTERS_DIR / f"ch_{ch_num:02d}.md"
    old_path.write_text(result, encoding="utf-8")
    step(f"针对性修订 第 {ch_num} 章 完成 ✓")


if __name__ == "__main__":
    ch = int(sys.argv[1])
    brief = sys.argv[2]
    revise_chapter(ch, brief)