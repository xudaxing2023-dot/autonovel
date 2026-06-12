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
列出力量/魔法/科技体系的硬规则。

## 五、矛盾标注
如果发现任何矛盾或冲突的事实，标注在此处以供后续解决。

【规则】
1. 只提取已经明确陈述的事实，不推断、不假设
2. 每条事实可独立验证
3. 目标：400+ 条事实"""

    step("调用 LLM 生成正典 ...")
    result = call_writer(prompt, system=CANON_SYSTEM_PROMPT, max_tokens=max_tokens)

    canon_path = OUTPUT_DIR / "canon.md"
    canon_path.write_text(result, encoding="utf-8")
    step(f"正典已保存: {canon_path}")


if __name__ == "__main__":
    generate_canon()