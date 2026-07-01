# adversarial_edit JSON 解析能力 — 修改方案计划

## 目标

让重构版 `revision/adversarial_edit.py` 像原版一样解析 LLM 返回的 JSON 结构，
使下游消费者（`gen_brief.py`、`apply_cuts.py`）能直接读取结构化字段。

---

## 诊断：cuts.json 完整消费者链路

### 生产者（当前）

```
revision/adversarial_edit.py:49-60
  call_judge(prompt) → result (原始文本)
  ↓
  cuts_data = {chapter, timestamp, raw_output: result}   ← ⚠ 仅保存原始文本
  ↓
  edit_logs/chXX_cuts.json
```

### 消费者（失败原因）

| 消费者 | 位置 | 读取字段 | 当前返回值 |
|--------|------|----------|-----------|
| `build_cuts_brief()` | [`gen_brief.py:612-617`](revision/gen_brief.py:612) | `cuts[]`, `total_cuttable_words`, `tightest_passage`, `loosest_passage`, `overall_fat_percentage`, `one_sentence_verdict` | 全部为默认空值 |
| `build_panel_brief()` | [`gen_brief.py:319-323`](revision/gen_brief.py:319) | `tightest_passage` | `""`（跳过） |
| `build_eval_brief()` | [`gen_brief.py:551-555`](revision/gen_brief.py:551) | `tightest_passage` | `""`（跳过） |
| `build_auto_brief()` | [`gen_brief.py:892-926`](revision/gen_brief.py:892) | `total_cuttable_words`, `overall_fat_percentage`, `tightest_passage`, `one_sentence_verdict`, `cuts[]` | 全部为默认空值 |
| `generate_brief()` | [`gen_brief.py:1007`](revision/gen_brief.py:1007) | `total_cuttable_words > 0` 判断 | `False`（跳过 cuts 分支） |
| `apply_cuts()` | [`apply_cuts.py:31-33`](revision/apply_cuts.py:31) | `chapter` | ✅ 可读（但功能是桩） |

**结论**：6 个消费者中有 5 个完全读不到数据，只有 `apply_cuts` 桩能读到 `chapter` 字段。

---

## 修改清单

### 改 1：`prompts/adversarial_prompts.py` — prompt 改为 JSON，对齐分类标签

**当前问题**：
- [`build_adversarial_prompt()`](prompts/adversarial_prompts.py:9) 要求非结构化输出 `位置:/分类:/理由:/建议操作:`
- 分类标签是中文：`OVER-EXPLAIN / REDUNDANT / TELLING-NOT-SHOWING / SLOP-PHRASE / WEAK-TRANSITION / PADDING`
- 下游 `gen_brief.py` 的 `type_label_map` 期望：`REDUNDANT / OVER-EXPLAIN / FAT / TELL / GENERIC / OTHER`

**修改内容**：

```python
# prompts/adversarial_prompts.py — 修改后

def build_adversarial_prompt(chapter_text: str, cut_target: int = 300) -> str:
    """构建对抗性编辑 prompt。要求 LLM 输出结构化 JSON。"""

    char_count = len(chapter_text.replace(" ", "").replace("\n", ""))

    return f"""你正在编辑一部小说的章节。你的任务是找出本章中可以删除或改写的段落，
使文本更紧凑、更生动。

【章节内容】（共约 {char_count} 字）:

{chapter_text}

【你的任务】
1. 找出 10-20 处应删除或改写的具体段落。
   每处引用原文精确文本（至少 20 字，确保可唯一定位），
   解释为什么弱，并分类。

2. 分类标准（使用以下英文标签）:
   - FAT: 纯粹赘语，删除无损情节
   - REDUNDANT: 与前文重复表达
   - OVER-EXPLAIN: 叙述者复述场景已展示的内容
   - TELL: 命名情绪/状态而非展示感官细节（如「他感到愤怒」）
   - SLOP: AI 套话（如「眼中闪过一丝」「嘴角微微上扬」「一股…涌上心头」）
   - STRUCTURAL: 段落/节奏扰乱阅读体验

3. 对 REWRITE 候选项提供具体替换文本。

4. 估算总共可删除字数（不丢失必要信息的前提下）。

【重要：请用纯 JSON 回复，不要包含 markdown 代码块标记】
{{
  "cuts": [
    {{
      "quote": "原文精确引用（20字以上，确保可唯一定位）",
      "type": "FAT|REDUNDANT|OVER-EXPLAIN|TELL|SLOP|STRUCTURAL",
      "reason": "为什么该删/改写",
      "action": "CUT|REWRITE",
      "rewrite": "替换文本（仅 action=REWRITE 时填写，否则 null）"
    }}
  ],
  "total_cuttable_words": 450,
  "tightest_passage": "本章最精炼的2-3句——永远不该动的句子",
  "loosest_passage": "本章最拖沓的2-3句——最需要修改的句子",
  "overall_fat_percentage": 15,
  "one_sentence_verdict": "用一句话评价：本章的优点和拖后腿的地方"
}}

请直接输出 JSON，不要加 ```json``` 代码块。"""


ADVERSARIAL_SYSTEM_PROMPT = """你是一位苛刻的小说编辑，擅长发现并删除 AI 写作痕迹和水文。
你关注的是：过度解释、冗余重复、说教式情感表达、AI 套话、无意义过渡、纯粹水字数。
你引用原文时必须逐字精确——不编造、不改写原文。
你的建议具体可操作——不仅指出问题，还给出删除/压缩/重写方案。
始终用纯 JSON 回复，不含 markdown 代码块标记。"""
```

**关键设计决策**：
- 字段名 `total_cuttable_words` 与下游消费者完全一致（不用 `total_cuttable_chars`）
- 分类标签 `FAT / REDUNDANT / OVER-EXPLAIN / TELL / SLOP / STRUCTURAL` 中，
  `FAT/REDUNDANT/OVER-EXPLAIN/TELL` 匹配 `gen_brief.py` 的 `type_label_map`；
  `SLOP` 和 `STRUCTURAL` 会落入 `OTHER` 默认映射，不影响功能
- 保留 `raw_output` 存储原始 LLM 响应用于调试

---

### 改 2：`revision/adversarial_edit.py` — 新增 `_parse_json_response()` + 保存结构化数据

**当前代码**（[`adversarial_edit.py:54-60`](revision/adversarial_edit.py:54)）：
```python
cuts_data = {
    "chapter": ch_num,
    "timestamp": datetime.now().isoformat(),
    "raw_output": result,
}
```

**修改后**（在 `run_adversarial_edit()` 上方新增解析函数，修改保存逻辑）：

```python
# revision/adversarial_edit.py — 修改后

import json
import re       # ★ 新增
import sys
from datetime import datetime
from pathlib import Path

from core.config import OUTPUT_DIR, CHAPTERS_DIR, EDIT_LOGS_DIR
from core.api_client import call_judge
from core.state_manager import step
from prompts.adversarial_prompts import build_adversarial_prompt, ADVERSARIAL_SYSTEM_PROMPT


# ★★★ 新增：JSON 解析函数（三级回退，对齐原版 parse_json）★★★
def _parse_json_response(text: str) -> dict:
    """从 LLM 响应中提取 JSON 对象。

    三级回退策略：
      1. 剥除 ```json ... ``` markdown 代码块 → json.loads()
      2. 从首个 { 或 [ 开始直接 json.loads()
      3. 花括号深度匹配（处理 LLM 在 JSON 后追加额外文本的情况）
    """
    if not text or not text.strip():
        return {}

    text = text.strip()

    # 第1层：剥除 markdown 代码块标记
    if text.startswith("```"):
        text = re.sub(r'^```\w*\n?', '', text)
        text = re.sub(r'\n?```$', '', text)
        text = text.strip()

    # 第2层：从第一个 { 或 [ 开始尝试直接解析
    start = text.find('{')
    if start == -1:
        start = text.find('[')
    if start == -1:
        step(f"  ⚠ JSON 解析失败: 响应中未找到 {{ 或 [")
        return {}

    try:
        return json.loads(text[start:], strict=False)
    except json.JSONDecodeError:
        pass  # 回退到深度匹配

    # 第3层：花括号/方括号深度匹配
    depth = 0
    in_string = False
    escape = False
    open_char = text[start]
    close_char = '}' if open_char == '{' else ']'

    for i in range(start, len(text)):
        c = text[i]
        if escape:
            escape = False
            continue
        if c == '\\' and in_string:
            escape = True
            continue
        if c == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == open_char:
            depth += 1
        elif c == close_char:
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1], strict=False)
                except json.JSONDecodeError:
                    break

    # 最终尝试宽松解析
    try:
        return json.loads(text[start:], strict=False)
    except json.JSONDecodeError:
        step(f"  ⚠ JSON 解析失败: 所有回退策略均失败，响应前200字: {text[:200]}")
        return {}


def run_adversarial_edit(
    target: str = "all",
    max_tokens: int = 4096,
    retries: int = 3,
    max_total_time: int = None,
) -> None:
    """运行对抗性编辑。"""
    EDIT_LOGS_DIR.mkdir(parents=True, exist_ok=True)

    if target == "all":
        chapter_files = sorted(CHAPTERS_DIR.glob("ch_*.md"))
    else:
        ch_num = int(target)
        ch_file = CHAPTERS_DIR / f"ch_{ch_num:02d}.md"
        chapter_files = [ch_file] if ch_file.exists() else []

    if not chapter_files:
        step("无章节文件可供编辑")
        return

    total_chapters = len(chapter_files)
    for idx, ch_file in enumerate(chapter_files, 1):
        ch_text = ch_file.read_text(encoding="utf-8")
        ch_num = int(ch_file.stem.split("_")[1])

        step(f"对抗性编辑 第 {ch_num} 章 ({idx}/{total_chapters}) ...")
        prompt = build_adversarial_prompt(ch_text, cut_target=300)

        result = call_judge(
            prompt, system=ADVERSARIAL_SYSTEM_PROMPT, max_tokens=max_tokens,
            retries=retries, max_total_time=max_total_time,
        )

        # ★★★ 解析 JSON 响应 ★★★
        parsed = _parse_json_response(result)

        cuts_path = EDIT_LOGS_DIR / f"ch{ch_num:02d}_cuts.json"

        # ★ 构建结构化数据：顶层展开 parsed 的所有字段
        cuts_data = {
            "chapter": ch_num,
            "timestamp": datetime.now().isoformat(),
            "raw_output": result,  # 保留原始响应用于调试
        }
        if parsed:
            cuts_data.update(parsed)  # 展开 cuts, total_cuttable_words, 等
            cut_count = len(parsed.get("cuts", []))
            fat_pct = parsed.get("overall_fat_percentage", "?")
            step(f"对抗性编辑 第 {ch_num} 章: "
                 f"发现 {cut_count} 处可删改, 赘语比例 {fat_pct}%")
        else:
            step(f"对抗性编辑 第 {ch_num} 章: JSON 解析失败，仅保存原始响应")

        cuts_path.write_text(
            json.dumps(cuts_data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        step(f"对抗性编辑 第 {ch_num} 章 完成 ✓ (编辑清单: {cuts_path})")

    step("对抗性编辑全部完成 ✓")
```

---

### 改 3（可选优化）：`revision/gen_brief.py` — 类型标签映射补充

当前 `type_label_map` 已覆盖大部分标签，但 prompt 新增了 `SLOP` 和 `STRUCTURAL`。建议补充映射：

```python
# gen_brief.py:630-637 — 现有代码（修改后）
type_label_map = {
    "REDUNDANT": "冗余",
    "OVER-EXPLAIN": "过度解释",
    "FAT": "赘语",
    "TELL": "说教(tell)",
    "GENERIC": "套话/通用",
    "SLOP": "AI套话",        # ★ 新增
    "STRUCTURAL": "结构问题", # ★ 新增
    "OTHER": "其他",
}
```

这一步非必须——不修改的话，`SLOP` 和 `STRUCTURAL` 会落入 `OTHER` 的 `"混合"` 显示，不影响功能。

---

## 修改后 cuts.json 数据结构

```json
{
  "chapter": 3,
  "timestamp": "2026-07-01T16:00:00.000000",
  "raw_output": "原始LLM响应文本（完整保留，用于调试）",
  "cuts": [
    {
      "quote": "他感到一阵莫名的恐惧涌上心头，手指不自觉地颤抖起来。",
      "type": "TELL",
      "reason": "告知读者恐惧而非展示：可改为身体感受描写",
      "action": "REWRITE",
      "rewrite": "指尖发麻，有什么东西顺着脊椎爬上来。他说不清那是什么。"
    },
    {
      "quote": "值得一提的是，这场战斗的胜负将决定整个王国的命运。",
      "type": "OVER-EXPLAIN",
      "reason": "读者已从场景中理解战斗重要性，无需叙述者复述",
      "action": "CUT",
      "rewrite": null
    }
  ],
  "total_cuttable_words": 450,
  "tightest_passage": "她的手指在剑柄上收紧，指节泛白。没有说话。",
  "loosest_passage": "他知道现在必须做出选择，而这个选择将会影响所有人的命运，他陷入了深深的思考之中。",
  "overall_fat_percentage": 15,
  "one_sentence_verdict": "场景张力充足，但叙述者频繁跳出来解释角色心理，削弱了沉浸感。"
}
```

---

## 消费者兼容性验证

| 消费者（位置） | 读取代码 | 修改后返回值 | 状态 |
|---------------|----------|-------------|------|
| `build_cuts_brief:612` | `cuts_data.get("cuts", [])` | 非空 list | ✅ |
| `build_cuts_brief:613` | `cuts_data.get("total_cuttable_words", 0)` | >0 | ✅ |
| `build_cuts_brief:614` | `cuts_data.get("tightest_passage", "")` | 非空字符串 | ✅ |
| `build_cuts_brief:615` | `cuts_data.get("loosest_passage", "")` | 非空字符串 | ✅ |
| `build_cuts_brief:616` | `cuts_data.get("overall_fat_percentage", 0)` | >0 | ✅ |
| `build_cuts_brief:617` | `cuts_data.get("one_sentence_verdict", "")` | 非空字符串 | ✅ |
| `build_panel_brief:320` | `cuts_data.get("tightest_passage")` | 非空 | ✅ |
| `build_eval_brief:552` | `cuts_data.get("tightest_passage")` | 非空 | ✅ |
| `build_auto_brief:894` | `cuts_data.get("total_cuttable_words", 0)` | >0 | ✅ |
| `build_auto_brief:910` | `cuts_data.get("cuts", [])` | 非空 list | ✅ |
| `generate_brief:1007` | `cuts_data.get("total_cuttable_words", 0) > 0` | True → 进入 cuts 分支 | ✅ |
| `apply_cuts:32` | `data.get("chapter", "?")` | 正常 | ✅ |

---

## 执行顺序

| 顺序 | 文件 | 改动摘要 | 风险 |
|------|------|----------|------|
| 1 | `prompts/adversarial_prompts.py` | prompt → JSON + 英文分类标签 + system_prompt 强调纯 JSON | 低：不影响其他模块 |
| 2 | `revision/adversarial_edit.py` | +`_parse_json_response()` + `cuts_data.update(parsed)` | 低：向后兼容，`raw_output` 保留 |
| 3 | `revision/gen_brief.py` | 补充 `type_label_map` 中的 `SLOP`/`STRUCTURAL` | 极低：可选优化 |
| 4 | 手动测试 | 运行 `adversarial_edit` 对单章，检查 `cuts.json` 是否含 `cuts` 数组 | — |

---

## 风险与缓解

| 风险 | 缓解措施 |
|------|----------|
| LLM 不返回 JSON（返回非结构化文本） | `_parse_json_response()` 返回 `{}` → `raw_output` 保留 → step 警告日志 → 不影响流水线继续 |
| LLM 返回 JSON 但字段缺失 | 所有消费者使用 `.get(key, default)` 读取 → 不回退到 `raw_output` 导致下游空壳摘要的问题不再发生 |
| 分类标签不匹配下游 `type_label_map` | 未知标签落入 `OTHER` → `"混合"` 显示，功能不受影响 |
| `total_cuttable_words` 返回非数字 | `generate_brief:1007` 的 `> 0` 判断会失败 → 回退到 panel/auto 分支 |
