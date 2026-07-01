# reader_panel JSON 结构化 — 修改方案计划

## 诊断结论

### 问题比 `adversarial_edit` 更严重：不仅是 JSON 不解析，而是架构结构不匹配

| 维度 | 原版 | 重构版 |
|------|------|--------|
| 评审粒度 | **整本小说**一次调用（4 读者 × 1 次 = 4 次 API） | **逐章评审**多次调用（4 读者 × N 章 = 最多 32 次 API） |
| Prompt 格式 | 要求 JSON（10 字段模板） | 要求自然语言（8 个问题） |
| 响应解析 | ✅ markdown剥离→{定位→深度匹配 | ❌ 不解析，保存原始字符串 |
| 保存结构 | `readers[role] = {momentum_loss: "...", worst_scene: "..."}`（平铺 dict） | `readers[role] = {ch01: {chapter, response}, ch02: {...}}`（嵌套 dict） |
| disagreements 算法 | 解析各 question 中章节号对比 | 负面关键词子串搜索 |

### 消费者期望的结构 vs 实际产出的结构

```
消费者期望（5 个消费者一致）:
  readers[role_key] = {
    "momentum_loss": "Ch 7 节奏拖沓...",
    "worst_scene": "Ch 12 最弱...",
    "cut_candidate": "...",
    "best_scene": "...",
    "thinnest_character": "...",
    "missing_scene": "...",
    "earned_ending": "..."
  }

实际产出:
  readers[role_key] = {
    "ch01": {"chapter": 1, "response": "一大段原始文本..."},
    "ch02": {"chapter": 2, "response": "一大段原始文本..."}
  }
```

**所有 5 个消费者都在 `readers[role_key]` 上调用 `.get("momentum_loss")` 等字段名 → 全部返回空。**

---

## 消费者完整追踪

| # | 消费者 | 位置 | 读取方式 | 失败原因 |
|---|--------|------|----------|----------|
| 1 | `_parse_panel_consensus()` | [`pipeline_orchestrator.py:392-396`](pipeline_orchestrator.py:392) | `answers.get(question, "")` — 期望 `answers` 是 `{momentum_loss: "...", ...}` | `answers` 实际是 `{ch01: {...}, ch02: {...}}` |
| 2 | `panel_mentions_for_chapter()` | [`gen_brief.py:229-231`](revision/gen_brief.py:229) | `reader_data.get(key, "")` — 期望 reader_data 是 `{momentum_loss: "...", ...}` | `reader_data` 实际是 `{ch01: {...}, ch02: {...}}` |
| 3 | `build_panel_brief()` | [`gen_brief.py:258-424`](revision/gen_brief.py:258) | 调用 `panel_mentions_for_chapter()` → 同 #2 | 同 #2 |
| 4 | `build_auto_brief()` | [`gen_brief.py:864-891`](revision/gen_brief.py:864) | 调用 `panel_mentions_for_chapter()` → 同 #2 | 同 #2 |
| 5 | `_build_fallback_brief()` | [`pipeline_orchestrator.py:486-491`](pipeline_orchestrator.py:486) | `d.get("chapter")`, `d.get("question")`, `d.get("flagged_by")` ← 只读 disagreements | ⚠ 部分可用（disagreements 结构匹配） |

---

## 修改方案

### 设计决策：保持逐章架构 + 聚合为消费者兼容格式

保持重构版的"逐章评审"架构（更细粒度），但将每个读者的逐章结构化响应**聚合**为消费者期望的平铺 dict 格式。

### 改 1：`prompts/reader_panel_prompts.py` — prompt 改为请求 JSON

将 [`build_reader_panel_prompt()`](prompts/reader_panel_prompts.py:33) 的 8 个自然语言问题改为 JSON 输出，字段对齐消费者期望的 7 个维度：

```python
# 修改后的 prompt 核心片段
"""
请从以下 7 个维度评审本章，用纯 JSON 回复（不含 markdown 代码块标记）：

{
  "momentum_loss": "本章是否在某个位置节奏拖沓、失去推进力？...",
  "worst_scene": "本章最薄弱的场景/段落是什么？...",
  "cut_candidate": "如果本章必须删减 15%，你会从哪里删？...",
  "best_scene": "本章最好的场景/段落是什么？...",
  "thinnest_character": "本章中哪个角色最单薄？...",
  "missing_scene": "本章是否缺少某个应有的场景？...",
  "earned_ending": "本章的结尾是否有力量？..."
}

请直接输出 JSON，不要加 ```json``` 代码块。
"""
```

同时更新 `READER_SYSTEM_PROMPT` 增加 "始终用纯 JSON 回复，不含 markdown 代码块标记"。

### 改 2：`revision/reader_panel.py` — 三个阶段重构

**新增三个函数**：

1. `_parse_json_response(text)` — 复用 `adversarial_edit.py` 的三级回退逻辑（markdown剥离→直接解析→深度匹配）

2. `_aggregate_reader_responses(per_chapter, reader_name)` — 将 `{1: {momentum_loss: "..."}, 2: {...}}` 聚合为 `{momentum_loss: "[第1章] ...\n[第2章] ...", ...}`

3. `_find_disagreements_structured(aggregated, chapter_list)` — 基于聚合后的结构化数据，对每个 question 找出部分读者标记、部分未标记的章节（对齐原版算法）

**`run_reader_panel()` 流水线三个阶段**：

```
阶段1: 逐章评审 + JSON 解析
  for role → for chapter:
    call_judge(prompt) → raw response
    parsed = _parse_json_response(raw)
    保存: per_chapter_raw[role][ch_num] = {chapter, raw_output, **parsed}

阶段2: 聚合
  for role:
    aggregated[role] = _aggregate_reader_responses(per_chapter_raw[role])
    → {momentum_loss: "[第3章] ...\n[第7章] ...", ...}

阶段3: disagreements
  disagreements = _find_disagreements_structured(aggregated, chapter_nums)

保存:
  panel_data = {
    readers: aggregated,           ← ★ 消费者兼容格式
    disagreements: disagreements,  ← ★ 结构化分歧
    _raw_per_chapter: ...          ← 调试保留
  }
```

### 修改后 reader_panel.json 结构

```json
{
  "timestamp": "2026-07-01T...",
  "readers": {
    "plot_reader": {
      "momentum_loss": "[第3章] 中段派系会议场景拖沓…\n[第7章] 结尾节奏突然加快…",
      "worst_scene": "[第3章] 开头对话过于直白…",
      "cut_candidate": "[第5章] 第二章节约500字不影响情节…",
      "best_scene": "[第2章] 结尾段落张力十足…",
      "thinnest_character": "[第4章] 配角张三缺乏动机…",
      "missing_scene": "[第6章] 需要一场师徒对话…",
      "earned_ending": "[第1章] 结尾戛然而止但有力…"
    }
  },
  "disagreements": [
    {
      "question": "momentum_loss",
      "chapter": 3,
      "flagged_by": ["plot_reader", "prose_reader"],
      "not_flagged": ["character_reader", "general_reader"]
    }
  ],
  "_raw_per_chapter": { /* 逐章原始数据，调试用 */ }
}
```

---

## 消费者兼容性

| 消费者 | 读取代码 | 修改后 | 状态 |
|--------|----------|--------|------|
| `_parse_panel_consensus:392` | `answers.get("momentum_loss", "")` | 非空字符串 | ✅ |
| `panel_mentions_for_chapter:229` | `reader_data.get("momentum_loss", "")` | 如 "[第3章] 中段…" | ✅ |
| `panel_mentions_for_chapter:239` | `d.get("chapter")`, `d.get("question")` | 完全可用 | ✅ |
| `build_panel_brief:267` | 调用 panel_mentions_for_chapter | 返回有效数据 | ✅ |
| `build_auto_brief:867` | 调用 panel_mentions_for_chapter | 返回有效数据 | ✅ |
| `_build_fallback_brief:487` | `d.get("chapter")`, `d.get("flagged_by")` | 完全可用 | ✅ |

---

## 修改清单

| 顺序 | 文件 | 改动摘要 | 风险 |
|------|------|----------|------|
| 1 | `prompts/reader_panel_prompts.py` | prompt → JSON（7 字段），system_prompt 强调纯 JSON | 低 |
| 2 | `revision/reader_panel.py` | +3 函数 + 重写 `run_reader_panel()` 三阶段流水线 | 中 |
| 3 | 手动测试 | 单章评审 → 验证 JSON 解析 → 验证聚合 → 验证 disagreements | — |

## 风险

| 风险 | 缓解 |
|------|------|
| LLM 不返回 JSON | `_parse_json_response()` 返回 `{}` → 该章字段为空 → 聚合时跳过 |
| 聚合后文本过长导致 disagreements 正则误匹配 | 每章回答截断至 500 字 |
| 聚合前缀 `[第N章]` 与消费者正则 `第\s*N\s*章` 兼容性 | 前缀格式 `[第3章]` 确保正则能匹配（`\s*` 匹配 `]` 后的空格） |
