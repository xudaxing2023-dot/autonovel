#!/usr/bin/env python3
"""阶段 1b: 导入完整性检查 — 模拟导入全部模块，但不调用 API"""
import sys
import traceback

# 必须加入项目根目录
sys.path.insert(0, r'e:\my novel')

# 提前创建必要的目录
from pathlib import Path
Path(r'e:\my novel\output').mkdir(parents=True, exist_ok=True)

MODULES = [
    # 核心基础设施
    ("core.config", "from core.config import config, OUTPUT_DIR, ROOT_DIR"),
    ("core.api_client", "from core.api_client import call_llm, call_writer, call_judge, get_rate_limiter"),
    ("core.state_manager", "from core.state_manager import load_state, save_state, default_state, git_available, backup_snapshot, restore_latest, log_result, banner, step, parse_score, parse_lore_score"),
    
    # 主编排器
    ("pipeline_orchestrator", "from pipeline_orchestrator import run_pipeline"),
    
    # 9 个 Prompt 模块
    ("prompts.world_prompts", "from prompts.world_prompts import build_world_prompt, WORLD_SYSTEM_PROMPT"),
    ("prompts.character_prompts", "from prompts.character_prompts import build_character_prompt, CHARACTER_SYSTEM_PROMPT"),
    ("prompts.chapter_prompts", "from prompts.chapter_prompts import build_chapter_prompt"),
    ("prompts.outline_prompts", "from prompts.outline_prompts import build_outline_prompt, build_outline_part2_prompt"),
    ("prompts.revision_prompts", "from prompts.revision_prompts import build_revision_prompt, REVISION_SYSTEM_PROMPT"),
    ("prompts.adversarial_prompts", "from prompts.adversarial_prompts import build_adversarial_prompt, ADVERSARIAL_SYSTEM_PROMPT"),
    ("prompts.reader_panel_prompts", "from prompts.reader_panel_prompts import READER_ROLES, build_reader_panel_prompt, READER_SYSTEM_PROMPT"),
    ("prompts.review_prompts", "from prompts.review_prompts import build_review_prompt, REVIEW_SYSTEM_PROMPT"),
    ("prompts.eval_judge_prompts", "from prompts.eval_judge_prompts import build_foundation_eval_prompt, build_chapter_eval_prompt, build_full_novel_eval_prompt, JUDGE_SYSTEM_PROMPT"),
    
    # Phase 1: Foundation
    ("foundation.gen_world", "from foundation.gen_world import generate_world"),
    ("foundation.gen_characters", "from foundation.gen_characters import generate_characters"),
    ("foundation.gen_outline", "from foundation.gen_outline import generate_outline"),
    ("foundation.gen_outline_part2", "from foundation.gen_outline_part2 import generate_outline_part2"),
    ("foundation.gen_canon", "from foundation.gen_canon import generate_canon"),
    ("foundation.gen_voice", "from foundation.gen_voice import generate_voice"),
    
    # Phase 2: Drafting
    ("drafting.draft_chapter", "from drafting.draft_chapter import draft_chapter"),
    ("drafting.run_drafts", "from drafting.run_drafts import run_drafts"),
    
    # Phase 3: Revision
    ("revision.adversarial_edit", "from revision.adversarial_edit import run_adversarial_edit"),
    ("revision.apply_cuts", "from revision.apply_cuts import run_apply_cuts"),
    ("revision.reader_panel", "from revision.reader_panel import run_reader_panel"),
    ("revision.gen_brief", "from revision.gen_brief import generate_brief"),
    ("revision.gen_revision", "from revision.gen_revision import revise_chapter"),
    ("revision.review", "from revision.review import run_review_loop"),
    ("revision.compare_chapters", "from revision.compare_chapters import compare_chapters"),
    
    # Phase 4: Export
    ("export.build_outline", "from export.build_outline import build_outline"),
    ("export.build_arc_summary", "from export.build_arc_summary import build_arc_summary"),
    ("export.build_manuscript", "from export.build_manuscript import build_manuscript"),
    
    # 评估
    ("evaluation.evaluate", "from evaluation.evaluate import evaluate_foundation, evaluate_chapter, evaluate_full, slop_score_zh"),
    
    # 启动入口
    ("novel_app", "from novel_app import main, collect_input"),
]

ok = 0
fail = 0

for module_name, import_stmt in MODULES:
    try:
        exec(import_stmt)
        print(f"  OK  {module_name}")
        ok += 1
    except Exception as e:
        print(f"  FAIL  {module_name}")
        traceback.print_exc()
        fail += 1

print(f"\n{'='*60}")
print(f"  导入检查: {ok} OK, {fail} FAIL")
print(f"{'='*60}")

if fail:
    sys.exit(1)