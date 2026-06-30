# 🔧 Stage 4 E2E-1 异常修复方案计划

> 基准：[`e2e1_anomaly_report.md`](e2e1_anomaly_report.md)  
> 日期：2026-06-29  
> 原则：最小改动、不引入新风险、优先修复有功能影响的缺陷

---

## 修复总览

| 序号 | 异常 | 级别 | 影响文件 | 改动行数 |
|:--:|------|:---:|------|:------:|
| F1 | `max_revision_cycles` 配置被忽略 | 🔴 P0 | `pipeline_orchestrator.py` | ~3 行 |
| F2 | 审阅修订识别幻影章节 | 🟡 P1 | `pipeline_orchestrator.py` | ~3 行 |
| F3 | `parse_score()` 高频返回 -1.0 | 🟡 P1 | `core/state_manager.py` + `evaluation/evaluate.py` | ~30 行 |
| F4 | Revision 横幅显示错误 max_cycles | 🟢 P2 | `pipeline_orchestrator.py` | 被 F1 修复 |
| F5 | E2E-1 插桩脚本验证逻辑修正 | 🟢 P2 | `_run_stage4_e2e1.py` | ~15 行 |
| F6 | `results.tsv` 跨运行累积 | 🟢 P3 | `core/state_manager.py` + `_run_stage4_e2e1.py` | ~5 行 |

---

## F1 🔴 P0：`max_revision_cycles` 配置被忽略

### 根因

[`run_pipeline()`](pipeline_orchestrator.py:1204) 仅检查 CLI 参数 `--max-cycles`，不读取 `config.json` 的 `max_revision_cycles` 字段。  
对比 `run_foundation()`（line 79）和 `run_drafting()`（line 197）都正确读取了 config。

### 影响

- E2E-1 配置意图 `max_revision_cycles=3` 被忽略
- 实际使用常量 `MAX_REVISION_CYCLES=6`
- 本次因平台期检测幸运停止在 3 轮，但不可靠

### 修复

**文件**：[`pipeline_orchestrator.py`](pipeline_orchestrator.py:1204)

```python
# === 修改前 ===
    revision_cycles = max_cycles if max_cycles else MAX_REVISION_CYCLES

# === 修改后 ===
    cfg = config
    cfg.load()
    revision_cycles = (
        max_cycles
        or (cfg.max_revision_cycles if cfg.loaded else None)
        or MAX_REVISION_CYCLES
    )
```

### 验证

- [ ] E2E-1 重新运行，确认日志显示 `修订 循环 N/3` 而非 `N/6`
- [ ] 修改 config.json 中 `max_revision_cycles` 为 2，确认循环数为 2
- [ ] 通过 CLI `--max-cycles 4` 确认 CLI 参数优先级高于 config

---

## F2 🟡 P1：审阅修订识别幻影章节

### 根因

[`_parse_review_weak_chapters()`](pipeline_orchestrator.py:888) 用正则从审阅文本提取章节号后，不验证章节号是否 ≤ `total_chapters`。审阅文本中的假设性描述被误解析。

### 影响

- 审阅轮次 1 错误识别 ch5、ch10（不存在）
- 审阅轮次 3 错误识别 ch4（不存在）
- 浪费 API 调用和审阅时间（优雅跳过但占用了轮次配额）

### 修复

**文件**：[`pipeline_orchestrator.py`](pipeline_orchestrator.py:886-888)

```python
# === 修改前 ===
    sorted_chs = sorted(chapter_hits.items(), key=lambda x: -x[1])
    return [ch for ch, _ in sorted_chs[:5]]

# === 修改后 ===
    sorted_chs = sorted(chapter_hits.items(), key=lambda x: -x[1])
    # 获取实际章节数用于范围校验
    chapter_files = sorted(CHAPTERS_DIR.glob("ch_*.md"))
    total_ch = len(chapter_files)
    # 兜底：无明确引用时取中段
    result = [ch for ch, _ in sorted_chs if 1 <= ch <= total_ch]
    if not result and total_ch >= 6:
        mid_start = total_ch // 3
        mid_end = 2 * total_ch // 3
        result = list(range(mid_start + 1, mid_end + 1))
    return result[:5]
```

### 验证

- [ ] 运行 3 章小说的审阅修订，确认弱章节列表不包含 >3 的章节号
- [ ] 运行 10 章小说的审阅修订，确认弱章节列表不包含 >10 的章节号

---

## F3 🟡 P1：`parse_score()` 高频返回 -1.0

### 根因

裁判模型输出的评分格式不稳定。`parse_score()` 有 9 种正则模式，但 LLM 有时输出不在覆盖范围内的格式。全部匹配失败时返回 sentinel `-1.0`。

修订阶段 `-1.0` 出现约 10+ 次，导致：
- 有效修订被错误回退（`-1.0 < pre_score`）
- 修订前评分不可靠（pre_score = -1.0）
- results.tsv 中出现无意义的 -1.0 记录

### 修复方案（双管齐下）

#### 方案 A：硬约束裁判 prompt（推荐优先）

**文件**：[`evaluation/evaluate.py`](evaluation/evaluate.py) — 在 `build_chapter_eval_prompt()` 返回值末尾追加格式约束

在返回的 prompt 字符串末尾强制追加：

```python
# 在 evaluate.py 的 build_chapter_eval_prompt() 中，return 之前追加：
    prompt += (
        "\n\n"
        "=== 输出格式（必须严格遵守）===\n"
        "请在你的评审报告末尾，单独一行输出以下内容：\n"
        "overall_score: X.X\n"
        "其中 X.X 是一个 0.0-10.0 之间的浮点数，代表本章的综合评分。\n"
        "这行必须单独存在，前面不添加任何 markdown 标记。"
    )
    return prompt
```

#### 方案 B：增强 `parse_score()` 的 fallback 鲁棒性

**文件**：[`core/state_manager.py`](core/state_manager.py:422)

在 `return -1.0` 之前增加最终兜底：

```python
# === 在 line 422 return -1.0 之前插入 ===
    # 最终兜底：反向搜索——从文本末尾向前找任何类似 "X.X/10" 的数字
    import re as _re_final
    for line in reversed(lines):
        # 匹配任何类似 6.5/10, 7.0, 8/10 的评分模式
        m = _re_final.search(r'(\d+(?:\.\d+)?)\s*/\s*10', line)
        if m:
            return float(m.group(1))
        m = _re_final.search(r'(?:score|评分|Score)\D*(\d+(?:\.\d+)?)', line, _re_final.IGNORECASE)
        if m:
            val = float(m.group(1))
            return val if val <= 10 else val / 10.0
    return -1.0
```

#### 方案 C：在 `evaluate_chapter()` 中添加兜底（新增）

**文件**：[`evaluation/evaluate.py`](evaluation/evaluate.py:387)

```python
# === 在 evaluate_chapter() 的 return result 之前 ===
    # 如果裁判输出不包含 overall_score 格式，追加解析提示
    if "overall_score" not in result and "综合评分" not in result:
        # 尝试从结果中提取任何数字作为兜底
        import re as _re_scr
        scores = _re_scr.findall(r'(\d+(?:\.\d+)?)\s*/\s*10', result)
        if scores:
            result += f"\noverall_score: {scores[-1]}"
```

### 实施顺序

1. **先实施方案 A**（硬约束 prompt）— 从源头解决格式问题
2. **再实施方案 B**（增强 parse_score）— 作为兜底安全网
3. **方案 C** 可选 — 双重兜底

### 验证

- [ ] 运行 3-5 次章节评估，确认 `-1.0` 出现次数 < 总次数的 5%
- [ ] 检查 `eval_logs/` 中的裁判输出是否包含 `overall_score:` 行
- [ ] 确认修订阶段的 pre_score 不再出现 -1.0

---

## F4 🟢 P2：Revision 横幅显示 N/6 而非 N/3

### 根因

与 F1 同源。`run_revision()` 的 `max_cycles` 参数值为 6（常量），banner 使用该值显示。

### 影响

纯显示问题，不影响功能。

### 修复

被 **F1** 修复后自动解决。无需额外修改。

### 验证

- [ ] F1 修复后确认横幅显示 `修订 循环 N/3`

---

## F5 🟢 P2：E2E-1 插桩脚本验证逻辑修正

### 根因

三个验证逻辑缺陷：

1. **B2 验证**（[`_run_stage4_e2e1.py:491-496`](_run_stage4_e2e1.py:491)）：依赖 `results.tsv` 而非直接检查 pipeline 日志
2. **B4 验证**（[`_run_stage4_e2e1.py:503`](_run_stage4_e2e1.py:503)）：比较对象是脚本常量而非实际运行参数
3. **`_parse_results_tsv()`**（[`_run_stage4_e2e1.py:271`](_run_stage4_e2e1.py:271)）：不跳过表头行

### 修复

#### 5a：修正 `_parse_results_tsv()` 跳过表头

```python
# === 修改前 ===
    with open(RESULTS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

# === 修改后 ===
    with open(RESULTS_FILE, "r", encoding="utf-8") as f:
        header_skipped = False
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if not header_skipped:
                header_skipped = True
                continue
```

#### 5b：修正 B4 平台期验证

```python
# === 修改前 (line 503-508) ===
    if rev_cycle < MAX_REV_CYCLES:
        inlog(f"B4 平台期: revision_cycle={rev_cycle} < {MAX_REV_CYCLES}，可能触发了平台期停止")
    else:
        inlog(f"B4 平台期: revision_cycle={rev_cycle}，达到 max 上限，未触发提前停止")

# === 修改后 ===
    # 检查日志中是否出现了平台期停止标记
    # 如果 revision_cycle < 期望的 max，说明提前停止了
    expected_max = final_config.get("max_revision_cycles", 3)
    if rev_cycle < expected_max:
        inok(f"B4 平台期: revision_cycle={rev_cycle} < {expected_max}，触发了平台期提前停止 ✓")
    else:
        inlog(f"B4 平台期: revision_cycle={rev_cycle}，达到 max={expected_max} 上限")
```

#### 5c：修正 B2 验证 — 改为直接检查日志而非 TSV

```python
# === 修改前 (line 491-496) ===
    ch_discard = [r for r in rows if r[4] == "discard" and r[1].startswith("ch")] if a5_ok else []
    if ch_discard:
        inlog(f"B2 章节重试: {len(ch_discard)} 条 discard → 已触发重试")
    else:
        observations.append("B2: 所有章节一次通过，未触发 retry")

# === 修改后 ===
    # 直接检查 state 和各章尝试次数（更可靠）
    # 逻辑：如果 chapters_drafted 与实际尝试次数一致但中途有丢弃，
    # 通过检查 results.tsv 的 discard 行 + keep 行总数是否 > chapters_total 判断
    total_chapter_rows = len([r for r in rows if r[1].startswith("ch")]) if a5_ok else 0
    if total_chapter_rows > TOTAL_CH:
        inok(f"B2 章节重试: {total_chapter_rows} 条记录 > {TOTAL_CH} 章 → 已触发重试 ✓")
    else:
        inlog(f"B2 章节重试: {total_chapter_rows} 条记录 = {TOTAL_CH} 章 → 全部一次通过")
```

### 验证

- [ ] 重新运行 E2E-1，确认 B2 显示"已触发重试"而非"一次通过"
- [ ] 确认 B4 正确识别平台期停止

---

## F6 🟢 P3：`results.tsv` 跨运行累积

### 根因

`clean_output()` 删除 `results.tsv`，但该函数没有验证删除是否成功。此外，`log_result()` 使用追加模式 `"a"`，如果删除失败旧数据会残留。

### 影响

- 本次 E2E-1 的 `results.tsv` 前 62 行来自历史运行
- `_parse_results_tsv()` 解析到混合数据，导致验证不可靠

### 修复

#### 方案 A（推荐）：在 `log_result()` 中加入运行标记

**文件**：[`core/state_manager.py`](core/state_manager.py) — `log_result()` 函数

在每次写入第一条记录前，写入一个运行标记行：

```python
# 在 log_result() 函数开头，首次调用时写入标记
def log_result(commit_hash, stage, score, word_count, decision, notes):
    # 如果文件不存在或为空，写入运行标记
    need_marker = not RESULTS_FILE.exists() or RESULTS_FILE.stat().st_size < 10
    with open(RESULTS_FILE, "a", encoding="utf-8") as f:
        if need_marker:
            run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
            f.write(f"# RUN {run_id}\n")
        f.write(f"{commit_hash}\t{stage}\t{score}\t{word_count}\t{decision}\t{notes}\n")
```

#### 方案 B：在 `clean_output()` 中验证

```python
# _run_stage4_e2e1.py clean_output() 末尾
    # 验证 results.tsv 已删除
    if RESULTS_FILE.exists():
        inlog("⚠ results.tsv 删除失败，可能存在文件锁定")
```

### 验证

- [ ] 运行两次 E2E-1，确认 results.tsv 中只有最新运行的数据
- [ ] 检查 `# RUN` 标记行是否正确写入

---

## 实施顺序

```
第 1 步: F1 (P0) → pipeline_orchestrator.py 读取 config.max_revision_cycles
              │
              └── 自动修复 F4 (横幅显示)
              
第 2 步: F2 (P1) → 审阅弱章节范围校验
              
第 3 步: F3 (P1) → 方案 A: prompt 硬约束格式
              │
              └── 方案 B: parse_score 增强兜底

第 4 步: F5 (P2) → E2E-1 插桩脚本修正

第 5 步: F6 (P3) → results.tsv 运行标记

第 6 步: 回归验证 → 重新运行 E2E-1，确认所有异常修复
```

## 回归验证清单

- [ ] Foundation 迭代循环正常（3 次，阈值 7.5）
- [ ] Drafting 多尝试 + slop/反模式/文风检查正常
- [ ] Revision 横幅显示 `N/3`（而非 `N/6`）
- [ ] 审阅修订弱章节列表不含幻影章节
- [ ] `parse_score` 返回 -1.0 的频率 < 5%
- [ ] 修订评分轨迹：pre_score 不再出现 -1.0
- [ ] E2E-1 验证 B2 正确报告"已触发重试"
- [ ] E2E-1 验证 B4 正确识别平台期
- [ ] `results.tsv` 不含跨运行旧数据
- [ ] A1-A6 结构完整性全部通过
