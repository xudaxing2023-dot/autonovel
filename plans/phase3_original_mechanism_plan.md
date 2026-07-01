# Phase 3 重构为原版机制 — 修改方案

## 目标

将重构版（当前 `pipeline_orchestrator.py`）的复杂多路径修订简化为原版 `autonovel-原版` 的简洁单循环，同时保留重构版中已验证的改进。

---

## 当前 vs 目标对比

```
当前（重构版）                          目标（原版化）
═══════════════════════════════        ═══════════════════════════
for cycle:                            for cycle:
  Step 1: adversarial(破损)              Step 1: adversarial(修复→JSON)
  Step 2: apply_cuts(桩)                Step 2: apply_cuts(修复→真正裁剪)
  Step 3: reader_panel                  Step 3: reader_panel
  Step 4: parse_consensus               Step 4: parse_consensus
  Step 5: consensus_revision            Step 5: consensus_revision(富摘要)
    generate_brief → 回退 → fallback       build_panel_brief_v2(四源聚合)
  Step 5b: sample_evaluate              (删除)
  Step 5c: cross_volume                 (删除)
  Step 5d: combined_revision            (删除)
  Step 6: full_evaluation               Step 6: full_evaluation
  Step 7: plateau_detection             Step 7: plateau_detection

Phase 3b: 审阅修订闭环(broken)          Phase 3b: 修复后保留
```

---

## 修改清单（共 6 个文件）

### 改 1: `prompts/adversarial_prompts.py` — prompt 改为请求 JSON

**当前问题**：prompt 要求非结构化文本输出（`位置:/分类:/理由:/建议操作:`）

**改为**：请求结构化 JSON，字段对齐原版，分类适配中文：

```json
{
  "cuts": [
    { "quote": "原文引用(20+字)", "type": "OVER-EXPLAIN|REDUNDANT|FAT|TELL|SLOP|STRUCTURAL",
      "reason": "为什么该删", "action": "CUT|REWRITE",
      "rewrite": "替换文本(仅REWRITE时)" }
  ],
  "total_cuttable_chars": 450,
  "tightest_passage": "最精炼的2-3句",
  "loosest_passage": "最拖沓的2-3句",
  "overall_fat_percentage": 15,
  "one_sentence_verdict": "一句话评价"
}
```

`SYSTEM_PROMPT` 要求输出纯 JSON，不含 markdown 代码块。

### 改 2: `revision/adversarial_edit.py` — 增加 JSON 解析

**当前问题**：只保存 `raw_output`，不解析

**改为**：增加 `_parse_json_response()`（markdown 剥除 + 括号匹配回退），保存结构化 JSON：

```python
parsed = _parse_json_response(result)
cuts_data = {
    "chapter": ch_num, "timestamp": datetime.now().isoformat(),
    **parsed,  # 展开 cuts, total_cuttable_chars 等
}
cuts_path.write_text(json.dumps(cuts_data, ensure_ascii=False, indent=2), ...)
```

### 改 3: `revision/apply_cuts.py` — 完整重写

**当前问题**：占位桩

**改为**：实现原版的 `find_and_remove()` + `process_chapter()`，适配中文：

- 精确子串匹配 `text.replace(quote, "", 1)`
- 空白标准化回退（`re.compile` 逐字匹配）
- `collapse_blank_lines` 合并多余空行
- 写回章节文件
- 新增 `--types` 和 `--min-fat` 参数

### 改 4: `revision/gen_brief.py` — 新增 `build_panel_brief_v2()`

**当前问题**：`_build_fallback_brief` 产出空洞模板

**改为**：实现四源聚合的富摘要生成：

```python
def build_panel_brief_v2(ch_num: int) -> str:
    # ① reader_panel.json → 提取 4 读者完整评论
    # ② chXX_cuts.json → tightest_passage, loosest_passage
    # ③ eval_logs/chapter_XX_*.json → strongest/weakest sentences, top_3_revisions
    # ④ voice.md → 文风规则
    # → 组装 PROBLEM / KEEP / CHANGE / VOICE / TARGET
```

### 改 5: `pipeline_orchestrator.py` — 简化 `run_revision()`

**删除**的代码块：

| 删除项 | 当前行号范围 |
|--------|-------------|
| `_sample_evaluate_volumes()` 嵌套函数 | ~652-689 |
| `_cross_volume_consistency_review()` 嵌套函数 | ~689-787 |
| 采样评估执行 (`sample_weaks = ...`) | ~789-799 |
| 跨卷审阅执行 (`cross_broken = ...`) | ~801-807 |
| 合并修订队列 + 执行 (`combined_targets` + `for ch_num, reason`) | ~809-915 |

**替换**的代码块：

Step 5 共识修订的 brief 生成逻辑：
```python
# ❌ 当前（复杂但空洞）
try:
    generate_brief(ch_num, panel_data=panel_path, ...)
    if len(brief_text) < 500: raise ValueError
except:
    brief_content = _build_fallback_brief(ch_num, context, label)
    brief_file.write_text(brief_content)

# ✅ 改为（简洁且丰富）
brief_text = build_panel_brief_v2(ch_num)
brief_file.write_text(brief_text)
```

### 改 6: Phase 3b — 保持不变（BUG-1 已修复）

之前已修复 `_parse_review_weak_chapters` 的 `total` → `chapter_count` 变量遮蔽。无需额外修改。

---

## 修改顺序

| 顺序 | 文件 | 改动 | 依赖 |
|------|------|------|------|
| 1 | `prompts/adversarial_prompts.py` | prompt → JSON | - |
| 2 | `revision/adversarial_edit.py` | +JSON 解析 | 改1 |
| 3 | `revision/apply_cuts.py` | 完全重写 | 改2 |
| 4 | `revision/gen_brief.py` | +`build_panel_brief_v2()` | 改2,3 |
| 5 | `pipeline_orchestrator.py` | 简化循环 + 替换 brief 调用 | 改4 |
| 6 | 编译验证 | `py_compile` | 全部 |

---

## 风险评估

| 风险 | 缓解 |
|------|------|
| 删除采样评估后遗漏弱章 | 共识修订覆盖被读者标记的弱章；全文评估会识别 |
| LLM JSON 输出不稳定 | `_parse_json_response` 有 markdown 剥除 + 括号匹配回退 |
| 中文 quote 匹配失败 | 精确匹配 + 空白标准化回退 |
| `build_panel_brief_v2` 首次实现可能不完善 | 基于已验证的原版逻辑，路径适配即可 |
