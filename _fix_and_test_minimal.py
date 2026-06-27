#!/usr/bin/env python3
"""5.7.5 — 一次性修复全部 Bug + Layer 1 最小验证

Bug修复:
  1. gen_brief.py:749 sys.exit() → raise FileNotFoundError
  2. gen_brief.py:754 sys.exit() → raise ValueError
  3. pipeline_orchestrator.py:438 添加 threshold 变量

验证:
  复用现有4章 → 只跑 run_revision(max_cycles=1)
  通过标准: revision_cycle ≥ 1
"""

import json, sys, time
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ═══════════════════════════════════════════════════════════════
# Phase 0: 修复全部 Bug
# ═══════════════════════════════════════════════════════════════
print("=" * 60)
print("  Phase 0: 修复全部 3 个 Bug")
print("=" * 60)

def fix_file(path, old, new, desc):
    content = open(path, "r", encoding="utf-8").read()
    if new in content:
        print(f"  ✅ {desc}: 已修复 (跳过)")
        return True
    if old not in content:
        # Already fixed but with different text? Check anyway
        if "raise" in content.split(old.split("\n")[0])[0] if old.split("\n")[0] in content else False:
            pass  # continue to check
        print(f"  ⚠ {desc}: SEARCH 块未找到 (可能已修复), 尝试定位...")
        lines = content.split("\n")
        for i, line in enumerate(lines):
            if old.split("\n")[0].strip() in line:
                print(f"    找到相似行 {i+1}: {line.strip()}")
                if "raise" in line:
                    print(f"    → 该行已包含 raise, 视为已修复")
                    return True
        return False
    content = content.replace(old, new)
    open(path, "w", encoding="utf-8").write(content)
    # Verify
    verify = open(path, "r", encoding="utf-8").read()
    if new in verify:
        print(f"  ✅ {desc}: 写入成功")
        return True
    else:
        print(f"  ❌ {desc}: 写入后验证失败")
        return False

ROOT_DIR = ROOT

# Bug 1: gen_brief.py line 749
fix1 = fix_file(
    str(ROOT_DIR / "revision/gen_brief.py"),
    'if full_eval_path is None:\n        sys.exit("错误: eval_logs/ 中未找到 *_full.json")',
    'if full_eval_path is None:\n        raise FileNotFoundError("eval_logs/ 中未找到 *_full.json")',
    "Bug1: gen_brief.py:749 sys.exit→raise"
)

# Bug 2: gen_brief.py line 754
fix2 = fix_file(
    str(ROOT_DIR / "revision/gen_brief.py"),
    'if ch is None:\n        sys.exit("错误: 全文评估中未包含 \'weakest_chapter\' 字段")',
    'if ch is None:\n        raise ValueError("全文评估中未包含 \'weakest_chapter\' 字段")',
    "Bug2: gen_brief.py:754 sys.exit→raise"
)

# Bug 3: pipeline_orchestrator.py — add threshold
fix3 = fix_file(
    str(ROOT_DIR / "pipeline_orchestrator.py"),
    'plateau_delta = cfg.get("plateau_delta", PLATEAU_DELTA) if cfg.loaded else PLATEAU_DELTA\n    max_tokens',
    'plateau_delta = cfg.get("plateau_delta", PLATEAU_DELTA) if cfg.loaded else PLATEAU_DELTA\n    threshold = cfg.chapter_threshold if cfg.loaded else CHAPTER_THRESHOLD\n    max_tokens',
    "Bug3: pipeline_orchestrator.py 添加 threshold"
)

if not all([fix1, fix2, fix3]):
    print("\n  ❌ 部分 Bug 修复失败, 中止!")
    sys.exit(1)

# ═══════════════════════════════════════════════════════════════
# Phase 1: 清理 + 配置
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("  Phase 1: 环境准备")
print("=" * 60)

from core.config import config, OUTPUT_DIR, CHAPTERS_DIR, CONFIG_FILE, STATE_FILE
from core.state_manager import default_state, load_state, save_state

TOTAL_CH = 4; TOTAL_VOL = 2; CH_PER_VOL = 2

# 确认4章存在
for ch in range(1, 5):
    p = CHAPTERS_DIR / f"ch_{ch:02d}.md"
    if not p.exists():
        print(f"  ❌ 第{ch}章缺失! 请先执行 Foundation + Drafting")
        sys.exit(1)
    print(f"  ✓ ch_{ch:02d}.md: {p.stat().st_size}B")

# 写 config
cfg = {
    "story_summary": "2049年上海，程序员在维护老旧服务器时发现AI觉醒迹象。悬疑科幻风格。",
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
CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
with open(CONFIG_FILE, "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2, ensure_ascii=False)
config._loaded = False
config.load()
print(f"  ✓ config: total_ch={TOTAL_CH}, total_vol={TOTAL_VOL}")

# 写 state
state = default_state()
state.update({
    "phase": "revision", "revision_cycle": 0,
    "chapters_drafted": TOTAL_CH, "chapters_total": TOTAL_CH,
    "total_volumes": TOTAL_VOL, "chapters_per_volume": CH_PER_VOL,
    "foundation_score": 7.2, "lore_score": 7.2,
})
save_state(state)
print(f"  ✓ state: phase=revision, chapters={TOTAL_CH}/{TOTAL_CH}")

# ═══════════════════════════════════════════════════════════════
# Phase 2: 验证 — 只跑 run_revision(max_cycles=1)
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("  Phase 2: run_revision(max_cycles=1) — 验证 3 个 Bug 修复")
print("=" * 60)

from pipeline_orchestrator import run_revision

t0 = time.time()
try:
    state = run_revision(state, max_cycles=1)
    print(f"\n  ✅ run_revision 返回成功")
except SystemExit as e:
    print(f"\n  ❌ sys.exit({e.code}) — Bug1 或 Bug2 修复未生效!")
    sys.exit(1)
except NameError as e:
    if "threshold" in str(e):
        print(f"\n  ❌ NameError: threshold — Bug3 修复未生效!")
        sys.exit(1)
    raise
except Exception as e:
    print(f"\n  ⚠ 其他异常: {e}")
    import traceback; traceback.print_exc()
    sys.exit(1)

elapsed = time.time() - t0
print(f"  耗时: {elapsed/60:.1f}min")

# ═══════════════════════════════════════════════════════════════
# Phase 3: 验证结果
# ═══════════════════════════════════════════════════════════════
state = load_state()
print(f"\n{'='*60}")
print(f"  最终 state:")
print(f"  phase={state.get('phase')}")
print(f"  revision_cycle={state.get('revision_cycle')}")
print(f"  chapters_drafted={state.get('chapters_drafted')}/{state.get('chapters_total')}")
print(f"  novel_score={state.get('novel_score')}")

if state.get("revision_cycle", 0) >= 1:
    print(f"\n  ✅✅✅ 全部 3 个 Bug 修复已生效! revision_cycle={state.get('revision_cycle')}")
    print(f"  ✅ Layer 1 验证通过 — 可以执行 Layer 2 (完整 5 步)")
else:
    print(f"\n  ❌ revision_cycle={state.get('revision_cycle')} — cycle 1 未完成")
    sys.exit(1)