# Stage 4 E2E-1 插桩执行计划

> **父文档**: [enterprise_test_plan_stage4.md](enterprise_test_plan_stage4.md)  
> **版本**: v1.0  
> **日期**: 2026-06-27  
> **类型**: 真实 API 调用 — 单文件 `_run_stage4_e2e1.py`

---

## 1. 与 5.7.5 插桩脚本的关键差异

| 维度 | 5.7.5 插桩脚本 | E2E-1 插桩脚本 |
|------|---------------|---------------|
| 阈值 | `foundation_threshold=1.0`, `chapter_threshold=1.0`, `plateau_delta=999.0` | `foundation_threshold=7.5`, `chapter_threshold=6.0`, `plateau_delta=0.3` |
| 执行方式 | **5 步手动**：手动调用 run_foundation → 手动 draft_chapter(1) → draft_chapter(2) → … | **1 步全流水线**：`run_pipeline("from_scratch")` 一口气跑完 |
| 中断 | 有（4 次 state 回退模拟中断） | **无** — 纯 from_scratch 从头跑到尾 |
| 验证重点 | 中断恢复后 state 不漂移 | 正常阈值下质量循环不崩溃 |
| 步骤数 | 5 个大步骤 | 1 个大步骤（内部 Phase 1→2→3→4 由 pipeline 自动驱动） |
| 日志基础设施 | ✅ 成熟，直接复用 | ✅ 完全复用同一套 |

---

## 2. 日志基础设施（复用 5.7.5 模板）

```python
# ═══════════════════════════════════════════════════════════════
# 文件日志基础设施：同时写终端 + logs/debug.log，每行立即 flush
# ═══════════════════════════════════════════════════════════════
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)        # 需求4: 自动创建
LOG_FILE = LOG_DIR / "debug.log"
_fp_log = open(str(LOG_FILE), "a", encoding="utf-8", buffering=1)

def _write_log(line: str):
    """双写：终端 + 文件，立刻 flush——需求1+2"""
    sys.stdout.write(line)
    sys.stdout.flush()           # 需求2: 每行 flush
    _fp_log.write(line)
    _fp_log.flush()              # 需求2: 每行 flush
```

**四个需求全部满足**：
- 需求1: 所有日志 `_write_log` 同时写终端和 `logs/debug.log` ✅
- 需求2: 每行 `sys.stdout.flush()` + `_fp_log.flush()` ✅
- 需求3: 顶层 `try/except` → `[CRASH]` 格式写入 `logs/debug.log` ✅
- 需求4: `LOG_DIR.mkdir(parents=True, exist_ok=True)` ✅

---

## 3. 配置

```python
STAGE4_E2E1_CONFIG = {
    "story_summary": "2049年上海，程序员在维护老旧服务器时发现AI觉醒迹象，36小时倒计时。悬疑科幻风格，节奏紧凑。",
    "total_chapters": 3,
    "total_volumes": 1,
    "chapters_per_volume": 3,
    # ★ 正常质量阈值（与 5.7.x 的本质差异）
    "foundation_threshold": 7.5,
    "chapter_threshold": 6.0,
    "max_foundation_iters": 3,
    "max_chapter_attempts": 3,
    "max_revision_cycles": 3,
    "plateau_delta": 0.3,
}
```

---

## 4. 插桩点设计

E2E-1 不像 5.7.5 那样手动操控每一步，而是依赖 `run_pipeline("from_scratch")` 自动驱动。因此插桩策略是：

### 4.1 在 pipeline_orchestrator.py 的每个 Phase 函数关键行插入日志

**不修改业务逻辑**，仅在以下位置插入 `_write_log` 调用（通过 monkey-patch `step()` 函数实现）：

| 插桩点 | 位置 | 记录内容 |
|--------|------|---------|
| Phase 1 每次迭代开始 | [`run_foundation:82`](pipeline_orchestrator.py:82) | `iteration i/max_iters`, foundation 文件列表 |
| Phase 1 评分结果 | [`run_foundation:145`](pipeline_orchestrator.py:145) | `score`, `best_score`, `keep/discard` |
| Phase 1 git_reset_hard | [`run_foundation:160`](pipeline_orchestrator.py:160) | `discard — score <= best_score` |
| Phase 2 每章开始 | [`run_drafting:207`](pipeline_orchestrator.py:207) | `chapter ch/total, attempt N/max` |
| Phase 2 评分 | [`run_drafting:236`](pipeline_orchestrator.py:236) | `score`, `slop_penalty`, `keep/discard` |
| Phase 2 反套话触发 | [`run_drafting:239`](pipeline_orchestrator.py:239) | `slop_fail`, 重写触发 |
| Phase 2 反模式触发 | [`run_drafting:296`](pipeline_orchestrator.py:296) | `warning_count >= antipattern_max`, 重写触发 |
| Phase 2 增量 canon | [`run_drafting:319-321`](pipeline_orchestrator.py:319) | `+N 条新事实` |
| Phase 2 state 快照 | 每章通过后 | `chapters_drafted`, `canon_entry_count` |
| Phase 3 每轮开始 | [`run_revision:450`](pipeline_orchestrator.py:450) | `cycle N/max_cycles`, 当前 novel_score |
| Phase 3 采样评估 | [`run_revision:682-686`](pipeline_orchestrator.py:682) | `sample_weaks` 弱章列表 |
| Phase 3 跨卷审阅 | [`run_revision:690-694`](pipeline_orchestrator.py:690) | `cross_broken` 或 "跳过"（单卷） |
| Phase 3 合并修订队列 | [`run_revision:705-709`](pipeline_orchestrator.py:705) | `combined_targets` |
| Phase 3 全文评估 | [`run_revision:805-813`](pipeline_orchestrator.py:805) | `novel_score`, `prev_score`, 总字数 |
| Phase 3 平台期检测 | [`run_revision:827-830`](pipeline_orchestrator.py:827) | `delta < plateau_delta → break` 或 `继续` |
| Phase 3b 审阅开始 | [`run_revision:1076`](pipeline_orchestrator.py:1076) | `审阅轮次` |
| Phase 4 导出 | [`run_export:1098`](pipeline_orchestrator.py:1098) | 每个子步骤完成 |
| 全局 KeyboardInterrupt | [`run_pipeline:1216-1219`](pipeline_orchestrator.py:1216) | 状态已保存 |
| 全局 Exception | [`run_pipeline:1220-1225`](pipeline_orchestrator.py:1220) | 阶段、异常详情 |

### 4.2 插桩方式：Monkey-patch `step()` + `banner()`

不修改 `pipeline_orchestrator.py` 源码，而是在 `_run_stage4_e2e1.py` 启动时 monkey-patch `pipeline_orchestrator.step` 和 `pipeline_orchestrator.banner`：

```python
# 替换 step/banner 函数，自动记录所有日志到 debug.log
import pipeline_orchestrator as po
_original_step = po.step
_original_banner = po.banner

def _instrumented_step(msg):
    _write_log(f"  [PIPELINE] {msg}\n")
    _original_step(msg)   # 保留原行为

def _instrumented_banner(msg, char="="):
    _write_log(f"\n  [PIPELINE BANNER] {msg}\n")
    _original_banner(msg, char)

po.step = _instrumented_step
po.banner = _instrumented_banner
```

**效果**：流水线的每一行 `step()` 和 `banner()` 输出都会被同时写入终端和 `logs/debug.log`，实现运行时全程日志记录。

---

## 5. 脚本骨架

```python
#!/usr/bin/env python3
"""Stage 4 E2E-1: 3章正常阈值 from_scratch — 全流程插桩执行"""

import json, sys, time, traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ═══ 日志基础设施（复用 5.7.5 模板）═══
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "debug.log"
_fp_log = open(str(LOG_FILE), "a", encoding="utf-8", buffering=1)

def _write_log(line: str):
    sys.stdout.write(line); sys.stdout.flush()
    _fp_log.write(line); _fp_log.flush()

def _now_ts() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]

from core.config import config, OUTPUT_DIR, CHAPTERS_DIR, CONFIG_FILE, STATE_FILE, RESULTS_FILE
from core.state_manager import default_state, load_state, save_state
from pipeline_orchestrator import run_pipeline

# ═══ 配置 ═══
CONFIG_E2E1 = {...}  # 见第3节

# ═══ 插桩工具 ═══
STEP_COUNTER = [0]
def instep(label): ...
def inlog(msg): ...
def inerr(msg): ...
def inok(msg): ...
def snap(step_name): ...
def safe_call(label, fn, *args, **kwargs): ...
def verify_condition(label, cond, detail=""): ...
def file_check(path, label, min_size=100): ...

# ═══ monkey-patch pipeline_orchestrator 的 step/banner ═══
def _patch_pipeline_logging():
    import pipeline_orchestrator as po
    # 替换 step/banner，双写所有日志
    ...

# ═══ 主流程 ═══
def main():
    t_global = time.time()
    
    # header
    _write_log("=" * 70 + "\n")
    _write_log("  Stage 4 E2E-1: 3章正常阈值 from_scratch\n")
    _write_log(f"  配置: foundation_threshold=7.5, chapter_threshold=6.0, plateau_delta=0.3\n")
    _write_log(f"  日志文件: {LOG_FILE}\n")
    _write_log("=" * 70 + "\n")
    
    try:
        # ── 初始化 ──
        instep("初始化: 清理 + 写入正常阈值配置")
        clean_output()
        write_e2e1_config()
        inok("配置和 state 已就绪")
        snap("初始")
        
        # ── 核心: 全流水线 from_scratch ──
        instep("═══ 启动全流水线 from_scratch ═══")
        _patch_pipeline_logging()    # monkey-patch step/banner
        run_pipeline("from_scratch")
        inok("run_pipeline 正常返回")
        
        # ── 验证 ──
        instep("═══ 验证产出 ═══")
        all_ok = True
        # A1-A6, B*, C* 验证...
        
        show_summary(t_global, success=all_ok)
    
    except Exception as e:
        # ── 顶层崩溃捕获（需求3）──
        total_elapsed = time.time() - t_global
        crash_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _write_log("\n" + "=" * 70 + "\n")
        _write_log(f"  [CRASH] 崩溃时间：{crash_ts}\n")
        _write_log(f"  [CRASH] 崩溃原因：{type(e).__name__}: {e}\n")
        _write_log("=" * 70 + "\n")
        # 崩溃时的 state
        try:
            crash_s = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            _write_log(f"  [CRASH] 崩溃时的state：phase={crash_s.get('phase')} drafted={crash_s.get('chapters_drafted')}/{crash_s.get('chapters_total')} cycle={crash_s.get('revision_cycle')} score={crash_s.get('novel_score','?')}\n")
        except Exception:
            _write_log("  [CRASH] 崩溃时的state：无法读取 state.json\n")
        _write_log("  [CRASH] 完整调用栈：\n")
        for line in traceback.format_exc().strip().split("\n"):
            _write_log(f"    {line}\n")
        _write_log(f"\n  总耗时: {total_elapsed/60:.1f}min\n")
        _write_log("=" * 70 + "\n")
    
    finally:
        _fp_log.close()
        sys.stdout.write(f"\n  日志已保存至: {LOG_FILE}\n")
        sys.stdout.flush()
```

---

## 6. 执行命令

```bash
python _run_stage4_e2e1.py
```

单文件，无参数，配置硬编码在脚本中（确保可复现）。

---

## 7. 日志输出示例

```
======================================================================
  Stage 4 E2E-1: 3章正常阈值 from_scratch
  配置: foundation_threshold=7.5, chapter_threshold=6.0, plateau_delta=0.3
  日志文件: logs/debug.log
======================================================================

──────────────────────────────────────────────────────────────────────
  [INSTR #1] 14:32:01.234  初始化: 清理 + 写入正常阈值配置
──────────────────────────────────────────────────────────────────────
  [INSTR ✅] 14:32:01.345  output/ 已清理
  [INSTR ✅] 14:32:01.346  config.json 已写入: total_chapters=3, threshold=7.5/6.0
  [INSTR LOG] 14:32:01.347  SNAP [初始]: phase=foundation drafted=0/3 cycle=0 score=0.0

──────────────────────────────────────────────────────────────────────
  [INSTR #2] 14:32:01.348  ═══ 启动全流水线 from_scratch ═══
──────────────────────────────────────────────────────────────────────
  [PIPELINE BANNER] ═══ PHASE 1: FOUNDATION (基础构建) ═══
  [PIPELINE] 基础构建 迭代 1/3
  [PIPELINE] 生成世界观 world.md ...
  [PIPELINE] 生成角色 characters.md ...
  [PIPELINE] 生成卷级总纲 outline_volume.md ...
  [PIPELINE] 生成大纲 outline.md (Part 1) ...
  [PIPELINE] 生成大纲 outline.md (Part 2 - 伏笔账本) ...
  [PIPELINE] 生成正典 canon.md ...
  [PIPELINE] 正典条目数: 287 (世界观120 + 角色98 + 时间线45 + 规则24)
  [PIPELINE] ⚠ 警告: 正典条目 287 < 400，信息密度不足，将在评估中体现
  [PIPELINE] 生成文风指纹 voice.md Part 2 ...
  [PIPELINE] 评估基础构建 ...
  [PIPELINE] 基础构建评分: 6.8  (lore: 7.2, 历史最佳: 0.0)
  [PIPELINE] 评分未提升 (6.8 <= 0.0)，丢弃     ← ★ 质量循环路径被覆盖！
  
  [PIPELINE BANNER] 基础构建 迭代 2/3
  ...
```

如果崩溃：

```
======================================================================
  [CRASH] 崩溃时间：2026-06-27 14:45:32
  [CRASH] 崩溃原因：RuntimeError: API 调用全部重试耗尽
======================================================================
  [CRASH] 崩溃时的state：phase=drafting drafted=1/3 cycle=0 score=0.0
  [CRASH] 完整调用栈：
    Traceback (most recent call last):
      File "_run_stage4_e2e1.py", line XXX, in main
        run_pipeline("from_scratch")
      ...
  ======================================================================
```

---

## 8. 验证清单映射

| 验证项 | 在脚本中的实现 |
|--------|--------------|
| A1 Foundation 文件产出 | `file_check(OUTPUT_DIR / "world.md", ...)` × 5 |
| A2 章节文件产出 | `file_check(CHAPTERS_DIR / f"ch_{ch:02d}.md", ...)` × 3 |
| A3 manuscript.md | `file_check(OUTPUT_DIR / "manuscript.md", ...)` |
| A4 state.json | `state["phase"] == "complete"`, `chapters_drafted == 3` |
| A5 results.tsv | `file_check(RESULTS_FILE, ...)` + 解析关键列 |
| A6 零崩溃 | 顶层 try/except 捕获 → 若无 [CRASH] 输出即为通过 |
| B1 Foundation 重试 | 日志中搜索 "迭代 2/" 或 discard 记录 |
| B2 章节重试 | `results.tsv` 中 search discard 行 |
| B3 canon 警告 | 日志中搜索 "⚠ 警告: 正典条目" |
| B4 平台期 | `state["revision_cycle"]` 值 |
| C1 增量 canon | `state["canon_entry_count"]` 增长 |
| C2 文风指纹 | 日志中搜索 "文风指纹" |
| C3 反模式审计 | 日志中搜索 "结构反模式" |
| C4 results.tsv 完整 | TSV 逐行验证 |