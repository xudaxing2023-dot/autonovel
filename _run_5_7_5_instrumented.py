#!/usr/bin/env python3
"""5.7.5 多次中断串联 — 全插桩执行脚本
每一步包裹 try/except + 时间戳 + 状态快照，精确定位失败点。
不修改任何业务逻辑源码，仅在测试脚本层插桩。"""

import json, shutil, sys, time, traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ═══════════════════════════════════════════════════════════════
# 文件日志基础设施：同时写终端 + logs/debug.log，每行立即 flush
# ═══════════════════════════════════════════════════════════════
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "debug.log"
_fp_log = open(str(LOG_FILE), "a", encoding="utf-8", buffering=1)  # 行缓冲=每行自动 flush

def _write_log(line: str):
    """双写：终端 + 文件，立刻 flush"""
    sys.stdout.write(line)
    sys.stdout.flush()
    _fp_log.write(line)
    _fp_log.flush()

def _now_ts() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]

from core.config import config, OUTPUT_DIR, CHAPTERS_DIR, CONFIG_FILE, STATE_FILE, RESULTS_FILE
from core.state_manager import default_state, load_state, save_state, parse_score
from pipeline_orchestrator import run_foundation, run_revision, run_drafting, run_export, run_pipeline
from drafting.draft_chapter import draft_chapter
from evaluation.evaluate import evaluate_chapter

TOTAL_CH = 4
TOTAL_VOL = 2
CH_PER_VOL = 2
MAX_REV_CYCLES_CFG = 2
PLATEAU_DELTA = 999.0
STORY_SUMMARY = "2049年上海，程序员在维护老旧服务器时发现AI觉醒迹象，36小时倒计时。悬疑科幻风格，节奏紧凑。"

# ═══════════════════════════════════════════════════════════════
# 插桩工具
# ═══════════════════════════════════════════════════════════════

STEP_COUNTER = [0]
def instep(label: str):
    """插桩步骤标记，记录时间和序号（终端+文件双写）"""
    STEP_COUNTER[0] += 1
    ts = _now_ts()
    _write_log(f"\n{'─'*70}\n")
    _write_log(f"  [INSTR #{STEP_COUNTER[0]}] {ts}  {label}\n")
    _write_log(f"{'─'*70}\n")


def inlog(msg: str):
    """插桩日志行（终端+文件双写）"""
    ts = _now_ts()
    _write_log(f"  [INSTR LOG] {ts}  {msg}\n")


def inerr(msg: str):
    """插桩错误行（终端+文件双写）"""
    ts = _now_ts()
    _write_log(f"  [INSTR ❌] {ts}  {msg}\n")


def inok(msg: str):
    """插桩成功行（终端+文件双写）"""
    ts = _now_ts()
    _write_log(f"  [INSTR ✅] {ts}  {msg}\n")


def snap(step_name: str):
    """打印 state + config 快照（终端+文件双写）"""
    try:
        s = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        s = {}
    try:
        c = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        c = {}
    inlog(f"SNAP [{step_name}]: phase={s.get('phase')} drafted={s.get('chapters_drafted')}/{s.get('chapters_total')} cycle={s.get('revision_cycle')} score={s.get('novel_score','?')}")
    inlog(f"       config: total_ch={c.get('total_chapters')} total_vol={c.get('total_volumes')} ch_per_vol={c.get('chapters_per_volume')} max_rev={c.get('max_revision_cycles')}")


def safe_call(label: str, fn, *args, **kwargs):
    """插桩包裹：调用函数，捕获所有异常，完整回溯写入终端+文件，不终止脚本"""
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
        tb_text = traceback.format_exc()
        _write_log(tb_text)
        _write_log(f"  {'='*60}\n")
        return None, (type(e).__name__, str(e))


def verify_condition(label: str, cond: bool, detail: str = ""):
    """验证条件，不抛异常"""
    if cond:
        inok(f"VERIFY {label}: {detail}")
    else:
        inerr(f"VERIFY {label}: 失败 — {detail}")
    return cond


def file_check(path: Path, label: str, min_size: int = 100):
    """检查文件存在性和大小"""
    exists = path.exists()
    size = path.stat().st_size if exists else 0
    ok = exists and size >= min_size
    detail = f"{size}B" if exists else "MISSING"
    verify_condition(f"FILE {label}", ok, detail)
    return ok


# ═══════════════════════════════════════════════════════════════
# 配置 + 清理
# ═══════════════════════════════════════════════════════════════

def write_config():
    data = {
        "story_summary": STORY_SUMMARY,
        "total_chapters": TOTAL_CH,
        "total_volumes": TOTAL_VOL,
        "chapters_per_volume": CH_PER_VOL,
        "max_foundation_iters": 1,
        "max_chapter_attempts": 1,
        "max_revision_cycles": MAX_REV_CYCLES_CFG,
        "foundation_threshold": 1.0,
        "chapter_threshold": 1.0,
        "plateau_delta": PLATEAU_DELTA,
    }
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    config._loaded = False
    config.load()
    inok(f"config.json 已写入: total_chapters={TOTAL_CH}, total_volumes={TOTAL_VOL}, ch_per_vol={CH_PER_VOL}")


def clean_output():
    """清理 output/ 目录"""
    for sub in ["chapters", "briefs", "edit_logs", "eval_logs"]:
        d = OUTPUT_DIR / sub
        if d.exists():
            shutil.rmtree(d)
    for pat in ["*.md", "*.json", "*.tsv", "*.txt"]:
        for f in OUTPUT_DIR.glob(pat):
            f.unlink()
    STATE_FILE.unlink(missing_ok=True)
    inok("output/ 已清理")


def reinforce_state():
    """加固 state: 确保关键字段存在"""
    try:
        state = load_state()
    except Exception:
        state = {}
    state["chapters_total"] = TOTAL_CH
    state["total_volumes"] = TOTAL_VOL
    state["chapters_per_volume"] = CH_PER_VOL
    if state.get("chapters_drafted") is None:
        state["chapters_drafted"] = 0
    save_state(state)
    return state


# ═══════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════

def main():
    t_global = time.time()

    _write_log("=" * 70 + "\n")
    _write_log("  5.7.5 多次中断串联 — 全插桩执行\n")
    _write_log(f"  配置: {TOTAL_VOL}卷×{CH_PER_VOL}章={TOTAL_CH}章, {MAX_REV_CYCLES_CFG}轮修订\n")
    _write_log(f"  日志文件: {LOG_FILE}\n")
    _write_log(f"  插桩覆盖: 每个 API 调用点 + 状态快照 + 异常完整回溯\n")
    _write_log("=" * 70 + "\n")

    try:
        # ── 初始化 ──
        instep("初始化: 清理 + 配置 + 初始 state")
        clean_output()
        write_config()

        state = default_state()
        state["chapters_total"] = TOTAL_CH
        state["total_volumes"] = TOTAL_VOL
        state["chapters_per_volume"] = CH_PER_VOL
        save_state(state)
        inok("初始 state 已写入")
        snap("初始")

        # ═══════════════════════════════════════════════════════════
        # STEP 1: Foundation → 中断1 (F→D 边界)
        # ═══════════════════════════════════════════════════════════
        instep("═══ STEP 1: Foundation 完整执行 ═══")

        inlog("调用 run_foundation(state) ...")
        t0 = time.time()
        state, err = safe_call("STEP1.run_foundation", run_foundation, state)
        if err:
            inerr("STEP 1 失败，无法继续后续步骤")
            inlog(f">>> 根因: {err[0]}: {err[1]}")
            show_summary(t_global, failed_at="STEP1: run_foundation")
            return

        # 加固 state
        state = reinforce_state()
        state["phase"] = "drafting"
        save_state(state)
        snap("中断1: Foundation 完成")

        # Int1 验证
        s = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        ok = True
        ok &= verify_condition("Int1/phase=drafting", s.get("phase") == "drafting", f"phase={s.get('phase')}")
        ok &= verify_condition("Int1/chapters_drafted=0", s.get("chapters_drafted") == 0, f"drafted={s.get('chapters_drafted')}")
        ok &= verify_condition("Int1/chapters_total=4", s.get("chapters_total") == TOTAL_CH, f"total={s.get('chapters_total')}")
        for fn in ["world.md", "characters.md", "outline.md", "canon.md", "voice.md"]:
            ok &= file_check(OUTPUT_DIR / fn, fn, 100)
        inlog(f"中断1 验证结果: {'全部通过' if ok else '有失败项'}")

        # ═══════════════════════════════════════════════════════════
        # STEP 2: Drafting 卷1 ch_01 + ch_02 → 中断2
        # ═══════════════════════════════════════════════════════════
        instep("═══ STEP 2: Drafting 卷1 (ch_01 + ch_02) ═══")

        state = reinforce_state()

        # ch_01
        instep("STEP2: 起草 ch_01")
        _, err = safe_call("STEP2.draft_chapter(1)", draft_chapter, 1, max_tokens=16000)
        if err:
            inerr(f"ch_01 起草失败: {err}")
            show_summary(t_global, failed_at="STEP2: draft_chapter(1)")
            return
        inlog("ch_01 起草完成，开始评估...")
        eval_result, err = safe_call("STEP2.evaluate_chapter(1)", evaluate_chapter, 1)
        if err:
            inerr(f"ch_01 评估失败: {err}")
        score = parse_score(eval_result, "overall_score") if eval_result else "?"
        inlog(f"ch_01 评分: {score}")
        state = load_state()
        state["chapters_drafted"] = 1
        state["chapters_total"] = TOTAL_CH
        save_state(state)

        # ch_02
        instep("STEP2: 起草 ch_02")
        _, err = safe_call("STEP2.draft_chapter(2)", draft_chapter, 2, max_tokens=16000)
        if err:
            inerr(f"ch_02 起草失败: {err}")
            show_summary(t_global, failed_at="STEP2: draft_chapter(2)")
            return
        inlog("ch_02 起草完成，开始评估...")
        eval_result, err = safe_call("STEP2.evaluate_chapter(2)", evaluate_chapter, 2)
        if err:
            inerr(f"ch_02 评估失败: {err}")
        score = parse_score(eval_result, "overall_score") if eval_result else "?"
        inlog(f"ch_02 评分: {score}")
        state = load_state()
        state["chapters_drafted"] = 2
        state["chapters_total"] = TOTAL_CH
        save_state(state)

        snap("中断2: 卷1完成")

        # Int2 验证
        s = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        ok = True
        ok &= verify_condition("Int2/phase=drafting", s.get("phase") == "drafting", f"phase={s.get('phase')}")
        ok &= verify_condition("Int2/chapters_drafted=2", s.get("chapters_drafted") == 2, f"drafted={s.get('chapters_drafted')}")
        ok &= verify_condition("Int2/chapters_total=4", s.get("chapters_total") == TOTAL_CH, f"total={s.get('chapters_total')}")
        ok &= file_check(CHAPTERS_DIR / "ch_01.md", "ch_01.md", 300)
        ok &= file_check(CHAPTERS_DIR / "ch_02.md", "ch_02.md", 300)
        ch03p = CHAPTERS_DIR / "ch_03.md"
        ok &= verify_condition("Int2/ch_03_NOT_exists", not ch03p.exists(), "OK" if not ch03p.exists() else "残留文件!")
        inlog(f"中断2 验证结果: {'全部通过' if ok else '有失败项'}")

        # ═══════════════════════════════════════════════════════════
        # STEP 3: Drafting 卷2 + Revision cycle 1 → 中断3
        # 这是关键步骤 — 两个 Bug 都在这里触发
        # ═══════════════════════════════════════════════════════════
        instep("═══ STEP 3: Drafting 卷2 (ch_03+ch_04) + Revision cycle 1 ═══")
        inlog("⚠ 此步骤将触发已知 Bug: (1) threshold NameError (2) build_auto_brief sys.exit")

        state = reinforce_state()

        # ch_03
        instep("STEP3: 起草 ch_03")
        _, err = safe_call("STEP3.draft_chapter(3)", draft_chapter, 3, max_tokens=16000)
        if err:
            inerr(f"ch_03 起草失败: {err}")
            show_summary(t_global, failed_at="STEP3: draft_chapter(3)")
            return
        eval_result, err = safe_call("STEP3.evaluate_chapter(3)", evaluate_chapter, 3)
        score = parse_score(eval_result, "overall_score") if eval_result else "?"
        inlog(f"ch_03 评分: {score}")
        state = load_state()
        state["chapters_drafted"] = 3
        state["chapters_total"] = TOTAL_CH
        save_state(state)

        # ch_04
        instep("STEP3: 起草 ch_04")
        _, err = safe_call("STEP3.draft_chapter(4)", draft_chapter, 4, max_tokens=16000)
        if err:
            inerr(f"ch_04 起草失败: {err}")
            show_summary(t_global, failed_at="STEP3: draft_chapter(4)")
            return
        eval_result, err = safe_call("STEP3.evaluate_chapter(4)", evaluate_chapter, 4)
        score = parse_score(eval_result, "overall_score") if eval_result else "?"
        inlog(f"ch_04 评分: {score}")
        state = load_state()
        state["chapters_drafted"] = 4
        state["chapters_total"] = TOTAL_CH
        state["phase"] = "revision"
        state["revision_cycle"] = 0
        state["total_volumes"] = TOTAL_VOL
        state["chapters_per_volume"] = CH_PER_VOL
        save_state(state)
        snap("Revision 前")

        # ★ 再次写入 config，确保不被覆盖
        write_config()

        # ══ 执行 Revision cycle 1 — 这是两个 Bug 的触发点 ══
        instep("STEP3: run_revision(max_cycles=1) — ⚠ Bug 触发区域")
        inlog("  Bug 1 (gen_brief.py:749 sys.exit) 触发条件: evaluate_full 返回 None → latest_full_eval()=None → sys.exit")
        inlog("  Bug 2 (pipeline_orchestrator.py:682 threshold NameError) 触发条件: run_revision 未定义 threshold 变量")

        t0 = time.time()
        state, err = safe_call("STEP3.run_revision(max_cycles=1)", run_revision, state, max_cycles=1)

        if err:
            err_type, err_msg = err
            inerr(f"!!! run_revision 在 cycle 1 中失败 !!!")
            inerr(f"    异常类型: {err_type}")
            inerr(f"    异常消息: {err_msg}")

            if err_type == "NameError" and "threshold" in err_msg:
                inerr(">>> 确认: Bug 2 — threshold 变量未在 run_revision 中定义")
                inerr("    位置: pipeline_orchestrator.py line 682")
                inerr("    调用链: run_revision → _sample_evaluate_volumes(total, ch_per_vol, total_vol, threshold)")
                inerr("    修复: 在 run_revision 函数开头 (line 438-439 附近) 添加:")
                inerr('        threshold = cfg.chapter_threshold if cfg.loaded else CHAPTER_THRESHOLD')
            elif err_type == "SystemExit":
                inerr(">>> 确认: Bug 1 — sys.exit() 在 build_auto_brief() 中被调用")
                inerr("    位置: revision/gen_brief.py line 749")
                inerr("    调用链: run_revision → build_auto_brief() → latest_full_eval()=None → sys.exit()")
                inerr("    修复: 将 sys.exit() 改为 raise FileNotFoundError()")
            else:
                inerr(f">>> 未知异常，查看上方 traceback 定位")

            show_summary(t_global, failed_at=f"STEP3: run_revision — {err_type}")
            return

        # run_revision 成功返回
        inok("run_revision(max_cycles=1) 成功完成")
        state = reinforce_state()
        if state.get("revision_cycle", 0) < 1:
            state["revision_cycle"] = 1
            inlog("手动修正: revision_cycle=1")
        state["phase"] = "revision"
        save_state(state)
        snap("中断3: Revision cycle 1 完成")

        # Int3 验证
        s = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        ok = True
        ok &= verify_condition("Int3/phase=revision", s.get("phase") == "revision", f"phase={s.get('phase')}")
        ok &= verify_condition("Int3/revision_cycle>=1", s.get("revision_cycle", 0) >= 1, f"cycle={s.get('revision_cycle')}")
        ok &= verify_condition("Int3/chapters_drafted=4", s.get("chapters_drafted") == TOTAL_CH, f"drafted={s.get('chapters_drafted')}")
        inlog(f"中断3 验证结果: {'全部通过' if ok else '有失败项'}")

        # ═══════════════════════════════════════════════════════════
        # STEP 4: Revision cycle 2 + Export → 中断4
        # ═══════════════════════════════════════════════════════════
        instep("═══ STEP 4: Revision cycle 2 + Export → 中断4 ═══")

        state = reinforce_state()
        write_config()

        instep("STEP4: run_pipeline(resume, max_cycles=2)")
        inlog("  这将从 revision phase 恢复，执行 cycle 2 + export")
        inlog("  ⚠ 如果 Bug 2 未触发 cycle 1（因异常被捕获），cycle 2 可能再次触发")
        t0 = time.time()
        _, err = safe_call("STEP4.run_pipeline(resume)", run_pipeline, mode="resume", max_cycles=MAX_REV_CYCLES_CFG)

        if err:
            err_type, err_msg = err
            inerr(f"!!! run_pipeline(resume) 失败 !!!")
            inerr(f"    异常类型: {err_type}")
            inerr(f"    异常消息: {err_msg}")
            show_summary(t_global, failed_at=f"STEP4: run_pipeline — {err_type}")
            return

        # 回滚 phase 模拟中断4
        state = load_state()
        state["phase"] = "export"
        state["chapters_total"] = TOTAL_CH
        state["chapters_drafted"] = TOTAL_CH
        save_state(state)
        snap("中断4: Export 边界")

        # Int4 验证
        s = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        ok = True
        ok &= verify_condition("Int4/phase=export", s.get("phase") == "export", f"phase={s.get('phase')}")
        ok &= verify_condition("Int4/revision_cycle>=2", s.get("revision_cycle", 0) >= 2, f"cycle={s.get('revision_cycle')}")
        ok &= verify_condition("Int4/chapters_drafted=4", s.get("chapters_drafted") == TOTAL_CH, f"drafted={s.get('chapters_drafted')}")
        inlog(f"中断4 验证结果: {'全部通过' if ok else '有失败项'}")

        # ═══════════════════════════════════════════════════════════
        # STEP 5: Export resume → complete
        # ═══════════════════════════════════════════════════════════
        instep("═══ STEP 5: Export resume → complete ═══")

        state = reinforce_state()
        write_config()

        _, err = safe_call("STEP5.run_pipeline(resume)", run_pipeline, mode="resume")
        if err:
            err_type, err_msg = err
            inerr(f"!!! STEP 5 失败: {err_type}: {err_msg}")
            show_summary(t_global, failed_at=f"STEP5: run_pipeline(export) — {err_type}")
            return

        snap("最终: complete")

        # Final 验证
        s = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        all_ok = True
        all_ok &= verify_condition("Final/phase=complete", s.get("phase") == "complete", f"phase={s.get('phase')}")
        all_ok &= verify_condition("Final/chapters_drafted=4", s.get("chapters_drafted") == TOTAL_CH, f"drafted={s.get('chapters_drafted')}")
        all_ok &= verify_condition("Final/revision_cycle>=2", s.get("revision_cycle", 0) >= 2, f"cycle={s.get('revision_cycle')}")
        for ch in range(1, 5):
            all_ok &= file_check(CHAPTERS_DIR / f"ch_{ch:02d}.md", f"ch_{ch:02d}.md", 300)
        all_ok &= file_check(OUTPUT_DIR / "manuscript.md", "manuscript.md", 100)
        all_ok &= file_check(OUTPUT_DIR / "arc_summary.md", "arc_summary.md", 100)

        show_summary(t_global, success=all_ok)

    except Exception as e:
        # ── 顶层崩溃捕获：记录到文件 + 终端 ──
        total_elapsed = time.time() - t_global
        exc_type = type(e).__name__
        exc_msg = str(e)
        crash_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        _write_log("\n" + "=" * 70 + "\n")
        _write_log(f"  [CRASH] 崩溃时间：{crash_ts}\n")
        _write_log(f"  [CRASH] 崩溃原因：{exc_type}: {exc_msg}\n")
        _write_log("=" * 70 + "\n")

        # 崩溃时的 state
        try:
            crash_s = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            _write_log(f"  [CRASH] 崩溃时的state：phase={crash_s.get('phase')} drafted={crash_s.get('chapters_drafted')}/{crash_s.get('chapters_total')} cycle={crash_s.get('revision_cycle')} score={crash_s.get('novel_score','?')}\n")
        except Exception:
            _write_log("  [CRASH] 崩溃时的state：无法读取 state.json\n")

        # 完整 traceback
        _write_log("  [CRASH] 完整调用栈：\n")
        tb_text = traceback.format_exc()
        for tb_line in tb_text.strip().split("\n"):
            _write_log(f"    {tb_line}\n")

        _write_log(f"\n  总耗时: {total_elapsed/60:.1f}min\n")
        _write_log("=" * 70 + "\n")

    finally:
        _fp_log.close()
        sys.stdout.write(f"\n  日志已保存至: {LOG_FILE}\n")
        sys.stdout.flush()


def show_summary(t_global: float, failed_at: str = None, success: bool = None):
    """打印汇总（终端+文件双写）"""
    total_elapsed = time.time() - t_global
    _write_log(f"\n{'='*70}\n")
    if success:
        _write_log(f"  ✅ 5.7.5 全插桩执行完成 — 全部通过!\n")
    elif failed_at:
        _write_log(f"  ❌ 5.7.5 在 [{failed_at}] 处失败\n")
    else:
        _write_log(f"  ⚠ 5.7.5 执行结束（状态不明）\n")
    _write_log(f"  总耗时: {total_elapsed/60:.1f}min\n")
    _write_log(f"{'='*70}\n")


if __name__ == "__main__":
    main()