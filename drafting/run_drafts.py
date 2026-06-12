#!/usr/bin/env python3
"""
drafting/run_drafts.py — 批量顺序起草

按大纲顺序逐章调用 draft_chapter.py。
"""

import sys
from pathlib import Path

from core.config import config, OUTPUT_DIR, CHAPTERS_DIR
from core.state_manager import step, banner, save_state, load_state, get_total_chapters
from drafting.draft_chapter import draft_chapter


def run_drafts(state: dict = None, max_tokens: int = 16000) -> None:
    """批量起草所有未完成的章节。"""
    if state is None:
        state = load_state()

    total = get_total_chapters(state)
    start = state.get("chapters_drafted", 0) + 1

    banner(f"批量起草: 第 {start}-{total} 章 ({total - start + 1} 章待写)", "-")

    cfg = config
    cfg.load()
    max_attempts = cfg.max_chapter_attempts if cfg.loaded else 5
    threshold = cfg.chapter_threshold if cfg.loaded else 6.0

    CHAPTERS_DIR.mkdir(parents=True, exist_ok=True)

    for ch in range(start, total + 1):
        step(f"--- 第 {ch}/{total} 章 ---")
        drafted = False

        for attempt in range(1, max_attempts + 1):
            step(f"尝试 {attempt}/{max_attempts}")
            try:
                draft_chapter(ch, max_tokens=max_tokens)
            except Exception as e:
                step(f"起草失败: {e}")
                continue

            ch_file = CHAPTERS_DIR / f"ch_{ch:02d}.md"
            if not ch_file.exists() or ch_file.stat().st_size < 100:
                step("章节文件缺失或过短")
                continue

            drafted = True
            state["chapters_drafted"] = ch
            save_state(state)
            break

        if not drafted:
            step(f"警告: 第 {ch} 章全部尝试失败，继续下一章")

    state["chapters_drafted"] = total
    state["phase"] = "revision"
    save_state(state)
    banner(f"草拟完成 — {total} 章")


if __name__ == "__main__":
    run_drafts()