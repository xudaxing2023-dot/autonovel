"""
core/config.py — 全局配置加载模块

从 output/config.json 加载用户配置，提供全局可访问的配置单例。
所有生成脚本均可导入此模块获取 API 参数、故事梗概等。
"""

import json
import os
from pathlib import Path
from typing import Optional

# 项目根目录 (e:/my novel/)
ROOT_DIR = Path(__file__).parent.parent
OUTPUT_DIR = ROOT_DIR / "output"
TEMPLATES_DIR = ROOT_DIR / "templates"
CHAPTERS_DIR = OUTPUT_DIR / "chapters"
BRIEFS_DIR = OUTPUT_DIR / "briefs"
EDIT_LOGS_DIR = OUTPUT_DIR / "edit_logs"
EVAL_LOGS_DIR = OUTPUT_DIR / "eval_logs"
BACKUPS_DIR = OUTPUT_DIR / "backups"

CONFIG_FILE = OUTPUT_DIR / "config.json"
STATE_FILE = OUTPUT_DIR / "state.json"
RESULTS_FILE = OUTPUT_DIR / "results.tsv"


class Config:
    """全局配置单例，从 output/config.json 加载。"""

    def __init__(self):
        self._data: dict = {}
        self._loaded = False

    def load(self) -> dict:
        """加载配置文件。若不存在则返回空字典。"""
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                self._data = json.load(f)
            self._loaded = True
        return self._data

    def save(self, data: dict) -> None:
        """保存配置到文件。"""
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        self._data = data
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        self._loaded = True

    @property
    def loaded(self) -> bool:
        return self._loaded

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    # ——— 便捷属性 ———

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
        return self._data.get("api_interval_seconds", 4.0)

    @property
    def story_summary(self) -> str:
        """用户输入的故事梗概。"""
        # 优先从 config.json 读取，其次从 story_summary.txt
        summary = self._data.get("story_summary", "")
        if not summary:
            story_file = OUTPUT_DIR / "story_summary.txt"
            if story_file.exists():
                summary = story_file.read_text(encoding="utf-8").strip()
        return summary

    @property
    def novel_title(self) -> str:
        """小说标题，从梗概中提取或由 gen_outline 阶段生成。"""
        return self._data.get("novel_title", "")

    @property
    def total_chapters(self) -> int:
        return self._data.get("total_chapters", 24)

    @property
    def mode(self) -> str:
        """生成模式: 'from_scratch' | 'resume'"""
        return self._data.get("mode", "from_scratch")

    @property
    def genre(self) -> str:
        """小说类型，从梗概自动识别。"""
        return self._data.get("genre", "玄幻")

    # ——— 阈值（根据模型能力自动调整） ———

    @property
    def foundation_threshold(self) -> float:
        return self._data.get("foundation_threshold", 7.5)

    @property
    def chapter_threshold(self) -> float:
        return self._data.get("chapter_threshold", 6.0)

    @property
    def max_foundation_iters(self) -> int:
        return self._data.get("max_foundation_iters", 20)

    @property
    def max_chapter_attempts(self) -> int:
        return self._data.get("max_chapter_attempts", 5)

    @property
    def chapter_word_target(self) -> int:
        """中文每章字数目标。"""
        return self._data.get("chapter_word_target", 2500)

    @property
    def max_tokens_per_call(self) -> int:
        return self._data.get("max_tokens_per_call", 16000)

    # ——— 模型能力等级 ———

    @property
    def model_tier(self) -> str:
        """
        根据模型名称推断能力等级：'high' / 'medium' / 'low'
        影响重试次数和评分阈值。
        """
        return self._data.get("model_tier", self._guess_model_tier())

    def _guess_model_tier(self) -> str:
        model = self.model_name.lower()
        if any(k in model for k in ["deepseek-v3", "deepseek-v4", "deepseek-chat", "deepseek-r1", "llama-3.3-70b", "llama-3.1-405b", "qwen2.5-72b"]):
            return "high"
        if any(k in model for k in ["qwen2.5-32b", "llama-3.1-70b", "llama-3-70b"]):
            return "medium"
        return "low"

    def apply_model_tier_defaults(self) -> None:
        """根据 model_tier 自动设置阈值和重试次数。"""
        tier = self.model_tier
        defaults = {
            "high": {
                "foundation_threshold": 7.5, "chapter_threshold": 6.0,
                "max_foundation_iters": 20, "max_chapter_attempts": 5,
                "chapter_word_target": 2500, "max_tokens_per_call": 16000,
                "min_revision_cycles": 3, "max_revision_cycles": 6,
                "plateau_delta": 0.3,
            },
            "medium": {
                "foundation_threshold": 7.0, "chapter_threshold": 5.5,
                "max_foundation_iters": 25, "max_chapter_attempts": 6,
                "chapter_word_target": 2000, "max_tokens_per_call": 8192,
                "min_revision_cycles": 4, "max_revision_cycles": 7,
                "plateau_delta": 0.4,
            },
            "low": {
                "foundation_threshold": 6.5, "chapter_threshold": 5.0,
                "max_foundation_iters": 30, "max_chapter_attempts": 7,
                "chapter_word_target": 1500, "max_tokens_per_call": 4096,
                "min_revision_cycles": 5, "max_revision_cycles": 8,
                "plateau_delta": 0.5,
            },
        }
        d = defaults.get(tier, defaults["high"])
        for k, v in d.items():
            if k not in self._data:
                self._data[k] = v

    def __repr__(self) -> str:
        return f"Config(api={self.api_base_url}, model={self.model_name}, ch={self.total_chapters})"


# 全局单例
config = Config()

# 预创建关键目录
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
CHAPTERS_DIR.mkdir(parents=True, exist_ok=True)
BRIEFS_DIR.mkdir(parents=True, exist_ok=True)
EDIT_LOGS_DIR.mkdir(parents=True, exist_ok=True)
EVAL_LOGS_DIR.mkdir(parents=True, exist_ok=True)
BACKUPS_DIR.mkdir(parents=True, exist_ok=True)