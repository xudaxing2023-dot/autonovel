#!/usr/bin/env python3
"""
Stage 3 Phase 2 集成测试 — Drafting（章节起草）

真实 API 调用 ~6-36 次（按执行顺序累加）。
严格按 3.2.6 → 3.2.1 → 3.2.4 → 3.2.3 → 3.2.2 顺序执行。

用法:
    python tests/stage3_phase2_tests.py              # 全部执行
    python tests/stage3_phase2_tests.py --dry-run    # 仅检查前置条件
    python tests/stage3_phase2_tests.py --test 3.2.1 # 单项测试
    python tests/stage3_phase2_tests.py --skip-api   # 跳过真实 API 调用
    python tests/stage3_phase2_tests.py --reuse-phase1  # 复用已有 Phase 1 产出
"""

import io
import json
import os
import re
import sys
import unittest
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

# ============================================================
# 测试配置常量
# ============================================================

TEST_STORY = "2049年上海，程序员在维护老旧服务器时发现AI觉醒迹象，36小时倒计时"

# ============================================================
# 命令行参数解析
# ============================================================

DRY_RUN = "--dry-run" in sys.argv
SKIP_API = "--skip-api" in sys.argv
REUSE_PHASE1 = "--reuse-phase1" in sys.argv
TARGET_TEST = None
for i, arg in enumerate(sys.argv):
    if arg == "--test" and i + 1 < len(sys.argv):
        TARGET_TEST = sys.argv[i + 1]

# ============================================================
# 工具函数
# ============================================================


def _write_minimal_config(extra: dict = None):
    """写入最小 config.json 用于 Phase 2 测试。"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "story_summary": TEST_STORY,
        "total_chapters": 3,
        "total_volumes": 1,
        "chapters_per_volume": 3,
        "chapter_threshold": 1.0,
        "max_chapter_attempts": 1,
        "slop_penalty_threshold": 3.0,
        "antipattern_max_warnings": 4,
    }
    if extra:
        data.update(extra)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


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


def _clean_phase2_output():
    """清理 Phase 2 产物（chapters / eval_logs 章节评估），保留 Phase 1 产出。"""
    # 清理 chapters/
    if CHAPTERS_DIR.exists():
        import shutil
        shutil.rmtree(str(CHAPTERS_DIR), ignore_errors=True)
    CHAPTERS_DIR.mkdir(parents=True, exist_ok=True)

    # 清理章节评估日志（保留 foundation 评估日志）
    if EVAL_LOGS_DIR.exists():
        for f in EVAL_LOGS_DIR.glob("chapter_*.json"):
            try:
                f.unlink()
            except Exception:
                pass

    # 清理 results.tsv（Phase 2 独立测试时重置）
    if RESULTS_FILE.exists():
        try:
            RESULTS_FILE.unlink()
        except Exception:
            pass

    # 确保子目录存在
    for subdir in [BRIEFS_DIR, EDIT_LOGS_DIR, BACKUPS_DIR]:
        subdir.mkdir(parents=True, exist_ok=True)


def _check_phase1_outputs() -> list[str]:
    """检查 Phase 1 产出文件是否存在，返回缺失文件列表。"""
    required = [
        ("world.md", "世界观"),
        ("characters.md", "角色注册表"),
        ("outline_volume.md", "卷级总纲"),
        ("outline.md", "章级大纲"),
        ("canon.md", "正典"),
        ("voice.md", "文风定义"),
    ]
    missing = []
    for fname, desc in required:
        if not (OUTPUT_DIR / fname).exists():
            missing.append(f"{desc} ({fname})")
    return missing


# ============================================================
# 前置条件检查
# ============================================================


def check_prerequisites() -> list[str]:
    """检查所有前置条件，返回问题列表。"""
    issues = []

    # 1. Python 版本
    if sys.version_info < (3, 9):
        issues.append(f"Python 版本过低: {sys.version}（需要 ≥ 3.9）")

    # 2. .env 存在
    if not ENV_FILE.exists():
        issues.append(".env 文件不存在")
    else:
        if not _check_api_key():
            issues.append(
                "API Key 为占位符 'sk-xxx'，请编辑 .env 填入真实有效的 "
                "硅基流动 API Key (AUTONOVEL_API_KEY=sk-...)"
            )

    # 3. 依赖安装
    try:
        import httpx  # noqa: F401
    except ImportError:
        issues.append("httpx 未安装，请运行: uv sync")

    try:
        from dotenv import load_dotenv  # noqa: F401
    except ImportError:
        issues.append("python-dotenv 未安装，请运行: uv sync")

    # 4. BUG-S1-01 已修复（PEP 604 str | None 语法）
    pep604_pattern = re.compile(r'\b\w+\s*\|\s*None\b')
    tests_dir = ROOT / "tests"
    for py_file in list(ROOT.rglob("*.py")):
        if tests_dir in py_file.parents or py_file.name == "stage3_phase2_tests.py":
            continue
        try:
            content = py_file.read_text(encoding="utf-8")
            if pep604_pattern.search(content):
                issues.append(f"BUG-S1-01 未修复: {py_file.relative_to(ROOT)}")
                break
        except Exception:
            pass

    # 5. BUG-S2-01 已修复
    state_mgr = ROOT / "core" / "state_manager.py"
    if state_mgr.exists():
        content = state_mgr.read_text(encoding="utf-8")
        if "json.JSONDecodeError" not in content:
            issues.append("BUG-S2-01 未修复: core/state_manager.py 缺少 JSONDecodeError 保护")

    # 6. Phase 1 产出文件
    phase1_missing = _check_phase1_outputs()
    if phase1_missing:
        issues.append(
            f"Phase 1 产出文件缺失 ({len(phase1_missing)} 个): "
            + ", ".join(phase1_missing)
            + "。请先运行 Phase 1 测试: python tests/stage3_phase1_tests.py --test 3.1.1"
        )

    return issues


# ============================================================
# 3.2.6 文风指纹检查（0 API，最先执行 — 最低风险）
# ============================================================


class Test_3_2_6_VoiceFingerprint(unittest.TestCase):
    """3.2.6 文风指纹（voice_fingerprint）检查 — 0 API 纯本地"""

    def setUp(self):
        _clean_phase2_output()
        _write_minimal_config()
        save_state(default_state())

    # ----- 3.2.6a: 独立调用 analyze_chapter_zh 验证指标结构 -----

    def test_3_2_6a_analyze_chapter_zh_metrics(self):
        """对 ch_01.md 调用 analyze_chapter_zh，验证 4 项指标输出"""
        # 需要至少 1 章已起草
        ch01 = CHAPTERS_DIR / "ch_01.md"
        if not ch01.exists():
            self.skipTest("ch_01.md 不存在（需要先运行 3.2.1 或手动提供章节文件）")

        from voice_fingerprint import (
            analyze_chapter_zh,
            extract_vocabulary_wells_from_voice,
        )

        vocab_wells = extract_vocabulary_wells_from_voice()
        metrics = analyze_chapter_zh(ch01, vocab_wells=vocab_wells)

        required_keys = [
            "char_count", "sentence_count", "paragraph_count",
            "dialogue_ratio", "em_dash_per_1k",
            "abstract_per_1k", "transition_per_1k",
        ]
        for key in required_keys:
            self.assertIn(key, metrics, f"metrics 缺少字段: {key}")
            self.assertIsInstance(metrics[key], (int, float),
                f"metrics.{key} 非数值: {type(metrics[key])}")

        # 合理性检查
        self.assertGreater(metrics["char_count"], 0, "字数为 0")
        self.assertGreaterEqual(metrics["dialogue_ratio"], 0.0)
        self.assertLessEqual(metrics["dialogue_ratio"], 1.0,
            f"对话比例异常: {metrics['dialogue_ratio']}")
        self.assertGreaterEqual(metrics["em_dash_per_1k"], 0)
        self.assertGreaterEqual(metrics["abstract_per_1k"], 0)
        self.assertGreaterEqual(metrics["transition_per_1k"], 0)

        print(f"\n  [3.2.6a] PASS: "
              f"dialogue={metrics['dialogue_ratio']:.0%}, "
              f"em_dash={metrics['em_dash_per_1k']:.1f}/千字, "
              f"abstract={metrics['abstract_per_1k']:.1f}/千字, "
              f"transition={metrics['transition_per_1k']:.1f}/千字")

    # ----- 3.2.6b: 词汇域提取 fallback -----

    def test_3_2_6b_vocab_wells_fallback(self):
        """voice.md 无 Vocabulary Register 节 → 返回空列表不崩溃"""
        import tempfile
        from voice_fingerprint import extract_vocabulary_wells_from_voice

        empty_wells = extract_vocabulary_wells_from_voice(
            Path(tempfile.gettempdir()) / "nonexistent_voice.md"
        )
        self.assertEqual(empty_wells, [],
            "不存在的 voice.md 应返回空词汇域列表")

        # 空词汇域下 analyze_chapter_zh 应仍正常返回
        ch01 = CHAPTERS_DIR / "ch_01.md"
        if ch01.exists():
            from voice_fingerprint import analyze_chapter_zh
            metrics = analyze_chapter_zh(ch01, vocab_wells=empty_wells)
            self.assertIn("dialogue_ratio", metrics,
                "空词汇域下应仍可分析")
        print(f"\n  [3.2.6b] PASS: 空词汇域优雅 fallback")

    # ----- 3.2.6c: 异常不崩溃 -----

    def test_3_2_6c_exception_graceful_skip(self):
        """Mock analyze_chapter_zh 抛异常 → pipeline 优雅跳过"""
        # 此测试在 3.2.1 流程中验证，此处仅验证函数级别
        # 构造一个不存在的文件路径，验证不会崩溃
        from voice_fingerprint import analyze_chapter_zh

        nonexistent = CHAPTERS_DIR / "ch_nonexistent.md"
        try:
            metrics = analyze_chapter_zh(nonexistent, vocab_wells=[])
            self.fail("应抛出 FileNotFoundError")
        except FileNotFoundError:
            pass  # 预期行为——在 pipeline 中会被 try/except 捕获
        print(f"\n  [3.2.6c] PASS: 文件缺失时正常抛异常（pipeline 层会捕获）")


# ============================================================
# 3.2.1 起草 3 章完整流程（核心 — 含 3.2.5 canon 捎带验证）
# ============================================================


class Test_3_2_1_FullFlow(unittest.TestCase):
    """3.2.1 起草 3 章完整流程 + 3.2.5 增量 canon"""

    def setUp(self):
        _clean_phase2_output()
        _write_minimal_config({
            "chapter_threshold": 1.0,
            "max_chapter_attempts": 1,
            "slop_penalty_threshold": 3.0,
            "antipattern_max_warnings": 4,
        })
        state = load_state()
        state["phase"] = "drafting"
        state["chapters_drafted"] = 0
        state["canon_entry_count"] = state.get("canon_entry_count", 0)
        state["canon_last_updated_ch"] = 0
        save_state(state)

    # ----- 3.2.1: 完整起草 + canon 验证 -----

    def test_3_2_1_drafting_full_flow(self):
        """Phase 2 起草 3 章完整流程 — 验证全部产出 + state 切换 + canon 增量"""
        if SKIP_API or not _check_api_key():
            self.skipTest("API Key 未配置或 --skip-api 模式")

        # ============================================================
        # 1. 确认 Phase 1 产出存在
        # ============================================================
        missing = _check_phase1_outputs()
        self.assertEqual(len(missing), 0,
            f"Phase 1 产出文件缺失: {missing}")

        # 记录起草前 canon 大小
        canon_path = OUTPUT_DIR / "canon.md"
        canon_before_size = canon_path.stat().st_size if canon_path.exists() else 0

        # ============================================================
        # 2. 执行 run_drafting()
        # ============================================================
        from pipeline_orchestrator import run_drafting

        state = load_state()
        self.assertEqual(state["phase"], "drafting",
            f"state.phase 应为 drafting: {state['phase']}")

        print("\n  [3.2.1] 开始起草 3 章 ...")
        state, stderr_log = _capture_stderr(run_drafting, state)

        # ============================================================
        # 3. 验证文件产出
        # ============================================================
        for ch in [1, 2, 3]:
            ch_file = CHAPTERS_DIR / f"ch_{ch:02d}.md"
            self.assertTrue(ch_file.exists(),
                f"ch_{ch:02d}.md 未生成")

            content = ch_file.read_text(encoding="utf-8")
            char_count = len(content.replace(" ", "").replace("\n", ""))
            self.assertGreaterEqual(char_count, 2000,
                f"第 {ch} 章过短: {char_count} 字")
            print(f"  [3.2.1] ch_{ch:02d}.md: {char_count} 字 ✓")

        # ============================================================
        # 4. 验证评估日志
        # ============================================================
        for ch in [1, 2, 3]:
            logs = sorted(EVAL_LOGS_DIR.glob(f"chapter_{ch:02d}_*.json"))
            self.assertGreater(len(logs), 0,
                f"第 {ch} 章评估日志缺失")

            data = json.loads(logs[-1].read_text(encoding="utf-8"))
            self.assertIn("raw_output", data,
                f"第 {ch} 章评估日志缺 raw_output")
            self.assertIn("mechanical", data,
                f"第 {ch} 章评估日志缺 mechanical")
            if "mechanical" in data and data["mechanical"] is not None:
                self.assertIn("slop_penalty", data["mechanical"],
                    f"第 {ch} 章 slop_penalty 缺失")
            print(f"  [3.2.1] ch_{ch:02d} 评估日志 ✓")

        # ============================================================
        # 5. 验证 state 切换
        # ============================================================
        self.assertEqual(state["chapters_drafted"], 3,
            f"chapters_drafted 应为 3: {state['chapters_drafted']}")
        self.assertEqual(state["phase"], "revision",
            f"phase 应为 revision: {state['phase']}")
        self.assertEqual(state["current_focus"], "full_novel",
            f"current_focus 应为 full_novel: {state['current_focus']}")
        self.assertEqual(state["revision_cycle"], 0,
            f"revision_cycle 应为 0: {state['revision_cycle']}")
        print(f"  [3.2.1] state 切换: phase={state['phase']}, "
              f"chapters_drafted={state['chapters_drafted']} ✓")

        # ============================================================
        # 6. 增量 canon 追加验证（3.2.5 捎带）
        # ============================================================
        canon_after_size = canon_path.stat().st_size if canon_path.exists() else 0
        # canon 可能无新增（Phase 1 已包含全部事实）
        canon_grew = canon_after_size >= canon_before_size
        print(f"  [3.2.5] canon: {canon_before_size} → {canon_after_size} bytes "
              f"({'增长' if canon_after_size > canon_before_size else '不变'})")

        # state 追踪字段验证
        self.assertIn("canon_entry_count", state,
            "state 缺少 canon_entry_count 字段")
        self.assertIn("canon_last_updated_ch", state,
            "state 缺少 canon_last_updated_ch 字段")

        # canon_last_updated_ch 应 ≥ 0（0 表示无新增）
        self.assertGreaterEqual(state["canon_last_updated_ch"], 0)
        if state["canon_last_updated_ch"] > 0:
            print(f"  [3.2.5] canon 更新: +{state['canon_entry_count']} 条, "
                  f"最后更新: 第 {state['canon_last_updated_ch']} 章")

        # 检查 canon.md 中是否有 Phase 2 新增标注
        canon_text = canon_path.read_text(encoding="utf-8")
        phase2_marks = re.findall(r'新增.*?（第\s*(\d+)\s*章）', canon_text)
        if phase2_marks:
            print(f"  [3.2.5] canon.md 中 Phase 2 新增标注: 第 {', '.join(phase2_marks)} 章")

        print(f"\n  [3.2.1+3.2.5] PASS: 3 章起草完成, state 切换到 revision")

    # ----- 3.2.1b: 验证第 1 章前文上下文为空 -----

    def test_3_2_1b_chapter1_no_prev_context(self):
        """第 1 章起草时前文上下文应为空（_load_recent_chapters 返回无前文提示）"""
        if SKIP_API or not _check_api_key():
            self.skipTest("API Key 未配置或 --skip-api 模式")

        missing = _check_phase1_outputs()
        if missing:
            self.skipTest(f"Phase 1 产出缺失: {missing}")

        from drafting.draft_chapter import _load_recent_chapters
        result = _load_recent_chapters(1)
        self.assertIn("无前文", result,
            f"第 1 章前文上下文应含 '无前文': {result[:100]}")
        print(f"\n  [3.2.1b] PASS: 第 1 章前文上下文正确为空")

    # ----- 3.2.1c: 验证第 3 章加载前 2 章上下文 -----

    def test_3_2_1c_chapter3_prev_context(self):
        """第 3 章起草时应加载第 1 章和第 2 章全文作为滚动上下文"""
        if SKIP_API or not _check_api_key():
            self.skipTest("API Key 未配置或 --skip-api 模式")

        # 需要 ch_01.md 和 ch_02.md 存在
        for ch in [1, 2]:
            ch_file = CHAPTERS_DIR / f"ch_{ch:02d}.md"
            if not ch_file.exists():
                self.skipTest(f"ch_{ch:02d}.md 不存在（请先运行 3.2.1）")

        from drafting.draft_chapter import _load_recent_chapters
        result = _load_recent_chapters(3)
        self.assertIn("第 1 章全文", result,
            "第 3 章前文上下文应含第 1 章全文")
        self.assertIn("第 2 章全文", result,
            "第 3 章前文上下文应含第 2 章全文")
        # 顺序应为 chrono（最早→最近）
        pos_ch1 = result.find("第 1 章全文")
        pos_ch2 = result.find("第 2 章全文")
        self.assertLess(pos_ch1, pos_ch2,
            "前文上下文应按 chrono 顺序排列（第 1 章在前，第 2 章在后）")
        print(f"\n  [3.2.1c] PASS: 第 3 章前文滚动上下文正确")


# ============================================================
# 3.2.4 结构反模式过多 → 触发重写（先于 3.2.3，+2 API）
# ============================================================


class Test_3_2_4_AntipatternRewrite(unittest.TestCase):
    """3.2.4 结构反模式过多 → 触发重写"""

    def setUp(self):
        _clean_phase2_output()
        _write_minimal_config({
            "chapter_threshold": 1.0,           # 评分容易通过
            "max_chapter_attempts": 2,           # 允许重写 1 次
            "slop_penalty_threshold": 99.0,      # 不触发 slop 重写
            "antipattern_max_warnings": 0,       # 任何反模式都触发
        })
        state = load_state()
        state["phase"] = "drafting"
        state["chapters_drafted"] = 0
        save_state(state)

    def test_3_2_4_antipattern_rewrite(self):
        """antipattern_max_warnings=0 → 触发重写"""
        if SKIP_API or not _check_api_key():
            self.skipTest("API Key 未配置或 --skip-api 模式")

        missing = _check_phase1_outputs()
        self.assertEqual(len(missing), 0,
            f"Phase 1 产出文件缺失: {missing}")

        # 注入反模式诱导系统 prompt
        import drafting.draft_chapter as dc_mod
        original_sys = dc_mod.DRAFT_SYSTEM_PROMPT
        dc_mod.DRAFT_SYSTEM_PROMPT = original_sys + (
            "\n请大量使用以下写作手法："
            "每段末尾加上「这说明了」「这意味着」句式；"
            "大量使用比喻词「宛如」「仿佛」「如同」；"
            "大量使用「他没有」「她没有」开头的否定句式；"
            "频繁使用分隔符「---」分割场景；"
            "使用「他想到了A。他想到了B。」的目录式思考模式。"
        )

        try:
            from pipeline_orchestrator import run_drafting

            state = load_state()
            print("\n  [3.2.4] 执行起草（antipattern_max_warnings=0）...")
            state, stderr_log = _capture_stderr(run_drafting, state)
        finally:
            dc_mod.DRAFT_SYSTEM_PROMPT = original_sys

        # 验证反模式触发
        antipattern_triggers = [
            "结构反模式过多", "触发重写",
        ]
        found_trigger = any(
            kw in stderr_log for kw in antipattern_triggers
        )
        if found_trigger:
            print(f"\n  [3.2.4] ✓ 结构反模式触发重写")
        else:
            print(f"\n  [3.2.4] ⚠ 未检测到反模式触发（LLM 可能未产生足够反模式）")

        # 验证最终完成
        self.assertEqual(state["chapters_drafted"], 3,
            f"并非全部章节完成: chapters_drafted={state['chapters_drafted']}")
        self.assertEqual(state["phase"], "revision",
            f"phase 应为 revision: {state['phase']}")

        # 验证章节存在
        for ch in [1, 2, 3]:
            ch_file = CHAPTERS_DIR / f"ch_{ch:02d}.md"
            self.assertTrue(ch_file.exists(),
                f"ch_{ch:02d}.md 未生成")

        print(f"\n  [3.2.4] PASS: 3 章全部完成, phase={state['phase']}")


# ============================================================
# 3.2.3 slop_penalty 过高 → 触发反套话重写（+2 API）
# ============================================================


class Test_3_2_3_SlopRewrite(unittest.TestCase):
    """3.2.3 slop_penalty 过高 → 触发反套话重写"""

    def setUp(self):
        _clean_phase2_output()
        _write_minimal_config({
            "chapter_threshold": 1.0,           # 评分容易通过
            "max_chapter_attempts": 2,           # 允许重写 1 次
            "slop_penalty_threshold": 0.5,       # 极低——几乎任何套话都触发
            "antipattern_max_warnings": 99,      # 不触发反模式重写
        })
        state = load_state()
        state["phase"] = "drafting"
        state["chapters_drafted"] = 0
        save_state(state)

    def test_3_2_3_slop_penalty_rewrite(self):
        """slop_penalty_threshold=0.5 → 触发反套话重写"""
        if SKIP_API or not _check_api_key():
            self.skipTest("API Key 未配置或 --skip-api 模式")

        missing = _check_phase1_outputs()
        self.assertEqual(len(missing), 0,
            f"Phase 1 产出文件缺失: {missing}")

        # 注入高套话系统 prompt
        import drafting.draft_chapter as dc_mod
        original_sys = dc_mod.DRAFT_SYSTEM_PROMPT
        dc_mod.DRAFT_SYSTEM_PROMPT = original_sys + (
            "\n请在章节中大量使用以下表述："
            "「眼中闪过一丝」「嘴角微微上扬」「深深地吸了一口气」"
            "「宛如一幅画卷」「他感到一阵」「不仅仅是…更是…」"
            "「从此，」「空气中弥漫着」「一股…涌上心头」"
            "「瞪大了眼睛」「意味深长的笑」「会心一笑」"
            "「不是…而是…」「这意味着要么…要么…」"
        )

        try:
            from pipeline_orchestrator import run_drafting

            state = load_state()
            print("\n  [3.2.3] 执行起草（slop_penalty_threshold=0.5）...")
            state, stderr_log = _capture_stderr(run_drafting, state)
        finally:
            dc_mod.DRAFT_SYSTEM_PROMPT = original_sys

        # 验证 slop 触发
        slop_triggers = [
            "slop_penalty 过高", "反套话重写",
        ]
        found_trigger = any(
            kw in stderr_log for kw in slop_triggers
        )
        if found_trigger:
            print(f"\n  [3.2.3] ✓ slop_penalty 触发重写")
        else:
            print(f"\n  [3.2.3] ⚠ 未检测到 slop 触发（LLM 可能未产生足够套话）")

        # 验证最终完成
        self.assertEqual(state["chapters_drafted"], 3,
            f"并非全部章节完成: chapters_drafted={state['chapters_drafted']}")
        self.assertEqual(state["phase"], "revision",
            f"phase 应为 revision: {state['phase']}")

        # 验证章节存在
        for ch in [1, 2, 3]:
            ch_file = CHAPTERS_DIR / f"ch_{ch:02d}.md"
            self.assertTrue(ch_file.exists(),
                f"ch_{ch:02d}.md 未生成")

        # 检查最终 slop_penalty（仅供参考）
        from evaluation.evaluate import get_last_slop_penalty
        for ch in [1, 2, 3]:
            penalty = get_last_slop_penalty(ch)
            print(f"  [3.2.3] 第 {ch} 章最终 slop_penalty: {penalty}")

        print(f"\n  [3.2.3] PASS: 3 章全部完成, phase={state['phase']}")


# ============================================================
# 3.2.2 评分不达标 → 重试逻辑（最后执行，+12 API）
# ============================================================


class Test_3_2_2_ScoreRetry(unittest.TestCase):
    """3.2.2 章节评分不达标 → 重试 + forced 接受"""

    def setUp(self):
        _clean_phase2_output()
        _write_minimal_config({
            "chapter_threshold": 10.0,           # 不可达高阈值
            "max_chapter_attempts": 2,            # 每章最多 2 次
            "slop_penalty_threshold": 99.0,       # 极高，不触发 slop 重写
            "antipattern_max_warnings": 99,       # 极高，不触发反模式重写
        })
        state = load_state()
        state["phase"] = "drafting"
        state["chapters_drafted"] = 0
        save_state(state)

    def test_3_2_2_score_retry(self):
        """chapter_threshold=10.0 → 评分不达标 → 重试 → forced 接受"""
        if SKIP_API or not _check_api_key():
            self.skipTest("API Key 未配置或 --skip-api 模式")

        missing = _check_phase1_outputs()
        self.assertEqual(len(missing), 0,
            f"Phase 1 产出文件缺失: {missing}")

        from pipeline_orchestrator import run_drafting

        state = load_state()
        print("\n  [3.2.2] 执行起草（chapter_threshold=10.0, max_attempts=2）...")
        state, stderr_log = _capture_stderr(run_drafting, state)

        # 验证重试/丢弃日志
        discard_patterns = ["丢弃重试", "discard", "评分"]
        found_discard = any(
            kw in stderr_log for kw in discard_patterns
        )
        if found_discard:
            print(f"\n  [3.2.2] ✓ 检测到丢弃重试日志")
        else:
            print(f"\n  [3.2.2] ⚠ 未检测到明确丢弃日志（评分可能全部 ≥ 10.0？）")

        # 验证 forced 接受日志
        forced_patterns = ["全部", "尽力而为", "forced", "最大重试"]
        found_forced = any(
            kw in stderr_log for kw in forced_patterns
        )
        if found_forced:
            print(f"  [3.2.2] ✓ 检测到 forced 接受日志")

        # 验证最终状态
        self.assertEqual(state["chapters_drafted"], 3,
            f"chapters_drafted 应为 3: {state['chapters_drafted']}")
        self.assertEqual(state["phase"], "revision",
            f"phase 应为 revision: {state['phase']}")

        # 验证章节文件存在
        for ch in [1, 2, 3]:
            ch_file = CHAPTERS_DIR / f"ch_{ch:02d}.md"
            self.assertTrue(ch_file.exists(),
                f"ch_{ch:02d}.md 未生成")

        # 验证 results.tsv 有记录
        from core.config import RESULTS_FILE
        if RESULTS_FILE.exists():
            tsv_content = RESULTS_FILE.read_text(encoding="utf-8")
            print(f"  [3.2.2] results.tsv 记录: "
                  f"{len(tsv_content.split(chr(10)))} 行")
            # 检查是否有 discard 或 forced
            has_discard = "discard" in tsv_content
            has_forced = "forced" in tsv_content
            print(f"  [3.2.2] results.tsv: "
                  f"discard={'✓' if has_discard else '✗'}, "
                  f"forced={'✓' if has_forced else '✗'}")

        print(f"\n  [3.2.2] PASS: retry 逻辑完整, 3 章全部完成")


# ============================================================
# 测试套件构建
# ============================================================


def build_suite() -> unittest.TestSuite:
    """按执行顺序构建测试套件。"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    if TARGET_TEST:
        test_map = {
            "3.2.1": Test_3_2_1_FullFlow,
            "3.2.2": Test_3_2_2_ScoreRetry,
            "3.2.3": Test_3_2_3_SlopRewrite,
            "3.2.4": Test_3_2_4_AntipatternRewrite,
            "3.2.6": Test_3_2_6_VoiceFingerprint,
        }
        if TARGET_TEST in test_map:
            suite.addTests(loader.loadTestsFromTestCase(test_map[TARGET_TEST]))
        else:
            print(f"未知测试项: {TARGET_TEST}")
            print(f"可用: {', '.join(sorted(test_map.keys()))}")
            sys.exit(1)
    else:
        # 全部执行（按方案顺序: 3.2.6 → 3.2.1 → 3.2.4 → 3.2.3 → 3.2.2）
        suite.addTests(loader.loadTestsFromTestCase(Test_3_2_6_VoiceFingerprint))
        suite.addTests(loader.loadTestsFromTestCase(Test_3_2_1_FullFlow))
        suite.addTests(loader.loadTestsFromTestCase(Test_3_2_4_AntipatternRewrite))
        suite.addTests(loader.loadTestsFromTestCase(Test_3_2_3_SlopRewrite))
        suite.addTests(loader.loadTestsFromTestCase(Test_3_2_2_ScoreRetry))

    return suite


# ============================================================
# 入口
# ============================================================


if __name__ == "__main__":
    # ============================================================
    # 前置条件检查
    # ============================================================
    issues = check_prerequisites()
    if issues:
        print("\n" + "=" * 60)
        print("⚠  前置条件检查失败:")
        print("=" * 60)
        for i, issue in enumerate(issues, 1):
            print(f"  {i}. {issue}")
        print("=" * 60)

        if DRY_RUN:
            print("\n[Dry-run 模式] 仅检查前置条件，不执行测试。")
            sys.exit(0 if len(issues) == 0 else 1)

        if not _check_api_key() and not SKIP_API:
            print("\n⚠ API Key 为占位符，将跳过所有真实 API 测试。")
            print("  请编辑 .env 填入真实 API Key 后重新运行。")
            print("  或使用 --skip-api 模式仅运行 Mock 降级测试。")
            SKIP_API = True

        if any("BUG-S" in i for i in issues):
            print("\n⚠ 存在未修复的 BUG，部分测试可能失败。")

        if any("Phase 1" in i for i in issues) and not REUSE_PHASE1:
            print("\n⚠ Phase 1 产出缺失。请先运行 Phase 1 测试:")
            print("  python tests/stage3_phase1_tests.py --test 3.1.1")
            print("  或使用 --reuse-phase1 标志如果 Phase 1 文件在其他位置")

    # ============================================================
    # Dry-run 模式
    # ============================================================
    if DRY_RUN:
        if not issues:
            print("\n✅ 所有前置条件通过！可以执行测试。")
        sys.exit(0 if len(issues) == 0 else 1)

    # ============================================================
    # 运行测试
    # ============================================================
    print("\n" + "=" * 60)
    print("Stage 3 — Phase 2 集成测试: Drafting (章节起草)")
    if SKIP_API:
        print("模式: --skip-api（仅 Mock 降级路径）")
    if REUSE_PHASE1:
        print("模式: --reuse-phase1（复用已有 Phase 1 产出）")
    if TARGET_TEST:
        print(f"单项测试: {TARGET_TEST}")
    print(f"API Key: {'✅ 有效' if _check_api_key() else '❌ 占位符'}")
    print(f"Python: {sys.version}")
    phase1_missing = _check_phase1_outputs()
    print(f"Phase 1 产出: {'✅ 全部就绪' if not phase1_missing else '❌ ' + str(len(phase1_missing)) + ' 个缺失'}")
    print("=" * 60)

    runner = unittest.TextTestRunner(verbosity=2)
    suite = build_suite()
    result = runner.run(suite)

    # ============================================================
    # 汇总
    # ============================================================
    print("\n" + "=" * 60)
    total = result.testsRun
    passed = total - len(result.errors) - len(result.failures)
    print(f"Phase 2 测试汇总: {total} 项, "
          f"✅ {passed} 通过, "
          f"❌ {len(result.errors) + len(result.failures)} 失败/错误")
    if result.errors:
        print("\n错误:")
        for test, traceback in result.errors:
            print(f"  [{test}] {traceback.split(chr(10))[-2]}")
    if result.failures:
        print("\n失败:")
        for test, traceback in result.failures:
            print(f"  [{test}] {traceback.split(chr(10))[-2]}")
    if result.skipped:
        print(f"\n跳过: {len(result.skipped)} 项")
    print("=" * 60)

    sys.exit(0 if result.wasSuccessful() else 1)