"""
tests/conftest.py — 全局测试 fixture 和 mock 配置

所有测试必须在无 LLM API 调用的情况下运行。
此文件提供共享的 mock fixture，防止任何测试意外触发真实 API 调用。
"""

import os
import sys
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock

import pytest


# ============================================================================
# 预加载 mock — 在任何模块导入前设置
# 必须在 conftest.py 最顶层执行，防止 import cascade 触发真实 API
# ============================================================================

# 1. Mock dotenv 加载（防止读取真实 .env 文件）
_MOCK_DOTENV = patch("dotenv.load_dotenv", return_value=True)
_MOCK_DOTENV.start()
_MOCK_SET_KEY = patch("dotenv.set_key", return_value=True)
_MOCK_SET_KEY.start()

# 2. 设置假环境变量（确保测试隔离）
os.environ.setdefault("AUTONOVEL_API_KEY", "sk-test-mock-key")
os.environ.setdefault("AUTONOVEL_API_BASE_URL", "https://api.test.mock/v1")
os.environ.setdefault("AUTONOVEL_MODEL_NAME", "test-model-mock")

# 3. 设置测试标记，供各模块检测
os.environ["AUTONOVEL_TEST_MODE"] = "1"

# 4. Mock 目录创建（防止测试中在项目目录下创建 output/ 等）
_ORIG_MKDIR = Path.mkdir


def _mock_mkdir(self, *args, **kwargs):
    """允许在 tmp_path 下创建目录，但阻止在项目根目录创建。"""
    # 允许临时目录
    path_str = str(self)
    if "tmp" in path_str or "temp" in path_str or "Temp" in path_str:
        return _ORIG_MKDIR(self, *args, **kwargs)
    # 允许已存在的目录（如 tests/fixtures/）
    if self.exists():
        return None
    # 其他情况静默跳过
    return None


# 仅当未处于"允许真实文件系统"模式时启用
if not os.environ.get("AUTONOVEL_REAL_FS"):
    pass  # 不全局 mock mkdir，改为在测试中按需 mock


# ============================================================================
# 关键路径注入 — 覆盖 core/config.py 的路径常量
# ============================================================================

@pytest.fixture
def temp_project(tmp_path, monkeypatch):
    """创建临时项目结构，覆盖所有路径常量。

    使用此 fixture 的测试完全隔离于真实文件系统。
    在 tmp_path 下创建：
      - .env (mock)
      - output/ (含 config.json, state.json 等子目录)
      - templates/
    """
    project_root = tmp_path / "project"
    project_root.mkdir()

    output_dir = project_root / "output"
    output_dir.mkdir()
    (output_dir / "chapters").mkdir()
    (output_dir / "briefs").mkdir()
    (output_dir / "edit_logs").mkdir()
    (output_dir / "eval_logs").mkdir()
    (output_dir / "backups").mkdir()

    templates_dir = project_root / "templates"
    templates_dir.mkdir()

    # Mock 路径常量
    import core.config as cfg

    monkeypatch.setattr(cfg, "ROOT_DIR", project_root, raising=False)
    monkeypatch.setattr(cfg, "OUTPUT_DIR", output_dir, raising=False)
    monkeypatch.setattr(cfg, "TEMPLATES_DIR", templates_dir, raising=False)
    monkeypatch.setattr(cfg, "CHAPTERS_DIR", output_dir / "chapters", raising=False)
    monkeypatch.setattr(cfg, "BRIEFS_DIR", output_dir / "briefs", raising=False)
    monkeypatch.setattr(cfg, "EDIT_LOGS_DIR", output_dir / "edit_logs", raising=False)
    monkeypatch.setattr(cfg, "EVAL_LOGS_DIR", output_dir / "eval_logs", raising=False)
    monkeypatch.setattr(cfg, "BACKUPS_DIR", output_dir / "backups", raising=False)
    monkeypatch.setattr(cfg, "ENV_FILE", project_root / ".env", raising=False)
    monkeypatch.setattr(cfg, "CONFIG_FILE", output_dir / "config.json", raising=False)
    monkeypatch.setattr(cfg, "STATE_FILE", output_dir / "state.json", raising=False)
    monkeypatch.setattr(cfg, "RESULTS_FILE", output_dir / "results.tsv", raising=False)

    return {
        "project_root": project_root,
        "output_dir": output_dir,
        "chapters_dir": output_dir / "chapters",
        "briefs_dir": output_dir / "briefs",
        "edit_logs_dir": output_dir / "edit_logs",
        "eval_logs_dir": output_dir / "eval_logs",
        "backups_dir": output_dir / "backups",
        "templates_dir": templates_dir,
        "env_file": project_root / ".env",
        "config_file": output_dir / "config.json",
        "state_file": output_dir / "state.json",
        "results_file": output_dir / "results.tsv",
    }


# ============================================================================
# Mock LLM API 调用 — 防止任何测试触发真实 API
# ============================================================================

@pytest.fixture(autouse=True)
def mock_all_llm_calls(monkeypatch):
    """全局 autouse fixture：mock 所有 LLM API 调用函数。

    任何测试中调用 call_llm / call_writer / call_judge 等
    都会抛出异常，防止意外触发真实 API。
    如需模拟 LLM 返回数据，在具体测试中覆盖 mock。
    """
    def _mock_llm_raise(*args, **kwargs):
        raise RuntimeError(
            "REAL LLM API CALL BLOCKED BY TEST SUITE. "
            "Use mock_llm_response fixture or patch in your test."
        )

    # 尝试 mock core.api_client 中的函数
    try:
        import core.api_client as api
        monkeypatch.setattr(api, "call_llm", _mock_llm_raise, raising=False)
        monkeypatch.setattr(api, "call_writer", _mock_llm_raise, raising=False)
        monkeypatch.setattr(api, "call_judge", _mock_llm_raise, raising=False)
        monkeypatch.setattr(api, "_call_llm_internal", _mock_llm_raise, raising=False)
        monkeypatch.setattr(api, "call_p1_writer", _mock_llm_raise, raising=False)
        monkeypatch.setattr(api, "call_p2_writer", _mock_llm_raise, raising=False)
        monkeypatch.setattr(api, "call_p2_ctx_writer", _mock_llm_raise, raising=False)
        monkeypatch.setattr(api, "call_p3_judge", _mock_llm_raise, raising=False)
    except ImportError:
        pass


# ============================================================================
# 通用 fixture
# ============================================================================

@pytest.fixture
def mock_llm_response():
    """返回一个可配置的 mock LLM 响应函数。

    用法:
        def test_xxx(mock_llm_response, monkeypatch):
            mock_fn = mock_llm_response('{"overall_score": 7.5}')
            monkeypatch.setattr("core.api_client.call_llm", mock_fn)
    """
    def _make_mock(response_text: str = "", side_effect=None):
        if side_effect:
            return MagicMock(side_effect=side_effect)
        return MagicMock(return_value=response_text)
    return _make_mock


@pytest.fixture
def clean_config():
    """返回一个新的、未加载的 Config 实例（绕过全局单例）。"""
    from core.config import Config
    cfg = Config()
    # 确保未加载
    cfg._data = {}
    cfg._loaded = False
    return cfg


@pytest.fixture
def mock_subprocess_run():
    """Mock subprocess.run 返回成功结果。"""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="abc1234\n",
            stderr="",
        )
        yield mock_run


# ============================================================================
# Session 清理
# ============================================================================

def pytest_sessionfinish(session, exitstatus):
    """测试会话结束后清理 mock。"""
    _MOCK_DOTENV.stop()
    _MOCK_SET_KEY.stop()
