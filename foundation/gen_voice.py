#!/usr/bin/env python3
"""
foundation/gen_voice.py — 文风发现（替代原 voice_fingerprint.py）

试写 5 段不同风格的小说段落，选择最佳者，
填充 voice.md Part 2（本书专属文风身份）。
"""

import sys
from pathlib import Path

from core.config import config, OUTPUT_DIR, TEMPLATES_DIR
from core.api_client import call_writer
from core.state_manager import step


VOICE_SYSTEM_PROMPT = """你是一位文学风格的探索者。你用不同的笔触试写同一场景：
— 简约式：短句，精准，留白多
— 温暖式：亲密，感官丰富，情感充沛
— 冷峻式：客观，疏离，像纪录片旁白
— 诗性式：意象密集，语言有音乐性
— 口语式：像有人在讲故事，直接，有个性
你不对风格做评判，你只是展示每种风格的可能性。"""


def generate_voice(max_tokens: int = 16000) -> None:
    """发现文风并填充 voice.md Part 2。"""
    cfg = config
    cfg.load()

    story = cfg.story_summary
    world_path = OUTPUT_DIR / "world.md"
    world = world_path.read_text(encoding="utf-8") if world_path.exists() else ""
    chars_path = OUTPUT_DIR / "characters.md"
    chars = chars_path.read_text(encoding="utf-8") if chars_path.exists() else ""

    # 读取 voice 模板 Part 1
    voice_template = TEMPLATES_DIR / "voice.md"
    existing_voice = voice_template.read_text(encoding="utf-8") if voice_template.exists() else ""

    prompt = f"""请为以下小说概念试写 5 种不同文风的小说开头段落（每种约 300-500 字）。

【故事梗概】
{story[:2000]}

【世界观设定参考】
{world[:2000]}

【角色参考】
{chars[:2000]}

请依次写出：

## 风格 1：简约式
（短句、精准、留白多。像海明威或雷蒙德·卡佛。）

## 风格 2：温暖式
（亲密、感官丰富、情感充沛。像村上春树或巴克曼。）

## 风格 3：冷峻式
（客观、疏离、像纪录片旁白。像 J.M.库切或残雪。）

## 风格 4：诗性式
（意象密集、语言有音乐性。像张爱玲或马尔克斯。）

## 风格 5：口语式
（像有人在讲故事，直接、有个性。像王小波或冯唐。）

对每种风格，写完后简要标注这种风格适合这个故事的理由（1-2 句）。"""

    step("调用 LLM 试写 5 种文风 ...")
    result = call_writer(prompt, system=VOICE_SYSTEM_PROMPT, max_tokens=max_tokens, max_total_time=300)

    # 选择最佳风格 — 由 LLM 完成
    select_prompt = f"""以下是 5 种候选文风及其试写段落：

{result}

请选择最适合这个故事的一种风格，并写出：

## Part 2 — 本书专属文风身份

### 选定风格
（风格名称和一句话定位）

### 范例段落
（从试写中选择最精彩的一段作为范例）

### 反范例段落
（选择最不适合的一段作为反面教材，并解释为什么不合适）

### 文风特征清单
（列出 5-8 条具体的风格特征：语调、句式偏好、词汇域、比喻风格、对话风格等）

### 本小说文风规则
（列出 5-10 条这个风格在此小说中的具体写作规则）"""

    step("调用 LLM 选定最佳文风 ...")
    voice_identity = call_writer(select_prompt, max_tokens=4096)

    # 合并：Part 1（模板中的禁区） + Part 2（新发现的文风身份）
    full_voice = existing_voice.rstrip() + "\n\n---\n\n" + voice_identity

    voice_path = OUTPUT_DIR / "voice.md"
    voice_path.write_text(full_voice, encoding="utf-8")
    step(f"文风定义已保存: {voice_path}")


if __name__ == "__main__":
    generate_voice()