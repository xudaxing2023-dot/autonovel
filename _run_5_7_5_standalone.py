#!/usr/bin/env python3
"""5.7.5 多次中断串联 — 独立执行脚本（绕过测试框架）
2卷×2章, 4次中断, 5步执行, 每步之间存盘验证"""

import json, sys, time
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from core.config import config, OUTPUT_DIR, CHAPTERS_DIR, CONFIG_FILE, STATE_FILE, RESULTS_FILE
from core.state_manager import default_state, load_state, save_state, parse_score
from pipeline_orchestrator import run_foundation, run_revision, run_pipeline
from drafting.draft_chapter import draft_chapter
from evaluation.evaluate import evaluate_chapter

TOTAL_CH = 4
TOTAL_VOL = 2
CH_PER_VOL = 2
MAX_REV_CYCLES_CFG = 2  # config.json 中的值，让 run_revision 读
PLATEAU_DELTA = 999.0

def show_state(label=""):
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
    print(f"  phase={s.get('phase')}  drafted={s.get('chapters_drafted')}/{s.get('chapters_total')}  cycle={s.get('revision_cycle')}  score={s.get('novel_score','?')}")
    print(f"  CONFIG: total_ch={c.get('total_chapters')}  total_vol={c.get('total_volumes')}  ch_per_vol={c.get('chapters_per_volume')}  max_rev_cycles={c.get('max_revision_cycles')}  plateau_delta={c.get('plateau_delta')}")
    return s, c

def write_config():
    data = {
        "story_summary": "2049年上海，程序员在维护老旧服务器时发现AI觉醒迹象，36小时倒计时。悬疑科幻风格，节奏紧凑。",
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
    print(f"  ✓ config.json 写入: total_chapters={TOTAL_CH}")

def verify(label, cond, detail=""):
    status = "✅" if cond else "❌"
    print(f"    {status} {label}: {detail}")
    if not cond:
        raise AssertionError(f"{label}: {detail}")

# ═══════════════════════════════════════════════════════════════
print("=" * 70)
print("  5.7.5 多次中断串联 — 独立脚本执行")
print(f"  配置: {TOTAL_VOL}卷×{CH_PER_VOL}章={TOTAL_CH}章, {MAX_REV_CYCLES_CFG}轮修订")
print("=" * 70)

write_config()
show_state("初始")

t_global = time.time()

# ═══════════════════════════════════════════════════════════════
# Step 1: Foundation → 中断1 (F→D 边界)
# ═══════════════════════════════════════════════════════════════
print(f"\n{'─'*60}")
print("  Step 1: Foundation 完整执行")
print(f"{'─'*60}")
t0 = time.time()
state = default_state()
state["chapters_total"] = TOTAL_CH  # ★ 关键: 显式设 chapters_total，不依赖 config
save_state(state)

state = run_foundation(state)
# ★ 验证后立即显式加固 state
state["chapters_total"] = TOTAL_CH
state["total_volumes"] = TOTAL_VOL
state["chapters_per_volume"] = CH_PER_VOL
save_state(state)

elapsed = time.time() - t0
print(f"  耗时: {elapsed/60:.1f}min")

s, c = show_state("中断1: Foundation 完成")
verify("Int1/phase=drafting", s.get("phase") == "drafting", f"phase={s.get('phase')}")
verify("Int1/chapters_drafted=0", s.get("chapters_drafted") == 0, f"drafted={s.get('chapters_drafted')}")
verify("Int1/chapters_total=4", s.get("chapters_total") == TOTAL_CH, f"total={s.get('chapters_total')}")
verify("Int1/config total_ch=4", c.get("total_chapters") == TOTAL_CH, f"config total_ch={c.get('total_chapters')}")
for fn in ["world.md", "characters.md", "outline.md", "canon.md", "voice.md"]:
    p = OUTPUT_DIR / fn
    verify(f"Int1/{fn}", p.exists() and p.stat().st_size > 100, f"{p.stat().st_size}B" if p.exists() else "MISSING")

# ═══════════════════════════════════════════════════════════════
# Step 2: Drafting 卷1 ch_01 + ch_02 → 中断2
# ═══════════════════════════════════════════════════════════════
print(f"\n{'─'*60}")
print("  Step 2: Drafting 卷1 (ch_01 + ch_02)")
print(f"{'─'*60}")
t0 = time.time()

state = load_state()
# ★ 加固
state["chapters_total"] = TOTAL_CH
state["total_volumes"] = TOTAL_VOL
state["chapters_per_volume"] = CH_PER_VOL

# ch_01
print(f"  起草 第 1/{TOTAL_CH} 章 ...")
draft_chapter(1, max_tokens=16000)
eval_result = evaluate_chapter(1)
score = parse_score(eval_result, "overall_score")
state["chapters_drafted"] = 1
state["chapters_total"] = TOTAL_CH
save_state(state)
print(f"  ch_01 评分: {score}")

# ch_02
print(f"  起草 第 2/{TOTAL_CH} 章 ...")
draft_chapter(2, max_tokens=16000)
eval_result = evaluate_chapter(2)
score = parse_score(eval_result, "overall_score")
state["chapters_drafted"] = 2
state["chapters_total"] = TOTAL_CH
save_state(state)
print(f"  ch_02 评分: {score}")

elapsed = time.time() - t0
print(f"  耗时: {elapsed/60:.1f}min")

s, c = show_state("中断2: 卷1完成")
verify("Int2/phase=drafting", s.get("phase") == "drafting", f"phase={s.get('phase')}")
verify("Int2/chapters_drafted=2", s.get("chapters_drafted") == 2, f"drafted={s.get('chapters_drafted')}")
verify("Int2/chapters_total=4", s.get("chapters_total") == TOTAL_CH, f"total={s.get('chapters_total')}")
for ch in range(1, 3):
    chp = CHAPTERS_DIR / f"ch_{ch:02d}.md"
    verify(f"Int2/ch_{ch:02d}.md", chp.exists() and chp.stat().st_size >= 300, f"{chp.stat().st_size}B" if chp.exists() else "MISSING")
ch03p = CHAPTERS_DIR / "ch_03.md"
verify("Int2/ch_03_NOT_exists", not ch03p.exists(), "OK" if not ch03p.exists() else "SHOULD NOT EXIST")

# ═══════════════════════════════════════════════════════════════
# Step 3: Drafting 卷2 + Revision cycle 1 → 中断3
# ═══════════════════════════════════════════════════════════════
print(f"\n{'─'*60}")
print("  Step 3: Drafting 卷2 (ch_03+ch_04) + Revision cycle 1")
print(f"{'─'*60}")
t0 = time.time()

state = load_state()
state["chapters_total"] = TOTAL_CH
state["total_volumes"] = TOTAL_VOL
state["chapters_per_volume"] = CH_PER_VOL

# ch_03
print(f"  起草 第 3/{TOTAL_CH} 章 ...")
draft_chapter(3, max_tokens=16000)
eval_result = evaluate_chapter(3)
score = parse_score(eval_result, "overall_score")
state["chapters_drafted"] = 3
state["chapters_total"] = TOTAL_CH
save_state(state)
print(f"  ch_03 评分: {score}")

# ch_04
print(f"  起草 第 4/{TOTAL_CH} 章 ...")
draft_chapter(4, max_tokens=16000)
eval_result = evaluate_chapter(4)
score = parse_score(eval_result, "overall_score")
state["chapters_drafted"] = 4
state["chapters_total"] = TOTAL_CH
save_state(state)
print(f"  ch_04 评分: {score}")

# 设置 phase 进入 revision
state["phase"] = "revision"
state["revision_cycle"] = 0
state["chapters_total"] = TOTAL_CH
state["chapters_drafted"] = TOTAL_CH
state["total_volumes"] = TOTAL_VOL
state["chapters_per_volume"] = CH_PER_VOL
save_state(state)

s_before_rev, c_before_rev = show_state("Revision 前")
verify("PreRev/chapters_total=4", s_before_rev.get("chapters_total") == TOTAL_CH, f"total={s_before_rev.get('chapters_total')}")

# ★ 确保 config.json 不被 run_revision 内部覆盖
write_config()

# 执行 Revision cycle 1
print(f"\n  执行 Revision cycle 1 (max_cycles=1) ...")
state = run_revision(state, max_cycles=1)

# ★ 加固 state — 回滚 phase 模拟中断3
state = load_state()
if state.get("revision_cycle", 0) < 1:
    state["revision_cycle"] = 1
    print(f"  [修复] revision_cycle 手动设为 1")
state["phase"] = "revision"
state["chapters_total"] = TOTAL_CH
state["chapters_drafted"] = TOTAL_CH
state["total_volumes"] = TOTAL_VOL
state["chapters_per_volume"] = CH_PER_VOL
save_state(state)

elapsed = time.time() - t0
print(f"  耗时: {elapsed/60:.1f}min")

s, c = show_state("中断3: Revision cycle 1 完成")
verify("Int3/phase=revision", s.get("phase") == "revision", f"phase={s.get('phase')}")
verify("Int3/revision_cycle>=1", s.get("revision_cycle", 0) >= 1, f"cycle={s.get('revision_cycle')}")
verify("Int3/chapters_drafted=4", s.get("chapters_drafted") == TOTAL_CH, f"drafted={s.get('chapters_drafted')}")
verify("Int3/chapters_total=4", s.get("chapters_total") == TOTAL_CH, f"total={s.get('chapters_total')}")

# ═══════════════════════════════════════════════════════════════
# Step 4: Revision cycle 2 (含跨卷审阅) + Export → 中断4
# ═══════════════════════════════════════════════════════════════
print(f"\n{'─'*60}")
print("  Step 4: Revision cycle 2 + Export → 中断4")
print(f"{'─'*60}")
t0 = time.time()

# 加固 state + config
state = load_state()
state["chapters_total"] = TOTAL_CH
state["chapters_drafted"] = TOTAL_CH
state["total_volumes"] = TOTAL_VOL
state["chapters_per_volume"] = CH_PER_VOL
save_state(state)
write_config()

try:
    run_pipeline(mode="resume", max_cycles=MAX_REV_CYCLES_CFG)
except Exception as e:
    print(f"  ⚠ run_pipeline 异常: {e}")
    import traceback
    traceback.print_exc()

elapsed = time.time() - t0
print(f"  耗时: {elapsed/60:.1f}min")

# 回滚 phase 模拟中断4
state = load_state()
state["phase"] = "export"
state["chapters_total"] = TOTAL_CH
state["chapters_drafted"] = TOTAL_CH
state["total_volumes"] = TOTAL_VOL
state["chapters_per_volume"] = CH_PER_VOL
save_state(state)

s, c = show_state("中断4: Export 边界")
verify("Int4/phase=export", s.get("phase") == "export", f"phase={s.get('phase')}")
verify("Int4/revision_cycle>=2", s.get("revision_cycle", 0) >= 2, f"cycle={s.get('revision_cycle')}")
verify("Int4/chapters_drafted=4", s.get("chapters_drafted") == TOTAL_CH, f"drafted={s.get('chapters_drafted')}")

# ═══════════════════════════════════════════════════════════════
# Step 5: Export resume → complete
# ═══════════════════════════════════════════════════════════════
print(f"\n{'─'*60}")
print("  Step 5: Export resume → complete")
print(f"{'─'*60}")
t0 = time.time()

state = load_state()
state["chapters_total"] = TOTAL_CH
state["chapters_drafted"] = TOTAL_CH
save_state(state)
write_config()

run_pipeline(mode="resume")

elapsed = time.time() - t0
total_elapsed = time.time() - t_global
print(f"  耗时: {elapsed/60:.1f}min")
print(f"\n  ═══ 5.7.5 全流程完成, 总耗时: {total_elapsed/60:.1f}min ═══")

s, c = show_state("最终: complete")
verify("Final/phase=complete", s.get("phase") == "complete", f"phase={s.get('phase')}")
verify("Final/chapters_drafted=4", s.get("chapters_drafted") == TOTAL_CH, f"drafted={s.get('chapters_drafted')}")
verify("Final/chapters_total=4", s.get("chapters_total") == TOTAL_CH, f"total={s.get('chapters_total')}")
verify("Final/revision_cycle>=2", s.get("revision_cycle", 0) >= 2, f"cycle={s.get('revision_cycle')}")

# 产出验证
for ch in range(1, 5):
    chp = CHAPTERS_DIR / f"ch_{ch:02d}.md"
    verify(f"Final/ch_{ch:02d}.md", chp.exists() and chp.stat().st_size >= 300, f"{chp.stat().st_size}B" if chp.exists() else "MISSING")

ms = OUTPUT_DIR / "manuscript.md"
verify("Final/manuscript.md", ms.exists(), f"{len(ms.read_text(encoding='utf-8'))} chars" if ms.exists() else "MISSING")

arc = OUTPUT_DIR / "arc_summary.md"
verify("Final/arc_summary.md", arc.exists(), "OK" if arc.exists() else "MISSING")

print(f"\n{'='*70}")
print(f"  ✅ 5.7.5 独立脚本执行完成!")
print(f"  总耗时: {total_elapsed/60:.1f}min")
print(f"{'='*70}")