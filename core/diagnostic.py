#!/usr/bin/env python3
"""Business source instrumentation - minimal, zero-dependency.
 
Writes one line per event to logs/diagnostic.log (diag) or logs/debug.log (debug_log).
diag() — fine-grained technical events, auto-clears on first write.
debug_log() — high-level business events, append mode.
"""
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

LOGS_DIR = Path(__file__).parent.parent / "logs"
LOG_PATH = LOGS_DIR / "diagnostic.log"
DEBUG_LOG_PATH = LOGS_DIR / "debug.log"
JSONL_LOG_PATH = LOGS_DIR / "debug.jsonl"
_CLEARED = False
_DEBUG_CLEARED = False

# P0-1: event → level 隐式映射（未列出的默认为 INFO）
_EVENT_LEVEL = {
    "CRASH": "ERROR", "API_FAIL": "ERROR", "STATE_ERROR": "ERROR",
    "WARNING": "WARNING", "API_RETRY": "WARNING", "JSON_PARSE_FALLBACK": "WARNING",
    "FILE_READ_WARN": "WARNING", "SCORE_PARSE_WARN": "WARNING",
}

# Windows 终端编码兼容性修复
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _ensure():
    global _CLEARED
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not _CLEARED:
        # Clear previous run's log
        LOG_PATH.write_text("", encoding="utf-8")
        _CLEARED = True


def _safe(val, max_len=200):
    """Truncate long values to keep log compact."""
    s = str(val)
    return s if len(s) <= max_len else s[:max_len] + "..."


def _ts():
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def _caller_info():
    """Get (filename, lineno, function) of the caller's caller."""
    try:
        frame = sys._getframe(2)
        fname = Path(frame.f_code.co_filename).name
        lineno = frame.f_lineno
        func = frame.f_code.co_name
        return f"{fname}:{lineno} {func}"
    except Exception:
        return "?:?"


def diag(event, detail="", data=None):
    """Write one diagnostic event to diagnostic.log.

    Args:
        event: Short event code, e.g. "SENTINEL_PARSE" or "GIT_RESET"
        detail: Human-readable context
        data: Optional dict of key=value pairs (values auto-truncated)
    """
    ts = _ts()
    caller = _caller_info()
    parts = [f"[{ts}] [{event}] [{caller}]"]
    if detail:
        parts.append(detail)
    if data:
        items = [f"{k}={_safe(v)}" for k, v in data.items()]
        parts.append(" | " + ", ".join(items))

    line = "".join(parts) + "\n"
    _ensure()
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
    except Exception:
        pass
    try:
        print(f"  [DIAG] {line.strip()}", file=sys.stderr)
    except (OSError, UnicodeEncodeError):
        pass


# ============================================================================
# debug_log — 高级别业务事件日志 (追加模式, 写入 logs/debug.log)
# ============================================================================

def _debug_ts():
    """Full ISO-ish timestamp for debug log."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _debug_caller():
    """Get (filename, lineno, function) of the caller."""
    try:
        frame = sys._getframe(2)  # debug_log → caller
        fname = Path(frame.f_code.co_filename).name
        lineno = frame.f_lineno
        func = frame.f_code.co_name
        return f"{fname}:{lineno} {func}"
    except Exception:
        return "?:?"


def debug_log(event: str, detail: str = "", data: dict = None,
              exc_info: bool = False, **kwargs) -> None:
    """Write a structured debug event to logs/debug.log (append mode).

    Format: [YYYY-MM-DD HH:MM:SS.mmm] [LEVEL] [EVENT] [caller] detail | k=v, ...

    Also writes a JSON Lines entry to logs/debug.jsonl for machine parsing.

    Args:
        event:    Event code, e.g. "PIPELINE_START", "CHAPTER_DRAFTED"
        detail:   Human-readable context
        data:     Optional dict of key=value pairs
        exc_info: If True, append traceback to the log entry
        **kwargs: Additional key=value pairs merged with data
    """
    try:
        ts = _debug_ts()
        caller = _debug_caller()
        # P0-1: 隐式 event → level 映射（未列出的默认为 INFO）
        level = _EVENT_LEVEL.get(event, "INFO")
        parts = [f"[{ts}] [{level}] [{event}] [{caller}]"]
        if detail:
            parts.append(detail)

        # Merge data dict + kwargs
        merged = {}
        if data:
            merged.update(data)
        if kwargs:
            merged.update(kwargs)

        if merged:
            items = [f"{k}={_safe(v)}" for k, v in merged.items()]
            parts.append(" | " + ", ".join(items))

        line = "".join(parts) + "\n"

        # P2-1: 可选 traceback 追加
        if exc_info:
            tb = traceback.format_exc()
            if tb and tb.strip() != "NoneType: None":
                line += f"  [TRACEBACK]\n{tb}\n"

        # Ensure logs/ directory exists
        DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

        with open(DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()

        # P2-2: 同时写入 JSON Lines 文件（写入失败不阻塞主流程）
        try:
            import json as _json
            _json_line = _json.dumps({
                "ts": datetime.now(timezone.utc).isoformat(),
                "level": level,
                "event": event,
                "location": caller,
                "detail": detail,
                "data": merged,
            }, ensure_ascii=False)
            with open(JSONL_LOG_PATH, "a", encoding="utf-8") as jf:
                jf.write(_json_line + "\n")
                jf.flush()
        except Exception:
            pass

        # Also print to stderr for real-time observation
        try:
            print(f"  [DEBUG] {line.strip()}", file=sys.stderr)
        except (OSError, UnicodeEncodeError):
            pass
    except Exception:
        pass  # 自身不能抛异常


# ============================================================================
# crash_handler — 崩溃捕获器
# ============================================================================

def crash_handler(exc: BaseException = None, context: dict = None) -> None:
    """Capture full crash context and write to debug.log.

    Supports two calling styles:
        crash_handler(exc, {"phase": "foundation"})
        crash_handler({"phase": "foundation"})  # exc from sys.exc_info()

    Args:
        exc:     The exception (if None, uses sys.exc_info())
        context: Optional dict with current phase, chapter, etc.
    """
    try:
        # Auto-detect: if first arg is a dict, treat as context-only call
        if exc is not None and not isinstance(exc, BaseException) and isinstance(exc, dict):
            context = exc
            exc = None

        if exc is None:
            exc = sys.exc_info()[1]

        crash_time = datetime.now(timezone.utc).isoformat()

        lines = []
        lines.append(f"[CRASH] 崩溃时间 (UTC): {crash_time}")

        if exc:
            lines.append(f"[CRASH] 异常类型: {type(exc).__name__}")
            lines.append(f"[CRASH] 异常消息: {str(exc)[:500]}")
            lines.append(f"[CRASH] Traceback:")
            tb_lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
            for tb_line in tb_lines:
                lines.append(f"  {tb_line.rstrip()}")

        if context:
            lines.append(f"[CRASH] 上下文:")
            for k, v in context.items():
                lines.append(f"  {k} = {_safe(v, max_len=500)}")

        # Process memory (psutil, optional)
        try:
            import psutil
            proc = psutil.Process()
            mem = proc.memory_info()
            lines.append(f"[CRASH] 内存: RSS={mem.rss // (1024*1024)}MB, VMS={mem.vms // (1024*1024)}MB")
        except Exception:
            pass

        # Current directory listing
        try:
            cwd = os.getcwd()
            lines.append(f"[CRASH] 工作目录: {cwd}")
            output_dir = os.path.join(cwd, "output")
            if os.path.isdir(output_dir):
                files = sorted(os.listdir(output_dir))[:30]
                lines.append(f"[CRASH] output/ 文件 ({len(files)}): {', '.join(files)}")
        except Exception:
            pass

        # Write to debug.log
        DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        crash_text = "\n".join(lines) + "\n" + ("=" * 60) + "\n"
        with open(DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(crash_text)
            f.flush()

        # Also log as structured event
        debug_log("CRASH", f"{type(exc).__name__ if exc else 'Unknown'}: {str(exc)[:200] if exc else 'N/A'}",
                  data=context)
    except Exception:
        pass  # 自身不能抛异常