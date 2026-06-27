#!/usr/bin/env python3
"""
Stage 3 Phase 3.E2E 集成测试 — 端到端串联

Phase 1→2→3→4 完整流水线串联执行一次。
真实 API 调用 ~25-30 次。

用法:
    python tests/stage3_e2e_tests.py                  # 全部执行
    python tests/stage3_e2e_tests.py --skip-pipeline  # 跳过流水线（仅验证已有产出）
    python tests/stage3_e2e_tests.py --test 3.E2E.1   # 单项测试
"""

import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from core.config import (
    config, OUTPUT_DIR, CHAPTERS_DIR, BRIEFS_DIR,
    EDIT_LOGS_DIR, EVAL_LOGS_DIR, STATE_FILE, RESULTS_FILE,
    BACKUPS_DIR, CONFIG_FILE, ENV_FILE,
)
from core.state_manager import default_state, save_state, load_state
from core.state_manager import count_words_in_chapters, count_chapter_files

SKIP_PIPELINE = "--skip-pipeline" in sys.argv
TARGET_TEST = None
for i, arg in enumerate(sys.argv):
    if arg == "--test" and i + 1 < len(sys.argv):
        TARGET_TEST = sys.argv[i + 1]

TEST_STORY = (
    "一个年轻程序员在2049年的上海发现自己写的AI系统已经觉醒，"
    "他必须在36小时内找到并解除它，否则它将接管全球网络。"
    "悬疑科幻风格，节奏紧凑。"
)

E2E_CONFIG = {
    "story_summary": TEST_STORY,
    "total_chapters": 3,
    "total_volumes": 1,
    "chapters_per_volume": 3,
    "max_foundation_iters": 1,
    "max_revision_cycles": 1,
    "max_revision_rounds": 3,
    "foundation_threshold": 1.0,
    "chapter_threshold": 1.0,
    "revision_threshold": 1.0,
    "plateau_delta": 0.5,
    "max_chapter_attempts": 1,
}

_OUTPUT_BACKUP = ROOT / "output_backup_e2e"


def _check_api_key() -> bool:
    cfg = config
    cfg._loaded = False
    cfg.load()
    key = cfg.api_key
    if not key or key.startswith("sk-xxx") or key.startswith("'sk-xxx"):
        return False
    return True


def _backup_output():
    """备份当前 output/ 到 output_backup_e2e/。"""
    if OUTPUT_DIR.exists():
        if _OUTPUT_BACKUP.exists():
            shutil.rmtree(str(_OUTPUT_BACKUP))
        shutil.copytree(str(OUTPUT_DIR), str(_OUTPUT_BACKUP),
                        dirs_exist_ok=True)
        return True
    return False


def _restore_output():
    """恢复备份的 output/。"""
    if _OUTPUT_BACKUP.exists():
        if OUTPUT_DIR.exists():
            shutil.rmtree(str(OUTPUT_DIR))
        shutil.copytree(str(_OUTPUT_BACKUP), str(OUTPUT_DIR),
                        dirs_exist_ok=True)
        shutil.rmtree(str(_OUTPUT_BACKUP))
        return True
    return False


def _clean_output_for_e2e():
    """清空 output/ 中的生成产物，保留 config.json 结构。"""
    for d in [CHAPTERS_DIR, BRIEFS_DIR, EDIT_LOGS_DIR, EVAL_LOGS_DIR,
              BACKUPS_DIR]:
        if d.exists():
            shutil.rmtree(str(d))
        d.mkdir(parents=True, exist_ok=True)

    for fn in ["manuscript.md", "state.json", "results.tsv",
               "story_summary.txt", "arc_summary.md",
               "world.md", "characters.md", "outline.md",
               "outline_volume.md", "outline_volume1.md",
               "canon.md", "voice.md"]:
        fp = OUTPUT_DIR / fn
        if fp.exists():
            fp.unlink()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _write_e2e_config():
    """写入 E2E 测试配置。"""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(E2E_CONFIG, f, indent=2, ensure_ascii=False)


def _capture_stdout(func, *args, **kwargs):
    captured = io.StringIO()
    old = sys.stdout
    sys.stdout = captured
    try:
        result = func(*args, **kwargs)
    finally:
        sys.stdout = old
    return result, captured.getvalue()


class TestE2E(unittest.TestCase):
    """3.E2E 端到端串联测试"""

    _output: str = ""       # 3.E2E.1 的 stdout 日志
    _elapsed: float = 0.0   # 3.E2E.1 的执行耗时

    @classmethod
    def setUpClass(cls):
        _backup_output()
        print(f"  📋 output/ 已备份")

    @classmethod
    def tearDownClass(cls):
        _restore_output()
        print(f"  ✅ output/ 已恢复")

    # ——— 3.E2E.1 —————————————————————
    def test_3_e2e_1_full_pipeline(self):
        """3.E2E.1 完整 3 章 from_scratch 流水线"""
        if TARGET_TEST and TARGET_TEST not in ("3.E2E.1", "3.E2E"):
            raise unittest.SkipTest(f"--test={TARGET_TEST}")

        if SKIP_PIPELINE:
            raise unittest.SkipTest("--skip-pipeline")

        if not _check_api_key():
            self.skipTest("API Key 无效")

        # 前置
        _clean_output_for_e2e()
        _write_e2e_config()
        save_state(default_state())

        # 执行
        start = time.time()
        result = subprocess.run(
            [sys.executable, str(ROOT / "pipeline_orchestrator.py"),
             "--mode", "from_scratch"],
            cwd=str(ROOT),
            capture_output=True, text=True, timeout=1800,
        )
        elapsed = time.time() - start
        TestE2E._output = result.stdout + "\n" + result.stderr
        TestE2E._elapsed = elapsed

        results = []

        # (A) 退出码
        rc = result.returncode
        results.append(("exit_code", rc == 0,
                        f"exit={rc} ({elapsed/60:.1f}min)"))

        # (B) Foundation
        for fname, min_b in [("world.md", 100), ("characters.md", 100),
                             ("outline_volume.md", 100), ("outline.md", 100),
                             ("canon.md", 100), ("voice.md", 100)]:
            p = OUTPUT_DIR / fname
            ok = p.exists() and p.stat().st_size >= min_b
            results.append((f"Foundation/{fname}", ok,
                            f"{p.stat().st_size}B" if p.exists() else "MISSING"))

        # (C) Drafting
        for ch in range(1, 4):
            cp = CHAPTERS_DIR / f"ch_{ch:02d}.md"
            if cp.exists():
                text = cp.read_text(encoding="utf-8")
                chars = len(text.replace(" ", "").replace("\n", ""))
                ok = chars >= 200
                results.append((f"Drafting/ch_{ch:02d}.md", ok,
                                f"{chars} 字"))
            else:
                results.append((f"Drafting/ch_{ch:02d}.md", False, "MISSING"))

        # (D) Revision
        eval_files = sorted(EVAL_LOGS_DIR.glob("full_*.json"))
        results.append(("Revision/eval_full",
                        len(eval_files) >= 1, f"{len(eval_files)} files"))
        rp = EDIT_LOGS_DIR / "reader_panel.json"
        results.append(("Revision/reader_panel", rp.exists(),
                        "OK" if rp.exists() else "MISSING"))

        # (E) Export
        ms = OUTPUT_DIR / "manuscript.md"
        if ms.exists():
            mt = ms.read_text(encoding="utf-8")
            ms_ok = "目录" in mt and len(mt) > 500
            results.append(("Export/manuscript.md", ms_ok,
                            f"{len(mt)} chars"))
        else:
            results.append(("Export/manuscript.md", False, "MISSING"))

        arc = OUTPUT_DIR / "arc_summary.md"
        if arc.exists():
            at = arc.read_text(encoding="utf-8")
            arc_ok = "角色弧线" in at and len(at) > 100
            results.append(("Export/arc_summary.md", arc_ok,
                            f"{len(at)} chars"))
        else:
            results.append(("Export/arc_summary.md", False, "MISSING"))

        # (F) State
        state = load_state()
        results.append(("State/phase=complete",
                        state.get("phase") == "complete",
                        f"phase={state.get('phase')}"))
        results.append(("State/chapters_drafted=3",
                        state.get("chapters_drafted") == 3,
                        f"drafted={state.get('chapters_drafted')}"))
        results.append(("State/novel_score>0",
                        state.get("novel_score", 0) > 0,
                        f"score={state.get('novel_score')}"))

        # (G) Results
        if RESULTS_FILE.exists():
            tsv = RESULTS_FILE.read_text(encoding="utf-8")
            lines = [l for l in tsv.strip().split("\n") if l.strip()]
            has_export = "export" in tsv
            results.append(("Results/tsv",
                            len(lines) >= 4 and has_export,
                            f"{len(lines)} rows, export={'Y' if has_export else 'N'}"))

        # (H) 无崩溃
        has_crash = "❌ 阶段" in TestE2E._output
        results.append(("No crash", not has_crash,
                        "CRASH" if has_crash else "clean"))

        passed = sum(1 for _, ok, _ in results if ok)
        total = len(results)
        print(f"\n  {passed}/{total} 验证通过")
        for n, ok, d in results:
            print(f"  {'✅' if ok else '❌'} {n}: {d}")

        self.assertEqual(passed, total,
                         f"{total - passed} 项未通过")

    # ——— 3.E2E.2 —————————————————————
    def test_3_e2e_2_output_integrity(self):
        """3.E2E.2 串联前后数据完整性"""
        if TARGET_TEST and TARGET_TEST not in ("3.E2E.2", "3.E2E"):
            raise unittest.SkipTest(f"--test={TARGET_TEST}")

        if SKIP_PIPELINE and not (OUTPUT_DIR / "manuscript.md").exists():
            self.skipTest("流水线未执行且无历史产出")

        self.assertTrue(CONFIG_FILE.exists(), "config.json 缺失")
        self.assertTrue((OUTPUT_DIR / "manuscript.md").exists(),
                        "manuscript.md 缺失")
        self.assertTrue((OUTPUT_DIR / "arc_summary.md").exists(),
                        "arc_summary.md 缺失")
        self.assertTrue(STATE_FILE.exists(), "state.json 缺失")

        # 子目录统计
        for name, d in [("chapters", CHAPTERS_DIR),
                        ("eval_logs", EVAL_LOGS_DIR),
                        ("edit_logs", EDIT_LOGS_DIR),
                        ("briefs", BRIEFS_DIR)]:
            count = len(list(d.glob("*"))) if d.exists() else 0
            self.assertGreater(count, 0,
                               f"{name}/ 为空，预期 ≥ 1 文件")
            print(f"  {name}/: {count} files")

    # ——— 3.E2E.3 —————————————————————
    def test_3_e2e_3_log_integrity(self):
        """3.E2E.3 流水线日志完整性"""
        if TARGET_TEST and TARGET_TEST not in ("3.E2E.3", "3.E2E"):
            raise unittest.SkipTest(f"--test={TARGET_TEST}")

        if not TestE2E._output and SKIP_PIPELINE:
            self.skipTest("流水线未执行，无日志")

        output = TestE2E._output
        self.assertIn("PHASE 1: FOUNDATION", output)
        # 注意：实际代码中 banner 为 "(草拟)" 而非计划的 "(章节起草)"
        self.assertIn("PHASE 2: DRAFTING", output)
        self.assertIn("PHASE 3: REVISION", output)
        self.assertIn("PHASE 4: EXPORT", output)
        # 实际 banner 含 "！"："[DONE] 流水线完成！"
        self.assertIn("[DONE] 流水线完成", output)
        self.assertNotIn("❌ 阶段", output)
        self.assertNotIn("Traceback (most recent call last)", output)
        print("  ✅ 4 Phase banner + [DONE] + 无崩溃")

    # ——— 3.E2E.4 —————————————————————
    def test_3_e2e_4_metrics(self):
        """3.E2E.4 字数/评分/耗时合理性"""
        if TARGET_TEST and TARGET_TEST not in ("3.E2E.4", "3.E2E"):
            raise unittest.SkipTest(f"--test={TARGET_TEST}")

        if SKIP_PIPELINE and not STATE_FILE.exists():
            self.skipTest("流水线未执行且无 state.json")

        state = load_state()
        total_words = count_words_in_chapters()

        # 字数
        self.assertGreaterEqual(total_words, 3000,
                                f"总字数 {total_words} < 3000")
        print(f"  ✅ 总字数: {total_words}")

        # 评分
        score = state.get("novel_score", 0)
        self.assertGreater(score, 0,
                           f"novel_score={score} ≤ 0")
        print(f"  ✅ novel_score: {score}")

        # foundation
        fs = state.get("foundation_score", 0)
        print(f"  ✅ foundation_score: {fs}")

        # 修订
        rc = state.get("revision_cycle", 0)
        self.assertGreaterEqual(rc, 1,
                                f"revision_cycle={rc} < 1")
        print(f"  ✅ revision_cycle: {rc}")

        # 耗时
        if TestE2E._elapsed > 0:
            self.assertLess(TestE2E._elapsed, 1800,
                            f"耗时 {TestE2E._elapsed:.0f}s > 1800s")
            print(f"  ✅ 耗时: {TestE2E._elapsed/60:.1f} min")

        # results.tsv（3 章最小配置：header + foundation/drafting/revision/export ≥ 4 行数据）
        if RESULTS_FILE.exists():
            lines = [l for l in RESULTS_FILE.read_text(
                encoding="utf-8").strip().split("\n") if l.strip()]
            self.assertGreaterEqual(len(lines), 5,
                                    f"results.tsv 行数 {len(lines)} < 5")
            print(f"  ✅ results.tsv: {len(lines)} 行")


# ============================================================
# 自定义排序
# ============================================================

def custom_test_order(tests):
    order = [
        "test_3_e2e_1_full_pipeline",
        "test_3_e2e_2_output_integrity",
        "test_3_e2e_3_log_integrity",
        "test_3_e2e_4_metrics",
    ]
    lookup = {id(t): t for t in tests}
    ordered = []
    seen = set()
    for name in order:
        for t in tests:
            if t._testMethodName == name and id(t) not in seen:
                ordered.append(t)
                seen.add(id(t))
                break
    for t in tests:
        if id(t) not in seen:
            ordered.append(t)
    return ordered


if __name__ == "__main__":
    print("=" * 70)
    print("  Stage 3 E2E 端到端串联测试")
    print("=" * 70)
    print(f"  skip-pipeline: {SKIP_PIPELINE}")
    print(f"  target: {TARGET_TEST or '全部'}")
    print(f"  .env: {ENV_FILE}")
    print("-" * 70)

    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestE2E)
    suite._tests = custom_test_order(list(suite))

    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
    result = runner.run(suite)

    passed = result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped)
    print(f"\n{'='*70}")
    print(f"  测试汇总")
    print(f"{'='*70}")
    print(f"  通过: {passed}")
    print(f"  失败: {len(result.failures)}")
    print(f"  错误: {len(result.errors)}")
    print(f"  跳过: {len(result.skipped)}")
    print(f"  总计: {result.testsRun}")
    if result.failures or result.errors:
        print(f"\n  ❌ 存在未通过的测试项")
        sys.exit(1)
    else:
        print(f"\n  ✅ 全部测试通过")
        sys.exit(0)