# Phase 3 共识修订对齐原版 — 修改方案（更新版）

## 背景

原始计划 [`phase3_original_mechanism_plan.md`](plans/phase3_original_mechanism_plan.md) 中的 6 项修改已有 4 项完成：

| 改 | 文件 | 状态 |
|----|------|:---:|
| 改1 | `prompts/adversarial_prompts.py` → prompt 改 JSON | ✅ 已完成 |
| 改2 | `revision/adversarial_edit.py` → +JSON 解析 | ✅ 已完成 |
| 改2b | `revision/reader_panel.py` → +JSON 解析 + 聚合 | ✅ 已完成 |
| 改2c | `evaluation/evaluate.py` → +JSON 解析 | ✅ 已完成 |
| 改3 | `revision/apply_cuts.py` → 完整重写 | 📋 待办 |
| 改4 | `revision/gen_brief.py` → 简化 brief 生成 | 📋 待办 |
| 改5 | `pipeline_orchestrator.py` → 简化 run_revision() | 📋 待办 |

---

## 目标：重构版共识修订链路 = 原版共识修订链路

### 原版链路（目标）

```
Step 3: reader_panel.py → reader_panel.json
Step 4: parse_panel_consensus() → [{chapter, question, flagged_by}, ...]
Step 5: for each consensus item:
  ① 修订前评估 → pre_score
  ② build_panel_brief(ch_num) → 从 reader_panel.json + cuts.json + eval JSON 生成修订摘要
  ③ gen_revision(ch_num, brief)
  ④ 修订后评估 → post_score
  ⑤ if post_score >= pre_score: commit  else: revert
Step 6: evaluate_full() → novel_score
Step 7: plateau detection

Phase 3b: review → parse → gen_brief --auto → gen_revision → apply_cuts
```

### 重构版当前链路（需要修改的部分标注 ★）

```
Step 3: reader_panel.py → reader_panel.json
Step 4: _parse_panel_consensus() → [{chapter, question, ...}, ...]
Step 5: for each consensus item:
  ① 修订前评估 → pre_score
  ② ★ generate_brief(ch_num, panel_data=...) → eval→cuts→panel→auto 四级回退
      失败回退 _build_fallback_brief()
  ③ revise_chapter(ch_num, brief)
  ④ 修订后评估 → post_score
  ⑤ ★ if post_score >= pre_score - 0.5: commit  else: revert  ← 太宽松

★ Step 5b: _sample_evaluate_volumes()       ← 原版没有，需删除
★ Step 5c: _cross_volume_consistency_review() ← 原版没有，需删除
★ Step 5d: 合并修订队列 (共识∪采样∪跨卷)      ← 原版没有，需删除

★ Step 6: evaluate_full() (前置到合并修订之前) ← 位置不对

Step 7: plateau detection  ← 对齐原版
```

---

## 剩余修改清单（3 项）

### 改 A：`pipeline_orchestrator.py` — 简化 `run_revision()` 共识修订部分

这是核心修改，需要做以下操作：

#### A1. 替换 Step 5 的 brief 生成逻辑

当前（[`pipeline_orchestrator.py:602-618`](pipeline_orchestrator.py:602)）：
```python
try:
    generate_brief(ch_num, panel_data=panel_path, output_path=brief_file, ...)
    if brief_file.exists():
        brief_text = brief_file.read_text(...)
        if len(brief_text) < 500 or "未给出具体修订建议" in brief_text:
            raise ValueError("...")
except:
    brief_content = _build_fallback_brief(ch_num, context, label)
    brief_file.write_text(brief_content)
```

改为（对齐原版）：
```python
from revision.gen_brief import build_panel_brief

brief_text = build_panel_brief(ch_num)
brief_file.write_text(brief_text, encoding="utf-8")
```

#### A2. 修改评分容忍区间

当前：`if post_score >= pre_score - 0.5:`（第 637 行）
改为：`if post_score >= pre_score:`（对齐原版严格比较）

#### A3. 删除额外步骤

删除以下代码块（全部在 `run_revision()` 函数体内）：

| 删除项 | 说明 |
|--------|------|
| `_sample_evaluate_volumes()` 嵌套函数定义 | 采样评估逻辑 |
| `_cross_volume_consistency_review()` 嵌套函数定义 | 跨卷审阅逻辑 |
| `sample_weaks = _sample_evaluate_volumes(...)` 执行 | 采样评估调用 |
| `cross_broken = _cross_volume_consistency_review(...)` 执行 | 跨卷审阅调用 |
| `combined_targets: dict[int, str] = {}` + 后续 `for ch_num, reason` 修订循环 | 合并修订队列 |

#### A4. 全文评估位置恢复

当前全文评估（`evaluate_full`）在合并修订之前执行（第 809-823 行）。需要移到共识修订之后、平台检测之前（对齐原版 Step 6 位置）。

---

### 改 B：`revision/apply_cuts.py` — 完整重写（对齐原版实现）

当前 [`apply_cuts.py`](revision/apply_cuts.py) 是占位桩。需要移植原版 [`autonovel-原版/apply_cuts.py`](autonovel-原版/apply_cuts.py) 的完整实现：

- `find_and_remove(text, quote)` — 精确子串匹配 + 空白标准化回退
- `process_chapter(chapter_num, type_filter, min_fat, dry_run)` — 逐章处理
- `collapse_blank_lines(text)` — 合并多余空行
- `--types` 和 `--min-fat` CLI 参数

适配要点：
- 原版用英文 `MIN_QUOTE_LEN = 25`（单词），中文改为字符数
- 原版分类标签 `FAT|REDUNDANT|OVER-EXPLAIN|GENERIC|TELL|STRUCTURAL` 对齐已修复的 adversarial prompt 标签
- 路径适配重构版的 `CHAPTERS_DIR` / `EDIT_LOGS_DIR`

---

### 改 C：Phase 3b 评分容忍对齐

[`pipeline_orchestrator.py:1131`](pipeline_orchestrator.py:1131) 的 `_run_review_revision_loop()` 中：
```python
if post_score >= pre_score - 0.5:  # ★ 也需对齐为严格比较
```

---

## 修改后完整链路（对齐原版）

```
Step 1: run_adversarial_edit("all")     → chXX_cuts.json (✅ 已结构化)
Step 2: run_apply_cuts("all", ...)      → 真正删除赘语段落 (📋 待改B)
Step 3: run_reader_panel()              → reader_panel.json (✅ 已结构化)
Step 4: _parse_panel_consensus()        → 共识问题列表 (✅ 已可用)
Step 5: for each consensus item:
  ① evaluate_chapter_stable(ch_num) → pre_score
  ② build_panel_brief(ch_num)       → 简明摘要 (📋 待改A1)
     (内部交叉引用 panel + cuts + eval + voice)
  ③ revise_chapter(ch_num, brief)   → 执行修订
  ④ evaluate_chapter_stable(ch_num) → post_score
  ⑤ if post_score >= pre_score: commit  else: revert  (📋 待改A2)
Step 6: evaluate_full()              → novel_score (📋 待改A4)
Step 7: plateau detection

Phase 3b: 审阅修订闭环 (📋 待改C 评分容忍)
```

---

## 执行顺序

| 顺序 | 文件 | 改动 | 依赖 |
|------|------|------|------|
| 1 | `revision/apply_cuts.py` | 完全重写（移植原版实现） | 无 |
| 2 | `pipeline_orchestrator.py` | 简化 run_revision()：删除采样/跨卷/合并修订，替换 brief 为 build_panel_brief，严格评分比较 | 改1 |
| 3 | 编译验证 | `py_compile` 全部受影响文件 | 全部 |

---

## 风险评估

| 风险 | 缓解 |
|------|------|
| 删除采样评估可能遗漏弱章 | 原版同样没有采样评估——共识修订覆盖了被读者标记的弱章，全文评估也会识别弱章 |
| 删除跨卷审阅可能遗漏断裂 | 原版同样没有跨卷审阅——Phase 3b 的深度审阅会覆盖连续性检查 |
| `build_panel_brief` 可能在某些场景下数据不足 | 三个数据源现已全部 JSON 结构化，数据可用的可靠性大幅提升 |
| 评分严格化可能导致更多修订被回退 | 原版用严格比较运行良好——0.5 容忍区间是重构版为容忍评分波动加的，现在 JSON 修复后评分更稳定 |
