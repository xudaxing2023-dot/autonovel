"""
prompts/review_prompts.py — 深度审阅 Prompt（对齐原版双角色风格）

原版 review.py 使用 Opus，以文学评论家 + 小说教授双角色审阅全书。
本模块对齐原版：全文发送 + 双角色 prompt + 末尾结构化摘要。
"""


def build_review_prompt(manuscript_text: str, title: str = "") -> str:
    """构建深度审阅 prompt——对齐原版双角色风格。

    原版: "Review it first as a literary critic ... then as a professor of fiction"
    全文发送，不截断，不传大纲。
    末尾附结构化摘要便于程序解析。
    """
    title_prefix = f"《{title}》" if title else ""

    return f"""请阅读以下长篇小说{title_prefix}。

首先以文学评论家的身份审阅（像报纸书评那样，评估其文学价值、叙事技巧、
角色塑造、语言风格等），然后以小说教授的身份审阅（给出具体、可操作的
改进建议，指出具体哪些章节、哪些段落可以如何提升）。

要公正但诚实。你不一定非要找到缺陷——如果你的真实判断是它已经很优秀，
就如实写。但如果发现缺陷，请准确指出位置和具体问题。

{manuscript_text}

---
审阅完成后，请在末尾附上结构化摘要（便于程序解析）：

总评: ★★★★☆ (填写 1-5 星)
严重问题数: N（标注为 MAJOR 的问题数）
总问题数: N（所有问题总数，含 MINOR）
合格问题数: N（标注为 MINOR 或可接受的问题数）
最弱章节: N,M（最需要修订的 1-3 章编号，用逗号分隔；如无则填 0）
"""


REVIEW_SYSTEM_PROMPT = """你是一位资深文学编辑，兼具文学评论家的审美眼光和
创意写作教授的实战经验。你的审阅公正、诚实、具体。你不会为了找茬而找茬——
如果作品优秀，你就说它优秀；如果发现缺陷，你准确指出位置和可操作的改进方案。
你用中文写作。"""
