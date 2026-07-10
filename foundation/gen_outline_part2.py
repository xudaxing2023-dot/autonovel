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


def generate_outline_part2(previous_output: str = "", eval_feedback: str = "") -> None:
    """增强 outline.md 的伏笔账本部分。

    Args:
        previous_output: 上一轮迭代的 outline.md 内容（增量改进模式）。
        eval_feedback: 评估裁判对该步骤的改进建议（增量改进模式）。
                       两个参数均为空字符串时，使用 from_scratch 模式（迭代 1 行为不变）。
    """
    cfg = config
    cfg.load()

    outline_path = OUTPUT_DIR / "outline.md"
    if not outline_path.exists():
        step("大纲文件不存在，跳过 Part 2")
        return

    outline_text = outline_path.read_text(encoding="utf-8-sig")
    chars_path = OUTPUT_DIR / "characters.md"
    chars = chars_path.read_text(encoding="utf-8-sig") if chars_path.exists() else ""

    # ── 增量改进模式 vs from_scratch 模式 ──
    if previous_output and eval_feedback:
        step("使用增量改进模式生成伏笔账本（基于上一轮输出 + 评估反馈）...")
        prompt = f"""你正在改进大纲的伏笔账本部分。

【当前版本（需要改进的对象）】
{previous_output}

【改进建议（来自评估裁判）】
{eval_feedback}

【改进指南】
1. 保留当前版本中好的伏笔线索
2. 针对改进建议逐条修正：补充缺失的伏笔、调整种植/回收章位置、增加强化环节
3. 不要改变核心设定和故事方向
4. 只做有针对性的改进，不要推翻重写
5. 输出完整的改进后大纲（含伏笔账本）

【角色信息（参考）】
{chars}

请确保大纲末尾包含完整的「## 伏笔账本」章节，格式如下：

| 编号 | 线索描述 | 种植章 | 强化章 | 回收章 | 类型 |

至少 15 条伏笔线索。类型包括：物品、对话、行动、象征、结构。
种植→回收间距必须 ≥ 3 章。每条线索在回收前至少强化 1 次。"""
        step("调用 LLM 生成伏笔账本 ...")
        result = call_writer(prompt, system=OUTLINE_PART2_SYSTEM_PROMPT)
        # 改进模式：直接覆盖（不追加，因为改进 prompt 要求输出完整大纲）
        outline_path.write_text(result, encoding="utf-8")
    else:
        prompt = f"""请基于以下大纲和角色信息，补充完整的伏笔账本（Foreshadowing Ledger）。

【现有大纲】
{outline_text}

【角色信息】
{chars}

请添加「## 伏笔账本」章节，格式如下：

| 编号 | 线索描述 | 种植章 | 强化章 | 回收章 | 类型 |

至少 15 条伏笔线索。类型包括：物品、对话、行动、象征、结构。
种植→回收间距必须 ≥ 3 章。每条线索在回收前至少强化 1 次。
每条线索的回收方式应让读者感到「意料之外、情理之中」。

将结果追加到现有大纲末尾。"""

        step("调用 LLM 生成伏笔账本 ...")
        result = call_writer(prompt, system=OUTLINE_PART2_SYSTEM_PROMPT)

        # 追加到 outline.md
        combined = outline_text.rstrip() + "\n\n" + result
        outline_path.write_text(combined, encoding="utf-8")

    step(f"伏笔账本已更新: {outline_path}")


if __name__ == "__main__":
    generate_outline_part2()