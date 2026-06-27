#!/usr/bin/env python3
"""
5.7.5 多次中断串联 — 手动执行脚本 (保留中间产物用于诊断)

避免 tearDownClass 擦除证据。每步完成后写入 step<N>_snapshot.json 供诊断。
"""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from core.config import config, OUTPUT_DIR, CHAPTERS_DIR, STATE_FILE, CONFIG_FILE, RESULTS_FILE
from core.state_manager import default_state, load_state, save_state, parse_score

# ═══════════════════════════════════════════════════════════════
# 写配置（不依赖 MINIMAL_CONFIG_57 的缺键问题）
# ═══════════════════════════════════════════════════════════════
CONFIG_57_5 = {
    "story_summary": "2049年上海，程序员在维护老旧服务器时发现AI觉醒迹象，36小时倒计时。悬疑科幻风格，节奏紧凑。",
    "total_chapters": 4,
    "total_volumes": 2,
    "chapters_per_volume": 2,
    "max_foundation_iters": 1,
    "max_chapter_attempts": 1,
    "max_revision_cycles": 2,
    "foundation_threshold": 1.0,
    "chapter_threshold": 1.0,
    "plateau_delta": 999.0,
}
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
with open(CONFIG_FILE, "w", encoding="utf-8") as f:
    json.dump(CONFIG_57_5, f, indent=2, ensure_ascii=False)
config._loaded = False
config.load()
# 验证配置写入正确
c = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
assert c["total_chapters"] == 4, f"config.total_chapters={c['total_chapters']} != 4"
assert c["total_volumes"] == 2, f"config.total_volumes={c['total_volumes']} != 2"
print("✅ 配置写入正确: total_chapters=4, total_volumes=2")

from pipeline_orchestrator import run_foundation, run_revision, run_pipeline
from drafting.draft_chapter import draft_chapter
from evaluation.evaluate import evaluate_chapter

TOTAL = time.time()


def check(label, ok, detail=""):
    status = "✅" if ok else "❌"
    print(f"    {status} {label}: {detail}")
    return ok


def snapshot(step_num, state):
    """保存步骤快照。"""
    snap = dict(state)
    snap["_snapshot_step"] = step_num
    snap["_snapshot_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
    f = OUTPUT_DIR / f"step{step_num}_snapshot.json"
    f.write_text(json.dumps(snap, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  📸 快照已保存: {f.name}")


def verify_config():
    """验证 config.json 未被篡改。"""
    c = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    ok = c.get("total_chapters") == 4 and c.get("total_volumes") == 2
    if not ok:
        print(f"  ⚠ CONFIG CORRUPTED: total_chapters={c.get('total_chapters')}, total_volumes={c.get('total_volumes')}")
    return ok


# ═══════════════════════════════════════════════════════════════
# Step 1: Foundation → 中断1
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("  Step 1: Foundation 完整执行")
print("=" * 60)

t0 = time.time()
state = default_state()
state["chapters_total"] = 4  # 硬编码确保不被 config 污染
save_state(state)
state = run_foundation(state)
elapsed = time.time() - t0
print(f"  耗时: {elapsed/60:.1f}min")
print(f"  phase={state['phase']}, chapters_total={state.get('chapters_total')}, drafted={state.get('chapters_drafted')}")

# 中断1 验证
results1 = []
results1.append(check("Int1/phase=drafting", state.get("phase") == "drafting", f"phase={state.get('phase')}"))
results1.append(check("Int1/chapters_drafted=0", state.get("chapters_drafted") == 0, f"drafted={state.get('chapters_drafted')}"))
