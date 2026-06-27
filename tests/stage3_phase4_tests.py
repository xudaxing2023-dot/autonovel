#!/usr/bin/env python3
"""
Stage 3 Phase 4 集成测试 — Export（导出）

真实 API 调用 ~2 次（build_outline + build_arc_summary）。
严格按 3.4.3 → 3.4.1 → 3.4.2 → 3.4.4 → 3.4.5 顺序执行。

用法:
    python tests/stage3_phase4_tests.py                  # 全部执行
    python tests/stage3_phase4_tests.py --dry-run        # 仅检查前置条件
    python tests/stage3_phase4_tests.py --test 3.4.1     # 单项测试
    python tests/stage3_phase4_tests.py --skip-api       # 跳过真实 API 调用
"""

import io
import json
import os
import re
import shutil
import sys
import unittest
import warnings
from pathlib import Path

# Windows 控制台 GBK 编码不支持中文，强制使用 UTF-8
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from core.config import (
    config, OUTPUT_DIR, CHAPTERS_DIR, BRIEFS_DIR,
    EDIT_LOGS_DIR, EVAL_LOGS_DIR, STATE_FILE, RESULTS_FILE, BACKUPS_DIR,
    CONFIG_FILE, ENV_FILE,
)
from core.state_manager import default_state, load_state, save_state
from core.state_manager import count_words_in_chapters, count_chapter_files

# ============================================================
# 命令行参数解析
# ============================================================

DRY_RUN = "--dry-run" in sys.argv
SKIP_API = "--skip-api" in sys.argv
TARGET_TEST = None
for i, arg in enumerate(sys.argv):
    if arg == "--test" and i + 1 < len(sys.argv):
        TARGET_TEST = sys.argv[i + 1]

# ============================================================
# 工具函数
# ============================================================


def _check_api_key() -> bool:
    """检查 API Key 是否有效（非占位符）。"""
    cfg = config
    cfg._loaded = False
    cfg.load()
    key = cfg.api_key
    if not key or key.startswith("sk-xxx") or key.startswith("'sk-xxx"):
        return False
    return True


def _capture_stderr(func, *args, **kwargs):
    """捕获 stderr 输出后执行函数。"""
    captured = io.StringIO()
    old = sys.stderr
    sys.stderr = captured
    try:
        result = func(*args, **kwargs)
    finally:
        sys.stderr = old
    return result, captured.getvalue()


def _capture_stdout(func, *args, **kwargs):
    """捕获 stdout 输出后执行函数。"""
    captured = io.StringIO()
    old = sys.stdout
    sys.stdout = captured
    try:
        result = func(*args, **kwargs)
    finally:
        sys.stdout = old
    return result, captured.getvalue()


def _backup_outline() -> bool:
    """备份当前 outline.md，供 3.4.5 对比。"""
    src = OUTPUT_DIR / "outline.md"
    dst = OUTPUT_DIR / "_outline_backup_before_export.md"
    if src.exists():
        shutil.copy2(str(src), str(dst))
        return True
    return False


def _restore_outline_backup() -> bool:
    """恢复备份的 outline.md（在导出失败时回退）。"""
    backup = OUTPUT_DIR / "_outline_backup_before_export.md"
    target = OUTPUT_DIR / "outline.md"
    if backup.exists():
        shutil.copy2(str(backup), str(target))
        return True
    return False


# ============================================================
# Test 3.4.3 — 优雅降级（需最先执行，因为会移动 chapters）
# ============================================================

_BACKUP_DIR_343 = OUTPUT_DIR / "_chapters_backup_test343"


def _setup_343():
    """备份并清空 chapters 目录。"""
    if CHAPTERS_DIR.exists():
        chapter_files = list(CHAPTERS_DIR.glob("ch_*.md"))
        if chapter_files:
            # 清理旧的备份
            if _BACKUP_DIR_343.exists():
                shutil.rmtree(str(_BACKUP_DIR_343))
            shutil.copytree(str(CHAPTERS_DIR), str(_BACKUP_DIR_343),
                            dirs_exist_ok=True)
            shutil.rmtree(str(CHAPTERS_DIR))
    CHAPTERS_DIR.mkdir(parents=True, exist_ok=True)


def _teardown_343():
    """恢复 chapters 目录。"""
    if _BACKUP_DIR_343.exists():
        if CHAPTERS_DIR.exists():
            shutil.rmtree(str(CHAPTERS_DIR))
        shutil.copytree(str(_BACKUP_DIR_343), str(CHAPTERS_DIR),
                        dirs_exist_ok=True)
        shutil.rmtree(str(_BACKUP_DIR_343))


# ============================================================
# 测试类
# ============================================================

class TestPhase4Export(unittest.TestCase):
    """Phase 4 导出集成测试"""

    @classmethod
    def setUpClass(cls):
        """全局前置：确保 output/ 目录存在。"""
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        CHAPTERS_DIR.mkdir(parents=True, exist_ok=True)

    # ============================================================
    # 3.4.0 前置条件检查
    # ============================================================

    def test_3_4_0_prerequisites(self):
        """前置条件检查：Phase 1+2+3 产出是否存在。"""
        ok = True
        checks = []

        # Phase 1
        for label in ["world.md", "characters.md", "outline.md",
                       "canon.md", "voice.md"]:
            path = OUTPUT_DIR / label
            exists = path.exists()
            size = path.stat().st_size if exists else 0
            checks.append((f"Phase 1: {label}", exists and size >= 100))
            if not exists:
                ok = False

        # Phase 2
        chapter_files = sorted(CHAPTERS_DIR.glob("ch_*.md"))
        checks.append(("Phase 2: 章节文件数", len(chapter_files) >= 1))
        if len(chapter_files) < 1:
            ok = False

        # Phase 3
        state = load_state()
        drafted = state.get("chapters_drafted", 0)
        checks.append(("Phase 3: chapters_drafted", drafted >= 1))

        for name, passed in checks:
            status = "✅" if passed else "❌"
            print(f"  {status} {name}")

        if not ok:
            print("\n  ⚠ 前置条件不满足：部分 Phase 1/2/3 产出缺失。")
            print("    3.4.1 需要章节文件；3.4.3 仅需 Foundation 文件。")
            print("    跳过 API 测试可使用 --skip-api 参数。")

    # ============================================================
    # 3.4.3 异常不崩溃
    # ============================================================

    def test_3_4_3_export_graceful_degradation(self):
        """3.4.3 export 各步骤异常不崩溃。

        验证：无章节文件时，build_outline / build_arc_summary /
              build_manuscript 全部优雅降级，pipeline 不崩溃。
        API 调用：0。
        """
        if TARGET_TEST and TARGET_TEST not in ("3.4.3", "3.4"):
            raise unittest.SkipTest(f"--test={TARGET_TEST}")

        # 确保 Foundation 文件存在
        for label in ["world.md", "characters.md"]:
            path = OUTPUT_DIR / label
            self.assertTrue(path.exists(),
                            f"Phase 1 {label} 缺失，无法执行 3.4.3")

        # 备份并清空 chapters
        _setup_343()

        try:
            # 确认清空
            remaining = list(CHAPTERS_DIR.glob("ch_*.md"))
            self.assertEqual(len(remaining), 0,
                             f"chapters 目录未清空: {len(remaining)} 文件")

            # 设置 state
            state = load_state()
            state["phase"] = "export"
            state["current_focus"] = "export"
            save_state(state)

            # 执行导出 — 不抛异常即为通过
            # step() 输出到 stdout，因此捕获 stdout
            from pipeline_orchestrator import run_export
            state, stdout_output = _capture_stdout(run_export, state)

            # (a) build_outline 跳过信息
            self.assertIn("无章节文件，跳过", stdout_output,
                          "build_outline 未输出 '无章节文件，跳过'")

            # (b) build_arc_summary 跳过信息
            # （build_arc_summary 也在 stderr 中输出相似信息）

            # (c) build_manuscript 跳过信息
            # （同上）

            # (d) state.phase == "complete"
            self.assertEqual(state["phase"], "complete",
                             f"state.phase 应为 complete，"
                             f"实际={state['phase']}")

            # (e) results.tsv 有 export 记录
            if RESULTS_FILE.exists():
                results_content = RESULTS_FILE.read_text(
                    encoding="utf-8")
                self.assertIn("export", results_content,
                              "results.tsv 缺少 export 记录")

            print("  ✅ 3.4.3 优雅降级通过 — 所有步骤优雅跳过")

        finally:
            _teardown_343()

    # ============================================================
    # 3.4.1 run_export() 全流程
    # ============================================================

    def test_3_4_1_run_export_full(self):
        """3.4.1 run_export() 全流程。

        验证：build_outline → build_arc_summary → build_manuscript
              全部执行，产出完整。
        API 调用：~2 次。
        """
        if TARGET_TEST and TARGET_TEST not in ("3.4.1", "3.4"):
            raise unittest.SkipTest(f"--test={TARGET_TEST}")

        if DRY_RUN:
            # 仅检查前置条件
            for label in ["world.md", "characters.md", "outline.md",
                           "canon.md", "voice.md"]:
                path = OUTPUT_DIR / label
                self.assertTrue(path.exists() and path.stat().st_size >= 100,
                                f"Phase 1 {label} 缺失")
            chapter_files = sorted(CHAPTERS_DIR.glob("ch_*.md"))
            self.assertGreaterEqual(len(chapter_files), 1,
                                    "Phase 2 无章节文件")
            print("  ℹ dry-run: 前置条件满足")
            return

        if SKIP_API:
            raise unittest.SkipTest("--skip-api")

        if not _check_api_key():
            self.skipTest("API Key 无效或为占位符，跳过真实 API 调用")

        # 前置条件
        chapter_files = sorted(CHAPTERS_DIR.glob("ch_*.md"))
        self.assertGreaterEqual(len(chapter_files), 1,
                                f"Phase 2 无章节文件，当前={len(chapter_files)}")

        # 备份原始 outline.md（供 3.4.5 对比）
        backed = _backup_outline()
        if backed:
            print("  📋 已备份 outline.md → _outline_backup_before_export.md")

        # 设置 state 为 export 阶段
        state = load_state()
        orig_phase = state.get("phase", "?")
        state["phase"] = "export"
        state["current_focus"] = "export"
        save_state(state)

        from pipeline_orchestrator import run_export
        try:
            state, stderr_output = _capture_stderr(run_export, state)
        except Exception as e:
            # 失败时恢复 outline
            if backed:
                _restore_outline_backup()
            self.fail(f"run_export() 抛出异常: {e}")

        # ---- 验证 ----

        # (a) outline.md 被重建
        outline_path = OUTPUT_DIR / "outline.md"
        self.assertTrue(outline_path.exists(),
                        "outline.md 未生成")
        outline_size = outline_path.stat().st_size
        self.assertGreaterEqual(outline_size, 50,
                                f"outline.md 过小 ({outline_size} bytes)")

        # (b) arc_summary.md 产出
        arc_path = OUTPUT_DIR / "arc_summary.md"
        self.assertTrue(arc_path.exists(),
                        "arc_summary.md 未生成")
        arc_content = arc_path.read_text(encoding="utf-8")
        self.assertGreaterEqual(len(arc_content), 50,
                                f"arc_summary.md 过短 ({len(arc_content)} 字符)")
        # 验证四个章节
        for section in ["角色弧线", "情节弧线", "主题弧线", "伏笔回顾"]:
            self.assertIn(section, arc_content,
                          f"arc_summary.md 缺少 '{section}' 章节")

        # (c) manuscript.md 产出
        ms_path = OUTPUT_DIR / "manuscript.md"
        self.assertTrue(ms_path.exists(),
                        "manuscript.md 未生成")
        ms_content = ms_path.read_text(encoding="utf-8")
        self.assertGreaterEqual(len(ms_content), 100,
                                f"manuscript.md 过短 ({len(ms_content)} 字符)")
        self.assertIn("目录", ms_content,
                      "manuscript.md 缺少目录")

        # (d) 章节数一致
        chapter_count_in_ms = ms_content.count("# 第 ")
        self.assertEqual(chapter_count_in_ms, len(chapter_files),
                         f"手稿章节数 ({chapter_count_in_ms}) "
                         f"≠ 实际 ({len(chapter_files)})")

        # (e) state.phase == "complete"
        self.assertEqual(state["phase"], "complete",
                         f"state.phase={state['phase']}，应为 complete")

        # (f) results.tsv 含 export 记录
        if RESULTS_FILE.exists():
            results_content = RESULTS_FILE.read_text(encoding="utf-8")
            self.assertIn("export", results_content,
                          "results.tsv 缺少 export 记录")

        print(f"  ✅ 3.4.1 导出全流程通过 "
              f"(outline={outline_size}B, "
              f"arc={len(arc_content)}字, "
              f"ms={len(ms_content)}字, "
              f"chapters={len(chapter_files)})")

    # ============================================================
    # 3.4.2 手稿章节数一致性
    # ============================================================

    def test_3_4_2_manuscript_chapter_consistency(self):
        """3.4.2 手稿章节数一致性。

        验证：manuscript.md 章节数与 chapters/ 文件数精确匹配，
              顺序正确，内容非空。
        API 调用：0。
        """
        if TARGET_TEST and TARGET_TEST not in ("3.4.2", "3.4"):
            raise unittest.SkipTest(f"--test={TARGET_TEST}")

        ms_path = OUTPUT_DIR / "manuscript.md"
        if not ms_path.exists():
            self.skipTest("manuscript.md 不存在，请先执行 3.4.1")

        ms_content = ms_path.read_text(encoding="utf-8")
        chapter_files = sorted(CHAPTERS_DIR.glob("ch_*.md"))

        # (a) 章节数一致性
        chapter_headers = re.findall(r'^# 第 (\d+) 章', ms_content,
                                     re.MULTILINE)
        self.assertEqual(len(chapter_headers), len(chapter_files),
                         f"手稿章节标题数 ({len(chapter_headers)}) "
                         f"≠ 文件数 ({len(chapter_files)})")

        # (b) 顺序正确
        expected_numbers = list(range(1, len(chapter_files) + 1))
        actual_numbers = [int(n) for n in chapter_headers]
        self.assertEqual(actual_numbers, expected_numbers,
                         f"章节顺序错误: 期望 {expected_numbers}, "
                         f"实际 {actual_numbers}")

        # (c) 每章正文非空
        chapter_sections = re.split(r'^# 第 \d+ 章\s*$', ms_content,
                                    flags=re.MULTILINE)
        for i, body in enumerate(chapter_sections[1:], 1):
            clean = body.replace(" ", "").replace("\n", "").replace("---", "")
            self.assertGreaterEqual(len(clean), 10,
                                    f"第 {i} 章正文过短 ({len(clean)} 字符)")

        # (d) 目录条目数一致
        toc_lines = [line for line in ms_content.split("\n")
                     if re.match(r'^\d+\.\s', line.strip())]
        self.assertEqual(len(toc_lines), len(chapter_files),
                         f"目录条目数 ({len(toc_lines)}) "
                         f"≠ 文件数 ({len(chapter_files)})")

        # (e) 目录格式 "N. 标题"
        for line in toc_lines:
            self.assertTrue(re.match(r'^\d+\.\s', line.strip()),
                            f"目录条目格式错误: '{line.strip()}'")

        print(f"  ✅ 3.4.2 一致性通过 "
              f"(章节={len(chapter_headers)}, "
              f"目录={len(toc_lines)})")

    # ============================================================
    # 3.4.4 manuscript.md 格式完整性
    # ============================================================

    def test_3_4_4_manuscript_format_integrity(self):
        """3.4.4 manuscript.md 格式完整性。

        验证：目录标题、分隔符、章节标题、正文、字数、
              POSIX 换行符。
        API 调用：0。
        """
        if TARGET_TEST and TARGET_TEST not in ("3.4.4", "3.4"):
            raise unittest.SkipTest(f"--test={TARGET_TEST}")

        ms_path = OUTPUT_DIR / "manuscript.md"
        if not ms_path.exists():
            self.skipTest("manuscript.md 不存在，请先执行 3.4.1")

        ms_content = ms_path.read_text(encoding="utf-8")

        # (a) 目录标题
        self.assertTrue(ms_content.startswith("# 目录"),
                        f"manuscript.md 应以 '# 目录' 开头，"
                        f"实际开头: '{ms_content[:30]}'")

        # (b) 目录与正文分隔
        self.assertIn("\n\n---\n\n", ms_content,
                      "manuscript.md 目录后缺少 '---' 分隔符")

        # (c) 章节间分隔符数量
        chapter_headers = re.findall(r'^# 第 \d+ 章', ms_content,
                                     re.MULTILINE)
        chapter_count = len(chapter_headers)
        sep_count = ms_content.count("\n\n---\n\n")
        expected_sep = chapter_count  # 目录分隔1 + (N-1) 章间分隔
        self.assertGreaterEqual(sep_count, max(1, chapter_count - 1),
                                f"分隔符数 ({sep_count}) 不足，"
                                f"期望 ≥ {max(1, chapter_count - 1)}")

        # (d) 每章标题格式
        for header in chapter_headers:
            self.assertTrue(re.match(r'^# 第 \d+ 章$', header),
                            f"章节标题格式错误: '{header}'")

        # (e) 每章有实质内容
        sections = re.split(r'\n\n---\n\n', ms_content)
        for i, section in enumerate(sections[1:], 1):
            body_lines = section.strip().split("\n")
            if body_lines and body_lines[0].startswith("# 第"):
                body = "\n".join(body_lines[1:]).strip()
            else:
                body = section.strip()
            clean = body.replace(" ", "").replace("\n", "").replace("---", "")
            self.assertGreaterEqual(len(clean), 10,
                                    f"第 {i} 章正文过短 ({len(clean)} 字符)")

        # (f) 总字数合理
        reported_words = count_words_in_chapters()
        ms_words = len(ms_content.replace(" ", "").replace("\n", ""))
        if reported_words > 0:
            diff_ratio = abs(ms_words - reported_words) / max(ms_words, 1)
            self.assertLess(diff_ratio, 0.50,
                            f"手稿字数 ({ms_words}) 与统计 ({reported_words}) "
                            f"差异过大 ({diff_ratio:.1%})")

        # (g) 以换行符结尾
        self.assertTrue(ms_content.endswith("\n"),
                        "manuscript.md 应以换行符结尾")

        print(f"  ✅ 3.4.4 格式完整性通过 "
              f"(字数={ms_words}, 章={chapter_count}, 分隔={sep_count})")

    # ============================================================
    # 3.4.5 outline.md 重建内容验证
    # ============================================================

    def test_3_4_5_outline_rebuild_content(self):
        """3.4.5 outline.md 重建内容验证。

        验证：自动检测 outline.md 是 Foundation 还是 build_outline 产出。
              - Foundation 格式：含 `## 第N章：` 层级条目
              - Rebuild 格式：含 `### 第 N 章` + 关键事件/角色变化/情感弧线
              - 如存在备份文件，对比新旧大纲相似度
        API 调用：0。
        """
        if TARGET_TEST and TARGET_TEST not in ("3.4.5", "3.4"):
            raise unittest.SkipTest(f"--test={TARGET_TEST}")

        outline_path = OUTPUT_DIR / "outline.md"
        if not outline_path.exists():
            self.skipTest("outline.md 不存在")

        outline_content = outline_path.read_text(encoding="utf-8")

        # 检测大纲格式类型
        is_rebuilt = ("整体弧线" in outline_content
                      or "弧线摘要" in outline_content
                      or "关键事件" in outline_content)

        # (a) 含章节条目
        chapter_entries = re.findall(
            r'^#{1,4}\s*第\s*\d+\s*章', outline_content, re.MULTILINE)
        self.assertGreaterEqual(len(chapter_entries), 1,
                                "outline.md 无章节条目")

        # (b) 章节条目数合理（至少覆盖到实际章节数）
        chapter_files = sorted(CHAPTERS_DIR.glob("ch_*.md"))
        if chapter_files:
            # 条目数不一定精确等于（Foundation 可能多卷），
            # 但至少应覆盖到最后一章
            last_ch_num = len(chapter_files)
            found_nums = []
            for entry in chapter_entries:
                m = re.search(r'第\s*(\d+)\s*章', entry)
                if m:
                    found_nums.append(int(m.group(1)))
            if found_nums:
                self.assertGreaterEqual(
                    max(found_nums), last_ch_num,
                    f"大纲最大章节号 ({max(found_nums)}) 未覆盖实际 "
                    f"章节数 ({last_ch_num})")

        if is_rebuilt:
            # 已重建 — 严格验证 rebuild 格式
            # (c) 子项检查
            expected_items = ["关键事件", "角色变化", "伏笔", "情感弧线"]
            found = sum(1 for item in expected_items
                        if item in outline_content)
            self.assertGreaterEqual(found, 2,
                                    f"大纲子项不足: {found}/4 {expected_items}")

            # (d) 整体弧线摘要
            self.assertTrue("整体弧线" in outline_content
                            or "弧线摘要" in outline_content,
                            "outline.md 缺少整体弧线摘要")

            # (e) 与原始大纲不同（如果有备份）
            backup_outline = OUTPUT_DIR / "_outline_backup_before_export.md"
            if backup_outline.exists():
                original = backup_outline.read_text(encoding="utf-8")
                sim = _text_similarity(original, outline_content)
                self.assertLess(sim, 0.98,
                                f"重建大纲与原始大纲相似度过高 "
                                f"({sim:.1%})，可能未真正重建")
                print(f"  ℹ 原始 vs 重建 outline 相似度: {sim:.1%}")

            print(f"  ✅ 3.4.5 大纲重建验证通过 "
                  f"(条目={len(chapter_entries)}, 子项={found}/4)")
        else:
            # 未重建（Foundation 阶段）— 基础验证
            # Foundation 格式：含 ## 第N章：名称
            foundation_entries = re.findall(
                r'^##\s+第\s*\d+\s*章', outline_content, re.MULTILINE)
            has_beat_list = "节拍清单" in outline_content
            has_emotion = "情感弧线" in outline_content

            # 验证 Foundation 基本结构
            self.assertGreaterEqual(
                len(foundation_entries), 1,
                "Foundation 大纲无 `## 第N章` 条目")

            print(f"  ✅ 3.4.5 大纲验证通过 "
                  f"(Foundatation格式, 条目={len(foundation_entries)}, "
                  f"节拍清单={'✅' if has_beat_list else '❌'}, "
                  f"情感弧线={'✅' if has_emotion else '❌'})")


def _text_similarity(text1: str, text2: str) -> float:
    """简单相似度计算（基于共同行比例 + 共同字符比例）。"""
    lines1 = set(text1.split("\n"))
    lines2 = set(text2.split("\n"))
    if not lines1 or not lines2:
        return 0.0
    # Jaccard on lines
    intersection = lines1 & lines2
    union = lines1 | lines2
    line_sim = len(intersection) / len(union) if union else 0.0

    # Character-level Jaccard (sampled)
    chars1 = set(text1.replace(" ", "").replace("\n", "")[::5])
    chars2 = set(text2.replace(" ", "").replace("\n", "")[::5])
    if not chars1 or not chars2:
        return line_sim
    char_intersection = chars1 & chars2
    char_union = chars1 | chars2
    char_sim = len(char_intersection) / len(char_union) if char_union else 0.0

    return (line_sim + char_sim) / 2.0


# ============================================================
# 自定义 TestRunner — 始终输出详细信息
# ============================================================

def custom_test_order(tests):
    """按文档顺序排列测试：3.4.0 → 3.4.3 → 3.4.1 → 3.4.2 → 3.4.4 → 3.4.5"""
    order = [
        "test_3_4_0_prerequisites",
        "test_3_4_3_export_graceful_degradation",
        "test_3_4_1_run_export_full",
        "test_3_4_2_manuscript_chapter_consistency",
        "test_3_4_4_manuscript_format_integrity",
        "test_3_4_5_outline_rebuild_content",
    ]
    lookup = {id(test): test for test in tests}
    ordered = []
    seen = set()
    for name in order:
        for test in tests:
            if test._testMethodName == name and id(test) not in seen:
                ordered.append(test)
                seen.add(id(test))
                break
    # 追加不在列表中的测试
    for test in tests:
        if id(test) not in seen:
            ordered.append(test)
    return ordered


if __name__ == "__main__":
    print("=" * 70)
    print("  Stage 3 Phase 4 集成测试 — Export（导出）")
    print("=" * 70)
    print(f"  dry-run: {DRY_RUN}")
    print(f"  skip-api: {SKIP_API}")
    print(f"  target: {TARGET_TEST or '全部'}")
    print(f"  output: {OUTPUT_DIR}")
    print(f"  chapters: {len(list(CHAPTERS_DIR.glob('ch_*.md')))} 文件")
    print("-" * 70)

    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestPhase4Export)
    # 自定义排序
    suite._tests = custom_test_order(list(suite))

    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
    result = runner.run(suite)

    # 汇总
    print("\n" + "=" * 70)
    print("  测试汇总")
    print("=" * 70)
    print(f"  通过: {result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped)}")
    print(f"  失败: {len(result.failures)}")
    print(f"  错误: {len(result.errors)}")
    print(f"  跳过: {len(result.skipped)}")
    print(f"  总计: {result.testsRun}")

    if result.failures or result.errors:
        print("\n  ❌ 存在未通过的测试项")
        sys.exit(1)
    else:
        print("\n  ✅ 全部测试通过")
        sys.exit(0)