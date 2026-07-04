# Step 6 全文评估对齐原版 — 修改方案

## 全局原则：所有基础资料不截断

> 发送给 LLM 的 world / characters / voice / canon / outline / chapter_text 等基础资料，全部传入全文，不做 `[:N]` 截断。
> 此原则同时适用于 Step 5（`build_chapter_eval_prompt`）和 Step 6（`build_full_novel_eval_prompt`）。

## 差异回顾

| 维度 | 原版 | 重构版 | 需对齐？ |
|------|------|--------|:---:|
| **上下文输入** | voice + world + characters + outline + chapter_summaries | voice + outline + chapter_summaries | ✅ |
| **评分维度** | 7 维 | 6 维（缺 theme_coherence） | ✅ |
| **章节摘要** | 含每章字数 | 无字数 | ✅ |
| **基础资料截断** | world[:4000], voice 全文 | voice[:2000], outline[:3000] | ✅ 全部不截断 |
| **大纲加载** | 单文件 | 卷感知 | ⬜ 更好，保留 |
| **章节摘要构建** | 在 evaluate_full() 中 | 在 prompt builder 中 | ⬜ 保留 |

---

## 修改清单（3 个文件，含 Step 5 截断清理）

### 改 E1: `prompts/eval_judge_prompts.py` — `build_full_novel_eval_prompt()` 签名扩展 + 维度恢复

**文件**: [`prompts/eval_judge_prompts.py:505`](prompts/eval_judge_prompts.py:505)

### 改 E0: `prompts/eval_judge_prompts.py` — `build_chapter_eval_prompt()` 清理截断

> ★ 此项是对已完成的 D1 的补充修正。移除 Step 5 评估 prompt 中所有基础资料的 `[:N]` 截断。

**文件**: [`prompts/eval_judge_prompts.py`](prompts/eval_judge_prompts.py) — `build_chapter_eval_prompt()`

| 数据源 | 当前截断 | 改为 |
|--------|---------|------|
| `chapter_text` | `[:12000]` | 全文（不再截断） |
| `chapter_outline` | `[:3000]` | 全文 |
| `voice_text` | `[:4000]` | 全文 |
| `world_text` | `[:4000]` | 全文 |
| `characters_text` | `[:4000]` | 全文 |
| `prev_chapter_tail` | `[:3000]` | 全文（`prev_tail` 本身就是后 3000 字，所以这个保留原样） |

> `canon_text` 在 D1 中已经是全文，无需改动。

---

### 改 E1: `prompts/eval_judge_prompts.py` — `build_full_novel_eval_prompt()` 签名扩展 + 维度恢复

**文件**: [`prompts/eval_judge_prompts.py:505`](prompts/eval_judge_prompts.py:505)

#### E1-1. 函数签名扩展

```diff
 def build_full_novel_eval_prompt(
     manuscript_text: str = "",
     outline_text: str = "",
     voice_text: str = "",
+    world_text: str = "",
+    characters_text: str = "",
 ) -> str:
```

#### E1-2. 章节摘要增加字数统计

```diff
             for f in ch_files:
                 text = f.read_text(encoding="utf-8")
                 head = text[:500]
                 tail = text[-500:] if len(text) > 1000 else ""
                 ch_name = f.stem.replace("ch_", "")
+                wc = len(text.replace(" ", "").replace("\n", ""))
                 chapter_summaries += (
-                    f"\n### 第 {ch_name} 章 开头\n{head}\n"
+                    f"\n### 第 {ch_name} 章（{wc} 字）开头\n{head}\n"
                 )
```

#### E1-3. 新增 world / characters context section（不截断）

在 `voice_section` 之后新增:

```python
world_section = ""
if world_text:
    world_section = f"""
【世界观设定（world.md）】
{world_text}

请在评估 world_consistency 时检查：全书各章是否都与世界观设定一致？
"""

characters_section = ""
if characters_text:
    characters_section = f"""
【角色注册表（characters.md）】
{characters_text}

请在评估 arc_coherence 时检查：角色弧线是否与角色设定一致？
"""
```

#### E1-4. 移除 voice / outline 截断

| 数据源 | 当前 | 改为 |
|--------|------|------|
| `voice_text` | `[:2000]` | 全文 |
| `outline_text` | `[:3000]` | 全文 |

#### E1-5. 恢复 theme_coherence 维度（第 6 维）

在 5. momentum 之后、6. engagement 之前插入:

```
6. theme_coherence (主题一致性):
   全书的核心主题是否贯穿始终？是否有章节偏离了主线主题？
   主题是否通过情节和角色行动自然呈现（而非通过旁白说教）？
   多重主题之间是否有层次和递进？
   评分: ___/10  |  最大弱点: ___  |  改进方案: ___
```

`engagement` 顺延为第 7 维。

#### E1-6. 更新 JSON 输出字段

在 prompt 末尾 JSON 格式中增加 `"theme_coherence": {"score": N, "note": "..."}`。

---

### 改 E2: `evaluation/evaluate.py` — `evaluate_full()` 加载 world + characters

**文件**: [`evaluation/evaluate.py:515`](evaluation/evaluate.py:515)

#### E2-1. 加载 world.md 和 characters.md

在 `voice` 加载之后:

```python
world_path = OUTPUT_DIR / "world.md"
world_text = world_path.read_text(encoding="utf-8") if world_path.exists() else ""

chars_path = OUTPUT_DIR / "characters.md"
characters_text = chars_path.read_text(encoding="utf-8") if chars_path.exists() else ""
```

#### E2-2. 传入 build_full_novel_eval_prompt()

```diff
 prompt = build_full_novel_eval_prompt(
     manuscript, outline_text=outline, voice_text=voice,
+    world_text=world_text,
+    characters_text=characters_text,
 )
```

---

## 执行顺序

| 顺序 | 文件 | 改动 | 依赖 |
|------|------|------|------|
| 1 | [`prompts/eval_judge_prompts.py`](prompts/eval_judge_prompts.py) | E0: 清理 build_chapter_eval_prompt 中所有截断 | 无 |
| 2 | [`prompts/eval_judge_prompts.py`](prompts/eval_judge_prompts.py) | E1: build_full_novel_eval_prompt 签名扩展 + 维度恢复 + 去截断 | E0 |
| 3 | [`evaluation/evaluate.py`](evaluation/evaluate.py) | E2: evaluate_full 加载 world/characters 并传入 | E1 |
| 4 | 编译验证 | `py_compile` 全部 2 个文件 | 全部 |

---

## 改动量汇总

| 改动 | 文件 | 操作 | 估算 |
|------|------|------|------|
| E0 | `prompts/eval_judge_prompts.py` | 移除 `build_chapter_eval_prompt` 中 chapter_text/outline/voice/world/characters 截断 | +5 / -5 |
| E1-1 | `prompts/eval_judge_prompts.py` | 签名 +2 参数 | +2 |
| E1-2 | `prompts/eval_judge_prompts.py` | 字数统计 | +2 / -1 |
| E1-3 | `prompts/eval_judge_prompts.py` | world/characters section（不截断） | +18 |
| E1-4 | `prompts/eval_judge_prompts.py` | 移除 voice/outline 截断 | +2 / -2 |
| E1-5 | `prompts/eval_judge_prompts.py` | theme_coherence 维度 | +8 |
| E1-6 | `prompts/eval_judge_prompts.py` | JSON 字段 | +1 |
| E2-1 | `evaluation/evaluate.py` | 加载 world/characters | +8 |
| E2-2 | `evaluation/evaluate.py` | 传入参数 | +2 / -1 |
| **合计** | **2 个文件** | | **约 +48 / -9 行** |
