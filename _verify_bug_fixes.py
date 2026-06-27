#!/usr/bin/env python3
"""5.7.5 Bug修复最小验证 — 复用现有4章，只跑 run_revision(max_cycles=1)

验证两个修复:
  Bug 1: gen_brief.py sys.exit() → raise FileNotFoundError
  Bug 2: pipeline_orchestrator.py threshold 变量

前提: output/chapters/ch_01.md–ch_04.md 已存在
预期: revision_cycle ≥ 1 且不崩溃
"""

import json, sys, time
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from core.config import config, OUTPUT_DIR, CHAPTERS_DIR, CONFIG_FILE, STATE_FILE
from core.state_manager import default_state, load_state, save_state
from pipeline_orchestrator import run_revision

TOTAL_CH = 4
TOTAL_VOL = 2
CH_PER_VOL = 2

# ═══ 1. 写 config ═══
cfg = {
    "story_summary": "2049年上海，程序员在维护老旧服务器时发现AI觉醒迹象，36小时倒计时。悬疑科幻风格，节奏紧凑。",
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
    json.dump(cfg, f, indent=2, ensure_ascii=False)
config._loaded = False
config.load()
print(f"  ✓ config.json: total_chapters={TOTAL_CH}, total_volumes={TOTAL_VOL}")

# ═══ 2. 确认章节存在 ═══
for ch in range(1, 5):
    p = CHAPTERS_DIR / f"ch_{ch:02d}.md"
    if not p.exists():
        print(f"  ❌ 第{ch}章缺失: {p}")
        sys.exit(1)
    print(f"  ✓ ch_{ch:02d}.md: {p.stat().st_size}B")

# ═══ 3. 写 state ═══
state = default_state()
state.update({
    "phase": "revision",
    "revision_cycle": 0,
    "chapters_drafted": TOTAL_CH,
    "chapters_total": TOTAL_CH,
    "total_volumes": TOTAL_VOL,
    "chapters_per_volume": CH_PER_VOL,
    "foundation_score": 7.2,
    "lore_score": 7.2,
})
save_state(state)
print(f"  ✓ state.json: phase=revision, chapters={TOTAL_CH}/{TOTAL_CH}")

# ═══ 4. 执行 run_revision ═══
print("\n" + "=" * 60)
print("  运行 run_revision(max_cycles=1)...")
print("=" * 60)
t0 = time.time()

try:
    state = run_revision(state, max_cycles=1)
    print(f"\n  ✅ run_revision 返回成功")
except SystemExit as e:
    print(f"\n  ❌ sys.exit({e.code}) 被调用 — Bug 1 修复未生效!")
    sys.exit(1)
except NameError as e:
    if "threshold" in str(e):
        print(f"\n  ❌ NameError: threshold — Bug 2 修复未生效!")
        sys.exit(1)
    raise
except Exception as e:
    print(f"\n  ⚠ 其他异常: {e}")
    import traceback
    traceback.print_exc()

elapsed = time.time() - t0
print(f"\n  耗时: {elapsed/60:.1f}min")

# ═══ 5. 验证 ═══
state = load_state()
print(f"\n{'='*60}")
print(f"  最终 state:")
print(f"  phase={state.get('phase')}")
print(f"  revision_cycle={state.get('revision_cycle')}")
print(f"  chapters_drafted={state.get('chapters_drafted')}/{state.get('chapters_total')}")
print(f"  novel_score={state.get('novel_score')}")

if state.get("revision_cycle", 0) >= 1:
    print(f"\n  ✅✅✅ 两个 Bug 修复均已生效! revision_cycle={state.get('revision_cycle')}")
else:
    print(f"\n  ❌ revision_cycle={state.get('revision_cycle')} — cycle 1 未完成")
    sys.exit(1)