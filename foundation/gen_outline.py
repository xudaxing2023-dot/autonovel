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
from core.diagnostic import debug_log
from core.pattern_registry import registry
from core.state_manager import step
from prompts.outline_prompts import (
    build_outline_prompt,
    CHAPTER_OUTLINE_SYSTEM_PROMPT,
    build_chapter_outline_for_volume_prompt)


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


def _cn_to_arabic(cn: str) -> int | None:
    """将中文数字（一～四百九十九）转换为阿拉伯数字。"""
    _MAP = {
        "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
        "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
    }
    cn = cn.strip()

    # —— 百位处理 (100–499) ——
    if "百" in cn:
        parts = cn.split("百", 1)
        hundreds_str = parts[0]
        remainder = parts[1] if len(parts) > 1 else ""

        hundreds = _MAP.get(hundreds_str, 0)
        if hundreds == 0 or hundreds > 4:
            return None

        if not remainder:
            return hundreds * 100

        # remainder: 零一(101), 一十(110), 二十一(121), 九十九(499) 等
        if remainder.startswith("零"):
            # 一百零一 → 101, 二百零九 → 209
            ones = _MAP.get(remainder[1], 0) if len(remainder) >= 2 else 0
            return hundreds * 100 + ones
        else:
            # 递归解析余数 (1–99)
            remainder_val = _cn_to_arabic(remainder)
            if remainder_val is not None:
                return hundreds * 100 + remainder_val
            return None

    # —— 个位/十位处理 (1–99) ——
    if cn in _MAP:
        return _MAP[cn]
    # 十一～十九
    if cn.startswith("十") and len(cn) == 2:
        return 10 + _MAP.get(cn[1], 0)
    # 二十～九十九
    if len(cn) == 2 and cn[1] == "十":
        tens = _MAP.get(cn[0], 0)
        return tens * 10
    if len(cn) == 3 and cn[1] == "十":
        tens = _MAP.get(cn[0], 0)
        ones = _MAP.get(cn[2], 0)
        return tens * 10 + ones
    return None


def _build_volume_patterns(volume_num: int) -> list[tuple[str, str]]:
    """为指定卷号构建多级正则表达式模式列表。

    返回 [(heading_pattern, next_section_pattern), ...]，按优先级降序排列。
    每个 heading_pattern 匹配一行包含该卷号的标题/标记行。

    支持两种卷号表述模式：
      — 「卷 N」模式：卷 1、卷一（数字在"卷"之后）
      — 「第N卷」模式：第一卷、第1卷（数字在"第"和"卷"之间）
    """
    # 生成所有等价的卷号表述
    num_variants: list[str] = [str(volume_num)]  # "1", "2"
    # 中文数字映射（1→一, 2→二, ...）
    _ARABIC_TO_CN = {
        1: "一", 2: "二", 3: "三", 4: "四", 5: "五",
        6: "六", 7: "七", 8: "八", 9: "九", 10: "十",
    }
    cn = _ARABIC_TO_CN.get(volume_num)
    if cn:
        num_variants.append(cn)  # "一", "二"

    def _num_alt() -> str:
        """构建卷号正则片段: (?:1|一) 等。"""
        return "(?:" + "|".join(num_variants) + ")"

    n = _num_alt()

    # 核心匹配片段：匹配「卷 N」「卷一」或「第N卷」「第一卷」
    #   (?:第{N}卷|卷\s*{N})  — 覆盖两种模式
    vol_ref = rf'(?:第{n}卷|卷\s*{n})\b'

    patterns: list[tuple[str, str]] = [
        # 1) ### / ## 标题（最优先）：
        #    '### 二、卷 1 规划'  '### 卷 1：时空的裂缝'  '### 第一卷：开端'
        #    '### 卷一：迷雾'  '## 卷 1 规划（3章）'  '## 二、逐卷规划（卷1）'
        (rf'^#{{2,3}}\s*[^\n]*?{vol_ref}[^\n]*$', r'^#{2,3}\s'),

        # 2) **粗体** 标记：'**卷 1：开端**'  '**第一卷：开端**'  '**二、卷 1 规划**'
        (rf'^\*\*[^*\n]*?{vol_ref}[^*\n]*\*\*\s*$', r'^(\*\*|#{2,3})\s'),

        # 3) 任意包含卷号引用的行（最宽泛回退）
        (rf'^[^\n]*?{vol_ref}[^\n]*$', r'^(\*\*|#{2,3}|##)\s'),
    ]

    return patterns


def _extract_global_prefix(vol_macro_text: str) -> str:
    """提取 outline_volume.md 的全局视角前缀。

    识别「全书弧线」「核心冲突」「全局节拍」「MICE」「伏笔总账」
    等全局战略段落，截取从文件头到第一个卷专属标题之前的内容。
    每卷生成章级大纲时都应引用此部分作为公共上下文。

    Returns:
        全局前缀文本；未识别到则返回空字符串。
    """
    # 全局段落的关键词标记
    global_markers = [
        "全书弧线", "核心冲突", "全局节拍", "MICE",
        "伏笔总账", "跨卷伏笔", "阶段性演化",
    ]
    # 卷专属段落的分界标记（通过 Pattern Registry 统一管理，支持更多变体）
    boundary_result = registry.match("outline.vol_boundary", vol_macro_text)
    if not boundary_result.value:
        return ""
    vol_boundary = boundary_result.value  # re.Match 对象
    
    prefix_text = vol_macro_text[:vol_boundary.start()].strip()
    if not prefix_text:
        return ""
    
    # 验证是否包含全局关键词
    has_global = any(marker in prefix_text for marker in global_markers)
    return prefix_text if has_global else ""


def _extract_volume_section(vol_macro_text: str, volume_num: int) -> str:
    """从卷级总纲（outline_volume.md）提取指定卷的约束段。

    多级回退策略：
    1. 匹配 ### / ## 标题行（支持 '### 二、卷 1 规划' / '### 卷 1：标题' / '### 卷一：…'）
    2. 回退：匹配 **粗体** 标记行（如 '**卷 1：开端**'）
    3. 回退：匹配任何包含"卷 N"的非空行

    支持阿拉伯数字（1, 2）和中文数字（一, 二, 第一, 第二）的卷号表述。
    提取从匹配行到下一个同级标记或文件末尾的内容。

    ★ 每卷都会自动拼接全局视角前缀（全书弧线、跨卷伏笔等公共战略信息）。

    Returns:
        提取到的卷约束文本（含全局前缀）；未找到返回空字符串。
    """
    # 提取全局前缀（全书弧线等公共战略段落）
    global_prefix = _extract_global_prefix(vol_macro_text)
    
    # 提取卷专属段落
    patterns = _build_volume_patterns(volume_num)
    vol_section = ""

    for heading_pat, next_pat in patterns:
        match = re.search(heading_pat, vol_macro_text, re.MULTILINE)
        if not match:
            continue

        start = match.start()
        remaining = vol_macro_text[match.end():]
        next_marker = re.search(next_pat, remaining, re.MULTILINE)
        if next_marker:
            end = match.end() + next_marker.start()
            vol_section = vol_macro_text[start:end].strip()
        else:
            vol_section = vol_macro_text[start:].strip()
        break

    # 拼接全局前缀 + 卷专属段落
    if global_prefix and vol_section:
        return f"{global_prefix}\n\n---\n\n{vol_section}"
    elif global_prefix:
        return global_prefix
    return vol_section


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
        voice_text=voice_text)

    label = (
        f"第 {volume_num} 卷章级大纲 调用 {segment_index + 1}/{total_segments}: "
        f"第 {ch_start}–{ch_end} 章"
    )

    step(f"调用 LLM — {label} ...")
    result = call_p1_writer(
        prompt,
        system=CHAPTER_OUTLINE_SYSTEM_PROMPT,
        temperature=0.7)
    step(f"{label} 完成 ({len(result)} chars)")
    return result


def generate_outline_for_volume(
    volume_num: int) -> None:
    """为指定卷生成章级大纲 → output/outline_volume{N}.md。

    根据 chapters_per_volume 自适应拆分为 1–N 次链式 LLM 调用。
    每次调用不再限制 max_tokens，由模型自主决定输出长度。

    Args:
        volume_num: 卷号（1-indexed）。
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
        vol_macro = vol_macro_path.read_text(encoding="utf-8-sig")
        vol_section = _extract_volume_section(vol_macro, volume_num)
        if not vol_section:
            step(
                f"⚠ 警告: 无法在 outline_volume.md 中找到卷 {volume_num} 的约束段。"
                f"将继续生成章级大纲（依赖 world.md + characters.md 上下文）。"
                f"建议检查 outline_volume.md 是否包含 "
                f"'### 卷 {volume_num}：标题' 或 '## 卷 {volume_num} 规划' 等标题行。"
            )
            debug_log(
                "WARNING",
                f"卷 {volume_num} 约束段缺失，回退到无卷约束生成",
                data={"volume_num": volume_num, "file": str(vol_macro_path)})

    # 前一卷章级大纲（跨卷衔接）
    prev_vol_tail = ""
    if volume_num > 1:
        prev_path = OUTPUT_DIR / f"outline_volume{volume_num - 1}.md"
        if prev_path.exists():
            prev_text = prev_path.read_text(encoding="utf-8-sig")
            prev_vol_tail = prev_text
            step(f"  加载前一卷章级大纲: {len(prev_vol_tail)} chars (尾部)")

    # 基础文档
    world_path = OUTPUT_DIR / "world.md"
    world = world_path.read_text(encoding="utf-8-sig") if world_path.exists() else ""

    chars_path = OUTPUT_DIR / "characters.md"
    chars = chars_path.read_text(encoding="utf-8-sig") if chars_path.exists() else ""

    voice_path = OUTPUT_DIR / "voice.md"
    voice = voice_path.read_text(encoding="utf-8-sig") if voice_path.exists() else ""

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
            voice_text=voice)
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

def generate_outline(previous_output: str = "", eval_feedback: str = "") -> None:
    """生成 outline.md（向后兼容封装）。

    方案 D 始终走分层大纲路径：
    — 逐卷生成 outline_volume{N}.md
    — 然后合并全部卷级大纲写入 outline.md

    这确保现有消费者（draft_chapter.py、evaluate.py、gen_outline_part2.py）
    无需任何改动即可继续工作。

    Args:
        previous_output: 上一轮迭代的 outline.md 内容（增量改进模式）。
        eval_feedback: 评估裁判对该步骤的改进建议（增量改进模式）。
                       两个参数均为空字符串时，使用 from_scratch 模式（迭代 1 行为不变）。
    """
    cfg = config
    cfg.load()

    total_vol = cfg.total_volumes

    # ── 增量改进模式：对已有大纲做针对性改进 ──
    if previous_output and eval_feedback:
        step("使用增量改进模式生成章级大纲（基于上一轮输出 + 评估反馈）...")
        # 逐卷使用改进 prompt 重新生成章级大纲
        for vol in range(1, total_vol + 1):
            # 读取当前卷的已有章级大纲
            vol_path = OUTPUT_DIR / f"outline_volume{vol}.md"
            prev_vol_text = ""
            if vol_path.exists():
                prev_vol_text = vol_path.read_text(encoding="utf-8-sig")

            # 加载上下文
            world_path = OUTPUT_DIR / "world.md"
            world = world_path.read_text(encoding="utf-8-sig") if world_path.exists() else ""
            chars_path = OUTPUT_DIR / "characters.md"
            chars = chars_path.read_text(encoding="utf-8-sig") if chars_path.exists() else ""
            voice_path = OUTPUT_DIR / "voice.md"
            voice = voice_path.read_text(encoding="utf-8-sig") if voice_path.exists() else ""

            # 卷级总纲约束
            vol_macro_path = OUTPUT_DIR / "outline_volume.md"
            vol_section = ""
            if vol_macro_path.exists():
                vol_macro = vol_macro_path.read_text(encoding="utf-8-sig")
                vol_section = _extract_volume_section(vol_macro, vol)

            # 构建改进 prompt
            improve_prompt = f"""你正在改进第 {vol} 卷的章级大纲。

【当前版本（需要改进的对象）】
{prev_vol_text}

【改进建议（来自评估裁判）】
{eval_feedback}

【改进指南】
1. 保留当前版本中好的章级大纲结构
2. 针对改进建议逐条修正：补充缺失的节拍、调整 try-fail 类型、增强伏笔种植
3. 不要改变核心设定和故事方向
4. 只做有针对性的改进，不要推翻重写
5. 输出完整的改进后章级大纲

【参考上下文】
## 卷级总纲约束
{vol_section}

## 世界观设定
{world}

## 角色注册表
{chars}

## 文风参考
{voice}

请输出完整的改进后第 {vol} 卷章级大纲。"""

            step(f"  改进第 {vol} 卷章级大纲 ...")
            result = call_p1_writer(
                improve_prompt,
                system=CHAPTER_OUTLINE_SYSTEM_PROMPT,
                temperature=0.7)
            vol_path.write_text(result, encoding="utf-8")

        step("增量改进完成，合并卷级大纲 ...")
    else:
        step(f"大纲生成: {total_vol} 卷，逐卷生成章级大纲 ...")

        all_parts = []
        for vol in range(1, total_vol + 1):
            generate_outline_for_volume(vol)
            vol_path = OUTPUT_DIR / f"outline_volume{vol}.md"
            if vol_path.exists():
                all_parts.append(
                    f"\n\n{'=' * 60}\n"
                    f"## 第 {vol} 卷\n"
                    f"{'=' * 60}\n\n"
                    + vol_path.read_text(encoding="utf-8-sig")
                )

    # 合并所有卷级大纲写入 outline.md
    all_parts = []
    for vol in range(1, total_vol + 1):
        vol_path = OUTPUT_DIR / f"outline_volume{vol}.md"
        if vol_path.exists():
            all_parts.append(
                f"\n\n{'=' * 60}\n"
                f"## 第 {vol} 卷\n"
                f"{'=' * 60}\n\n"
                + vol_path.read_text(encoding="utf-8-sig")
            )

    outline_path = OUTPUT_DIR / "outline.md"
    outline_path.write_text("\n".join(all_parts), encoding="utf-8")
    step(f"大纲（合并 {total_vol} 卷）已保存: {outline_path}")


if __name__ == "__main__":
    generate_outline()