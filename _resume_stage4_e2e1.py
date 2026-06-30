#!/usr/bin/env python3
"""从当前 state 恢复执行 — Stage 4 E2E-1 中断恢复脚本

当前 state: phase=revision, drafted=3/3, revision_cycle=0
→ 将自动执行 Revision → Export 阶段
→ 复用 _run_stage4_e2e1.py 的双写日志 + 插桩机制
"""

import json
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ═══════════════════════════════════════════════════════════════
# 双写日志基础设施
# ═══════════════════════════════════════════════════════════════
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "debug.log"
_fp_log = open(str(LOG_FILE), "a", encoding="utf-8", buffering=1)


def _write_log(line: str):
    sys.stdout.write(line)
    sys.stdout.flush()
    _fp_log.write(line)
    _fp_log.flush()


def _now_ts() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def log(msg: str):
    _write_log(f"  [RESUME LOG] {_now_ts()}  {msg}\n")


def ok(msg: str):
    _write_log(f"  [RESUME ✅] {_now_ts()}  {msg}\n")


def err(msg: str):
    _write_log(f"  [RESUME ❌] {_now_ts()}  {msg}\n")


from core.config import config, STATE_FILE
from core.state_manager import load_state, save_state
from pipeline_orchestrator import run_pipeline


def main():
    t_start = time.time()

    _write_log(f"\n{'=' * 70}\n")
    _write_log(f"  Stage 4 E2E-1 中断恢复 — 从 phase=revision 继续\n")
    _write_log(f"  启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    _write_log(f"{'=' * 70}\n")

    # 验证当前 state
    state = load_state()
    log(f"当前 state: phase={state.get('phase')}, "
        f"drafted={state.get('chapters_drafted')}/{state.get('chapters_total')}, "
        f"cycle={state.get('revision_cycle')}, score={state.get('novel_score')}")

    if state.get("phase") == "complete":
        ok("流水线已完成，无需恢复")
        _fp_log.close()
        return

    log("开始执行 run_pipeline('resume') ...")
    log("预期流程: Revision (最多 3 循环 + 审阅修订) → Export (build_outline + arc_summary + manuscript)")

    try:
        run_pipeline("resume")
        elapsed = time.time() - t_start
        ok(f"run_pipeline('resume') 完成! 耗时 {elapsed / 60:.1f}min")

        # 验证最终状态
        final_state = load_state()
        ok(f"最终 phase={final_state.get('phase')}, score={final_state.get('novel_score')}")

    except KeyboardInterrupt:
        elapsed = time.time() - t_start
        _write_log(f"\n  [RESUME ⚠] {_now_ts()}  用户中断 — 状态已保存\n")
        _write_log(f"  已运行: {elapsed / 60:.1f}min\n")
        sys.exit(130)

    except Exception as e:
        elapsed = time.time() - t_start
        err(f"恢复执行失败! 耗时 {elapsed / 60:.1f}min")
        err(f"异常类型: {type(e).__name__}")
        err(f"异常消息: {e}")
        _write_log(f"\n  {'=' * 60}\n")
        _write_log(f"  [RESUME TRACEBACK]\n")
        _write_log(f"  {'=' * 60}\n")
        _write_log(traceback.format_exc())
        _write_log(f"  {'=' * 60}\n")

        # 保存崩溃时的 state
        try:
            crash_s = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            _write_log(
                f"  [CRASH] 崩溃时的 state: phase={crash_s.get('phase')} "
                f"drafted={crash_s.get('chapters_drafted')}/{crash_s.get('chapters_total')} "
                f"cycle={crash_s.get('revision_cycle')} "
                f"score={crash_s.get('novel_score', '?')}\n"
            )
        except Exception:
            pass

        sys.exit(1)

    finally:
        _fp_log.close()
        sys.stdout.write(f"\n  日志已保存至: {LOG_FILE}\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()