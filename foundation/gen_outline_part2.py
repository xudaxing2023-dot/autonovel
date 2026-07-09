#!/usr/bin/env python3
"""
foundation/gen_outline_part2.py — 大纲增强器 (Part 2 — 伏笔账本)

读取已有 outline.md，调用 LLM 补充伏笔账本（foreshadowing ledger）。
"""

import sys
from pathlib import Path

from core.config import config, OUTPUT_DIR
from core.api_client import call_writer
from core.state_manager import step


OUTLINE_PART2_SYSTEM_PROMPT = """你是一位伏笔设计专家。你为小说大纲补充完整的伏笔账本：
— 每条线索标注：种植章、强化章、回收章、类型
— 种植→回收间距 ≥ 3 章
— 每条线索在回收前至少强化 1 次
— 类型多样化：物品、对话、行动、象征、结构
你的汉语写作简洁直接。"""


def generate_outline_part2() -> None:
    """增强 outline.md 的伏笔账本部分。"""
    cfg = config
    cfg.load()

    outline_path = OUTPUT_DIR / "outline.md"
    if not outline_path.exists():
        step("大纲文件不存在，跳过 Part 2")
        return

    outline_text = outline_path.read_text(encoding="utf-8")
    chars_path = OUTPUT_DIR / "characters.md"
    chars = chars_path.read_text(encoding="utf-8") if chars_path.exists() else ""

    prompt = f"""请基于以下大纲和角色信息，补充完整的伏笔账本（Foreshadowing Ledger）。

【现有大纲】
{outline_text[:12000]}

【角色信息】
{chars[:3000]}

请添加「## 伏笔账本」章节，格式如下：

| 编号 | 线索描述 | 种植章 | 强化章 | 回收章 | 类型 |

至少 15 条伏笔线索。类型包括：物品、对话、行动、象征、结构。
种植→回收间距必须 ≥ 3 章。每条线索在回收前至少强化 1 次。
每条线索的回收方式应让读者感到「意料之外、情理之中」。

将结果追加到现有大纲末尾。"""

    step("调用 LLM 生成伏笔账本 ...")
    result = call_writer(prompt, system=OUTLINE_PART2_SYSTEM_PROMPT, max_total_time=300)

    # 追加到 outline.md
    combined = outline_text.rstrip() + "\n\n" + result
    outline_path.write_text(combined, encoding="utf-8")
    step(f"伏笔账本已追加到: {outline_path}")


if __name__ == "__main__":
    generate_outline_part2()