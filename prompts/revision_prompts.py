"""
prompts/revision_prompts.py — 章节修订 Prompt (通用中文)

原版 gen_revision.py 硬编码了英文奇幻小说元素。
重构为通用中文修订——根据修订摘要 (brief) 重写章节。
"""


def build_revision_prompt(
    ch_num: int,
    brief_text: str,
    voice_text: str,
    world_text: str,
    characters_text: str,
    old_chapter_text: str,
    prev_chapter_tail: str = "",
    next_chapter_head: str = "",
    outline_text: str = "",
) -> str:
    """构建章节修订 prompt。"""

    outline_section = ""
    if outline_text:
        outline_section = f"""
【本章大纲条目（必须覆盖的节奏点和伏笔，修订时不可删减）】
{outline_text}
"""

    return f"""请根据以下修订摘要重写第 {ch_num} 章。

【修订摘要（严格遵循）】
{brief_text}

【文风定义】
{voice_text}

【角色注册表】
{characters_text}

【世界观设定】
{world_text}
{outline_section}
【上一章结尾（保持连续性）】
{prev_chapter_tail if prev_chapter_tail else "（第一章）"}

【下一章开头（本章结尾应自然流入）】
{next_chapter_head if next_chapter_head else "（最后一章）"}

【当前版本（保留有价值的，删掉有问题的）】
{old_chapter_text}

【反模式规则（严格遵守）】
— 禁止三连感官列举（X。Y。Z。连续罗列）
— 禁止「他/她没有 [动词]」句式（每章最多 1 次）
— 禁止「他/她思考着 [X]」句式（用思想片段代替，或直接展示行为）
— 禁止「[否定]……而是……」公式化句式
— 禁止展示之后的过度解释（场景已经展示的，不要再复述）
— 每章最多 2 个分隔符（---）
— 至少有一个令人真正意外的瞬间
— 70%+ 的内容应为即时场景（对话+动作），而非叙述概要
— 对话应该像说话，不是写作
— 段落长度有意变化

重写完整的章节。目标约 3000–3500 字。

保持原有章节标题格式 `# 第{ch_num}章：标题` 不变（如有标题），修订只修改正文内容。"""


REVISION_SYSTEM_PROMPT = """你是一位正在根据修订摘要重写小说章节的作者。
你严格遵循摘要中的每一条指示。
你保留原版本的文风、世界设定和角色特质，同时做出摘要指定的结构性修改。
你写的是完整章节——不截断、不概括。
你的汉语写作简洁有力，避免 AI 套话。"""