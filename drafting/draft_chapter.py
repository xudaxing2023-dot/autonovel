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
from core.api_client import call_p2_writer
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


def extract_chapter_outline(chapter_num: int) -> str:
    """从对应卷的大纲文件提取指定章节条目。

    优先从 output/outline_volume{N}.md 提取，不存在则回退到 output/outline.md。
    """
    cfg = config
    cfg.load()
    ch_per_vol = cfg.chapters_per_volume or 10
    vol_num = (chapter_num - 1) // ch_per_vol + 1

    vol_outline_path = OUTPUT_DIR / f"outline_volume{vol_num}.md"
    if not vol_outline_path.exists():
        vol_outline_path = OUTPUT_DIR / "outline.md"

    outline_text = load_file(vol_outline_path)

    # 匹配 "### 第 N 章" 或 "### Ch N"
    patterns = [
        rf'###\s*(?:第\s*)?{chapter_num}\s*章.*?(?=###\s*(?:第\s*)?{chapter_num + 1}\s*章|## 伏笔|## 二、|## 三、|$)',
        rf'###\s*Ch\s*{chapter_num}[:：].*?(?=###\s*Ch\s*{chapter_num + 1}[:：]|## Foreshadowing|$)',
    ]
    for pattern in patterns:
        match = re.search(pattern, outline_text, re.DOTALL)
        if match:
            return match.group(0).strip()
    return f"(第 {chapter_num} 章大纲未找到)"


def extract_next_chapter_preview(chapter_num: int) -> str:
    """提取下一章大纲的前几行作为预告。

    优先从卷级大纲文件提取，不存在则回退到 outline.md。
    """
    next_entry = extract_chapter_outline(chapter_num + 1)
    if "未找到" in next_entry:
        return "(最终章)"
    lines = next_entry.split('\n')[:8]
    return '\n'.join(lines)


RECENT_CHAPTERS = 2  # ★ 从 8 降为 2，减少上下文稀释，保留最近连续性


def _load_recent_chapters(chapter_num: int) -> str:
    """加载前 RECENT_CHAPTERS 章全文，作为滚动上下文。

    对于第 N 章，加载尽可能多的前文章节（最多 RECENT_CHAPTERS 章），
    按时间顺序排列（最早的在前），用分隔符连接。

    Returns:
        前文上下文字符串；第一章返回无前文提示。
    """
    recent_chapters = []
    for offset in range(1, RECENT_CHAPTERS + 1):
        prev_ch = chapter_num - offset
        if prev_ch < 1:
            break
        prev_path = CHAPTERS_DIR / f"ch_{prev_ch:02d}.md"
        if prev_path.exists():
            text = prev_path.read_text(encoding="utf-8")
            recent_chapters.append(
                f"【第 {prev_ch} 章全文】\n{text}"
            )

    if not recent_chapters:
        return "(第一章——无前文)"

    # 反转使顺序为 chrono（最早→最近）
    recent_chapters.reverse()
    return "\n\n---\n\n".join(recent_chapters)


def draft_chapter(
    chapter_num: int,
    max_tokens: int = 16000,
    retries: int = 3,
    max_total_time: int = None,
) -> None:
    """起草指定章节。"""
    cfg = config
    cfg.load()

    # 加载所有上下文（全量，不截断——由 P2 大上下文模型处理）
    voice = load_file(OUTPUT_DIR / "voice.md")
    world = load_file(OUTPUT_DIR / "world.md")
    characters = load_file(OUTPUT_DIR / "characters.md")
    canon = load_file(OUTPUT_DIR / "canon.md")

    chapter_outline = extract_chapter_outline(chapter_num)
    next_chapter = extract_next_chapter_preview(chapter_num)

    # ★ 滚动窗口：前 8 章全文
    prev_context = _load_recent_chapters(chapter_num)

    novel_title = cfg.novel_title or ""

    prompt = build_chapter_prompt(
        chapter_num,
        voice_text=voice,
        world_text=world,
        characters_text=characters,
        chapter_outline=chapter_outline,
        next_chapter_preview=next_chapter,
        prev_context=prev_context,
        canon_text=canon,
        novel_title=novel_title,
    )

    step(f"起草第 {chapter_num} 章 ...")
    result = call_p2_writer(
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