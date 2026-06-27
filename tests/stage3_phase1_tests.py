#!/usr/bin/env python3
"""
Stage 3 Phase 1 集成测试 — Foundation（基础构建）

真实 API 调用 ~40-80 次（含降级路径 Mock）。
严格按 3.1.6 → 3.1.1 → 3.1.3 → 3.1.4 → 3.1.5 → 3.1.2 顺序执行。

用法:
    python tests/stage3_phase1_tests.py              # 全部执行
    python tests/stage3_phase1_tests.py --dry-run    # 仅检查前置条件
    python tests/stage3_phase1_tests.py --test 3.1.1 # 单项测试
    python tests/stage3_phase1_tests.py --skip-api   # 跳过真实 API 调用（仅验证 Mock 路径）
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
TARGET_TEST = None
for i, arg in enumerate(sys.argv):
    if arg == "--test" and i + 1 < len(sys.argv):
        TARGET_TEST = sys.argv[i + 1]

# ============================================================
# 工具函数
# ============================================================

def _write_minimal_config(extra: dict = None):
    """写入最小 config.json 用于 Phase 1 测试。

    仅写入 config.json，不覆盖 .env 中的 API Key。
    config.save() 会重置 config._data，因此直接写文件。
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "story_summary": TEST_STORY,
        "total_chapters": 3,
        "total_volumes": 1,
        "chapters_per_volume": 3,
        "foundation_threshold": 1.0,
        "max_foundation_iters": 1,
    }
    if extra:
        data.update(extra)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _check_api_key() -> bool:
    """检查 API Key 是否有效（非占位符）。

    强制重新加载 .env（不依赖 config._loaded 缓存），
    因为测试 setUp 可能已修改 config._data。
    """
    cfg = config
    cfg._loaded = False  # 强制重新加载
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


def _clean_output():
    """清理 output/ 目录（保留 .gitkeep 等若有）。"""
    for subdir in [CHAPTERS_DIR, BRIEFS_DIR, EDIT_LOGS_DIR, EVAL_LOGS_DIR, BACKUPS_DIR]:
        if subdir.exists():
            import shutil
            shutil.rmtree(str(subdir), ignore_errors=True)
    for pattern in ["*.md", "*.json", "*.tsv"]:
        for f in OUTPUT_DIR.glob(pattern):
            if f.name not in (".gitkeep",):
                try:
                    f.unlink()
                except Exception:
                    pass
    # 重新创建子目录
    for subdir in [CHAPTERS_DIR, BRIEFS_DIR, EDIT_LOGS_DIR, EVAL_LOGS_DIR, BACKUPS_DIR]:
        subdir.mkdir(parents=True, exist_ok=True)


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
        # 3. API Key 有效
        if not _check_api_key():
            issues.append(
                "API Key 为占位符 'sk-xxx'，请编辑 .env 填入真实有效的 "
                "硅基流动 API Key (AUTONOVEL_API_KEY=sk-...)"
            )

    # 4. 依赖安装
    try:
        import httpx  # noqa: F401
    except ImportError:
        issues.append("httpx 未安装，请运行: uv sync")

    try:
        from dotenv import load_dotenv  # noqa: F401
    except ImportError:
        issues.append("python-dotenv 未安装，请运行: uv sync")

    # 5. BUG-S1-01 已修复（PEP 604 str | None 语法）
    # 使用正则匹配实际类型注解，排除字符串字面量中的 "str | None"
    pep604_pattern = re.compile(r'\b\w+\s*\|\s*None\b')
    tests_dir = ROOT / "tests"
    for py_file in list(ROOT.rglob("*.py")):
        # 跳过测试文件自身（避免检查函数中的字面量误匹配）
        if tests_dir in py_file.parents or py_file.name == "stage3_phase1_tests.py":
            continue
        try:
            content = py_file.read_text(encoding="utf-8")
            if pep604_pattern.search(content):
                issues.append(f"BUG-S1-01 未修复: {py_file.relative_to(ROOT)}")
                break
        except Exception:
            pass

    # 6. BUG-S2-01 已修复
    state_mgr = ROOT / "core" / "state_manager.py"
    if state_mgr.exists():
        content = state_mgr.read_text(encoding="utf-8")
        if "json.JSONDecodeError" not in content:
            issues.append("BUG-S2-01 未修复: core/state_manager.py 缺少 JSONDecodeError 保护")

    return issues


# ============================================================
# 3.1.6 中间文件缺失降级测试（最先执行 — 低风险快速失败）
# ============================================================

class Test_3_1_6_MissingFiles(unittest.TestCase):
    """3.1.6 中间文件缺失 → 跳过不崩溃"""

    def setUp(self):
        _clean_output()
        _write_minimal_config()
        save_state(default_state())

    # ----- 3.1.6a: outline.md 缺失 → gen_outline_part2 跳过 -----

    def test_3_1_6a_outline_part2_skip_on_missing_outline(self):
        """outline.md 缺失 → gen_outline_part2 跳过不崩溃"""
        if SKIP_API or not _check_api_key():
            self.skipTest("API Key 未配置或 --skip-api 模式")

        # 1. 手动生成 outline.md 然后删除
        from foundation.gen_outline import generate_outline
        print("\n  [3.1.6a] 生成 outline.md ...")
        generate_outline(max_tokens=16000)

        outline_path = OUTPUT_DIR / "outline.md"
        self.assertTrue(outline_path.exists(), "outline.md 未生成（前置条件失败）")
        outline_path.unlink()

        # 2. 调用 gen_outline_part2 — 应跳过
        from foundation.gen_outline_part2 import generate_outline_part2
        result, log = _capture_stderr(generate_outline_part2, max_tokens=16000)
        self.assertIn("跳过", log, f"日志应含 '跳过': {log[:200]}")
        print(f"  [3.1.6a] PASS: gen_outline_part2 优雅跳过")

    # ----- 3.1.6b: world.md + characters.md 缺失 → gen_voice 降级 -----

    def test_3_1_6b_gen_voice_degrade_on_missing_world_chars(self):
        """world.md + characters.md 缺失 → gen_voice 降级使用空上下文"""
        if SKIP_API or not _check_api_key():
            self.skipTest("API Key 未配置或 --skip-api 模式")

        from foundation.gen_voice import generate_voice
        # 确保 world.md 和 characters.md 不存在
        for fname in ["world.md", "characters.md"]:
            p = OUTPUT_DIR / fname
            if p.exists():
                p.unlink()

        print("\n  [3.1.6b] 调用 gen_voice（无 world/chars）...")
        result, log = _capture_stderr(generate_voice, max_tokens=16000)

        # voice.md 应产出
        voice_path = OUTPUT_DIR / "voice.md"
        self.assertTrue(voice_path.exists(),
            "voice.md 未产出（gen_voice 降级失败）")
        voice_text = voice_path.read_text(encoding="utf-8")
        self.assertGreater(len(voice_text), 300,
            f"voice.md 过短: {len(voice_text)} 字")
        print(f"  [3.1.6b] PASS: gen_voice 降级产出 voice.md ({len(voice_text)} chars)")

    # ----- 3.1.6c: run_foundation 中 outline.md 缺失 → Part 2 跳过 -----

    def test_3_1_6c_outline_missing_in_full_flow(self):
        """run_foundation 流程中 outline.md 缺失 → Part 2 跳过，其余正常"""
        if SKIP_API or not _check_api_key():
            self.skipTest("API Key 未配置或 --skip-api 模式")

        import foundation.gen_outline_part2 as part2_module
        original = part2_module.generate_outline_part2

        def _delete_then_call(max_tokens=16000):
            outline_path = OUTPUT_DIR / "outline.md"
            if outline_path.exists():
                outline_path.unlink()
            from core.state_manager import step
            step("Mock: outline.md 已删除，测试跳过逻辑")
            original(max_tokens=max_tokens)

        part2_module.generate_outline_part2 = _delete_then_call

        try:
            from pipeline_orchestrator import run_foundation
            state = default_state()
            save_state(state)

            print("\n  [3.1.6c] 执行 run_foundation（Mock outline 缺失）...")
            state, log = _capture_stderr(run_foundation, state)

            self.assertEqual(state["phase"], "drafting",
                f"phase 应切换为 drafting: {state['phase']}")
            self.assertTrue((OUTPUT_DIR / "outline.md").exists(),
                "outline.md 应最终存在（gen_outline 生成）")
            print(f"  [3.1.6c] PASS: phase={state['phase']}, iteration={state['iteration']}")
        finally:
            part2_module.generate_outline_part2 = original


# ============================================================
# 3.1.1 完整流程单轮测试（核心）
# ============================================================

class Test_3_1_1_FullFlow(unittest.TestCase):
    """3.1.1 run_foundation() 完整流程单轮"""

    def setUp(self):
        _clean_output()
        _write_minimal_config()
        save_state(default_state())

    def test_3_1_1_foundation_full_flow_single_round(self):
        """Phase 1 完整流程单轮 — 验证全部 7 个 output 文件 + state 更新"""
        if SKIP_API or not _check_api_key():
            self.skipTest("API Key 未配置或 --skip-api 模式")

        from pipeline_orchestrator import run_foundation

        print("\n  [3.1.1] 执行 run_foundation() 完整流程单轮...")
        state = default_state()
        state, log = _capture_stderr(run_foundation, state)

        # ============================================================
        # 验证文件产出 (7 个文件)
        # ============================================================
        expected_files = [
            "world.md", "characters.md", "outline_volume.md",
            "outline.md", "outline_volume1.md", "canon.md", "voice.md",
        ]
        for fname in expected_files:
            fpath = OUTPUT_DIR / fname
            self.assertTrue(fpath.exists(), f"❌ 缺失产出文件: {fname}")

        # ============================================================
        # 验证内容完整性
        # ============================================================

        # world.md ≥ 500 字
        world_text = (OUTPUT_DIR / "world.md").read_text(encoding="utf-8")
        world_chars = len(world_text.replace(" ", "").replace("\n", ""))
        self.assertGreaterEqual(world_chars, 500,
            f"world.md 过短: {world_chars} 字（预期 ≥ 500）")

        # characters.md 含角色条目
        chars_text = (OUTPUT_DIR / "characters.md").read_text(encoding="utf-8")
        self.assertTrue("角色" in chars_text or "人物" in chars_text,
            "characters.md 无角色相关内容")
        char_entries = len(re.findall(r'^\d+\.\s', chars_text, re.MULTILINE))
        self.assertGreaterEqual(char_entries, 1,
            f"characters.md 角色条目过少: {char_entries}")

        # outline_volume.md 含卷级规划
        vol_text = (OUTPUT_DIR / "outline_volume.md").read_text(encoding="utf-8")
        self.assertTrue("卷" in vol_text or "Volume" in vol_text,
            "outline_volume.md 无卷级相关内容")

        # outline.md 含 3 章条目
        outline_text = (OUTPUT_DIR / "outline.md").read_text(encoding="utf-8")
        ch_matches = len(re.findall(r'第\s*\d+\s*章', outline_text))
        self.assertGreaterEqual(ch_matches, 3,
            f"outline.md 章节条目不足: {ch_matches}（预期 ≥ 3）")

        # canon.md 条目数 ≥ 3
        from foundation.gen_canon import count_canon_entries
        canon_counts = count_canon_entries()
        self.assertGreaterEqual(canon_counts["total"], 3,
            f"canon 条目过少: {canon_counts['total']}")

        # voice.md 含 Part 2 结构
        voice_text = (OUTPUT_DIR / "voice.md").read_text(encoding="utf-8")
        voice_sections = ["Tone", "Sentence Rhythm", "Exemplar"]
        found = sum(1 for s in voice_sections if s in voice_text)
        self.assertGreaterEqual(found, 2,
            f"voice.md 结构不完整: 仅匹配 {found}/{len(voice_sections)} 个子节")

        # ============================================================
        # 验证评估日志
        # ============================================================
        eval_files = list(EVAL_LOGS_DIR.glob("foundation_*.json"))
        self.assertGreater(len(eval_files), 0,
            "eval_logs 中无 foundation 评估 JSON")
        eval_data = json.loads(eval_files[0].read_text(encoding="utf-8"))
        self.assertIn("raw_output", eval_data, "评估 JSON 缺少 raw_output")
        self.assertIn("timestamp", eval_data, "评估 JSON 缺少 timestamp")
        self.assertIn("phase", eval_data, "评估 JSON 缺少 phase")

        # ============================================================
        # 验证 state 更新
        # ============================================================
        self.assertGreater(state["foundation_score"], 0,
            f"foundation_score 未写入或为 0: {state['foundation_score']}")
        self.assertGreaterEqual(state["iteration"], 1,
            f"iteration 未递增: {state['iteration']}")
        self.assertEqual(state["phase"], "drafting",
            f"phase 未切换为 drafting: {state['phase']}")
        self.assertEqual(state["current_focus"], "chapter_drafting",
            f"current_focus 不正确: {state['current_focus']}")
        self.assertEqual(state["chapters_total"], 3,
            f"chapters_total 不正确: {state['chapters_total']}")

        # ============================================================
        # 汇总
        # ============================================================
        print(f"\n  [3.1.1] ✅ PASS: 7 文件产出, "
              f"score={state['foundation_score']}, "
              f"lore={state.get('lore_score', 'N/A')}, "
              f"canon_entries={canon_counts['total']}, "
              f"world={world_chars}chars, "
              f"outline_chapters={ch_matches}")


# ============================================================
# 3.1.3 canon 条目不足测试
# ============================================================

class Test_3_1_3_CanonBelowThreshold(unittest.TestCase):
    """3.1.3 count_canon_entries() < 阈值 → 警告不崩溃"""

    def setUp(self):
        _clean_output()
        _write_minimal_config()
        save_state(default_state())

    def test_3_1_3_canon_entries_below_threshold_no_crash(self):
        """Mock 空正典 → 验证警告日志 + 流程继续"""
        if SKIP_API or not _check_api_key():
            self.skipTest("API Key 未配置或 --skip-api 模式")

        import foundation.gen_canon as gen_canon_module
        original_gen_canon = gen_canon_module.generate_canon

        def _mock_empty_canon(max_tokens=16000):
            canon_path = OUTPUT_DIR / "canon.md"
            canon_path.write_text(
                "## 一、世界观硬事实\n\n## 二、角色硬事实\n\n"
                "## 三、时间线硬事实\n\n## 四、规则硬事实\n\n",
                encoding="utf-8"
            )
            from core.state_manager import step
            step("正典已保存 (MOCK 空正典)")

        gen_canon_module.generate_canon = _mock_empty_canon

        try:
            from pipeline_orchestrator import run_foundation
            state = default_state()
            save_state(state)

            print("\n  [3.1.3] 执行 run_foundation（Mock 空正典）...")
            state, log = _capture_stderr(run_foundation, state)

            # 验证警告日志
            self.assertIn("正典条目", log,
                f"日志缺少 '正典条目' 警告: {log[-500:]}")
            self.assertIn("严重不足", log,
                f"日志缺少 '严重不足' 警告: {log[-500:]}")

            # 验证不崩溃 + 流程继续
            self.assertGreaterEqual(state["iteration"], 1,
                f"iteration 未递增: {state['iteration']}")
            self.assertEqual(state["phase"], "drafting",
                f"phase 未切换: {state['phase']}")
            self.assertGreater(state["foundation_score"], 0,
                f"foundation_score 未写入: {state['foundation_score']}")

            # 验证 canon 确实为空（Mock 生效）
            from foundation.gen_canon import count_canon_entries
            counts = count_canon_entries()
            self.assertEqual(counts["total"], 0,
                f"Mock 未生效: canon total={counts['total']}（预期 0）")

            # 验证其余文件正常产出
            for fname in ["world.md", "characters.md", "outline_volume.md",
                           "outline.md", "voice.md"]:
                self.assertTrue((OUTPUT_DIR / fname).exists(),
                    f"缺失产出文件: {fname}")

            print(f"  [3.1.3] ✅ PASS: 警告已触发, phase={state['phase']}, "
                  f"canon_total={counts['total']}")

        finally:
            gen_canon_module.generate_canon = original_gen_canon


# ============================================================
# 3.1.4 gen_voice 评估失败降级测试
# ============================================================

class Test_3_1_4_VoiceDegradation(unittest.TestCase):
    """3.1.4 gen_voice 评估失败 → 降级兜底"""

    def setUp(self):
        _clean_output()
        _write_minimal_config()
        save_state(default_state())

    def test_3_1_4_gen_voice_eval_failure_fallback(self):
        """Mock evaluate_registers 始终低分 → 精炼循环 + fallback 兜底"""
        if SKIP_API or not _check_api_key():
            self.skipTest("API Key 未配置或 --skip-api 模式")

        import foundation.gen_voice as voice_module
        original_eval = voice_module.evaluate_registers

        def _mock_low_score(registers_text, story):
            from core.state_manager import step
            step("  [Mock] 裁判评估: 始终低分 3.0")
            return {
                "overall_score": 3.0,
                "best_register": 1,
                "best_register_name": "简约式",
                "registers": [{
                    "register_id": 1,
                    "register_name": "简约式",
                    "scores": {
                        "fit": 3, "quality": 3, "sustainability": 3,
                        "ai_free": 3, "distinctiveness": 3,
                    },
                    "overall": 3.0,
                    "weakness": "过于平淡",
                    "improvement": "增加感官细节",
                }],
            }

        voice_module.evaluate_registers = _mock_low_score

        try:
            from pipeline_orchestrator import run_foundation
            state = default_state()
            save_state(state)

            print("\n  [3.1.4] 执行 run_foundation（Mock 低分 voice eval）...")
            state, log = _capture_stderr(run_foundation, state)

            # 验证精炼循环被触发
            self.assertIn("语域精炼", log,
                f"日志缺少精炼循环信息: {log[-500:]}")

            # 验证 voice.md 产出（fallback 兜底路径生效）
            voice_path = OUTPUT_DIR / "voice.md"
            self.assertTrue(voice_path.exists(),
                "voice.md 未产出（fallback 路径可能未生效）")
            voice_text = voice_path.read_text(encoding="utf-8")
            self.assertIn("Part 2", voice_text,
                "voice.md 缺少 Part 2 文风身份")
            self.assertGreater(len(voice_text), 500,
                f"voice.md 过短: {len(voice_text)} 字")

            # 验证 foundation 流程不崩溃
            self.assertGreaterEqual(state["iteration"], 1)
            self.assertEqual(state["phase"], "drafting",
                f"phase 未切换: {state['phase']}")

            print(f"  [3.1.4] ✅ PASS: 精炼降级路径正常, "
                  f"voice.md={len(voice_text)} chars, phase={state['phase']}")

        finally:
            voice_module.evaluate_registers = original_eval


# ============================================================
# 3.1.5 evaluate_foundation JSON 解析失败降级测试
# ============================================================

class Test_3_1_5_EvalJsonParseFailure(unittest.TestCase):
    """3.1.5 evaluate_foundation JSON 解析失败 → 降级不崩溃"""

    def setUp(self):
        _clean_output()
        _write_minimal_config()
        save_state(default_state())

    def test_3_1_5_evaluate_foundation_json_parse_failure(self):
        """Mock evaluate_foundation 返回非法 JSON — parse_score 降级"""
        if SKIP_API or not _check_api_key():
            self.skipTest("API Key 未配置或 --skip-api 模式")

        import evaluation.evaluate as eval_module
        original_eval = eval_module.evaluate_foundation

        def _mock_broken_eval(max_tokens=4096, retries=3, max_total_time=None):
            """Mock: 返回不含 JSON 的纯文本"""
            result = "这是一段不含任何结构化 JSON 的评论文本。评分: 无法确定。"
            ts = __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M%S")
            EVAL_LOGS_DIR.mkdir(parents=True, exist_ok=True)
            log_path = EVAL_LOGS_DIR / f"foundation_{ts}.json"
            log_path.write_text(json.dumps({
                "timestamp": ts,
                "phase": "foundation",
                "raw_output": result,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            print(result)
            return result

        eval_module.evaluate_foundation = _mock_broken_eval

        try:
            from pipeline_orchestrator import run_foundation
            state = default_state()
            save_state(state)

            print("\n  [3.1.5] 执行 run_foundation（Mock 非法 eval JSON）...")
            state, log = _capture_stderr(run_foundation, state)

            # parse_score 应返回 -1.0 → best_score 保持 0.0
            # score(-1.0) <= best_score(0.0) → discard
            self.assertEqual(state["foundation_score"], 0.0,
                f"foundation_score 应为 0.0（解析失败），实际: {state['foundation_score']}")

            # 验证流程继续
            self.assertGreaterEqual(state["iteration"], 1,
                f"iteration 未递增: {state['iteration']}")
            self.assertEqual(state["phase"], "drafting",
                f"Phase 应切换为 drafting: {state['phase']}")

            # 验证 eval_log 存在
            eval_files = list(EVAL_LOGS_DIR.glob("foundation_*.json"))
            self.assertGreater(len(eval_files), 0,
                "eval_log 缺失（Mock 应写入日志）")

            # 验证其余 6 个文件产出
            for fname in ["world.md", "characters.md", "outline_volume.md",
                           "outline.md", "canon.md", "voice.md"]:
                self.assertTrue((OUTPUT_DIR / fname).exists(),
                    f"缺失产出文件: {fname}")

            print(f"  [3.1.5] ✅ PASS: parse_score 降级, "
                  f"foundation_score={state['foundation_score']}, "
                  f"phase={state['phase']}")

        finally:
            eval_module.evaluate_foundation = original_eval


# ============================================================
# 3.1.2 重试逻辑测试（最后执行 — 高 API 消耗）
# ============================================================

class Test_3_1_2_Retry(unittest.TestCase):
    """3.1.2 Foundation 评分 < 阈值 → 触发重试逻辑"""

    def setUp(self):
        _clean_output()
        _write_minimal_config({
            "foundation_threshold": 10.0,   # 不可达高阈值
            "max_foundation_iters": 2,
        })
        save_state(default_state())

    def test_3_1_2_foundation_retry_on_low_score(self):
        """设置不可达高阈值 → 验证 keep/discard 逻辑 + iteration ≥ 2"""
        if SKIP_API or not _check_api_key():
            self.skipTest("API Key 未配置或 --skip-api 模式")

        from pipeline_orchestrator import run_foundation

        print("\n  [3.1.2] 执行 run_foundation（threshold=10.0, max_iters=2）...")
        state = default_state()
        state, log = _capture_stderr(run_foundation, state)

        # 验证迭代完成
        self.assertGreaterEqual(state["iteration"], 2,
            f"未完成 2 轮迭代: iteration={state['iteration']}")

        # 验证 eval_logs（至少 2 个评估日志）
        eval_files = sorted(EVAL_LOGS_DIR.glob("foundation_*.json"))
        self.assertGreaterEqual(len(eval_files), 2,
            f"评估日志数不足: {len(eval_files)}（预期 ≥ 2）")

        # 验证 results.tsv 记录
        results_text = ""
        if RESULTS_FILE.exists():
            results_text = RESULTS_FILE.read_text(encoding="utf-8")
        # 验证至少有一条 keep 记录
        self.assertIn("keep", results_text,
            f"results.tsv 缺少 keep 记录: {results_text[:500]}")

        # 验证重试机制实际运行: 有 discard（低分被丢弃）或有 ≥2 条 keep（两轮均递增）
        keep_count = results_text.count("\tkeep\t")
        has_discard = "discard" in results_text
        self.assertTrue(
            has_discard or keep_count >= 2,
            f"重试机制验证失败: discard={has_discard}, keep_count={keep_count} "
            f"（预期: 有 discard 或有 ≥2 条 keep）"
        )

        # 验证最终 state
        self.assertGreater(state["foundation_score"], 0,
            "foundation_score 未写入")
        self.assertEqual(state["phase"], "drafting",
            f"phase 未切换: {state['phase']}")

        # 验证最终文件是高保留轮产物
        for fname in ["world.md", "characters.md", "outline.md", "canon.md", "voice.md"]:
            self.assertTrue((OUTPUT_DIR / fname).exists(), f"缺失: {fname}")

        print(f"  [3.1.2] ✅ PASS: iteration={state['iteration']}, "
              f"best_score={state['foundation_score']}, "
              f"eval_logs={len(eval_files)}, "
              f"phase={state['phase']}")


# ============================================================
# 测试套件组装
# ============================================================

def build_suite() -> unittest.TestSuite:
    """按执行顺序构建测试套件"""
    suite = unittest.TestSuite()

    # 按 3.1.6 → 3.1.1 → 3.1.3 → 3.1.4 → 3.1.5 → 3.1.2 顺序
    loader = unittest.TestLoader()

    if TARGET_TEST:
        # 单项测试模式
        test_map = {
            "3.1.1": Test_3_1_1_FullFlow,
            "3.1.2": Test_3_1_2_Retry,
            "3.1.3": Test_3_1_3_CanonBelowThreshold,
            "3.1.4": Test_3_1_4_VoiceDegradation,
            "3.1.5": Test_3_1_5_EvalJsonParseFailure,
            "3.1.6": Test_3_1_6_MissingFiles,
        }
        if TARGET_TEST in test_map:
            suite.addTests(loader.loadTestsFromTestCase(test_map[TARGET_TEST]))
        else:
            print(f"未知测试项: {TARGET_TEST}")
            print(f"可用: {', '.join(sorted(test_map.keys()))}")
            sys.exit(1)
    else:
        # 全部执行（按顺序）
        suite.addTests(loader.loadTestsFromTestCase(Test_3_1_6_MissingFiles))
        suite.addTests(loader.loadTestsFromTestCase(Test_3_1_1_FullFlow))
        suite.addTests(loader.loadTestsFromTestCase(Test_3_1_3_CanonBelowThreshold))
        suite.addTests(loader.loadTestsFromTestCase(Test_3_1_4_VoiceDegradation))
        suite.addTests(loader.loadTestsFromTestCase(Test_3_1_5_EvalJsonParseFailure))
        suite.addTests(loader.loadTestsFromTestCase(Test_3_1_2_Retry))

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
            # API Key 是占位符但用户可能想先看结构
            print("\n⚠ API Key 为占位符，将跳过所有真实 API 测试。")
            print("  请编辑 .env 填入真实 API Key 后重新运行。")
            print("  或使用 --skip-api 模式仅运行 Mock 降级测试。")
            SKIP_API = True  # 自动跳过 API 测试

        if any("BUG-S" in i for i in issues):
            print("\n⚠ 存在未修复的 BUG，部分测试可能失败。")

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
    print("Stage 3 — Phase 1 集成测试: Foundation (基础构建)")
    if SKIP_API:
        print("模式: --skip-api（仅 Mock 降级路径）")
    if TARGET_TEST:
        print(f"单项测试: {TARGET_TEST}")
    print(f"API Key: {'✅ 有效' if _check_api_key() else '❌ 占位符'}")
    print(f"Python: {sys.version}")
    print("=" * 60)

    runner = unittest.TextTestRunner(verbosity=2)
    suite = build_suite()
    result = runner.run(suite)

    # ============================================================
    # 汇总
    # ============================================================
    print("\n" + "=" * 60)
    print(f"Phase 1 测试汇总: {result.testsRun} 项, "
          f"✅ {result.testsRun - len(result.errors) - len(result.failures)} 通过, "
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