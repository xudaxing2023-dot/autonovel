#!/usr/bin/env python3
"""
foundation/gen_voice.py — Voice Discovery 子循环

5段语域试验 → 裁判评估 → 选择 → 精炼 → exemplar + anti-exemplar
填充 voice.md Part 2（本书专属文风身份）。

适用于所有中文小说类型（现实/言情/历史/悬疑/科幻/武侠等），
无体裁偏见，通过动态词汇域提取实现类型自适应。
"""

import json
import re
import sys
from pathlib import Path

from core.config import config, OUTPUT_DIR, TEMPLATES_DIR
from core.api_client import call_writer, call_judge
from core.state_manager import step


# ============================================================================
# 常量
# ============================================================================

VOICE_SYSTEM_PROMPT = """你是一位文学风格的探索者。你用不同的笔触试写同一场景：
— 简约式：短句，精准，留白多
— 温暖式：亲密，感官丰富，情感充沛
— 冷峻式：客观，疏离，像纪录片旁白
— 诗性式：意象密集，语言有音乐性
— 口语式：像有人在讲故事，直接，有个性
你不对风格做评判，你只是展示每种风格的可能性。"""

VOICE_THRESHOLD = 7.0
MAX_REFINE_ROUNDS = 2


# ============================================================================
# Prompt 构建函数
# ============================================================================

def _build_register_prompt(story: str, world: str, chars: str) -> str:
    """构建5段语域试验 prompt（体裁无关，无作者引用）。"""
    return f"""请为以下小说概念试写 5 种不同文风的小说开头段落（每种约 300-500 字）。

【故事梗概】
{story[:2000]}

【世界观设定参考】
{world[:2000]}

【角色参考】
{chars[:2000]}

请依次写出：

## 风格 1：简约式
（短句、精准、留白多。）

## 风格 2：温暖式
（亲密、感官丰富、情感充沛。）

## 风格 3：冷峻式
（客观、疏离、像纪录片旁白。）

## 风格 4：诗性式
（意象密集、语言有音乐性。）

## 风格 5：口语式
（像有人在讲故事，直接、有个性。）

对每种风格，写完后简要标注这种风格适合这个故事的理由（1-2 句）。"""


def _build_select_prompt(registers_text: str, eval_scores: dict = None) -> str:
    """构建选择+精炼 prompt（结构化输出）。"""
    eval_section = ""
    if eval_scores:
        eval_section = f"""

【裁判评估结果】
{json.dumps(eval_scores, ensure_ascii=False, indent=2)}
请优先选择评分最高的风格，并针对弱维度进行精炼。"""

    return f"""以下是 5 种候选文风及其试写段落：

{registers_text}
{eval_section}

请选择最适合这个故事的一种风格，并按以下结构化格式输出：

## Part 2 — 本书专属文风身份

### 选定风格
（风格名称和一句话定位）

### Tone（基调）
（具体描述本小说的笔触）

### Sentence Rhythm（句式节奏）
（短句/长句分别用于什么场景，给出具体对应）

### Vocabulary Register（词汇域）
（这部小说的语言质地听起来像什么？列出3个词汇领域及其关键词）

### POV and Tense（视角与时态）

### Dialogue Conventions（对话惯例）
（对话标签风格、角色语言差异、潜台词规则）

### Exemplar Passages（范例段落）
（3-5段足以代表本书文风的段落，必须不含 AI 套话）

### Anti-Exemplars（反范例段落）
（3-5段展示不是本书文风的段落，必须具体展示怎么写错）

### 本小说文风规则
（列出 5-10 条具体、可操作、可量化的写作规则）"""


# ============================================================================
# 子循环函数
# ============================================================================

def generate_5_registers(story: str, world: str, chars: str) -> str:
    """5段语域试验：调用 writer LLM 生成5种不同风格的试写段落。"""
    prompt = _build_register_prompt(story, world, chars)
    step("调用 LLM 试写 5 种文风 ...")
    return call_writer(prompt, system=VOICE_SYSTEM_PROMPT, max_total_time=300)


def evaluate_registers(registers_text: str, story: str) -> dict:
    """调用裁判模型评估5段语域试验。返回评分 JSON。"""
    eval_prompt = f"""请评估以下5段语域试验的文风质量。

【故事梗概】
{story[:1000]}

【5段语域试验】
{registers_text}

请按以下维度对每种风格打分（1-10）：

1. 风格契合度：该风格是否适合这个故事的类型、主题和情感基调？
2. 执行质量：试写段落本身的文学品质如何？
3. 可持续性：该风格能否在长篇写作中持续产出？
4. AI痕迹检查：是否存在AI套话、句式模板等机器特征？
5. 独特性和辨识度：该风格是否有鲜明个性？

对每种风格额外输出：
- weakness: 最大弱点（一句话）
- improvement: 具体改进方向（一句话）

输出 JSON：
{{
  "registers": [
    {{
      "register_id": 1,
      "register_name": "简约式",
      "scores": {{"fit": 7, "quality": 7, "sustainability": 7, "ai_free": 7, "distinctiveness": 7}},
      "overall": 7.0,
      "weakness": "...",
      "improvement": "..."
    }},
    ...
  ],
  "best_register": 1,
  "best_register_name": "简约式",
  "overall_score": 7.5
}}"""

    step("调用裁判模型评估 5 段语域 ...")
    result = call_judge(eval_prompt, max_total_time=300)

    try:
        json_match = re.search(r'\{[\s\S]*\}', result)
        if json_match:
            return json.loads(json_match.group())
    except Exception:
        pass

    return {"overall_score": 6.0, "best_register": 1, "raw_result": result}


def refine_voice(registers_text: str, eval_result: dict, best_register: int,
                 story: str) -> str:
    """针对裁判评估指出的弱维度，精炼最佳语域。"""
    weaknesses = []
    if "registers" in eval_result:
        # best_register is 1-indexed
        idx = best_register - 1
        if 0 <= idx < len(eval_result["registers"]):
            reg = eval_result["registers"][idx]
            weaknesses.append(f"最大弱点: {reg.get('weakness', '未指定')}")
            weaknesses.append(f"改进方向: {reg.get('improvement', '未指定')}")

    weaknesses_text = "\n".join(weaknesses) if weaknesses else "未发现具体弱点，请保持并加强现有风格特色。"

    refine_prompt = f"""以下是裁判模型对语域试验的评估结果：

{weaknesses_text}

【原始试写段落】
{registers_text}

请基于裁判反馈，精炼最佳风格（{eval_result.get('best_register_name', '最佳风格')}），
按结构化格式输出完整的文风身份。要求：

1. Exemplar Passages 必须不含 AI 套话
2. Anti-Exemplars 必须具体展示怎么写错
3. 文风规则必须是可操作的、可量化的
4. 句式节奏必须给出具体场景对应

{_build_select_prompt(registers_text)}"""

    step("调用 LLM 精炼最佳文风 ...")
    return call_writer(refine_prompt, max_total_time=300)


# ============================================================================
# 主函数 — Voice Discovery 子循环编排
# ============================================================================

def generate_voice() -> None:
    """Voice Discovery 子循环：5段语域 → 评估 → 精炼 → 输出。

    流程：
      Step A: 生成5段语域试验
      Step B: 裁判模型评估
      Step C: 若评分 >= 7.0，直接生成文风身份；
              若评分 < 7.0，进入精炼循环（最多2轮）
      Step D: 合并模板 Part 1 + 生成 Part 2 → output/voice.md
    """
    cfg = config
    cfg.load()

    story = cfg.story_summary
    world_path = OUTPUT_DIR / "world.md"
    world = world_path.read_text(encoding="utf-8") if world_path.exists() else ""
    chars_path = OUTPUT_DIR / "characters.md"
    chars = chars_path.read_text(encoding="utf-8") if chars_path.exists() else ""

    # 读取 voice 模板 Part 1
    voice_template = TEMPLATES_DIR / "voice.md"
    existing_voice = voice_template.read_text(encoding="utf-8") if voice_template.exists() else ""

    # ── Step A: 5段语域试验 ──
    registers_text = generate_5_registers(story, world, chars)

    # ── Step B: 裁判评估 ──
    eval_result = evaluate_registers(registers_text, story)
    best_score = eval_result.get("overall_score", 6.0)
    best_register = eval_result.get("best_register", 1)
    best_name = eval_result.get("best_register_name", f"风格 #{best_register}")
    step(f"语域评估: {best_score}, 最佳: {best_name}")

    # ── Step C: 精炼循环（最多 2 轮，阈值 7.0）──
    voice_identity = None

    if best_score >= VOICE_THRESHOLD:
        step(f"语域评估 {best_score} >= {VOICE_THRESHOLD} — 直接生成文风身份")
        voice_identity = call_writer(
            _build_select_prompt(registers_text))
    else:
        for rnd in range(1, MAX_REFINE_ROUNDS + 1):
            step(f"语域精炼 轮次 {rnd}/{MAX_REFINE_ROUNDS} (当前分: {best_score})")
            voice_identity = refine_voice(
                registers_text, eval_result, best_register, story)
            # 重新评估精炼后的文风身份
            eval_result = evaluate_registers(
                f"【精炼后文风身份】\n{voice_identity}", story)
            best_score = eval_result.get("overall_score", 6.0)
            step(f"精炼后评估: {best_score}")
            if best_score >= VOICE_THRESHOLD:
                step("精炼评分通过！")
                break

    # 兜底：如果精炼后仍无结果，直接生成
    if voice_identity is None:
        voice_identity = call_writer(
            _build_select_prompt(registers_text))

    # ── Step D: 合并 Part 1 + Part 2 → output/voice.md ──
    full_voice = existing_voice.rstrip() + "\n\n---\n\n" + voice_identity
    voice_path = OUTPUT_DIR / "voice.md"
    voice_path.write_text(full_voice, encoding="utf-8")
    step(f"文风定义已保存: {voice_path} (评估分: {best_score})")


if __name__ == "__main__":
    generate_voice()