# 【5.7.5 根因诊断】`run_revision` 共识修订阶段卡死问题 — 诊断方案

> **目的**: 定位 `run_revision` 在 2卷×4章 配置下共识修订阶段反复卡死的真因
> **背景**: 7次独立执行（含测试框架和独立脚本）均在 Revision cycle 1 共识修订阶段停止产出新输出
> **日期**: 2026-06-25
> **类型**: 真实 API 调用（需 API，~15次）
> **优先级**: 阻断 — 导致 5.7.5 无法完成

---

## 1. 已知事实

### 1.1 已排除的原因

| 原因 | 排除证据 |
|------|---------|
| 测试框架 tearDown 擦除证据 | 独立脚本（绕过测试框架）也在同一位置卡住 |
| `config.json` 被覆盖导致 `chapters_total=1` | 独立脚本显式加固 `state` + `config`，卡住时 state 已正确 (`chapters_total=4`) |
| `state.json` 被污染 | 独立脚本在每步显式加固，卡住时 state 正确 |
| `MINIMAL_CONFIG_57` 缺少 `total_chapters` | 独立脚本不依赖 `_write_config_57`，直接写文件 |

### 1.2 确认的代码路径

卡住点位于 [`run_revision`](pipeline_orchestrator.py:425) cycle 1 的内部循环中：

```
已完成:
  Step 1: 对抗性编辑 (4章) ✅
  Step 2: 机械裁剪 ✅
  Step 3: 读者评审团 (16次) ✅
  Step 5: 共识修订 (4章 × evaluate+generate_brief+revise+evaluate) ← ⚠️ 卡在这里

未到达:
  Step 6: 采样评估 line 683
  Step 6b: save_state line 829 (唯一写 revision_cycle 的位置)
```

### 1.3 完整的 cycle 1 API 调用清单

```
对抗性编辑:     4次 API  (retries=2, max_total_time=1200s/chapter)
读者评审团:     16次 API (retries=2, max_total_time=600s/batch)
共识修订(含摘要): ~16次 API (evaluate×4 + brief×4 + revise×4 + evaluate×4)
采样评估:       4次 API  (evaluate_chapter, retries=2, max_total_time=600s)
合并队列修订:   弱章数 × 3次 API
审阅修订闭环:   2 + 弱章数×3 + 4次 API
───────────────────────────────────────────
Cycle 1 总计:   ~48-56次 API
```

**关键**: `state["revision_cycle"]` 仅在 [line 829](pipeline_orchestrator.py:829) 写入 — 全部 48-56 次 API 完成后才能到达此代码。

---

## 2. 两个假说

### 假说 A: 共识修订的 `generate_brief()` 函数执行时间远超预期

[`build_auto_brief()`](revision/gen_brief.py:742) 调用 `latest_full_eval()` 查找 `eval_logs/` 中 `*_full.json` 文件。在共识修订阶段（Step 5），这个文件**不存在**（因为 `evaluate_full` 已从 `run_revision` 中删除，采样评估尚未执行）。

```python
# gen_brief.py:747-749
def build_auto_brief() -> tuple[int, str]:
    full_eval_path = latest_full_eval()
    if full_eval_path is None:
        sys.exit("错误: eval_logs/ 中未找到 *_full.json")  ← ⚠️ 直接 sys.exit!
```

**⚠️ 关键发现**: `generate_brief()` 如果 `latest_full_eval()` 返回 `None`，会直接调用 `sys.exit()` — **这会导致整个 Python 进程退出**，而不是抛异常。

### 假说 B: 共识修订的单章节 API 调用级联超时

每章 4 次 API（evaluate → revise → evaluate），每次最多 600-1200s 超时 + 2次重试。在最坏情况下，单章可能耗时 `(600×3 + 1200×3) = 90分钟`。4章总计可能 360 分钟。

---

## 3. 诊断步骤

### Step 1: 验证假说 A — 检查 `generate_brief()` 是否 `sys.exit()`

**操作**: 在独立脚本的 `run_revision` 调用前，预先创建 `eval_logs/` 中的 `_full.json` 文件。

```python
# 创建一个假的 _full.json 防止 sys.exit()
import json, time
from pathlib import Path
from core.config import EVAL_LOGS_DIR

dummy_eval = {
    "weakest_chapter": 1,
    "novel_score": 7.0,
    "weakest_dimension": "prose_quality",
    "top_suggestion": "测试占位",
}
ts = time.strftime("%Y%m%d_%H%M%S")
EVAL_LOGS_DIR.mkdir(parents=True, exist_ok=True)
(EVAL_LOGS_DIR / f"foundation_{ts}_full.json").write_text(
    json.dumps(dummy_eval, ensure_ascii=False), encoding="utf-8"
)
```

**通过标准**: 如果创建假文件后 `run_revision` 不再"卡死"（而是继续执行到采样评估），则假说 A 成立。

### Step 2: 验证假说 B — 仅跑共识修订的第一步

**操作**: 修改独立脚本，`run_revision` 之前预先创建假 `_full.json`，然后直接调用 `run_revision`。

如果假说 A 成立（`sys.exit` 是罪魁祸首），则修复方案是：在 `generate_brief` 调用前确保 `_full.json` 存在，或在 `gen_brief.py:748-749` 处将 `sys.exit` 改为抛异常。

### Step 3: 如果两个假说都排除 — 添加逐步日志

在独立脚本中添加每步 API 前后的时间戳输出，精确定位哪个 API 调用触发超时/卡死。

---

## 4. 执行计划

| # | 步骤 | 操作 | 预期结果 |
|---|------|------|---------|
| D1 | 杀旧进程 | `taskkill /F /IM python.exe` | 清理环境 |
| D2 | 创建假 `_full.json` | 在 `eval_logs/` 中写 dummy 文件 | 防止 `sys.exit()` |
| D3 | 准备章节文件 | 复用现有 4章（不重起草） | 节省 API |
| D4 | 设置 state | `phase=revision, revision_cycle=0, chapters_drafted=4` | 直接进 run_revision |
| D5 | 调用 `run_revision(state, max_cycles=1)` | 单次执行 | 观察是否到达 `save_state` |
| D6 | 检查结果 | 看 `state.json` 中 `revision_cycle` 是否变为 1 | 判断是否通过 |

---

## 5. 最小诊断脚本（待实现）

```python
#!/usr/bin/env python3
"""5.7.5 根因诊断脚本 — 隔离 run_revision 共识修订阶段"""
import json, sys, time
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from core.config import config, OUTPUT_DIR, EVAL_LOGS_DIR, CONFIG_FILE
from core.state_manager import load_state, save_state
from pipeline_orchestrator import run_revision

# 1. 设置 config
cfg = {
    "story_summary": "2049年上海...",
    "total_chapters": 4, "total_volumes": 2, "chapters_per_volume": 2,
    "max_revision_cycles": 1, "plateau_delta": 999.0,
    "chapter_threshold": 1.0, "foundation_threshold": 1.0,
    "max_foundation_iters": 1, "max_chapter_attempts": 1,
    "max_tokens_per_call": 16000,
}
with open(CONFIG_FILE, "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2)
config._loaded = False; config.load()

# 2. ★ 关键修复: 创建假 _full.json 防止 sys.exit()
ts = time.strftime("%Y%m%d_%H%M%S")
EVAL_LOGS_DIR.mkdir(parents=True, exist_ok=True)
dummy_eval = {
    "weakest_chapter": 1, "novel_score": 7.0,
    "weakest_dimension": "prose_quality",
    "top_suggestion": "测试占位",
}
(EVAL_LOGS_DIR / f"foundation_{ts}_full.json").write_text(
    json.dumps(dummy_eval, ensure_ascii=False), encoding="utf-8"
)
print(f"  ✓ 创建假 _full.json: foundation_{ts}_full.json")

# 3. State 加固
state = load_state()
state.update({
    "phase": "revision", "revision_cycle": 0,
    "chapters_drafted": 4, "chapters_total": 4,
    "total_volumes": 2, "chapters_per_volume": 2,
})
save_state(state)
print(f"  ✓ State: phase=revision, chapters=4/4")

# 4. 执行 run_revision
print(f"\n{'='*60}")
print("  运行 run_revision(max_cycles=1)...")
print(f"{'='*60}")
t0 = time.time()
try:
    state = run_revision(state, max_cycles=1)
except Exception as e:
    print(f"  ❌ 异常: {e}")
    import traceback; traceback.print_exc()

elapsed = time.time() - t0
print(f"\n  耗时: {elapsed/60:.1f}min")

# 5. 检查结果
state = load_state()
print(f"  phase={state.get('phase')}, revision_cycle={state.get('revision_cycle')}")
if state.get("revision_cycle", 0) >= 1:
    print("  ✅ 成功: revision_cycle 已更新")
else:
    print("  ❌ 失败: revision_cycle 仍为 0 (卡在共识修订阶段)")
```

---

## 6. 如果确认是 `sys.exit()` 的修复方案

**文件**: [`revision/gen_brief.py`](revision/gen_brief.py:742-754)

**修改**:

```python
def build_auto_brief() -> tuple[int, str]:
    full_eval_path = latest_full_eval()
    if full_eval_path is None:
        # ★ 不 sys.exit(), 而是抛异常让调用者处理
        raise FileNotFoundError(
            "eval_logs/ 中未找到 *_full.json — 请先执行 evaluate_full 或采样评估"
        )
    ...
```

**调用者端** ([`pipeline_orchestrator.py:742-751](pipeline_orchestrator.py:742)) 已有 `try/except` 兜底:

```python
try:
    ch, brief_text = build_auto_brief()
    ...
except Exception:  # ← 这个 except 会捕获 FileNotFoundError
    brief_content = (...)  # 兜底摘要
    brief_file.write_text(brief_content, encoding="utf-8")
```

但 `sys.exit()` **不在 `except Exception` 范围内** — `SystemExit` 继承自 `BaseException` 而非 `Exception`。

---

## 7. 通过标准

| 维度 | 标准 |
|------|------|
| 诊断执行 | 诊断脚本成功运行并输出 `revision_cycle` 状态 |
| 假说 A 确认 | 创建假 `_full.json` 后 `run_revision` 不再卡死 |
| 假说 B 确认 | 如果假说 A 不成立，逐步日志定位到具体 API 调用 |
| 修复方案 | 明确需要修改的文件和代码行 |