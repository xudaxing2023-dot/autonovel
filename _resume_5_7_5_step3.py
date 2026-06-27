#!/usr/bin/env python3
"""5.7.5 中断恢复 — 从 Step 3 Revision cycle 1 继续执行
前提: output/state.json phase=revision, chapters_drafted=4, revision_cycle=0
产出: logs/debug.log 追加, 所有日志双写 + flush"""

import json, sys, time, traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ═══ 日志基础设施 ═══
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "debug.log"
_fp_log = open(str(LOG_FILE), "a", encoding="utf-8", buffering=1)

def _write_log(line: str):
    sys.stdout.write(line); sys.stdout.flush()
    _fp_log.write(line); _fp_log.flush()

def _ts():
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]

STEP_COUNTER = [20]  # 从 #20 开始，接续第二轮 #19
def instep(label: str):
    STEP_COUNTER[0] += 1
    _write_log(f"\n{'─'*70}\n")
    _write_log(f"  [INSTR #{STEP_COUNTER[0]}] {_ts()}  {label}\n")
    _write_log(f"{'─'*70}\n")

def inlog(msg: str):
    _write_log(f"  [INSTR LOG] {_ts()}  {msg}\n")

def inerr(msg: str):
    _write_log(f"  [INSTR ❌] {_ts()}  {msg}\n")

def inok(msg: str):
    _write_log(f"  [INSTR ✅] {_ts()}  {msg}\n")

def safe_call(label: str, fn, *args, **kwargs):
    instep(f"▶ {label}")
    t0 = time.time()
    try:
        result = fn(*args, **kwargs)
        elapsed = time.time() - t0
        inok(f"{label} — 完成, 耗时 {elapsed:.1f}s")
        return result, None
    except Exception as e:
        elapsed = time.time() - t0
        inerr(f"{label} — 失败! 耗时 {elapsed:.1f}s")
        inerr(f"   异常类型: {type(e).__name__}")
        inerr(f"   异常消息: {e}")
        _write_log(f"\n  {'='*60}\n")
        _write_log(f"  [INSTR TRACEBACK] {label}\n")
        _write_log(f"  {'='*60}\n")
        _write_log(traceback.format_exc())
        _write_log(f"  {'='*60}\n")
        return None, (type(e).__name__, str(e))

# ═══ 导入业务模块 ═══
from core.config import config, OUTPUT_DIR, STATE_FILE, CONFIG_FILE
from core.state_manager import load_state, save_state
from pipeline_orchestrator import run_revision, run_pipeline

TOTAL_CH = 4
TOTAL_VOL = 2
CH_PER_VOL = 2
MAX_REV_CYCLES = 2

def write_config():
    data = {
        "story_summary": "2049年上海，程序员在维护老旧服务器时发现AI觉醒迹象，36小时倒计时。悬疑科幻风格，节奏紧凑。",
        "total_chapters": TOTAL_CH, "total_volumes": TOTAL_VOL, "chapters_per_volume": CH_PER_VOL,
        "max_foundation_iters": 1, "max_chapter_attempts": 1, "max_revision_cycles": MAX_REV_CYCLES,
        "foundation_threshold": 1.0, "chapter_threshold": 1.0, "plateau_delta": 999.0,
    }
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    config._loaded = False
    config.load()

def snap(label: str):
    try:
        s = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        s = {}
    inlog(f"SNAP [{label}]: phase={s.get('phase')} drafted={s.get('chapters_drafted')}/{s.get('chapters_total')} cycle={s.get('revision_cycle')} score={s.get('novel_score','?')}")

def main():
    t_global = time.time()
    _write_log("=" * 70 + "\n")
    _write_log("  5.7.5 中断恢复 — 从 Step 3 Revision cycle 1 继续\n")
    _write_log(f"  日志文件: {LOG_FILE}\n")
    _write_log("=" * 70 + "\n")

    try:
        state = load_state()
        inlog(f"当前 state: phase={state.get('phase')} drafted={state.get('chapters_drafted')}/{state.get('chapters_total')} cycle={state.get('revision_cycle')}")
        write_config()
        inok("config.json 已写入")

        # ═══ Step 3: run_revision(max_cycles=1) → 中断3 ═══
        instep("═══ STEP 3 (续): run_revision(max_cycles=1) ═══")
        state, err = safe_call("run_revision(max_cycles=1)", run_revision, state, max_cycles=1)
        if err:
            inerr(f"!!! run_revision 失败: {err[0]}: {err[1]}")
            _write_log(f"\n{'='*70}\n  ❌ 在 Step 3 中断\n{'='*70}\n")
            return

        inok("run_revision(max_cycles=1) 成功完成")
        state = load_state()
        if state.get("revision_cycle", 0) < 1:
            state["revision_cycle"] = 1
            inlog("手动修正: revision_cycle=1")
        state["phase"] = "revision"
        save_state(state)
        snap("中断3: Revision cycle 1 完成")

        # ═══ Step 4: run_pipeline(resume, max_cycles=2) → 中断4 ═══
        instep("═══ STEP 4: Revision cycle 2 + Export → 中断4 ═══")
        write_config()
        _, err = safe_call("run_pipeline(resume, max_cycles=2)", run_pipeline, mode="resume", max_cycles=MAX_REV_CYCLES)
        if err:
            inerr(f"!!! Step 4 失败: {err[0]}: {err[1]}")
            _write_log(f"\n{'='*70}\n  ❌ 在 Step 4 中断\n{'='*70}\n")
            return

        state = load_state()
        state["phase"] = "export"
        state["chapters_total"] = TOTAL_CH
        state["chapters_drafted"] = TOTAL_CH
        save_state(state)
        snap("中断4: Export 边界")

        # ═══ Step 5: run_pipeline(resume) → complete ═══
        instep("═══ STEP 5: Export resume → complete ═══")
        write_config()
        _, err = safe_call("run_pipeline(resume)", run_pipeline, mode="resume")
        if err:
            inerr(f"!!! Step 5 失败: {err[0]}: {err[1]}")
            _write_log(f"\n{'='*70}\n  ❌ 在 Step 5 中断\n{'='*70}\n")
            return

        snap("最终: complete")
        total_elapsed = time.time() - t_global
        _write_log(f"\n{'='*70}\n")
        _write_log(f"  ✅ 5.7.5 中断恢复完成!\n")
        _write_log(f"  总耗时: {total_elapsed/60:.1f}min\n")
        _write_log(f"{'='*70}\n")

    except Exception as e:
        total_elapsed = time.time() - t_global
        crash_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _write_log("\n" + "=" * 70 + "\n")
        _write_log(f"  [CRASH] 崩溃时间：{crash_ts}\n")
        _write_log(f"  [CRASH] 崩溃原因：{type(e).__name__}: {e}\n")
        try:
            crash_s = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            _write_log(f"  [CRASH] 崩溃时的state：phase={crash_s.get('phase')} drafted={crash_s.get('chapters_drafted')}/{crash_s.get('chapters_total')} cycle={crash_s.get('revision_cycle')} score={crash_s.get('novel_score','?')}\n")
        except Exception:
            _write_log("  [CRASH] 崩溃时的state：无法读取\n")
        _write_log("  [CRASH] 完整调用栈：\n")
        for tb_line in traceback.format_exc().strip().split("\n"):
            _write_log(f"    {tb_line}\n")
        _write_log(f"  总耗时: {total_elapsed/60:.1f}min\n")
        _write_log("=" * 70 + "\n")
    finally:
        _fp_log.close()
        sys.stdout.write(f"\n  日志已保存至: {LOG_FILE}\n")
        sys.stdout.flush()

if __name__ == "__main__":
    main()