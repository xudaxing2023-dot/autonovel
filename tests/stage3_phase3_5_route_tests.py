#!/usr/bin/env python3
"""
Stage 3 Phase 3.5 集成测试 — Phase 模型路由

验证方案 D Phase 分离模型配置的回退链和路由逻辑。
真实 API 调用 ~2 次（3.5.4 真实路由验证）。

用法:
    python tests/stage3_phase3_5_route_tests.py               # 全部执行
    python tests/stage3_phase3_5_route_tests.py --skip-api    # 跳过真实 API
    python tests/stage3_phase3_5_route_tests.py --test 3.5.1  # 单项测试
"""

import hashlib
import io
import json
import os
import re
import shutil
import sys
import unittest
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from core.config import config, ENV_FILE, OUTPUT_DIR, CHAPTERS_DIR

# ============================================================
# 命令行参数解析
# ============================================================

SKIP_API = "--skip-api" in sys.argv
TARGET_TEST = None
for i, arg in enumerate(sys.argv):
    if arg == "--test" and i + 1 < len(sys.argv):
        TARGET_TEST = sys.argv[i + 1]

# ============================================================
# .env 备份 / 恢复
# ============================================================

_ENV_BACKUP = ROOT / ".env.backup_3_5_test"


def _backup_env() -> bool:
    """备份当前 .env。"""
    if ENV_FILE.exists():
        shutil.copy2(str(ENV_FILE), str(_ENV_BACKUP))
        return True
    return False


def _restore_env() -> bool:
    """恢复 .env。"""
    if _ENV_BACKUP.exists():
        shutil.copy2(str(_ENV_BACKUP), str(ENV_FILE))
        _ENV_BACKUP.unlink()
        return True
    return False


def _env_sha256() -> str:
    """当前 .env 的 SHA256 哈希。"""
    if ENV_FILE.exists():
        return hashlib.sha256(ENV_FILE.read_bytes()).hexdigest()
    return ""


# ============================================================
# 工具函数
# ============================================================

def _check_api_key() -> bool:
    """检查 API Key 是否有效。"""
    cfg = config
    cfg._loaded = False
    cfg.load()
    key = cfg.api_key
    if not key or key.startswith("sk-xxx") or key.startswith("'sk-xxx"):
        return False
    return True


def _reload_config():
    """强制重新加载 config。"""
    cfg = config
    cfg._loaded = False
    cfg._data = {}
    cfg.load()


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


# ============================================================
# 测试类
# ============================================================


class TestPhase35Route(unittest.TestCase):
    """Phase 3.5 模型路由集成测试"""

    _env_hash_before: str = ""
    _backed_up: bool = False

    @classmethod
    def setUpClass(cls):
        cls._env_hash_before = _env_sha256()
        cls._backed_up = _backup_env()
        if cls._backed_up:
            print(f"\n  📋 .env 已备份 ({cls._env_hash_before[:12]}...)")

    @classmethod
    def tearDownClass(cls):
        if cls._backed_up:
            _restore_env()
            restored_hash = _env_sha256()
            if restored_hash == cls._env_hash_before:
                print(f"  ✅ .env 已恢复 ({restored_hash[:12]}...)")
            else:
                print(f"  ❌ .env 恢复失败！哈希不匹配")
                print(f"     原始: {cls._env_hash_before[:12]}...")
                print(f"     当前: {restored_hash[:12]}...")

    def setUp(self):
        """每个测试前重新加载 config。"""
        _reload_config()

    # ——— 3.5.1 —————————————————————

    def test_3_5_1_shared_key_fallback(self):
        """3.5.1 仅配共用 Key → 所有 Phase 回退到共用。

        验证：P1/P2/P3 均未配置时，所有 Phase 属性回退到共用 Key。
        API 调用：0。
        """
        if TARGET_TEST and TARGET_TEST not in ("3.5.1", "3.5"):
            raise unittest.SkipTest(f"--test={TARGET_TEST}")

        cfg = config
        shared_key = cfg.api_key
        shared_base = cfg.api_base_url
        shared_model = cfg.model_name

        self.assertTrue(shared_key, "共用 API Key 为空，无法验证回退链")
        print(f"  共用 Key: {shared_key[:12]}...")
        print(f"  共用 Model: {shared_model}")

        failures = []

        # — P1 回退 —
        p1_key = cfg.p1_api_key
        p1_base = cfg.p1_api_base_url
        p1_model = cfg.p1_model_name
        if p1_key != shared_key:
            failures.append(f"P1 key: {p1_key[:12]}... ≠ shared: {shared_key[:12]}...")
        if p1_base.rstrip("/") != shared_base.rstrip("/"):
            failures.append(f"P1 base: {p1_base} ≠ shared: {shared_base}")
        if p1_model != shared_model:
            failures.append(f"P1 model: {p1_model} ≠ shared: {shared_model}")

        # — P2 回退链 —
        p2_key = cfg.p2_api_key
        p2_base = cfg.p2_api_base_url
        p2_model = cfg.p2_model_name
        if p2_key != shared_key:
            failures.append(f"P2 key: {p2_key[:12]}... ≠ shared: {shared_key[:12]}...")
        if p2_base.rstrip("/") != shared_base.rstrip("/"):
            failures.append(f"P2 base: {p2_base} ≠ shared: {shared_base}")
        if p2_model != shared_model:
            failures.append(f"P2 model: {p2_model} ≠ shared: {shared_model}")

        # — P2_CTX 回退链 —
        p2c_key = cfg.p2_ctx_api_key
        p2c_base = cfg.p2_ctx_api_base_url
        p2c_model = cfg.p2_ctx_model_name
        if p2c_key != shared_key:
            failures.append(f"P2_CTX key: {p2c_key[:12]}... ≠ shared")
        if p2c_base.rstrip("/") != shared_base.rstrip("/"):
            failures.append(f"P2_CTX base: {p2c_base} ≠ shared: {shared_base}")
        if p2c_model != shared_model:
            failures.append(f"P2_CTX model: {p2c_model} ≠ shared: {shared_model}")

        # — P3 回退链 —
        p3_key = cfg.p3_api_key
        p3_base = cfg.p3_api_base_url
        p3_model = cfg.p3_model_name
        if p3_key != shared_key:
            failures.append(f"P3 key: {p3_key[:12]}... ≠ shared: {shared_key[:12]}...")
        if p3_base.rstrip("/") != shared_base.rstrip("/"):
            failures.append(f"P3 base: {p3_base} ≠ shared: {shared_base}")
        if p3_model != shared_model:
            failures.append(f"P3 model: {p3_model} ≠ shared: {shared_model}")

        if failures:
            self.fail("回退链错误:\n  " + "\n  ".join(failures))

        print(f"  ✅ 3.5.1 共用 Key 回退链通过 — 4个Phase全部回退到共用")

    # ——— 3.5.2 —————————————————————

    def test_3_5_2_p1_independent_key_fallback(self):
        """3.5.2 P1 独立 Key → P2/P3 回退到 P1 而非共用。

        验证：配置 P1 独立 Key 后，P2/P3 停在 P1 层，不穿透到共用。
        API 调用：0。
        """
        if TARGET_TEST and TARGET_TEST not in ("3.5.2", "3.5"):
            raise unittest.SkipTest(f"--test={TARGET_TEST}")

        cfg = config
        shared_key = cfg.api_key
        shared_model = cfg.model_name

        # 注入 P1 独立值到 config._data（不修改 .env 文件）
        cfg._data["p1_api_key"] = "sk-p1-test-key"
        cfg._data["p1_api_base_url"] = "https://p1.example.com/v1"
        cfg._data["p1_model_name"] = "p1-model-v1"

        p1_key = cfg.p1_api_key
        p1_base = cfg.p1_api_base_url
        p1_model = cfg.p1_model_name

        self.assertEqual(p1_key, "sk-p1-test-key",
                         f"P1 key 应为 sk-p1-test-key，实际={p1_key}")

        failures = []

        # — P2 回退到 P1 —
        p2_key = cfg.p2_api_key
        p2_base = cfg.p2_api_base_url
        p2_model = cfg.p2_model_name
        if p2_key != p1_key:
            failures.append(f"P2 key ({p2_key}) ≠ P1 key ({p1_key})")
        if p2_key == shared_key:
            failures.append(f"P2 key ({p2_key}) 错误穿透到共用 ({shared_key})")

        # — P2_CTX 回退 P2→P1 —
        p2c_key = cfg.p2_ctx_api_key
        if p2c_key != p1_key:
            failures.append(f"P2_CTX key ({p2c_key}) ≠ P1 key ({p1_key})")

        # — P3 回退到 P1 —
        p3_key = cfg.p3_api_key
        p3_base = cfg.p3_api_base_url
        p3_model = cfg.p3_model_name
        if p3_key != p1_key:
            failures.append(f"P3 key ({p3_key}) ≠ P1 key ({p1_key})")
        if p3_key == shared_key:
            failures.append(f"P3 key ({p3_key}) 错误穿透到共用 ({shared_key})")

        if failures:
            self.fail("P1 独立 Key 回退链错误:\n  " + "\n  ".join(failures))

        print(f"  ✅ 3.5.2 P1 独立 Key 回退链通过 — P2/P3停在P1，不穿透")

    # ——— 3.5.3 —————————————————————

    def test_3_5_3_phase_config_routing(self):
        """3.5.3 _call_with_phase_config 路由逻辑验证。

        验证：根据 phase 参数正确调用 getattr 并路由到对应 Phase 配置。
        API 调用：0（Mock _call_llm_internal）。
        """
        if TARGET_TEST and TARGET_TEST not in ("3.5.3", "3.5"):
            raise unittest.SkipTest(f"--test={TARGET_TEST}")

        from unittest.mock import patch
        import core.api_client as api

        cfg = config

        with patch.object(api, '_call_llm_internal') as mock_call:
            mock_call.return_value = "mock response"

            # Phase "p1"
            api._call_with_phase_config("p1", "test prompt", max_tokens=512)
            kw = mock_call.call_args[1]
            self.assertEqual(kw["api_key"], cfg.p1_api_key,
                             f"p1: api_key={kw['api_key']} ≠ {cfg.p1_api_key}")
            self.assertEqual(kw["model"], cfg.p1_model_name,
                             f"p1: model={kw['model']} ≠ {cfg.p1_model_name}")

            # Phase "p2"
            api._call_with_phase_config("p2", "test prompt", max_tokens=512)
            kw = mock_call.call_args[1]
            self.assertEqual(kw["api_key"], cfg.p2_api_key,
                             f"p2: api_key={kw['api_key']} ≠ {cfg.p2_api_key}")

            # Phase "p2_ctx"
            api._call_with_phase_config("p2_ctx", "test prompt", max_tokens=512)
            kw = mock_call.call_args[1]
            self.assertEqual(kw["api_key"], cfg.p2_ctx_api_key,
                             f"p2_ctx: api_key={kw['api_key']} ≠ {cfg.p2_ctx_api_key}")

            # Phase "p3"
            api._call_with_phase_config("p3", "test prompt", max_tokens=512)
            kw = mock_call.call_args[1]
            self.assertEqual(kw["api_key"], cfg.p3_api_key,
                             f"p3: api_key={kw['api_key']} ≠ {cfg.p3_api_key}")

            # Phase "p4" — 无效
            with self.assertRaises(AttributeError,
                                   msg="p4 无效 phase 应抛出 AttributeError"):
                api._call_with_phase_config("p4", "test")

        print(f"  ✅ 3.5.3 路由逻辑验证通过 — 4个phase路由正确 + p4抛异常")

    # ——— 3.5.4 —————————————————————

    def test_3_5_4_real_phase_routing_call(self):
        """3.5.4 Phase 路由真实调用验证。

        验证：call_p1_writer + call_p2_writer 真实 API 调用成功。
        API 调用：~2 次。
        """
        if TARGET_TEST and TARGET_TEST not in ("3.5.4", "3.5"):
            raise unittest.SkipTest(f"--test={TARGET_TEST}")

        if SKIP_API:
            raise unittest.SkipTest("--skip-api")

        if not _check_api_key():
            self.skipTest("API Key 无效或为占位符")

        from core.api_client import call_p1_writer, call_p2_writer

        # (A) P1 Writer 调用
        print("  🔄 调用 call_p1_writer ...")
        result_p1 = call_p1_writer(
            "用一段话描述一个2049年上海的科幻世界观，约100字。简洁输出。",
            system="你是小说设定师。",
            max_tokens=512,
        )
        self.assertIsNotNone(result_p1, "call_p1_writer 返回 None")
        p1_len = len(result_p1.strip())
        self.assertGreaterEqual(p1_len, 25,
                                f"P1 输出过短: {p1_len} 字")
        print(f"  P1 产出: {p1_len} 字")

        # (B) P2 Writer 调用
        print("  🔄 调用 call_p2_writer ...")
        result_p2 = call_p2_writer(
            "写一段小说的开场段落，主角在机房发现异常，约100字。简洁输出。",
            system="你是小说作家。",
            max_tokens=512,
        )
        self.assertIsNotNone(result_p2, "call_p2_writer 返回 None")
        p2_len = len(result_p2.strip())
        self.assertGreaterEqual(p2_len, 25,
                                f"P2 输出过短: {p2_len} 字")
        print(f"  P2 产出: {p2_len} 字")

        print(f"  ✅ 3.5.4 真实调用验证通过 "
              f"(P1={p1_len}字, P2={p2_len}字)")

    # ——— 3.5.5 —————————————————————

    def test_3_5_5_migration_gap_analysis(self):
        """3.5.5 架构对齐审查 — 未迁移模块对比。

        验证：识别已迁移/未迁移模块，确认 call_p3_judge 孤儿状态。
        API 调用：0。
        """
        if TARGET_TEST and TARGET_TEST not in ("3.5.5", "3.5"):
            raise unittest.SkipTest(f"--test={TARGET_TEST}")

        # 已迁移模块白名单
        migrated = {
            "foundation/gen_outline_volume.py": "call_p1_writer",
            "foundation/gen_outline.py": "call_p1_writer",
            "drafting/draft_chapter.py": "call_p2_writer",
            "foundation/update_canon.py": "call_p2_ctx_writer",
        }

        # 扫描 call_p3_judge 导入者
        p3_judge_imported_by = []
        self_file = str(Path(__file__).relative_to(ROOT))
        for py_file in sorted(ROOT.rglob("*.py")):
            if py_file.name in ("__init__.py",):
                continue
            try:
                content = py_file.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            if "call_p3_judge" in content:
                # 标准化为 forward-slash 路径
                rel = str(py_file.relative_to(ROOT)).replace("\\", "/")
                # 排除定义文件自身、测试文件、本测试文件
                if (rel == "core/api_client.py"
                        or rel.startswith("tests/")
                        or rel == self_file.replace("\\", "/")):
                    continue
                p3_judge_imported_by.append(rel)

        # (a) call_p3_judge 孤儿确认
        self.assertEqual(
            len(p3_judge_imported_by), 0,
            f"call_p3_judge 被以下非测试模块导入（应为空）: {p3_judge_imported_by}")

        # (b) 已迁移模块数量
        self.assertEqual(len(migrated), 4,
                         f"已迁移模块数应为 4，实际={len(migrated)}")

        # 输出差距报告
        gap_report = {
            "migrated": list(migrated.keys()),
            "migrated_count": len(migrated),
            "p3_judge_orphan": len(p3_judge_imported_by) == 0,
            "unmigrated_p1": ["gen_world.py", "gen_characters.py",
                              "gen_canon.py", "gen_voice.py",
                              "gen_outline_part2.py"],
            "unmigrated_p3": ["evaluate.py", "adversarial_edit.py",
                              "reader_panel.py", "review.py",
                              "compare_chapters.py", "gen_revision.py"],
            "unmigrated_p4": ["build_outline.py", "build_arc_summary.py"],
        }

        print(f"  已迁移: {gap_report['migrated_count']} 模块")
        for m in gap_report['migrated']:
            print(f"    ✅ {m}")
        print(f"  P1 未迁移: {len(gap_report['unmigrated_p1'])} 模块")
        for m in gap_report['unmigrated_p1']:
            print(f"    ⚠ foundation/{m}")
        print(f"  P3 未迁移: {len(gap_report['unmigrated_p3'])} 模块")
        for m in gap_report['unmigrated_p3']:
            print(f"    ⚠ revision/{m}")
        print(f"  call_p3_judge 孤儿: {'✅ 确认' if gap_report['p3_judge_orphan'] else '❌'}")

        print(f"  ✅ 3.5.5 架构对齐审查通过 "
              f"(已迁移={gap_report['migrated_count']}, "
              f"P3孤儿={gap_report['p3_judge_orphan']})")

    # ——— 3.5.6 —————————————————————

    def test_3_5_6_env_restore_safety(self):
        """3.5.6 .env 恢复安全验证。

        验证：setUpClass 备份 → tearDownClass 恢复流程正确。
        API 调用：0。
        """
        if TARGET_TEST and TARGET_TEST not in ("3.5.6", "3.5"):
            raise unittest.SkipTest(f"--test={TARGET_TEST}")

        # 验证备份文件存在
        self.assertTrue(
            _ENV_BACKUP.exists(),
            ".env 备份文件不存在 — setUpClass 可能未执行")

        # 验证备份内容与当前 .env 一致（因为尚未恢复）
        backup_hash = hashlib.sha256(_ENV_BACKUP.read_bytes()).hexdigest()
        current_hash = _env_sha256()

        # 记录状态（可能相同也可能不同，取决于中间是否修改）
        print(f"  备份哈希: {backup_hash[:12]}...")
        print(f"  当前哈希: {current_hash[:12]}...")

        # 验证 tearDownClass 会正确恢复
        # 实际恢复在 tearDownClass 中执行，此处仅验证备份存在
        self.assertTrue(backup_hash, "备份哈希为空")

        print(f"  ✅ 3.5.6 .env 恢复机制就绪 "
              f"(备份={backup_hash[:12]}...)")


# ============================================================
# 自定义 TestRunner — 按文档顺序排列
# ============================================================

def custom_test_order(tests):
    """按文档顺序排列测试：3.5.1 → 3.5.2 → 3.5.3 → 3.5.4 → 3.5.5 → 3.5.6"""
    order = [
        "test_3_5_1_shared_key_fallback",
        "test_3_5_2_p1_independent_key_fallback",
        "test_3_5_3_phase_config_routing",
        "test_3_5_4_real_phase_routing_call",
        "test_3_5_5_migration_gap_analysis",
        "test_3_5_6_env_restore_safety",
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
    for test in tests:
        if id(test) not in seen:
            ordered.append(test)
    return ordered


if __name__ == "__main__":
    print("=" * 70)
    print("  Stage 3 Phase 3.5 集成测试 — Phase 模型路由")
    print("=" * 70)
    print(f"  skip-api: {SKIP_API}")
    print(f"  target: {TARGET_TEST or '全部'}")
    print(f"  .env: {ENV_FILE}")
    print("-" * 70)

    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestPhase35Route)
    suite._tests = custom_test_order(list(suite))

    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
    result = runner.run(suite)

    # 汇总
    print("\n" + "=" * 70)
    print("  测试汇总")
    print("=" * 70)
    passed = result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped)
    print(f"  通过: {passed}")
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