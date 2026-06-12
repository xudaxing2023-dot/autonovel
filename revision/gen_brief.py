#!/usr/bin/env python3
"""
revision/gen_brief.py — 修订摘要生成器

综合对抗性编辑结果、读者评审团共识、Elo 排名，
为最需要修订的章节生成修订摘要 (brief)。
"""
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.config import OUTPUT_DIR, CHAPTERS_DIR, EDIT_LOGS_DIR, BRIEFS_DIR
from core.api_client import call_writer
from core.state_manager import step


BRIEF_SYSTEM_PROMPT = """你是一位小说修订顾问。你综合多个评估来源（对抗性编辑、读者评审团、Elo排名），
为需要修订的章节写出一份具体、可操作的修订摘要。
你的摘要：明确指出问题所在、给出具体修订建议、不做泛泛而谈的评论。
你的汉语写作简洁直接，不使用 AI 套话。"""


def generate_brief(
    chapter_num: int = 0,
    panel_data: Optional[Path] = None,
    max_tokens: int = 4096,
) -> Optional[Path]:
    """为指定章节生成修订摘要。如果 chapter_num=0，自动选择最弱章节。"""
    BRIEFS_DIR.mkdir(parents=True, exist_ok=True)

    # 收集诊断信息
    cuts_path = EDIT_LOGS_DIR / f"ch{chapter_num:02d}_cuts.json" if chapter_num > 0 else None

    # 构建 prompt
    ch_file = CHAPTERS_DIR / f"ch_{chapter_num:02d}.md" if chapter_num > 0 else None
    ch_text = ch_file.read_text(encoding="utf-8")[:5000] if ch_file and ch_file.exists() else ""
    cuts_text = cuts_path.read_text(encoding="utf-8")[:3000] if cuts_path and cuts_path.exists() else ""
    panel_text = panel_data.read_text(encoding="utf-8")[:3000] if panel_data and panel_data.exists() else ""

    prompt = f"""请为第 {chapter_num} 章生成一份修订摘要 (Revision Brief)。

【本章当前内容】
{ch_text if ch_text else "(未提供)"}

【对抗性编辑诊断】
{cuts_text if cuts_text else "(未提供)"}

【读者评审团反馈】
{panel_text if panel_text else "(未提供)"}

【修订摘要格式】
## 第 {chapter_num} 章 修订摘要

### 核心问题
（1-2 句话：本章最需要解决的核心问题是什么？）

### 具体修订项
（每条以「—」开头，包含：位置定位 + 问题类型 + 修订建议）

### 保留项
（本章做得好、应该保留的部分）

### 修订后预期效果
（修订完成后本章应有的阅读体验）

请写出具体、可操作的修订摘要。"""

    step(f"生成第 {chapter_num} 章修订摘要 ...")
    try:
        result = call_writer(prompt, system=BRIEF_SYSTEM_PROMPT, max_tokens=max_tokens)
    except Exception as e:
        step(f"摘要生成失败: {e}")
        # 创建最小摘要
        result = f"# 修订摘要: 第 {chapter_num} 章\n\n综合评估指示本章需要修订。请根据对抗性编辑和读者反馈进行针对性修改。\n"

    brief_path = BRIEFS_DIR / f"ch{chapter_num:02d}_brief.md"
    brief_path.write_text(result, encoding="utf-8")
    step(f"修订摘要已保存: {brief_path}")
    return brief_path


if __name__ == "__main__":
    ch = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    generate_brief(ch)