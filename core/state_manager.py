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
    BACKUPS_DIR, EDIT_LOGS_DIR, EVAL_LOGS_DIR, BRIEFS_DIR, config)

# 可选导入 debug_log
try:
    from core.diagnostic import debug_log as _debug_log
except ImportError:
    def _debug_log(*args, **kwargs):
        pass


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
            encoding="utf-8", errors="replace")
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
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            _debug_log("STATE_LOAD", data={
                "phase": data.get("phase", "?"),
                "chapters_drafted": data.get("chapters_drafted", 0),
            })
            return data
        except (json.JSONDecodeError, IOError) as e:
            _debug_log("STATE_ERROR", f"加载 state.json 失败: {e}",
                       data={"error": str(e)[:200]})
    return default_state()


def save_state(state: dict) -> None:
    """写入 state.json。"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        _debug_log("STATE_SAVE", data={
            "phase": state.get("phase", "?"),
            "chapters_drafted": state.get("chapters_drafted", 0),
        })
    except IOError as e:
        _debug_log("STATE_ERROR", f"保存 state.json 失败: {e}",
                   data={"error": str(e)[:200]})


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
        encoding="utf-8", errors="replace")


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
        key=lambda p: p.name, reverse=True)
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
    description: str = "") -> None:
    """追加一行到 results.tsv。

    如果 score 为负值（parse_score 无法解析时的哨兵 -1.0），
    将 status 自动改为 "error" 并标记 score 为 "N/A"。
    """
    header = "commit\tphase\tscore\tword_count\tstatus\tdescription\n"
    if not RESULTS_FILE.exists():
        RESULTS_FILE.write_text(header, encoding="utf-8")
    elif RESULTS_FILE.stat().st_size == 0:
        RESULTS_FILE.write_text(header, encoding="utf-8")

    # ★ 拦截 -1.0 哨兵值：评分解析失败时记录为 error 而非正常值
    display_score = score
    display_status = status
    if isinstance(score, (int, float)) and score < 0:
        display_score = "N/A"
        display_status = "error"
        description = f"[评分解析失败] {description}"

    with open(RESULTS_FILE, "a", encoding="utf-8") as f:
        row = f"{commit}\t{phase}\t{display_score}\t{word_count}\t{display_status}\t{description}\n"
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
# 分数解析 — 统一格式：JSON 优先，回退到单一固定 Markdown 格式
# ============================================================================

def parse_score(stdout: str, key: str = "overall_score") -> float:
    """
    从 LLM 评估输出中解析分数。

    策略（严格有序，不猜格式）:
      1. JSON 提取: 从文本中提取 JSON 对象，读取 key 字段
      2. Markdown 固定格式: `**综合评分**: X/10` 或 `key: X`
      3. 以上均失败 → 报错，记录原始输出

    Prompt 已锁定输出格式为纯 JSON（见 eval_judge_prompts.py）。
    此函数仅处理 LLM 未遵守 JSON 格式时的降级场景。
    """
    # ── 策略 1: JSON 提取 ──
    json_score = _try_json_extract(stdout, key)
    if json_score is not None:
        return json_score

    # ── 策略 2: 固定 Markdown 格式 ──
    # 2a: key: X 格式（最简）
    for line in stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith(f"{key}:"):
            val = stripped.split(":", 1)[1].strip().rstrip(",")
            try:
                return round(float(val), 1)
            except ValueError:
                continue

    # 2b: **综合评分**: X/10 格式
    m = re.search(
        r'\*\*综合评分\*\*\s*[：:]\s*(\d+(?:\.\d+)?)\s*/\s*10',
        stdout, re.IGNORECASE)
    if m:
        return round(float(m.group(1)), 1)

    # 2c: **评分**: X/10 格式（在 key 对应的 ### 小节内）
    m = re.search(
        rf'###.*?{re.escape(key)}.*?\n.*?\*\*评分\*\*\s*[：:]\s*(\d+(?:\.\d+)?)\s*/\s*10',
        stdout, re.DOTALL | re.IGNORECASE)
    if m:
        return round(float(m.group(1)), 1)

    # ── 全部失败 → 报错 ──
    raise ValueError(
        f"无法从 LLM 输出中解析 '{key}' 分数。"
        f"Prompt 要求 JSON 格式，但 LLM 未遵守。"
        f"原始输出前 500 字符:\n{stdout[:500]}"
    )


def _try_json_extract(text: str, key: str):
    """从文本中提取 JSON 并读取指定 key 的值。成功返回 float，失败返回 None。"""
    # 尝试直接 json.loads
    try:
        data = json.loads(text.strip())
        if key in data:
            return float(data[key])
    except (json.JSONDecodeError, ValueError, TypeError):
        pass

    # 尝试提取 ```json ... ``` 代码块
    m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(1).strip())
            if key in data:
                return float(data[key])
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

    # 尝试从第一个 { 到最后一个 } 提取
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end > start:
        try:
            data = json.loads(text[start:end + 1])
            if key in data:
                return float(data[key])
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

    return None


# ============================================================================
# 稳定评估 — 多次调用取中位数，降低 LLM 评分波动
# ============================================================================

def evaluate_chapter_stable(
    ch_num: int,
    retries: int = 2,
    max_total_time: int = 600,
    samples: int = 3) -> float:
    """稳定版章节评估：调用 N 次取中位数，过滤 -1.0 异常值。

    用于修订前后的评分比较，避免单次 LLM 评分波动导致误判回退。
    """
    from evaluation.evaluate import evaluate_chapter as _eval
    scores: list[float] = []
    for _ in range(samples):
        try:
            result = _eval(ch_num, retries=retries, max_total_time=max_total_time)
            s = parse_score(result, "overall_score")
            if s >= 0:
                scores.append(s)
        except Exception:
            pass
    if not scores:
        return 0.0
    scores.sort()
    return scores[len(scores) // 2]  # 中位数


def evaluate_foundation_stable(
    retries: int = 3,
    max_total_time: int = None,
    samples: int = 3) -> float:
    """稳定版 Foundation 评估：调用 N 次取中位数。

    用于 Foundation 迭代间的评分比较，避免 LLM 评分波动导致
    更优的迭代被错误丢弃。
    """
    from evaluation.evaluate import evaluate_foundation as _eval
    scores: list[float] = []
    for _ in range(samples):
        try:
            result = _eval(retries=retries,
                           max_total_time=max_total_time)
            s = parse_score(result, "overall_score")
            if s >= 0:
                scores.append(s)
        except Exception:
            pass
    if not scores:
        return 0.0
    scores.sort()
    return scores[len(scores) // 2]  # 中位数


def parse_lore_score(stdout: str) -> float:
    """解析 lore_score。"""
    return parse_score(stdout, "lore_score")