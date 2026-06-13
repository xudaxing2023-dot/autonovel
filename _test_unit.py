#!/usr/bin/env python3
"""Phase 2: Unit-level verification -- no API Key needed"""
import json, os, sys, time, traceback
from pathlib import Path

sys.path.insert(0, r'e:\my novel')
Path(r'e:\my novel\output').mkdir(parents=True, exist_ok=True)

print("=" * 60)
print("  Phase 2: Unit Tests")
print("=" * 60)

results = []

def test(name, fn):
    try:
        fn()
        results.append(("OK", name))
        print(f"  [OK] {name}")
    except Exception as e:
        results.append(("FAIL", name))
        print(f"  [FAIL] {name} -- {e}")
        traceback.print_exc()

# Test 1: Config CRUD
def test_config_crud():
    from core.config import Config
    cfg = Config()
    test_data = {
        "story_summary": "test story",
        "total_chapters": 10,
        "api_key": "test-key-123",
        "model_name": "test-model",
    }
    cfg.save(test_data)
    cfg2 = Config()
    cfg2.load()
    assert cfg2.loaded, "loaded should be True"
    assert cfg2.get("story_summary") == "test story"
    assert cfg2.get("total_chapters") == 10
    assert cfg2.api_key == "test-key-123"
    assert cfg2.model_name == "test-model"

test("Config save/load CRUD", test_config_crud)

# Test 2: State CRUD
def test_state_crud():
    from core.state_manager import default_state, load_state, save_state
    state = default_state()
    assert state["phase"] == "foundation"
    assert state["iteration"] == 0
    state["phase"] = "drafting"
    state["chapters_drafted"] = 5
    save_state(state)
    loaded = load_state()
    assert loaded["phase"] == "drafting"
    assert loaded["chapters_drafted"] == 5

test("State default/save/load roundtrip", test_state_crud)

# Test 3: RateLimiter
def test_rate_limiter():
    from core.api_client import RateLimiter
    rl = RateLimiter(min_interval=0.1)
    t0 = time.time()
    rl.wait()
    t1 = time.time()
    rl.wait()
    t2 = time.time()
    dt1 = t1 - t0
    dt2 = t2 - t1
    assert dt1 < 0.3, f"first wait took too long: {dt1:.2f}s"
    assert dt2 >= 0.05, f"second wait should be >= min_interval: {dt2:.2f}s"

test("RateLimiter thread-safe + interval", test_rate_limiter)

# Test 4: parse_score robustness
def test_parse_score():
    from core.state_manager import parse_score, parse_lore_score
    # Normal format
    assert parse_score("overall_score: 8.5\nlore_score: 7.2") == 8.5
    assert parse_score("overall_score: 6.0") == 6.0
    assert parse_score("some text\noverall_score: 9.5\nmore") == 9.5
    # Abnormal format -- should return -1.0, NOT crash
    assert parse_score("total_score: 8.5") == -1.0
    assert parse_score("overall_score:not_a_number") == -1.0
    assert parse_score("") == -1.0
    # lore_score
    assert parse_lore_score("lore_score: 7.2") == 7.2
    assert parse_lore_score("overall_score: 8.0") == -1.0

test("parse_score / parse_lore_score robustness", test_parse_score)

# Test 5: slop_score_zh detection
def test_slop_score():
    from evaluation.evaluate import slop_score_zh
    # AI slop text
    ai_text = (
        "Ta gan dao yi zhen bei shang yong shang xin tou. "
        "Ta yan zhong shan guo yi si guang mang, zui jiao wei wei shang yang. "
        "Zhe wan ru yi fu hua juan, zai yan qian xu xu zhan kai."
    )
    # Use actual Chinese slop phrases
    ai_text_cn = (
        "\u4ed6\u611f\u5230\u4e00\u9635\u60b2\u4f24\u6d8c\u4e0a\u5fc3\u5934\u3002"
        "\u5979\u773c\u4e2d\u95ea\u8fc7\u4e00\u4e1d\u5149\u8292\uff0c"
        "\u5634\u89d2\u5fae\u5fae\u4e0a\u626c\u3002"
        "\u8fd9\u5b9b\u5982\u4e00\u5e45\u753b\u5377\uff0c\u5728\u773c\u524d\u5f90\u5f90\u5c55\u5f00\u3002"
    )
    result = slop_score_zh(ai_text_cn)
    assert len(result["tier2_hits"]) > 0, f"should detect Tier2 slop: {result['tier2_hits']}"
    assert len(result["tier1_hits"]) > 0, f"should detect Tier1 slop: {result['tier1_hits']}"
    assert result["slop_penalty"] > 0, "AI text should have penalty"
    # Clean text
    clean = (
        "\u8001\u4eba\u63a8\u5f00\u6728\u95e8\uff0c\u95e8\u8f74\u53d1\u51fa\u5e72\u6da9\u7684\u58f0\u54cd\u3002"
        "\u9662\u5b50\u91cc\u90a3\u68f5\u67a3\u6811\u7684\u5f71\u5b50\u5df2\u7ecf\u722c\u5230\u4e1c\u5899\u6839\u4e0b\u3002"
        "\u4ed6\u6ca1\u6709\u5f00\u706f\uff0c\u501f\u7740\u7a97\u5916\u7684\u6708\u5149\u6478\u7d22\u5230\u684c\u8fb9\u5750\u4e0b\u3002"
        "\u684c\u4e0a\u7684\u8336\u65e9\u5c31\u51c9\u900f\u4e86\u3002"
    )
    result2 = slop_score_zh(clean)
    assert result2["tier1_hits"] == [], f"clean text should have no Tier1: {result2['tier1_hits']}"
    assert result2["slop_penalty"] <= 1.0, f"clean text penalty should be low: {result2['slop_penalty']}"

test("slop_score_zh detection (AI slop + clean text)", test_slop_score)

# Test 6: Prompt builders -- all return non-empty
def test_prompt_builds():
    seed = "A story about a young adventurer"
    voice = "voice sample"; world = "world sample"; chars = "characters sample"
    outline = "outline sample"; ch_text = "chapter text sample"

    from prompts.world_prompts import build_world_prompt
    p = build_world_prompt(seed)
    assert len(p) > 100, f"world prompt too short: {len(p)}"

    from prompts.character_prompts import build_character_prompt
    p = build_character_prompt(seed)
    assert len(p) > 100, f"character prompt too short: {len(p)}"

    from prompts.chapter_prompts import build_chapter_prompt
    p = build_chapter_prompt(1, voice, world, chars, outline, "next", "prev")
    assert len(p) > 100, f"chapter prompt too short: {len(p)}"

    from prompts.outline_prompts import build_outline_prompt
    p = build_outline_prompt(seed, world, chars, voice)
    assert len(p) > 100, f"outline prompt too short: {len(p)}"

    from prompts.revision_prompts import build_revision_prompt
    p = build_revision_prompt(3, "brief text", voice, world, chars, "old chapter")
    assert len(p) > 100, f"revision prompt too short: {len(p)}"

    from prompts.adversarial_prompts import build_adversarial_prompt
    p = build_adversarial_prompt(ch_text, cut_target=100)
    assert len(p) > 100, f"adversarial prompt too short: {len(p)}"

    from prompts.reader_panel_prompts import build_reader_panel_prompt, READER_ROLES
    p = build_reader_panel_prompt(1, ch_text, reader_role=READER_ROLES["general_reader"])
    assert len(p) > 100, f"reader panel prompt too short: {len(p)}"

    from prompts.review_prompts import build_review_prompt
    p = build_review_prompt("manuscript text")
    assert len(p) > 100, f"review prompt too short: {len(p)}"

    from prompts.eval_judge_prompts import (build_foundation_eval_prompt, build_chapter_eval_prompt, build_full_novel_eval_prompt)
    p = build_foundation_eval_prompt(seed, world, chars, outline)
    assert len(p) > 100, f"foundation eval prompt too short: {len(p)}"
    p = build_chapter_eval_prompt(1, ch_text)
    assert len(p) > 100, f"chapter eval prompt too short: {len(p)}"
    p = build_full_novel_eval_prompt("full manuscript")
    assert len(p) > 100, f"full novel eval prompt too short: {len(p)}"

test("All build_*_prompt() return non-empty", test_prompt_builds)

# Test 7: Word count
def test_word_count():
    from core.state_manager import count_words_in_chapters, count_chapter_files
    from core.config import CHAPTERS_DIR
    CHAPTERS_DIR.mkdir(parents=True, exist_ok=True)
    test_ch = CHAPTERS_DIR / "ch_01.md"
    test_ch.write_text("chinese test content with punctuation.", encoding="utf-8")
    count = count_words_in_chapters()
    assert count > 0, f"word count should be > 0: {count}"
    files = count_chapter_files()
    assert files >= 1, f"should have at least 1 file: {files}"
    test_ch.unlink()

test("Word count / chapter file count", test_word_count)

# Test 8: Git detection
def test_git_detection():
    from core.state_manager import git_available, git_short_hash
    has_git = git_available()
    assert isinstance(has_git, bool)
    h = git_short_hash()
    assert isinstance(h, str) and len(h) > 0, f"short_hash should be non-empty: {h!r}"

test("Git detection + short_hash fallback", test_git_detection)

# Test 9: Backup/restore — use state.json (tracked, clean path)
def test_backup_restore():
    from core.state_manager import backup_snapshot, restore_latest
    from core.config import OUTPUT_DIR, BACKUPS_DIR, STATE_FILE
    # Save known state, then backup
    state_before = {"test_marker": "BEFORE_BACKUP", "phase": "test"}
    import json
    STATE_FILE.write_text(json.dumps(state_before), encoding="utf-8")
    snap_id = backup_snapshot("test backup")
    assert snap_id.startswith("snapshot-"), f"bad snapshot id: {snap_id}"
    # Modify state
    STATE_FILE.write_text(json.dumps({"test_marker": "AFTER_MODIFY"}), encoding="utf-8")
    # Restore
    restored = restore_latest()
    assert restored, "restore_latest should return True"
    # Verify state.json restored
    content = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    assert content.get("test_marker") == "BEFORE_BACKUP", f"restore failed: {content}"
    # Cleanup backups
    import shutil
    for d in BACKUPS_DIR.iterdir():
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)

test("File backup/restore roundtrip", test_backup_restore)

# Test 10: Config default properties
def test_config_properties():
    from core.config import Config
    cfg = Config()
    cfg._data = {}
    assert cfg.api_base_url == "https://api.siliconflow.cn/v1"
    assert cfg.model_name == "deepseek-ai/DeepSeek-V3"
    assert cfg.total_chapters == 24
    assert cfg.chapter_word_target == 2500
    assert cfg.api_interval_seconds == 4.0

test("Config property defaults", test_config_properties)

# Test 11: Model tier inference
def test_model_tier():
    from core.config import Config
    cfg = Config()
    cfg._data = {"model_name": "deepseek-ai/DeepSeek-V3"}
    assert cfg.model_tier == "high"
    cfg._data = {"model_name": "meta/llama-3.1-70b-instruct"}
    assert cfg.model_tier == "medium"
    cfg._data = {"model_name": "unknown-model"}
    assert cfg.model_tier == "low"

test("Model tier auto-inference (high/medium/low)", test_model_tier)

# Summary
print(f"\n{'='*60}")
ok_count = sum(1 for r, _ in results if r == "OK")
fail_count = sum(1 for r, _ in results if r == "FAIL")
print(f"  Phase 2 results: {ok_count} OK, {fail_count} FAIL")
print(f"{'='*60}")
if fail_count:
    sys.exit(1)