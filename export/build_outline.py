#!/usr/bin/env python3
"""
export/build_outline.py — 从章节重建大纲

读取所有已完成章节，调用 LLM 重建实际大纲（反映真实内容，而非初始计划）。
"""

import sys
from pathlib import Path

from core.config import OUTPUT_DIR, CHAPTERS_DIR
from core.api_client import call_writer
from core.state_manager import step


REBUILD_OUTLINE_SYSTEM = """你是一位小说分析员。你阅读所有已完成章节，反向重建章节大纲。
你的大纲：每章概括关键事件、角色变化、伏笔进展。
你的汉语写作简洁直接。"""


def build_outline() -> None:
    """从章节重建大纲。"""
    chapter_files = sorted(CHAPTERS_DIR.glob("ch_*.md"))
    if not chapter_files:
        step("无章节文件，跳过")
        return

    # 拼接各章概要
    summaries = []
    for f in chapter_files:
        text = f.read_text(encoding="utf-8-sig")
        summaries.append(f"## {f.stem}\n{text[:800]}...（共{len(text)}字）")

    manuscript = "\n\n".join(summaries)

    prompt = f"""请阅读以下所有章节的概要，反向重建一份实际的章节大纲（反映真实完成的章节内容，而非初始计划）：

{manuscript[:20000]}

对每一章，写出：
### 第 N 章
— 关键事件
— 角色变化
— 伏笔进展/回收
— 情感弧线（起始→结束）

最后给出整体弧线摘要。"""

    step("重建大纲 ...")
    result = call_writer(prompt, system=REBUILD_OUTLINE_SYSTEM)

    outline_path = OUTPUT_DIR / "outline.md"
    outline_path.write_text(result, encoding="utf-8")
    step(f"大纲已重建: {outline_path}")


if __name__ == "__main__":
    build_outline()