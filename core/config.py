"""
core/config.py — 全局配置加载模块

从 .env 加载敏感信息（API Key 等），从 output/config.json 加载项目状态。
所有生成脚本均可导入此模块获取 API 参数、故事梗概等。
"""

import json
import os
from pathlib import Path
from typing import Optional

# python-dotenv (已在 pyproject.toml 中声明)
try:
    from dotenv import load_dotenv, set_key
    _HAS_DOTENV = True
except ImportError:
    _HAS_DOTENV = False

# 项目根目录
ROOT_DIR = Path(__file__).parent.parent
OUTPUT_DIR = ROOT_DIR / "output"
TEMPLATES_DIR = ROOT_DIR / "templates"
CHAPTERS_DIR = OUTPUT_DIR / "chapters"
BRIEFS_DIR = OUTPUT_DIR / "briefs"
EDIT_LOGS_DIR = OUTPUT_DIR / "edit_logs"
EVAL_LOGS_DIR = OUTPUT_DIR / "eval_logs"
BACKUPS_DIR = OUTPUT_DIR / "backups"

ENV_FILE = ROOT_DIR / ".env"
CONFIG_FILE = OUTPUT_DIR / "config.json"
STATE_FILE = OUTPUT_DIR / "state.json"
RESULTS_FILE = OUTPUT_DIR / "results.tsv"

# .env → 内部键名映射（敏感信息：API Key / 端点 / 模型名）
_SECRET_KEYS = {
    "api_key":              "AUTONOVEL_API_KEY",
    "api_base_url":         "AUTONOVEL_API_BASE_URL",
    "model_name":           "AUTONOVEL_MODEL_NAME",
    "api_interval_seconds": "AUTONOVEL_API_INTERVAL_SECONDS",
    "judge_api_key":        "AUTONOVEL_JUDGE_API_KEY",
    "judge_api_base_url":   "AUTONOVEL_JUDGE_API_BASE_URL",
    "judge_model_name":     "AUTONOVEL_JUDGE_MODEL_NAME",
    # === 方案 D: Phase 分离模型配置 ===
    "p1_api_key":           "AUTONOVEL_P1_API_KEY",
    "p1_api_base_url":      "AUTONOVEL_P1_API_BASE_URL",
    "p1_model_name":        "AUTONOVEL_P1_MODEL_NAME",
    "p2_api_key":           "AUTONOVEL_P2_API_KEY",
    "p2_api_base_url":      "AUTONOVEL_P2_API_BASE_URL",
    "p2_model_name":        "AUTONOVEL_P2_MODEL_NAME",
    "p2_ctx_api_key":       "AUTONOVEL_P2_CTX_API_KEY",
    "p2_ctx_api_base_url":  "AUTONOVEL_P2_CTX_API_BASE_URL",
    "p2_ctx_model_name":    "AUTONOVEL_P2_CTX_MODEL_NAME",
    "p3_api_key":           "AUTONOVEL_P3_API_KEY",
    "p3_api_base_url":      "AUTONOVEL_P3_API_BASE_URL",
    "p3_model_name":        "AUTONOVEL_P3_MODEL_NAME",
}


class Config:
    """全局配置单例，从 .env + output/config.json 加载。"""

    def __init__(self):
        self._data: dict = {}
        self._loaded = False

    # ——— 加载 —————————————————————

    def load(self) -> dict:
        """加载配置。优先 .env（敏感信息），再合并 config.json（状态）。"""
        if self._loaded:
            return self._data

        # 1) 从 .env 加载敏感信息
        self._load_env()

        # 2) 从 config.json 合并非敏感状态
        self._load_config_json()

        self._loaded = True
        return self._data

    def _load_env(self) -> None:
        """从 .env 文件加载敏感配置。"""
        if _HAS_DOTENV and ENV_FILE.exists():
            load_dotenv(ENV_FILE, override=True)

        for internal_key, env_key in _SECRET_KEYS.items():
            value = os.getenv(env_key, "")
            if value:
                if internal_key == "api_interval_seconds":
                    try:
                        value = float(value)
                    except ValueError:
                        value = 4.0
                self._data[internal_key] = value

    def _load_config_json(self) -> None:
        """从 config.json 合并非敏感状态（不会覆盖 .env 已加载的键）。"""
        if not CONFIG_FILE.exists():
            return
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                json_data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return

        for key, value in json_data.items():
            # config.json 中的敏感键忽略（以 .env 为准）
            if key in _SECRET_KEYS:
                continue
            self._data[key] = value

    # ——— 保存 —————————————————————

    def save(self, data: dict) -> None:
        """保存配置：敏感信息写入 .env，状态写入 config.json。"""
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        self._data = data

        # 写入 .env（仅敏感键）
        self._save_env(data)

        # 写入 config.json（仅非敏感键）
        self._save_config_json(data)

        self._loaded = True

    def _save_env(self, data: dict) -> None:
        """将敏感键写入 .env 文件。"""
        if not _HAS_DOTENV:
            return

        # 确保 .env 文件存在
        if not ENV_FILE.exists():
            ENV_FILE.touch()

        for internal_key, env_key in _SECRET_KEYS.items():
            value = data.get(internal_key, "")
            if value:
                set_key(str(ENV_FILE), env_key, str(value))

    def _save_config_json(self, data: dict) -> None:
        """将非敏感键写入 config.json。"""
        non_secret = {}
        for key, value in data.items():
            if key not in _SECRET_KEYS:
                non_secret[key] = value

        if non_secret:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(non_secret, f, indent=2, ensure_ascii=False)

    # ——— 通用 —————————————————————

    @property
    def loaded(self) -> bool:
        return self._loaded

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    # ——— 便捷属性 —————————————————————

    @property
    def api_base_url(self) -> str:
        return self._data.get("api_base_url", "https://api.siliconflow.cn/v1")

    @property
    def api_key(self) -> str:
        return self._data.get("api_key", "")

    @property
    def model_name(self) -> str:
        return self._data.get("model_name", "deepseek-ai/DeepSeek-V3")

    @property
    def api_interval_seconds(self) -> float:
        val = self._data.get("api_interval_seconds", 4.0)
        if isinstance(val, str):
            try:
                return float(val)
            except ValueError:
                return 4.0
        return float(val)

    @property
    def story_summary(self) -> str:
        """用户输入的故事梗概。"""
        summary = self._data.get("story_summary", "")
        if not summary:
            story_file = OUTPUT_DIR / "story_summary.txt"
            if story_file.exists():
                summary = story_file.read_text(encoding="utf-8-sig").strip()
        return summary

    @property
    def novel_title(self) -> str:
        return self._data.get("novel_title", "")

    @property
    def total_chapters(self) -> int:
        return self._data.get("total_chapters", 24)

    # ============================================================
    # 卷级配置（方案 D）
    # ============================================================

    @property
    def total_volumes(self) -> int:
        """总卷数。默认 1（方案 D 始终启用分层大纲，单卷时一卷含全部章节）。"""
        return self._data.get("total_volumes", 1)

    @property
    def chapters_per_volume(self) -> int:
        """每卷章节数。未配置时自动 = total_chapters // total_volumes，最小 1。"""
        val = self._data.get("chapters_per_volume", 0)
        if val > 0:
            return val
        return max(1, self.total_chapters // max(1, self.total_volumes))

    @property
    def mode(self) -> str:
        """生成模式: 'from_scratch' | 'resume'"""
        return self._data.get("mode", "from_scratch")

    @property
    def genre(self) -> str:
        return self._data.get("genre", "玄幻")

    # ——— 判断模型独立配置 —————————————————————

    @property
    def judge_model_name(self) -> str:
        return self._data.get("judge_model_name", "")

    @property
    def judge_api_base_url(self) -> str:
        return self._data.get("judge_api_base_url", "")

    @property
    def judge_api_key(self) -> str:
        return self._data.get("judge_api_key", "")

    # ============================================================
    # Phase 分离模型配置（方案 D）
    # — 每个 Phase 可指定独立的 API Key / Base URL / Model Name
    # — 回退链:
    #   P1:     p1_*     → 共用_*
    #   P2:     p2_*     → p1_*      → 共用_*
    #   P2_CTX: p2_ctx_* → p2_*      → p1_*      → 共用_*
    #   P3:     p3_*     → p1_*      → 共用_*
    # — 用户通常只需配置 P1；P2/P3 留空自动复用 Phase 1
    # ============================================================

    # --- Phase 1: 基础构建 (world/characters/outline/canon/voice) ---

    @property
    def p1_api_key(self) -> str:
        return self._data.get("p1_api_key") or self.api_key

    @property
    def p1_api_base_url(self) -> str:
        return self._data.get("p1_api_base_url") or self.api_base_url

    @property
    def p1_model_name(self) -> str:
        return self._data.get("p1_model_name") or self.model_name

    # --- Phase 2: 章节起草 ---
    # 回退链: p2_* → p1_* → 共用_*

    @property
    def p2_api_key(self) -> str:
        return self._data.get("p2_api_key") or self._data.get("p1_api_key") or self.api_key

    @property
    def p2_api_base_url(self) -> str:
        return self._data.get("p2_api_base_url") or self._data.get("p1_api_base_url") or self.api_base_url

    @property
    def p2_model_name(self) -> str:
        return self._data.get("p2_model_name") or self._data.get("p1_model_name") or self.model_name

    # --- Phase 2 上下文模型（可选: canon 增量追加等大上下文任务）---
    # 回退链: p2_ctx_* → p2_* → p1_* → 共用_*

    @property
    def p2_ctx_api_key(self) -> str:
        return (self._data.get("p2_ctx_api_key")
                or self._data.get("p2_api_key")
                or self._data.get("p1_api_key")
                or self.api_key)

    @property
    def p2_ctx_api_base_url(self) -> str:
        return (self._data.get("p2_ctx_api_base_url")
                or self._data.get("p2_api_base_url")
                or self._data.get("p1_api_base_url")
                or self.api_base_url)

    @property
    def p2_ctx_model_name(self) -> str:
        return (self._data.get("p2_ctx_model_name")
                or self._data.get("p2_model_name")
                or self._data.get("p1_model_name")
                or self.model_name)

    # --- Phase 3: 修订评估 (对抗编辑/读者评审/全文评估) ---
    # 回退链: p3_* → p1_* → 共用_*

    @property
    def p3_api_key(self) -> str:
        return self._data.get("p3_api_key") or self._data.get("p1_api_key") or self.api_key

    @property
    def p3_api_base_url(self) -> str:
        return self._data.get("p3_api_base_url") or self._data.get("p1_api_base_url") or self.api_base_url

    @property
    def p3_model_name(self) -> str:
        return self._data.get("p3_model_name") or self._data.get("p1_model_name") or self.model_name

    # ——— 阈值 —————————————————————

    @property
    def foundation_threshold(self) -> float:
        return self._data.get("foundation_threshold", 7.5)

    @property
    def chapter_threshold(self) -> float:
        return self._data.get("chapter_threshold", 7.0)

    @property
    def max_foundation_iters(self) -> int:
        return self._data.get("max_foundation_iters", 20)

    @property
    def max_chapter_attempts(self) -> int:
        return self._data.get("max_chapter_attempts", 10)

    @property
    def chapter_word_target(self) -> int:
        """中文每章字数目标（中值，实际区间 3000–3500 字）。"""
        return self._data.get("chapter_word_target", 3250)

    @property
    def max_revision_cycles(self) -> int:
        """修订最大循环数（可从 config.json 覆盖，默认 6）。"""
        return self._data.get("max_revision_cycles", 6)

    @property
    def max_tokens_per_call(self) -> int:
        return self._data.get("max_tokens_per_call", 16000)

    # ——— P2-11: slop/反模式/canon 门槛 —————————————————————

    @property
    def canon_min_entries(self) -> int:
        return self._data.get("canon_min_entries", 400)

    @property
    def slop_penalty_threshold(self) -> float:
        return self._data.get("slop_penalty_threshold", 3.0)

    @property
    def antipattern_max_warnings(self) -> int:
        return self._data.get("antipattern_max_warnings", 4)

    def __repr__(self) -> str:
        return f"Config(api={self.api_base_url}, model={self.model_name}, ch={self.total_chapters})"


# 全局单例
config = Config()

# 预创建关键目录（只读文件系统友好：exist_ok=True + try/except 包裹）
try:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    CHAPTERS_DIR.mkdir(parents=True, exist_ok=True)
    BRIEFS_DIR.mkdir(parents=True, exist_ok=True)
    EDIT_LOGS_DIR.mkdir(parents=True, exist_ok=True)
    EVAL_LOGS_DIR.mkdir(parents=True, exist_ok=True)
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    pass