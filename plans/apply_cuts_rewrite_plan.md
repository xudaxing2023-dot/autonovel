# Step 2 apply_cuts 对齐原版 — 修改方案计划

## 诊断

| | 原版 [`autonovel-原版/apply_cuts.py`](autonovel-原版/apply_cuts.py) | 重构版 [`revision/apply_cuts.py`](revision/apply_cuts.py) |
|---|---|---|
| 行数 | 270 行 | 40 行（占位桩） |
| 核心函数 | `find_and_remove()`, `process_chapter()` 等 6 个 | 无（只有占位 `run_apply_cuts()`） |
| 实际效果 | 真正修改章节文件，删除赘语段落 | 只列出 cuts 文件名，不修改任何文本 |
| 调用方式 | CLI（`argparse`） | 函数调用 `run_apply_cuts(target, types, min_fat)` |

### 重构版调用链路

[`pipeline_orchestrator.py`](pipeline_orchestrator.py) 中两处调用：

```python
# Phase 3 Step 2 (line 573) — 全章节裁剪
run_apply_cuts("all", ["OVER-EXPLAIN", "REDUNDANT"], min_fat=15)

# Phase 3b 审阅修订 (line 1158) — 单章裁剪
run_apply_cuts(str(ch_num), ["OVER-EXPLAIN", "REDUNDANT"], min_fat=15)
```

接口签名必须保持：`run_apply_cuts(target: str, types: list | None, min_fat: int) -> None`

---

## 修改方案

### 策略：移植原版 6 个核心函数 + 保留重构版接口包装

| 函数 | 原版行号 | 作用 | 中文适配点 |
|------|---------|------|-----------|
| `load_cuts(chapter_num)` | 26-36 | 加载单章 cuts JSON | 路径改为 `EDIT_LOGS_DIR` |
| `chapter_path(chapter_num)` | 39-40 | 构造章节文件路径 | 路径改为 `CHAPTERS_DIR` |
| `find_and_remove(text, quote)` | 43-76 | 精确匹配 + 空白标准化回退 | `MIN_QUOTE_LEN` 改为 20 字符 |
| `collapse_blank_lines(text)` | 79-81 | 合并 3+ 空行 → 2 空行 | 不变 |
| `discover_chapters()` | 84-91 | 扫描有 cuts 文件的章节 | 路径改为 `EDIT_LOGS_DIR` |
| `process_chapter(...)` | 94-183 | 逐章裁剪主逻辑 | 字数统计改为中文字符 |

### 关键适配

#### 1. 字数统计：英文词数 → 中文字符

```python
def char_count(text: str) -> int:
    return len(text.replace(" ", "").replace("\n", "").replace("\r", ""))
```

#### 2. MIN_QUOTE_LEN：25 → 20

原版 `25`（英文单词场景），中文改为 `20` 字符。cuts.json 中的 `quote` 字段是 LLM 引用的原文字符串。

#### 3. VALID_TYPES 扩充

原版：`{"OVER-EXPLAIN", "REDUNDANT", "FAT", "TELL", "STRUCTURAL", "GENERIC"}`
更新为：`{"FAT", "REDUNDANT", "OVER-EXPLAIN", "TELL", "SLOP", "STRUCTURAL", "GENERIC"}`
（`SLOP` 是我们在 adversarial prompt 中新增的分类标签）

#### 4. 日志输出

原版用 `print()`，重构版改为 `step()`。

#### 5. cut 对象字段名

cuts.json 中每个 cut 有 `quote`, `type`, `reason`, `action`, `rewrite` —— 这与我们修复后的 adversarial_edit 产出的字段完全一致，无需适配。

---

## 完整伪代码

```
run_apply_cuts(target, types, min_fat):
  type_filter = set(types)

  if target == "all":
    chapters = discover_chapters()  # 扫描 edit_logs/ch*_cuts.json
  else:
    chapters = [int(target)]

  for ch_num in chapters:
    stats = process_chapter(ch_num, type_filter, min_fat)
    # 汇总统计

process_chapter(ch_num, type_filter, min_fat):
  data = load_cuts(ch_num)
  if data is None: return

  fat_pct = data.get("overall_fat_percentage", 0)
  if fat_pct < min_fat: return  # 赘语不够多，跳过

  cuts = data.get("cuts", [])
  text = chapter_path(ch_num).read_text()

  for cut in cuts:
    if cut.type not in type_filter: skip
    if len(cut.quote) < 20: skip
    new_text, ok = find_and_remove(text, cut.quote)
    if ok: text = new_text

  text = collapse_blank_lines(text)
  chapter_path(ch_num).write_text(text)  # 真正写回

find_and_remove(text, quote):
  if text.count(quote) == 1:
    return text.replace(quote, "", 1), True   # 精确匹配

  # 空白标准化回退
  norm_quote = re.sub(r"\s+", " ", quote).strip()
  tokens = norm_quote.split()
  pattern = r"\s+".join(re.escape(t) for t in tokens)
  matches = re.finditer(pattern, text)
  if 唯一匹配:
    删除该区间 → 返回新文本, True

  return text, False  # 未找到或歧义
```

---

## 修改文件清单

| 文件 | 改动 | 行数 |
|------|------|------|
| [`revision/apply_cuts.py`](revision/apply_cuts.py) | 完全重写 | 40 → ~155 行 |

## 风险

| 风险 | 缓解 |
|------|------|
| 中文 quote 匹配失败 | 两层匹配：精确子串优先，空白标准化回退兜底 |
| 删除后文本格式破坏 | `collapse_blank_lines()` 修复 3+ 空行 |
| LLM 产出的 quote 不够精确 | adversarial prompt 要求 "20 字以上，确保可唯一定位" |
| cuts.json 解析失败（raw_output 场景） | JSON 修复后 cuts.json 已结构化，`load_cuts` 有异常保护 |