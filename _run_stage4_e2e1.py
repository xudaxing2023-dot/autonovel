#!/usr/bin/env python3
"""Stage 4 E2E-1: 3章正常阈值 from_scratch — 全流程插桩执行脚本

与 5.7.5 的本质差异：
- 使用正常质量阈值（foundation_threshold=7.5, chapter_threshold=6.0, plateau_delta=0.3）
  而非极低阈值 1.0，专门验证 5.7.x 跳过的质量重试循环
- 单步全流水线：run_pipeline("from_scratch") 一口气跑完 Phase 1→2→3→4
- 无中断/recovery — 纯 from_scratch 从头跑到尾

插桩策略：
- 复用 5.7.5 的日志双写基础设施（终端 + logs/debug.log，每行 flush）
- monkey-patch pipeline_orchestrator.step / banner，截获所有运行时输出
- 顶层 try/except 捕获崩溃，[CRASH] 格式写入 state + traceback

不修改任何业务逻辑源码，仅在测试脚本层插桩。
"""

import json
import shutil
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ═══════════════════════════════════════════════════════════════
# 文件日志基础设施：同时写终端 + logs/debug.log，每行立即 flush
# （需求1: 双写文件 / 需求2: 每行 flush / 需求4: 自动创建 logs/）
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
from core.state_manager import default_state, load_state, save_state
from pipeline_orchestrator import run_pipeline

# ═══════════════════════════════════════════════════════════════
# E2E-1 配置 — 正常质量阈值（与 5.7.x 的核心差异）
# ═══════════════════════════════════════════════════════════════
TOTAL_CH = 3
TOTAL_VOL = 1
CH_PER_VOL = 3
MAX_FOUNDATION_ITERS = 3
MAX_CHAPTER_ATTEMPTS = 3
MAX_REV_CYCLES = 3
FOUNDATION_THRESHOLD = 7.5       # ★ 正常值，可能触发重试
CHAPTER_THRESHOLD = 6.0          # ★ 正常值，可能触发重试
PLATEAU_DELTA = 0.3              # ★ 正常值，可能触发平台期停止
STORY_SUMMARY = "2049年上海，程序员在维护老旧服务器时发现AI觉醒迹象，36小时倒计时。悬疑科幻风格，节奏紧凑。"

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
    inlog(
        f"SNAP [{step_name}]: phase={s.get('phase')} "
        f"drafted={s.get('chapters_drafted')}/{s.get('chapters_total')} "
        f"cycle={s.get('revision_cycle')} score={s.get('novel_score', '?')}"
    )
    inlog(
        f"       config: total_ch={c.get('total_chapters')} "
        f"total_vol={c.get('total_volumes')} ch_per_vol={c.get('chapters_per_volume')} "
        f"f_threshold={c.get('foundation_threshold')} ch_threshold={c.get('chapter_threshold')} "
        f"max_rev={c.get('max_revision_cycles')}"
    )


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
# E2E-1 专用：monkey-patch pipeline_orchestrator 的 step/banner
# 目的：截获流水线运行时所有输出，双写到日志文件
# 不修改 pipeline_orchestrator.py 源码
# ═══════════════════════════════════════════════════════════════

_original_step = None
_original_banner = None


def _patch_pipeline_logging():
    """Monkey-patch pipeline_orchestrator.step / banner。
    使流水线的每一行输出都通过 _write_log 双写到终端+debug.log。
    """
    global _original_step, _original_banner
    import pipeline_orchestrator as po

    _original_step = po.step
    _original_banner = po.banner

    def _instrumented_step(msg: str):
        """拦截 step()，先写日志再执行原函数"""
        _write_log(f"  [PIPELINE] {msg}\n")
        _original_step(msg)

    def _instrumented_banner(msg: str, char: str = "="):
        """拦截 banner()，记录横幅到日志"""
        _write_log(f"\n  [PIPELINE BANNER] {msg}\n")
        _original_banner(msg, char)

    po.step = _instrumented_step
    po.banner = _instrumented_banner
    inok("pipeline_orchestrator.step / banner 已挂载插桩")


def _restore_pipeline_logging():
    """恢复原始的 step / banner 函数"""
    global _original_step, _original_banner
    import pipeline_orchestrator as po

    if _original_step is not None:
        po.step = _original_step
    if _original_banner is not None:
        po.banner = _original_banner


# ═══════════════════════════════════════════════════════════════
# 配置 + 清理
# ═══════════════════════════════════════════════════════════════

def write_e2e1_config():
    """写入 E2E-1 正常阈值配置到 config.json"""
    data = {
        "story_summary": STORY_SUMMARY,
        "total_chapters": TOTAL_CH,
        "total_volumes": TOTAL_VOL,
        "chapters_per_volume": CH_PER_VOL,
        "foundation_threshold": FOUNDATION_THRESHOLD,
        "chapter_threshold": CHAPTER_THRESHOLD,
        "max_foundation_iters": MAX_FOUNDATION_ITERS,
        "max_chapter_attempts": MAX_CHAPTER_ATTEMPTS,
        "max_revision_cycles": MAX_REV_CYCLES,
        "plateau_delta": PLATEAU_DELTA,
    }
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    config._loaded = False
    config.load()
    inok(
        f"config.json 已写入: "
        f"total_chapters={TOTAL_CH}, "
        f"foundation_threshold={FOUNDATION_THRESHOLD}, "
        f"chapter_threshold={CHAPTER_THRESHOLD}, "
        f"plateau_delta={PLATEAU_DELTA}"
    )


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


# ═══════════════════════════════════════════════════════════════
# _parse_results_tsv — 解析 results.tsv 辅助函数
# ═══════════════════════════════════════════════════════════════

def _parse_results_tsv():
    """解析 results.tsv，返回 [(commit_hash, stage, score, word_count, decision, notes), ...]"""
    if not RESULTS_FILE.exists():
        return []
    rows = []
    with open(RESULTS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 6:
                rows.append(tuple(parts[:6]))
    return rows


# ═══════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════

def main():
    t_global = time.time()

    # ── 头部 ──
    _write_log("=" * 70 + "\n")
    _write_log("  Stage 4 E2E-1: 3章正常阈值 from_scratch — 全插桩执行\n")
    _write_log(f"  配置: total_chapters={TOTAL_CH}, total_volumes={TOTAL_VOL}\n")
    _write_log(f"  质量阈值: foundation={FOUNDATION_THRESHOLD}, chapter={CHAPTER_THRESHOLD}, plateau_delta={PLATEAU_DELTA}\n")
    _write_log(f"  迭代上限: max_foundation_iters={MAX_FOUNDATION_ITERS}, max_chapter_attempts={MAX_CHAPTER_ATTEMPTS}, max_revision_cycles={MAX_REV_CYCLES}\n")
    _write_log(f"  故事梗概: {STORY_SUMMARY}\n")
    _write_log(f"  日志文件: {LOG_FILE}\n")
    _write_log(f"  需求验证: 双写文件✅ 每行flush✅ 崩溃捕获✅ logs/自动创建✅\n")
    _write_log("=" * 70 + "\n")

    try:
        # ═════════════════════════════════════════════════════
        # 初始化
        # ═════════════════════════════════════════════════════
        instep("初始化: 清理 output + 写入正常阈值配置 + 创建初始 state")
        clean_output()
        write_e2e1_config()

        state = default_state()
        state["chapters_total"] = TOTAL_CH
        state["total_volumes"] = TOTAL_VOL
        state["chapters_per_volume"] = CH_PER_VOL
        save_state(state)
        inok("初始 state 已写入")
        snap("初始")

        # ═════════════════════════════════════════════════════
        # 核心: 全流水线 from_scratch
        # ═════════════════════════════════════════════════════
        instep("═══ 启动全流水线 from_scratch ═══")
        inlog("调用 run_pipeline('from_scratch') — 将自动执行 Phase 1→2→3→4")
        inlog(
            "预期 API 调用: Foundation(~7-21) + Drafting(~9-27) "
            "+ Revision(~30-45) + Export(0) = ~45-93"
        )
        inlog("⚠ 注意: 正常阈值下 Foundation/章节 可能多次重试，耗时会增加")

        _patch_pipeline_logging()  # monkey-patch step/banner，双写所有日志

        t_pipeline = time.time()
        _, err = safe_call("E2E1.run_pipeline(from_scratch)", run_pipeline, "from_scratch")

        _restore_pipeline_logging()  # 恢复原始函数

        if err:
            inerr(f"run_pipeline 失败: {err[0]}: {err[1]}")
            show_summary(t_global, failed_at="E2E1.run_pipeline(from_scratch)")
            return

        pipeline_elapsed = time.time() - t_pipeline
        inok(f"全流水线完成 — 总耗时 {pipeline_elapsed / 60:.1f}min")

        # ═════════════════════════════════════════════════════
        # 验证
        # ═════════════════════════════════════════════════════
        instep("═══ 验证产出 ═══")

        all_ok = True
        observations = []  # 观察性验证项记录

        # 加载最终 state
        try:
            final_state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            final_state = {}
            inerr("无法读取最终 state.json")

        # ====== A1: Foundation 文件产出 ======
        instep("验证 A1: Phase 1 文件产出")
        foundation_files = [
            "world.md", "characters.md", "outline_volume.md",
            "outline.md", "canon.md", "voice.md",
        ]
        a1_ok = True
        for fn in foundation_files:
            a1_ok &= file_check(OUTPUT_DIR / fn, fn, 100)
        if a1_ok:
            inok("A1: 全部 Foundation 文件产出 ✓")
        else:
            inerr("A1: Foundation 文件缺失")
        all_ok &= a1_ok

        # ====== A2: 章节文件产出 ======
        instep("验证 A2: Phase 2 章节文件")
        a2_ok = True
        for ch in range(1, TOTAL_CH + 1):
            ch_file = CHAPTERS_DIR / f"ch_{ch:02d}.md"
            ok = file_check(ch_file, f"ch_{ch:02d}.md", 500)
            # 额外检查字数
            if ok:
                try:
                    text = ch_file.read_text(encoding="utf-8")
                    word_count = len(text.replace(" ", "").replace("\n", ""))
                    inlog(f"  ch_{ch:02d}.md: {word_count} 字")
                    if word_count < 1000:
                        inlog(f"  ⚠ ch_{ch:02d}.md 字数偏低 ({word_count} < 1000)")
                except Exception:
                    pass
            a2_ok &= ok
        if a2_ok:
            inok(f"A2: 全部 {TOTAL_CH} 章产出 ✓")
        else:
            inerr("A2: 章节文件缺失")
        all_ok &= a2_ok

        # ====== A3: manuscript.md ======
        instep("验证 A3: Phase 4 manuscript.md")
        manuscript_path = OUTPUT_DIR / "manuscript.md"
        a3_ok = file_check(manuscript_path, "manuscript.md", 500)
        if a3_ok:
            try:
                text = manuscript_path.read_text(encoding="utf-8")
                # 检查是否包含各章内容（简单方法：看总字数）
                total_manuscript_words = len(text.replace(" ", "").replace("\n", ""))
                inlog(f"  manuscript.md: {total_manuscript_words} 字")
                # 检查是否包含章标题
                ch_count_in_manuscript = 0
                for ch in range(1, TOTAL_CH + 1):
                    if f"第{ch}章" in text or f"第 {ch} 章" in text:
                        ch_count_in_manuscript += 1
                inlog(f"  manuscript.md 包含 {ch_count_in_manuscript}/{TOTAL_CH} 章标题")
                if ch_count_in_manuscript < TOTAL_CH:
                    inlog("  ⚠ manuscript.md 可能不完整")
            except Exception:
                pass
        all_ok &= a3_ok

        # ====== A4: state.json ======
        instep("验证 A4: state.json 最终状态")
        phase = final_state.get("phase", "?")
        chapters_drafted = final_state.get("chapters_drafted", 0)
        chapters_total = final_state.get("chapters_total", 0)
        revision_cycle = final_state.get("revision_cycle", 0)
        novel_score = final_state.get("novel_score", 0)
        foundation_score = final_state.get("foundation_score", 0)

        inlog(
            f"  state: phase={phase} drafted={chapters_drafted}/{chapters_total} "
            f"revision_cycle={revision_cycle} novel_score={novel_score} "
            f"foundation_score={foundation_score}"
        )

        a4_ok = True
        a4_ok &= verify_condition(
            "A4/phase=complete", phase == "complete", f"phase={phase}"
        )
        a4_ok &= verify_condition(
            "A4/chapters_drafted", chapters_drafted == TOTAL_CH,
            f"drafted={chapters_drafted}"
        )
        a4_ok &= verify_condition(
            "A4/chapters_total", chapters_total == TOTAL_CH,
            f"total={chapters_total}"
        )
        all_ok &= a4_ok

        # ====== A5: results.tsv ======
        instep("验证 A5: results.tsv")
        a5_ok = file_check(RESULTS_FILE, "results.tsv", 100)
        if a5_ok:
            rows = _parse_results_tsv()
            inlog(f"  results.tsv: {len(rows)} 行记录")

            # 检查关键阶段存在
            stages_found = set(r[1] for r in rows)
            inlog(f"  阶段: {sorted(stages_found)}")

            # 检查 discard 行（质量循环路径覆盖）
            discard_rows = [r for r in rows if r[4] == "discard"]
            if discard_rows:
                inlog(f"  ★ 质量循环覆盖: {len(discard_rows)} 条 discard 记录")
                for dr in discard_rows:
                    inlog(f"    discard: stage={dr[1]} score={dr[2]} reason={dr[5][:80]}")
            else:
                observations.append("质量循环: 无 discard 记录（全部评分达标）")

            # 检查 keep 行
            keep_rows = [r for r in rows if r[4] == "keep"]
            inlog(f"  keep: {len(keep_rows)} 条记录")

        all_ok &= a5_ok

        # ====== A6: 零崩溃 ======
        # （如果执行到这里说明没有 uncaught exception，自动通过）
        inok("A6: 零崩溃 / 零未捕获异常 ✓ (执行到达此点)")

        # ====== B1: Foundation 重试循环（观察性） ======
        instep("验证 B1-B6: 质量循环路径覆盖（观察性）")
        found_rows = [r for r in rows if r[1] == "foundation"] if a5_ok else []
        if len(found_rows) >= 2:
            keep_f = [r for r in found_rows if r[4] == "keep"]
            discard_f = [r for r in found_rows if r[4] == "discard"]
            inlog(f"B1 Foundation 重试: {len(found_rows)} 行 (keep={len(keep_f)}, discard={len(discard_f)})")
            if discard_f:
                inok("B1: Foundation 重试循环已触发 ✓")
            else:
                observations.append("B1: Foundation 迭代全部 keep，未触发 discard 回退")
        else:
            inlog(f"B1 Foundation 重试: {len(found_rows)} 行")
            if len(found_rows) == 1:
                observations.append("B1: Foundation 一次通过，未触发 retry loop")
            else:
                observations.append("B1: 无 Foundation 记录（异常）")

        # ====== B2: 章节重试（观察性） ======
        ch_discard = [r for r in rows if r[4] == "discard" and r[1].startswith("ch")] if a5_ok else []
        if ch_discard:
            inlog(f"B2 章节重试: {len(ch_discard)} 条 discard → 已触发重试")
        else:
            observations.append("B2: 所有章节一次通过，未触发 retry")

        # ====== B3: canon 警告（观察性） ======
        # 在日志中搜索（无法直接从程序内搜索，需运行时观察）
        inlog("B3 canon 警告: 请检查上方 [PIPELINE] 日志中是否出现 '⚠ 警告: 正典条目'")

        # ====== B4: 平台期检测（观察性） ======
        rev_cycle = final_state.get("revision_cycle", 0)
        if rev_cycle < MAX_REV_CYCLES:
            inlog(f"B4 平台期: revision_cycle={rev_cycle} < {MAX_REV_CYCLES}，可能触发了平台期停止")
            inlog("  请检查上方 [PIPELINE] 日志中是否出现 '平台期检测 ... 停止修订'")
        else:
            inlog(f"B4 平台期: revision_cycle={rev_cycle}，达到 max 上限，未触发提前停止")

        # ====== B5: Foundation 回退不崩溃（观察性） ======
        # 如果有 discard，但脚本未崩溃 → 通过
        if any(r[4] == "discard" and r[1] == "foundation" for r in rows) if a5_ok else False:
            inok("B5: Foundation discard → git_reset_hard 链路未崩溃 ✓")
        else:
            observations.append("B5: 无 Foundation discard，回退链路未验证")

        # ====== B6: 修订回退不崩溃（观察性） ======
        rev_discard = [r for r in rows if r[4] == "discard" and "rev" in r[1]] if a5_ok else []
        if rev_discard:
            inok(f"B6: 修订回退: {len(rev_discard)} 条 discard → 链路未崩溃 ✓")
        else:
            observations.append("B6: 无修订 discard，回退链路未验证")

        # ====== C1: 增量 canon ======
        instep("验证 C1-C4: 业务正确性")
        canon_entry_count = final_state.get("canon_entry_count", 0)
        inlog(f"C1 增量 canon: canon_entry_count={canon_entry_count}")
        if canon_entry_count > 0:
            inok(f"C1: 增量 canon 正常 ({canon_entry_count} 条) ✓")
        else:
            inlog("C1: canon_entry_count=0（可能 canon 未增长或被重置）")

        # ====== C2: 文风指纹 ======
        inlog("C2 文风指纹: 请检查上方 [PIPELINE] 日志中是否出现 '文风指纹'")

        # ====== C3: 反模式审计 ======
        inlog("C3 反模式审计: 请检查上方 [PIPELINE] 日志中是否出现 '结构反模式'")

        # ====== C4: results.tsv 完整 ======
        if a5_ok:
            expected_stages = ["foundation"]
            for ch in range(1, TOTAL_CH + 1):
                expected_stages.append(f"ch{ch:02d}")
            expected_stages.extend(["revision", "export"])
            missing = [s for s in expected_stages if s not in str(rows)]
            if not missing:
                inok("C4: results.tsv 各阶段记录完整 ✓")
            else:
                inlog(f"C4: results.tsv 缺少阶段: {missing}")
        else:
            inerr("C4: results.tsv 无法解析")

        # ====== 总结 ======
        instep("═══ 验证结果汇总 ═══")
        if all_ok:
            inok("全部结构完整性验证 (A1-A6) 通过 ✓")
        else:
            inerr("存在结构完整性失败项 ✗")

        if observations:
            inlog("")
            inlog("观察性验证项（未触发不判失败，需人工判断）：")
            for obs in observations:
                inlog(f"  📋 {obs}")

        show_summary(t_global, success=all_ok, observations=observations)

    except Exception as e:
        # ═════════════════════════════════════════════════════
        # 顶层崩溃捕获（需求3: [CRASH] 格式）
        # ═════════════════════════════════════════════════════
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
            _write_log(
                f"  [CRASH] 崩溃时的state：phase={crash_s.get('phase')} "
                f"drafted={crash_s.get('chapters_drafted')}/{crash_s.get('chapters_total')} "
                f"cycle={crash_s.get('revision_cycle')} "
                f"score={crash_s.get('novel_score', '?')}\n"
            )
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
        _restore_pipeline_logging()  # 确保恢复原始函数
        _fp_log.close()
        sys.stdout.write(f"\n  日志已保存至: {LOG_FILE}\n")
        sys.stdout.flush()


def show_summary(t_global: float, failed_at: str = None, success: bool = None,
                 observations: list = None):
    """打印汇总（终端+文件双写）"""
    total_elapsed = time.time() - t_global
    _write_log(f"\n{'=' * 70}\n")
    if success:
        _write_log("  ✅ Stage 4 E2E-1 全插桩执行完成 — 结构完整性全部通过!\n")
    elif failed_at:
        _write_log(f"  ❌ Stage 4 E2E-1 在 [{failed_at}] 处失败\n")
    else:
        _write_log("  ⚠ Stage 4 E2E-1 执行结束（状态不明）\n")
    _write_log(f"  总耗时: {total_elapsed / 60:.1f}min\n")
    _write_log(f"  配置: {TOTAL_VOL}卷×{CH_PER_VOL}章={TOTAL_CH}章\n")
    _write_log(f"  质量阈值: foundation={FOUNDATION_THRESHOLD}, chapter={CHAPTER_THRESHOLD}, plateau_delta={PLATEAU_DELTA}\n")
    _write_log(f"  迭代上限: foundation_iters={MAX_FOUNDATION_ITERS}, ch_attempts={MAX_CHAPTER_ATTEMPTS}, rev_cycles={MAX_REV_CYCLES}\n")
    if observations:
        _write_log(f"  观察性验证: {len(observations)} 项需人工判断\n")
    _write_log(f"{'=' * 70}\n")


if __name__ == "__main__":
    main()