# evaluate 评估系统 JSON 结构化修复 — 修改方案计划

## 诊断结论

### 这是整个项目中第三个需要 JSON 结构化修复的子系统

与前两个修复（adversarial_edit、reader_panel）的模式完全相同：

| 维度 | 原版 `evaluate.py` | 重构版 `evaluation/evaluate.py` |
|------|-------------------|-------------------------------|
| Prompt 格式 | 要求 JSON（每维 `{score, weakest_moment, fix, note}`） | 要求 `评分: ___/10 \| 最大弱点: ___ \| 改进方案: ___` |
| 响应解析 | ✅ `parse_json_response(raw)` → 结构化 dict | ❌ 不解析，只存 `raw_output` |
| 保存格式 | 结构化 dict（15+ 字段平铺） | `{timestamp, phase, raw_output: "非结构化文本"}` |

### 特殊之处：prompt 极其庞大且已调优

重构版的 eval prompt（[`prompts/eval_judge_prompts.py`](prompts/eval_judge_prompts.py)，550 行）在维度描述上远优于原版：
- 评分校准矩阵（SCORING_CALIBRATION）
- 强制 gap+fix 要求（MANDATORY_GAP_FIX）
- 交叉检查（CHAPTER_CROSS_CHECKS）
- 最终检查（FINAL_CHECK）

直接替换成原版的简洁 prompt 会丢失这些调优。采用**混合方案**：保留现有 prompt 的认知脚手架，在末尾追加 JSON 输出要求。

---

## 消费者完整追踪

### 核心消费者（需要结构化字段）

| # | 消费者 | 位置 | 关键读取字段 | 当前状态 |
|---|--------|------|-------------|----------|
| 1 | `build_eval_brief()` | [`gen_brief.py:450-594`](revision/gen_brief.py:450) | `overall_score`, `weakest_dimension`, 各维度 `{score, weakest_moment, fix}`, `top_3_revisions`, `ai_patterns_detected`, `three_strongest_sentences`, `three_weakest_sentences` | ❌ 全部为空 |
| 2 | `build_auto_brief()` | [`gen_brief.py:806-861`](revision/gen_brief.py:806) | 同上 + full eval 的 `novel_score`, `weakest_chapter`, `top_suggestion`, 各维度 `{score, note}` | ❌ 全部为空 |
| 3 | `build_panel_brief()` | [`gen_brief.py:326-333`](revision/gen_brief.py:326) | `three_strongest_sentences` | ❌ 读不到 |
| 4 | `build_cuts_brief()` | [`gen_brief.py:671-678`](revision/gen_brief.py:671) | `three_strongest_sentences` | ❌ 读不到 |
| 5 | `_build_fallback_brief()` | [`pipeline_orchestrator.py:438-465`](pipeline_orchestrator.py:438) | `overall_score`, `weakest_dimension`, 各维度 `{score, fix}`, `top_3_revisions`, `ai_patterns_detected` | ❌ 全部为空 |
| 6 | `generate_brief()` | [`gen_brief.py:992-1003`](revision/gen_brief.py:992) | `latest_chapter_eval()` 存在性检查 | ⚠️ 文件存在但内容无效 |

### 分数消费者（不受影响）

| # | 消费者 | 位置 | 读取方式 | 状态 |
|---|--------|------|----------|------|
| 7 | `evaluate_chapter_stable()` | [`state_manager.py:441`](core/state_manager.py:441) | 调用 `evaluate_chapter()` → `parse_score(stdout)` 从 stdout 解析 | ✅ 不受影响 |
| 8 | `evaluate_foundation_stable()` | [`state_manager.py:467`](core/state_manager.py:467) | 同 #7 | ✅ 不受影响 |
| 9 | `parse_lore_score()` | [`state_manager.py:495`](core/state_manager.py:495) | 同 #7 | ✅ 不受影响 |
| 10 | `get_last_slop_penalty()` | [`evaluate.py:485`](evaluation/evaluate.py:485) | 读 `mechanical.slop_penalty`（Python 计算，非 LLM） | ✅ 不受影响 |

**结论**：分数消费者（7-10）从 `stdout` 或 `mechanical` 字段读取，不受影响。结构化消费者（1-6）都从 eval JSON 文件读取，全部失败。

---

## 修改方案：混合 prompt + JSON 解析

### 核心思路

1. **保留现有 prompt 的认知脚手架**（评分校准矩阵、交叉检查等），LLM 以自然格式思考
2. **在 prompt 末尾追加 JSON 输出要求**，让 LLM 在思考完成后输出结构化 JSON
3. **evaluate.py 解析 JSON**，保存结构化数据

### 改 1：`prompts/eval_judge_prompts.py` — 三种 prompt 末尾追加 JSON 模板

#### 单章评估 prompt — 末尾追加

当前结尾（第412行）：
```
请用中文输出。每个维度都包括：评分、最大弱点（引用原文）、具体改进方案。
强制输出字段不可省略。
```

追加为：
```python
# 替换现有结尾
【最终输出格式】
完成上述逐维度评审后，将结果汇总为以下纯 JSON（不含 markdown 代码块）:

{{
  "prose_quality": {{"score": N, "weakest_moment": "引用原文最弱段落", "fix": "具体改进方案", "note": "额外说明"}},
  "pacing": {{"score": N, "weakest_moment": "...", "fix": "...", "note": "..."}},
  "character_voice": {{"score": N, "weakest_moment": "...", "fix": "...", "note": "..."}},
  "dialogue": {{"score": N, "weakest_moment": "...", "fix": "...", "note": "..."}},
  "scene_craft": {{"score": N, "weakest_moment": "...", "fix": "...", "note": "..."}},
  "plants_seeded": {{"score": N, "weakest_moment": "...", "fix": "...", "note": "..."}},
  "canon_compliance": {{"score": N, "violations": ["列出违规项"], "note": "..."}},
  "lore_integration": {{"score": N, "weakest_moment": "...", "fix": "...", "note": "..."}},
  "engagement": {{"score": N, "weakest_moment": "...", "fix": "...", "note": "..."}},
  "three_weakest_sentences": ["引用1", "引用2", "引用3"],
  "three_strongest_sentences": ["引用1", "引用2", "引用3"],
  "ai_patterns_detected": ["检测到的 AI 写作模式"],
  "top_3_revisions": ["可操作的修订1", "修订2", "修订3"],
  "new_canon_entries": ["本章引入的新设定/事实"],
  "overall_score": N,
  "weakest_dimension": "最弱维度名称"
}}

请直接输出 JSON，不要加 ```json``` 代码块。
```

#### 全文评估 prompt — 末尾追加

当前结尾（约549行）后追加：

```python
【最终输出格式】
完成上述逐维度评审后，将结果汇总为以下纯 JSON（不含 markdown 代码块）:

{{
  "arc_coherence": {{"score": N, "note": "..."}},
  "payoff_satisfaction": {{"score": N, "note": "..."}},
  "world_consistency": {{"score": N, "note": "..."}},
  "voice_consistency": {{"score": N, "note": "..."}},
  "momentum": {{"score": N, "note": "..."}},
  "emotional_range": {{"score": N, "note": "..."}},
  "weakest_chapter": N,
  "top_suggestion": "如果只改一件事，最有杠杆效应的建议",
  "novel_score": N,
  "weakest_dimension": "最弱维度名称"
}}

请直接输出 JSON，不要加 ```json``` 代码块。
```

#### 基础构建评估 prompt — 类似追加 JSON 模板

`build_foundation_eval_prompt()` 末尾也追加对应的 JSON 模板（13 个维度）。

### 改 2：`evaluation/evaluate.py` — 新增解析 + 保存结构化

**新增 `_parse_json_response()`**（复用前两次修复的三级回退逻辑）。

**修改 `evaluate_foundation()`**（第342-384行）：
```python
# 修改前
log_path.write_text(json.dumps({
    "timestamp": ts, "phase": "foundation", "raw_output": result,
}), ...)

# 修改后
parsed = _parse_json_response(result)
log_path.write_text(json.dumps({
    "timestamp": ts, "phase": "foundation",
    "raw_output": result,   # 保留调试
    **parsed,               # 展开结构化字段
}, ...))
```

**修改 `evaluate_chapter()`**（第387-437行）：
```python
# 修改前
log_path.write_text(json.dumps({
    "timestamp": ts, "phase": "chapter", "chapter": ch_num,
    "mechanical": mech, "raw_output": result,
}), ...)

# 修改后
parsed = _parse_json_response(result)
log_path.write_text(json.dumps({
    "timestamp": ts, "phase": "chapter", "chapter": ch_num,
    "mechanical": mech,
    "raw_output": result,
    **parsed,
}), ...)
```

**修改 `evaluate_full()`**（第440-478行）：
```python
# 修改前
log_path.write_text(json.dumps({
    "timestamp": ts, "phase": "full", "chapter_count": len(chapter_files),
    "raw_output": result,
}), ...)

# 修改后
parsed = _parse_json_response(result)
log_path.write_text(json.dumps({
    "timestamp": ts, "phase": "full", "chapter_count": len(chapter_files),
    "raw_output": result,
    **parsed,
}), ...)
```

### 改 3（可选）：`JUDGE_SYSTEM_PROMPT` 更新

在 [`eval_judge_prompts.py`](prompts/eval_judge_prompts.py) 中更新 `JUDGE_SYSTEM_PROMPT`，增加 "最终输出必须是纯 JSON" 指令。

---

## 修改后 eval JSON 结构示例

### 单章评估
```json
{
  "timestamp": "20260701_140000",
  "phase": "chapter",
  "chapter": 3,
  "mechanical": { "tier1_hits": [...], "slop_penalty": 1.5, ... },
  "raw_output": "原始LLM响应（保留调试）",
  "prose_quality": { "score": 7, "weakest_moment": "第3段句子过于冗长...", "fix": "拆分为两个短句...", "note": "" },
  "pacing": { "score": 6, "weakest_moment": "中段会议场景拖沓...", "fix": "删减填充段落...", "note": "" },
  "character_voice": { ... },
  "overall_score": 6.5,
  "weakest_dimension": "pacing",
  "top_3_revisions": ["1. 删除第3-5段过度解释...", "2. 增加对话潜台词...", "3. 加强结尾张力..."],
  "three_strongest_sentences": ["...", "...", "..."],
  "three_weakest_sentences": ["...", "...", "..."],
  "ai_patterns_detected": ["眼中闪过一丝", "嘴角微微上扬"],
  "new_canon_entries": ["新角色: 张三", "新地点: 青龙镇"]
}
```

---

## 消费者兼容性验证

| 消费者 | 关键读取 | 修改后 | 状态 |
|--------|----------|--------|------|
| `build_eval_brief:450` | `ch_eval.get("overall_score")` | 有值 | ✅ |
| `build_eval_brief:460-493` | `ch_eval.get(dk).get("score")` | 有值 | ✅ |
| `build_auto_brief:810` | `ch_eval.get("overall_score")` | 有值 | ✅ |
| `build_panel_brief:329` | `ch_eval.get("three_strongest_sentences")` | 非空 list | ✅ |
| `build_cuts_brief:674` | 同上 | 非空 list | ✅ |
| `_build_fallback_brief:443` | `ch_eval.get("overall_score")` | 有值 | ✅ |
| `evaluate_chapter_stable` | stdout → `parse_score()` | 不变 | ✅ |
| `get_last_slop_penalty` | `mechanical.slop_penalty` | 不变 | ✅ |

---

## 修改清单

| 顺序 | 文件 | 改动 | 风险 |
|------|------|------|------|
| 1 | `prompts/eval_judge_prompts.py` | 三种 prompt 末尾追加 JSON 输出模板；更新 `JUDGE_SYSTEM_PROMPT` | 中：prompt 调优可能影响评分质量 |
| 2 | `evaluation/evaluate.py` | +`_parse_json_response()`；`evaluate_foundation/chapter/full` 保存时 `**parsed` 展开 | 低：向后兼容 |
| 3 | 编译验证 | `py_compile` 全部文件 | — |

## 风险

| 风险 | 缓解 |
|------|------|
| 追加 JSON 要求可能降低 LLM 思考质量 | 保留全部认知脚手架在前，JSON 输出在最后；如评分异常可在后续迭代中回退 |
| `parse_score()` 仍需从 stdout 提取分数（兼容性） | `evaluate_chapter/foundation/full` 继续 `print(result)` 到 stdout，`parse_score` 不受影响 |
| JSON 模板中的字段名必须与消费者完全一致 | 字段名直接从 gen_brief.py 实际读取的 key 复制 |
