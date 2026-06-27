# 3.E2E 端到端串联 — 详细测试方案

> 版本：v1.0
> 日期：2026-06-22
> 目标：Phase 1→2→3→4 完整流水线串联执行一次，验证全流程零崩溃、零中断
> 策略：**单次 from_scratch 执行 + 全产出验证**
> 配置：`total_chapters=3`, `total_volumes=1`, `max_foundation_iters=1`, `max_revision_cycles=1`, `model=deepseek-ai/DeepSeek-V4-Flash`
> 通过标准：exit 0 + phase=complete + 所有 4 个 Phase 产出完整

---

## 前置条件

### 环境要求

| 配置项 | 值 |
|--------|-----|
| Python | ≥ 3.9 |
| API 端点 | 硅基流动 `https://api.siliconflow.cn/v1` |
| 写作模型 | `deepseek-ai/DeepSeek-V4-Flash` |
| 裁判模型 | 同写作模型 |
| 故事梗概 | `2049年上海，程序员在维护老旧服务器时发现AI觉醒迹象，36小时倒计时` |
| API 间隔 | ≥ 4 秒 |
| total_chapters | 3 |
| total_volumes | 1 |
| max_foundation_iters | 1 |
| max_revision_cycles | 1 |

### 依赖

| 依赖项 | 说明 |
|--------|------|
| `.env` 配置 | `AUTONOVEL_API_KEY` 有效（非占位符） |
| `output/config.json` | 需由测试脚本覆写（含 `story_summary` + `total_chapters=3`） |
| `output/` 目录 | 测试前清空（保留 `.env` 和 `config.json` 由脚本管理） |

---

## 目标代码分析

### 流水线核心路径

```
run_pipeline("from_scratch")
    │
    ├─ state = default_state()
    ├─ save_state(state)
    │
    ├─ for phase in PHASE_ORDER:
    │   ├── "foundation" → run_foundation(state)
    │   ├── "drafting"   → run_drafting(state)
    │   ├── "revision"   → run_revision(state, max_cycles=1)
    │   └── "export"     → run_export(state)
    │
    ├─ KeyboardInterrupt → save_state + exit(130)
    ├─ Exception         → save_state + raise
    │
    └─ [DONE] → 打印统计
```

### 各 Phase 关键模块与产出

| Phase | 入口函数 | 关键子模块 | 产出文件 |
|-------|---------|-----------|---------|
| **Foundation** | [`run_foundation()`](pipeline_orchestrator.py:58) | `gen_world` → `gen_characters` → `gen_outline_volume` → `gen_outline` → `gen_outline_part2` → `gen_canon` → `gen_voice` → `evaluate_foundation` | `world.md`, `characters.md`, `outline_volume.md`, `outline.md`, `canon.md`, `voice.md` |
| **Drafting** | [`run_drafting()`](pipeline_orchestrator.py:145) | `draft_chapter` × 3 → `evaluate_chapter` × 3 → `update_canon` × 3 → `voice_fingerprint` × 3 → `antipatterns` × 3 | `ch_01.md` ~ `ch_03.md`, `eval_logs/`, `edit_logs/` |
| **Revision** | [`run_revision()`](pipeline_orchestrator.py:425) | `adversarial_edit` → `apply_cuts` → `reader_panel` → `gen_brief` → `gen_revision` → `evaluate_chapter` → `evaluate_full` | 修订后的 `ch_*.md`, `briefs/`, `edit_logs/reader_panel.json` |
| **Export** | [`run_export()`](pipeline_orchestrator.py:1101) | `build_outline` → `build_arc_summary` → `build_manuscript` | `outline.md`(重建), `arc_summary.md`, `manuscript.md` |

### 阶段失败模式

| 阶段 | 致命失败点 | 行为 |
|------|-----------|------|
| Foundation | `evaluate_foundation()` 分数持续 < threshold 且达到 `max_foundation_iters` | 循环退出但不抛异常（`state["foundation_score"]` 低） |
| Foundation | LLM 调用 3 次重试全部失败 | `retries=3` 耗尽后 `raise RuntimeError`，`run_pipeline` 捕获后 `save_state` + `raise` |
| Drafting | 单章起草 `draft_chapter` 3 次重试失败 | `chapter_attempt >= MAX_CHAPTER_ATTEMPTS` 则跳过该章继续 |
| Revision | `evaluate_full()` 超时 | `try/except` 包裹，不阻塞 |
| Export | `build_outline` / `build_arc_summary` LLM 调用失败 | `try/except` 包裹，打印跳过信息继续 |

**关键发现**：仅有 Foundation 阶段的 LLM 重试耗尽会导致流水线崩溃。Drafting/Revision/Export 均为容错设计。

---

## 测试总览

```mermaid
flowchart TD
    subgraph E2E["3.E2E 端到端串联 — ~25-30 次 API"]
        PREP["前置: 备份 output/ + 写入 config.json"]
        RUN["执行: pipeline_orchestrator --mode from_scratch"]
        V1["验证: Foundation 产出 (6 文件)"]
        V2["验证: Drafting 产出 (3 章 + eval_logs)"]
        V3["验证: Revision 产出 (修订记录)"]
        V4["验证: Export 产出 (3 文件)"]
        V5["验证: State + Results 完整性"]
    end

    PREP --> RUN --> V1 --> V2 --> V3 --> V4 --> V5
```

---

## 3.E2E.1 完整 3 章 from_scratch 流水线

> 验证：Phase 1→2→3→4 全流程零崩溃执行
> API 调用：~25-30 次
> 前置：`.env` 配置有效，`output/` 已清空

| 项目 | 内容 |
|------|------|
| **测试方法** | `python pipeline_orchestrator.py --mode from_scratch` |
| **前置条件** | |
| | — `.env` 中 `AUTONOVEL_API_KEY` 有效 |
| | — `output/config.json` 已写入（含 `story_summary` + `total_chapters=3`） |
| | — `output/` 目录中无旧 state/章节文件（避免 resume 误判） |
| | — `output/state.json` 为 `default_state()` |
| **配置** | `total_chapters=3`, `total_volumes=1`, `max_foundation_iters=1`, `max_revision_cycles=1`, `foundation_threshold=1.0`, `chapter_threshold=1.0` |
| **验证点** | |
| | (A) **退出码**：`exit 0` |
| | (B) **Foundation**：`world.md`、`characters.md`、`outline_volume.md`、`outline.md`、`canon.md`、`voice.md` 全部存在且 > 100 bytes |
| | (C) **Drafting**：`ch_01.md` ~ `ch_03.md` 全部存在且每章 > 200 字 |
| | (D) **Revision**：`eval_logs/full_*.json` ≥ 1 个，`edit_logs/reader_panel.json` 存在 |
| | (E) **Export**：`manuscript.md` 含 3 章目录 + 分隔符；`arc_summary.md` 含四个章节；`outline.md` 已重建 |
| | (F) **State**：`phase="complete"`, `chapters_drafted==3`, `novel_score>0` |
| | (G) **Results**：`results.tsv` 含 foundation → drafting → revision → export 四阶段记录 |
| | (H) **无崩溃**：stdout/stderr 中无 `❌ 阶段 xxx 致命错误` 和未捕获 traceback |
| **API 调用计数** | ~25-30 次 |
| **预期行为** | 全流程零 BUG 跑完，所有产出完整 |

### 配置参数

```python
E2E_CONFIG = {
    "story_summary": (
        "一个年轻程序员在2049年的上海发现自己写的AI系统已经觉醒，"
        "他必须在36小时内找到并解除它，否则它将接管全球网络。"
        "悬疑科幻风格，节奏紧凑。"
    ),
    "total_chapters": 3,
    "total_volumes": 1,
    "chapters_per_volume": 3,
    "max_foundation_iters": 1,
    "max_revision_cycles": 1,
    "max_revision_rounds": 3,
    "foundation_threshold": 1.0,
    "chapter_threshold": 1.0,
    "revision_threshold": 1.0,
    "plateau_delta": 0.5,
    "max_chapter_attempts": 1,
}
```

### 验证逻辑伪代码

```python
def test_3_e2e_1_full_pipeline(self):
    """3.E2E.1 完整 3 章 from_scratch 流水线"""

    # ——— 前置 ———
    # 清空 output/（保留 .env）
    _clean_output_for_e2e()

    # 写入配置
    _write_e2e_config(E2E_CONFIG)

    # 重置 state
    from core.state_manager import save_state, default_state
    save_state(default_state())

    # ——— 执行 ———
    start = time.time()
    result = subprocess.run(
        [sys.executable, str(ROOT / "pipeline_orchestrator.py"),
         "--mode", "from_scratch"],
        cwd=str(ROOT),
        capture_output=True, text=True, timeout=1800,  # 30min
    )
    elapsed = time.time() - start
    combined_output = result.stdout + "\n" + result.stderr

    # ——— 验证 ———
    results = []

    # (A) 退出码
    results.append(("exit_code", result.returncode == 0,
                    f"exit={result.returncode} ({elapsed/60:.1f}min)"))

    # (B) Foundation 产出
    foundation_files = [
        ("world.md", 100), ("characters.md", 100),
        ("outline_volume.md", 100), ("outline.md", 100),
        ("canon.md", 100), ("voice.md", 100),
    ]
    for fname, min_b in foundation_files:
        path = OUTPUT_DIR / fname
        ok = path.exists() and path.stat().st_size >= min_b
        results.append((f"Foundation/{fname}", ok,
                        f"{path.stat().st_size}B" if path.exists() else "MISSING"))

    # (C) Drafting 产出
    for ch in range(1, 4):
        ch_path = CHAPTERS_DIR / f"ch_{ch:02d}.md"
        ok = ch_path.exists()
        if ok:
            text = ch_path.read_text(encoding="utf-8")
            chars = len(text.replace(" ", "").replace("\n", ""))
            ok = chars >= 200
            detail = f"{chars} 字"
        else:
            detail = "MISSING"
        results.append((f"Drafting/ch_{ch:02d}.md", ok, detail))

    # (D) Revision 产出
    eval_full_files = sorted(EVAL_LOGS_DIR.glob("full_*.json"))
    results.append(("Revision/eval_full", len(eval_full_files) >= 1,
                    f"{len(eval_full_files)} files"))
    rp_path = EDIT_LOGS_DIR / "reader_panel.json"
    results.append(("Revision/reader_panel", rp_path.exists(),
                    "OK" if rp_path.exists() else "MISSING"))

    # (E) Export 产出
    ms_path = OUTPUT_DIR / "manuscript.md"
    if ms_path.exists():
        ms_text = ms_path.read_text(encoding="utf-8")
        ms_ok = "目录" in ms_text and len(ms_text) > 500
        results.append(("Export/manuscript.md", ms_ok,
                        f"{len(ms_text)} chars"))
    else:
        results.append(("Export/manuscript.md", False, "MISSING"))

    arc_path = OUTPUT_DIR / "arc_summary.md"
    if arc_path.exists():
        arc_text = arc_path.read_text(encoding="utf-8")
        arc_ok = "角色弧线" in arc_text and len(arc_text) > 100
        results.append(("Export/arc_summary.md", arc_ok,
                        f"{len(arc_text)} chars"))
    else:
        results.append(("Export/arc_summary.md", False, "MISSING"))

    # (F) State
    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    results.append(("State/phase=complete", state.get("phase") == "complete",
                    f"phase={state.get('phase')}"))
    results.append(("State/chapters_drafted=3",
                    state.get("chapters_drafted") == 3,
                    f"drafted={state.get('chapters_drafted')}"))
    results.append(("State/novel_score>0",
                    state.get("novel_score", 0) > 0,
                    f"score={state.get('novel_score')}"))

    # (G) Results
    if RESULTS_FILE.exists():
        tsv = RESULTS_FILE.read_text(encoding="utf-8")
        lines = tsv.strip().split("\n")
        has_export = "export" in tsv
        results.append(("Results/tsv", len(lines) >= 4 and has_export,
                        f"{len(lines)} rows, export={'Y' if has_export else 'N'}"))

    # (H) 无崩溃
    has_crash = "❌ 阶段" in combined_output
    results.append(("No crash", not has_crash,
                    "CRASH DETECTED" if has_crash else "clean"))

    # 汇总
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"\n  {passed}/{total} 验证通过")
    self.assertEqual(passed, total,
                     f"{total - passed} 项未通过: "
                     + "; ".join(n for n, ok, _ in results if not ok))
```

---

## 3.E2E.2 串联前后数据完整性对比

> 验证：流水线执行前后 output/ 目录的文件变更可追溯，无意外文件删除
> API 调用：0（文件统计）
> 前置：3.E2E.1 已执行

| 项目 | 内容 |
|------|------|
| **测试方法** | 记录执行前 `output/` 文件清单 → 执行后对比 → 验证预期新增/覆写/保留 |
| **前置条件** | 3.E2E.1 已执行 |
| **验证点** | |
| | (a) Foundation 文件存在（执行前不存在 → 执行后存在） |
| | (b) 章节文件 3 个（执行前不存在 → 执行后存在） |
| | (c) 导出文件 3 个（执行前不存在 → 执行后存在） |
| | (d) `state.json` 从 default → complete |
| | (e) `results.tsv` 从不存在/空 → ≥ 10 行 |
| | (f) `config.json` 保留（仅覆写，不删除） |
| | (g) 无意外残留文件 |
| **API 调用计数** | 0 |
| **预期行为** | 文件变更与流水线阶段一一对应 |

### 验证逻辑伪代码

```python
def test_3_e2e_2_output_integrity(self):
    """前后数据完整性对比"""
    # 统计各子目录文件数
    dirs = {
        "chapters": CHAPTERS_DIR,
        "eval_logs": EVAL_LOGS_DIR,
        "edit_logs": EDIT_LOGS_DIR,
        "briefs": BRIEFS_DIR,
    }
    for name, d in dirs.items():
        count = len(list(d.glob("*"))) if d.exists() else 0
        print(f"  {name}/: {count} files")

    # 验证 config.json 未被删除
    self.assertTrue(CONFIG_FILE.exists(), "config.json 缺失")

    # 验证关键产出存在
    critical = [
        OUTPUT_DIR / "world.md",
        OUTPUT_DIR / "manuscript.md",
        OUTPUT_DIR / "arc_summary.md",
        OUTPUT_DIR / "state.json",
        OUTPUT_DIR / "results.tsv",
    ]
    for p in critical:
        self.assertTrue(p.exists(), f"{p.name} 缺失")
```

---

## 3.E2E.3 流水线日志完整性

> 验证：stdout 输出包含所有 4 个 Phase 的 banner 和完成标记
> API 调用：0（日志分析）
> 前置：3.E2E.1 已执行

| 项目 | 内容 |
|------|------|
| **测试方法** | 解析 subprocess 捕获的 stdout，逐一验证 Phase 标记出现 |
| **前置条件** | 3.E2E.1 已执行（日志已保存在测试对象中） |
| **验证点** | |
| | (a) `PHASE 1: FOUNDATION (基础构建)` banner 出现 |
| | (b) `PHASE 2: DRAFTING (章节起草)` banner 出现 |
| | (c) `PHASE 3: REVISION (修订)` banner 出现 |
| | (d) `PHASE 4: EXPORT (导出)` banner 出现 |
| | (e) `[DONE] 流水线完成！` 出现 |
| | (f) 手稿位置路径出现在日志中 |
| | (g) 无 `❌ 阶段` 致命错误信息 |
| | (h) 无 Python traceback（`Traceback (most recent call last)`） |
| **API 调用计数** | 0 |
| **预期行为** | 4 个 Phase 顺次执行，最后 [DONE] 完成 |

---

## 3.E2E.4 字数/评分/耗时合理性

> 验证：产出字数、小说评分、总耗时在合理区间内
> API 调用：0（统计验证）
> 前置：3.E2E.1 已执行

| 项目 | 内容 |
|------|------|
| **测试方法** | 读取 `state.json` + `results.tsv` + 实际文件字数统计，与预期区间比较 |
| **前置条件** | 3.E2E.1 已执行 |
| **验证点** | |
| | (a) 总字数 ≥ 3000 字（3 章 × ≥ 1000 字/章） |
| | (b) `novel_score` > 0（评分非零） |
| | (c) `foundation_score` > 0 或 foundation 至少执行了 1 轮 |
| | (d) 总耗时 ≤ 30 分钟（3 章配置上限） |
| | (e) `revision_cycle` ≥ 1（至少执行了 1 轮修订） |
| | (f) `results.tsv` 中实验记录 ≥ 8 行 |
| **API 调用计数** | 0 |
| **预期行为** | 所有指标在合理范围内 |

---

## API 调用预算汇总

| 测试项 | API 调用 | 说明 |
|--------|---------|------|
| 3.E2E.1 完整流水线(含子进程) | ~25-30 | Foundation(8-9) + Drafting(6-9) + Revision(8-12) + Export(2-3) |
| 3.E2E.2 数据完整性 | 0 | 复用 3.E2E.1 产出 |
| 3.E2E.3 日志完整性 | 0 | 复用 3.E2E.1 日志 |
| 3.E2E.4 字数/评分/耗时 | 0 | 复用 3.E2E.1 产出 |
| **合计** | **~25-30** | |

---

## 门禁标准

| 门禁项 | 标准 | 不通过时禁止进入 |
|--------|------|---------------|
| 3.E2E.1 | exit 0 + phase=complete + 全产出完整 | Stage 4 |
| 3.E2E.2 | 所有必需文件存在，config.json 未删除 | Stage 4 |
| 3.E2E.3 | 4 Phase banner + [DONE] + 无崩溃 | Stage 4 |
| 3.E2E.4 | 字数 ≥ 3000, score > 0, 耗时 ≤ 30min | Stage 4 |
| **3.E2E 汇总** | **全部 4 项通过，零崩溃** | **Stage 4** |

---

## 风险与缓解

| 风险 | 严重度 | 缓解措施 |
|------|--------|---------|
| API 调用费用超预期（~30 次 ≈ ¥0.30） | 低 | 使用 `--max-cycles 1` 限制修订轮数；`max_foundation_iters=1` 限制重试 |
| 网络中断导致 `RuntimeError` | 🔴 高 | 测试前确认 API 端点可达；发生中断后 state 已保存，可 resume |
| `evaluate_foundation` 解析失败导致分数为 0 | 🟡 中 | `parse_score` 回退 -1.0，`foundation_threshold=1.0` 确保低分不无限循环 |
| Git commit 失败（无 .git 目录） | 🟢 低 | `state_manager` 自动检测并切换到文件快照模式 |
| 子进程超时 | 🟡 中 | 设置 30 分钟 timeout；3 章流水线通常在 15-20 分钟内完成 |

---

## 执行顺序

```
3.E2E.1 完整流水线
    │  ← 唯一需要 API 调用的测试项（~25-30 次）
    │  ← 耗时 ~15-20 分钟
    │
    ├── 3.E2E.2 数据完整性   ← 依赖 3.E2E.1
    ├── 3.E2E.3 日志完整性   ← 依赖 3.E2E.1
    └── 3.E2E.4 字数/评分/耗时 ← 依赖 3.E2E.1
```

### 推荐执行策略

1. **确认 API Key + 配额** — 至少 ¥0.50 余额
2. **备份当前 `output/`** — `robocopy output output_backup /E`
3. **配置写入** — 测试脚本自动覆写 `output/config.json`
4. **执行 3.E2E.1** — 约 15-20 分钟
5. **并行执行 3.E2E.2/3.E2E.3/3.E2E.4** — 纯文件/日志分析，秒级完成

---

## 测试脚本模板

```python
#!/usr/bin/env python3
"""
Stage 3 Phase 3.E2E 集成测试 — 端到端串联

Phase 1→2→3→4 完整流水线串联执行一次。
真实 API 调用 ~25-30 次。

用法:
    python tests/stage3_e2e_tests.py                  # 全部执行
    python tests/stage3_e2e_tests.py --skip-pipeline  # 跳过流水线（仅验证已有产出）
    python tests/stage3_e2e_tests.py --test 3.E2E.1   # 单项测试
"""

import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from core.config import (
    config, OUTPUT_DIR, CHAPTERS_DIR, BRIEFS_DIR,
    EDIT_LOGS_DIR, EVAL_LOGS_DIR, STATE_FILE, RESULTS_FILE,
    BACKUPS_DIR, CONFIG_FILE, ENV_FILE,
)
from core.state_manager import default_state, save_state, load_state
from core.state_manager import count_words_in_chapters, count_chapter_files

SKIP_PIPELINE = "--skip-pipeline" in sys.argv
TARGET_TEST = None
for i, arg in enumerate(sys.argv):
    if arg == "--test" and i + 1 < len(sys.argv):
        TARGET_TEST = sys.argv[i + 1]

TEST_STORY = (
    "一个年轻程序员在2049年的上海发现自己写的AI系统已经觉醒，"
    "他必须在36小时内找到并解除它，否则它将接管全球网络。"
    "悬疑科幻风格，节奏紧凑。"
)

E2E_CONFIG = {
    "story_summary": TEST_STORY,
    "total_chapters": 3,
    "total_volumes": 1,
    "chapters_per_volume": 3,
    "max_foundation_iters": 1,
    "max_revision_cycles": 1,
    "max_revision_rounds": 3,
    "foundation_threshold": 1.0,
    "chapter_threshold": 1.0,
    "revision_threshold": 1.0,
    "plateau_delta": 0.5,
    "max_chapter_attempts": 1,
}

_OUTPUT_BACKUP = ROOT / "output_backup_e2e"


def _check_api_key() -> bool:
    cfg = config
    cfg._loaded = False
    cfg.load()
    key = cfg.api_key
    if not key or key.startswith("sk-xxx") or key.startswith("'sk-xxx"):
        return False
    return True


def _backup_output():
    """备份当前 output/ 到 output_backup_e2e/。"""
    if OUTPUT_DIR.exists():
        if _OUTPUT_BACKUP.exists():
            shutil.rmtree(str(_OUTPUT_BACKUP))
        shutil.copytree(str(OUTPUT_DIR), str(_OUTPUT_BACKUP),
                        dirs_exist_ok=True)
        return True
    return False


def _restore_output():
    """恢复备份的 output/。"""
    if _OUTPUT_BACKUP.exists():
        if OUTPUT_DIR.exists():
            shutil.rmtree(str(OUTPUT_DIR))
        shutil.copytree(str(_OUTPUT_BACKUP), str(OUTPUT_DIR),
                        dirs_exist_ok=True)
        shutil.rmtree(str(_OUTPUT_BACKUP))
        return True
    return False


def _clean_output_for_e2e():
    """清空 output/ 中的生成产物，保留 config.json 结构。"""
    for d in [CHAPTERS_DIR, BRIEFS_DIR, EDIT_LOGS_DIR, EVAL_LOGS_DIR,
              BACKUPS_DIR]:
        if d.exists():
            shutil.rmtree(str(d))
        d.mkdir(parents=True, exist_ok=True)

    for fn in ["manuscript.md", "state.json", "results.tsv",
               "story_summary.txt", "arc_summary.md",
               "world.md", "characters.md", "outline.md",
               "outline_volume.md", "outline_volume1.md",
               "canon.md", "voice.md"]:
        fp = OUTPUT_DIR / fn
        if fp.exists():
            fp.unlink()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _write_e2e_config():
    """写入 E2E 测试配置。"""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(E2E_CONFIG, f, indent=2, ensure_ascii=False)


def _capture_stdout(func, *args, **kwargs):
    captured = io.StringIO()
    old = sys.stdout
    sys.stdout = captured
    try:
        result = func(*args, **kwargs)
    finally:
        sys.stdout = old
    return result, captured.getvalue()


class TestE2E(unittest.TestCase):
    """3.E2E 端到端串联测试"""

    _output: str = ""       # 3.E2E.1 的 stdout 日志
    _elapsed: float = 0.0   # 3.E2E.1 的执行耗时

    @classmethod
    def setUpClass(cls):
        _backup_output()
        print(f"  📋 output/ 已备份")

    @classmethod
    def tearDownClass(cls):
        _restore_output()
        print(f"  ✅ output/ 已恢复")

    # ——— 3.E2E.1 —————————————————————
    def test_3_e2e_1_full_pipeline(self):
        """3.E2E.1 完整 3 章 from_scratch 流水线"""
        if TARGET_TEST and TARGET_TEST not in ("3.E2E.1", "3.E2E"):
            raise unittest.SkipTest(f"--test={TARGET_TEST}")

        if SKIP_PIPELINE:
            raise unittest.SkipTest("--skip-pipeline")

        if not _check_api_key():
            self.skipTest("API Key 无效")

        # 前置
        _clean_output_for_e2e()
        _write_e2e_config()
        save_state(default_state())

        # 执行
        start = time.time()
        result = subprocess.run(
            [sys.executable, str(ROOT / "pipeline_orchestrator.py"),
             "--mode", "from_scratch"],
            cwd=str(ROOT),
            capture_output=True, text=True, timeout=1800,
        )
        elapsed = time.time() - start
        TestE2E._output = result.stdout + "\n" + result.stderr
        TestE2E._elapsed = elapsed

        results = []

        # (A) 退出码
        rc = result.returncode
        results.append(("exit_code", rc == 0,
                        f"exit={rc} ({elapsed/60:.1f}min)"))

        # (B) Foundation
        for fname, min_b in [("world.md", 100), ("characters.md", 100),
                             ("outline_volume.md", 100), ("outline.md", 100),
                             ("canon.md", 100), ("voice.md", 100)]:
            p = OUTPUT_DIR / fname
            ok = p.exists() and p.stat().st_size >= min_b
            results.append((f"Foundation/{fname}", ok,
                            f"{p.stat().st_size}B" if p.exists() else "MISSING"))

        # (C) Drafting
        for ch in range(1, 4):
            cp = CHAPTERS_DIR / f"ch_{ch:02d}.md"
            if cp.exists():
                text = cp.read_text(encoding="utf-8")
                chars = len(text.replace(" ", "").replace("\n", ""))
                ok = chars >= 200
                results.append((f"Drafting/ch_{ch:02d}.md", ok,
                                f"{chars} 字"))
            else:
                results.append((f"Drafting/ch_{ch:02d}.md", False, "MISSING"))

        # (D) Revision
        eval_files = sorted(EVAL_LOGS_DIR.glob("full_*.json"))
        results.append(("Revision/eval_full",
                        len(eval_files) >= 1, f"{len(eval_files)} files"))
        rp = EDIT_LOGS_DIR / "reader_panel.json"
        results.append(("Revision/reader_panel", rp.exists(),
                        "OK" if rp.exists() else "MISSING"))

        # (E) Export
        ms = OUTPUT_DIR / "manuscript.md"
        if ms.exists():
            mt = ms.read_text(encoding="utf-8")
            ms_ok = "目录" in mt and len(mt) > 500
            results.append(("Export/manuscript.md", ms_ok,
                            f"{len(mt)} chars"))
        else:
            results.append(("Export/manuscript.md", False, "MISSING"))

        arc = OUTPUT_DIR / "arc_summary.md"
        if arc.exists():
            at = arc.read_text(encoding="utf-8")
            arc_ok = "角色弧线" in at and len(at) > 100
            results.append(("Export/arc_summary.md", arc_ok,
                            f"{len(at)} chars"))
        else:
            results.append(("Export/arc_summary.md", False, "MISSING"))

        # (F) State
        state = load_state()
        results.append(("State/phase=complete",
                        state.get("phase") == "complete",
                        f"phase={state.get('phase')}"))
        results.append(("State/chapters_drafted=3",
                        state.get("chapters_drafted") == 3,
                        f"drafted={state.get('chapters_drafted')}"))
        results.append(("State/novel_score>0",
                        state.get("novel_score", 0) > 0,
                        f"score={state.get('novel_score')}"))

        # (G) Results
        if RESULTS_FILE.exists():
            tsv = RESULTS_FILE.read_text(encoding="utf-8")
            lines = [l for l in tsv.strip().split("\n") if l.strip()]
            has_export = "export" in tsv
            results.append(("Results/tsv",
                            len(lines) >= 4 and has_export,
                            f"{len(lines)} rows, export={'Y' if has_export else 'N'}"))

        # (H) 无崩溃
        has_crash = "❌ 阶段" in TestE2E._output
        results.append(("No crash", not has_crash,
                        "CRASH" if has_crash else "clean"))

        passed = sum(1 for _, ok, _ in results if ok)
        total = len(results)
        print(f"\n  {passed}/{total} 验证通过")
        for n, ok, d in results:
            print(f"  {'✅' if ok else '❌'} {n}: {d}")

        self.assertEqual(passed, total,
                         f"{total - passed} 项未通过")

    # ——— 3.E2E.2 —————————————————————
    def test_3_e2e_2_output_integrity(self):
        """3.E2E.2 串联前后数据完整性"""
        if TARGET_TEST and TARGET_TEST not in ("3.E2E.2", "3.E2E"):
            raise unittest.SkipTest(f"--test={TARGET_TEST}")

        if SKIP_PIPELINE and not (OUTPUT_DIR / "manuscript.md").exists():
            self.skipTest("流水线未执行且无历史产出")

        self.assertTrue(CONFIG_FILE.exists(), "config.json 缺失")
        self.assertTrue((OUTPUT_DIR / "manuscript.md").exists(),
                        "manuscript.md 缺失")
        self.assertTrue((OUTPUT_DIR / "arc_summary.md").exists(),
                        "arc_summary.md 缺失")
        self.assertTrue(STATE_FILE.exists(), "state.json 缺失")

        # 子目录统计
        for name, d in [("chapters", CHAPTERS_DIR),
                        ("eval_logs", EVAL_LOGS_DIR),
                        ("edit_logs", EDIT_LOGS_DIR),
                        ("briefs", BRIEFS_DIR)]:
            count = len(list(d.glob("*"))) if d.exists() else 0
            self.assertGreater(count, 0,
                               f"{name}/ 为空，预期 ≥ 1 文件")
            print(f"  {name}/: {count} files")

    # ——— 3.E2E.3 —————————————————————
    def test_3_e2e_3_log_integrity(self):
        """3.E2E.3 流水线日志完整性"""
        if TARGET_TEST and TARGET_TEST not in ("3.E2E.3", "3.E2E"):
            raise unittest.SkipTest(f"--test={TARGET_TEST}")

        if not TestE2E._output and SKIP_PIPELINE:
            self.skipTest("流水线未执行，无日志")

        output = TestE2E._output
        self.assertIn("PHASE 1: FOUNDATION", output)
        self.assertIn("PHASE 2: DRAFTING", output)
        self.assertIn("PHASE 3: REVISION", output)
        self.assertIn("PHASE 4: EXPORT", output)
        self.assertIn("[DONE] 流水线完成", output)
        self.assertNotIn("❌ 阶段", output)
        self.assertNotIn("Traceback (most recent call last)", output)
        print("  ✅ 4 Phase banner + [DONE] + 无崩溃")

    # ——— 3.E2E.4 —————————————————————
    def test_3_e2e_4_metrics(self):
        """3.E2E.4 字数/评分/耗时合理性"""
        if TARGET_TEST and TARGET_TEST not in ("3.E2E.4", "3.E2E"):
            raise unittest.SkipTest(f"--test={TARGET_TEST}")

        if SKIP_PIPELINE and not STATE_FILE.exists():
            self.skipTest("流水线未执行且无 state.json")

        state = load_state()
        total_words = count_words_in_chapters()

        # 字数
        self.assertGreaterEqual(total_words, 3000,
                                f"总字数 {total_words} < 3000")
        print(f"  ✅ 总字数: {total_words}")

        # 评分
        score = state.get("novel_score", 0)
        self.assertGreater(score, 0,
                           f"novel_score={score} ≤ 0")
        print(f"  ✅ novel_score: {score}")

        # foundation
        fs = state.get("foundation_score", 0)
        print(f"  ✅ foundation_score: {fs}")

        # 修订
        rc = state.get("revision_cycle", 0)
        self.assertGreaterEqual(rc, 1,
                                f"revision_cycle={rc} < 1")
        print(f"  ✅ revision_cycle: {rc}")

        # 耗时
        if TestE2E._elapsed > 0:
            self.assertLess(TestE2E._elapsed, 1800,
                            f"耗时 {TestE2E._elapsed:.0f}s > 1800s")
            print(f"  ✅ 耗时: {TestE2E._elapsed/60:.1f} min")

        # results.tsv
        if RESULTS_FILE.exists():
            lines = [l for l in RESULTS_FILE.read_text(
                encoding="utf-8").strip().split("\n") if l.strip()]
            self.assertGreaterEqual(len(lines), 8,
                                    f"results.tsv 行数 {len(lines)} < 8")
            print(f"  ✅ results.tsv: {len(lines)} 行")


# ============================================================
# 自定义排序
# ============================================================

def custom_test_order(tests):
    order = [
        "test_3_e2e_1_full_pipeline",
        "test_3_e2e_2_output_integrity",
        "test_3_e2e_3_log_integrity",
        "test_3_e2e_4_metrics",
    ]
    lookup = {id(t): t for t in tests}
    ordered = []
    seen = set()
    for name in order:
        for t in tests:
            if t._testMethodName == name and id(t) not in seen:
                ordered.append(t)
                seen.add(id(t))
                break
    for t in tests:
        if id(t) not in seen:
            ordered.append(t)
    return ordered


if __name__ == "__main__":
    print("=" * 70)
    print("  Stage 3 E2E 端到端串联测试")
    print("=" * 70)
    print(f"  skip-pipeline: {SKIP_PIPELINE}")
    print(f"  target: {TARGET_TEST or '全部'}")
    print(f"  .env: {ENV_FILE}")
    print("-" * 70)

    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestE2E)
    suite._tests = custom_test_order(list(suite))

    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
    result = runner.run(suite)

    passed = result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped)
    print(f"\n{'='*70}")
    print(f"  测试汇总")
    print(f"{'='*70}")
    print(f"  通过: {passed}")
    print(f"  失败: {len(result.failures)}")
    print(f"  错误: {len(result.errors)}")
    print(f"  跳过: {len(result.skipped)}")
    print(f"  总计: {result.testsRun}")
    if result.failures or result.errors:
        print(f"\n  ❌ 存在未通过的测试项")
        sys.exit(1)
    else:
        print(f"\n  ✅ 全部测试通过")
        sys.exit(0)
```

---

## Stage 3 测试检查清单

### 执行前

- [ ] Stage 3 3.1 ~ 3.5 各自分散测试已完成
- [ ] `.env` 中 `AUTONOVEL_API_KEY` 有效
- [ ] API 账户余额 ≥ ¥0.50
- [ ] 当前 `output/` 已备份（`output_backup_e2e/`）
- [ ] 网络可访问 API 端点

### 执行中

- [ ] 3.E2E.1 流水线子进程启动成功
- [ ] 4 个 Phase banner 顺次出现
- [ ] 无 `❌ 阶段` 崩溃日志
- [ ] 退出码 0

### 执行后

- [ ] 3.E2E.1 全部验证通过
- [ ] 3.E2E.2 文件完整性通过
- [ ] 3.E2E.3 日志完整性通过
- [ ] 3.E2E.4 字数/评分/耗时合理
- [ ] `output/` 已从备份恢复（可选）