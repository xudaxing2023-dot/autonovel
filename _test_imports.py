#!/usr/bin/env python3
"""Test imports of the newly added functions in eval_judge_prompts.py."""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

try:
    from prompts.eval_judge_prompts import (
        JUDGE_SYSTEM_PROMPT,
        build_foundation_eval_prompt,
        build_chapter_eval_prompt,
        build_full_novel_eval_prompt,
    )
    print("JUDGE_SYSTEM_PROMPT: OK")
    print("build_foundation_eval_prompt: OK")
    print("build_chapter_eval_prompt: OK")
    print("build_full_novel_eval_prompt: OK")

    r = build_chapter_eval_prompt(1, "test chapter", "outline", "voice", "canon")
    print(f"Chapter prompt length: {len(r)} chars")

    r2 = build_full_novel_eval_prompt("test", "outline", "voice")
    print(f"Full novel prompt length: {len(r2)} chars")

    print("\nALL TESTS PASSED")
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)