"""
prompts/adversarial_prompts.py — 对抗性编辑 Prompt (结构化 JSON)

原版 adversarial_edit.py 的「削减 500 词」裁判 prompt。
中文版改为「削减 X 字」+ JSON 结构化输出，
分类标签对齐 gen_brief.py 的 type_label_map。
"""


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