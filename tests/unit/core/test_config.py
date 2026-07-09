"""
tests/unit/core/test_config.py — 阶段2: 配置与状态管理异常测试（Config 部分）

测试目标:
  TC-CFG-001 ~ TC-CFG-009: Config 加载异常测试
  TC-CFG-010 ~ TC-CFG-013: 模型 tier 推断测试

使用 unittest.mock.patch 和 tempfile 测试 Config 单例。
所有测试不调用 LLM API。
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock

import pytest

# 确保在导入 core.config 之前设置环境
os.environ.setdefault("AUTONOVEL_API_KEY", "")
os.environ.setdefault("AUTONOVEL_API_BASE_URL", "")
os.environ.setdefault("AUTONOVEL_MODEL_NAME", "")


# ============================================================================
# Helper: 创建干净的 Config 实例
# ============================================================================

def _new_config():
    """创建全新的 Config 实例（非全局单例）。"""
    from core.config import Config
    cfg = Config()
    cfg._data = {}
    cfg._loaded = False
    return cfg


# ============================================================================
# 5.1 Config 加载异常测试 (TC-CFG-001 ~ TC-CFG-009)
# ============================================================================

class TestConfigLoadEdgeCases:
    """测试 Config.load() 在各种异常条件下的行为。"""

    def test_env_missing_config_json_missing(self, temp_project, monkeypatch):
        """TC-CFG-003: .env 和 config.json 同时缺失。

        Config 应成功加载，所有属性返回硬编码默认值。
        """
        cfg = _new_config()

        # 清除可能由测试环境设置的 API 环境变量
        monkeypatch.delenv("AUTONOVEL_API_KEY", raising=False)
        monkeypatch.delenv("AUTONOVEL_API_BASE_URL", raising=False)
        monkeypatch.delenv("AUTONOVEL_MODEL_NAME", raising=False)

        # 确保两个文件都不存在
        assert not temp_project["env_file"].exists()
        assert not temp_project["config_file"].exists()

        # 加载
        data = cfg.load()

        assert cfg.loaded is True
        assert cfg.api_key == ""
        assert cfg.api_base_url == "https://api.siliconflow.cn/v1"
        assert cfg.model_name == "deepseek-ai/DeepSeek-V3"
        assert cfg.api_interval_seconds == 4.0
        assert cfg.total_chapters == 24

    def test_env_missing_config_json_present(self, temp_project, monkeypatch):
        """TC-CFG-001: .env 缺失但有 config.json 时的行为。

        Config 应从 config.json 加载非敏感键，
        敏感键使用默认值。
        """
        cfg = _new_config()

        # 清除可能由测试环境设置的 API 环境变量
        monkeypatch.delenv("AUTONOVEL_API_KEY", raising=False)
        monkeypatch.delenv("AUTONOVEL_API_BASE_URL", raising=False)
        monkeypatch.delenv("AUTONOVEL_MODEL_NAME", raising=False)

        # 创建 config.json（仅非敏感键）
        config_data = {
            "novel_title": "测试小说",
            "total_chapters": 36,
            "genre": "科幻",
            "mode": "resume",
        }
        temp_project["config_file"].write_text(
            json.dumps(config_data, ensure_ascii=False), encoding="utf-8")

        data = cfg.load()

        assert cfg.loaded is True
        # 非敏感键来自 config.json
        assert cfg.novel_title == "测试小说"
        assert cfg.total_chapters == 36
        assert cfg.genre == "科幻"
        # 敏感键使用默认值
        assert cfg.api_key == ""

    def test_config_json_missing_env_present(self, temp_project):
        """TC-CFG-002: config.json 缺失但有 .env 时的行为。

        Config 应仅加载 .env 中的值，非敏感键使用默认值。
        """
        cfg = _new_config()

        # 创建 .env 文件
        temp_project["env_file"].write_text(
            "AUTONOVEL_API_KEY=env-test-key\n"
            "AUTONOVEL_API_BASE_URL=https://env.test.api/v1\n"
            "AUTONOVEL_MODEL_NAME=env-test-model\n",
            encoding="utf-8")

        # 加载 .env 到 os.environ（模拟 load_dotenv 已执行）
        # 注意：我们在 conftest 中 mock 了 load_dotenv，所以需要手动设置环境变量
        os.environ["AUTONOVEL_API_KEY"] = "env-test-key"
        os.environ["AUTONOVEL_API_BASE_URL"] = "https://env.test.api/v1"
        os.environ["AUTONOVEL_MODEL_NAME"] = "env-test-model"

        data = cfg.load()

        assert cfg.loaded is True
        # 敏感键从环境变量加载
        assert cfg.api_key == "env-test-key"
        # 非敏感键使用默认值
        assert cfg.total_chapters == 24

        # 清理环境变量
        del os.environ["AUTONOVEL_API_KEY"]
        del os.environ["AUTONOVEL_API_BASE_URL"]
        del os.environ["AUTONOVEL_MODEL_NAME"]

    def test_config_json_corrupt(self, temp_project):
        """TC-CFG-004: config.json 损坏（无效JSON）。

        Config 应静默跳过损坏的 config.json，不崩溃。
        """
        cfg = _new_config()

        # 写入损坏的 JSON
        temp_project["config_file"].write_text(
            '{invalid json "novel_title": "test"', encoding="utf-8")

        # 不应抛出异常
        data = cfg.load()

        assert cfg.loaded is True
        # 损坏的 config.json 被跳过，使用默认值
        assert cfg.novel_title == ""

    def test_config_json_unknown_keys(self, temp_project):
        """TC-CFG-005: config.json 含未知额外键。

        未知字段应被加载到 _data 中，可通过 config.get() 访问。
        """
        cfg = _new_config()

        config_data = {
            "novel_title": "测试",
            "unknown_custom_field": 12345,
            "another_extra": "hello",
        }
        temp_project["config_file"].write_text(
            json.dumps(config_data, ensure_ascii=False), encoding="utf-8")

        data = cfg.load()

        # 已知键正常
        assert cfg.novel_title == "测试"
        # 未知键可通过 get() 访问
        assert cfg.get("unknown_custom_field") == 12345
        assert cfg.get("another_extra") == "hello"

    def test_config_json_sensitive_keys_not_overwritten(self, temp_project):
        """TC-CFG-006: config.json 中含敏感键不会被覆盖 .env 值。

        设置环境变量 api_key 后，config.json 中的 api_key 应被忽略。
        """
        cfg = _new_config()

        # 设置环境变量
        os.environ["AUTONOVEL_API_KEY"] = "env-secure-key"

        # config.json 中也写 api_key（恶意/错误配置）
        config_data = {
            "api_key": "evil-key-in-json",
            "novel_title": "测试",
        }
        temp_project["config_file"].write_text(
            json.dumps(config_data, ensure_ascii=False), encoding="utf-8")

        data = cfg.load()

        # config.json 中的敏感键被忽略
        assert cfg.api_key != "evil-key-in-json"
        assert cfg.api_key == "env-secure-key"

        del os.environ["AUTONOVEL_API_KEY"]

    def test_api_interval_seconds_invalid(self, temp_project):
        """TC-CFG-007: api_interval_seconds 为非数字值。

        环境变量含非数字值时应回退为 4.0，不抛出异常。
        """
        cfg = _new_config()

        # 设置无效的环境变量
        os.environ["AUTONOVEL_API_INTERVAL_SECONDS"] = "abc"

        data = cfg.load()

        # 应从 _load_env 中捕获 ValueError，回退为 4.0
        # 注意：_load_env 尝试 float("abc") 失败后设为 4.0
        assert cfg.api_interval_seconds == 4.0

        del os.environ["AUTONOVEL_API_INTERVAL_SECONDS"]

    def test_config_load_multiple_times(self, temp_project):
        """TC-CFG-008: config.load() 多次调用。

        _loaded=True 后的调用应立即返回缓存 _data。
        """
        cfg = _new_config()

        # 第一次加载
        temp_project["config_file"].write_text(
            '{"novel_title": "第一次"}', encoding="utf-8")
        data1 = cfg.load()
        assert cfg.novel_title == "第一次"

        # 修改 config.json
        temp_project["config_file"].write_text(
            '{"novel_title": "第二次"}', encoding="utf-8")

        # 第二次调用 load() 应返回缓存
        data2 = cfg.load()
        assert cfg.novel_title == "第一次"  # 仍是缓存值

        assert cfg.loaded is True

    def test_config_save_then_load(self, temp_project):
        """TC-CFG-009: config.save() 写入后 config.load() 重载。

        需要先强制重置 _loaded 标志才能重新加载。
        """
        cfg = _new_config()

        # 先加载初始状态
        cfg.load()

        # 强制重置以模拟新实例
        cfg._loaded = False
        cfg._data = {}

        # save 新数据
        save_data = {
            "novel_title": "保存测试",
            "total_chapters": 48,
        }
        cfg.save(save_data)

        # 验证 config.json 已写入
        assert temp_project["config_file"].exists()
        saved_content = json.loads(
            temp_project["config_file"].read_text(encoding="utf-8"))
        assert saved_content.get("novel_title") == "保存测试"

        # 重置并重新加载
        cfg._loaded = False
        cfg._data = {}
        cfg.load()

        assert cfg.novel_title == "保存测试"
        assert cfg.total_chapters == 48


# ============================================================================
# 5.2 模型 tier 推断测试 (TC-CFG-010 ~ TC-CFG-013)
# ============================================================================

class TestModelTierInference:
    """测试模型能力等级的自动推断。"""

    HIGH_MODEL_NAMES = [
        "deepseek-ai/DeepSeek-V3",
        "deepseek-ai/DeepSeek-V4",
        "deepseek-chat",
        "deepseek-r1",
        "llama-3.3-70b",
        "llama-3.1-405b",
        "qwen2.5-72b",
    ]

    MEDIUM_MODEL_NAMES = [
        "Qwen2.5-32B-Instruct",
        "llama-3.1-70b",
        "llama-3-70b",
    ]

    UNKNOWN_MODEL_NAMES = [
        "some-new-model-2026",
        "custom-fine-tuned-v1",
        "unknown-model",
    ]

    def test_high_model_tier_inference(self, temp_project):
        """TC-CFG-010: 已知 high 模型推断为 'high'。

        对每个已知 high 模型名称验证模型 tier。
        """
        for model_name in self.HIGH_MODEL_NAMES:
            cfg = _new_config()
            cfg._data["model_name"] = model_name
            tier = cfg.model_tier
            assert tier == "high", \
                f"模型 '{model_name}' 应推断为 'high'，实际为 '{tier}'"

    def test_medium_model_tier_inference(self, temp_project):
        """TC-CFG-011: 已知 medium 模型推断为 'medium'。"""
        for model_name in self.MEDIUM_MODEL_NAMES:
            cfg = _new_config()
            cfg._data["model_name"] = model_name
            tier = cfg.model_tier
            assert tier == "medium", \
                f"模型 '{model_name}' 应推断为 'medium'，实际为 '{tier}'"

    def test_unknown_model_tier_inference(self, temp_project):
        """TC-CFG-012: 未知模型推断为 'low'。"""
        for model_name in self.UNKNOWN_MODEL_NAMES:
            cfg = _new_config()
            cfg._data["model_name"] = model_name
            tier = cfg.model_tier
            assert tier == "low", \
                f"模型 '{model_name}' 应推断为 'low'，实际为 '{tier}'"

    def test_model_tier_explicit_override(self, temp_project):
        """验证 model_tier 可通过 _data 显式设置，不依赖推断。"""
        cfg = _new_config()
        cfg._data["model_tier"] = "high"
        cfg._data["model_name"] = "some-unknown-model"
        tier = cfg.model_tier
        assert tier == "high", \
            "显式设置的 model_tier 应优先于推断"

    def test_apply_model_tier_defaults_high(self, temp_project):
        """TC-CFG-013: apply_model_tier_defaults() 为 high tier 设置正确阈值。"""
        cfg = _new_config()
        cfg._data["model_tier"] = "high"
        cfg.apply_model_tier_defaults()

        assert cfg._data.get("foundation_threshold") == 7.5
        assert cfg._data.get("chapter_threshold") == 6.0
        assert cfg._data.get("max_foundation_iters") == 10
        assert cfg._data.get("max_chapter_attempts") == 5
        assert cfg._data.get("chapter_word_target") == 3250
        assert cfg._data.get("max_tokens_per_call") == 16000

    def test_apply_model_tier_defaults_medium(self, temp_project):
        """验证 medium tier 的默认阈值。"""
        cfg = _new_config()
        cfg._data["model_tier"] = "medium"
        cfg.apply_model_tier_defaults()

        assert cfg._data.get("foundation_threshold") == 7.0
        assert cfg._data.get("chapter_threshold") == 5.5
        assert cfg._data.get("max_foundation_iters") == 25
        assert cfg._data.get("chapter_word_target") == 2000
        assert cfg._data.get("max_tokens_per_call") == 8192

    def test_apply_model_tier_defaults_low(self, temp_project):
        """验证 low tier 的默认阈值。"""
        cfg = _new_config()
        cfg._data["model_tier"] = "low"
        cfg.apply_model_tier_defaults()

        assert cfg._data.get("foundation_threshold") == 6.5
        assert cfg._data.get("chapter_threshold") == 5.0
        assert cfg._data.get("max_foundation_iters") == 30
        assert cfg._data.get("chapter_word_target") == 1500
        assert cfg._data.get("max_tokens_per_call") == 4096

    def test_apply_model_tier_defaults_no_overwrite(self, temp_project):
        """验证 apply_model_tier_defaults() 不覆盖已有配置。"""
        cfg = _new_config()
        cfg._data["model_tier"] = "high"
        cfg._data["foundation_threshold"] = 9.0  # 用户自定义
        cfg.apply_model_tier_defaults()

        # 已有配置不被覆盖
        assert cfg._data.get("foundation_threshold") == 9.0
        # 未设置的配置仍被填充
        assert cfg._data.get("chapter_threshold") == 6.0


# ============================================================================
# 附加测试: Config 属性测试
# ============================================================================

class TestConfigProperties:
    """测试 Config 属性的默认值和边界行为。"""

    def test_story_summary_default_empty(self, temp_project):
        """验证空 story_summary 时的行为。"""
        cfg = _new_config()
        cfg._data = {}
        # story_summary 为空时尝试读取 output/story_summary.txt
        # 在测试环境中该文件不存在
        summary = cfg.story_summary
        assert summary == ""

    def test_story_summary_from_file(self, temp_project):
        """验证从文件读取 story_summary。"""
        cfg = _new_config()
        cfg._data = {}
        story_file = temp_project["output_dir"] / "story_summary.txt"
        story_file.write_text("这是一个测试故事梗概。", encoding="utf-8")

        summary = cfg.story_summary
        assert summary == "这是一个测试故事梗概。"

    def test_chapters_per_volume_auto_calc(self, temp_project):
        """验证 chapters_per_volume 自动计算。"""
        cfg = _new_config()
        cfg._data = {
            "total_chapters": 24,
            "total_volumes": 3,
        }
        assert cfg.chapters_per_volume == 8  # 24 // 3

    def test_chapters_per_volume_min_one(self, temp_project):
        """验证 chapters_per_volume 最小为 1。"""
        cfg = _new_config()
        cfg._data = {
            "total_chapters": 2,
            "total_volumes": 10,
        }
        assert cfg.chapters_per_volume == 1  # max(1, 2//10) = 1

    def test_phase_api_fallback(self, temp_project):
        """验证 Phase API 配置的回退链。"""
        cfg = _new_config()
        cfg._data = {
            "api_key": "main-key",
            "api_base_url": "https://main.api/v1",
            "model_name": "main-model",
        }

        # P1 未配置 → 回退到共用
        assert cfg.p1_api_key == "main-key"
        assert cfg.p1_model_name == "main-model"

        # P2 未配置 → P1 → 共用
        assert cfg.p2_api_key == "main-key"

        # P3 未配置 → P1 → 共用
        assert cfg.p3_model_name == "main-model"
