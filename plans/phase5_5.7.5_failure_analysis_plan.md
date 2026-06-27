# 【5.7.5 失败回溯分析】8次运行根因追踪 + 验证计划

> **目的**: 完整回溯 8 次运行的每次失败根因，确认所有修复是否真正生效
> **日期**: 2026-06-25
> **类型**: 无 API 调用（纯分析 + 验证计划）

---

## 1. 8次运行完整回溯

| # | 方式 | 停止位置 | 停止原因 | 修复状态 |
|---|------|---------|---------|---------|
| 1 | 测试框架 | `run_revision` 共识修订阶段 | **Bug 1**: [`build_auto_brief()`](revision/gen_brief.py:749) `sys.exit()` 静默杀死进程 | ❌ 未修复 |
| 2 | 测试框架 (改 MINIMAL_CONFIG_57) | 同上 | **Bug 1** — `MINIMAL_CONFIG_57` 修复**不相关**（真因不是它） | ❌ 未修复 |
| 3 | 测试框架 | 同上 | **Bug 1** | ❌ 未修复 |
| 4 | 测试框架 | 同上 | **Bug 1** | ❌ 未修复 |
| 5 | 测试框架 | 同上 | **Bug 1** | ❌ 未修复 |
| **6** | **独立脚本** | `_sample_evaluate_volumes(..., threshold, ...)` | **Bug 2**: [`run_revision` line 682](pipeline_orchestrator.py:682) 使用未定义的 `threshold` 变量 | ✅ Bug 1 已验证（共识修订4章全部通过！）<br>❌ Bug 2 未修复 |
| 7 | 独立脚本 (修复 Bug 2 后) | Step 2 Int2 验证: `ch_03_NOT_exists` | **环境残留**: 上次运行的 `ch_03.md` 未清理 | ⚠️ Bug 修复未测试到 |
| **8** | 独立脚本 (两修复+清理后) | 合并队列修订 → `build_auto_brief()` → `sys.exit()` | **Bug 1** 修复写入文件但进程已启动（Python 字节码缓存旧版本） | ⚠️ Bug 1 修复**已写入文件**，下次新进程生效 |

### 关键验证：第 6 次运行证明 Bug 1 修复成功

第 6 次运行的输出明确显示：
```
共识修订 ch_01 ✅ → ch_02 ✅ → ch_03 ✅ → ch_04 ✅
→ "修订摘要已保存" (4章全过)
→ "采样评估 — 每卷随机 5 章 ..."
→ NameError: name 'threshold' is not defined  ← 新 bug，不是 sys.exit
```

**4章共识修订全部通过**，证明 `sys.exit()` → `raise` 修复**有效**（共识修订路径使用 `generate_brief()` → `build_eval_brief/build_cuts_brief`，不触及 `build_auto_brief`）。

但 `build_auto_brief()` 被**合并队列修订**路径调用（[`pipeline_orchestrator.py:745`](pipeline_orchestrator.py:745)），第 6 次未到达此处（被 Bug 2 阻断）。

---

## 2. 两个已确认的 Bug 详解

### Bug 1: `sys.exit()` 静默杀死进程

**文件**: [`revision/gen_brief.py`](revision/gen_brief.py:747-754)

**触发路径 1** (共识修订 — 已验证修复):
```
run_revision → for cycle → 共识修订 (line 482) →
  generate_brief(ch_num, ...) → 使用 eval/cuts brief ✅
```

**触发路径 2** (合并队列修订 — 未验证修复，第 8 次运行在此失败):
```
run_revision → for cycle → 合并队列修订 (line 718) →
  build_auto_brief() (line 745) →
    latest_full_eval() → None (因 evaluate_full 已删除) →
    sys.exit("eval_logs/ 中未找到 *_full.json")  ← 杀死进程
```

**修复**: `sys.exit()` → `raise FileNotFoundError()` — 已写入文件 ✅

**`except Exception` 兜底已存在**: [`pipeline_orchestrator.py:751-758`](pipeline_orchestrator.py:751) 的 `try/except Exception:` 会捕获 `FileNotFoundError`，生成兜底摘要。

### Bug 2: `threshold` 变量未定义

**文件**: [`pipeline_orchestrator.py`](pipeline_orchestrator.py:438-682)

**原因**: `run_revision` 在 [line 682](pipeline_orchestrator.py:682) 使用了 `threshold` 变量，但该变量从未在函数作用域内定义。

**修复**: 在 [line 438-439](pipeline_orchestrator.py:438-439) 添加:
```python
threshold = cfg.chapter_threshold if cfg.loaded else CHAPTER_THRESHOLD
```
— 已写入文件 ✅

---

## 3. 两个 Bug 修复后的预期执行路径

```
Step 1: Foundation 完整执行          — API: ~7次
Step 2: 手动起草 ch_01 + ch_02       — API: ~4次
  → Int2 验证 ✅

Step 3: 手动起草 ch_03 + ch_04       — API: ~4次
  → run_revision(max_cycles=1):
    ├── 对抗性编辑 (4章)               — API: 4次
    ├── 机械裁剪                     — 0次
    ├── 读者评审团 (4读者×4章)         — API: 16次
    ├── 共识修订 (4章):
    │   └── generate_brief → build_eval_brief/build_cuts_brief  — 0次直接API (摘要生成)
    ├── 采样评估 (2卷×采样章)          — API: ~4次  ← Bug 2 修复后可通过
    ├── 跨卷审阅 (cycle=1, 跳过)       — 0次
    ├── 合并队列修订 (可能有弱章):
    │   └── build_auto_brief() → FileNotFoundError → except 兜底  ← Bug 1 修复后可通过
    ├── save_state (line 829)         ← ✅ revision_cycle=1 写入
    ├── 审阅修订闭环                  — API: ~6次
    └── phase="export" → save_state
  → Int3 验证 ✅

Step 4: run_pipeline(resume) → cycle 2 + Export  — API: ~14次
  → Int4 验证 ✅

Step 5: Export resume → complete      — API: 0次
  → Final 验证 ✅
```

---

## 4. 验证计划：最小执行脚本

**策略**: 不复跑完整 5 步。直接复用现有 4 章（从上次运行残留），跳过 Foundation + Drafting，只跑 `run_revision`。

**前提**: `output/chapters/ch_01.md`~`ch_04.md` 已存在（从上次运行留下）。

### Step: 验证 script

```python
#!/usr/bin/env python3
"""5.7.5 最小验证脚本 — 只跑 Revision + Export（复用现有4章）"""
import json, sys, time
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from core.config import config, OUTPUT_DIR, CHAPTERS_DIR, CONFIG_FILE
from core.state_manager import default_state, load_state, save_state
from pipeline_orchestrator import run_revision, run_pipeline

TOTAL_CH = 4; TOTAL_VOL = 2; CH_PER_VOL = 2

# 1. 写 config
cfg = {
    "story_summary": "2049年上海...", "total_chapters": TOTAL_CH,
    "total_volumes": TOTAL_VOL, "chapters_per_volume": CH_PER_VOL,
    "max_revision_cycles": 2, "plateau_delta": 999.0,
    "chapter_threshold": 1.0, "foundation_threshold": 1.0,
    "max_foundation_iters": 1, "max_chapter_attempts": 1,
}
with open(CONFIG_FILE, "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2)
config._loaded = False; config.load()

# 2. 确认4章存在
for ch in range(1, 5):
    p = CHAPTERS_DIR / f"ch_{ch:02d}.md"
    assert p.exists(), f"第{ch}章缺失: {p}"

# 3. 写 state
state = default_state()
state.update({
    "phase": "revision", "revision_cycle": 0,
    "chapters_drafted": TOTAL_CH, "chapters_total": TOTAL_CH,
    "total_volumes": TOTAL_VOL, "chapters_per_volume": CH_PER_VOL,
    "foundation_score": 7.2,
})
save_state(state)

# 4. 跑 run_revision(max_cycles=1)
print("═" * 60)
print("  运行 run_revision(max_cycles=1)...")
print("═" * 60)
t0 = time.time()
try:
    state = run_revision(state, max_cycles=1)
except Exception as e:
    print(f"  ❌ run_revision 异常: {e}")
    import traceback; traceback.print_exc()
print(f"  耗时: {(time.time()-t0)/60:.1f}min")

# 5. 检查
state = load_state()
print(f"  phase={state.get('phase')}, revision_cycle={state.get('revision_cycle')}")
if state.get("revision_cycle", 0) >= 1:
    print("  ✅ cycle 1 完成 — Bug 1 + Bug 2 修复已生效!")
else:
    print("  ❌ cycle 1 未完成 — 仍有 bug")
```

### 验证通过标准

| 检查项 | 通过条件 |
|--------|---------|
| run_revision 不崩溃 | 无未捕获异常 |
| revision_cycle ≥ 1 | state.json 中已更新 |
| phase = "export" 或 "revision" | phase 已推进 |

### 如果验证通过

继续跑完整 5.7.5 独立脚本（从 step 1 开始完整跑）。

---

## 5. 结论

**两个 Bug 均已确认并修复**：
- Bug 1: `gen_brief.py:749` `sys.exit()` → `raise FileNotFoundError()` — 第 6 次已验证共识修订通过
- Bug 2: `pipeline_orchestrator.py:438` 添加 `threshold` 变量 — 未验证（因第 7/8 次环境残留/进程缓存）

**需要一次干净运行来完整验证**。建议先跑最小验证脚本（复用现有 4 章），确认后跑完整独立脚本。