#!/usr/bin/env python3
"""
drafting/draft_chapter.py — 章节草拟

从 voice.md / world.md / characters.md / outline.md / canon.md 加载上下文,调用 LLM 起草单章。
用法: python draft_chapter.py <章节号>
"""

import re
import sys
from pathlib import Path

from core.config import config, OUTPUT_DIR, CHAPTERS_DIR, TEMPLATES_DIR
from core.api_client import call_writer
from core.state_manager import step
from prompts.chapter_prompts import build_chapter_prompt


DRAFT_SYSTEM_PROMPT = """你是一位文学小说作者，正在撰写一部长篇小说的章节。
你使用第三人称有限视角，锁定一位 POV 角色。
你的写作：展示感官细节、对话自然、信任读者、句子有节奏变化。
你完整写出整个章节——不截断、不概括、不跳前。
你避免一切中文 AI 套话：不写「宛如一幅画卷」「眼中闪过一丝」「嘴角微微上扬」「深深地吸了一口气」。
你的汉语简洁、具体、有力量。"""


def load_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def extract_chapter_outline(outline_text: str, chapter_num: int) -> str:
    """从大纲中提取指定章节条目。"""
    # 匹配 "### 第 N 章" 或 "### Ch N"
    patterns = [
        rf'###\s*(?:第\s*)?{chapter_num}\s*章.*?(?=###\s*(?:第\s*)?{chapter_num + 1}\s*章|## 伏笔|## 三、|$)',
        rf'###\s*Ch\s*{chapter_num}[:：].*?(?=###\s*Ch\s*{chapter_num + 1}[:：]|## Foreshadowing|$)',
    ]
    for pattern in patterns:
        match = re.search(pattern, outline_text, re.DOTALL)
        if match:
            return match.group(0).strip()
    return f"(第 {chapter_num} 章大纲未找到)"


def extract_next_chapter_preview(outline_text: str, chapter_num: int) -> str:
    """提取下一章大纲的前几行作为预告。"""
    next_entry = extract_chapter_outline(outline_text, chapter_num + 1)
    if "未找到" in next_entry:
        return "(最终章)"
    lines = next_entry.split('\n')[:8]
    return '\n'.join(lines)


def draft_chapter(
    chapter_num: int,
    max_tokens: int = 16000,
    retries: int = 3,
    max_total_time: int = None,
) -> None:
    """起草指定章节。"""
    cfg = config
    cfg.load()

    # 加载所有上下文
    voice = load_file(OUTPUT_DIR / "voice.md")
    world = load_file(OUTPUT_DIR / "world.md")
    characters = load_file(OUTPUT_DIR / "characters.md")
    outline = load_file(OUTPUT_DIR / "outline.md")
    canon = load_file(OUTPUT_DIR / "canon.md")

    chapter_outline = extract_chapter_outline(outline, chapter_num)
    next_chapter = extract_next_chapter_preview(outline, chapter_num)

    prev_path = CHAPTERS_DIR / f"ch_{chapter_num - 1:02d}.md"
    if prev_path.exists():
        prev_text = prev_path.read_text(encoding="utf-8")
        prev_tail = prev_text[-2000:] if len(prev_text) > 2000 else prev_text
    else:
        prev_tail = "(第一章——无前文)"

    novel_title = cfg.novel_title or ""

    prompt = build_chapter_prompt(
        chapter_num,
        voice_text=voice,
        world_text=world,
        characters_text=characters,
        chapter_outline=chapter_outline,
        next_chapter_preview=next_chapter,
        prev_chapter_tail=prev_tail,
        canon_text=canon,
        novel_title=novel_title,
    )

    step(f"起草第 {chapter_num} 章 ...")
    result = call_writer(
        prompt, system=DRAFT_SYSTEM_PROMPT, max_tokens=max_tokens,
        retries=retries, max_total_time=max_total_time,
    )

    CHAPTERS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = CHAPTERS_DIR / f"ch_{chapter_num:02d}.md"
    out_path.write_text(result, encoding="utf-8")
    step(f"第 {chapter_num} 章已保存: {out_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python draft_chapter.py <章节号>", file=sys.stderr)
        sys.exit(1)
    draft_chapter(int(sys.argv[1]))