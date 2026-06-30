# 🪲 Stage 4 E2E-1 全流水线逐项核对报告

> **分析策略**：严格基于最近一次 `run_pipeline("from_scratch")` 的 Pipeline 日志  
> **数据来源**：[`debug.log`](logs/debug.log) 第 1860-2268 行（E2E-1 from_scratch 单次运行）  
> **运行时间**：2026-06-29 14:32 — 20:05（总耗时 333min）  
> **⚠ results.tsv 数据污染说明**：`results.tsv` 前 62 行来自历史运行（如 foundation=8.0/9.0/10.0，与本次实际评分 4.0/7.0/7.0 不符），仅第 63-74 行属于本次运行。标记 🗂️ 的条目依赖 TSV，可靠性降低。

---

## 一、核对总览

| # | 异常项 | 严重级别 | 数据来源 | 分析章节 |
|:--:|--------|:------:|:------:|:--------:|
| 1 | `max_revision_cycles` 配置被忽略 | 🔴 严重 | Pipeline 日志 ✅ | [二.1](#1--严重-max_revision_cycles-配置被忽略) |
| 2 | 审阅修订识别出幻影章节 | 🟡 中等 | Pipeline 日志 ✅ | [二.2](#2--中等-审阅修订识别出幻影章节ch5ch10ch4) |
| 3 | 审阅修订后评分反降 | 🟡 中等 | Pipeline 日志 ✅ | [二.3](#3--中等-审阅修订闭环后评分反降-65--55) |
| 4 | 章节草拟 discard 未写入 results.tsv 🗂️ | 🟡 中等 | TSV（受污染） | [二.4](#4--中等-章节草拟-discard-未写入-resultstsv) |
| 5 | Revision 横幅显示 N/6 而非 N/3 | 🟢 轻微 | Pipeline 日志 ✅ | [二.5](#5--轻微-revision-横幅显示-n6-而非-n3) |
| 6 | E2E-1 B2 验证误判 🗂️ | 🟢 轻微 | TSV（受污染） | [二.6](#6--轻微-e2e-1-脚本-b2-验证逻辑误判) |
| 7 | Foundation 迭代3 canon=0 | 🟢 轻微 | Pipeline 日志 ✅ | [二.7](#7--轻微-foundation-迭代3-canon条目为0) |

---

## 二、逐项详细分析

### 1. 🔴 严重：`max_revision_cycles` 配置被忽略

**数据来源**：Pipeline 日志 + [`pipeline_orchestrator.py`](pipeline_orchestrator.py:1204) 源码

**配置意图**（E2E-1 脚本，[`_run_stage4_e2e1.py:230`](_run_stage4_e2e1.py:230)）：
```json
// output/config.json（第9行，14:32写入）
"max_revision_cycles": 3,
```

**实际行为**：日志显示 `修订 循环 N/6`，而非 `N/3`。

```
日志行 1863: max_revision_cycles=3     ← E2E-1 写入 config 的意图
日志行 1994: 修订 循环 1/6             ← 实际使用了 6
日志行 2026: 修订 循环 2/6
日志行 2057: 修订 循环 3/6
日志行 2086: 平台期检测 — 停止修订     ← 因平台期才在 3 轮停止，不是因配置
```

**根因**：[`run_pipeline()`](pipeline_orchestrator.py:1204) 只检查 CLI 参数 `--max-cycles`，从不读取 `config.json`：

```python
# pipeline_orchestrator.py:1204
revision_cycles = max_cycles if max_cycles else MAX_REVISION_CYCLES
#                 ^^^^^^^^^^                    ^^^^^^^^^^^^^^^^^^^^
#                 仅 CLI 参数                   常量 = 6，从不读 config
```

**与 Phase 1/2 的对比**——`run_foundation()` 和 `run_drafting()` 都正确读取了 config：

| Phase | 函数 | 读取 config? | 代码 |
|-------|------|:-----------:|------|
| Foundation | `run_foundation()` | ✅ | `cfg.max_foundation_iters` (line 79) |
| Drafting | `run_drafting()` | ✅ | `cfg.max_chapter_attempts` (line 197) |
| **Revision** | `run_revision()` | **❌** | `max_cycles` 参数，默认 `MAX_REVISION_CYCLES=6` |

**幸运巧合**：平台期检测（delta 0.30 < 0.3）在 cycle 3 停止了修订，恰好与配置意图一致。如果评分持续提升，流水线会错误地运行到 cycle 6。

**修复**（`pipeline_orchestrator.py:1204`）：
```python
# 修改前
revision_cycles = max_cycles if max_cycles else MAX_REVISION_CYCLES
# 修改后
cfg = config; cfg.load()
revision_cycles = (
    max_cycles
    or (cfg.max_revision_cycles if cfg.loaded else None)
    or MAX_REVISION_CYCLES
)
```

---

### 2. 🟡 中等：审阅修订识别出幻影章节（ch5、ch10、ch4）

**数据来源**：Pipeline 日志

**配置**：`total_chapters = 3`，小说只有 3 章。

**实际行为**：

```
日志行 2091: 弱章节: [2, 1, 3, 5, 10]   ← ch5、ch10 不存在
日志行 2110:   第 5 章不存在，跳过
日志行 2111:   第 10 章不存在，跳过

日志行 2139: 弱章节: [1, 2, 3, 4]       ← ch4 不存在
日志行 2158:   第 4 章不存在，跳过
```

**根因**：[`_parse_review_weak_chapters()`](pipeline_orchestrator.py:838) 使用正则 `第\d+章` 匹配审阅文本中的章节引用，但**不验证章节号是否 ≤ total_chapters**。审阅文本中的假设性描述（如"如果第5章能加强..."）被误解析为弱章节。

**影响**：浪费了 API 调用和审阅轮次，但管线优雅跳过（"第 N 章不存在，跳过"）未崩溃。

**修复**（`pipeline_orchestrator.py:888`）：
```python
# 修改前
return [ch for ch, _ in sorted_chs[:5]]
# 修改后
total = get_total_chapters(state)
return [ch for ch, _ in sorted_chs[:5] if 1 <= ch <= total]
```

---

### 3. 🟡 中等：审阅修订闭环后评分反降（6.5 → 5.5）

**数据来源**：Pipeline 日志

**评分轨迹**（本次 from_scratch 运行）：

```
循环1 全文评估: 6.5  (日志行 2024)
循环2 全文评估: 6.5  (日志行 2055)
循环3 全文评估: 6.2  (日志行 2085)    ← 开始下降
平台期检测: delta 0.30 < 0.3 → 停止修订
↓ 进入审阅修订闭环
审阅轮次1: ★, 22严重 → 修订5章 → 全部回退  (日志行 2090-2111)
审阅轮次2: ★, 6严重  → 修订3章 → 2章改善   (日志行 2115-2134)
审阅轮次3: ★, 15严重 → 修订4章 → 1章改善   (日志行 2138-2157)
审阅后评估: 5.5  (日志行 2160)          ← 比进入前 (6.2) 更低
```

**分析**：

- 审阅修订 3 轮共修订 12 章次（含 3 次幻影章节 skip），**仅 3 次评分真正提升**
- 3 轮审阅的严重问题数分别为 22、6、15，从未达到通过条件（≥4.5★ 且 0 严重问题）
- 最终全文评估将 `novel_score` 从 6.2 覆盖为 5.5

**根因**：审阅修订闭环的 `_run_review_revision_loop()` 在退出时调用 `evaluate_full()`（[line 1063](pipeline_orchestrator.py:1063)），这个评估覆盖了循环中的 `novel_score`。由于多轮修订中大部分被回退，部分章节处于不确定状态，最终评估分数反而更低。

---

### 4. 🟡 中等：章节草拟 discard 未写入 results.tsv [🗂️ 依赖 TSV]

**Pipeline 日志事实**（本次运行中发生了 4 次章节丢弃）：

```
日志行 1947: 第 1 章评分: -1.0 → 丢弃重试     (ch01 attempt 2)
日志行 1961: 第 2 章评分: -1.0 → 丢弃重试     (ch02 attempt 1)
日志行 1974: 第 3 章评分: -1.0 → 丢弃重试     (ch03 attempt 1)
日志行 1979: 第 3 章评分: 5.5  → 丢弃重试     (ch03 attempt 2)
```

**results.tsv 本次运行部分（第 63-74 行）**中，所有章节阶段都是 `keep`：

```
ch01: 无 discard 行 (应有 1 条)
ch02: 无 discard 行 (应有 1 条)  
ch03: 无 discard 行 (应有 2 条)
```

**源码确认**：[`run_drafting()`](pipeline_orchestrator.py:332-338) 确实在丢弃时调用了 `log_result("discarded", ...)`。

**可能根因**：
1. `results.tsv` 前 62 行的历史数据污染了 `_parse_results_tsv()` 的搜索结果——该函数遍历全部 74 行，在旧数据中未找到章节 discard（旧运行可能使用极端阈值），在新数据中即使有也被淹没了
2. `clean_output()` 删除 `results.tsv` 可能失败（文件被锁定），导致新旧数据混杂

> ⚠ 此条完全依赖 `results.tsv` 解析。本次运行的 TSV 数据（第 63-74 行，12 行）不足以交叉验证 pipeline 日志中的 4 次章节丢弃是否确实写入了 TSV。

---

### 5. 🟢 轻微：Revision 横幅显示 "N/6" 而非 "N/3"

**数据来源**：Pipeline 日志

**证据**：日志行 1994、2026、2057 均显示 `修订 循环 N/6`

**根因**：[`run_revision()`](pipeline_orchestrator.py:451) 的 `banner(f"修订 循环 {cycle}/{max_cycles}")` 使用 `max_cycles=6`（由 [#1](#1--严重-max_revision_cycles-配置被忽略) 传入），而非 config 中的 3。

**影响**：纯显示问题。不影响实际行为。

---

### 6. 🟢 轻微：E2E-1 脚本 B2 验证逻辑误判 [🗂️ 依赖 TSV]

**E2E-1 验证日志**：

```
日志行 2258: 📋 B2: 所有章节一次通过，未触发 retry
```

**Pipeline 日志事实**：所有 3 章都经过了多次尝试：

| 章节 | 尝试次数 | 丢弃次数 | 最终评分 |
|------|:------:|:------:|:------:|
| 第 1 章 | 3 | 2 | 7.5 |
| 第 2 章 | 2 | 1 | 6.0 |
| 第 3 章 | 3 | 2 | 8.0 |

**根因**：[`_run_stage4_e2e1.py:491-496`](_run_stage4_e2e1.py:491) 的 B2 检查完全依赖 `results.tsv`：

```python
ch_discard = [r for r in rows if r[4] == "discard" and r[1].startswith("ch")]
```

由于 [#4](#4--中等-章节草拟-discard-未写入-resultstsv) 导致章节 discard 未在 TSV 中找到，B2 误判为"一次通过"。

> ⚠ 此条依赖 TSV 数据，与 [#4](#4--中等-章节草拟-discard-未写入-resultstsv) 同源。

---

### 7. 🟢 轻微：Foundation 迭代3 canon=0

**数据来源**：Pipeline 日志

**证据**：

```
日志行 1927: 正典条目数: 0 (世界观0 + 角色0 + 时间线0 + 规则0)

对比：
日志行 1903: 迭代1 → 714 条目
日志行 1915: 迭代2 → 596 条目
日志行 1927: 迭代3 → 0 条目  ← 异常
```

**根因**：LLM API 返回的 canon 被 `count_canon_entries()` 解析为 0（可能返回空内容或格式异常）。

**影响**：无。迭代 3 评分 7.0 未超过历史最佳 7.0，该迭代被丢弃。最终使用的是迭代 2 的 canon（596 条目）。

---

## 三、插桩脚本自身的验证逻辑问题

以下问题来自 [`_run_stage4_e2e1.py`](_run_stage4_e2e1.py) 本身，而非被测流水线：

### 3.1 `_parse_results_tsv()` 不跳过 TSV 表头行

```python
# _run_stage4_e2e1.py:271
if not line or line.startswith("#"):
    continue   # ❌ 不跳过 "commit\tphase\t..." 表头行
```

表头被当作数据行解析（行计数 +1），但实际查询不命中。

### 3.2 `results.tsv` 跨运行累积 [🗂️]

`clean_output()` 删除 `results.tsv`，但前 62 行历史数据仍然存在——这意味着要么删除失败，要么日志文件是多次运行累积写入的。无论原因，`_parse_results_tsv()` 解析了包含旧数据的文件，导致验证结果不可靠。

### 3.3 B4 平台期验证条件写反

```python
# _run_stage4_e2e1.py:503-508
if rev_cycle < MAX_REV_CYCLES:    # MAX_REV_CYCLES=3
    inlog("可能触发了平台期停止")
else:
    inlog("达到 max 上限，未触发提前停止")
```

日志输出 `revision_cycle=3，达到 max 上限，未触发提前停止`——但实际日志行 2086 明确显示"平台期检测 — 停止修订"。

根因：`state.revision_cycle` 在停止时已是 3，`3 < 3` 为 False，走了 else 分支；且代码比较对象是脚本常量 `MAX_REV_CYCLES=3` 而非实际运行时参数。

---

## 四、总结

### 功能完整性核对（仅基于 Pipeline 日志）

| 功能 | 实现状态 | 证据（日志行） |
|------|:------:|------|
| Phase 1 Foundation 迭代循环 | ✅ 正常 | 1896-1934 |
| Phase 1 质量门控 (阈值 7.5) | ✅ 正常 | 1932-1934 |
| Phase 2 Drafting 多尝试 | ✅ 正常 | 1940-1988 |
| Phase 2 Slop 触发反套话重写 | ✅ 正常 | 1944 |
| Phase 2 文风指纹检查 | ✅ 正常 | 1953-1955 |
| Phase 2 结构反模式审计 | ✅ 正常 | 1985-1987 |
| Phase 2 增量 Canon | ✅ 正常 | 1956, 1969, 1988 |
| Phase 3 对抗性编辑 | ✅ 正常 | 1995-1996 |
| Phase 3 机械裁剪 | ✅ 正常 | 1997 |
| Phase 3 读者评审团 | ✅ 正常 | 1998-1999 |
| Phase 3 共识问题修订 | ✅ 正常 | 2000-2016 |
| Phase 3 采样评估 | ✅ 正常 | 2017-2022 |
| Phase 3 全文评估 | ✅ 正常 | 2023-2024 |
| Phase 3 平台期检测 | ✅ 正常 | 2086 |
| Phase 3 审阅修订闭环 | ⚠ 部分异常 | 2088-2162（幻影章节、评分反降） |
| Phase 3 **config.max_revision_cycles** | ❌ 未实现 | 1994 vs config intent |
| Phase 4 Export | ✅ 正常 | 2166-2174 |
| Git 回退防护 | ✅ 正常 | 2016, 2038, 2097 等 |
| 中断恢复 | ⚠ 未触发 | 本次未中断 |

### 关键修复优先级

1. **🔴 立即**：[`run_pipeline():1204`](pipeline_orchestrator.py:1204) — 读取 `cfg.max_revision_cycles`
2. **🟡 建议**：[`_parse_review_weak_chapters():888`](pipeline_orchestrator.py:888) — 添加章节号范围校验
3. **🟡 建议**：审计 `log_result()` 在 `run_drafting()` discard 路径的写入是否完整
4. **🟢 可选**：消除 `results.tsv` 跨运行累积问题（`clean_output` 中验证删除成功）
5. **🟢 可选**：修复 E2E-1 插桩脚本的 `_parse_results_tsv()` 表头跳过和 B4 条件
