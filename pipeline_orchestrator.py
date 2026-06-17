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

        # 3. 生成大纲 (Part 1)
        step("生成大纲 outline.md (Part 1) ...")
        from foundation.gen_outline import generate_outline
        generate_outline(max_tokens=max_tokens)

        # 4. 生成大纲 (Part 2 - 伏笔)
        step("生成大纲 outline.md (Part 2 - 伏笔账本) ...")
        from foundation.gen_outline_part2 import generate_outline_part2
        generate_outline_part2(max_tokens=max_tokens)

        # 5. 生成正典
        step("生成正典 canon.md ...")
        from foundation.gen_canon import generate_canon
        generate_canon(max_tokens=max_tokens)

        # 6. 生成文风指纹
        step("生成文风指纹 voice.md Part 2 ...")
        from foundation.gen_voice import generate_voice
        generate_voice(max_tokens=max_tokens)

        # 7. 评估
        step("评估基础构建 ...")
        from evaluation.evaluate import evaluate_foundation
        eval_result = evaluate_foundation()
        score = parse_score(eval_result, "overall_score")
        lore = parse_lore_score(eval_result)

        step(f"基础构建评分: {score}  (lore: {lore}, 历史最佳: {best_score})")

        # 8. 保留/丢弃
        if score > best_score:
            commit_hash = git_add_commit(
                f"基础构建 迭代{i}: 评分 {score} (lore {lore})"
            )
            log_result(commit_hash, "foundation", score, 0, "keep",
                       f"迭代 {i}: 评分提升 {best_score} -> {score}")
            best_score = score
            state["foundation_score"] = score
            state["lore_score"] = lore
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
            step(f"第 {ch} 章评分: {score}")

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
    banner(f"草拟完成 — {total} 章, {total_words} 字")
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
    max_tokens = cfg.max_tokens_per_call if cfg.loaded else 16000

    from revision.adversarial_edit import run_adversarial_edit
    from revision.apply_cuts import run_apply_cuts
    from revision.reader_panel import run_reader_panel
    from revision.gen_brief import generate_brief
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

            pre_eval = evaluate_chapter(ch_num, retries=2, max_total_time=600)
            pre_score = parse_score(pre_eval, "overall_score")

            # 生成修订摘要（retries=2, max_total_time=1200 = 20分钟）
            brief_file = BRIEFS_DIR / f"ch{ch_num:02d}_cycle{cycle}_{question}.md"
            try:
                generate_brief(ch_num, panel_data=panel_path, retries=2, max_total_time=1200)
            except Exception:
                # 创建最小摘要
                brief_content = (
                    f"# 修订摘要: 第 {ch_num} 章\n\n"
                    f"## 问题: {question}\n\n"
                    f"评审团共识指出本章需要修订。\n"
                    f"焦点: 处理 {question.replace('_', ' ')} 问题。\n"
                    f"保留现有文风、角色塑造和关键节拍。\n"
                )
                brief_file.write_text(brief_content, encoding="utf-8")

            if not brief_file.exists():
                step(f"无摘要文件，跳过第 {ch_num} 章")
                continue

            # 执行修订（retries=2, max_total_time=1200 = 20分钟）
            step(f"按摘要修订第 {ch_num} 章 (retries=2, 总超时=1200s) ...")
            revise_chapter(ch_num, brief_file, max_tokens=max_tokens, retries=2, max_total_time=1200)

            # 评估修订后章节
            post_eval = evaluate_chapter(ch_num, retries=2, max_total_time=600)
            post_score = parse_score(post_eval, "overall_score")

            ch_file = CHAPTERS_DIR / f"ch_{ch_num:02d}.md"
            word_count = len(ch_file.read_text(encoding="utf-8").replace(" ", "").replace("\n", "")) if ch_file.exists() else 0

            step(f"第 {ch_num} 章: {pre_score} -> {post_score}")

            step(f"针对性修订 第 {ch_num} 章 完成 ✓ ({pre_score} -> {post_score})")
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

        # Step 6: 全文评估（max_total_time=600 = 10分钟）
        step("运行全文评估 (总超时=600s) ...")
        full_eval = evaluate_full(max_total_time=600)
        novel_score = parse_score(full_eval, "novel_score")
        if novel_score < 0:
            novel_score = parse_score(full_eval, "overall_score")

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
    # Phase 3b: 深度审阅循环
    # =========================================================
    try:
        from revision.review import run_review_loop
        run_review_loop(state, max_tokens=max_tokens, retries=2, max_total_time=1200)
    except Exception as e:
        step(f"深度审阅跳过: {e}")

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

    revision_cycles = max_cycles if max_cycles else MAX_REVISION_CYCLES

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