#!/usr/bin/env python3
"""
export/build_manuscript.py — 构建完整手稿

将所有章节拼接为一份 manuscript.md，含目录和章节分隔。
"""

import sys
from pathlib import Path

from core.config import OUTPUT_DIR, CHAPTERS_DIR
from core.state_manager import step


def build_manuscript() -> None:
    """拼接所有章节为完整手稿。"""
    chapter_files = sorted(CHAPTERS_DIR.glob("ch_*.md"))
    if not chapter_files:
        step("无章节文件，跳过")
        return

    parts = []
    toc_lines = ["# 目录\n"]

    for i, f in enumerate(chapter_files, 1):
        text = f.read_text(encoding="utf-8").strip()
        if not text:
            continue

        # 提取章节标题（第一行）
        first_line = text.split("\n")[0].strip("# ").strip()
        toc_lines.append(f"{i}. {first_line}")

        # ★ 去重：若正文首行已经是章节标题，不再重复添加 "# 第 i 章"
        if text.startswith("#"):
            parts.append(text)
        else:
            parts.append(f"# 第 {i} 章\n\n{text}")

    toc = "\n".join(toc_lines) + "\n\n---\n\n"
    full_manuscript = toc + "\n\n---\n\n".join(parts) + "\n"

    manuscript_path = OUTPUT_DIR / "manuscript.md"
    manuscript_path.write_text(full_manuscript, encoding="utf-8")

    total_chars = sum(len(p.replace(" ", "").replace("\n", "")) for p in parts)
    step(f"完整手稿: {len(parts)} 章, 约 {total_chars} 字")
    step(f"手稿位置: {manuscript_path}")


if __name__ == "__main__":
    build_manuscript()