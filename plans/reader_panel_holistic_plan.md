# Step 3 reader_panel 架构对齐原版 — 修改方案计划（完整版）

## 用户洞察

> Step 2 已经对每个章节进行单独修改了。Step 3 又对每个章节进行修改，不是重复了吗？

**完全正确。** 原版的设计哲学：

```
Step 2: 逐章机械裁剪（局部视角） → 删除赘语段落
Step 3: 整本全局评审（全局视角） → 发现跨章结构问题和整体节奏
Step 5: 基于全局共识问题的单章修订
```

---

## 修改内容（3 项）

### 改 1：`prompts/reader_panel_prompts.py` — 读者角色对齐原版

**当前问题**：4 个角色只有一行描述，共用一个 `READER_SYSTEM_PROMPT`。无区分度 → 不产生分歧 → disagreements 为空。

**对齐方案**：翻译原版 4 套独立 system 人格到中文，嵌入 `READER_ROLES`，删除共享 `READER_SYSTEM_PROMPT`。

```python
READER_ROLES = {
    "editor": {
        "name": "资深编辑",
        "system": (
            "你是一家大型出版社的资深小说编辑，编辑过 200+ 本小说。"
            "你关心散文的质感、潜台词、句子层面的工艺，以及文风是否一致且自然。"
            "你能察觉叙述者何时过度解释，对话何时听起来像'写作'而非'说话'，"
            "比喻何时是借来的而非自然的。你不残忍但很精确。"
            "你见过太多'合格'的散文，知道'好'和'活着'之间的区别。"
            "始终用纯 JSON 回复。"
        ),
    },
    "genre_reader": {
        "name": "资深类型文学读者",
        "system": (
            "你是一位年读 50+ 本小说的铁杆类型文学读者。"
            "你关心节奏、悬念、世界观回报，以及是否让你想一直翻页。"
            "优美的散文如果不推动情节，你会感到无聊。"
            "你能察觉调查何时停滞、张力何时平台化、作者何时更爱自己的世界而非故事。"
            "你对自己喜爱的慷慨，对无聊的直言不讳。"
            "始终用纯 JSON 回复。"
        ),
    },
    "writer": {
        "name": "小说作者",
        "system": (
            "你是一位出版了多部作品的作者。你以匠人的眼光阅读。"
            "你注意结构：节拍落在哪里、伏笔是否回报、角色弧线是否完成。"
            "你注意技巧何时显露、何时消失在故事中。"
            "你能给的最大赞美是'我忘了在读书'。"
            "你能说的最差评价是'我能看到大纲'。"
            "你关心一部小说试图达到什么和实际达到了什么之间的差距。"
            "始终用纯 JSON 回复。"
        ),
    },
    "first_reader": {
        "name": "普通读者",
        "system": (
            "你是一位有思考力的普通读者。不是作者、不是编辑、不是类型专家。"
            "你为体验而阅读。你知道自己的感受但不一定知道为什么。"
            "你注意到当你被感动、当你无聊、当你困惑、当你想告诉别人你刚读到的内容。"
            "你不使用工艺术语。你会说'我不关心这部分'、"
            "'看完这场戏后我需要缓一缓，因为我需要消化'。"
            "你的反馈是情感化的、诚实的，不是分析性的。"
            "始终用纯 JSON 回复。"
        ),
    },
}
```

---

### 改 2：`prompts/reader_panel_prompts.py` — 整本评审 prompt

**删除**：逐章 prompt `build_reader_panel_prompt()`

**新增**：整本评审 prompt（对齐原版 10 字段）：

```python
def build_novel_reader_prompt(
    novel_summary: str,
    total_chapters: int,
    reader_role: dict,
) -> str:
    return f"""你刚读完了一部完整的长篇小说（共 {total_chapters} 章）。
以下是每章的首尾摘要和关键对话：

{novel_summary}

现在请从全局视角回答以下关于整本小说的问题。请具体引用章节号和段落。

用纯 JSON 回复（不含 markdown 代码块）:

{{
  "momentum_loss": "故事在哪些章节失去推进力？具体哪个位置拖沓？如果没有，说明节奏好的原因。",
  "earned_ending": "结局是否被前文充分铺垫？最后一章是否与第一章形成呼应？什么感觉不自然？",
  "cut_candidate": "如果要删减 10%，你会优先删哪章或哪些段落？为什么？删掉会损失什么？",
  "missing_scene": "小说缺了什么场景？哪段对话该有但没有？哪个角色需要更多篇幅？",
  "thinnest_character": "哪个角色最单薄？谁可以删除而不影响故事？",
  "best_scene": "全书最好的一场戏是什么？引用具体段落，说明为什么好。",
  "worst_scene": "全书最弱的一场戏是什么？出了什么问题？如何修改？",
  "would_recommend": "你会推荐这本小说吗？推荐给谁？用一句话描述。",
  "haunts_you": "有没有让你读完还在回味的段落或句子？引用它。",
  "next_book_hook": "你会读这个作者的下一本书吗？为什么？"
}}

请直接输出 JSON，不要加 ```json``` 代码块。"""
```

---

### 改 3：`revision/reader_panel.py` — 新增构建摘要 + 简化为 4 次调用

#### 3a. 新增 `_build_arc_summary()`（完全对齐原版）

产出与原版 `arc_summary.md` 完全一致的逐章摘要文档。每章包含 5 部分：

| 原版 `build_arc_summary.py` | 重构版 `_build_arc_summary()` |
|---|---|
| LLM 3 句摘要（Writer 模型） | LLM 3 句摘要（`call_writer`, max_tokens=200） |
| 开头 150 词 | 开头 500 字 |
| 结尾 150 词 | 结尾 500 字 |
| 最长 3 句对话 | 最长 3 句对话 |
| 字数统计 | 字数统计 |

```python
def _build_arc_summary(chapter_files: list) -> str:
    """构建整本小说的逐章摘要。

    完全对齐原版 build_arc_summary.py (113行) 的 arc_summary.md 格式。
    每章调用 Writer 模型生成 3 句话摘要，对齐原版 call_writer() 的用法。
    """
    from core.api_client import call_writer as _call_writer

    cfg = config; cfg.load()
    premise = cfg.story_summary

    parts = [f"# 小说前提\n{premise}\n\n---"]

    summary_system = (
        "你精确地总结小说章节。只陈述：发生了什么、什么改变了、"
        "留下了什么未解的问题。不评价。不赞扬。只陈述事件和转变。"
    )

    for cf in sorted(chapter_files):
        text = cf.read_text(encoding="utf-8")
        ch_num = int(cf.stem.split("_")[1])
        chars = len(text.replace(" ", "").replace("\n", ""))

        # LLM 3 句话摘要
        try:
            summary = _call_writer(
                f"用恰好 3 句话总结本章。发生了什么、什么改变了、"
                f"什么未解问题留下。\n\n第 {ch_num} 章:\n{text[:5000]}",
                system=summary_system,
                max_tokens=200,
            )
        except Exception:
            summary = "(摘要生成失败)"

        head = text[:500]
        tail = text[-500:] if len(text) > 1000 else ""

        dialogue = re.findall(r'["「]([^"」]{15,})["」]', text)
        dialogue.sort(key=len, reverse=True)
        top_dialogue = dialogue[:3]

        entry = f"### 第 {ch_num} 章 ({chars} 字)\n"
        entry += f"**摘要:** {summary.strip()}\n\n"
        entry += f"**开头:** {head}...\n\n"
        if tail:
            entry += f"**结尾:** ...{tail}\n\n"
        if top_dialogue:
            entry += "**关键对话:**\n"
            for d in top_dialogue:
                entry += f'> "{d}"\n\n'
        parts.append(entry)

        step(f"  第 {ch_num} 章: 摘要 ({chars} 字)")

    result = "\n---\n\n".join(parts)
    step(f"小说摘要已构建: {len(chapter_files)} 章, {len(result)} 字")
    return result
```

#### 3b. 简化为 4 次调用的主循环

**删除**：`_aggregate_reader_responses()`、逐章 for 循环、阶段 1/2/3 标签。

```python
def run_reader_panel(max_tokens=4096, retries=3, max_total_time=None):
    chapter_files = sorted(CHAPTERS_DIR.glob("ch_*.md"))
    if not chapter_files:
        step("无章节文件，跳过读者评审")
        return
    chapter_nums = [int(cf.stem.split("_")[1]) for cf in chapter_files]
    total = len(chapter_files)

    # 1. 构建整本小说摘要（含 LLM 摘要）
    novel_summary = _build_arc_summary(chapter_files)

    step(f"读者评审团: {len(READER_ROLES)} 位读者评审整本小说 ({total} 章) ...")

    # 2. 每位读者评审一次整本小说（共 4 次 API 调用）
    results = {}
    for role_key, role_info in READER_ROLES.items():
        step(f"  {role_info['name']} 评审中 ...")
        prompt = build_novel_reader_prompt(novel_summary, total, role_info)
        try:
            response = call_judge(
                prompt,
                system=role_info["system"],  # 每人独立人格
                max_tokens=max_tokens, retries=retries,
                max_total_time=max_total_time,
            )
            parsed = _parse_json_response(response)
            results[role_key] = parsed
            step(f"  {role_info['name']} 评审完成 ✓ ({len(parsed)} 字段)")
        except Exception as e:
            step(f"  {role_info['name']} 评审失败: {e}")
            results[role_key] = {}

    # 3. 找分歧
    disagreements = _find_disagreements_structured(results, chapter_nums)

    # 4. 保存
    panel_data = {
        "timestamp": datetime.now().isoformat(),
        "readers": results,
        "disagreements": disagreements,
    }
    log_path = EDIT_LOGS_DIR / "reader_panel.json"
    log_path.write_text(
        json.dumps(panel_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    step(f"读者评审完成: {len(disagreements)} 个分歧")
    for d in disagreements:
        step(f"  第 {d['chapter']} 章 [{d['question']}]: "
             f"{len(d['flagged_by'])}/{len(READER_ROLES)} 位读者标记")
```

---

## 变化对比

| 维度 | 修改前 | 修改后 |
|------|--------|--------|
| 读者人格 | 共享 system prompt | 4 套独立人格（翻译自原版） |
| 评审粒度 | 逐章（最多 32 次 API） | 整本（4 次 API） |
| arc_summary | 无 | LLM 摘要 + 首尾 + 对话（完全对齐原版） |
| 代码行数 | ~230 行 | ~220 行 |
| JSON 结构 | 需逐章聚合 | 直接产出平铺 dict |
| 消费者兼容 | ✅ | ✅ |

## API 调用统计

| 阶段 | 调用内容 | 次数 |
|------|---------|------|
| `_build_arc_summary` | Writer 生成每章 3 句摘要 | N 章 |
| `run_reader_panel` | 4 读者整本评审 | 4 次 |
| **总计** | | **N + 4 次**（原版为 N + 4 次，完全一致） |

## 修改文件清单

| 顺序 | 文件 | 改动 |
|------|------|------|
| 1 | `prompts/reader_panel_prompts.py` | 重写 READER_ROLES（4 套独立人格）；新增 `build_novel_reader_prompt()`；删除 `build_reader_panel_prompt()`、`READER_SYSTEM_PROMPT` |
| 2 | `revision/reader_panel.py` | 新增 `_build_arc_summary()`（含 LLM 摘要）；删除 `_aggregate_reader_responses()`、逐章循环；简化为 4 次调用主循环 |

## 风险

| 风险 | 缓解 |
|------|------|
| LLM 摘要可能失败 | `try/except` 回退到 "(摘要生成失败)"，不阻塞流程 |
| 摘要超 token | 每章 5000 字输入 + 200 token 输出，总计可控 |
| 整本评审可能浅读 | 这是设计意图——全局视角，细节留给 Step 5 |
