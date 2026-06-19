"""
prompts/chapter_prompts.py — 章节起草 Prompt (通用中文)

原版 draft_chapter.py 硬编码了「Cass POV / Tonal Law / The Second Son of the House of Bells」。
重构为通用中文小说章节起草——从 voice.md / world.md / characters.md / outline.md 获取上下文。
"""


def build_chapter_prompt(
    chapter_num: int,
    voice_text: str,
    world_text: str,
    characters_text: str,
    chapter_outline: str,
    next_chapter_preview: str,
    prev_context: str,
    canon_text: str = "",
    novel_title: str = "",
    protagonist_name: str = "",
) -> str:
    """构建章节起草 prompt。"""

    return f"""请撰写第 {chapter_num} 章。

{'小说名称：《' + novel_title + '》' if novel_title else ''}

【文风定义（严格遵守）】
{voice_text}

【本章大纲（逐项完成）】
{chapter_outline}

【下一章预告（保持连续——本章结尾应自然衔接到下章）】
{next_chapter_preview}

【前文回顾——保持情节、对话、情感连续性】
{prev_context}

【世界观设定】
{world_text}

【角色注册表】
{characters_text}

{('【正典（已确立的硬事实——不可违反）】' + canon_text) if canon_text else ''}

【写作指令】

1. 写出【完整】的章节。目标约 3000–3500 字。不要截断或概括。

2. 第三人称有限视角（通常锁定一位 POV 角色{f'：{protagonist_name}' if protagonist_name else ''}），过去时态。

3. 按顺序完成大纲中的所有节拍。

4. 如有「伏笔种植」标注，在本章正文中埋入。

5. 展示感官细节：POV 角色听到什么、闻到什么、身体感受到什么。

6. 对话须遵循角色注册表中定义的说话模式。

7. 【禁止使用的 AI 套话】：
   — "他感到一阵……"（情绪说教——用行为和感官替代）
   — "眼中闪过一丝……"、"嘴角微微上扬/勾起一抹……"（泛滥套话）
   — "深深地吸了一口气"（万能过渡——每章最多 1 次）
   — "宛如一幅……画卷" / "如同一首……交响乐"（直接删除）
   — "不仅仅是……更是……"（每章最多 1 次）
   — "从此……"（不要用作段落结尾）

8. 句子长度要有变化。短句制造冲击。长句营造氛围。

9. 比喻应来自 POV 角色的生活经验，而非作者/ AI 的外部视角。

10. 相信读者。不要解释场景的含义。让它自然传达。

11. 从【场景中】开始，而非从说明性文字开始。以【瞬间】结束，而非总结。

12. 【场景优先于概述】：至少 70% 的章节应是即时场景（时刻推进，有对话和动作），
    而非概述（叙述者压缩时间）。

13. 对话应该像【说话】，而非【写作】。角色偶尔会结巴、打断、说错话、欲言又止。
    一个普通人不会口吐精炼格言。

14. 至少包含一个【令人意外的瞬间】——角色说出不该说的话、情感提前或迟到登场、
    不符合预设模式的细节。预料之中的优秀仍然是预料之中。

15. 段落长度要有意变化。禁止连续 3 段以上长度相近的段落。
    至少包含 1 段 1-2 句的短段落，和 1 段 6+ 句的长段落。

16. 章节分隔符（---）仅用于真正的时间/地点跳跃。每章最多 2 个分隔符。

17. 【禁止过度解释】：如果场景已经展示了什么，叙述者不要再复述一遍。
    相信场景的力量。

18. 【跨章一致性】: 复读前文中角色正在进行的动作、未完成的对话、
    持有的物品、当前的情绪状态。不要重置或遗忘。

现在，从第一句话到最后一句话，写出完整的章节。"""