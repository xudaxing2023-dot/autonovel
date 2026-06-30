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
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# Windows 控制台 GBK 编码不支持中文，强制使用 UTF-8
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# 核心基础设施
from core.config import config, ROOT_DIR, OUTPUT_DIR, CHAPTERS_DIR, BRIEFS_DIR, EDIT_LOGS_DIR, EVAL_LOGS_DIR, STATE_FILE, BACKUPS_DIR
from core.api_client import call_llm, call_writer, call_judge, get_rate_limiter
from core.state_manager import (
    load_state, save_state, default_state,
    git_available, git_short_hash, git_add_commit, git_reset_hard,
    backup_snapshot, restore_latest,
    log_result, banner, step, parse_score, parse_lore_score,
    count_words_in_chapters, count_chapter_files, get_total_chapters,
    evaluate_chapter_stable, evaluate_foundation_stable,
)


# ============================================================================
# 常量
# ============================================================================

FOUNDATION_THRESHOLD = 7.5
CHAPTER_THRESHOLD = 6.0
MAX_FOUNDATION_ITERS = 20
MAX_CHAPTER_ATTEMPTS = 5
MIN_REVISION_CYCLES = 3
MAX_REVISION_CYCLES = 6
PLATEAU_DELTA = 0.3
PHASE_ORDER = ["foundation", "drafting", "revision", "export"]


# ============================================================================
# Phase 1 — Foundation (基础构建)
# ============================================================================

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

    # 应用模型能力等级阈值
    cfg = config
    cfg.load()
    if cfg.loaded:
        cfg.apply_model_tier_defaults()

    threshold = cfg.foundation_threshold if cfg.loaded else FOUNDATION_THRESHOLD
    max_iters = cfg.max_foundation_iters if cfg.loaded else MAX_FOUNDATION_ITERS
    max_tokens = cfg.max_tokens_per_call if cfg.loaded else 16000

    for i in range(iteration + 1, max_iters + 1):
        banner(f"基础构建 迭代 {i}/{max_iters}", "-")
        state["iteration"] = i

        # 1. 生成世界观
        step("生成世界观 world.md ...")
        from foundation.gen_world import generate_world
        generate_world(max_tokens=max_tokens)

        # 2. 生成角色
        step("生成角色 characters.md ...")
        from foundation.gen_characters import generate_characters
        generate_characters(max_tokens=max_tokens)

        # ★ 方案 D Step 7: 2.5. 生成卷级总纲（output/outline_volume.md）
        # 必须在 generate_outline() 之前，因为 generate_outline_for_volume()
        # 依赖 outline_volume.md 获取每卷的结构化约束
        step("生成卷级总纲 outline_volume.md ...")
        from foundation.gen_outline_volume import generate_volume_outline
        generate_volume_outline(max_tokens=max_tokens)

        # 3. 生成大纲 (Part 1) — 逐卷章级大纲 + 合并 outline.md
        # generate_outline() 内部调用 generate_outline_for_volume()
        # 自动读取 outline_volume.md 获取卷级约束
        step("生成大纲 outline.md (Part 1) ...")
        from foundation.gen_outline import generate_outline
        generate_outline(max_tokens=max_tokens)

        # 4. 生成大纲 (Part 2 - 伏笔)
        step("生成大纲 outline.md (Part 2 - 伏笔账本) ...")
        from foundation.gen_outline_part2 import generate_outline_part2
        generate_outline_part2(max_tokens=max_tokens)

        # 5. 生成正典
        step("生成正典 canon.md ...")
        from foundation.gen_canon import generate_canon, count_canon_entries
        generate_canon(max_tokens=max_tokens)

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

        # 6. 生成文风指纹
        step("生成文风指纹 voice.md Part 2 ...")
        from foundation.gen_voice import generate_voice
        generate_voice(max_tokens=max_tokens)

        # 7. 评估（稳定版：3次中位数，降低 LLM 评分波动）
        step("评估基础构建 ...")
        score = evaluate_foundation_stable()
        from evaluation.evaluate import evaluate_foundation
        lore = parse_lore_score(evaluate_foundation())

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
        else:
            step(f"评分未提升 ({score} <= {best_score})，丢弃")
            git_reset_hard("HEAD")
            log_result("discarded", "foundation", score, 0, "discard",
                       f"迭代 {i}: 未提升 ({score} <= {best_score})")

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
    max_tokens = cfg.max_tokens_per_call if cfg.loaded else 16000

    for ch in range(start_chapter, total + 1):
        banner(f"起草 第 {ch}/{total} 章", "-")
        drafted = False

        from drafting.draft_chapter import draft_chapter
        from evaluation.evaluate import evaluate_chapter

        for attempt in range(1, max_attempts + 1):
            step(f"起草 第 {ch}/{total} 章 — 尝试 {attempt}/{max_attempts}")

            # 起草
            try:
                draft_chapter(ch, max_tokens=max_tokens)
            except Exception as e:
                step(f"起草失败: {e}，重试...")
                continue

            # 检查文件
            ch_file = CHAPTERS_DIR / f"ch_{ch:02d}.md"
            if not ch_file.exists() or ch_file.stat().st_size < 100:
                step("章节文件缺失或过短，重试...")
                continue

            word_count = len(ch_file.read_text(encoding="utf-8").replace(" ", "").replace("\n", ""))
            step(f"生成 {word_count} 字")

            # 评估
            eval_result = evaluate_chapter(ch)
            score = parse_score(eval_result, "overall_score")

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

                    if warnings:
                        step(f"⚠ 文风指纹警告 (第 {ch} 章): {', '.join(warnings)}")
                    else:
                        step(f"文风指纹: ✓ (对话 {dialogue_ratio:.0%}, "
                             f"破折号 {em_dash_per_1k:.1f}/千字)")
                except Exception as e:
                    step(f"文风指纹跳过: {e}")

                # ★ P2-11 子项 C: 结构反模式审计
                try:
                    from evaluation.antipatterns import run_structural_audit
                    chapter_text = ch_file.read_text(encoding="utf-8")
                    audit = run_structural_audit(chapter_text)
                    antipattern_max = cfg.antipattern_max_warnings if cfg.loaded else 4
                    if audit["warning_count"] > 0:
                        if audit["warning_count"] >= antipattern_max:
                            step(f"⚠ 结构反模式过多 ({audit['warning_count']} 项 ≥ {antipattern_max})，"
                                 f"触发重写…")
                            for w in audit["warnings"]:
                                step(f"  — {w}")
                            if ch_file.exists():
                                ch_file.unlink()
                            # 重置 drafted 标志，下一轮 attempt 会重新起草
                            drafted = False
                            continue
                        else:
                            step(f"⚠ 结构反模式警告 ({audit['warning_count']} 项):")
                            for w in audit["warnings"]:
                                step(f"  — {w}")
                    else:
                        step("结构反模式: ✓")
                except Exception as e:
                    step(f"结构反模式审计跳过: {e}")

                # ★ 方案 D Step 7: 增量 canon 追加
                # 每章起草通过后，从章节文本提取新设定追加到 canon.md
                try:
                    from foundation.update_canon import update_canon_from_chapter
                    ch_text = ch_file.read_text(encoding="utf-8")
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
            ch_file = CHAPTERS_DIR / f"ch_{ch:02d}.md"
            if ch_file.exists():
                word_count = len(ch_file.read_text(encoding="utf-8").replace(" ", "").replace("\n", ""))
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
            chs = re.findall(r'第?\s*(\d+)\s*章', answer)
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
            ch_eval = _json.loads(ch_eval_path.read_text(encoding="utf-8"))
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
            full_eval = _json.loads(full_path.read_text(encoding="utf-8"))
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
            panel = _json.loads(panel_path.read_text(encoding="utf-8"))
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
            latest_review = _json.loads(review_jsons[-1].read_text(encoding="utf-8"))
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
            text = ch_file.read_text(encoding="utf-8")
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
    max_tokens = cfg.max_tokens_per_call if cfg.loaded else 16000
    total = get_total_chapters(state)

    from revision.adversarial_edit import run_adversarial_edit
    from revision.apply_cuts import run_apply_cuts
    from revision.reader_panel import run_reader_panel
    from revision.gen_brief import generate_brief, build_auto_brief
    from revision.gen_revision import revise_chapter
    from evaluation.evaluate import evaluate_chapter, evaluate_full

    for cycle in range(start_cycle, max_cycles + 1):
        banner(f"修订 循环 {cycle}/{max_cycles}", "-")

        # Step 1: 对抗性编辑（retries=2, max_total_time=1200  = 20分钟）
        step("对抗性编辑全部章节 (retries=2, 总超时=1200s) ...")
        run_adversarial_edit("all", max_tokens=max_tokens, retries=2, max_total_time=1200)
        step("对抗性编辑全部章节 完成 ✓")

        # Step 2: 应用裁剪
        step("应用机械裁剪 (OVER_EXPLAIN, REDUNDANT) ...")
        try:
            run_apply_cuts("all", ["OVER-EXPLAIN", "REDUNDANT"], min_fat=15)
        except Exception as e:
            step(f"apply_cuts 跳过: {e}")

        # Step 3: 读者评审团（retries=2, max_total_time=600 = 10分钟）
        step("运行读者评审团 (retries=2, 总超时=600s) ...")
        run_reader_panel(max_tokens=max_tokens, retries=2, max_total_time=600)
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

            # 生成修订摘要（retries=2, max_total_time=1200 = 20分钟）
            brief_file = BRIEFS_DIR / f"ch{ch_num:02d}_cycle{cycle}_{question}.md"
            try:
                generate_brief(ch_num, panel_data=panel_path, output_path=brief_file, retries=2, max_total_time=1200)
                # ★ 检测空壳摘要：panel 数据逐薄时 build_panel_brief 生成无操作内容的占位符
                if brief_file.exists():
                    brief_text = brief_file.read_text(encoding="utf-8")
                    if len(brief_text) < 500 or "未给出具体修订建议" in brief_text:
                        raise ValueError("面板摘要内容不足，回退多源摘要")
            except Exception:
                # ★ 使用多源 fallback 摘要（eval + panel + review + cuts + voice）
                brief_content = _build_fallback_brief(
                    ch_num,
                    f"共识修订 循环{cycle}: {question}",
                    label=f"共识修订 ({question})"
                )
                brief_file.write_text(brief_content, encoding="utf-8")

            if not brief_file.exists():
                step(f"无摘要文件，跳过第 {ch_num} 章")
                continue

            # 执行修订（retries=2, max_total_time=1200 = 20分钟）
            step(f"按摘要修订第 {ch_num} 章 (retries=2, 总超时=1200s) ...")
            revise_chapter(ch_num, brief_file, max_tokens=max_tokens, retries=2, max_total_time=1200)

            # 评估修订后章节
            post_score = evaluate_chapter_stable(ch_num)

            ch_file = CHAPTERS_DIR / f"ch_{ch_num:02d}.md"
            word_count = len(ch_file.read_text(encoding="utf-8").replace(" ", "").replace("\n", "")) if ch_file.exists() else 0

            step(f"第 {ch_num} 章: {pre_score} -> {post_score}")

            step(f"针对性修订 第 {ch_num} 章 完成 ✓ ({pre_score} -> {post_score})")
            if post_score >= pre_score - 0.5:
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

        # ★ 方案 D Step 8: 采样评估 + 跨卷一致性审阅（替代 Elo 锦标赛）
        # ——— 嵌套函数：采样评估 ———
        def _sample_evaluate_volumes(
            total_ch: int,
            ch_per_vol: int,
            total_vol: int,
            threshold: float,
            sample_size: int = 5,
        ) -> list:
            """每卷随机采样章节做全文评估，返回评分低于阈值的弱章列表。

            从每卷中随机选至多 sample_size 章，调用 evaluate_chapter()（原函数），
            收集所有评分 < threshold 的章节，按评分升序返回至多 10 章。
            """
            weak_chapters: list[tuple[int, float]] = []

            for vol in range(1, total_vol + 1):
                start_ch = (vol - 1) * ch_per_vol + 1
                end_ch = min(vol * ch_per_vol, total_ch)
                population = list(range(start_ch, end_ch + 1))
                sample = random.sample(
                    population,
                    min(sample_size, len(population)),
                )

                for ch in sample:
                    try:
                        eval_result = evaluate_chapter(ch, retries=2, max_total_time=600)
                        score = parse_score(eval_result, "overall_score")
                        step(f"  采样评估 第 {ch} 章 (卷 {vol}): {score}")
                        if score < threshold:
                            weak_chapters.append((ch, score))
                    except Exception as e:
                        step(f"  采样评估 第 {ch} 章 跳过: {e}")

            # 按评分升序，取前 10
            weak_chapters.sort(key=lambda x: x[1])
            return [ch for ch, _ in weak_chapters[:10]]

        # ——— 嵌套函数：跨卷一致性审阅 ———
        def _cross_volume_consistency_review(
            total_ch: int,
            ch_per_vol: int,
            total_vol: int,
        ) -> list[int]:
            """用大上下文模型检查卷间连接点的连续性。

            提取每卷首尾各 3000 字，拼接 canon 前 5000 字作为参考，
            调用 call_judge() 检测角色状态/伏笔/设定的断裂点。
            返回疑似断裂的章节编号列表（去重）。
            """
            # 提取每卷边界文本
            segments: list[str] = []
            for vol in range(1, total_vol + 1):
                last_ch = vol * ch_per_vol
                first_ch_next = last_ch + 1

                # 卷 vol 终章尾部
                last_path = CHAPTERS_DIR / f"ch_{last_ch:02d}.md"
                if last_path.exists():
                    text = last_path.read_text(encoding="utf-8")
                    tail = text[-3000:] if len(text) > 3000 else text
                    segments.append(
                        f"【卷 {vol} 终章（第 {last_ch} 章）尾 3000 字】\n{tail}"
                    )

                # 卷 vol+1 首章头部（若存在）
                if first_ch_next <= total_ch:
                    next_path = CHAPTERS_DIR / f"ch_{first_ch_next:02d}.md"
                    if next_path.exists():
                        text = next_path.read_text(encoding="utf-8")
                        head = text[:3000] if len(text) > 3000 else text
                        segments.append(
                            f"【卷 {vol + 1} 首章（第 {first_ch_next} 章）头 3000 字】\n{head}"
                        )

            if len(segments) < 2:
                step("跨卷一致性审阅: 章节不足，跳过")
                return []

            # 保护：大规模卷数时截断 segments
            MAX_SEGMENTS = 10
            if len(segments) > MAX_SEGMENTS:
                step(f"跨卷审阅: 卷数过多 ({total_vol})，仅检查后 {MAX_SEGMENTS // 2} 个边界")
                segments = segments[-MAX_SEGMENTS:]

            # 加载 canon 参考
            canon_text = ""
            canon_path = OUTPUT_DIR / "canon.md"
            if canon_path.exists():
                full = canon_path.read_text(encoding="utf-8")
                canon_text = full[:5000] if len(full) > 5000 else full

            # 构建 prompt
            prompt_parts = [
                "请检查以下卷间连接点的连续性：",
                "",
                "\n\n".join(segments),
                "",
            ]
            if canon_text:
                prompt_parts.extend([
                    "【正典参考】",
                    canon_text,
                    "",
                ])
            prompt_parts.extend([
                "请检查：",
                "1. 角色状态是否一致（位置、持有物品、当前目标、情绪状态）",
                "2. 伏笔线索是否断裂（前卷末埋设 → 后卷首是否承接）",
                "3. 世界观设定是否漂移",
                "",
                "输出格式：",
                "断裂章节: [章节编号列表，用逗号分隔]",
                "如无断裂: 「无」",
            ])
            prompt = "\n".join(prompt_parts)

            try:
                result = call_judge(prompt, max_tokens=1000)
            except Exception as e:
                step(f"跨卷一致性审阅调用失败: {e}")
                return []

            # 解析章节编号
            if "无" in result and "断裂" not in result:
                step("跨卷一致性审阅: ✓ 未检测到断裂")
                return []

            chs = re.findall(r'\d+', result)
            broken = sorted(set(int(c) for c in chs if 1 <= int(c) <= total_ch))
            if broken:
                step(f"跨卷一致性审阅: ⚠ 疑似断裂章节: {broken}")
            else:
                step("跨卷一致性审阅: ✓ 未检测到断裂")
            return broken

        # ——— 执行采样评估 ———
        step("采样评估 — 每卷随机 5 章 ...")
        total_vol = cfg.total_volumes if cfg.loaded else 1
        ch_per_vol = cfg.chapters_per_volume if cfg.loaded else (
            total // max(1, total_vol)
        )
        sample_weaks = _sample_evaluate_volumes(
            total, ch_per_vol, total_vol, threshold,
        )
        if sample_weaks:
            step(f"采样弱章: {sample_weaks}")

        # ——— 执行跨卷一致性审阅（每两轮一次）———
        cross_broken: list[int] = []
        if total_vol > 1 and cycle % 2 == 0:
            step("跨卷一致性审阅 — 检查卷边界连续性 ...")
            cross_broken = _cross_volume_consistency_review(
                total, ch_per_vol, total_vol,
            )

        # ——— 合并修订队列：共识已修订 ∪ 采样弱章 ∪ 跨卷断裂章 ———
        revised_in_cycle = {item["chapter"] for item in consensus_items}
        combined_targets: dict[int, str] = {}
        for ch_num in sample_weaks:
            if ch_num not in revised_in_cycle:
                combined_targets.setdefault(ch_num, "采样弱章")
        for ch_num in cross_broken:
            combined_targets.setdefault(ch_num, "跨卷断裂")

        if combined_targets:
            step(f"合并修订队列: {len(combined_targets)} 章 — "
                 f"{list(combined_targets.keys())}")
        else:
            step("无额外修订目标")

        # ——— 逐章修订合并队列（最多 10 章）———
        for idx_ch, (ch_num, reason) in enumerate(
            sorted(combined_targets.items())[:10]
        ):
            ch_file = CHAPTERS_DIR / f"ch_{ch_num:02d}.md"
            if not ch_file.exists():
                step(f"第 {ch_num} 章不存在，跳过")
                continue

            banner(
                f"  修订 第 {ch_num} 章 ({reason}) "
                f"[{idx_ch + 1}/{min(len(combined_targets), 10)}]",
                ".",
            )

            # 修订前评估
            try:
                pre_score = evaluate_chapter_stable(ch_num)
            except Exception:
                pre_score = 0

            step(f"第 {ch_num} 章 修订前评分: {pre_score}")

            # 生成修订摘要（--auto 模式，三源交叉引用）
            brief_file = BRIEFS_DIR / f"ch{ch_num:02d}_sample_cycle{cycle}.md"
            try:
                ch, brief_text = build_auto_brief()
                if ch is None:
                    ch = ch_num
                brief_file.write_text(brief_text, encoding="utf-8")
                if not brief_text.strip():
                    raise ValueError("空摘要")
            except Exception:
                # ★ 使用有意义的 fallback 摘要
                brief_content = _build_fallback_brief(
                    ch_num,
                    f"{reason}（循环 {cycle}）",
                    label=f"采样修订 ({reason})"
                )
                brief_file.write_text(brief_content, encoding="utf-8")

            # 执行修订
            step(
                f"按摘要修订第 {ch_num} 章 "
                f"(retries=2, 总超时=1200s) ..."
            )
            try:
                revise_chapter(
                    ch_num, brief_file, max_tokens=max_tokens,
                    retries=2, max_total_time=1200,
                )
            except Exception as e:
                step(f"修订第 {ch_num} 章失败: {e}")
                continue

            # 修订后评估
            try:
                post_score = evaluate_chapter_stable(ch_num)
            except Exception:
                post_score = 0

            word_count = (
                len(ch_file.read_text(encoding="utf-8")
                     .replace(" ", "").replace("\n", ""))
            )

            step(f"第 {ch_num} 章: {pre_score} -> {post_score}")

            # 提交或回退
            if post_score >= pre_score - 0.5:
                commit_hash = git_add_commit(
                    f"修订 循环{cycle}: ch{ch_num:02d} "
                    f"({reason}) {pre_score}->{post_score}"
                )
                log_result(
                    commit_hash, f"rev-ch{ch_num:02d}", post_score,
                    word_count, "keep",
                    f"循环 {cycle}: {reason} 改进 {pre_score}->{post_score}",
                )
                step(
                    f"修订 第 {ch_num} 章 完成 ✓ "
                    f"({pre_score} -> {post_score})"
                )
            else:
                step(f"修订使评分下降 ({post_score} < {pre_score})，回退")
                git_reset_hard("HEAD")
                log_result(
                    "reverted", f"rev-ch{ch_num:02d}", post_score,
                    word_count, "discard",
                    f"循环 {cycle}: {reason} 倒退 {pre_score}->{post_score}",
                )

        # Step 6: 全文评估（2次取中位数，降低 LLM 评分波动）
        step("运行全文评估 (总超时=600s, 2次取中位数) ...")
        full_scores: list[float] = []
        for _ in range(2):
            try:
                fe = evaluate_full(max_total_time=600)
                ns = parse_score(fe, "novel_score")
                if ns < 0:
                    ns = parse_score(fe, "overall_score")
                if ns >= 0:
                    full_scores.append(ns)
            except Exception:
                pass
        novel_score = sorted(full_scores)[len(full_scores) // 2] if full_scores else 0.0

        total_words = count_words_in_chapters()
        step(f"小说评分: {novel_score}  (前次: {prev_score}, 字数: {total_words})")

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
    # Phase 3b: 审阅修订闭环
    # =========================================================

    def _parse_review_weak_chapters() -> list:
        """解析深度审阅 JSON，提取被指出的弱章节编号列表。

        从 EDIT_LOGS_DIR/review_round*.json 中读取审阅报告，
        在负面上下文（问题/弱点/严重/MAJOR 等关键词 ±200 字窗口）中
        匹配章节引用，按引用频次降序返回最多5个弱章节编号。
        若无明确章节引用，返回中段 1/3~2/3 章节作为兜底。
        """
        import re
        review_jsons = sorted(EDIT_LOGS_DIR.glob("review_round*.json"))
        if not review_jsons:
            return []

        chapter_hits: dict[int, int] = {}
        negative_keywords = [
            "问题", "弱点", "严重", "必须", "MAJOR", "薄弱", "不足", "缺乏",
            "需改进", "需重写", "拖沓", "断裂", "不连贯", "最差", "最低",
            "weak", "flaw", "poor", "worst", "problem", "fail", "thin",
        ]

        for rj in review_jsons:
            try:
                data = json.loads(rj.read_text(encoding="utf-8"))
                raw = data.get("raw_review", "")
            except Exception:
                continue

            for ch_match in re.finditer(
                r'(?:第|Ch\.?|Chapter\s?)\s*(\d+)\s*(?:章|节|段)',
                raw, re.IGNORECASE,
            ):
                ch_num = int(ch_match.group(1))
                # ★ BUG-2 fix: 过滤超出范围的章节编号
                if not (1 <= ch_num <= total):
                    continue
                start = max(0, ch_match.start() - 200)
                context = raw[start:ch_match.start() + 200]
                if any(kw in context for kw in negative_keywords):
                    chapter_hits[ch_num] = chapter_hits.get(ch_num, 0) + 1

        if not chapter_hits:
            # 兜底: 无明确章节引用时，取全文中段 1/3~2/3 章节
            chapter_files = sorted(CHAPTERS_DIR.glob("ch_*.md"))
            total = len(chapter_files)
            if total >= 6:
                mid_start = total // 3
                mid_end = 2 * total // 3
                fallback = list(range(mid_start + 1, mid_end + 1))
                return fallback[:5]
            return []

        # 按引用频次降序，取前5
        sorted_chs = sorted(chapter_hits.items(), key=lambda x: -x[1])
        return [ch for ch, _ in sorted_chs[:5]]

    def _run_review_revision_loop(
        state: dict,
        max_tokens: int,
        max_revision_rounds: int = 3,
        retries: int = 2,
        max_total_time: int = 1200,
    ) -> None:
        """Phase 3b 审阅修订闭环。

        审阅 → 解析弱章节 → auto brief → 修订 → 评估 → commit/回退
        → apply_cuts → 循环至质量通过或达到上限。
        """
        from revision.review import run_review_loop
        from revision.gen_brief import build_auto_brief

        for rnd in range(1, max_revision_rounds + 1):
            banner(f"审阅修订 轮次 {rnd}/{max_revision_rounds}", "=")

            # --- Step A: 深度审阅 ---
            step("提交手稿给裁判模型深度审阅 ...")
            try:
                run_review_loop(state=None, max_tokens=max_tokens, max_rounds=1,
                                retries=retries, max_total_time=max_total_time)
            except Exception as e:
                step(f"深度审阅失败: {e}")
                break

            # --- Step B: 质量检查 ---
            review_jsons = sorted(EDIT_LOGS_DIR.glob("review_round*.json"))
            if not review_jsons:
                step("无审阅 JSON，跳过修订")
                break

            latest_review = json.loads(review_jsons[-1].read_text(encoding="utf-8"))
            stars = latest_review.get("stars", 0)
            major_items = latest_review.get("major_items", 0)

            step(f"审阅结果: ★{'★' * int(stars)}, {major_items} 严重问题")

            if stars >= 4.5 and major_items == 0:
                step("★★★★½ 且无严重问题 — 质量通过，无需修订")
                break

            # --- Step C: 解析弱章节 ---
            weak_chapters = _parse_review_weak_chapters()
            if not weak_chapters:
                step("审阅未指出具体弱章节 — 跳过修订")
                break

            step(f"弱章节: {weak_chapters}")

            # --- Step D: 逐章修订 ---
            any_improved = False
            for idx_ch, ch_num in enumerate(weak_chapters):
                ch_file = CHAPTERS_DIR / f"ch_{ch_num:02d}.md"
                if not ch_file.exists():
                    step(f"第 {ch_num} 章不存在，跳过")
                    continue

                banner(
                    f"  修订 第 {ch_num} 章 [{idx_ch + 1}/{len(weak_chapters)}]",
                    ".",
                )

                # D1. 修订前评估
                try:
                    pre_score = evaluate_chapter_stable(ch_num)
                except Exception:
                    pre_score = 0

                step(f"第 {ch_num} 章 修订前评分: {pre_score}")

                # D2. 生成修订摘要（--auto 模式，三源交叉引用）
                brief_file = BRIEFS_DIR / f"ch{ch_num:02d}_review_rnd{rnd}.md"
                try:
                    ch, brief_text = build_auto_brief()
                    if ch is None:
                        ch = ch_num
                    brief_file.write_text(brief_text, encoding="utf-8")
                    if not brief_text.strip():
                        raise ValueError("空摘要")
                except Exception:
                    # ★ 使用有意义的 fallback 摘要，包含审阅发现和评估数据
                    brief_content = _build_fallback_brief(
                        ch_num,
                        f"深度审阅 轮次 {rnd}",
                        label=f"审阅修订 (轮次{rnd})"
                    )
                    brief_file.write_text(brief_content, encoding="utf-8")

                # D3. 执行修订
                step(
                    f"按摘要修订第 {ch_num} 章 "
                    f"(retries={retries}, 总超时={max_total_time}s) ..."
                )
                try:
                    revise_chapter(
                        ch_num, brief_file, max_tokens=max_tokens,
                        retries=retries, max_total_time=max_total_time,
                    )
                except Exception as e:
                    step(f"修订第 {ch_num} 章失败: {e}")
                    continue

                # D4. 修订后评估
                try:
                    post_score = evaluate_chapter_stable(ch_num)
                except Exception:
                    post_score = 0

                word_count = (
                    len(ch_file.read_text(encoding="utf-8")
                         .replace(" ", "").replace("\n", ""))
                )

                step(f"第 {ch_num} 章: {pre_score} -> {post_score}")

                # D5. 提交或回退
                if post_score >= pre_score - 0.5:
                    commit_hash = git_add_commit(
                        f"审阅修订 轮次{rnd}: ch{ch_num:02d} "
                        f"{pre_score}->{post_score}",
                    )
                    log_result(
                        commit_hash, f"review-rev-ch{ch_num:02d}", post_score,
                        word_count, "keep",
                        f"审阅修订 轮次{rnd}: ch{ch_num:02d} "
                        f"{pre_score}->{post_score}",
                    )
                    any_improved = True
                    step(f"修订 第 {ch_num} 章 完成 ✓ ({pre_score} -> {post_score})")
                else:
                    step(
                        f"修订使评分下降 ({post_score} < {pre_score})，回退"
                    )
                    git_reset_hard("HEAD")
                    log_result(
                        "reverted", f"review-rev-ch{ch_num:02d}", post_score,
                        word_count, "discard",
                        f"审阅修订 轮次{rnd}: ch{ch_num:02d} "
                        f"倒退 {pre_score}->{post_score}",
                    )

                # D6. 应用裁剪
                try:
                    run_apply_cuts(
                        str(ch_num), ["OVER-EXPLAIN", "REDUNDANT"], min_fat=15,
                    )
                except Exception as e:
                    step(f"apply_cuts 第 {ch_num} 章跳过: {e}")

            # --- Step E: 提交本轮修订 ---
            if any_improved:
                commit_hash = git_add_commit(
                    f"审阅修订 轮次{rnd} 完成: 修订 {len(weak_chapters)} 章",
                )
                log_result(
                    commit_hash, f"review-revision-round-{rnd}", 0,
                    count_words_in_chapters(), "cycle",
                    f"审阅修订 轮次{rnd}: 修订 {len(weak_chapters)} 章",
                )

            state["review_revision_round"] = rnd
            save_state(state)

        # 最终全文评估
        step("审阅修订后全文评估 ...")
        try:
            full_eval = evaluate_full(max_total_time=600)
            novel_score = parse_score(full_eval, "novel_score")
            if novel_score < 0:
                novel_score = parse_score(full_eval, "overall_score")
            step(f"最终小说评分: {novel_score}")
            state["novel_score"] = novel_score
        except Exception as e:
            step(f"全文评估失败: {e}")

        banner("审阅修订闭环 完成")

    # 执行审阅修订闭环
    try:
        _run_review_revision_loop(state, max_tokens, max_revision_rounds=3,
                                   retries=2, max_total_time=1200)
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

    banner(f"导出完成 — {count_chapter_files()} 章, {total_words} 字")
    print(f"\n  📄 手稿位置: {OUTPUT_DIR / 'manuscript.md'}")
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

        state = default_state()
        # 应用模型等级默认值
        cfg.apply_model_tier_defaults()
        # ★ P7 fix: 将 config 中的卷/章配置传播到 state
        # default_state() 中这些字段为 0，需要从 config 同步
        state["total_volumes"] = cfg.total_volumes
        state["chapters_per_volume"] = cfg.chapters_per_volume
        state["chapters_total"] = cfg.total_chapters
        save_state(state)
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
        try:
            if phase == "foundation":
                state = run_foundation(state)
            elif phase == "drafting":
                state = run_drafting(state)
            elif phase == "revision":
                state = run_revision(state, max_cycles=revision_cycles)
            elif phase == "export":
                state = run_export(state)
        except KeyboardInterrupt:
            banner("⚠ 用户中断 — 状态已保存")
            save_state(state)
            sys.exit(130)
        except Exception as e:
            print(f"\n  ❌ 阶段 {phase} 致命错误: {e}")
            import traceback
            traceback.print_exc()
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


# ============================================================================
# CLI 入口
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="中文长篇小说自动生成器 — 流水线编排",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  python pipeline_orchestrator.py                        # 从头开始
  python pipeline_orchestrator.py --mode resume          # 恢复继续
  python pipeline_orchestrator.py --max-cycles 4         # 限制修订循环
  python pipeline_orchestrator.py --mode resume --max-cycles 3
""",
    )
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


if __name__ == "__main__":
    main()