#!/usr/bin/env python3
"""5.7.6 Export 中断→resume — 全流程插桩执行脚本
复用 5.7.5 的 4 章现存产物，phase 回退 → Export resume。
仅 2 次 API 调用（build_outline + build_arc_summary）。
不修改任何业务逻辑源码，仅在测试脚本层插桩。"""

import json, sys, time, traceback
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


from core.config import config, OUTPUT_DIR, CHAPTERS_DIR, CONFIG_FILE, STATE_FILE
from core.state_manager import default_state, load_state, save_state
from pipeline_orchestrator import run_export, run_pipeline

# ═══════════════════════════════════════════════════════════════
# 插桩工具（完全复用 5.7.5 模板）
# ═══════════════════════════════════════════════════════════════

STEP_COUNTER = [0]


def instep(label: str):
    """插桩步骤标记，记录时间和序号（终端+文件双写）"""
    STEP_COUNTER[0] += 1
    ts = _now_ts()
    _write_log(f"\n{'─' * 70}\n")
    _write_log(f"  [INSTR #{STEP_COUNTER[0]}] {ts}  {label}\n")
    _write_log(f"{'─' * 70}\n")


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
    inlog(f"SNAP [{step_name}]: phase={s.get('phase')} drafted={s.get('chapters_drafted')}/{s.get('chapters_total')} cycle={s.get('revision_cycle')} score={s.get('novel_score', '?')}")
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
        _write_log(f"\n  {'=' * 60}\n")
        _write_log(f"  [INSTR TRACEBACK] {label}\n")
        _write_log(f"  {'=' * 60}\n")
        tb_text = traceback.format_exc()
        _write_log(tb_text)
        _write_log(f"  {'=' * 60}\n")
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
# 主流程
# ═══════════════════════════════════════════════════════════════

def main():
    t_global = time.time()

    _write_log("=" * 70 + "\n")
    _write_log("  5.7.6 Export 中断→resume — 全插桩执行\n")
    _write_log(f"  策略: 复用 5.7.5 的 4 章现存产物，phase 回退 → Export resume\n")
    _write_log(f"  API 调用: 仅 2 次（build_outline + build_arc_summary）\n")
    _write_log(f"  日志文件: {LOG_FILE}\n")
    _write_log(f"  插桩覆盖: Export 3 子步骤 + 状态快照 + 异常完整回溯\n")
    _write_log("=" * 70 + "\n")

    try:
        # ═══════════════════════════════════════════════════════════
        # Phase A: 验证现有产物
        # ═══════════════════════════════════════════════════════════
        instep("Phase A: 验证现有产物（来自 5.7.5）")

        state = load_state()
        inlog(f"当前 state: phase={state.get('phase')}, drafted={state.get('chapters_drafted')}/{state.get('chapters_total')}, "
              f"cycle={state.get('revision_cycle')}, score={state.get('novel_score', '?')}")

        all_ok = True
        all_ok &= verify_condition("Pre/phase=complete",
                                   state.get("phase") == "complete",
                                   f"phase={state.get('phase')}")
        all_ok &= verify_condition("Pre/chapters_drafted=4",
                                   state.get("chapters_drafted") == 4,
                                   f"drafted={state.get('chapters_drafted')}")
        all_ok &= verify_condition("Pre/chapters_total=4",
                                   state.get("chapters_total") == 4,
                                   f"total={state.get('chapters_total')}")
        all_ok &= verify_condition("Pre/revision_cycle>=2",
                                   state.get("revision_cycle", 0) >= 2,
                                   f"cycle={state.get('revision_cycle')}")

        # 检查章节文件
        for ch in range(1, 5):
            all_ok &= file_check(CHAPTERS_DIR / f"ch_{ch:02d}.md", f"ch_{ch:02d}.md", 300)

        if not all_ok:
            inerr("前置条件不满足，终止脚本（请先确保 5.7.5 已成功运行）")
            show_summary(t_global, failed_at="Phase A: 前置验证")
            return

        inok("前置条件全部通过，4 章完整可用")

        # ═══════════════════════════════════════════════════════════
        # Phase B: phase 回退 → export，删除旧的 Export 产物
        # ═══════════════════════════════════════════════════════════
        instep("Phase B: phase 回退 complete→export + 清理旧 Export 产物")

        # 删除旧的 Export 产物（确保验证的是本次运行的真实输出）
        old_ms = OUTPUT_DIR / "manuscript.md"
        old_arc = OUTPUT_DIR / "arc_summary.md"
        cleaned = []
        for p, name in [(old_ms, "manuscript.md"), (old_arc, "arc_summary.md")]:
            if p.exists():
                p.unlink()
                cleaned.append(name)
        inlog(f"已清理旧 Export 产物: {', '.join(cleaned) if cleaned else '（无）'}")

        # phase 回退
        old_phase = state.get("phase")
        state["phase"] = "export"
        save_state(state)
        inlog(f"phase 回退: {old_phase} → export")
        snap("phase 回退后")

        # 验证回退结果
        s = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        verify_condition("Rollback/phase=export",
                         s.get("phase") == "export",
                         f"phase={s.get('phase')}")
        verify_condition("Rollback/chapters_intact",
                         s.get("chapters_drafted") == 4,
                         f"drafted={s.get('chapters_drafted')}")

        # ═══════════════════════════════════════════════════════════
        # Phase C: Export resume (包含 build_outline → build_arc_summary → build_manuscript)
        # ═══════════════════════════════════════════════════════════
        instep("Phase C: Export resume — 3 子步骤插桩")

        inlog("Export 子步骤 1/3: build_outline → 从章节重建大纲 (API 调用)")
        inlog("  → 调用 call_writer，max_tokens=8192")
        inlog("  → 输出: output/outline.md")

        inlog("Export 子步骤 2/3: build_arc_summary → 构建弧线摘要 (API 调用)")
        inlog("  → 调用 call_writer，max_tokens=8192")
        inlog("  → 输出: output/arc_summary.md")

        inlog("Export 子步骤 3/3: build_manuscript → 拼接完整手稿 (纯 I/O，零 API)")
        inlog("  → 拼接 ch_01~ch_04 → output/manuscript.md")

        t0 = time.time()
        _, err = safe_call("Export.resume", run_pipeline, mode="resume")

        if err:
            err_type, err_msg = err
            inerr(f"!!! Export resume 失败 !!!")
            inerr(f"    异常类型: {err_type}")
            inerr(f"    异常消息: {err_msg}")

            # 分析败在哪个子步骤
            s_after = load_state()
            ms_exists = (OUTPUT_DIR / "manuscript.md").exists()
            arc_exists = (OUTPUT_DIR / "arc_summary.md").exists()
            outline_new = (OUTPUT_DIR / "outline.md").exists()

            inlog(f"失败后 state: phase={s_after.get('phase')}")
            inlog(f"失败后产物: manuscript={'✅' if ms_exists else '❌'} "
                  f"arc_summary={'✅' if arc_exists else '❌'} "
                  f"outline={'✅' if outline_new else '❌'}")

            if not outline_new:
                inerr(">>> 推测: 败在 build_outline（子步骤 1/3）")
            elif not arc_exists:
                inerr(">>> 推测: 败在 build_arc_summary（子步骤 2/3）")
            elif not ms_exists:
                inerr(">>> 推测: 败在 build_manuscript（子步骤 3/3）")

            show_summary(t_global, failed_at=f"Phase C: Export resume — {err_type}")
            return

        inok("Export resume 成功完成")
        snap("Export 完成后")

        # ═══════════════════════════════════════════════════════════
        # Phase D: 最终验证
        # ═══════════════════════════════════════════════════════════
        instep("Phase D: 最终验证")

        final = load_state()
        all_ok = True

        # V1: phase=complete
        all_ok &= verify_condition("Final/phase=complete",
                                   final.get("phase") == "complete",
                                   f"phase={final.get('phase')}")

        # V2: manuscript.md 存在且非空
        ms = OUTPUT_DIR / "manuscript.md"
        ms_ok = file_check(ms, "manuscript.md", 200)
        all_ok &= ms_ok
        if ms.exists():
            ms_text = ms.read_text(encoding="utf-8")
            ms_size = len(ms_text)
            inlog(f"manuscript.md: {ms_size} 字符")

            # V2-extended: 合并了全部 4 章
            has_all = all(f"ch_{ch:02d}" in ms_text or f"第 {ch} 章" in ms_text or f"第{ch}章" in ms_text
                          for ch in range(1, 5))
            all_ok &= verify_condition("Final/manuscript_merge_4_chapters",
                                       has_all,
                                       "all 4 chapters merged" if has_all else "INCOMPLETE")

            # 含目录
            has_toc = "目录" in ms_text or "# 目录" in ms_text
            verify_condition("Final/manuscript_has_toc",
                             has_toc,
                             "TOC present" if has_toc else "NO TOC")

        # V3: arc_summary.md 存在
        arc = OUTPUT_DIR / "arc_summary.md"
        arc_ok = file_check(arc, "arc_summary.md", 200)
        all_ok &= arc_ok
        if arc.exists():
            arc_text = arc.read_text(encoding="utf-8")
            inlog(f"arc_summary.md: {len(arc_text)} 字符")

            # arc_summary 含关键段落
            has_sections = all(kw in arc_text for kw in ["角色弧线", "情节弧线", "主题弧线"])
            verify_condition("Final/arc_summary_complete",
                             has_sections,
                             "all sections present" if has_sections else "MISSING sections")

        # 章节完整性不变
        for ch in range(1, 5):
            all_ok &= file_check(CHAPTERS_DIR / f"ch_{ch:02d}.md", f"ch_{ch:02d}.md", 300)

        # state 一致性
        all_ok &= verify_condition("Final/chapters_drafted=4",
                                   final.get("chapters_drafted") == 4,
                                   f"drafted={final.get('chapters_drafted')}")

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
            _write_log(f"  [CRASH] 崩溃时的state：phase={crash_s.get('phase')} drafted={crash_s.get('chapters_drafted')}/{crash_s.get('chapters_total')} cycle={crash_s.get('revision_cycle')} score={crash_s.get('novel_score', '?')}\n")
        except Exception:
            _write_log("  [CRASH] 崩溃时的state：无法读取 state.json\n")

        # 完整 traceback
        _write_log("  [CRASH] 完整调用栈：\n")
        tb_text = traceback.format_exc()
        for tb_line in tb_text.strip().split("\n"):
            _write_log(f"    {tb_line}\n")

        _write_log(f"\n  总耗时: {total_elapsed / 60:.1f}min\n")
        _write_log("=" * 70 + "\n")

    finally:
        _fp_log.close()
        sys.stdout.write(f"\n  日志已保存至: {LOG_FILE}\n")
        sys.stdout.flush()


def show_summary(t_global: float, failed_at: str = None, success: bool = None):
    """打印汇总（终端+文件双写）"""
    total_elapsed = time.time() - t_global
    _write_log(f"\n{'=' * 70}\n")
    if success:
        _write_log(f"  ✅ 5.7.6 全插桩执行完成 — 全部通过!\n")
    elif failed_at:
        _write_log(f"  ❌ 5.7.6 在 [{failed_at}] 处失败\n")
    else:
        _write_log(f"  ⚠ 5.7.6 执行结束（状态不明）\n")
    _write_log(f"  总耗时: {total_elapsed / 60:.1f}min\n")
    _write_log(f"  API 调用: 最多 2 次（build_outline + build_arc_summary）\n")
    _write_log(f"{'=' * 70}\n")


if __name__ == "__main__":
    main()