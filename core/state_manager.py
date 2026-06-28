"""
core/state_manager.py — 状态管理 + git/文件备份双模式

原 autonovel 深度依赖 git（commit / reset / short_hash / log）。
重构方案：自动检测 git 可用性，不可用时使用文件快照备份。

提供与原版完全兼容的接口：
- load_state / save_state
- commit / reset / short_hash
- log_result
- backup / restore
"""

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.config import (
    ROOT_DIR, OUTPUT_DIR, CHAPTERS_DIR, STATE_FILE, RESULTS_FILE,
    BACKUPS_DIR, EDIT_LOGS_DIR, EVAL_LOGS_DIR, BRIEFS_DIR, config,
)


# ============================================================================
# Git 检测
# ============================================================================

def _has_git() -> bool:
    """检测当前环境是否可用 git（.git 目录存在 + git 命令可用）。"""
    git_dir = ROOT_DIR / ".git"
    if not git_dir.exists():
        return False
    try:
        result = subprocess.run(
            ["git", "status"],
            capture_output=True, text=True, timeout=10,
            cwd=str(ROOT_DIR),
            encoding="utf-8", errors="replace",
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


# 缓存检测结果
_GIT_AVAILABLE: Optional[bool] = None


def git_available() -> bool:
    global _GIT_AVAILABLE
    if _GIT_AVAILABLE is None:
        _GIT_AVAILABLE = _has_git()
        if _GIT_AVAILABLE:
            print("  [状态] Git 可用，使用 Git 版本控制", file=sys.stderr)
        else:
            print("  [状态] Git 不可用，使用文件快照备份", file=sys.stderr)
    return _GIT_AVAILABLE


# ============================================================================
# 状态管理
# ============================================================================

def default_state() -> dict:
    return {
        "phase": "foundation",
        "current_focus": "planning",
        "iteration": 0,
        "foundation_score": 0.0,
        "lore_score": 0.0,
        "chapters_drafted": 0,
        "chapters_total": 0,
        "novel_score": 0.0,
        "revision_cycle": 0,
        "debts": [],
        # === 方案 D 新增 ===
        "total_volumes": 0,
        "chapters_per_volume": 0,
        "current_volume": 1,
        "volumes_outlined": 0,
        "canon_entry_count": 0,
        "canon_last_updated_ch": 0,
    }


def load_state() -> dict:
    """加载 state.json，不存在则返回默认状态。"""
    if STATE_FILE.exists():
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return default_state()


def save_state(state: dict) -> None:
    """写入 state.json。"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def get_total_chapters(state: dict) -> int:
    """从 state 或 config 确定总章节数。"""
    if state.get("chapters_total", 0) > 0:
        return state["chapters_total"]
    cfg = config
    cfg.load()
    if cfg.loaded and cfg.total_chapters > 0:
        return cfg.total_chapters
    return 24  # 保底默认


def count_words_in_chapters() -> int:
    """统计所有章节文件的中文字数。"""
    total = 0
    if CHAPTERS_DIR.exists():
        for f in CHAPTERS_DIR.glob("ch_*.md"):
            text = f.read_text(encoding="utf-8")
            total += len(text.replace(" ", "").replace("\n", ""))
    return total


def count_chapter_files() -> int:
    if not CHAPTERS_DIR.exists():
        return 0
    return len(list(CHAPTERS_DIR.glob("ch_*.md")))


# ============================================================================
# Git 模式操作
# ============================================================================

def _git_run(cmd: str, timeout: int = 30) -> subprocess.CompletedProcess:
    """执行 git 命令，返回 CompletedProcess。使用 shlex.split 安全解析参数。"""
    return subprocess.run(
        shlex.split(cmd),
        capture_output=True, text=True,
        timeout=timeout, cwd=str(ROOT_DIR),
        encoding="utf-8", errors="replace",
    )


def git_short_hash() -> str:
    """获取当前 HEAD 短哈希。无 git 环境返回时间戳标识。"""
    if not git_available():
        return datetime.now().strftime("%Y%m%d%H%M%S")
    r = _git_run("git rev-parse --short HEAD")
    if r.returncode == 0:
        return r.stdout.strip()
    return datetime.now().strftime("%Y%m%d%H%M%S")


# 核心产出文件（纳入 Git 版本控制）
# 注意：backups/, chapters/, briefs/, edit_logs/, eval_logs/ 等高频/大体积产物
#      已通过 .gitignore 排除，不纳入 Git 追踪。
_GIT_TRACKED_GLOBS = [
    "world.md", "characters.md", "outline.md", "canon.md",
    "voice.md", "story_summary.txt",
    # state.json 保持追踪（小文件、低频变更、中断恢复关键）
    "state.json",
    # 基础模板
    "MYSTERY.md",
]


def git_add_commit(message: str) -> str:
    """Stage core output files and commit。返回短哈希。"""
    if git_available():
        # 只 add 核心产出文件，不再 git add -A
        # 避免将 backups/ 等高频大体积产物纳入 Git 索引
        from core.config import OUTPUT_DIR
        for pattern in _GIT_TRACKED_GLOBS:
            target = OUTPUT_DIR / pattern
            if target.exists():
                _git_run(f"git add \"{target}\"")
        result = _git_run(f'git commit -m "{message}" --allow-empty')
        if result.returncode == 0:
            return git_short_hash()
        print(f"  [Git] 提交失败或无变更: {message}", file=sys.stderr)
        return ""
    else:
        # 文件备份模式
        return backup_snapshot(message)


def git_reset_hard(ref: str = "HEAD"):
    """Hard reset 丢弃变更。Git 模式用 reset，备份模式用 restore。"""
    if git_available():
        print(f"  [Git] 回滚到: {ref}", file=sys.stderr)
        _git_run(f"git reset --hard {ref}")
    else:
        # 备份模式：恢复最近的快照
        restore_latest()


# ============================================================================
# 文件快照备份模式（无 Git 时的替代方案）
# ============================================================================

def backup_snapshot(label: str = "") -> str:
    """
    备份当前关键文件到 backups/{timestamp}/。
    返回 timestamp 标识。
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = BACKUPS_DIR / timestamp
    backup_dir.mkdir(parents=True, exist_ok=True)

    # 备份的文件列表
    files_to_backup = [
        "world.md", "characters.md", "outline.md", "canon.md",
        "voice.md", "MYSTERY.md", "state.json", "story_summary.txt",
    ]
    # 模板文件存在于 templates/，实际文件位于 output/
    _src_dirs = [OUTPUT_DIR, ROOT_DIR]

    for fname in files_to_backup:
        for src_dir in _src_dirs:
            src = src_dir / fname
            if src.exists():
                shutil.copy2(str(src), str(backup_dir / fname))
                break

    # 备份所有章节
    if CHAPTERS_DIR.exists():
        ch_backup_dir = backup_dir / "chapters"
        ch_backup_dir.mkdir(exist_ok=True)
        for ch in CHAPTERS_DIR.glob("ch_*.md"):
            shutil.copy2(str(ch), str(ch_backup_dir / ch.name))

    # 记录标签
    (backup_dir / "label.txt").write_text(label, encoding="utf-8")

    snapshot_id = f"snapshot-{timestamp}"
    print(f"  [备份] {snapshot_id}: {label}", file=sys.stderr)
    return snapshot_id


def restore_latest() -> bool:
    """从最新备份恢复所有文件。"""
    if not BACKUPS_DIR.exists():
        print("  [备份] 无可用备份", file=sys.stderr)
        return False

    backups = sorted(
        [d for d in BACKUPS_DIR.iterdir() if d.is_dir()],
        key=lambda p: p.name, reverse=True,
    )
    if not backups:
        print("  [备份] 无可用备份", file=sys.stderr)
        return False

    latest = backups[0]
    label_file = latest / "label.txt"
    label = label_file.read_text(encoding="utf-8").strip() if label_file.exists() else ""

    print(f"  [备份] 恢复到: {latest.name} ({label})", file=sys.stderr)

    # 恢复根目录文件到 output/
    for f in latest.iterdir():
        if f.is_file() and f.name != "label.txt":
            dest = OUTPUT_DIR / f.name
            shutil.copy2(str(f), str(dest))

    # 恢复章节
    ch_backup = latest / "chapters"
    if ch_backup.exists():
        CHAPTERS_DIR.mkdir(parents=True, exist_ok=True)
        for ch in ch_backup.glob("ch_*.md"):
            shutil.copy2(str(ch), str(CHAPTERS_DIR / ch.name))

    return True


# ============================================================================
# 日志记录
# ============================================================================

def log_result(
    commit: str,
    phase: str,
    score,
    word_count: int = 0,
    status: str = "",
    description: str = "",
) -> None:
    """追加一行到 results.tsv。"""
    header = "commit\tphase\tscore\tword_count\tstatus\tdescription\n"
    if not RESULTS_FILE.exists():
        RESULTS_FILE.write_text(header, encoding="utf-8")
    elif RESULTS_FILE.stat().st_size == 0:
        RESULTS_FILE.write_text(header, encoding="utf-8")

    with open(RESULTS_FILE, "a", encoding="utf-8") as f:
        row = f"{commit}\t{phase}\t{score}\t{word_count}\t{status}\t{description}\n"
        f.write(row)


# ============================================================================
# 打印辅助
# ============================================================================

def banner(text: str, char: str = "=", width: int = 70):
    """阶段横幅。"""
    print(f"\n{char * width}")
    print(f"  {text}")
    print(f"{char * width}")


def step(text: str):
    """时间戳步骤提示。"""
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"  [{ts}] {text}")


# ============================================================================
# 分数解析 (兼容原 evaluate.py 输出)
# ============================================================================

def parse_score(stdout: str, key: str = "overall_score") -> float:
    """
    从 evaluate.py 输出中解析分数。
    兼容两种格式：
      1. key: 8.0           （冒号格式）
      2. **评分**: 9/10      （分数格式，出现在 key 标题下方的 markdown 中）
    """
    lines = stdout.splitlines()
    in_section = False
    for i, line in enumerate(lines):
        stripped = line.strip()

        # 格式 1: key: 8.0
        if stripped.startswith(f"{key}:"):
            val = stripped.split(":", 1)[1].strip()
            try:
                return float(val)
            except ValueError:
                continue

        # 格式 2: 检测是否进入了目标 key 的 markdown 小节
        if key in stripped and stripped.startswith("###"):
            in_section = True
            continue

        # 如果在 key 小节内，查找 **评分**: X/Y 格式
        if in_section:
            # 遇到下一个 ### 就离开当前小节
            if stripped.startswith("###"):
                in_section = False
                continue
            # 匹配 **评分**: 9/10 或 **Score**: 9/10 等
            m = re.match(
                r"\*\*.*?(?:评分|Score|score)\*\*\s*:\s*(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)",
                stripped,
            )
            if m:
                numerator = float(m.group(1))
                denominator = float(m.group(2))
                if denominator > 0:
                    return numerator / denominator * 10.0  # 转换为 10 分制
                return numerator
            # 也尝试匹配纯数字评分: **评分**: 8.5
            m2 = re.match(
                r"\*\*.*?(?:评分|Score|score)\*\*\s*:\s*(\d+(?:\.\d+)?)",
                stripped,
            )
            if m2:
                val = float(m2.group(1))
                # 如果值 > 10 可能是百分制，缩放到10分制
                if val > 11:
                    return val / 10.0
                return val

    # ——— Fallback: 全文收集所有候选评分，取位置最靠后的 ———
    # 裁判模型不使用固定的 ### overall_score 小节头，输出格式多样化。
    # 跨模式收集所有 (end_position, value) 候选，取 end 最大者
    # （最后出现的评分通常是整体评分而非子维度评分）。
    candidates: list[tuple[int, float]] = []  # (end_pos, value)

    fallback_patterns = [
        # 格式 A: 综合评分：6.5/10 或 Overall Score: 6.5 或 Score: 8.2
        (r'(?:综合评分|Overall\s+Score|final\s+score|Score)\s*[：:]\s*\*{0,2}(\d+(?:\.\d+)?)\*{0,2}\s*(?:/\s*\*{0,2}(\d+(?:\.\d+)?)\*{0,2})?', True),
        # 格式 B: ### 15. overall_score ... 或 ## score: 7.0 或 overall_score: 6.5
        (r'(?:overall_score|Overall_Score|score)[^:\n]*[：:]\s*\*{0,2}(\d+(?:\.\d+)?)\*{0,2}\s*(?:/\s*\*{0,2}(\d+(?:\.\d+)?)\*{0,2})?', False),
        # 格式 C: 最终评分：**6.5/10**
        (r'最终评分\s*[：:]\s*\*{0,2}(\d+(?:\.\d+)?)\*{0,2}\s*(?:/\s*\*{0,2}(\d+(?:\.\d+)?)\*{0,2})?', True),
        # 格式 D: **评分**: 6.5/10 或 **score**: 6.5
        (r'\*\*(?:评分|Score|score)\*\*\s*[：:]\s*\*{0,2}(\d+(?:\.\d+)?)\*{0,2}\s*(?:/\s*\*{0,2}(\d+(?:\.\d+)?)\*{0,2})?', False),
        # 格式 E: X/10 分数
        (r'(?:评分|Score|score)[^:\n]*?(\d+(?:\.\d+)?)\s*/\s*(?:10|十)', False),
    ]
    for pattern, search_whole in fallback_patterns:
        flags = re.IGNORECASE if search_whole else re.IGNORECASE | re.MULTILINE
        for m in re.finditer(pattern, stdout, flags):
            try:
                val = float(m.group(1))
            except (ValueError, IndexError):
                continue
            if m.lastindex and m.lastindex >= 2:
                try:
                    denom = float(m.group(2))
                    if denom > 0:
                        val = val / denom * 10.0
                except (ValueError, IndexError):
                    pass
            if val > 11:
                val = val / 10.0
            if 0 <= val <= 10:
                candidates.append((m.end(), val))

    if candidates:
        # 取全文最后一个评分候选（end 位置最大）
        candidates.sort(key=lambda x: x[0])
        return candidates[-1][1]

    return -1.0


def parse_lore_score(stdout: str) -> float:
    """解析 lore_score。"""
    return parse_score(stdout, "lore_score")