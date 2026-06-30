#!/usr/bin/env python3
"""
foundation/gen_canon.py — 正典生成器

从 world.md + characters.md 提取硬事实，生成 canon.md。
"""

import sys
from pathlib import Path

from core.config import config, OUTPUT_DIR
from core.api_client import call_writer
from core.state_manager import step


CANON_SYSTEM_PROMPT = """你是一位严谨的设定审计员。你从世界设定和角色信息中提取所有硬事实：
— 每条事实必须已经被明确陈述（不可推断或假设）
— 事实按类别组织
— 矛盾的事实标注为需要解决
你的汉语写作简洁直接，不使用 AI 套话。"""


def generate_canon(max_tokens: int = 16000) -> None:
    """生成 canon.md 并写入 output/ 目录。"""
    world_path = OUTPUT_DIR / "world.md"
    world = world_path.read_text(encoding="utf-8") if world_path.exists() else ""
    chars_path = OUTPUT_DIR / "characters.md"
    chars = chars_path.read_text(encoding="utf-8") if chars_path.exists() else ""

    cfg = config
    cfg.load()
    total_ch = cfg.total_chapters if cfg.loaded else 24

    prompt = f"""请根据以下世界观和角色信息，提取一份结构化正典（CANON.md）。

【世界观设定】
{world[:8000]}

【角色信息】
{chars[:6000]}

【正典格式】

## 一、世界观硬事实
逐条列出已明确陈述的世界设定事实。每条以「—」开头。

## 二、角色硬事实
逐条列出已明确陈述的角色事实。每条以「—」开头。

## 三、时间线硬事实
按时间顺序列出已明确陈述的历史事件。

## 四、规则硬事实
列出核心规则/特殊体系的硬规则（根据题材可能是能力体系、社会制度、科技设定等）。

## 五、矛盾标注
如果发现任何矛盾或冲突的事实，标注在此处以供后续解决。

【规则】
1. 只提取已经明确陈述的事实，不推断、不假设
2. 每条事实可独立验证
3. 目标：400+ 条事实"""

    step("调用 LLM 生成正典 ...")
    result = call_writer(prompt, system=CANON_SYSTEM_PROMPT, max_tokens=max_tokens, max_total_time=900)

    canon_path = OUTPUT_DIR / "canon.md"
    canon_path.write_text(result, encoding="utf-8")
    step(f"正典已保存: {canon_path}")


def count_canon_entries(canon_path=None) -> dict:
    """
    统计 canon.md 中各节事实条目数。
    条目 = 以「—」开头的行（排除空行和标题行）。
    返回: {"total": int, "world": int, "character": int, "timeline": int, "rules": int}
    体裁无关 — 纯文本计数，适用于任何类型的小说。
    """
    from pathlib import Path as _Path
    if canon_path is None:
        canon_path = OUTPUT_DIR / "canon.md"
    if isinstance(canon_path, str):
        canon_path = _Path(canon_path)
    if not canon_path.exists():
        return {"total": 0, "world": 0, "character": 0, "timeline": 0, "rules": 0}

    text = canon_path.read_text(encoding="utf-8")
    sections = {"一、世界观": 0, "二、角色": 0, "三、时间线": 0, "四、规则": 0}
    current_section = None

    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        # 检测节标题 — 匹配 "## 一、世界观硬事实" 等
        for key in sections:
            if key in line and line.startswith("##"):
                current_section = key
                break
        # 统计条目 — 兼容 EM DASH / HYPHEN / ASTERISK 三种 bullet
        if current_section and line.startswith(("—", "-", "*")):
            sections[current_section] += 1

    total = sum(sections.values())
    return {
        "total": total,
        "world": sections["一、世界观"],
        "character": sections["二、角色"],
        "timeline": sections["三、时间线"],
        "rules": sections["四、规则"],
    }


if __name__ == "__main__":
    generate_canon()