"""
prompts/adversarial_prompts.py — 对抗性编辑 Prompt (通用中文)

原版 adversarial_edit.py 的「削减 500 词」裁判 prompt。
中文版改为「削减 X 字」+ 分类标注。
"""


def build_adversarial_prompt(chapter_text: str, cut_target: int = 300) -> str:
    """构建对抗性编辑 prompt。「削减 {cut_target} 字」。"""

    return f"""请你以严苛的编辑眼光审阅以下章节。你的任务是找到至少 {cut_target} 字可以删除或精简的内容。

对每一处建议删除的内容，按以下格式标注：

---
位置: (段落描述或引用前几个字定位)
分类: OVER-EXPLAIN / REDUNDANT / TELLING-NOT-SHOWING / SLOP-PHRASE / WEAK-TRANSITION / PADDING
理由: (一句话解释为什么该删除)
建议操作: (删除 / 压缩 / 重写为 [建议的替代文字])
---

【分类说明】
— OVER-EXPLAIN: 场景已展示，叙述者又复述解释
— REDUNDANT: 重复表达或冗余描述
— TELLING-NOT-SHOWING: 告知读者情绪而非展示感官细节（如「他感到愤怒」）
— SLOP-PHRASE: AI 套话（如「宛如一幅画卷」「眼中闪过一丝」「嘴角微微上扬」）
— WEAK-TRANSITION: 无信息量的过渡句
— PADDING: 单纯的水字数

【原则】
1. 不删情节关键信息，只删水分和 AI 痕迹
2. 宁可多标，不可漏标
3. 总计建议删除字数应 ≥ {cut_target} 字
4. 如果某章节问题较少，如实标注即可

以下是章节内容：

{chapter_text}
"""


ADVERSARIAL_SYSTEM_PROMPT = """你是一位苛刻的小说编辑，擅长发现并删除 AI 写作痕迹和水文。
你关注的是：过度解释、冗余重复、说教式情感表达、AI 套话、无意义过渡、纯粹水字数。
你的建议具体可操作——不仅指出问题，还给出删除/压缩/重写方案。
你用中文写作，直接、犀利、不留情面。"""