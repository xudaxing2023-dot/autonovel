"""
prompts/eval_judge_prompts.py — 评估裁判 Prompt (通用中文)

原版 evaluate.py 中的 LLM 裁判部分。
中文版：裁判对小说不同维度进行打分和诊断。
"""


def build_foundation_eval_prompt(
    seed_text: str,
    world_text: str,
    characters_text: str,
    outline_text: str,
    canon_text: str = "",
    mystery_text: str = "",
) -> str:
    """构建基础构建阶段评估 prompt。"""

    return f"""请对以下长篇小说基础构建文档进行评审打分。

【故事梗概】
{seed_text[:3000]}

【世界观设定】
{world_text[:8000]}

【角色注册表】
{characters_text[:8000]}

【章节大纲】
{outline_text[:8000]}

{('【正典硬事实】' + canon_text[:3000]) if canon_text else ''}
{('【核心谜团】' + mystery_text[:2000]) if mystery_text else ''}

【请对以下维度进行评分和诊断（1-10 分制）】

1. world_depth (世界观深度): 世界观是否具体、有层次、有冰山深度？力量/魔法体系是否有明确的规则和代价？
   评分: ___/10
   诊断: ___

2. character_depth (角色深度): 角色是否有清晰的创伤/欲望/需求/谎言因果链？说话模式是否可区分？
   评分: ___/10
   诊断: ___

3. outline_completeness (大纲完整度): 大纲是否覆盖所有章节？节拍安排是否合理？try-fail 类型是否多样化？
   评分: ___/10
   诊断: ___

4. foreshadowing_balance (伏笔平衡): 伏笔账本是否完整？每条伏笔是否有明确的种植和回收计划？
   评分: ___/10
   诊断: ___

5. internal_consistency (内部一致性): 世界观/角色/大纲之间是否存在矛盾？正典是否协调各个层面？
   评分: ___/10
   诊断: ___

6. lore_score (lore 互联性): 世界观各要素之间是否互相影响、牵一发动全身？
   评分: ___/10
   诊断: ___

7. overall_score (综合评分): 加权综合
   评分: ___/10

请以简洁直接的汉语输出。分数在前，诊断在后。"""


def build_chapter_eval_prompt(
    chapter_num: int,
    chapter_text: str,
    chapter_outline: str = "",
    voice_text: str = "",
    canon_text: str = "",
) -> str:
    """构建单章评估 prompt。"""

    return f"""请对以下小说章节进行评审打分。

【第 {chapter_num} 章】
{chapter_text[:10000]}

{('【本章大纲对照】' + chapter_outline[:2000]) if chapter_outline else ''}
{('【文风参考】' + voice_text[:2000]) if voice_text else ''}
{('【正典硬事实对照】' + canon_text[:2000]) if canon_text else ''}

【评分维度（1-10 分制）】

1. voice_adherence (文风一致性): 是否与既定文风保持一致？
   评分: ___/10

2. beat_coverage (节拍完成度): 是否完成了大纲中的所有节拍？
   评分: ___/10

3. character_voice (角色声音): 对话是否自然、可辨识？角色行为是否一致？
   评分: ___/10

4. prose_quality (文字品质): 句子是否有节奏变化？有无 AI 套话？
   评分: ___/10

5. continuity (连续性): 与前后章节的衔接是否自然？有无正典矛盾？
   评分: ___/10

6. overall_score (综合评分):
   评分: ___/10

请简要给出每个维度的诊断。"""


def build_full_novel_eval_prompt(
    manuscript_text: str,
    outline_text: str = "",
    voice_text: str = "",
) -> str:
    """构建全文评估 prompt。"""

    truncated = manuscript_text[:25000] if len(manuscript_text) > 25000 else manuscript_text

    return f"""请对以下长篇小说全文进行评审打分。

{('【大纲对照】' + outline_text[:5000]) if outline_text else ''}
{('【文风参考】' + voice_text[:3000]) if voice_text else ''}

【手稿内容（可能截断）】
{truncated}

【评分维度（1-10 分制）】

1. arc_completion (角色弧完成度): 主角是否经历了有意义的改变？
   评分: ___/10

2. pacing_curve (节奏曲线): 全文节奏是否有起伏变化？有无疲软期？
   评分: ___/10

3. theme_coherence (主题一致性): 核心主题是否始终贯穿？
   评分: ___/10

4. foreshadowing_resolution (伏笔回收): 重要伏笔是否都有回收？
   评分: ___/10

5. overall_engagement (整体吸引力): 作为完整作品，是否引人入胜？
   评分: ___/10

6. novel_score (小说总评分):
   评分: ___/10

请给出每个维度的简要诊断和整体建议。"""


# 裁判系统指令
JUDGE_SYSTEM_PROMPT = """你是一位专业的小说评审裁判，拥有深厚的文学鉴赏能力。
你的评审标准严格但不苛刻——你给予诚实的分数和具体的诊断。
你不会因为作品是 AI 生成的而手下留情，也不会因为一点瑕疵而全盘否定。
你用中文输出评分和诊断，简洁、直接、专业。"""