# Phase 3b 重构版对齐原版 — 实施计划（完整版）

## 差异总览

| 维度 | 原版 | 重构版 | 需对齐？ |
|------|------|--------|:--:|
| 最大轮数 | 4 | 3 | ✅ → 4 |
| 弱章识别 | `gen_brief.py --auto`（全文评估 weakest_chapter） | `_parse_review_weak_chapters()`（关键词匹配） | ✅ → 用原版方式 |
| 每轮修订章节数 | **1 章** | **多章** | ✅ → 1 章 |
| 修订前/后评分 | ❌ 无 | ✅ 有 | ✅ → 去掉 |
| brief 生成 | `build_auto_brief()` 一步到位 | `build_auto_brief()` → fallback | ✅ → 简化为单步 |
| apply_cuts | 每轮结束**一次全局** | **每章修订后**都裁剪 | ✅ → 全局一次 |
| 第二停止条件 | `stars≥4 && qualified/total>0.5` | ❌ 无 | ✅ → 补上 |
| 最终全文评估 | ❌ 无 | ✅ evaluate_full() | ✅ → 去掉 |
| 审阅 prompt | 双角色简单风格 | 五维结构化 + 大纲 | ✅ → 对齐 |
| 手稿截断 | 全文（不截断） | [:30000] | ✅ → 不截断 |
| 审阅解析 | `--parse` 子命令 | 内联关键词计数 | ⚠️ 保留内联，增强 |

---

## 修改清单（3 个文件，10 项改动）

### 目标链路

```
for rnd in 1..4:
    ① run_review_loop()          → 深度审阅（全文发送，双角色 prompt）
    ② 解析 JSON                  → stars, major_items, total_items, qualified_items
    ③ 停止条件检查:
       — stars >= 4.5 && major_items == 0  → 结束
       — stars >= 4 && qualified/total > 0.5 → 结束
    ④ build_auto_brief()         → 选最弱章，生成 1 个 brief
    ⑤ revise_chapter(最弱章, brief)
    ⑥ run_apply_cuts("all")      → 全局机械清理
```

---

### 改 F9: `prompts/review_prompts.py` — 审阅 prompt 对齐原版

**文件**: [`prompts/review_prompts.py`](prompts/review_prompts.py)

重写 `build_review_prompt()`：

- ❌ 去掉 `outline_text` 参数（原版不传大纲）
- ❌ 去掉 `[:30000]` 截断（原版全文发送）
- ✅ 改为原版双角色风格（文学评论家 + 小说教授）
- ✅ 末尾保留结构化摘要（便于程序解析 stars / major / total / qualified）
- ✅ 更新 `REVIEW_SYSTEM_PROMPT` 对齐原版语气

---

### 改 F10: `revision/review.py` — 调用适配 + 解析增强

**文件**: [`revision/review.py`](revision/review.py)

- 从 outline.md 首行提取书名，传入新的 `build_review_prompt(manuscript, title=title)`
- 从末尾结构化摘要提取 `qualified_items`（正则匹配"合格问题数: N"）

---

### 改 F1: 最大轮数 3 → 4

**文件**: [`pipeline_orchestrator.py`](pipeline_orchestrator.py)

`_run_review_revision_loop()` 默认参数 + 调用处：`3 → 4`

---

### 改 F2: 删除 `_parse_review_weak_chapters()` 函数

删除整个嵌套函数定义（约 50 行）。

---

### 改 F3: 弱章识别改为 `build_auto_brief()` 单章方式

每轮只修订 1 章（`build_auto_brief()` 返回的最弱章），不是多章循环。

---

### 改 F4: 去掉修订前后评分和回退逻辑

删除 Phase 3b 中所有 `pre_score` / `post_score` / commit / revert 代码。

---

### 改 F5: 简化 brief 生成（无 fallback）

直接 `build_auto_brief()`，失败则 `continue` 跳到下一轮。

---

### 改 F6: apply_cuts 从每章 → 每轮全局

当前每章修订后都裁剪 → 改为每轮结束后全局执行一次 `run_apply_cuts("all")`。

---

### 改 F7: 补充第二停止条件

对齐原版：`stars >= 4 && total_items > 0 && qualified / total_items > 0.5` 时停止。

---

### 改 F8: 删除最终 `evaluate_full()`

删除 Phase 3b 末尾的全文评估调用。

---

## 执行顺序

| 顺序 | 文件 | 改动 |
|------|------|------|
| 1 | `prompts/review_prompts.py` | F9: 重写 prompt |
| 2 | `revision/review.py` | F10: 适配调用 + 增强解析 |
| 3 | `pipeline_orchestrator.py` | F2: 删除 _parse_review_weak_chapters |
| 4 | 同上 | F3+F4+F5: 重写修订循环 |
| 5 | 同上 | F6: apply_cuts 全局 |
| 6 | 同上 | F7: 第二停止条件 |
| 7 | 同上 | F1: 最大轮数 3→4 |
| 8 | 同上 | F8: 删除最终 evaluate_full |
| 9 | — | 编译验证 |

---

## 改动量

| 改动 | 文件 | 操作 | 估算 |
|------|------|------|------|
| F9 | `prompts/review_prompts.py` | 重写 prompt + 去截断 + 去大纲 | +25 / -20 |
| F10 | `revision/review.py` | 适配调用 + 增强解析 | +10 / -5 |
| F1-F8 | `pipeline_orchestrator.py` | 循环结构对齐 | +30 / -145 |
| **合计** | **3 个文件** | | **约 +65 / -170 行** |
