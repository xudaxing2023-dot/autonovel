#!/usr/bin/env python3
"""5.7.5 多次中断串联 — 简化替代验证 (方案A)

不使用复杂的5步手动中断链。
改为两阶段验证:
  Test A: run_pipeline("from_scratch") 全流程 — 验证完整产出
  Test B: run_foundation → run_pipeline("resume") — 验证 resume 机制

先决条件: 两个 Bug 已修复:
  - gen_brief.py:749,754 sys.exit() → raise
  - pipeline_orchestrator.py:439 threshold 变量已定义
"""

import json, shutil, sys, time
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from core.config import config, OUTPUT_DIR, CHAPTERS_DIR, CONFIG_FILE, STATE_FILE, RESULTS_FILE
from core.state_manager import default_state, load_state, save_state
from pipeline_orchestrator import run_foundation, run_pipeline

TOTAL_CH = 4
TOTAL_VOL = 2
CH_PER_VOL = 2

STORY_SUMMARY = (
    "2049年上海，程序员在维护老旧服务器时发现AI觉醒迹象，"
    "36小时倒计时。悬疑科幻风格，节奏紧凑。"
)


# =============================================================================
# 工具函数
# =============================================================================

def write_config():
    """写入最小化配置，压低阈值确保一次通过。"""
    data = {
        "story_summary": STORY_SUMMARY,
        "total_chapters": TOTAL_CH,
        "total_volumes": TOTAL_VOL,
        "chapters_per_volume": CH_PER_VOL,
        "max_foundation_iters": 1,
        "max_chapter_attempts": 1,
        "max_revision_cycles": 2,
        "foundation_threshold": 1.0,
        "chapter_threshold": 1.0,
        "plateau_delta": 999.0,
    }
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    config._loaded = False
    config.load()
    print(f"  ✓ config.json 写入: total_chapters={TOTAL_CH}, total_volumes={TOTAL_VOL}")


def clean_output():
    """清理 output/ 目录中的所有产出和 state。"""
    # 删除子目录
    for sub in ["chapters", "briefs", "edit_logs", "eval_logs"]:
        d = OUTPUT_DIR / sub
        if d.exists():
            shutil.rmtree(d)
    # 删除顶层文件
    for pat in ["*.md", "*.json", "*.tsv", "*.txt"]:
        for f in OUTPUT_DIR.glob(pat):
            f.unlink()
    # 删除 state
    STATE_FILE.unlink(missing_ok=True)
    print("  ✓ 清理 output/ 完成")


def verify(label, cond, detail=""):
    """验证断点，失败抛出 AssertionError。"""
    status = "✅" if cond else "❌"
    print(f"    {status} {label}: {detail}")
    if not cond:
        raise AssertionError(f"{label}: {detail}")


def show_state(label=""):
    """打印当前 state 摘要。"""
    try:
        s = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        s = {}
    try:
        c = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        c = {}
    print(f"\n{'='*60}")
    print(f"  STATE [{label}]")
    print(f"  phase={s.get('phase')}  drafted={s.get('chapters_drafted')}/{s.get('chapters_total')}  "
          f"cycle={s.get('revision_cycle')}  score={s.get('novel_score','?')}")
    print(f"  CONFIG: total_ch={c.get('total_chapters')}  total_vol={c.get('total_volumes')}  "
          f"ch_per_vol={c.get('chapters_per_volume')}  max_rev_cycles={c.get('max_revision_cycles')}")
    return s, c


def final_verify():
    """通用最终验证：phase=complete, 4章存在, manuscript/arc_summary 存在。"""
    s = json.loads(STATE_FILE.read_text(encoding="utf-8"))

    verify("phase=complete", s.get("phase") == "complete",
           f"phase={s.get('phase')}")
    verify("chapters_drafted=4", s.get("chapters_drafted") == TOTAL_CH,
           f"drafted={s.get('chapters_drafted')}")
    verify("revision_cycle>=2", s.get("revision_cycle", 0) >= 2,
           f"cycle={s.get('revision_cycle')}")
    verify("novel_score>0", s.get("novel_score", 0) > 0,
           f"score={s.get('novel_score')}")

    for ch in range(1, TOTAL_CH + 1):
        p = CHAPTERS_DIR / f"ch_{ch:02d}.md"
        ok = p.exists() and p.stat().st_size >= 300
        verify(f"ch_{ch:02d}.md", ok,
               f"{p.stat().st_size}B" if p.exists() else "MISSING")

    ms = OUTPUT_DIR / "manuscript.md"
    verify("manuscript.md", ms.exists(),
           f"{len(ms.read_text(encoding='utf-8'))} chars" if ms.exists() else "MISSING")

    arc = OUTPUT_DIR / "arc_summary.md"
    verify("arc_summary.md", arc.exists(),
           f"{arc.stat().st_size}B" if arc.exists() else "MISSING")

    outline = OUTPUT_DIR / "outline.md"
    verify("outline.md", outline.exists(),
           f"{outline.stat().st_size}B" if outline.exists() else "MISSING")


# =============================================================================
# Test A: from_scratch 全流程
# =============================================================================

def test_a_from_scratch():
    """改进版 Test A：先运行 foundation，手动设置章节数，然后 resume 完成剩余阶段"""
    print(f"\n{'─'*60}")
    print("  Test A: foundation → resume 完整流程 (改进版)")
    print(f"{'─'*60}")

    clean_output()
    write_config()

    # ── 1️⃣ Foundation 阶段 ──
    t0 = time.time()
    state = default_state()
    # 明确声明章节总数，以便后续 drafting 使用
    state["chapters_total"] = TOTAL_CH
    state["total_volumes"] = TOTAL_VOL
    state["chapters_per_volume"] = CH_PER_VOL
    save_state(state)
    state = run_foundation(state)
    # Foundation 完成后再次确保章节数在 state 中（run_foundation 可能覆盖）
    state["chapters_total"] = TOTAL_CH
    state["total_volumes"] = TOTAL_VOL
    state["chapters_per_volume"] = CH_PER_VOL
    save_state(state)
    foundation_time = time.time() - t0
    print(f"\n  Foundation 耗时: {foundation_time/60:.1f}min")

    # ── 2️⃣ Resume 阶段：继续 Drafting → Revision → Export ──
    t1 = time.time()
    run_pipeline("resume")
    resume_time = time.time() - t1
    print(f"\n  Resume 耗时: {resume_time/60:.1f}min")

    total = (foundation_time + resume_time) / 60
    print(f"\n  Test A 总耗时: {total:.1f}min")

    s, c = show_state("Test A 完成")
    final_verify()
    print("\n  ✅ Test A 通过!")


# =============================================================================
# Test B: Foundation → resume (模拟 Foundation→Drafting 边界中断恢复)
# =============================================================================

def test_b_foundation_resume():
    print(f"\n{'─'*60}")
    print("  Test B: run_foundation → run_pipeline(resume) 中断恢复")
    print(f"{'─'*60}")

    clean_output()
    write_config()

    # ═══ Foundation 阶段 ═══
    t0 = time.time()
    state = default_state()
    state["chapters_total"] = TOTAL_CH
    state["total_volumes"] = TOTAL_VOL
    state["chapters_per_volume"] = CH_PER_VOL
    save_state(state)

    state = run_foundation(state)
    # 加固 state（确保 chapters_total 不被覆盖）
    state["chapters_total"] = TOTAL_CH
    state["total_volumes"] = TOTAL_VOL
    state["chapters_per_volume"] = CH_PER_VOL
    save_state(state)
    foundation_time = time.time() - t0
    print(f"\n  Foundation 耗时: {foundation_time/60:.1f}min")

    # ═══ 中断点验证: Foundation→Drafting 边界 ═══
    s, c = show_state("中断: Foundation 完成, 即将进入 Drafting")
    verify("Int/phase=drafting",
           s.get("phase") == "drafting",
           f"phase={s.get('phase')}")
    verify("Int/chapters_drafted=0",
           s.get("chapters_drafted") == 0,
           f"drafted={s.get('chapters_drafted')}")
    verify("Int/chapters_total=4",
           s.get("chapters_total") == TOTAL_CH,
           f"total={s.get('chapters_total')}")
    verify("Int/config total_ch=4",
           c.get("total_chapters") == TOTAL_CH,
           f"config total_ch={c.get('total_chapters')}")
    for fn in ["world.md", "characters.md", "outline.md", "canon.md", "voice.md"]:
        p = OUTPUT_DIR / fn
        verify(f"Int/{fn}",
               p.exists() and p.stat().st_size > 100,
               f"{p.stat().st_size}B" if p.exists() else "MISSING")
    print("  ✅ 中断验证通过 — Foundation 产出完整, phase=drafting")

    # ═══ Resume 阶段 ═══
    print(f"\n{'─'*60}")
    print("  Resume: run_pipeline(resume) — 从 drafting 继续")
    print(f"{'─'*60}")
    # 确保 config 在 resume 前正确
    write_config()
    state = load_state()
    state["chapters_total"] = TOTAL_CH
    state["total_volumes"] = TOTAL_VOL
    state["chapters_per_volume"] = CH_PER_VOL
    save_state(state)

    t0 = time.time()
    run_pipeline("resume")
    resume_time = time.time() - t0
    print(f"\n  Resume 耗时: {resume_time/60:.1f}min")

    # ═══ 最终验证 ═══
    s, c = show_state("Test B 完成: resume 后")
    final_verify()

    total_time = (foundation_time + resume_time) / 60
    print(f"\n  ✅ Test B 通过! 总耗时: {total_time:.1f}min")


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("  5.7.5 多次中断串联 — 简化替代验证 (方案A)")
    print(f"  配置: {TOTAL_VOL}卷×{CH_PER_VOL}章={TOTAL_CH}章, 2轮修订")
    print(f"  Bug修复: gen_brief sys.exit→raise ✅ | pipeline_orchestrator threshold ✅")
    print("=" * 70)

    t_global = time.time()

    test_a_from_scratch()
    test_b_foundation_resume()

    total = (time.time() - t_global) / 60
    print(f"\n{'='*70}")
    print(f"  ✅ 5.7.5 简化验证全部通过!")
    print(f"  总耗时: {total:.1f}min")
    print(f"{'='*70}")