#!/usr/bin/env python3
"""
foundation/gen_outline.py — 大纲生成器 (Part 1)

从故事梗概 + world.md + characters.md 调用 LLM 生成 outline.md（节拍 + 章节结构）。
"""

import re
import sys
from pathlib import Path

from core.config import config, OUTPUT_DIR
from core.api_client import call_writer, call_p1_writer
from core.state_manager import step
from prompts.outline_prompts import (
    build_outline_prompt,
    CHAPTER_OUTLINE_SYSTEM_PROMPT,
    build_chapter_outline_for_volume_prompt,
)


OUTLINE_SYSTEM_PROMPT = """你是一位小说结构架构师，深谙：
— Save the Cat 节拍表
— Dan Harmon 故事圈（分形应用）
— Sanderson 的许诺-进展-回报原则
— MICE 商数（Milieu/Inquiry/Character/Event 嵌套关闭）
— try-fail 循环设计
你构建的大纲让作者可以直接起草，无需现场发明结构。
每一章都有节拍、情感弧线、try-fail 类型。
你的汉语写作简洁直接，不使用 AI 套话。"""


# ============================================================
# 方案 D Step 5 新增 — 章级大纲自适应拆分 + 卷约束提取
# ============================================================

def _split_chapters_for_volume(start_ch: int, end_ch: int) -> list[tuple[int, int]]:
    """将卷内章节按 ≤5 章/组拆分为 1–N 组。

    拆分策略:
      — ≤5 章: 1 组 → [(start, end)]
      — 6–10 章: 2 组 → 前 ⌈N/2⌉ 章 + 剩余
      — 11+ 章: ceil(N/5) 组 → 每组 ≤5 章

    Returns:
        [(ch_start, ch_end), ...]  按调用顺序排列
    """
    total = end_ch - start_ch + 1
    if total <= 5:
        return [(start_ch, end_ch)]

    if total <= 10:
        mid = (total + 1) // 2
        return [(start_ch, start_ch + mid - 1), (start_ch + mid, end_ch)]

    # 11+ 章: 每组 5 章，最后一组收尾
    groups = []
    cur = start_ch
    while cur <= end_ch:
        nxt = min(cur + 4, end_ch)
        groups.append((cur, nxt))
        cur = nxt + 1
    return groups


def _extract_volume_section(vol_macro_text: str, volume_num: int) -> str:
    """从卷级总纲（outline_volume.md）提取指定卷的约束段。

    匹配模式:
      — "### 卷 N：" 或 "### 卷 N [" 开头
      — 到下一个 "### 卷 " 或 "## 二、" 或 "## 三、" 或文件末尾为止

    Returns:
        提取到的卷约束文本；未找到返回空字符串。
    """
    # 匹配从 "### 卷 N" 开始到下一个同级标题结束
    pattern = (
        rf'(###\s*卷\s*{volume_num}\s*[：\[].*?)'
        rf'(?=###\s*卷\s*{volume_num + 1}\s*[：\[]|##\s*[二三四五六七八九十]|$)'
    )
    match = re.search(pattern, vol_macro_text, re.DOTALL)
    if match:
        return match.group(1).strip()

    # 备选：英文标题格式
    pattern_en = (
        rf'(###\s*Vol(?:ume)?\s*{volume_num}[：:\[](.*?))'
        rf'(?=###\s*Vol(?:ume)?\s*{volume_num + 1}[：:\[]|##\s*[IVX]|$)'
    )
    match = re.search(pattern_en, vol_macro_text, re.DOTALL)
    if match:
        return match.group(1).strip()

    return ""


def _generate_outline_segment(
    volume_num: int,
    ch_start: int,
    ch_end: int,
    segment_index: int,
    total_segments: int,
    vol_section: str,
    prior_output: str,
    prev_vol_tail: str,
    world_text: str,
    characters_text: str,
    voice_text: str,
    max_tokens: int,
) -> str:
    """执行一次章级大纲 LLM 调用（一段章节）。

    链式传递：prior_output 包含所有前段输出，LLM 依此保持卷内连贯。
    """
    prompt = build_chapter_outline_for_volume_prompt(
        volume_num=volume_num,
        ch_start=ch_start,
        ch_end=ch_end,
        vol_section=vol_section,
        prior_segment=prior_output,
        prev_vol_tail=prev_vol_tail,
        world_text=world_text,
        characters_text=characters_text,
        voice_text=voice_text,
    )

    label = (
        f"第 {volume_num} 卷章级大纲 调用 {segment_index + 1}/{total_segments}: "
        f"第 {ch_start}–{ch_end} 章"
    )

    step(f"调用 LLM — {label} ...")
    result = call_p1_writer(
        prompt,
        system=CHAPTER_OUTLINE_SYSTEM_PROMPT,
        max_tokens=max_tokens,
        temperature=0.7,
        max_total_time=600,
    )
    step(f"{label} 完成 ({len(result)} chars)")
    return result


def generate_outline_for_volume(
    volume_num: int,
    max_tokens: int = 14000,
) -> None:
    """为指定卷生成章级大纲 → output/outline_volume{N}.md。

    根据 chapters_per_volume 自适应拆分为 1–N 次链式 LLM 调用。
    每次调用 ≤ max_tokens（默认 14000，适配 16000 硬限制）。

    Args:
        volume_num: 卷号（1-indexed）。
        max_tokens: 每次 LLM 调用的 max_tokens。
    """
    cfg = config
    cfg.load()

    ch_per_vol = cfg.chapters_per_volume  # 已由 config property 自动计算，≥ 1

    start_ch = (volume_num - 1) * ch_per_vol + 1
    end_ch = volume_num * ch_per_vol

    step(
        f"第 {volume_num} 卷章级大纲: 第 {start_ch}–{end_ch} 章 "
        f"（共 {end_ch - start_ch + 1} 章）"
    )

    # ── 加载上下文 ──────────────────────────────────────

    # 卷级总纲约束
    vol_macro_path = OUTPUT_DIR / "outline_volume.md"
    vol_section = ""
    if vol_macro_path.exists():
        vol_macro = vol_macro_path.read_text(encoding="utf-8")
        vol_section = _extract_volume_section(vol_macro, volume_num)
        if not vol_section:
            step(
                f"  ⚠ 未在 outline_volume.md 中找到卷 {volume_num} 的约束段，"
                f"将使用全书弧线作为参考"
            )
            vol_section = vol_macro[:4000]  # 回退：用全书弧线

    # 前一卷章级大纲（跨卷衔接）
    prev_vol_tail = ""
    if volume_num > 1:
        prev_path = OUTPUT_DIR / f"outline_volume{volume_num - 1}.md"
        if prev_path.exists():
            prev_text = prev_path.read_text(encoding="utf-8")
            prev_vol_tail = prev_text[-4000:] if len(prev_text) > 4000 else prev_text
            step(f"  加载前一卷章级大纲: {len(prev_vol_tail)} chars (尾部)")

    # 基础文档
    world_path = OUTPUT_DIR / "world.md"
    world = world_path.read_text(encoding="utf-8") if world_path.exists() else ""

    chars_path = OUTPUT_DIR / "characters.md"
    chars = chars_path.read_text(encoding="utf-8") if chars_path.exists() else ""

    voice_path = OUTPUT_DIR / "voice.md"
    voice = voice_path.read_text(encoding="utf-8") if voice_path.exists() else ""

    # ── 拆分章组并链式调用 ──────────────────────────────

    groups = _split_chapters_for_volume(start_ch, end_ch)
    total_segments = len(groups)

    outputs: list[str] = []
    prior = ""

    for i, (seg_start, seg_end) in enumerate(groups):
        result = _generate_outline_segment(
            volume_num=volume_num,
            ch_start=seg_start,
            ch_end=seg_end,
            segment_index=i,
            total_segments=total_segments,
            vol_section=vol_section,
            prior_output=prior,
            prev_vol_tail=prev_vol_tail,
            world_text=world,
            characters_text=chars,
            voice_text=voice,
            max_tokens=max_tokens,
        )
        outputs.append(result)
        prior = "\n\n---\n\n".join(outputs)

    # ── 写入输出文件 ──────────────────────────────────────

    full_outline = "\n\n".join(outputs)
    outline_path = OUTPUT_DIR / f"outline_volume{volume_num}.md"
    outline_path.write_text(full_outline, encoding="utf-8")
    step(
        f"第 {volume_num} 卷章级大纲已保存: {outline_path} "
        f"({len(full_outline)} chars, {total_segments} 次调用)"
    )


# ============================================================
# 向后兼容封装 — generate_outline()
# ============================================================

def generate_outline(max_tokens: int = 16000) -> None:
    """生成 outline.md（向后兼容封装）。

    方案 D 始终走分层大纲路径：
    — 逐卷生成 outline_volume{N}.md
    — 然后合并全部卷级大纲写入 outline.md

    这确保现有消费者（draft_chapter.py、evaluate.py、gen_outline_part2.py）
    无需任何改动即可继续工作。
    """
    cfg = config
    cfg.load()

    total_vol = cfg.total_volumes

    step(f"大纲生成: {total_vol} 卷，逐卷生成章级大纲 ...")

    all_parts = []
    for vol in range(1, total_vol + 1):
        generate_outline_for_volume(vol, max_tokens=14000)
        vol_path = OUTPUT_DIR / f"outline_volume{vol}.md"
        if vol_path.exists():
            all_parts.append(
                f"\n\n{'=' * 60}\n"
                f"## 第 {vol} 卷\n"
                f"{'=' * 60}\n\n"
                + vol_path.read_text(encoding="utf-8")
            )

    outline_path = OUTPUT_DIR / "outline.md"
    outline_path.write_text("\n".join(all_parts), encoding="utf-8")
    step(f"大纲（合并 {total_vol} 卷）已保存: {outline_path}")


if __name__ == "__main__":
    generate_outline()