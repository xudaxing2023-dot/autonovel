#!/usr/bin/env python3
"""
pipeline_orchestrator.py — 主流水线编排器

将原 autonovel 的 run_pipeline.py 完全重构：
- 调度 Phase 1-4 全部流程
- 管理 state.json 状态
- git / 文件备份双模式版本控制
- results.tsv 实验结果日志
- 支持 Ctrl+C 安全中断
"""

import argparse
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# Windows 控制台 GBK 编码不支持中文，强制使用 UTF-8
# 管道/重定向环境下 reconfigure 可能失败，此时依赖 _safe_print / _stderr_print 降级
_STDOUT_UTF8_OK = False
_STDERR_UTF8_OK = False
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        _STDOUT_UTF8_OK = True
    except (OSError, AttributeError):
        pass
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        _STDERR_UTF8_OK = True
    except (OSError, AttributeError):
        pass

# 核心基础设施
from core.config import config, ROOT_DIR, OUTPUT_DIR, CHAPTERS_DIR, BRIEFS_DIR, EDIT_LOGS_DIR, EVAL_LOGS_DIR, STATE_FILE, BACKUPS_DIR
from core.api_client import call_llm, call_writer, get_rate_limiter
from core.diagnostic import debug_log, crash_handler
from core.state_manager import (
    load_state, save_state, default_state,
    git_available, git_short_hash, git_add_commit, git_reset_hard,
    backup_snapshot, restore_latest,
    log_result, banner, step, parse_score, parse_lore_score,
    count_words_in_chapters, count_chapter_files, get_total_chapters,
    evaluate_chapter_stable, evaluate_foundation_stable)
from foundation.gen_outline import _cn_to_arabic
from foundation.feedback_extractor import (
    load_latest_foundation_eval,
    extract_feedback,
    map_feedback_to_step)


# ============================================================================
# 常量
# ============================================================================

FOUNDATION_THRESHOLD = 7.5
CHAPTER_THRESHOLD = 7.0
MAX_FOUNDATION_ITERS = 20
MAX_CHAPTER_ATTEMPTS = 10
MIN_REVISION_CYCLES = 3
MAX_REVISION_CYCLES = 6
PLATEAU_DELTA = 0.3
PHASE_ORDER = ["foundation", "drafting", "revision", "export"]


# ============================================================================
# Phase 1 — Foundation (基础构建)
# ============================================================================

def _load_previous_outputs() -> dict[str, str]:
    """从 output/ 目录读取上一轮迭代生成的所有文件内容。

    用于增量改进架构：迭代 2+ 时，将上一轮的输出作为
    previous_output 参数传给各 gen 函数。

    Returns:
        {文件名（不含路径）: 文件内容} 字典。
        文件不存在时对应值为空字符串。
    """
    files = {
        "world":        OUTPUT_DIR / "world.md",
        "characters":   OUTPUT_DIR / "characters.md",
        "outline":      OUTPUT_DIR / "outline.md",
        "canon":        OUTPUT_DIR / "canon.md",
        "voice":        OUTPUT_DIR / "voice.md",
        "outline_volume": OUTPUT_DIR / "outline_volume.md",
    }
    outputs: dict[str, str] = {}
    for key, path in files.items():
        if path.exists():
            try:
                outputs[key] = path.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeDecodeError):
                outputs[key] = ""
        else:
            outputs[key] = ""
    return outputs


def run_foundation(state: dict) -> dict:
    banner("PHASE 1: FOUNDATION (基础构建)", "=")

    # 确保所有子目录存在（直接调用 run_foundation 时不会走 run_pipeline 的 mkdir）
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    CHAPTERS_DIR.mkdir(parents=True, exist_ok=True)
    BRIEFS_DIR.mkdir(parents=True, exist_ok=True)
    EDIT_LOGS_DIR.mkdir(parents=True, exist_ok=True)
    EVAL_LOGS_DIR.mkdir(parents=True, exist_ok=True)
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)

    best_score = state.get("foundation_score", 0.0)
    iteration = state.get("iteration", 0)
    # ★ 断点续传：当前迭代内已完成的步骤（同迭代崩溃恢复用）
    completed_step = state.get("foundation_step")

    cfg = config
    cfg.load()

    threshold = cfg.foundation_threshold if cfg.loaded else FOUNDATION_THRESHOLD
    max_iters = cfg.max_foundation_iters if cfg.loaded else MAX_FOUNDATION_ITERS
    # ★ 步骤执行顺序（用于判断"是否已完成"）
    _STEP_ORDER = ["world", "characters", "outline_volume", "outline",
                   "outline_part2", "canon", "voice"]

    for i in range(iteration + 1, max_iters + 1):
        banner(f"基础构建 迭代 {i}/{max_iters}", "-")
        state["iteration"] = i
        # ★ 新迭代：重置步骤追踪
        # 增量改进架构中，迭代 2+ 不再无条件 from_scratch，
        # 而是基于上一轮输出 + 评估反馈做针对性改进。
        # 但同迭代断点续传逻辑仍然保留：completed_step 在迭代间重置。
        if completed_step is not None:
            state["foundation_step"] = None
            completed_step = None
            save_state(state)

        # ── 增量改进：加载上一轮输出 + 评估反馈 ──
        prev_outputs: dict[str, str] = {}
        eval_feedback: str = ""
        step_feedbacks: dict[str, str] = {}

        if i > 1:
            # 迭代 2+：尝试加载上一轮输出和评估反馈
            prev_outputs = _load_previous_outputs()
            eval_json = load_latest_foundation_eval()
            if eval_json:
                eval_feedback = extract_feedback(eval_json)
                # 按步骤提取针对性反馈
                for step_name in _STEP_ORDER:
                    step_feedbacks[step_name] = map_feedback_to_step(
                        eval_json, step_name)
                if eval_feedback:
                    step(f"已加载评估反馈（{len(eval_feedback)} 字符），"
                         f"将进行增量改进而非全量重生成")
                else:
                    step("评估反馈为空（所有维度均达标），使用 from_scratch 模式")
            else:
                step("未找到评估日志，回退到 from_scratch 模式")

        # ── 增量改进模式下跳过同迭代断点续传判断 ──
        # 增量改进时每个步骤都需要重新执行（基于 feedback），
        # 同迭代断点续传仅在迭代 1（from_scratch 模式）下生效。
        _use_resume = (i == 1)  # 只有迭代 1 才允许同迭代断点续传

        # 1. 生成世界观
        if _use_resume and completed_step and _STEP_ORDER.index("world") <= _STEP_ORDER.index(completed_step):
            step("跳过 world.md（同迭代断点续传）")
        else:
            step("生成世界观 world.md ...")
            from foundation.gen_world import generate_world
            _t0 = time.time()
            debug_log("STEP_BEGIN", f"step=gen_world")
            prev_world = prev_outputs.get("world", "")
            fb = step_feedbacks.get("world", eval_feedback)
            generate_world(previous_output=prev_world, eval_feedback=fb)
            debug_log("STEP_END", f"step=gen_world", {"elapsed_s": round(time.time() - _t0, 1)})
            state["foundation_step"] = "world"
            completed_step = "world"
            save_state(state)

        # 2. 生成角色
        if _use_resume and completed_step and _STEP_ORDER.index("characters") <= _STEP_ORDER.index(completed_step):
            step("跳过 characters.md（同迭代断点续传）")
        else:
            step("生成角色 characters.md ...")
            from foundation.gen_characters import generate_characters
            _t0 = time.time()
            debug_log("STEP_BEGIN", f"step=gen_characters")
            prev_chars = prev_outputs.get("characters", "")
            fb = step_feedbacks.get("characters", eval_feedback)
            generate_characters(previous_output=prev_chars, eval_feedback=fb)
            debug_log("STEP_END", f"step=gen_characters", {"elapsed_s": round(time.time() - _t0, 1)})
            state["foundation_step"] = "characters"
            completed_step = "characters"
            save_state(state)

        # ★ 方案 D Step 7: 2.5. 生成卷级总纲（output/outline_volume.md）
        if _use_resume and completed_step and _STEP_ORDER.index("outline_volume") <= _STEP_ORDER.index(completed_step):
            step("跳过 outline_volume.md（同迭代断点续传）")
        else:
            step("生成卷级总纲 outline_volume.md ...")
            from foundation.gen_outline_volume import generate_volume_outline
            _t0 = time.time()
            debug_log("STEP_BEGIN", f"step=gen_outline_volume")
            prev_vol = prev_outputs.get("outline_volume", "")
            fb = step_feedbacks.get("outline_volume", eval_feedback)
            generate_volume_outline(previous_output=prev_vol, eval_feedback=fb)
            debug_log("STEP_END", f"step=gen_outline_volume", {"elapsed_s": round(time.time() - _t0, 1)})
            state["foundation_step"] = "outline_volume"
            completed_step = "outline_volume"
            save_state(state)
        state["volumes_outlined"] = cfg.total_volumes if cfg.loaded else 1

        # 3. 生成大纲 (Part 1) — 逐卷章级大纲 + 合并 outline.md
        if _use_resume and completed_step and _STEP_ORDER.index("outline") <= _STEP_ORDER.index(completed_step):
            step("跳过 outline.md（同迭代断点续传）")
        else:
            step("生成大纲 outline.md (Part 1) ...")
            from foundation.gen_outline import generate_outline
            _t0 = time.time()
            debug_log("STEP_BEGIN", f"step=gen_outline")
            prev_outline = prev_outputs.get("outline", "")
            fb = step_feedbacks.get("outline", eval_feedback)
            generate_outline(previous_output=prev_outline, eval_feedback=fb)
            debug_log("STEP_END", f"step=gen_outline", {"elapsed_s": round(time.time() - _t0, 1)})
            state["foundation_step"] = "outline"
            completed_step = "outline"
            save_state(state)

        # 4. 生成大纲 (Part 2 - 伏笔)
        if _use_resume and completed_step and _STEP_ORDER.index("outline_part2") <= _STEP_ORDER.index(completed_step):
            step("跳过 outline_part2（同迭代断点续传）")
        else:
            step("生成大纲 outline.md (Part 2 - 伏笔账本) ...")
            from foundation.gen_outline_part2 import generate_outline_part2
            _t0 = time.time()
            debug_log("STEP_BEGIN", f"step=gen_outline_part2")
            prev_outline = prev_outputs.get("outline", "")
            fb = step_feedbacks.get("outline_part2", eval_feedback)
            generate_outline_part2(previous_output=prev_outline, eval_feedback=fb)
            debug_log("STEP_END", f"step=gen_outline_part2", {"elapsed_s": round(time.time() - _t0, 1)})
            state["foundation_step"] = "outline_part2"
            completed_step = "outline_part2"
            save_state(state)

        # 5. 生成正典（非关键步骤：失败时允许继续）
        if _use_resume and completed_step and _STEP_ORDER.index("canon") <= _STEP_ORDER.index(completed_step):
            step("跳过 canon.md（同迭代断点续传）")
        else:
            step("生成正典 canon.md ...")
            from foundation.gen_canon import generate_canon, count_canon_entries
            _t0 = time.time()
            debug_log("STEP_BEGIN", f"step=gen_canon")
            try:
                prev_canon = prev_outputs.get("canon", "")
                fb = step_feedbacks.get("canon", eval_feedback)
                generate_canon(previous_output=prev_canon, eval_feedback=fb)
            except Exception as e:
                step(f"⚠ 正典生成失败（非关键），跳过: {e}")
                debug_log("WARNING", f"正典生成失败: {e}", data={"step": "canon", "iteration": i})
            debug_log("STEP_END", f"step=gen_canon", {"elapsed_s": round(time.time() - _t0, 1)})
            state["foundation_step"] = "canon"
            completed_step = "canon"
            save_state(state)

        # ★ P2-11 子项 A: 验证正典规模
        canon_counts = count_canon_entries()
        canon_total = canon_counts["total"]
        canon_threshold = cfg.canon_min_entries if cfg.loaded else 400
        step(f"正典条目数: {canon_total} "
             f"(世界观{canon_counts['world']} + 角色{canon_counts['character']} "
             f"+ 时间线{canon_counts['timeline']} + 规则{canon_counts['rules']})")
        if canon_total < canon_threshold:
            step(f"⚠ 警告: 正典条目 {canon_total} < {canon_threshold}，"
                 f"信息密度不足，将在评估中体现")
            if canon_total < canon_threshold // 2:
                step("正典严重不足，后续迭代将使用更大 token 预算重试…")

        # 6. 生成文风指纹（非关键步骤：失败时允许继续）
        if _use_resume and completed_step and _STEP_ORDER.index("voice") <= _STEP_ORDER.index(completed_step):
            step("跳过 voice.md（同迭代断点续传）")
        else:
            step("生成文风指纹 voice.md Part 2 ...")
            from foundation.gen_voice import generate_voice
            _t0 = time.time()
            debug_log("STEP_BEGIN", f"step=gen_voice")
            try:
                prev_voice = prev_outputs.get("voice", "")
                fb = step_feedbacks.get("voice", eval_feedback)
                generate_voice(previous_output=prev_voice, eval_feedback=fb)
            except Exception as e:
                step(f"⚠ 文风指纹生成失败（非关键），跳过: {e}")
                debug_log("WARNING", f"文风指纹生成失败: {e}", data={"step": "voice", "iteration": i})
            debug_log("STEP_END", f"step=gen_voice", {"elapsed_s": round(time.time() - _t0, 1)})
            state["foundation_step"] = "voice"
            completed_step = "voice"
            save_state(state)

        # 7. 评估（稳定版：3次中位数，同时产出 overall + lore，零额外调用）
        step("评估基础构建 ...")
        score, lore = evaluate_foundation_stable()

        step(f"基础构建评分: {score}  (lore: {lore}, 历史最佳: {best_score})")

        # 8. 保留/丢弃（0.3 分容忍区间，避免评分波动误丢弃）
        if score >= best_score - 0.3:
            commit_hash = git_add_commit(
                f"基础构建 迭代{i}: 评分 {score} (lore {lore})"
            )
            log_result(commit_hash, "foundation", score, 0, "keep",
                       f"迭代 {i}: 评分提升 {best_score} -> {score}")
            best_score = score
            state["foundation_score"] = score
            state["lore_score"] = lore
            state["canon_entry_count"] = canon_total  # ★ P1 fix: 记录 Foundation 生成的 canon 条目数
            save_state(state)
            # ★ 日志移到 best_score 更新后，记录新值
            debug_log("FOUNDATION_SCORE",
                      data={"score": score, "lore": lore, "iteration": i,
                            "best_score": best_score, "threshold": threshold})
        else:
            step(f"评分未提升 ({score} <= {best_score})，丢弃")
            git_reset_hard("HEAD")
            log_result("discarded", "foundation", score, 0, "discard",
                       f"迭代 {i}: 未提升 ({score} <= {best_score})")
            debug_log("FOUNDATION_SCORE",
                      data={"score": score, "lore": lore, "iteration": i,
                            "best_score": best_score, "threshold": threshold,
                            "action": "discard"})

        # 9. 检查退出条件
        if best_score >= threshold:
            step(f"基础构建评分 {best_score} >= {threshold} — 通过！")
            break
    else:
        step(f"警告: 达到最大迭代次数 ({max_iters})，当前最佳评分 {best_score}")

    # 确定总章节数
    total = get_total_chapters(state)
    state["chapters_total"] = total
    state["phase"] = "drafting"
    state["current_focus"] = "chapter_drafting"
    save_state(state)

    banner(f"基础构建完成 — 评分 {best_score}, 计划 {total} 章")
    return state


# ============================================================================
# Phase 2 — Drafting (草拟)
# ============================================================================

def run_drafting(state: dict) -> dict:
    banner("PHASE 2: DRAFTING (草拟)", "=")

    total = get_total_chapters(state)
    start_chapter = state.get("chapters_drafted", 0) + 1

    CHAPTERS_DIR.mkdir(parents=True, exist_ok=True)

    cfg = config
    cfg.load()
    threshold = cfg.chapter_threshold if cfg.loaded else CHAPTER_THRESHOLD
    max_attempts = cfg.max_chapter_attempts if cfg.loaded else MAX_CHAPTER_ATTEMPTS
    for ch in range(start_chapter, total + 1):
        banner(f"起草 第 {ch}/{total} 章", "-")
        drafted = False

        from drafting.draft_chapter import draft_chapter
        from evaluation.evaluate import evaluate_chapter

        for attempt in range(1, max_attempts + 1):
            step(f"起草 第 {ch}/{total} 章 — 尝试 {attempt}/{max_attempts}")

            # 起草
            try:
                draft_chapter(ch)
            except Exception as e:
                step(f"起草失败: {e}，重试...")
                continue

            # 检查文件
            ch_file = CHAPTERS_DIR / f"ch_{ch:02d}.md"
            if not ch_file.exists() or ch_file.stat().st_size < 100:
                step("章节文件缺失或过短，重试...")
                continue

            word_count = len(ch_file.read_text(encoding="utf-8-sig").replace(" ", "").replace("\n", ""))
            step(f"生成 {word_count} 字")

            # 评估（带解析重试：LLM 偶发返回无效 JSON，重新调用评估而非直接崩溃）
            MAX_EVAL_PARSE_RETRIES = 5
            for eval_try in range(1, MAX_EVAL_PARSE_RETRIES + 1):
                eval_result = evaluate_chapter(ch)
                try:
                    score = parse_score(eval_result, "overall_score")
                    break  # 解析成功
                except ValueError:
                    if eval_try < MAX_EVAL_PARSE_RETRIES:
                        step(f"评估 JSON 解析失败 (尝试 {eval_try}/{MAX_EVAL_PARSE_RETRIES})，重试评估...")
                        continue
                    else:
                        step(f"⚠ 评估解析全部 {MAX_EVAL_PARSE_RETRIES} 次失败，使用阈值分 {threshold} 兜底")
                        score = threshold

            # ★ P2-11 子项 B: slop_penalty 参与决策
            from evaluation.evaluate import get_last_slop_penalty
            slop_penalty = get_last_slop_penalty(ch)
            slop_threshold = cfg.slop_penalty_threshold if cfg.loaded else 3.0
            slop_fail = slop_penalty > slop_threshold

            step(f"第 {ch} 章评分: {score}  (slop_penalty: {slop_penalty})")

            if slop_fail and score >= threshold:
                step(f"⚠ LLM 评分达标 ({score}) 但 slop_penalty 过高 "
                     f"({slop_penalty} > {slop_threshold})，触发反套话重写…")
                if ch_file.exists():
                    ch_file.unlink()
                continue

            if score >= threshold:
                commit_hash = git_add_commit(
                    f"ch{ch:02d}: 评分 {score}, {word_count}字"
                )
                log_result(commit_hash, f"ch{ch:02d}", score, word_count,
                           "keep", f"第 {ch} 章 (尝试 {attempt})")
                state["chapters_drafted"] = ch
                save_state(state)
                drafted = True
                step(f"起草 第 {ch}/{total} 章 完成 ✓ (评分 {score}, {word_count} 字)")
                debug_log("CHAPTER_DRAFTED",
                          data={"ch": ch, "score": score, "attempt": attempt,
                                "words": word_count, "total": total})

                # ── 质量门禁：文风指纹 + 结构反模式审计 ──
                # 先计算严重程度，再统一判断是否重写；
                # update_canon 只在所有门禁通过后才执行，避免从低质量章节提取事实污染正典。

                voice_severe = False
                anti_severe = False
                anti_warnings = []
                anti_warning_count = 0
                antipattern_max = cfg.antipattern_max_warnings if cfg.loaded else 4

                # Voice fingerprint 检查（每章起草后）
                try:
                    from voice_fingerprint import analyze_chapter_zh, extract_vocabulary_wells_from_voice
                    ch_path = CHAPTERS_DIR / f"ch_{ch:02d}.md"
                    vocab_wells = extract_vocabulary_wells_from_voice()
                    metrics = analyze_chapter_zh(ch_path, vocab_wells=vocab_wells)
                    # 简单检查
                    dialogue_ratio = metrics.get("dialogue_ratio", 0)
                    em_dash_per_1k = metrics.get("em_dash_per_1k", 0)
                    abstract_per_1k = metrics.get("abstract_per_1k", 0)
                    transition_per_1k = metrics.get("transition_per_1k", 0)

                    warnings = []
                    if dialogue_ratio == 0:
                        warnings.append("无对话")
                    if dialogue_ratio > 0.6:
                        warnings.append(f"对话过多 ({dialogue_ratio:.1%})")
                    if em_dash_per_1k > 5:
                        warnings.append(f"破折号密度过高 ({em_dash_per_1k:.1f}/千字)")
                    if abstract_per_1k > 30:
                        warnings.append(f"抽象名词密度过高 ({abstract_per_1k:.1f}/千字)")
                    if transition_per_1k > 15:
                        warnings.append(f"过渡词密度过高 ({transition_per_1k:.1f}/千字)")

                    # ≥3 项并发警告视为文风严重漂移
                    if len(warnings) >= 3:
                        voice_severe = True
                        step(f"⚠ 文风指纹严重警告 (第 {ch} 章): {', '.join(warnings)}")
                    elif warnings:
                        step(f"⚠ 文风指纹警告 (第 {ch} 章): {', '.join(warnings)}")
                    else:
                        step(f"文风指纹: ✓ (对话 {dialogue_ratio:.0%}, "
                             f"破折号 {em_dash_per_1k:.1f}/千字)")
                except Exception as e:
                    step(f"文风指纹跳过: {e}")

                # ★ P2-11 子项 C: 结构反模式审计
                try:
                    from evaluation.antipatterns import run_structural_audit
                    chapter_text = ch_file.read_text(encoding="utf-8-sig")
                    audit = run_structural_audit(chapter_text)
                    anti_warning_count = audit["warning_count"]
                    anti_warnings = audit["warnings"]
                    if anti_warning_count >= antipattern_max:
                        anti_severe = True
                        step(f"⚠ 结构反模式过多 ({anti_warning_count} 项 ≥ {antipattern_max})")
                        for w in anti_warnings:
                            step(f"  — {w}")
                    elif anti_warning_count > 0:
                        step(f"⚠ 结构反模式警告 ({anti_warning_count} 项):")
                        for w in anti_warnings:
                            step(f"  — {w}")
                    else:
                        step("结构反模式: ✓")
                except Exception as e:
                    step(f"结构反模式审计跳过: {e}")

                # ★ 质量门禁 1：文风 + 结构双重严重告警 → 必须重写
                if voice_severe and anti_severe:
                    step("⚠ 文风指纹与结构反模式双重大警，触发重写…")
                    if ch_file.exists():
                        ch_file.unlink()
                    # 重置 drafted 标志，下一轮 attempt 会重新起草
                    drafted = False
                    continue

                # ★ 质量门禁 2：结构反模式单项严重 → 触发重写（保留既有行为）
                if anti_severe:
                    if ch_file.exists():
                        ch_file.unlink()
                    drafted = False
                    continue

                # ── 所有质量门禁通过：更新正典 ──
                # ★ 方案 D Step 7: 增量 canon 追加
                # 每章起草通过后，从章节文本提取新设定追加到 canon.md
                # 仅在章节确认不会被重写后才执行，防止低质量事实污染正典。
                try:
                    from foundation.update_canon import update_canon_from_chapter
                    ch_text = ch_file.read_text(encoding="utf-8-sig")
                    new_count = update_canon_from_chapter(ch, ch_text)
                    if new_count > 0:
                        step(f"正典更新: +{new_count} 条新事实（第 {ch} 章）")
                        # 更新状态追踪
                        state["canon_entry_count"] = (
                            state.get("canon_entry_count", 0) + new_count
                        )
                        state["canon_last_updated_ch"] = ch
                        save_state(state)
                except Exception as e:
                    step(f"正典更新跳过: {e}")

                break
            else:
                step(f"评分 {score} < {threshold}，丢弃重试")
                log_result("discarded", f"ch{ch:02d}", score, word_count,
                           "discard", f"第 {ch} 章 尝试 {attempt}")
                # 删除坏章节
                if ch_file.exists():
                    ch_file.unlink()

        if not drafted:
            step(f"⚠ 警告: 第 {ch}/{total} 章全部 {max_attempts} 次尝试失败，保留最后结果继续")
            debug_log("CHAPTER_FAILED",
                      data={"ch": ch, "max_attempts": max_attempts,
                            "total": total, "reason": "all_attempts_exhausted"})
            ch_file = CHAPTERS_DIR / f"ch_{ch:02d}.md"
            if ch_file.exists():
                word_count = len(ch_file.read_text(encoding="utf-8-sig").replace(" ", "").replace("\n", ""))
                commit_hash = git_add_commit(
                    f"ch{ch:02d}: 尽力而为 ({max_attempts} 次重试后)"
                )
                log_result(commit_hash, f"ch{ch:02d}", "?", word_count,
                           "forced", f"第 {ch} 章: 达到最大重试次数")
                state["chapters_drafted"] = ch
                save_state(state)

    state["phase"] = "revision"
    state["current_focus"] = "full_novel"
    state["chapters_drafted"] = total
    state["revision_cycle"] = 0
    save_state(state)

    total_words = count_words_in_chapters()
    canon_total = state.get("canon_entry_count", 0)
    banner(f"草拟完成 — {total} 章, {total_words} 字, "
           f"正典条目 {canon_total} (最后更新: 第 {state.get('canon_last_updated_ch', 0)} 章)")
    return state


# ============================================================================
# Phase 3 — Revision (修订)
# ============================================================================

def _parse_panel_consensus(panel_path: Optional[Path]) -> list:
    """解析 reader_panel.json 找到共识问题。"""
    if not panel_path or not panel_path.exists():
        return []

    with open(panel_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    items = []

    for d in data.get("disagreements", []):
        items.append({
            "chapter": d.get("chapter", 0),
            "question": d.get("question", ""),
            "flagged_by": d.get("flagged_by", []),
            "count": len(d.get("flagged_by", [])),
        })

    # 也扫描 readers 的回答
    readers = data.get("readers", {})
    chapter_mentions = {}
    for reader_key, answers in readers.items():
        for question in ["momentum_loss", "cut_candidate", "worst_scene",
                         "thinnest_character", "missing_scene"]:
            answer = answers.get(question, "")
            if not isinstance(answer, str):
                continue
            # 阿拉伯数字章节号: 第1章, 第12章, 1章
            chs = re.findall(r'第?\s*(\d+)\s*章', answer)
            # 中文数字章节号回退: 第一章, 第十二章, 第一百二十三章
            cn_chs = re.findall(r'(?:第\s*)?([一二三四五六七八九十百零]+)\s*章', answer)
            for cn_str in cn_chs:
                arabic = _cn_to_arabic(cn_str)
                if arabic is not None:
                    debug_log("panel_cn_chapter", f"中文数字章节号匹配: '{cn_str}' → {arabic} (读者={reader_key}, 问题={question})")
                    chs.append(str(arabic))
            for ch_str in chs:
                ch_num = int(ch_str)
                key = (ch_num, question)
                if key not in chapter_mentions:
                    chapter_mentions[key] = {"chapter": ch_num, "question": question,
                                             "flagged_by": [], "count": 0}
                chapter_mentions[key]["flagged_by"].append(reader_key)
                chapter_mentions[key]["count"] += 1

    seen = set()
    for item in items:
        seen.add((item["chapter"], item["question"]))
    for key, item in chapter_mentions.items():
        if key not in seen:
            items.append(item)

    items.sort(key=lambda x: -x["count"])
    seen_chapters = set()
    unique = []
    for item in items:
        if item["chapter"] not in seen_chapters and item["chapter"] > 0:
            seen_chapters.add(item["chapter"])
            unique.append(item)

    return unique[:5]


def _build_fallback_brief(ch_num: int, context: str, label: str = "修订") -> str:
    """★ 构建有意义的 fallback 修订摘要，替代空占位符。

    拼接所有可用的评估/审阅/反模式数据，给 LLM 提供实质性指导。
    """
    parts = [f"# 修订摘要: 第 {ch_num} 章 — {label}\n"]
    parts.append(f"## 来源: {context}\n")

    # 1) 最新的单章评估
    try:
        from revision.gen_brief import latest_chapter_eval, load_json
        import json as _json
        ch_eval_path = latest_chapter_eval(ch_num)
        if ch_eval_path:
            ch_eval = _json.loads(ch_eval_path.read_text(encoding="utf-8-sig"))
            score = ch_eval.get("overall_score", "?")
            weakest = ch_eval.get("weakest_dimension", "")
            parts.append(f"## 最新单章评分: {score}/10\n")
            if weakest:
                parts.append(f"最弱维度: **{weakest}**\n")
            # 提取 ≤7 分的维度及其 fix
            for dk in ["voice_adherence", "beat_coverage", "character_voice",
                       "plants_seeded", "prose_quality", "continuity",
                       "canon_compliance", "engagement"]:
                dim = ch_eval.get(dk)
                if not dim or not isinstance(dim, dict):
                    continue
                ds = dim.get("score", "?")
                fix = dim.get("fix", "")
                if ds != "?" and int(ds) <= 7 and fix:
                    parts.append(f"- **{dk}** ({ds}/10): {fix}\n")
            # top_3_revisions
            for rev in ch_eval.get("top_3_revisions", [])[:3]:
                parts.append(f"- {rev}\n")
            # AI patterns
            for pat in ch_eval.get("ai_patterns_detected", [])[:3]:
                parts.append(f"- ⚠ AI模式: {pat}\n")
    except Exception:
        pass

    # 2) 最新的全文评估
    try:
        from revision.gen_brief import latest_full_eval
        full_path = latest_full_eval()
        if full_path:
            full_eval = _json.loads(full_path.read_text(encoding="utf-8-sig"))
            nscore = full_eval.get("novel_score", "?")
            tsug = full_eval.get("top_suggestion", "")
            parts.append(f"\n## 全文评估: {nscore}/10\n")
            if tsug:
                parts.append(f"首要建议: {tsug}\n")
    except Exception:
        pass

    # 3) 读者评审团共识
    try:
        panel_path = EDIT_LOGS_DIR / "reader_panel.json"
        if panel_path.exists():
            panel = _json.loads(panel_path.read_text(encoding="utf-8-sig"))
            for d in panel.get("disagreements", []):
                if d.get("chapter") == ch_num:
                    q = d.get("question", "")
                    flagged = d.get("flagged_by", [])
                    parts.append(f"\n## 评审团共识: {q} ({len(flagged)}/4 读者标记)\n")
    except Exception:
        pass

    # 4) 深度审阅
    try:
        review_jsons = sorted(EDIT_LOGS_DIR.glob("review_round*.json"))
        if review_jsons:
            latest_review = _json.loads(review_jsons[-1].read_text(encoding="utf-8-sig"))
            stars = latest_review.get("stars", 0)
            major = latest_review.get("major_items", 0)
            parts.append(f"\n## 审阅结果: {'★' * int(stars)}, {major} 严重问题\n")
            raw = latest_review.get("raw_review", "")
            # 提取提及本章的段落
            import re as _re
            ch_pat = _re.compile(rf"(?:第\s*{ch_num}\s*章|Ch\.?\s*{ch_num})")
            for para in raw.split("\n\n"):
                if ch_pat.search(para):
                    snippet = para[:400] + ("…" if len(para) > 400 else "")
                    parts.append(f"> {snippet}\n")
    except Exception:
        pass

    # 5) 章节基本统计
    try:
        ch_file = CHAPTERS_DIR / f"ch_{ch_num:02d}.md"
        if ch_file.exists():
            text = ch_file.read_text(encoding="utf-8-sig")
            wc = len(text.replace(" ", "").replace("\n", ""))
            parts.append(f"\n## 当前字数: {wc} 字\n")
    except Exception:
        pass

    # 6) 文风规则
    try:
        from revision.gen_brief import extract_voice_rules
        rules = extract_voice_rules()
        if rules:
            parts.append("\n## 文风规则\n")
            parts.append("\n".join(f"- {r}" for r in rules[:10]) + "\n")
    except Exception:
        pass

    return "\n".join(parts)


def run_revision(state: dict, max_cycles: int = MAX_REVISION_CYCLES) -> dict:
    banner("PHASE 3: REVISION (修订)", "=")

    BRIEFS_DIR.mkdir(parents=True, exist_ok=True)
    EDIT_LOGS_DIR.mkdir(parents=True, exist_ok=True)
    EVAL_LOGS_DIR.mkdir(parents=True, exist_ok=True)

    prev_score = state.get("novel_score", 0.0)
    start_cycle = state.get("revision_cycle", 0) + 1
    max_cycles = min(max_cycles, MAX_REVISION_CYCLES)

    cfg = config
    cfg.load()
    plateau_delta = cfg.get("plateau_delta", PLATEAU_DELTA) if cfg.loaded else PLATEAU_DELTA
    threshold = cfg.chapter_threshold if cfg.loaded else CHAPTER_THRESHOLD
    total = get_total_chapters(state)

    from revision.adversarial_edit import run_adversarial_edit
    from revision.apply_cuts import run_apply_cuts
    from revision.reader_panel import run_reader_panel
    from revision.gen_brief import build_panel_brief, build_auto_brief
    from revision.gen_revision import revise_chapter
    from evaluation.evaluate import evaluate_chapter, evaluate_full

    for cycle in range(start_cycle, max_cycles + 1):
        banner(f"修订 循环 {cycle}/{max_cycles}", "-")
        debug_log("REVISION_CYCLE",
                  data={"cycle": cycle, "max_cycles": max_cycles,
                        "prev_score": prev_score})

        # Step 1: 对抗性编辑（retries=3, max_total_time=None  = 自动计算）
        step("对抗性编辑全部章节 (retries=5, 总超时=自动) ...")
        run_adversarial_edit("all", retries=5, max_total_time=None)
        step("对抗性编辑全部章节 完成 ✓")

        # Step 2: 应用裁剪
        step("应用机械裁剪 (OVER_EXPLAIN, REDUNDANT) ...")
        try:
            run_apply_cuts("all", ["OVER-EXPLAIN", "REDUNDANT"], min_fat=15)
        except Exception as e:
            step(f"apply_cuts 跳过: {e}")

        # Step 3: 读者评审团（retries=3, max_total_time=None = 自动计算）
        step("运行读者评审团 (retries=5, 总超时=自动) ...")
        run_reader_panel(retries=5, max_total_time=None)
        step("读者评审团 完成 ✓")

        # Step 4: 解析共识
        panel_path = EDIT_LOGS_DIR / "reader_panel.json"
        consensus_items = _parse_panel_consensus(panel_path)

        if consensus_items:
            step(f"发现 {len(consensus_items)} 个共识问题:")
            for item in consensus_items:
                print(f"    第 {item['chapter']} 章: {item['question']} "
                      f"(标记数: {item['count']})")
        else:
            step("无显著共识问题")

        # Step 5: 针对性修订
        for idx, item in enumerate(consensus_items):
            ch_num = item["chapter"]
            question = item["question"]
            banner(f"  修订 第 {ch_num} 章 ({question}) [{idx+1}/{len(consensus_items)}]", ".")

            pre_score = evaluate_chapter_stable(ch_num)

            # 生成修订摘要（对齐原版：build_panel_brief 一步到位）
            brief_file = BRIEFS_DIR / f"ch{ch_num:02d}_cycle{cycle}_{question}.md"
            brief_text = build_panel_brief(ch_num)
            brief_file.write_text(brief_text, encoding="utf-8")

            # 执行修订（retries=5, max_total_time=None = 自动计算）
            step(f"按摘要修订第 {ch_num} 章 (retries=5, 总超时=自动) ...")
            revise_chapter(ch_num, brief_file, retries=5, max_total_time=None)

            # 评估修订后章节
            post_score = evaluate_chapter_stable(ch_num)

            ch_file = CHAPTERS_DIR / f"ch_{ch_num:02d}.md"
            word_count = len(ch_file.read_text(encoding="utf-8-sig").replace(" ", "").replace("\n", "")) if ch_file.exists() else 0

            step(f"第 {ch_num} 章: {pre_score} -> {post_score}")

            step(f"针对性修订 第 {ch_num} 章 完成 ✓ ({pre_score} -> {post_score})")
            # ★ 对齐原版：严格评分比较，无容忍区间
            if post_score >= pre_score:
                commit_hash = git_add_commit(
                    f"修订 循环{cycle}: ch{ch_num:02d} "
                    f"{question} {pre_score}->{post_score}"
                )
                log_result(commit_hash, f"rev-ch{ch_num:02d}", post_score,
                           word_count, "keep",
                           f"循环 {cycle}: {question} 改进 {pre_score}->{post_score}")
            else:
                step(f"修订使评分下降 ({post_score} < {pre_score})，回退")
                git_reset_hard("HEAD")
                log_result("reverted", f"rev-ch{ch_num:02d}", post_score,
                           word_count, "discard",
                           f"循环 {cycle}: {question} 倒退 {pre_score}->{post_score}")

        # Step 6: 全文评估（对齐原版位置：共识修订之后、平台检测之前）
        step("运行全文评估 ...")
        try:
            fe = evaluate_full(max_total_time=None)
            novel_score = parse_score(fe, "novel_score")
            if novel_score < 0:
                novel_score = parse_score(fe, "overall_score")
        except Exception:
            novel_score = prev_score

        total_words = count_words_in_chapters()
        step(f"小说评分: {novel_score}  (前次: {prev_score}, 字数: {total_words})")
        debug_log("FULL_EVAL",
                  data={"novel_score": novel_score, "prev_score": prev_score,
                        "total_words": total_words, "cycle": cycle})

        commit_hash = git_add_commit(
            f"修订 循环{cycle} 完成: novel_score {novel_score}"
        )
        log_result(commit_hash, f"revision-cycle-{cycle}", novel_score,
                   total_words, "cycle",
                   f"循环 {cycle}: novel_score {prev_score}->{novel_score}")

        state["novel_score"] = novel_score
        state["revision_cycle"] = cycle
        save_state(state)

        # Step 7: 平台期检测
        if cycle >= MIN_REVISION_CYCLES and abs(novel_score - prev_score) < plateau_delta:
            step(f"平台期检测 (delta {abs(novel_score - prev_score):.2f} "
                 f"< {plateau_delta}) — 停止修订")
            break

        prev_score = novel_score

    # =========================================================
    # Phase 3b: 审阅修订闭环（对齐原版 Opus 审阅流程）
    # =========================================================

    def _run_review_revision_loop(
        state: dict,
        max_revision_rounds: int = 4,
        retries: int = 3,
        max_total_time: int = None) -> None:
        """Phase 3b 审阅修订闭环——对齐原版：整本全文发送给裁判模型审阅。

        审阅 → 质量检查 → 从审阅报告中提取弱章 → 逐章修订 → 全局裁剪。
        不再依赖 evaluate_full() 的首尾摘要模式，改为裁判模型读了全文后直接指出弱章。
        """
        from revision.review import run_review_loop
        from revision.gen_brief import build_eval_brief, build_auto_brief, extract_voice_rules

        def _build_review_brief(ch_num: int, raw_review: str, rnd: int) -> str:
            """从审阅报告中提取指定章节的修订建议，构建 revision brief。

            搜索 raw_review 中提及「第N章」的段落，收集建议内容，
            拼接 voice 规则和当前章节统计，生成结构化修订摘要。
            """
            import re as _re
            ch_pat = _re.compile(
                rf"(?:第\s*{ch_num}\s*章|Ch\.?\s*{ch_num}|Chapter\s+{ch_num})"
            )
            relevant_paras = []
            for para in raw_review.split("\n\n"):
                if ch_pat.search(para):
                    snippet = para[:600] + ("…" if len(para) > 600 else "")
                    relevant_paras.append(snippet)

            if not relevant_paras:
                return ""  # 审阅报告未提及该章

            # 提取 voice 规则
            try:
                voice_rules = extract_voice_rules()
            except Exception:
                voice_rules = []

            # 获取当前章节统计
            ch_file = CHAPTERS_DIR / f"ch_{ch_num:02d}.md"
            wc = 0
            title = ""
            if ch_file.exists():
                ch_text = ch_file.read_text(encoding="utf-8-sig")
                wc = len(ch_text.replace(" ", "").replace("\n", ""))
                for line in ch_text.splitlines()[:3]:
                    if line.startswith("#"):
                        title = line.lstrip("# ").strip()
                        break

            parts = [
                f"# 修订摘要: 第 {ch_num} 章 — 审阅修订 (轮次 {rnd})",
                "",
                "## 【核心问题】（来自裁判模型全文审阅）",
                "",
            ]
            parts.extend(relevant_paras)
            parts.append("")
            parts.append("## 【修订项】")
            parts.append("1. 根据上述审阅意见，针对指出的具体问题逐项修改。")
            parts.append("2. 保持本章原有的事件主线、角色性格和前后衔接不变。")
            parts.append("")
            parts.append("## 【文风规则】")
            if voice_rules:
                parts.extend(f"- {r}" for r in voice_rules[:10])
            else:
                parts.append("(从 voice.md 未能提取规则)")
            parts.append("")
            parts.append("## 【字数目标】")
            parts.append(f"当前 {wc} 字，根据修订范围调整。")

            return "\n".join(parts)

        for rnd in range(1, max_revision_rounds + 1):
            banner(f"审阅修订 轮次 {rnd}/{max_revision_rounds}", "=")

            # --- Step A: 深度审阅（整本全文发送给裁判模型）---
            step("提交手稿给裁判模型深度审阅 ...")
            try:
                run_review_loop(state=None, max_rounds=1,
                                retries=retries, max_total_time=max_total_time)
            except Exception as e:
                step(f"深度审阅失败: {e}")
                break

            # --- Step B: 质量检查（对齐原版双停止条件）---
            review_jsons = sorted(EDIT_LOGS_DIR.glob("review_round*.json"))
            if not review_jsons:
                step("无审阅 JSON，跳过修订")
                break

            latest_review = json.loads(review_jsons[-1].read_text(encoding="utf-8-sig"))
            stars = latest_review.get("stars", 0) or 0
            total_items = latest_review.get("total_items", 0)
            major_items = latest_review.get("major_items", 0)
            qualified = latest_review.get("qualified_items", 0)
            weak_chapters = latest_review.get("weak_chapters", [])

            step(f"审阅结果: ★{'★' * int(stars)}, "
                 f"{total_items} 项 ({major_items} 严重, {qualified} 合格)")
            if weak_chapters:
                step(f"裁判指出弱章: {weak_chapters}")

            if stars >= 4.5 and major_items == 0:
                step("★★★★½ 且无严重问题 — 质量通过")
                break
            if stars >= 4 and total_items > 0 and qualified / max(total_items, 1) > 0.5:
                step(f"★{'★' * int(stars)} 且超半数问题已合格 — 质量通过")
                break

            # --- Step C: 从审阅报告中提取弱章并生成修订摘要 ---
            # ★ 优先使用裁判在审阅中指出的弱章（基于全文阅读）
            # ★ 回退：如审阅未指出弱章，使用 build_auto_brief()
            if not weak_chapters:
                step("审阅未指出具体弱章，回退到自动识别 ...")
                try:
                    ch_num, brief_text = build_auto_brief()
                    weak_chapters = [(ch_num, brief_text)]
                except Exception as e:
                    step(f"自动摘要生成失败: {e}，跳过本轮")
                    continue

            # --- Step D: 逐章修订审阅指出的弱章 ---
            revised_in_round = 0
            for ch_num in weak_chapters[:3]:  # 每轮最多修订 3 章
                if isinstance(ch_num, tuple):
                    ch_num, brief_text = ch_num
                else:
                    # 从审阅报告中提取该章的修订建议，生成 brief
                    raw_review = latest_review.get("raw_review", "")
                    brief_text = _build_review_brief(ch_num, raw_review, rnd)
                    if not brief_text:
                        step(f"第 {ch_num} 章: 无法从审阅报告中提取修订信息，跳过")
                        continue

                brief_file = BRIEFS_DIR / f"ch{ch_num:02d}_review_rnd{rnd}.md"
                brief_file.write_text(brief_text, encoding="utf-8")

                step(f"修订第 {ch_num} 章 ...")
                try:
                    revise_chapter(ch_num, brief_file,
                                   retries=retries, max_total_time=max_total_time)
                    git_add_commit(f"审阅修订 轮次{rnd}: 修订第 {ch_num} 章")
                    revised_in_round += 1
                except Exception as e:
                    step(f"第 {ch_num} 章修订失败: {e}")

            if revised_in_round == 0:
                step("本轮未成功修订任何章节")

            # --- Step E: 全局机械清理（每轮一次）---
            step("全局机械清理 ...")
            try:
                run_apply_cuts("all", ["OVER-EXPLAIN", "REDUNDANT"], min_fat=15)
                git_add_commit(f"审阅修订 轮次{rnd}: 机械清理")
            except Exception as e:
                step(f"apply_cuts 跳过: {e}")

            state["review_revision_round"] = rnd
            save_state(state)

        banner("审阅修订闭环 完成")

    # 执行审阅修订闭环
    try:
        _run_review_revision_loop(state, max_revision_rounds=4,
                                   retries=5, max_total_time=None)
    except Exception as e:
        step(f"审阅修订闭环跳过: {e}")

    state["phase"] = "export"
    state["current_focus"] = "export"
    save_state(state)

    banner(f"修订完成 — {state.get('revision_cycle', 0)} 循环, "
           f"小说评分 {state.get('novel_score', 0)}")
    return state


# ============================================================================
# Phase 4 — Export (导出)
# ============================================================================

def run_export(state: dict) -> dict:
    banner("PHASE 4: EXPORT (导出)", "=")

    # 1. 从章节重建大纲
    step("从章节重建大纲 outline.md ...")
    try:
        from export.build_outline import build_outline
        build_outline()
    except Exception as e:
        step(f"build_outline 跳过: {e}")

    # 2. 构建弧线摘要
    step("构建弧线摘要 arc_summary.md ...")
    try:
        from export.build_arc_summary import build_arc_summary
        build_arc_summary()
    except Exception as e:
        step(f"build_arc_summary 跳过: {e}")

    # 3. 拼接完整手稿
    step("拼接完整手稿 manuscript.md ...")
    try:
        from export.build_manuscript import build_manuscript
        build_manuscript()
    except Exception as e:
        step(f"build_manuscript 错误: {e}")

    # 4. 手稿统计
    manuscript = OUTPUT_DIR / "manuscript.md"
    if manuscript.exists():
        chapter_files = sorted(CHAPTERS_DIR.glob("ch_*.md"))
        total_words = count_words_in_chapters()
        step(f"手稿: {len(chapter_files)} 章, {total_words} 字")

    # 5. 最终提交
    commit_hash = git_add_commit("导出完成: 手稿、大纲、弧线摘要")
    total_words = count_words_in_chapters()
    log_result(commit_hash, "export", state.get("novel_score", "?"),
               total_words, "export", "最终导出")

    state["phase"] = "complete"
    state["current_focus"] = "done"
    save_state(state)

    chapter_cnt = count_chapter_files()
    banner(f"导出完成 — {chapter_cnt} 章, {total_words} 字")
    print(f"\n  📄 手稿位置: {OUTPUT_DIR / 'manuscript.md'}")
    debug_log("EXPORT_COMPLETE", data={"chapter_count": chapter_cnt, "total_words": total_words})
    return state


# ============================================================================
# 主编排器
# ============================================================================

def run_pipeline(mode: str = "from_scratch", max_cycles: Optional[int] = None):
    """
    运行完整流水线或从 state 恢复。

    Args:
        mode: 'from_scratch' | 'resume'
        max_cycles: 修订循环上限 (None 则使用默认)
    """
    if mode == "from_scratch":
        # 验证梗概存在
        cfg = config
        cfg.load()
        summary = cfg.story_summary
        if not summary:
            print("错误: 故事梗概 未配置。请先运行 novel_app.bat 完成配置。")
            sys.exit(1)

        banner("从头开始生成 — 故事梗概已就绪")
        # 保存梗概到独立文件
        story_file = OUTPUT_DIR / "story_summary.txt"
        story_file.write_text(summary, encoding="utf-8")

        # ★ 全面清理旧产物：output/ 下所有子目录和文件
        print("  清理旧产物...")
        # 清理 output/ 根目录下的旧生成文件
        output_root_files = [
            "state.json", "outline_volume.md", "outline.md",
            "canon.md", "voice.md", "world.md", "characters.md",
            "manuscript.md", "arc_summary.md", "results.tsv",
            ".config_hash", "story_summary.txt",
        ]
        for fname in output_root_files:
            p = OUTPUT_DIR / fname
            if p.exists():
                p.unlink()

        # 清理 output/ 根目录下所有残留的 .json / .tsv 文件（保留 config.json）
        for f in OUTPUT_DIR.glob("*.json"):
            if f.name == "config.json":
                continue
            f.unlink()
        for f in OUTPUT_DIR.glob("*.tsv"):
            f.unlink()

        # 清理各卷章级大纲 outline_volume{N}.md
        for f in OUTPUT_DIR.glob("outline_volume*.md"):
            f.unlink()

        # 清理 output/ 子目录：chapters, briefs, edit_logs, eval_logs, backups
        for sub in ["chapters", "briefs", "edit_logs", "eval_logs", "backups"]:
            subdir = OUTPUT_DIR / sub
            if subdir.exists() and subdir.is_dir():
                shutil.rmtree(subdir)
                print(f"  已清理 output/{sub}/")

        # 清空上次运行的调试日志
        debug_log_path = os.path.join(os.path.dirname(__file__), "logs", "debug.log")
        if os.path.exists(debug_log_path):
            os.remove(debug_log_path)
            print("  已清空旧调试日志")

        state = default_state()
        # ★ P7 fix: 将 config 中的卷/章配置传播到 state
        # default_state() 中这些字段为 0，需要从 config 同步
        state["total_volumes"] = cfg.total_volumes
        state["chapters_per_volume"] = cfg.chapters_per_volume
        state["chapters_total"] = cfg.total_chapters
        save_state(state)
        debug_log("PIPELINE_START",
                  data={"mode": mode, "total_volumes": cfg.total_volumes,
                        "total_chapters": cfg.total_chapters,
                        "chapter_word_target": cfg.chapter_word_target})
    else:
        # 恢复模式
        state = load_state()
        if state.get("phase") == "complete":
            print("流水线已完成。使用 mode=from_scratch 重新开始，"
                  "或手动编辑 state.json。")
            return

    # 确保目录存在
    CHAPTERS_DIR.mkdir(parents=True, exist_ok=True)
    BRIEFS_DIR.mkdir(parents=True, exist_ok=True)
    EDIT_LOGS_DIR.mkdir(parents=True, exist_ok=True)
    EVAL_LOGS_DIR.mkdir(parents=True, exist_ok=True)

    # 确定阶段
    current = state.get("phase", "foundation")
    try:
        start_idx = PHASE_ORDER.index(current)
    except ValueError:
        start_idx = 0
    phases = PHASE_ORDER[start_idx:]

    banner(f"[ZH] 中文长篇小说自动生成 — 阶段: {' → '.join(phases)}")
    print(f"  状态: phase={state.get('phase')}, "
          f"foundation_score={state.get('foundation_score', 0)}, "
          f"chapters={state.get('chapters_drafted', 0)}/{state.get('chapters_total', '?')}, "
          f"novel_score={state.get('novel_score', 0)}")

    start_time = datetime.now()

    # ★ P2 fix: 三级回退链 — 显式传参 → config → 硬编码常量
    cfg = config
    cfg.load()
    revision_cycles = (
        max_cycles
        or (cfg.max_revision_cycles if cfg.loaded else None)
        or MAX_REVISION_CYCLES
    )

    for phase in phases:
        phase_start = time.time()
        debug_log("PHASE_ENTER", data={"phase": phase})
        try:
            if phase == "foundation":
                state = run_foundation(state)
            elif phase == "drafting":
                state = run_drafting(state)
            elif phase == "revision":
                state = run_revision(state, max_cycles=revision_cycles)
            elif phase == "export":
                state = run_export(state)
            elapsed_s = time.time() - phase_start
            debug_log("PHASE_EXIT", data={"phase": phase, "elapsed_s": round(elapsed_s, 1), "success": True})
        except KeyboardInterrupt:
            banner("⚠ 用户中断 — 状态已保存")
            save_state(state)
            debug_log("USER_INTERRUPT", "用户按 Ctrl+C 终止",
                      data={"phase": phase})
            sys.exit(130)
        except Exception as e:
            elapsed_s = time.time() - phase_start
            debug_log("PHASE_EXIT", data={"phase": phase, "elapsed_s": round(elapsed_s, 1), "success": False, "error": str(e)[:200]})
            print(f"\n  ❌ 阶段 {phase} 致命错误: {e}")
            try:
                import traceback
                traceback.print_exc()
            except (OSError, UnicodeEncodeError):
                print(f"  [ERROR] {type(e).__name__}: {e}")
            save_state(state)
            raise

    elapsed = datetime.now() - start_time
    hours = elapsed.total_seconds() / 3600

    banner("[DONE] 流水线完成！")
    print(f"  耗时:       {hours:.1f} 小时")
    print(f"  阶段:       {state.get('phase')}")
    print(f"  基础构建:   {state.get('foundation_score', 0)}")
    print(f"  章节:       {state.get('chapters_drafted', 0)}/{state.get('chapters_total', '?')}")
    print(f"  总字数:     {count_words_in_chapters()}")
    print(f"  小说评分:   {state.get('novel_score', 0)}")
    print(f"  修订循环:   {state.get('revision_cycle', 0)}")
    print(f"\n  📄 手稿: {OUTPUT_DIR / 'manuscript.md'}")

    final_score = state.get('novel_score', 0)
    total_words = count_words_in_chapters()
    debug_log("PIPELINE_END", data={
        "elapsed_h": round(hours, 2), "final_score": final_score,
        "phase": state.get("phase"), "total_chapters": state.get("chapters_drafted", 0),
        "total_words": total_words, "revision_cycle": state.get("revision_cycle", 0),
    })


# ============================================================================
# CLI 入口
# ============================================================================

def main():
    try:
        parser = argparse.ArgumentParser(
            description="中文长篇小说自动生成器 — 流水线编排",
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""示例:
  python pipeline_orchestrator.py                        # 从头开始
  python pipeline_orchestrator.py --mode resume          # 恢复继续
  python pipeline_orchestrator.py --max-cycles 4         # 限制修订循环
  python pipeline_orchestrator.py --mode resume --max-cycles 3
""")
        parser.add_argument(
            "--mode", type=str, choices=["from_scratch", "resume"],
            default="from_scratch",
            help="生成模式: from_scratch (从头开始) / resume (继续上次)"
        )
        parser.add_argument(
            "--max-cycles", type=int, default=None,
            help=f"修订循环上限 (默认: {MAX_REVISION_CYCLES})"
        )

        args = parser.parse_args()
        run_pipeline(mode=args.mode, max_cycles=args.max_cycles)
    except KeyboardInterrupt:
        print("\n[中断] 用户手动终止")
        debug_log("USER_INTERRUPT", "用户按 Ctrl+C 终止",
                  data={"entry": "main()"})
        sys.exit(130)
    except Exception as e:
        crash_handler(e, {"phase": "unknown", "entry": "main()"})
        print(f"\n[崩溃] 未捕获异常: {type(e).__name__}: {e}")
        print("  详细信息已记录到 logs/debug.log")
        sys.exit(1)


if __name__ == "__main__":
    main()