# 5.7.6 Export 阶段中断→resume — 执行方案

> **来源**: [phase5_5.7_boundary_combination_plan.md](plans/phase5_5.7_boundary_combination_plan.md) §3.8
> **配置**: `total_chapters=2`, `max_revision_cycles=1`, `plateau_delta=10.0`
> **预估 API**: ~20 次（全部在 Step 1 的 F+D+R 中，Step 2 Export 零 API）
> **预估耗时**: ~20min

---

## 目的

验证 Export 作为只读阶段，中断后 `resume` 直接从 Export 开始（跳过 Foundation/Drafting/Revision），并完整产出 manuscript.md / arc_summary.md。

## 前置修复

[`pipeline_orchestrator.py:454`](pipeline_orchestrator.py:454) 已将 `run_adversarial_edit` 的 `max_tokens` 从 16000 → 4096，`max_total_time` 从 1200 → 600。

## 步骤拆解

### Step 1 — 完整跑完 Foundation → Drafting → Revision

```
state = default_state()
save_state(state)
state = run_foundation(state)    # ~7 次 API：world → chars → outline_vol → outline → outline_p2 → canon → voice → evaluate
state = run_drafting(state)      # ~6 次 API：ch_01 draft + eval, ch_02 draft + eval + canon更新
state = run_revision(state, max_cycles=1)  # ~5 次 API：adversarial(4096) + apply_cuts + reader_panel + gen_brief + revise
# run_revision 结尾设 phase="export"
save_state(state)
```

**关键边界**：`total_chapters=2`, `max_revision_cycles=1` — 只跑 1 轮修订。

### Step 2 — 验证中间状态

| 验证项 | 通过标准 |
|--------|----------|
| `state.phase` ∈ {"revision", "export"} | phase 已过 revision |
| `state.chapters_drafted == 2` | 精确等于 2 |

### Step 3 — 手动设 phase="export" + resume

```python
state["phase"] = "export"
save_state(state)
run_pipeline(mode="resume")
# PHASE_ORDER.index("export") = 3 → 只执行 run_export
```

### Step 4 — 验证最终状态

| # | 验证项 | 通过标准 |
|---|--------|----------|
| V1 | `state.phase = "complete"` | 最终 phase 正确 |
| V2 | `output/manuscript.md` 存在且非空 | 导出了合并手稿 |
| V3 | `output/arc_summary.md` 存在 | 导出了弧线摘要 |

## 风险点

| 风险 | 缓解 |
|------|------|
| `adversarial_edit` 再次超时 | 已修复 max_tokens=4096 |
| `run_revision` 在 single cycle 后 phase 可能不是 "export" | Step 3 手动设 phase 兜底 |
| API 网络波动 | 每步有 2 次 retry |

## 执行命令

```powershell
python tests/stage5_boundary_tests.py --live --test test_5_7_6_export_interrupt_resume
