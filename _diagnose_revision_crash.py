#!/usr/bin/env python3
"""精准诊断：从当前 state.json 恢复，直接调用 run_revision(max_cycles=1) 并捕获确切异常。
所有日志同步写入 logs/debug.log，每行立刻 flush。"""

import json, sys, time, traceback, os
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ═══════════════════════════════════════════════════════════════
# 日志基础设施：同时写终端 + 文件，每行立即 flush
# ═══════════════════════════════════════════════════════════════

LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "debug.log"
_fp_log = open(str(LOG_FILE), "a", encoding="utf-8", buffering=1)  # 行缓冲

def ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

def log(msg: str):
    """写终端 + 文件，立刻 flush"""
    line = f"  [{ts()}] {msg}\n"
    sys.stdout.write(line)
    sys.stdout.flush()
    _fp_log.write(line)
    _fp_log.flush()

def sepline(char: str = "─", width: int = 60):
    line = char * width + "\n"
    sys.stdout.write(f"\n{line}")
    sys.stdout.flush()
    _fp_log.write(f"\n{line}")
    _fp_log.flush()

# ═══════════════════════════════════════════════════════════════
# 主逻辑
# ═══════════════════════════════════════════════════════════════

def main():
    t_start = datetime.now()
    log(f"========== 诊断脚本启动 ==========")
    log(f"日志文件: {LOG_FILE}")

    try:
        from core.config import config, OUTPUT_DIR, STATE_FILE, CONFIG_FILE
        from core.state_manager import load_state, save_state
        from pipeline_orchestrator import run_revision

        # ── 加载当前状态 ──
        s = load_state()
        log(f"加载 state: phase={s.get('phase')} drafted={s.get('chapters_drafted')}/{s.get('chapters_total')} cycle={s.get('revision_cycle')} score={s.get('novel_score')}")

        # 确保 state 正确
        s["chapters_total"] = 4
        s["chapters_drafted"] = 4
        s["total_volumes"] = 2
        s["chapters_per_volume"] = 2
        s["phase"] = "revision"
        s["revision_cycle"] = 0
        save_state(s)
        log("state 已加固")

        # 确保 config 正确
        config_data = {
            "story_summary": "2049年上海，程序员在维护老旧服务器时发现AI觉醒迹象，36小时倒计时。悬疑科幻风格，节奏紧凑。",
            "total_chapters": 4, "total_volumes": 2, "chapters_per_volume": 2,
            "max_foundation_iters": 1, "max_chapter_attempts": 1, "max_revision_cycles": 2,
            "foundation_threshold": 1.0, "chapter_threshold": 1.0, "plateau_delta": 999.0,
        }
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=2, ensure_ascii=False)
        config._loaded = False
        config.load()
        log("config 已刷新")

        # ── 直接调用 run_revision ──
        sepline("=")
        log("开始 run_revision(max_cycles=1)")
        sepline("=")

        t0 = time.time()
        result = run_revision(s, max_cycles=1)
        elapsed = time.time() - t0
        log(f"✅ run_revision 成功完成! 耗时 {elapsed:.1f}s")
        log(f"   phase={result.get('phase')} cycle={result.get('revision_cycle')} score={result.get('novel_score')}")
        save_state(result)

        total_elapsed = (datetime.now() - t_start).total_seconds()
        log(f"========== 诊断脚本正常结束, 总耗时 {total_elapsed:.1f}s ==========")

    except Exception as e:
        elapsed = (datetime.now() - t_start).total_seconds()
        exc_type = type(e).__name__
        exc_msg = str(e)

        sepline("=")
        log(f"❌ CRASH 在 {elapsed:.1f}s 后")
        log(f"   异常类型: {exc_type}")
        log(f"   异常消息: {exc_msg}")
        sepline("=")

        # 捕获完整的 traceback
        tb_lines = traceback.format_exc().strip().split("\n")
        for line in tb_lines:
            log(f"   TRACE: {line}")

        # 读取最后已知的 state
        try:
            s = load_state()
            log(f"   崩溃时 state: phase={s.get('phase')} drafted={s.get('chapters_drafted')}/{s.get('chapters_total')} cycle={s.get('revision_cycle')} score={s.get('novel_score')}")
        except Exception:
            log(f"   崩溃时 state: 无法读取")

        # 根因判定
        sepline("=")
        if exc_type == "NameError" and "threshold" in exc_msg:
            log(">>> 【Bug 2】 threshold 变量未定义")
            log("    位置: pipeline_orchestrator.py line 682 (_sample_evaluate_volumes 调用)")
        elif exc_type == "SystemExit":
            log(">>> 【Bug 1】 sys.exit() 被调用")
            log("    位置: revision/gen_brief.py build_auto_brief()")
        elif exc_type == "FileNotFoundError" and "eval_logs" in exc_msg:
            log(">>> 【Bug 1 修复后触发】 latest_full_eval()=None → raise FileNotFoundError")
            log("    run_revision 的 except Exception 兜底应捕获此异常")
        else:
            log(f">>> 未知异常: {exc_type}")
        sepline("=")

        log(f"========== 诊断脚本因异常终止, 耗时 {elapsed:.1f}s ==========")

    finally:
        _fp_log.close()


if __name__ == "__main__":
    main()