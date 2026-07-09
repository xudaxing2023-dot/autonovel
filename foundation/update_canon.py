#!/usr/bin/env python3
"""
foundation/update_canon.py — 增量正典更新器

每章起草完成后，从章节文本中提取首次出现的新增硬事实，追加到 canon.md。
输出 ≤ 8000 token，适配 16000 限制。
"""

import re
from pathlib import Path

from core.config import config, OUTPUT_DIR
from core.api_client import call_p2_ctx_writer
from core.state_manager import step


UPDATE_CANON_SYSTEM_PROMPT = """你是正典管理员。从新完成的章节中提取首次出现的新增硬事实。
已有正典中已记录的事实不要重复。
你的输出直接追加到 canon.md 对应节。
你的汉语写作简洁直接。"""


def update_canon_from_chapter(
    chapter_num: int,
    chapter_text: str) -> int:
    """从章节提取新事实 → 追加 canon.md。返回新增事实条数。

    Args:
        chapter_num: 章节编号（1-indexed）。
        chapter_text: 章节全文。

    Returns:
        新增的硬事实条目数；0 表示无新增。
    """
    canon_path = OUTPUT_DIR / "canon.md"
    existing_canon = canon_path.read_text(encoding="utf-8-sig") if canon_path.exists() else ""

    prompt = f"""【已有正典】
{existing_canon}

【新完成的第 {chapter_num} 章全文】
{chapter_text}

请提取本章中【首次出现】的新增硬事实，按格式输出：

## 新增：世界观硬事实（第 {chapter_num} 章）
— ...

## 新增：角色硬事实（第 {chapter_num} 章）
— ...

## 新增：时间线硬事实（第 {chapter_num} 章）
— ...

## 新增：规则硬事实（第 {chapter_num} 章）
— ...

如无新增事实，输出「无新增事实」。
"""

    step(f"正典更新: 检查第 {chapter_num} 章新事实 ...")
    result = call_p2_ctx_writer(
        prompt,
        system=UPDATE_CANON_SYSTEM_PROMPT,
        temperature=0.5)

    if "无新增事实" in result:
        step(f"正典更新: 第 {chapter_num} 章无新增事实")
        return 0

    # 追加到 canon.md
    canon_path.write_text(
        existing_canon.rstrip() + "\n\n" + result,
        encoding="utf-8")

    # 统计新增条目数
    new_entries = len(re.findall(r"^— ", result, re.MULTILINE))
    step(f"正典更新: +{new_entries} 条新事实（第 {chapter_num} 章）")
    return new_entries