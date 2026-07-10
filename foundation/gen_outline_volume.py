#!/usr/bin/env python3
"""
foundation/gen_outline_volume.py — 卷级总纲生成器（方案 D Step 4）

为分层大纲提供顶层约束框架：
— 全书弧线（global arc）
— 逐卷规划（per-volume narrative function + key events + character movement）
— 跨卷伏笔矩阵（plant → reinforce → payoff lifecycle）
— 连续性契约（volume-to-volume transition snapshots）

支持单卷/多卷自适应拆分为 1–3 次链式 LLM 调用，每次 ≤ 14000 token。
链式传递前次输出保证全局一致性。

输出: output/outline_volume.md
"""

import sys
from pathlib import Path

from core.config import config, OUTPUT_DIR
from core.api_client import call_p1_writer
from core.state_manager import step
from prompts.outline_prompts import (
    VOLUME_OUTLINE_SYSTEM_PROMPT,
    build_volume_outline_prompt_part1,
    build_volume_outline_prompt_part2,
    build_volume_outline_prompt_part3,
    build_volume_outline_prompt_single)


def _load_context() -> dict:
    """加载生成卷级总纲所需的全部上下文。"""
    cfg = config
    cfg.load()

    world_path = OUTPUT_DIR / "world.md"
    world = world_path.read_text(encoding="utf-8-sig") if world_path.exists() else ""

    chars_path = OUTPUT_DIR / "characters.md"
    chars = chars_path.read_text(encoding="utf-8-sig") if chars_path.exists() else ""

    voice_path = OUTPUT_DIR / "voice.md"
    voice = voice_path.read_text(encoding="utf-8-sig") if voice_path.exists() else ""

    total_vol = cfg.total_volumes
    total_ch = cfg.total_chapters
    ch_per_vol = cfg.chapters_per_volume

    # 兜底：chapters_per_volume 未配置时自动计算
    if not ch_per_vol:
        ch_per_vol = max(1, total_ch // max(1, total_vol))

    return {
        "story": cfg.story_summary,
        "world": world,
        "characters": chars,
        "voice": voice,
        "total_volumes": total_vol,
        "chapters_per_volume": ch_per_vol,
        "total_chapters": total_ch,
    }


def _split_volumes(total_vol: int) -> list[tuple[int, int]]:
    """将 total_vol 卷拆分为 1–3 个组，每组 (start_vol, end_vol)。

    拆分策略:
      — 1 卷: 1 组 → [(1, 1)]
      — 2–3 卷: 2 组 → 前 ⌈N/2⌉ 卷 + 剩余
      — 4+ 卷: 3 组 → 均匀三等分

    Returns:
        [(start_vol, end_vol), ...]  按调用顺序排列
    """
    if total_vol <= 1:
        return [(1, 1)]

    if total_vol <= 4:
        # 2–4 卷: 均分两组，每组至少 1 卷
        mid = (total_vol + 1) // 2  # ⌈N/2⌉
        return [(1, mid), (mid + 1, total_vol)]

    # 5+ 卷: 三等分，每组至少 1 卷
    # 确保 g2_end < total_vol（给第三组留空间）
    chunk = (total_vol + 2) // 3  # ⌈N/3⌉
    g1_end = chunk
    g2_end = min(chunk * 2, total_vol - 1)
    return [
        (1, g1_end),
        (g1_end + 1, g2_end),
        (g2_end + 1, total_vol),
    ]


def _call_volume_segment(
    segment_index: int,
    total_segments: int,
    prior_outputs: str,
    ctx: dict,
    vol_start: int,
    vol_end: int,
    ) -> str:
    """执行一次卷级总纲 LLM 调用。

    segment_index=0 → part1 prompt
    segment_index=1 → part2 prompt（接收 part1 输出）
    segment_index=2 → part3 prompt（接收 part1+2 输出）
    """
    if total_segments == 1:
        # 单卷模式 — 专用 prompt
        prompt = build_volume_outline_prompt_single(
            story=ctx["story"],
            world_text=ctx["world"],
            characters_text=ctx["characters"],
            voice_text=ctx["voice"],
            total_chapters=ctx["total_chapters"])
        label = "卷级总纲（单卷）"
    elif segment_index == 0:
        prompt = build_volume_outline_prompt_part1(
            story=ctx["story"],
            world_text=ctx["world"],
            characters_text=ctx["characters"],
            voice_text=ctx["voice"],
            vol_start=vol_start,
            vol_end=vol_end,
            total_volumes=ctx["total_volumes"],
            chapters_per_volume=ctx["chapters_per_volume"])
        label = (
            f"卷级总纲 调用 {segment_index + 1}/{total_segments}: "
            f"卷 {vol_start}–{vol_end}"
        )
    elif segment_index == 1:
        prompt = build_volume_outline_prompt_part2(
            vol_start=vol_start,
            vol_end=vol_end,
            total_volumes=ctx["total_volumes"],
            chapters_per_volume=ctx["chapters_per_volume"],
            prior_output=prior_outputs,
            story=ctx.get("story", ""),
            world_text=ctx.get("world", ""),
            characters_text=ctx.get("characters", ""),
            voice_text=ctx.get("voice", ""))
        label = (
            f"卷级总纲 调用 {segment_index + 1}/{total_segments}: "
            f"卷 {vol_start}–{vol_end}"
        )
    else:  # segment_index == 2
        prompt = build_volume_outline_prompt_part3(
            vol_start=vol_start,
            vol_end=vol_end,
            total_volumes=ctx["total_volumes"],
            chapters_per_volume=ctx["chapters_per_volume"],
            prior_output=prior_outputs,
            story=ctx.get("story", ""),
            world_text=ctx.get("world", ""),
            characters_text=ctx.get("characters", ""),
            voice_text=ctx.get("voice", ""))
        label = (
            f"卷级总纲 调用 {segment_index + 1}/{total_segments}: "
            f"卷 {vol_start}–{vol_end}"
        )

    step(f"调用 LLM — {label} ...")
    result = call_p1_writer(
        prompt,
        system=VOLUME_OUTLINE_SYSTEM_PROMPT,
        temperature=0.7)   # 结构规划需要比创造性写作略低的温度
    step(f"{label} 完成 ({len(result)} chars)")
    return result


def _assemble_volume_outline(outputs: list[str], total_vol: int) -> str:
    """合并多次调用的输出为单一 outline_volume.md。

    单次调用（total_vol=1）直接返回原文，不做处理。
    多次调用时用分隔线标记各部分的边界。
    """
    if len(outputs) == 1:
        return outputs[0]

    parts = []
    for i, out in enumerate(outputs):
        header = (
            f"\n\n{'=' * 60}\n"
            f"## 卷级总纲 — 第 {i + 1}/{len(outputs)} 部分\n"
            f"{'=' * 60}\n\n"
        )
        parts.append(header + out)

    return "\n".join(parts)


def generate_volume_outline(previous_output: str = "", eval_feedback: str = "") -> None:
    """生成卷级总纲 → output/outline_volume.md。

    根据 total_volumes 自适应拆分为 1–3 次链式 LLM 调用。
    每次调用不再限制 max_tokens，由模型自主决定输出长度。

    Args:
        previous_output: 上一轮迭代的 outline_volume.md 内容（增量改进模式）。
        eval_feedback: 评估裁判对该步骤的改进建议（增量改进模式）。
                       两个参数均为空字符串时，使用 from_scratch 模式（迭代 1 行为不变）。
    """
    ctx = _load_context()
    total_vol = ctx["total_volumes"]

    step(
        f"卷级总纲: {total_vol} 卷, 每卷 {ctx['chapters_per_volume']} 章, "
        f"共 {ctx['total_chapters']} 章"
    )

    # ── 增量改进模式：直接对已有卷级总纲做针对性改进 ──
    if previous_output and eval_feedback:
        step("使用增量改进模式生成卷级总纲（基于上一轮输出 + 评估反馈）...")
        # 使用单次 LLM 调用做改进（不拆分，因为改进通常不需要很多 token）
        improve_prompt = f"""你正在改进卷级总纲（outline_volume.md）——小说的卷级结构规划。

【当前版本（需要改进的对象）】
{previous_output}

【改进建议（来自评估裁判）】
{eval_feedback}

【改进指南】
1. 保留当前版本中好的卷级规划结构
2. 针对改进建议逐条修正：调整卷间过渡、补充关键事件、修正角色弧线断层
3. 不要改变核心设定和故事方向
4. 只做有针对性的改进，不要推翻重写
5. 输出完整的改进后卷级总纲

【参考上下文】
## 故事梗概
{ctx['story']}

## 世界观设定
{ctx['world']}

## 角色注册表
{ctx['characters']}

## 文风参考
{ctx['voice']}

请输出完整的改进后卷级总纲。"""
        result = call_p1_writer(
            improve_prompt,
            system=VOLUME_OUTLINE_SYSTEM_PROMPT,
            temperature=0.7)
        outline_path = OUTPUT_DIR / "outline_volume.md"
        outline_path.write_text(result, encoding="utf-8")
        step(f"卷级总纲已更新: {outline_path} ({len(result)} chars)")
        return

    groups = _split_volumes(total_vol)
    total_segments = len(groups)

    outputs: list[str] = []
    prior = ""

    for i, (vol_start, vol_end) in enumerate(groups):
        result = _call_volume_segment(
            segment_index=i,
            total_segments=total_segments,
            prior_outputs=prior,
            ctx=ctx,
            vol_start=vol_start,
            vol_end=vol_end)
        outputs.append(result)
        prior = "\n\n---\n\n".join(outputs)

    full_outline = _assemble_volume_outline(outputs, total_vol)
    outline_path = OUTPUT_DIR / "outline_volume.md"
    outline_path.write_text(full_outline, encoding="utf-8")
    step(f"卷级总纲已保存: {outline_path} ({len(full_outline)} chars)")


if __name__ == "__main__":
    generate_volume_outline()