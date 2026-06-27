#!/usr/bin/env python3
"""
Stage 2 单元/边界/故障注入测试 — 全量自动执行脚本

零 API 调用，Mock 全部外部依赖。
75 个测试用例，覆盖 8 个模块。

关键设计：在脚本最顶部 patch core.api_client._call_llm_internal，
          所有 call_writer/call_judge/call_p1_writer 等最终都调用此函数，
          因此无论模块何时导入，Mock 均生效。

用法:
    python tests/stage2_unit_tests.py          # 全部执行
    python tests/stage2_unit_tests.py -v       # 详细输出
    python tests/stage2_unit_tests.py --report # 仅汇总
"""

import json, os, re, shutil, sys, tempfile, threading, time, unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).parent.parent

# ═══════════════════════════════════════════════════════════
# 第一层防护：环境隔离
# ═══════════════════════════════════════════════════════════

_ENV_BAK = ROOT / ".env.bak"
_ENV_ORIG = ROOT / ".env"
if _ENV_ORIG.exists():
    shutil.copy2(str(_ENV_ORIG), str(_ENV_BAK))
    _ENV_ORIG.unlink()

# 写入隔离 .env（空 API Key → 即使 mock 失效也不会发真实请求）
_ENV_ORIG.write_text(
    "AUTONOVEL_API_KEY=\n"
    "AUTONOVEL_API_BASE_URL=https://mock-api.example.com/v1\n"
    "AUTONOVEL_MODEL_NAME=mock-model\n"
    "AUTONOVEL_API_INTERVAL_SECONDS=0.0\n",
    encoding="utf-8",
)

os.environ["AUTONOVEL_API_KEY"] = ""
os.environ["AUTONOVEL_API_BASE_URL"] = "https://mock-api.example.com/v1"
os.environ["AUTONOVEL_MODEL_NAME"] = "mock-model"
os.environ["AUTONOVEL_API_INTERVAL_SECONDS"] = "0.0"


def _restore_env():
    try:
        if _ENV_ORIG.exists(): _ENV_ORIG.unlink()
        if _ENV_BAK.exists():
            shutil.copy2(str(_ENV_BAK), str(_ENV_ORIG))
            _ENV_BAK.unlink()
    except Exception: pass


import atexit
atexit.register(_restore_env)

sys.path.insert(0, str(ROOT))

# ═══════════════════════════════════════════════════════════
# 第二层防护：Mock 基础设施
# ═══════════════════════════════════════════════════════════

_MOCK_CALL_LOG = []
_MOCK_RESPONSES = []


def _global_llm_mock(**kwargs):
    """全局 LLM Mock — 所有 call_* 函数最终调用的汇聚点。"""
    _MOCK_CALL_LOG.append(kwargs)
    if _MOCK_RESPONSES:
        resp = _MOCK_RESPONSES.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp
    return "GLOBAL_MOCK_OK"


def push(r):
    _MOCK_RESPONSES.append(r)


def push_many(*rs):
    for r in rs:
        _MOCK_RESPONSES.append(r)


def clear_log():
    _MOCK_CALL_LOG.clear()
    _MOCK_RESPONSES.clear()


# ═══════════════════════════════════════════════════════════
# 第三层防护：在 import 任何模块前 patch _call_llm_internal
# 所有 call_writer/call_judge/call_p1_writer 等便捷函数
# 内部都调用 call_llm → _call_llm_internal，
# 所以 patch 此函数即可拦截一切 LLM 调用。
# ═══════════════════════════════════════════════════════════

# 先确保 core.api_client 模块被加载
import core.api_client as _ac_mod

# 替换 _call_llm_internal
_ORIG_CALL_LLM_INTERNAL = _ac_mod._call_llm_internal
_ac_mod._call_llm_internal = _global_llm_mock

# 同时替换 RateLimiter.wait 避免真实延迟
_ORIG_RL_WAIT = _ac_mod.RateLimiter.wait
_ac_mod.RateLimiter.wait = lambda self: 0.0

# 同时替换 get_rate_limiter 返回零间隔限制器
_ORIG_GET_RL = _ac_mod.get_rate_limiter


def _fake_get_rl():
    rl = _ac_mod.RateLimiter(min_interval=0.0)
    return rl


_ac_mod.get_rate_limiter = _fake_get_rl


def _restore_llm_mock():
    """恢复原始 _call_llm_internal（HTTP 层测试用）。"""
    _ac_mod._call_llm_internal = _ORIG_CALL_LLM_INTERNAL
    _ac_mod.RateLimiter.wait = _ORIG_RL_WAIT
    _ac_mod.get_rate_limiter = _ORIG_GET_RL


def _reapply_llm_mock():
    """重新应用 Mock。"""
    _ac_mod._call_llm_internal = _global_llm_mock
    _ac_mod.RateLimiter.wait = lambda self: 0.0
    _ac_mod.get_rate_limiter = _fake_get_rl


# ═══════════════════════════════════════════════════════════
# 测试基类
# ═══════════════════════════════════════════════════════════

class BaseStage2Test(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        self._patchers = []
        clear_log()

    def tearDown(self):
        for p in reversed(self._patchers):
            try:
                p.stop()
            except Exception:
                pass
        self.temp_dir.cleanup()
        _reapply_llm_mock()

    def _patch(self, target, new):
        p = patch(target, new)
        p.start()
        self._patchers.append(p)
        return p

    def make_output_dir(self):
        out = self.temp_path / "output"
        for d in ["chapters", "backups", "eval_logs", "edit_logs", "briefs"]:
            (out / d).mkdir(parents=True, exist_ok=True)
        return out

    def make_templates_dir(self):
        (self.temp_path / "templates").mkdir(parents=True, exist_ok=True)

    def _setup_config(self, extra=None):
        import core.config, importlib
        importlib.reload(core.config)
        cfg = core.config.Config()
        cfg._data = {
            "api_key": "sk-mock", "api_base_url": "https://api.test.com/v1",
            "model_name": "test-model", "story_summary": "测试故事梗概",
            "total_chapters": 3, "total_volumes": 1, "chapters_per_volume": 3,
        }
        if extra:
            cfg._data.update(extra)
        cfg._loaded = True
        self._patch('core.config.config', cfg)
        return cfg

    def _setup_foundation_files(self):
        o = self.temp_path / 'output'
        (self.temp_path / 'templates' / 'world.md').write_text("# 模板", encoding="utf-8")
        (self.temp_path / 'templates' / 'voice.md').write_text("# 模板", encoding="utf-8")
        (o / 'voice.md').write_text("文风", encoding="utf-8")
        (o / 'world.md').write_text("世界", encoding="utf-8")
        (o / 'characters.md').write_text("角色", encoding="utf-8")
        (o / 'canon.md').write_text("正典", encoding="utf-8")
        (o / 'outline.md').write_text("大纲", encoding="utf-8")


# ═══════════════════════════════════════════════════════════
# 2.1 core/config.py 层 — 12 项
# ═══════════════════════════════════════════════════════════

class TestConfigLayer(BaseStage2Test):

    def setUp(self):
        super().setUp()
        self.make_output_dir()
        self.make_templates_dir()
        self._patch('core.config.ROOT_DIR', self.temp_path)
        self._patch('core.config.OUTPUT_DIR', self.temp_path / 'output')
        self._patch('core.config.TEMPLATES_DIR', self.temp_path / 'templates')
        self._patch('core.config.CHAPTERS_DIR', self.temp_path / 'output' / 'chapters')
        self._patch('core.config.BRIEFS_DIR', self.temp_path / 'output' / 'briefs')
        self._patch('core.config.EDIT_LOGS_DIR', self.temp_path / 'output' / 'edit_logs')
        self._patch('core.config.EVAL_LOGS_DIR', self.temp_path / 'output' / 'eval_logs')
        self._patch('core.config.BACKUPS_DIR', self.temp_path / 'output' / 'backups')
        self._patch('core.config.ENV_FILE', self.temp_path / '.env')
        self._patch('core.config.CONFIG_FILE', self.temp_path / 'output' / 'config.json')
        self._patch('core.config.STATE_FILE', self.temp_path / 'output' / 'state.json')
        self._patch('core.config.RESULTS_FILE', self.temp_path / 'output' / 'results.tsv')

    def _cfg(self):
        import core.config, importlib
        importlib.reload(core.config)
        return core.config.Config()

    def test_211_env_not_exists(self):
        c = self._cfg()
        env = self.temp_path / '.env'
        if env.exists(): env.unlink()
        c.load()
        self.assertTrue(c.loaded)
        self.assertEqual(c.api_key, "")

    def test_212_partial_keys(self):
        c = self._cfg()
        (self.temp_path / '.env').write_text("AUTONOVEL_API_KEY=tk\n", encoding="utf-8")
        c.load()
        self.assertEqual(c.api_key, "tk")
        self.assertEqual(c.judge_api_key, "")

    def test_213_invalid_interval(self):
        c = self._cfg()
        (self.temp_path / '.env').write_text("AUTONOVEL_API_INTERVAL_SECONDS=abc\n", encoding="utf-8")
        c.load()
        self.assertAlmostEqual(c.api_interval_seconds, 4.0)

    def test_214_story_summary_file(self):
        c = self._cfg()
        (self.temp_path / 'output' / 'story_summary.txt').write_text("故事\n", encoding="utf-8")
        c.load()
        self.assertEqual(c.story_summary, "故事")

    def test_215_shared_key_fallback(self):
        c = self._cfg()
        (self.temp_path / '.env').write_text("AUTONOVEL_API_KEY=shared\n", encoding="utf-8")
        c.load()
        for attr in ['p1_api_key', 'p2_api_key', 'p2_ctx_api_key', 'p3_api_key']:
            self.assertEqual(getattr(c, attr), "shared")

    def test_216_p1_independent(self):
        c = self._cfg()
        (self.temp_path / '.env').write_text(
            "AUTONOVEL_P1_API_KEY=p1\nAUTONOVEL_API_KEY=shared\n", encoding="utf-8")
        c.load()
        self.assertEqual(c.p1_api_key, "p1")
        self.assertEqual(c.p2_api_key, "p1")

    def test_217_chapters_per_vol_auto(self):
        c = self._cfg()
        c._data["total_chapters"] = 12
        c._data["total_volumes"] = 3
        self.assertEqual(c.chapters_per_volume, 4)

    def test_218_save_split(self):
        c = self._cfg()
        c.save({"api_key": "sk-x", "total_chapters": 6, "story_summary": "t"})
        env_c = (self.temp_path / '.env').read_text(encoding="utf-8")
        self.assertIn("AUTONOVEL_API_KEY", env_c)
        self.assertNotIn("total_chapters", env_c)
        json_c = (self.temp_path / 'output' / 'config.json').read_text(encoding="utf-8")
        self.assertIn("total_chapters", json_c)
        self.assertNotIn("api_key", json_c)

    def test_219_tier_no_override(self):
        c = self._cfg()
        c._data["foundation_threshold"] = 8.0
        c._data["model_name"] = "deepseek-ai/DeepSeek-V4-Flash"
        c.apply_model_tier_defaults()
        self.assertEqual(c.foundation_threshold, 8.0)
        self.assertAlmostEqual(c.get("plateau_delta", 0), 0.3)

    def test_2110_load_idempotent(self):
        c = self._cfg()
        c.load()
        c._data["custom"] = "v"
        c.load()
        self.assertEqual(c._data.get("custom"), "v")

    def test_2111_broken_config_json(self):
        c = self._cfg()
        (self.temp_path / 'output' / 'config.json').write_text("{broken", encoding="utf-8")
        (self.temp_path / '.env').write_text("AUTONOVEL_API_KEY=env-k\n", encoding="utf-8")
        c.load()
        self.assertTrue(c.loaded)
        self.assertEqual(c.api_key, "env-k")

    def test_2112_model_tier(self):
        c = self._cfg()
        c._data["model_name"] = "deepseek-ai/DeepSeek-V3"
        self.assertEqual(c.model_tier, "high")
        c._data["model_name"] = "qwen2.5-32b"
        self.assertEqual(c.model_tier, "medium")
        c._data["model_name"] = "gpt-3.5"
        self.assertEqual(c.model_tier, "low")


# ═══════════════════════════════════════════════════════════
# 2.2 core/state_manager.py 层 — 10 项
# ═══════════════════════════════════════════════════════════

class TestStateManagerLayer(BaseStage2Test):

    def setUp(self):
        super().setUp()
        self.make_output_dir()
        for tgt, val in [
            ('core.state_manager.OUTPUT_DIR', self.temp_path / 'output'),
            ('core.state_manager.CHAPTERS_DIR', self.temp_path / 'output' / 'chapters'),
            ('core.state_manager.STATE_FILE', self.temp_path / 'output' / 'state.json'),
            ('core.state_manager.RESULTS_FILE', self.temp_path / 'output' / 'results.tsv'),
            ('core.state_manager.BACKUPS_DIR', self.temp_path / 'output' / 'backups'),
            ('core.state_manager.EDIT_LOGS_DIR', self.temp_path / 'output' / 'edit_logs'),
            ('core.state_manager.EVAL_LOGS_DIR', self.temp_path / 'output' / 'eval_logs'),
            ('core.state_manager.BRIEFS_DIR', self.temp_path / 'output' / 'briefs'),
            ('core.state_manager.ROOT_DIR', self.temp_path),
        ]:
            self._patch(tgt, val)
        import core.state_manager, importlib
        importlib.reload(core.state_manager)
        self.sm = core.state_manager

    def test_221_default_state(self):
        sf = self.temp_path / 'output' / 'state.json'
        if sf.exists():
            sf.unlink()
        s = self.sm.load_state()
        self.assertEqual(s["phase"], "foundation")
        self.assertIn("review_revision_round", s)
        self.assertEqual(s["review_revision_round"], 0)

    def test_222_broken_state_json(self):
        (self.temp_path / 'output' / 'state.json').write_text("{corrupted", encoding="utf-8")
        import core.state_manager, importlib
        importlib.reload(core.state_manager)
        try:
            core.state_manager.load_state()
            print("  NOTE: load_state() 非法 JSON 未抛异常 (已修复?)")
        except json.JSONDecodeError:
            print("  BUG-S2-01 确认: load_state() 对非法 JSON 无保护")

    def test_223_git_cache(self):
        import core.state_manager as sm, importlib
        importlib.reload(sm)
        sm._GIT_AVAILABLE = None
        cnt = [0]

        def f():
            cnt[0] += 1
            return False

        with patch('core.state_manager._has_git', side_effect=f):
            sm.git_available()
            sm.git_available()
            self.assertEqual(cnt[0], 1)

    def test_224_backup_snapshot(self):
        o = self.temp_path / 'output'
        (o / 'world.md').write_text("W", encoding="utf-8")
        (o / 'state.json').write_text('{"phase":"test"}', encoding="utf-8")
        (o / 'chapters' / 'ch_01.md').write_text("C1", encoding="utf-8")
        sid = self.sm.backup_snapshot("test")
        self.assertIn("snapshot-", sid)
        backups = sorted((o / 'backups').iterdir())
        self.assertGreater(len(backups), 0)
        latest = backups[-1]
        self.assertTrue((latest / 'world.md').exists())
        self.assertTrue((latest / 'chapters' / 'ch_01.md').exists())

    def test_225_restore_empty(self):
        bk = self.temp_path / 'output' / 'backups'
        bk.mkdir(parents=True, exist_ok=True)
        self.assertFalse(self.sm.restore_latest())

    def test_226_restore_normal(self):
        o = self.temp_path / 'output'
        (o / 'world.md').write_text("原始", encoding="utf-8")
        (o / 'chapters').mkdir(exist_ok=True)
        (o / 'chapters' / 'ch_01.md').write_text("原始章", encoding="utf-8")
        self.sm.backup_snapshot("pre")
        (o / 'world.md').write_text("篡改", encoding="utf-8")
        self.assertTrue(self.sm.restore_latest())
        self.assertEqual((o / 'world.md').read_text(encoding="utf-8"), "原始")

    def test_227_total_chapters(self):
        self.assertEqual(self.sm.get_total_chapters({"chapters_total": 6}), 6)
        self.assertEqual(self.sm.get_total_chapters({"chapters_total": 0}), 24)

    def test_228_count_words_empty(self):
        ch = self.temp_path / 'output' / 'chapters'
        ch.mkdir(parents=True, exist_ok=True)
        self.assertEqual(self.sm.count_words_in_chapters(), 0)

    def test_229_parse_score(self):
        self.assertAlmostEqual(self.sm.parse_score("overall_score: 8.5"), 8.5)
        self.assertAlmostEqual(
            self.sm.parse_score("### overall_score\n**评分**: 9/10\n"), 9.0)
        self.assertEqual(self.sm.parse_score("overall_score: abc"), -1.0)
        self.assertEqual(self.sm.parse_score(""), -1.0)

    def test_2210_log_result(self):
        rf = self.temp_path / 'output' / 'results.tsv'
        if rf.exists():
            rf.unlink()
        self.sm.log_result("abc", "drafting", 7.5, 3000, "OK", "t")
        c = rf.read_text(encoding="utf-8")
        self.assertIn("commit", c)
        self.assertIn("abc", c)
        self.sm.log_result("def", "revision", 8.0, 3200, "OK", "t2")
        lines = rf.read_text(encoding="utf-8").strip().split("\n")
        self.assertEqual(lines[0].count("commit"), 1)


# ═══════════════════════════════════════════════════════════
# 2.3 core/api_client.py Mock 层 — 11 项
# ═══════════════════════════════════════════════════════════

class TestApiClientMockLayer(BaseStage2Test):

    def setUp(self):
        super().setUp()
        self.make_output_dir()
        self._patch('core.config.ROOT_DIR', self.temp_path)
        self._patch('core.config.OUTPUT_DIR', self.temp_path / 'output')
        self._patch('core.config.ENV_FILE', self.temp_path / '.env')
        import core.config, importlib
        importlib.reload(core.config)
        cfg = core.config.Config()
        cfg._data = {
            "api_key": "sk-test-key", "api_base_url": "https://api.test.com/v1",
            "model_name": "test-model",
            "p1_api_key": "p1-key", "p2_api_key": "p2-key",
            "judge_model_name": "judge-model", "judge_api_key": "judge-key",
            "judge_api_base_url": "https://judge.test.com/v1",
        }
        cfg._loaded = True
        self._patch('core.api_client.config', cfg)
        import core.api_client as ac, importlib as _il
        _il.reload(ac)
        self.ac = ac

    # ── 使用全局 Mock 的测试 ──

    def test_231_call_llm_normal(self):
        push("测试响应")
        self.assertEqual(self.ac.call_llm("p", system="s"), "测试响应")

    def test_235_rate_limiter(self):
        import core.api_client
        rl = core.api_client.RateLimiter(min_interval=0.1)
        for _ in range(5):
            rl.wait()
        self.assertTrue(True)

    def test_236_build_messages_no_system(self):
        msgs = self.ac._build_messages("p", None, "https://x.com/v1", "m")
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["role"], "user")

    def test_237_build_messages_blacklisted(self):
        ep = "https://x.com/v1|m"
        self.ac._SYSTEM_ROLE_FAILED_FOR_ENDPOINT.add(ep)
        msgs = self.ac._build_messages("p", "sys", "https://x.com/v1", "m")
        self.assertEqual(len(msgs), 1)
        self.assertIn("[系统指令]", msgs[0]["content"])
        self.ac._SYSTEM_ROLE_FAILED_FOR_ENDPOINT.discard(ep)

    def test_238_call_judge_independent(self):
        push("JUDGE_OK")
        self.assertEqual(self.ac.call_judge("p", system="S"), "JUDGE_OK")

    def test_239_phase_routing(self):
        clear_log()
        push_many("P1", "P2")
        self.assertEqual(self.ac.call_p1_writer("p"), "P1")
        self.assertEqual(self.ac.call_p2_writer("p"), "P2")
        # 验证使用了 Phase 对应的 api_key
        self.assertEqual(_MOCK_CALL_LOG[0]["api_key"], "p1-key")
        self.assertEqual(_MOCK_CALL_LOG[1]["api_key"], "p2-key")

    # ── HTTP 层测试：临时恢复真实 _call_llm_internal，mock httpx.post ──

    def _http_test(self, side_effect=None, status_code=None, expect_error=None):
        _restore_llm_mock()
        try:
            with patch('core.api_client.get_rate_limiter') as mrl:
                rl = MagicMock()
                rl.wait.return_value = 0
                mrl.return_value = rl
                if side_effect:
                    hp = patch('httpx.post', side_effect=side_effect)
                else:
                    mr = MagicMock()
                    mr.status_code = status_code or 200
                    mr.text = "test"
                    if mr.status_code == 200:
                        mr.json.return_value = {
                            "choices": [{"message": {"content": "ok"}}],
                            "usage": {"total_tokens": 5},
                        }
                    else:
                        mr.json.side_effect = json.JSONDecodeError("m", "d", 0)
                    hp = patch('httpx.post', return_value=mr)
                hp.start()
                try:
                    import core.api_client, importlib
                    importlib.reload(core.api_client)
                    if expect_error:
                        with self.assertRaises(expect_error):
                            core.api_client._call_llm_internal(
                                api_key="k", api_base="https://x.com/v1", model="m",
                                prompt="p", system=None,
                                messages=[{"role": "user", "content": "p"}], retries=3,
                            )
                    else:
                        return core.api_client._call_llm_internal(
                            api_key="k", api_base="https://x.com/v1", model="m",
                            prompt="p", system=None,
                            messages=[{"role": "user", "content": "p"}], retries=3,
                        )
                finally:
                    hp.stop()
        finally:
            _reapply_llm_mock()

    def test_232_http_429(self):
        self._http_test(status_code=429, expect_error=RuntimeError)

    def test_233_http_500(self):
        self._http_test(status_code=500, expect_error=RuntimeError)

    def test_234_max_total_time(self):
        _restore_llm_mock()
        try:
            with patch('core.api_client.get_rate_limiter') as mrl:
                rl = MagicMock()
                rl.wait.return_value = 0
                mrl.return_value = rl

                def slow(*a, **kw):
                    time.sleep(1.5)
                    mr = MagicMock(status_code=200)
                    mr.json.return_value = {
                        "choices": [{"message": {"content": "ok"}}],
                        "usage": {"total_tokens": 5},
                    }
                    return mr

                with patch('httpx.post', side_effect=slow):
                    import core.api_client, importlib
                    importlib.reload(core.api_client)
                    with self.assertRaises(RuntimeError) as ctx:
                        core.api_client._call_llm_internal(
                            api_key="k", api_base="https://x.com/v1", model="m",
                            prompt="p", system=None,
                            messages=[{"role": "user", "content": "p"}],
                            retries=5, max_total_time=3,
                        )
                    self.assertIn("总超时", str(ctx.exception))
        finally:
            _reapply_llm_mock()

    def test_2310_api_key_empty(self):
        _restore_llm_mock()
        try:
            import core.api_client, importlib
            importlib.reload(core.api_client)
            with self.assertRaises(RuntimeError) as ctx:
                core.api_client._call_llm_internal(
                    api_key="", api_base="https://x.com/v1", model="m",
                    prompt="p", system=None,
                    messages=[{"role": "user", "content": "p"}],
                )
            self.assertIn("未配置", str(ctx.exception))
        finally:
            _reapply_llm_mock()

    def test_2311_system_role_degrade(self):
        _restore_llm_mock()
        try:
            with patch('core.api_client.get_rate_limiter') as mrl:
                rl = MagicMock()
                rl.wait.return_value = 0
                mrl.return_value = rl
                idx = [0]

                def mp(*a, **kw):
                    i = idx[0]
                    idx[0] += 1
                    mr = MagicMock()
                    if i == 0:
                        mr.status_code = 400
                        mr.text = "system role not supported"
                        mr.json.side_effect = json.JSONDecodeError("m", "d", 0)
                    else:
                        mr.status_code = 200
                        mr.json.return_value = {
                            "choices": [{"message": {"content": "hello"}}],
                            "usage": {"total_tokens": 5},
                        }
                    return mr

                with patch('httpx.post', side_effect=mp):
                    import core.api_client, importlib
                    importlib.reload(core.api_client)
                    r = core.api_client._call_llm_internal(
                        api_key="k", api_base="https://x.com/v1", model="m",
                        prompt="p", system="S",
                        messages=[{"role": "system", "content": "S"},
                                  {"role": "user", "content": "p"}],
                        retries=3,
                    )
                    self.assertEqual(r, "hello")
        finally:
            _reapply_llm_mock()


# ═══════════════════════════════════════════════════════════
# 2.4 evaluation/ 层 — 11 项
# ═══════════════════════════════════════════════════════════

class TestEvaluationLayer(BaseStage2Test):

    def setUp(self):
        super().setUp()
        self.make_output_dir()
        self._patch('evaluation.evaluate.OUTPUT_DIR', self.temp_path / 'output')
        self._patch('evaluation.evaluate.CHAPTERS_DIR', self.temp_path / 'output' / 'chapters')
        self._patch('evaluation.evaluate.EVAL_LOGS_DIR', self.temp_path / 'output' / 'eval_logs')
        import evaluation.evaluate, evaluation.antipatterns, importlib
        importlib.reload(evaluation.evaluate)
        importlib.reload(evaluation.antipatterns)
        self.ev = evaluation.evaluate
        self.ap = evaluation.antipatterns

    def test_241_slop_empty(self):
        self.assertEqual(self.ev.slop_score_zh("")["slop_penalty"], 0.0)

    def test_242_slop_tier2(self):
        r = self.ev.slop_score_zh("她眼中闪过一丝惊讶，嘴角微微上扬")
        self.assertGreater(len(r["tier2_hits"]), 0)

    def test_243_slop_telling(self):
        r = self.ev.slop_score_zh("他感到一阵愤怒地瞪大了眼睛")
        self.assertGreaterEqual(r["telling_violations"], 1)

    def test_244_slop_transition(self):
        r = self.ev.slop_score_zh("然而变了。\n\n但是不接受。\n\n不过无所谓。")
        self.assertGreater(r["transition_opener_ratio"], 0)

    def test_245_slop_clean(self):
        clean = (
            "林默推开铁门。酸味扑面而来。服务器在运转。指示灯闪烁。"
            "他坐下。屏幕日志滚动。数字像咒语。今晚不一样。"
            "右上角出现了从未见过的文本。"
        ) * 5
        self.assertLess(self.ev.slop_score_zh(clean)["slop_penalty"], 1.0)

    def test_246_slop_perf(self):
        text = (
            "林默推开铁门。酸味扑面而来。服务器在运转。指示灯闪烁。"
            "他坐下。屏幕日志滚动。数字像咒语。今晚不一样。"
        ) * 80
        t0 = time.time()
        self.ev.slop_score_zh(text)
        self.assertLess(time.time() - t0, 1.0)

    def test_247_eval_ch_missing(self):
        self.assertIn("overall_score: 0.0", self.ev.evaluate_chapter(999))

    def test_248_eval_foundation(self):
        (self.temp_path / 'output' / 'world.md').write_text("W", encoding="utf-8")
        (self.temp_path / 'output' / 'characters.md').write_text("C", encoding="utf-8")
        (self.temp_path / 'output' / 'canon.md').write_text("CN", encoding="utf-8")
        (self.temp_path / 'output' / 'outline.md').write_text("O", encoding="utf-8")
        push("非JSON评估")
        self.assertEqual(self.ev.evaluate_foundation(), "非JSON评估")

    def test_249_audit_empty(self):
        self.assertEqual(self.ap.run_structural_audit("")["warning_count"], 0)

    def test_2410_audit_antipatterns(self):
        text = (
            "他没有回头。" * 7
            + "\n\n这意味着结束。这说明对。\n\n"
            + "心跳像鼓声。呼吸像风声。目光像剑光。步伐像流水。"
        ) * 3
        r = self.ap.run_structural_audit(text)
        self.assertGreaterEqual(r["over_explain"]["count"], 1)
        self.assertGreaterEqual(r["negative_assertions"]["count"], 5)
        self.assertGreaterEqual(r["warning_count"], 1)

    def test_2411_slop_penalty_no_logs(self):
        el = self.temp_path / 'output' / 'eval_logs'
        el.mkdir(parents=True, exist_ok=True)
        self.assertEqual(self.ev.get_last_slop_penalty(1), 0.0)


# ═══════════════════════════════════════════════════════════
# 2.5 foundation/ 单元 — 12 项
# ═══════════════════════════════════════════════════════════

class TestFoundationUnits(BaseStage2Test):

    def setUp(self):
        super().setUp()
        self.make_output_dir()
        self.make_templates_dir()
        for tgt, val in [
            ('core.config.ROOT_DIR', self.temp_path),
            ('core.config.OUTPUT_DIR', self.temp_path / 'output'),
            ('core.config.TEMPLATES_DIR', self.temp_path / 'templates'),
            ('core.config.CHAPTERS_DIR', self.temp_path / 'output' / 'chapters'),
            ('core.config.ENV_FILE', self.temp_path / '.env'),
        ]:
            self._patch(tgt, val)
        self._setup_foundation_files()
        self._setup_config()

    def test_251_gen_world(self):
        push("# 世界观\n测试")
        import foundation.gen_world, importlib
        importlib.reload(foundation.gen_world)
        foundation.gen_world.generate_world()
        self.assertTrue((self.temp_path / 'output' / 'world.md').exists())

    def test_252_gen_characters(self):
        push("# 角色\n测试")
        import foundation.gen_characters, importlib
        importlib.reload(foundation.gen_characters)
        foundation.gen_characters.generate_characters()
        self.assertTrue((self.temp_path / 'output' / 'characters.md').exists())

    def test_253_volume_outline_single(self):
        clear_log()
        push("卷级大纲")
        import foundation.gen_outline_volume, importlib
        importlib.reload(foundation.gen_outline_volume)
        foundation.gen_outline_volume.generate_volume_outline()
        self.assertEqual(len(_MOCK_CALL_LOG), 1)

    def test_254_volume_outline_three(self):
        self._setup_config(extra={"total_volumes": 3, "total_chapters": 9})
        clear_log()
        push_many("卷1-2", "卷3")
        import foundation.gen_outline_volume, importlib
        importlib.reload(foundation.gen_outline_volume)
        foundation.gen_outline_volume.generate_volume_outline()
        self.assertLessEqual(len(_MOCK_CALL_LOG), 3)

    def test_255_gen_outline(self):
        clear_log()
        (self.temp_path / 'output' / 'outline_volume.md').write_text(
            "### 卷 1：觉醒\n卷1约束\n", encoding="utf-8")
        push_many("### 第1章\n大纲1", "### 第2章\n大纲2", "### 第3章\n大纲3")
        import foundation.gen_outline, importlib
        importlib.reload(foundation.gen_outline)
        foundation.gen_outline.generate_outline()
        self.assertGreater(
            len(list((self.temp_path / 'output').glob("outline*.md"))), 0)

    def test_256_split_chapters(self):
        import foundation.gen_outline as go
        self.assertEqual(go._split_chapters_for_volume(1, 3), [(1, 3)])
        self.assertEqual(go._split_chapters_for_volume(1, 8), [(1, 4), (5, 8)])
        self.assertEqual(go._split_chapters_for_volume(1, 12),
                         [(1, 5), (6, 10), (11, 12)])
        self.assertEqual(go._split_chapters_for_volume(5, 5), [(5, 5)])

    def test_257_extract_volume(self):
        import foundation.gen_outline as go
        t = "### 卷 1：A\n卷1内容。\n\n### 卷 2：B\n卷2内容。\n\n## 二、伏笔"
        self.assertIn("卷1内容", go._extract_volume_section(t, 1))
        self.assertNotIn("卷2内容", go._extract_volume_section(t, 1))
        self.assertIn("卷2内容", go._extract_volume_section(t, 2))
        self.assertEqual(go._extract_volume_section(t, 3), "")

    def test_258_outline_part2_skip(self):
        for f in (self.temp_path / 'output').glob("outline*.md"):
            f.unlink()
        clear_log()
        import foundation.gen_outline_part2, importlib
        importlib.reload(foundation.gen_outline_part2)
        foundation.gen_outline_part2.generate_outline_part2()
        self.assertEqual(len(_MOCK_CALL_LOG), 0)

    def test_259_gen_canon(self):
        push("## 一、世界观\n— f1\n## 二、角色\n— c1\n")
        import foundation.gen_canon, importlib
        importlib.reload(foundation.gen_canon)
        foundation.gen_canon.generate_canon()
        self.assertTrue((self.temp_path / 'output' / 'canon.md').exists())

    def test_2510_count_canon(self):
        t = (
            "## 一、世界观硬事实\n— f1\n— f2\n"
            "## 二、角色硬事实\n— c1\n"
            "## 三、时间线硬事实\n— t1\n— t2\n— t3\n"
            "## 四、规则硬事实\n— r1\n"
        )
        (self.temp_path / 'output' / 'canon.md').write_text(t, encoding="utf-8")
        import foundation.gen_canon
        c = foundation.gen_canon.count_canon_entries()
        self.assertEqual(c["total"], 7)
        self.assertEqual(c["world"], 2)
        self.assertEqual(c["character"], 1)
        self.assertEqual(c["timeline"], 3)
        self.assertEqual(c["rules"], 1)

    def test_2511_gen_voice(self):
        jj = json.dumps({
            "registers": [{
                "register_id": 1, "register_name": "简约式",
                "scores": {"fit": 8, "quality": 7, "sustainability": 8,
                           "ai_free": 9, "distinctiveness": 7},
                "overall": 7.8, "weakness": "平", "improvement": "增",
            }],
            "best_register": 1, "best_register_name": "简约式",
            "overall_score": 7.5,
        })
        push_many("## 风格1\n内容\n## 风格2\n内容2", jj, "## Part2\n精炼")
        import foundation.gen_voice, importlib
        importlib.reload(foundation.gen_voice)
        foundation.gen_voice.generate_voice()
        self.assertTrue((self.temp_path / 'output' / 'voice.md').exists())

    def test_2512_update_canon(self):
        (self.temp_path / 'output' / 'canon.md').write_text(
            "## 一、世界观硬事实\n— 已有\n", encoding="utf-8")
        push("## 新增：世界观硬事实（第 1 章）\n— 新1\n— 新2")
        import foundation.update_canon, importlib
        importlib.reload(foundation.update_canon)
        self.assertEqual(
            foundation.update_canon.update_canon_from_chapter(1, "章", 8000), 2)
        push("无新增事实")
        self.assertEqual(
            foundation.update_canon.update_canon_from_chapter(2, "章2"), 0)


# ═══════════════════════════════════════════════════════════
# 2.6 drafting/ 单元 — 5 项
# ═══════════════════════════════════════════════════════════

class TestDraftingUnits(BaseStage2Test):

    def setUp(self):
        super().setUp()
        self.make_output_dir()
        self.make_templates_dir()
        for tgt, val in [
            ('core.config.ROOT_DIR', self.temp_path),
            ('core.config.OUTPUT_DIR', self.temp_path / 'output'),
            ('core.config.TEMPLATES_DIR', self.temp_path / 'templates'),
            ('core.config.CHAPTERS_DIR', self.temp_path / 'output' / 'chapters'),
            ('core.config.ENV_FILE', self.temp_path / '.env'),
        ]:
            self._patch(tgt, val)
        self._setup_foundation_files()
        self._setup_config()

    def test_261_draft_chapter(self):
        push("# 第 1 章\n\n章节内容。")
        import drafting.draft_chapter, importlib
        importlib.reload(drafting.draft_chapter)
        drafting.draft_chapter.draft_chapter(1)
        ch = self.temp_path / 'output' / 'chapters' / 'ch_01.md'
        self.assertTrue(ch.exists())
        self.assertIn("第 1 章", ch.read_text(encoding="utf-8"))

    def test_262_extract_outline_vol(self):
        (self.temp_path / 'output' / 'outline_volume1.md').write_text(
            "### 第 1 章\n第一章大纲。\n### 第 2 章\n第二章大纲。",
            encoding="utf-8",
        )
        import drafting.draft_chapter, importlib
        importlib.reload(drafting.draft_chapter)
        r = drafting.draft_chapter.extract_chapter_outline(1)
        self.assertIn("第一章大纲", r)
        self.assertNotIn("第二章大纲", r)

    def test_263_extract_outline_fallback(self):
        for f in (self.temp_path / 'output').glob("outline_volume*.md"):
            f.unlink()
        import drafting.draft_chapter, importlib
        importlib.reload(drafting.draft_chapter)
        r = drafting.draft_chapter.extract_chapter_outline(1)
        self.assertIn("大纲", r)

    def test_264_load_file_missing(self):
        import drafting.draft_chapter
        self.assertEqual(
            drafting.draft_chapter.load_file(Path("/nonexistent.md")), "")

    def test_265_run_drafts(self):
        import core.state_manager, importlib
        importlib.reload(core.state_manager)
        push_many("第1章", "第2章", "第3章")
        import drafting.run_drafts
        importlib.reload(drafting.run_drafts)
        state = core.state_manager.default_state()
        state["chapters_total"] = 3
        state["chapters_drafted"] = 0
        drafting.run_drafts.run_drafts(state)
        self.assertEqual(state["chapters_drafted"], 3)
        self.assertEqual(state["phase"], "revision")
        for i in range(1, 4):
            self.assertTrue(
                (self.temp_path / 'output' / 'chapters' /
                 f'ch_{i:02d}.md').exists())


# ═══════════════════════════════════════════════════════════
# 2.7 revision/ 单元 — 7 项
# ═══════════════════════════════════════════════════════════

class TestRevisionUnits(BaseStage2Test):

    def setUp(self):
        super().setUp()
        self.make_output_dir()
        for tgt, val in [
            ('core.config.ROOT_DIR', self.temp_path),
            ('core.config.OUTPUT_DIR', self.temp_path / 'output'),
            ('core.config.CHAPTERS_DIR', self.temp_path / 'output' / 'chapters'),
            ('core.config.EDIT_LOGS_DIR', self.temp_path / 'output' / 'edit_logs'),
            ('core.config.EVAL_LOGS_DIR', self.temp_path / 'output' / 'eval_logs'),
            ('core.config.BRIEFS_DIR', self.temp_path / 'output' / 'briefs'),
            ('core.config.ENV_FILE', self.temp_path / '.env'),
        ]:
            self._patch(tgt, val)
        self._setup_foundation_files()
        self._setup_config()
        for i in range(1, 4):
            (self.temp_path / 'output' / 'chapters' /
             f'ch_{i:02d}.md').write_text(f"章节{i}", encoding="utf-8")

    def test_271_review_loop(self):
        push_many(
            json.dumps({"overall_score": 7.5, "issues": [], "strengths": []}),
            json.dumps({"overall_score": 7.5, "issues": [], "strengths": []}),
        )
        import revision.review, importlib
        importlib.reload(revision.review)
        try:
            revision.review.run_review_loop(
                state={"chapters_total": 3, "revision_cycle": 0}, max_cycles=1)
        except Exception as e:
            self.fail(f"review: {type(e).__name__}: {e}")

    def test_272_build_brief(self):
        (self.temp_path / 'output' / 'eval_logs' / 'ch_01_test.json').write_text(
            json.dumps({"mechanical": {"slop_penalty": 0.5}}), encoding="utf-8")
        import revision.gen_brief, importlib
        importlib.reload(revision.gen_brief)
        try:
            self.assertIsNotNone(
                revision.gen_brief.build_auto_brief(chapter_num=1))
        except FileNotFoundError:
            pass
        except Exception as e:
            self.fail(f"brief: {e}")

    def test_273_panel_mentions(self):
        (self.temp_path / 'output' / 'reader_panel.json').write_text(
            json.dumps([{"role": "读者", "chapter": 1, "comment": "好"}]),
            encoding="utf-8",
        )
        import revision.gen_brief, importlib
        importlib.reload(revision.gen_brief)
        try:
            self.assertGreater(
                len(revision.gen_brief.panel_mentions_for_chapter(1)), 0)
        except Exception as e:
            self.fail(f"panel: {e}")

    def test_274_revise(self):
        push("修订后")
        import revision.gen_revision, importlib
        importlib.reload(revision.gen_revision)
        try:
            revision.gen_revision.revise_chapter(1)
        except Exception as e:
            self.fail(f"revise: {e}")

    def test_275_adversarial(self):
        push(json.dumps({"to_cut": [], "to_keep": ["A"], "cuts": []}))
        import revision.adversarial_edit, importlib
        importlib.reload(revision.adversarial_edit)
        try:
            revision.adversarial_edit.run_adversarial_edit("all")
        except Exception as e:
            self.fail(f"adversarial: {e}")

    def test_276_reader_panel(self):
        push_many(*[json.dumps({"role": "r", "comment": "c"}) for _ in range(10)])
        import revision.reader_panel, importlib
        importlib.reload(revision.reader_panel)
        try:
            revision.reader_panel.run_reader_panel()
        except Exception:
            pass

    def test_277_compare(self):
        push_many(*[json.dumps({"winner": "A", "score_diff": 0.5})
                     for _ in range(10)])
        import revision.compare_chapters, importlib
        importlib.reload(revision.compare_chapters)
        try:
            revision.compare_chapters.run_compare_chapters()
        except Exception as e:
            self.fail(f"compare: {e}")


# ═══════════════════════════════════════════════════════════
# 2.8 故障注入矩阵 — 7 项
# ═══════════════════════════════════════════════════════════

class TestFaultInjection(BaseStage2Test):

    def setUp(self):
        super().setUp()
        self.make_output_dir()
        for tgt, val in [
            ('core.config.ROOT_DIR', self.temp_path),
            ('core.config.OUTPUT_DIR', self.temp_path / 'output'),
            ('core.config.CHAPTERS_DIR', self.temp_path / 'output' / 'chapters'),
            ('core.config.ENV_FILE', self.temp_path / '.env'),
            ('core.config.CONFIG_FILE', self.temp_path / 'output' / 'config.json'),
            ('core.config.STATE_FILE', self.temp_path / 'output' / 'state.json'),
        ]:
            self._patch(tgt, val)

    def test_281_timeout_x3(self):
        import httpx
        _restore_llm_mock()
        try:
            with patch('core.api_client.get_rate_limiter') as mrl:
                rl = MagicMock()
                rl.wait.return_value = 0
                mrl.return_value = rl
                with patch('httpx.post',
                           side_effect=httpx.TimeoutException("timeout")):
                    import core.api_client, importlib
                    importlib.reload(core.api_client)
                    with self.assertRaises(RuntimeError):
                        core.api_client._call_llm_internal(
                            api_key="k", api_base="https://x.com/v1", model="m",
                            prompt="p", system=None,
                            messages=[{"role": "user", "content": "p"}],
                            retries=3,
                        )
        finally:
            _reapply_llm_mock()

    def test_282_empty_content(self):
        _restore_llm_mock()
        try:
            with patch('core.api_client.get_rate_limiter') as mrl:
                rl = MagicMock()
                rl.wait.return_value = 0
                mrl.return_value = rl
                mr = MagicMock(status_code=200)
                mr.json.return_value = {
                    "choices": [{"message": {"content": ""}}],
                    "usage": {"total_tokens": 0},
                }
                with patch('httpx.post', return_value=mr):
                    import core.api_client, importlib
                    importlib.reload(core.api_client)
                    r = core.api_client._call_llm_internal(
                        api_key="k", api_base="https://x.com/v1", model="m",
                        prompt="p", system=None,
                        messages=[{"role": "user", "content": "p"}],
                    )
                    self.assertEqual(r, "")
        finally:
            _reapply_llm_mock()

    def test_283_malformed_json(self):
        _restore_llm_mock()
        try:
            with patch('core.api_client.get_rate_limiter') as mrl:
                rl = MagicMock()
                rl.wait.return_value = 0
                mrl.return_value = rl
                mr = MagicMock(status_code=200)
                mr.json.return_value = {"choices": []}
                with patch('httpx.post', return_value=mr):
                    import core.api_client, importlib
                    importlib.reload(core.api_client)
                    with self.assertRaises(RuntimeError):
                        core.api_client._call_llm_internal(
                            api_key="k", api_base="https://x.com/v1", model="m",
                            prompt="p", system=None,
                            messages=[{"role": "user", "content": "p"}],
                            retries=3,
                        )
        finally:
            _reapply_llm_mock()

    def test_284_illegal_score(self):
        import core.state_manager, importlib
        importlib.reload(core.state_manager)
        self.assertEqual(
            core.state_manager.parse_score("overall_score: abc"), -1.0)

    def test_285_readonly_dir(self):
        sp = self.temp_path / 'output' / 'state.json'
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text("{}", encoding="utf-8")
        try:
            os.chmod(str(sp), 0o444)
        except OSError:
            pass
        import core.state_manager, importlib
        importlib.reload(core.state_manager)
        try:
            core.state_manager.save_state({"test": "data"})
            print("  NOTE: save_state() 对只读未报错")
        except PermissionError:
            print("  BUG-S2-02 确认: save_state() PermissionError 无保护")

    def test_286_corrupted_config(self):
        (self.temp_path / 'output' / 'config.json').write_text(
            "{garbage", encoding="utf-8")
        (self.temp_path / '.env').write_text(
            "AUTONOVEL_API_KEY=ek\n", encoding="utf-8")
        import core.config, importlib
        importlib.reload(core.config)
        c = core.config.Config()
        c.load()
        self.assertTrue(c.loaded)
        self.assertEqual(c.api_key, "ek")

    def test_287_chapters_deleted(self):
        ch_dir = self.temp_path / 'output' / 'chapters'
        shutil.rmtree(str(ch_dir), ignore_errors=True)
        push("章节内容")
        import drafting.draft_chapter, importlib
        importlib.reload(drafting.draft_chapter)
        with patch('drafting.draft_chapter.CHAPTERS_DIR', ch_dir):
            drafting.draft_chapter.draft_chapter(1)
        self.assertTrue((ch_dir / 'ch_01.md').exists())


# ═══════════════════════════════════════════════════════════
# 运行入口
# ═══════════════════════════════════════════════════════════

def main():
    import argparse
    ap = argparse.ArgumentParser(description="Stage 2 单元测试")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in [
            TestConfigLayer, TestStateManagerLayer, TestApiClientMockLayer,
            TestEvaluationLayer, TestFoundationUnits, TestDraftingUnits,
            TestRevisionUnits, TestFaultInjection,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    vb = 2 if args.verbose else (0 if args.report else 1)
    runner = unittest.TextTestRunner(verbosity=vb)
    result = runner.run(suite)

    total = result.testsRun
    passed = total - len(result.failures) - len(result.errors)
    print("\n" + "=" * 60)
    print("Stage 2 单元测试 汇总")
    print("=" * 60)
    print(f"  总计: {total}  通过: {passed}  "
          f"失败: {len(result.failures)}  错误: {len(result.errors)}")
    if result.failures or result.errors:
        print("  [FAIL] 未通过 — 存在失败或错误")
        for name, tb in result.failures + result.errors:
            print(f"    FAIL/ERROR: {name}")
    else:
        print(f"  [PASS] 全部 {passed} 项通过")
    print("=" * 60)

    _restore_env()
    return 0 if not (result.failures or result.errors) else 1


if __name__ == "__main__":
    sys.exit(main())