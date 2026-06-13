#!/usr/bin/env python3
"""Phase 3: Integration verification —逐模块 dry-run API 调用。

Session A: Foundation 基础构建 (Tests 1-7) → 7 次 API 调用
Session B: Drafting 草拟 (Test 8) → 5 次 API 调用
Session C: Revision 修订 (Tests 9-12) → 7 次 API 调用
Session D: Export 导出 (Test 13) → 0 次 API 调用
"""
import json
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(r"e:/my novel")
sys.path.insert(0, str(ROOT))

OUTPUT = ROOT / "output"
CHAPTERS = OUTPUT / "chapters"
EDIT_LOGS = OUTPUT / "edit_logs"
BRIEFS = OUTPUT / "briefs"

results = []


def test(name, fn):
    t0 = time.time()
    try:
        fn()
        elapsed = time.time() - t0
        results.append(("OK", name, elapsed))
        print(f"  [OK] {name} ({elapsed:.1f}s)")
    except Exception as e:
        elapsed = time.time() - t0
        results.append(("FAIL", name, elapsed))
        print(f"  [FAIL] {name} ({elapsed:.1f}s) -- {e}")
        traceback.print_exc()


def check_file(path, min_bytes=100, label=""):
    """验证文件存在且达到最小字节数。"""
    p = Path(path)
    if not p.exists():
        raise AssertionError(f"{label or path} 不存在")
    size = p.stat().st_size
    if size < min_bytes:
        raise AssertionError(f"{label or path} 仅有 {size} bytes (< {min_bytes})")
    print(f"    -> {size} bytes", file=sys.stderr)


# ============================================================
# Step 0: 确保 config.json 正确 + 重置 state
# ============================================================
CFG = OUTPUT / "config.json"
CFG.parent.mkdir(parents=True, exist_ok=True)
json.dump(
    {
        "story_summary": (
            "一个年轻的程序员在2049年的上海发现自己写的AI系统已经觉醒，"
            "他必须在36小时内找到并解除它，否则它将接管全球网络。"
            "悬疑科幻风格，节奏紧凑。"
        ),
        "total_chapters": 3,
        "api_base_url": "https://api.siliconflow.cn/v1",
        "api_key": "sk-inekkeecxshmxodlufwvbygfadshfunooovpsgajltzofwmw",
        "model_name": "deepseek-ai/deepseek-v4-pro",
        "api_interval_seconds": 4,
        "mode": "from_scratch",
    },
    open(CFG, "w", encoding="utf-8"),
    indent=2,
    ensure_ascii=False,
)
print("[OK] config.json written")

from core.state_manager import default_state, save_state

save_state(default_state())
print("[OK] state.json reset to default")


# ============================================================
# Session A: Foundation (基础构建)
# ============================================================
print("\n" + "=" * 60)
print("  Session A: Foundation (基础构建)")
print("=" * 60)


# --- Test 1: gen_world ------------------------------------------------
def t1_gen_world():
    from foundation.gen_world import generate_world

    generate_world(max_tokens=4096)
    check_file(OUTPUT / "world.md", min_bytes=100, label="world.md")


test("Test 1: gen_world → world.md", t1_gen_world)


# --- Test 2: gen_characters -------------------------------------------
def t2_gen_characters():
    from foundation.gen_characters import generate_characters

    generate_characters(max_tokens=4096)
    check_file(OUTPUT / "characters.md", min_bytes=100, label="characters.md")


test("Test 2: gen_characters → characters.md", t2_gen_characters)


# --- Test 3: gen_outline ----------------------------------------------
def t3_gen_outline():
    from foundation.gen_outline import generate_outline

    generate_outline(max_tokens=4096)
    check_file(OUTPUT / "outline.md", min_bytes=200, label="outline.md")


test("Test 3: gen_outline → outline.md", t3_gen_outline)


# --- Test 4: gen_outline_part2 -----------------------------------------
def t4_gen_outline_part2():
    from foundation.gen_outline_part2 import generate_outline_part2

    generate_outline_part2(max_tokens=4096)
    outline_text = (OUTPUT / "outline.md").read_text(encoding="utf-8")
    if "伏笔" not in outline_text:
        raise AssertionError("outline.md 不包含 '伏笔' 关键字")
    print(f"    -> 伏笔账本已追加", file=sys.stderr)


test("Test 4: gen_outline_part2 → 伏笔账本", t4_gen_outline_part2)


# --- Test 5: gen_canon -------------------------------------------------
def t5_gen_canon():
    from foundation.gen_canon import generate_canon

    generate_canon(max_tokens=4096)
    check_file(OUTPUT / "canon.md", min_bytes=200, label="canon.md")


test("Test 5: gen_canon → canon.md", t5_gen_canon)


# --- Test 6: gen_voice -------------------------------------------------
def t6_gen_voice():
    from foundation.gen_voice import generate_voice

    generate_voice(max_tokens=4096)
    check_file(OUTPUT / "voice.md", min_bytes=200, label="voice.md")


test("Test 6: gen_voice → voice.md", t6_gen_voice)


# --- Test 7: evaluate_foundation ---------------------------------------
def t7_evaluate_foundation():
    from evaluation.evaluate import evaluate_foundation
    from core.state_manager import parse_score

    result = evaluate_foundation(max_tokens=4096)
    if not result or len(result) < 20:
        raise AssertionError(f"评估返回内容过短: {len(result)} chars")
    score = parse_score(result, "overall_score")
    print(f"    -> overall_score={score}", file=sys.stderr)


test("Test 7: evaluate_foundation → LLM 评分", t7_evaluate_foundation)

# ============================================================
# Session B: Drafting (草拟)
# ============================================================
print("\n" + "=" * 60)
print("  Session B: Drafting (草拟)")
print("=" * 60)


# --- Test 8: draft_chapter 1-3 + evaluate_chapter ----------------------
def t8_draft_eval():
    CHAPTERS.mkdir(parents=True, exist_ok=True)
    from drafting.draft_chapter import draft_chapter
    from evaluation.evaluate import evaluate_chapter, slop_score_zh
    from core.state_manager import parse_score

    # 第 1 章
    draft_chapter(1, max_tokens=16000)
    ch1 = CHAPTERS / "ch_01.md"
    check_file(ch1, min_bytes=500, label="ch_01.md")

    text = ch1.read_text(encoding="utf-8")
    mech = slop_score_zh(text)
    print(
        f"    -> 机械检测: Tier1={len(mech['tier1_hits'])}, "
        f"Tier2={len(mech['tier2_hits'])}, penalty={mech['slop_penalty']}",
        file=sys.stderr,
    )

    eval_result = evaluate_chapter(1, max_tokens=4096)
    score = parse_score(eval_result, "overall_score")
    print(f"    -> ch01 overall_score={score}", file=sys.stderr)

    # 第 2 章
    draft_chapter(2, max_tokens=16000)
    check_file(CHAPTERS / "ch_02.md", min_bytes=200, label="ch_02.md")
    print(f"    -> ch_02.md 已生成", file=sys.stderr)

    # 第 3 章
    draft_chapter(3, max_tokens=16000)
    check_file(CHAPTERS / "ch_03.md", min_bytes=200, label="ch_03.md")
    print(f"    -> ch_03.md 已生成", file=sys.stderr)


test("Test 8: draft_chapter 1-3 + evaluate", t8_draft_eval)

# ============================================================
# Session C: Revision (修订)
# ============================================================
print("\n" + "=" * 60)
print("  Session C: Revision (修订)")
print("=" * 60)


# --- Test 9: adversarial_edit ------------------------------------------
def t9_adversarial():
    EDIT_LOGS.mkdir(parents=True, exist_ok=True)
    from revision.adversarial_edit import run_adversarial_edit

    run_adversarial_edit(target="1", max_tokens=4096)
    cuts_file = EDIT_LOGS / "ch01_cuts.json"
    check_file(cuts_file, min_bytes=50, label="ch01_cuts.json")
    json.loads(cuts_file.read_text(encoding="utf-8"))
    print(f"    -> valid JSON", file=sys.stderr)


test("Test 9: adversarial_edit → ch01_cuts.json", t9_adversarial)


# --- Test 10: reader_panel ---------------------------------------------
def t10_reader_panel():
    EDIT_LOGS.mkdir(parents=True, exist_ok=True)
    from revision.reader_panel import run_reader_panel

    run_reader_panel(max_tokens=4096)
    panel_file = EDIT_LOGS / "reader_panel.json"
    check_file(panel_file, min_bytes=100, label="reader_panel.json")

    data = json.loads(panel_file.read_text(encoding="utf-8"))
    readers = data.get("readers", {})
    if len(readers) < 2:
        raise AssertionError(f"reader_panel 仅含 {len(readers)} 位读者 (期望 >= 2)")
    print(
        f"    -> {len(readers)} 位读者, {len(data.get('disagreements', []))} 共识问题",
        file=sys.stderr,
    )


test("Test 10: reader_panel → reader_panel.json", t10_reader_panel)


# --- Test 11: gen_brief + gen_revision ---------------------------------
def t11_brief_revision():
    BRIEFS.mkdir(parents=True, exist_ok=True)
    from revision.gen_brief import generate_brief
    from revision.gen_revision import revise_chapter

    ch1 = CHAPTERS / "ch_01.md"
    old_size = ch1.stat().st_size if ch1.exists() else 0

    panel_path = EDIT_LOGS / "reader_panel.json"
    brief_path = generate_brief(
        chapter_num=1,
        panel_data=panel_path,
        max_tokens=4096,
    )
    if brief_path is None:
        brief_path = generate_brief(chapter_num=1, max_tokens=4096)

    check_file(brief_path if brief_path else BRIEFS / "ch01_brief.md",
               min_bytes=50, label="ch01_brief.md")
    brief_path = brief_path or (BRIEFS / "ch01_brief.md")

    revise_chapter(ch_num=1, brief_file=str(brief_path), max_tokens=16000)
    new_size = ch1.stat().st_size
    print(f"    -> ch_01: {old_size} -> {new_size} bytes", file=sys.stderr)


test("Test 11: gen_brief + gen_revision → 修订 ch01", t11_brief_revision)


# --- Test 12: review (深度审阅, 1 轮) ----------------------------------
def t12_review():
    EDIT_LOGS.mkdir(parents=True, exist_ok=True)
    from revision.review import run_review_loop

    run_review_loop(state=None, max_tokens=4096, max_rounds=1)

    review_file = EDIT_LOGS / "review_round1.md"
    check_file(review_file, min_bytes=100, label="review_round1.md")

    review_text = review_file.read_text(encoding="utf-8")
    if "★" not in review_text:
        print(f"    -> 警告: 审阅报告未含 ★ 评分", file=sys.stderr)
    else:
        stars = review_text.count("★")
        print(f"    -> {stars} 颗星", file=sys.stderr)


test("Test 12: review → review_round1.md", t12_review)


# ============================================================
# Session D: Export (导出)
# ============================================================
print("\n" + "=" * 60)
print("  Session D: Export (导出)")
print("=" * 60)


# --- Test 13: build_manuscript -----------------------------------------
def t13_manuscript():
    from export.build_manuscript import build_manuscript

    build_manuscript()
    manuscript = OUTPUT / "manuscript.md"
    check_file(manuscript, min_bytes=500, label="manuscript.md")

    text = manuscript.read_text(encoding="utf-8")
    if "目录" not in text:
        raise AssertionError("manuscript.md 不包含目录")
    chapter_count = text.count("# 第 ")
    print(f"    -> {chapter_count} 章, {len(text)} chars", file=sys.stderr)


test("Test 13: build_manuscript → manuscript.md", t13_manuscript)


# ============================================================
# Summary
# ============================================================
print("\n" + "=" * 60)
print("  Phase 3 Integration Test — Results")
print("=" * 60)

total = len(results)
passed = sum(1 for r in results if r[0] == "OK")
failed = total - passed

for status, name, elapsed in results:
    mark = "✓" if status == "OK" else "✗"
    print(f"    [{mark}] {name} ({elapsed:.1f}s)")

print(f"\n  {passed}/{total} passed, {failed} failed")

if failed == 0:
    print("  🎉 阶段3集成测试全部通过！")
else:
    print(f"  ⚠ {failed} 个测试失败，请检查上述错误")

sys.exit(0 if failed == 0 else 1)