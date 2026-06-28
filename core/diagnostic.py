#!/usr/bin/env python3
"""Business source instrumentation - minimal, zero-dependency.

Writes one line per event to logs/diagnostic.log.
Auto-clears the log on first write of each run.
"""
import sys
import traceback
from datetime import datetime
from pathlib import Path

LOG_PATH = Path(__file__).parent.parent / "logs" / "diagnostic.log"
_CLEARED = False


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
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line)
        f.flush()
    print(f"  [DIAG] {line.strip()}", file=sys.stderr)