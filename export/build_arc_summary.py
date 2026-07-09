#!/usr/bin/env python3
"""
export/build_arc_summary.py — 构建弧线摘要

调用 LLM 分析所有章节，产出角色弧线、情节弧线、主题弧线的全局摘要。
"""

import sys
from pathlib import Path

from core.config import OUTPUT_DIR, CHAPTERS_DIR
from core.api_client import call_writer
from core.state_manager import step


ARC_SYSTEM_PROMPT = """你是一位小说分析员。你阅读全部章节后，写出全局弧线摘要：
— 主角角色弧线（从第一章到最后一章的变化路径）
— 情节弧线（核心冲突的起承转合）
— 主题弧线（核心问题的探索轨迹）
你的汉语写作简洁、有洞察力。"""


def build_arc_summary() -> None:
    """构建弧线摘要。"""
    chapter_files = sorted(CHAPTERS_DIR.glob("ch_*.md"))
    if not chapter_files:
        step("无章节文件，跳过")
        return

    # 取每章开头和结尾各 500 字
    snippets = []
    for f in chapter_files:
        text = f.read_text(encoding="utf-8-sig")
        head = text[:500]
        tail = text[-500:]
        snippets.append(f"## {f.stem} (开头)\n{head}\n...\n## {f.stem} (结尾)\n{tail}")

    prompt = f"""请阅读以下所有章节的开头和结尾片段，分析全局弧线：

{chr(10).join(snippets)[:25000]}

请输出：

## 一、主角角色弧线
（从最初状态到最终状态的演变路径。关键转折点分别在哪些章节？）

## 二、情节弧线
（核心冲突如何演变？激励事件 → 中点逆转 → 一切尽失 → 高潮 → 解决）

## 三、主题弧线
（小说探讨的核心问题是如何逐步展开的？读者的理解是如何演变的？）

## 四、伏笔回顾
（最重要的 5 条伏笔线索及它们的回收情况）"""

    step("构建弧线摘要 ...")
    result = call_writer(prompt, system=ARC_SYSTEM_PROMPT)

    arc_path = OUTPUT_DIR / "arc_summary.md"
    arc_path.write_text(result, encoding="utf-8")
    step(f"弧线摘要已保存: {arc_path}")


if __name__ == "__main__":
    build_arc_summary()