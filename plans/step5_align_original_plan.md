# Step 5 重构版对齐原版 — 详细实施计划

## 前提约束

| 维度 | 决定 |
|------|------|
| 评分采集方式 | **不改** — `evaluate_chapter_stable()` (3 次中位数) 保留 |
| 评分上下文 | **对齐原版** — 补充 world / characters / prev_chapter_tail 到评估 prompt |
| slop_penalty 扣分 | **对齐原版** — 对 `overall_score` 执行 `max(0, raw - slop_penalty)` |
| Brief 生成 | **对齐原版** — 替换为 `build_panel_brief()` 单源富摘要 |
| 评分比较 | **对齐原版** — `post_score >= pre_score` (严格比较) |
| 额外修订路径 | **删除** — Step 5b 采样 + Step 5c 跨卷 + Step 5d 合并队列 |

---

## 修改清单（3 个文件，共 7 项改动）

```
文件依赖关系:
  D1 (eval_judge_prompts.py) ──┐
                                ├──→ D3 (pipeline_orchestrator.py)
  D2 (evaluate.py) ────────────┘
  
  D1/D2 无相互依赖，可并行执行。D3 依赖 D1/D2 完成后验证。
```

---

## 改 D1: `prompts/eval_judge_prompts.py` — `build_chapter_eval_prompt()` 补充上下文参数

**文件**: [`prompts/eval_judge_prompts.py:279`](prompts/eval_judge_prompts.py:279)

### D1-1. 函数签名扩展

当前签名:
```python
def build_chapter_eval_prompt(
    ch_num: int,
    chapter_text: str,
    chapter_outline: str = "",
    voice_text: str = "",
    canon_text: str = "",
) -> str:
```

改为:
```python
def build_chapter_eval_prompt(
    ch_num: int,
    chapter_text: str,
    chapter_outline: str = "",
    voice_text: str = "",
    canon_text: str = "",
    world_text: str = "",             # ★ 新增：世界观
    characters_text: str = "",        # ★ 新增：角色注册表
    prev_chapter_tail: str = "",      # ★ 新增：前章末尾
) -> str:
```

### D1-2. 新增上下文节注入

在现有 `voice_section` / `canon_section` 之后，新增三个 context section：

```python
# ★ 新增：世界观节（截断至 4000 字，对齐原版 world[:4000]）
world_section = ""
if world_text:
    world_section = f"""
【世界观设定（world.md，节选）】
{world_text[:4000]}

请在评估中检查：本章场景是否与世界观设定一致？
地理位置、社会规则、技术水平等是否有矛盾？
"""

# ★ 新增：角色注册表节（截断至 4000 字）
characters_section = ""
if characters_text:
    characters_section = f"""
【角色注册表（characters.md，节选）】
{characters_text[:4000]}

请在评估中检查：本章角色行为/对话/动机是否与角色设定一致？
是否有角色 OOC（性格不一致）的地方？
"""

# ★ 新增：前章末尾节（截断至 3000 字，对齐原版 prev_chapter_tail）
prev_section = ""
if prev_chapter_tail:
    prev_section = f"""
【前一章末尾（连续性检查用）】
{prev_chapter_tail[:3000]}

请在评估 continuity 维度时检查：
本章的开头是否与前一章的结尾在情节/情绪/角色状态上无缝衔接？
"""
```

### D1-3. 放宽截断限制

当前截断过短，对齐原版：

| 数据源 | 当前截断 | 改为 |
|--------|---------|------|
| `voice_text` | 2000 字 | 4000 字 |
| `canon_text` | 2000 字 | 不截断（对齐原版全文传入） |

### D1-4. prompt 组装插入新节

在 return 的 f-string 中，`{canon_section}` 之后插入 `{world_section}{characters_section}{prev_section}`。

---

## 改 D2: `evaluation/evaluate.py` — `evaluate_chapter()` 补充上下文加载 + slop 扣分

**文件**: [`evaluation/evaluate.py:460`](evaluation/evaluate.py:460)

### D2-1. 加载 world.md 和 characters.md

在函数体开头（`chapter_text` 加载之后），新增：

```python
# ★ 对齐原版：加载评估所需的全部上下文
world_path = OUTPUT_DIR / "world.md"
world_text = world_path.read_text(encoding="utf-8") if world_path.exists() else ""

chars_path = OUTPUT_DIR / "characters.md"
characters_text = chars_path.read_text(encoding="utf-8") if chars_path.exists() else ""

# ★ 对齐原版：读取前章末尾 3000 字
prev_tail = ""
if ch_num > 1:
    prev_path = CHAPTERS_DIR / f"ch_{ch_num - 1:02d}.md"
    if prev_path.exists():
        prev_full = prev_path.read_text(encoding="utf-8")
        prev_tail = prev_full[-3000:] if len(prev_full) > 3000 else prev_full
else:
    prev_tail = "（第一章，无前章）"
```

### D2-2. 传给 build_chapter_eval_prompt()

当前调用:
```python
prompt = build_chapter_eval_prompt(
    ch_num, chapter_text,
    chapter_outline=outline, voice_text=voice, canon_text=canon,
)
```

改为:
```python
prompt = build_chapter_eval_prompt(
    ch_num, chapter_text,
    chapter_outline=outline, voice_text=voice, canon_text=canon,
    world_text=world_text,             # ★ 新增
    characters_text=characters_text,   # ★ 新增
    prev_chapter_tail=prev_tail,       # ★ 新增
)
```

### D2-3. slop_penalty 扣分

当前 `evaluate_chapter()` 执行 slop 检测但不修改 `overall_score`。
对齐原版 [`evaluate.py:705-708`](autonovel-原版/evaluate.py:705)，在 JSON 解析之后：

```python
# ★ 对齐原版：机械 slop 扣分
mech = slop_score_zh(chapter_text)
if "overall_score" in parsed and isinstance(parsed.get("overall_score"), (int, float)):
    raw_score = parsed["overall_score"]
    slop_penalty = mech.get("slop_penalty", 0)
    adjusted = max(0, raw_score - slop_penalty)
    parsed["raw_judge_score"] = raw_score        # ★ 保留原始评分供分析
    parsed["overall_score"] = round(adjusted, 2)
    parsed["slop_penalty_applied"] = slop_penalty
```

> **注意**: 需要确保 `slop_score_zh()` 调用在 `_parse_json_response()` 之前执行（当前已在第 475 行执行，但 `mech` 变量在解析循环外。需要把 `mech` 的作用域扩展到 JSON 解析后的扣分逻辑处）。

---

## 改 D3: `pipeline_orchestrator.py` — `run_revision()` 简化

**文件**: [`pipeline_orchestrator.py:537`](pipeline_orchestrator.py:537)

### D3-1. 替换 Step 5 brief 生成逻辑

**位置**: 第 602-618 行

当前代码:
```python
try:
    generate_brief(ch_num, panel_data=panel_path, output_path=brief_file, retries=2, max_total_time=1200)
    if brief_file.exists():
        brief_text = brief_file.read_text(encoding="utf-8")
        if len(brief_text) < 500 or "未给出具体修订建议" in brief_text:
            raise ValueError("面板摘要内容不足，回退多源摘要")
except:
    brief_content = _build_fallback_brief(
        ch_num, f"共识修订 循环{cycle}: {question}",
        label=f"共识修订 ({question})"
    )
    brief_file.write_text(brief_content, encoding="utf-8")
```

改为:
```python
from revision.gen_brief import build_panel_brief

brief_text = build_panel_brief(ch_num)
brief_file.write_text(brief_text, encoding="utf-8")
```

### D3-2. 修改评分容忍区间（共识修订）

**位置**: 第 637 行

```python
# 改前:
if post_score >= pre_score - 0.5:

# 改后:
if post_score >= pre_score:
```

### D3-3. 删除 Step 5b: 采样评估

**删除范围**: 第 652-799 行

删除内容:
- `_sample_evaluate_volumes()` 嵌套函数定义（第 654-689 行，约 36 行）
- `# ——— 执行采样评估 ———` 注释块 + `sample_weaks` 调用（第 789-799 行）
- `sample_weaks` 变量的所有后续引用

### D3-4. 删除 Step 5c: 跨卷一致性审阅

**删除范围**: 第 691-807 行

删除内容:
- `_cross_volume_consistency_review()` 嵌套函数定义（第 692-787 行，约 96 行）
- `# ——— 执行跨卷一致性审阅 ———` + `cross_broken` 调用（第 801-807 行）
- `cross_broken` 变量的所有后续引用

### D3-5. 删除 Step 5d: 合并修订队列

**删除范围**: 第 809-944 行

删除内容:
- `# ★ 全文评估提前到合并修订之前执行` 注释块（第 809-823 行）→ 移到共识修订后
- `# ——— 合并修订队列 ———` + `combined_targets` 构建（第 839-852 行）
- `# ——— 逐章修订合并队列 ———` + `for ch_num, reason` 循环（第 854-944 行，约 90 行）

### D3-6. 全文评估位置恢复

**操作**: 

1. 将第 809-823 行的 `evaluate_full` 调用块移动到共识修订循环（Step 5 `for item in consensus_items`）结束之后、平台检测之前。

2. 简化全文评估为单次调用（不用 2 次中位数）：

```python
# 改前（第 809-823 行，2 次中位数）:
step("运行全文评估 (总超时=600s, 2次取中位数) ...")
full_scores: list[float] = []
for _ in range(2):
    try:
        fe = evaluate_full(max_total_time=600)
        ns = parse_score(fe, "novel_score")
        if ns < 0:
            ns = parse_score(fe, "overall_score")
        if ns >= 0:
            full_scores.append(ns)
    except Exception:
        pass
novel_score = sorted(full_scores)[len(full_scores) // 2] if full_scores else 0.0

# 改后（对齐原版，单次调用）:
step("运行全文评估 ...")
try:
    fe = evaluate_full(max_total_time=600)
    novel_score = parse_score(fe, "novel_score")
    if novel_score < 0:
        novel_score = parse_score(fe, "overall_score")
except Exception:
    novel_score = prev_score
```

### D3-7. 修改 Phase 3b 评分容忍区间

**位置**: 第 1131 行

```python
# 改前:
if post_score >= pre_score - 0.5:

# 改后:
if post_score >= pre_score:
```

---

## 最终 Step 5 链路（修改后）

```
for cycle in range(1, max_cycles + 1):
    Step 1: run_adversarial_edit("all")
    Step 2: run_apply_cuts("all", ...)
    Step 3: run_reader_panel()
    Step 4: _parse_panel_consensus()          ← 不变
    
    Step 5: for each consensus_item:          ← 仅共识修订
        ① evaluate_chapter_stable(ch_num)     ← pre_score (3次中位数，保留)
            └─ evaluate_chapter()
                 └─ 上下文: voice + canon + world + characters + outline + prev_tail
                 └─ slop_penalty 已扣分
        ② build_panel_brief(ch_num)           ← 单源富摘要（对齐原版）
        ③ revise_chapter(ch_num, brief)
        ④ evaluate_chapter_stable(ch_num)     ← post_score
        ⑤ if post_score >= pre_score: commit  ← 严格比较
           else: revert
    
    Step 6: evaluate_full()                   ← 移到此处
    Step 7: plateau detection

Phase 3b: _run_review_revision_loop()          ← 评分容忍已对齐
```

---

## 执行顺序

| 顺序 | 文件 | 改动 | 依赖 |
|------|------|------|------|
| 1 | [`prompts/eval_judge_prompts.py`](prompts/eval_judge_prompts.py) | D1: `build_chapter_eval_prompt()` 签名扩展 + 新增 3 个 context section | 无 |
| 2 | [`evaluation/evaluate.py`](evaluation/evaluate.py) | D2: `evaluate_chapter()` 加载 world/characters/prev_tail + slop 扣分 | D1 |
| 3 | [`pipeline_orchestrator.py`](pipeline_orchestrator.py) | D3: 替换 brief + 严格比较 + 删除 5b/5c/5d + 移动全文评估 + Phase 3b 容忍 | D2 |
| 4 | 编译验证 | `python -m py_compile` 全部 3 个文件 | 全部 |

---

## 改动量汇总

| 改动 | 文件 | 操作 | 估算行数 |
|------|------|------|---------|
| D1 | `prompts/eval_judge_prompts.py` | 新增参数 + 新增 section + 放宽截断 | +50 / -5 |
| D2 | `evaluation/evaluate.py` | 新增加载 + 新增扣分 | +25 / -0 |
| D3-1 | `pipeline_orchestrator.py` | 替换 brief | +3 / -17 |
| D3-2 | `pipeline_orchestrator.py` | 严格比较（共识） | ±1 |
| D3-3 | `pipeline_orchestrator.py` | 删除采样评估 | -50 |
| D3-4 | `pipeline_orchestrator.py` | 删除跨卷审阅 | -100 |
| D3-5 | `pipeline_orchestrator.py` | 删除合并队列 | -105 |
| D3-6 | `pipeline_orchestrator.py` | 移动全文评估 + 简化 | +10 / -18 |
| D3-7 | `pipeline_orchestrator.py` | 严格比较（Phase 3b） | ±1 |
| **合计** | **3 个文件** | | **约 +90 / -295 行** |

---

## 风险评估

| 风险 | 缓解 |
|------|------|
| `build_panel_brief()` 在 panel 数据稀薄时产出薄摘要 | 现有 JSON 结构化后 panel 数据可靠性已大幅提升；且原版同样使用 `build_panel_brief()` |
| 删除采样评估可能遗漏弱章 | 共识修订覆盖被读者标记的弱章；全文评估也会识别最弱章节 |
| 删除跨卷审阅可能遗漏断裂 | 原版同样没有；Phase 3b 深度审阅会覆盖连续性检查 |
| 评分严格化导致更多修订被回退 | 原版用严格比较运行良好；JSON 修复后评分更稳定 |
| 新增 world/characters 上下文增大 prompt token | 每个都截断，总量可控（约 11K 字符 ≈ 3-4K tokens） |
