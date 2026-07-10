"""
prompts/outline_prompts.py — 大纲生成 Prompt (通用中文)

原版 gen_outline.py 硬编码了「The Second Son of the House of Bells」。
重构为从 {story_summary} 动态提取 {novel_title}。
"""
from core.config import config


def build_outline_prompt(
    seed_text: str,
    world_text: str = "",
    characters_text: str = "",
    mystery_text: str = "",
    voice_part2: str = "",
    craft_text: str = "",
) -> str:
    """构建大纲 Part 1 (章节节拍) prompt。"""

    cfg = config
    cfg.load()
    total_ch = cfg.total_chapters if cfg.loaded else 24
    word_target = cfg.chapter_word_target if cfg.loaded else 3250

    story = seed_text or cfg.story_summary

    return f"""请为这部长篇小说构建一份完整的章节大纲。
目标：{total_ch} 章，总计约 {total_ch * word_target} 字（每章约 3000–3500 字）。

【故事梗概】
{story}

{('【核心谜团（仅作者知道——读者逐步发现）】' + mystery_text) if mystery_text else ''}

{('【世界观设定】' + world_text) if world_text else ''}

{('【角色注册表】' + characters_text) if characters_text else ''}

{('【文风身份】' + voice_part2) if voice_part2 else ''}

{('【叙事技艺参考】' + craft_text) if craft_text else '请参考以下结构原则：\n— Save the Cat 节拍表 (Opening Image/Catalyst/Midpoint/All Is Lost/Finale)\n— try-fail 循环 (Yes-but / No-and 占 60%+)\n— MICE 商数 (Milieu/Inquiry/Character/Event 四线程嵌套关闭)\n— 伏笔种植与回收 (Plant → Reinforce → Payoff，间距 ≥ 3 章)'}

【大纲结构 — 请包含以下内容】

## 一、幕结构规划
标明各幕占比和关键节拍位置：
  — 第一幕 (0-23%): 建立正常世界 → 激励事件 → 犹豫 → 跨入新世界
  — 第二幕上 (23-50%): 探索/适应 → 假胜利或假失败（中点逆转）
  — 第二幕下 (50-77%): 压力升级 → 一切尽失 → 灵魂黑夜
  — 第三幕 (77-100%): 重整 → 高潮 → 终局画面（镜像开幕画面）

## 二、逐章大纲

对【每一章】，提供：
### 第 N 章：[章节标题]
  — **POV:** (锁定哪位角色视角)
  — **地点:** 关键地点
  — **对应节拍:** 本章对应的 Save the Cat 节拍 (Opening Image/Setup/Catalyst/...)
  — **情感弧线:** 起始情绪 → 结束情绪
  — **try-fail 类型:** Yes-but / No-and / No-but / Yes-and
  — **节拍清单:** 本章必须完成的 3-5 个具体场景节拍
  — **伏笔种植:** 本章应埋入的伏笔
  — **伏笔回收:** 本章应回收的前文伏笔
  — **角色移动:** 主角（或关键角色）在本章结束时的内在变化
  — **谎言状态:** 主角的核心谎言在本章是被强化还是被挑战？

## 三、伏笔账本

一张跟踪所有伏笔线索的表格：
| 编号 | 线索 | 种植章 | 强化章 | 回收章 | 类型 (物品/对话/行动/象征/结构) |

至少 15 条伏笔线索。

【重要原则】
1. try-fail 类型多样化：60%+ 应为 Yes-but 或 No-and（进展中带新问题，或失败后更糟）
2. 伏笔种植到回收的间距至少 3 章
3. 至少 3 章是「安静章节」——角色聚焦、低动作、情感丰富的时刻
4. 第二幕避免「疲软中间」——每章都有明确的 try-fail 循环推动
5. 高潮必须用此前设定过的方法解决（不能凭空出现新能力/新信息）
6. 「坏事要持续坏下去」——不是所有事情都能圆满解决
7. 开幕画面与终局画面应形成镜像对比

用简洁直接的汉语写作。写出完整的大纲。"""


# ============================================================
# 方案 D 新增 — 卷级总纲系统 Prompt + 分步构建器
# ============================================================

VOLUME_OUTLINE_SYSTEM_PROMPT = """你是一位长篇小说结构架构师，专精于多卷本叙事规划。
你构建的卷级大纲确保：
— 每卷有独立的叙事功能和情感弧线
— 卷间过渡有因果链（非跳跃式）
— 跨卷伏笔有明确的种植→强化→回收路径
— 角色弧线在卷间连续推进，无断层
你的汉语写作简洁直接，不使用 AI 套话。"""


def build_volume_outline_prompt_part1(
    story: str,
    world_text: str,
    characters_text: str,
    voice_text: str,
    vol_start: int,
    vol_end: int,
    total_volumes: int,
    chapters_per_volume: int,
) -> str:
    """构建卷级总纲调用 1 — 全书弧线 + 前 N 卷规划 + 伏笔种子。

    此调用锚定全局弧线框架，后续调用 2/3 将在此框架下逐卷填充。
    """
    return f"""请为一部长篇小说构建卷级总纲的第一部分。

【基本信息】
— 总卷数: {total_volumes}
— 每卷章数: {chapters_per_volume}
— 总章节数: {total_volumes * chapters_per_volume}
— 当前规划范围: 卷 {vol_start}–{vol_end}

【故事梗概】
{story}

【世界观设定】
{world_text}

【角色注册表】
{characters_text}

【文风参考】
{voice_text}

【输出要求】

## 一、全书弧线
为全部 {total_volumes} 卷勾画整体叙事弧线：
— 核心冲突及其阶段性演化
— 主角的内在弧线（起点 → 终点，逐卷推进）
— 全局节拍位置（激励事件、中点逆转、一切尽失、高潮）分布在哪些卷
— MICE 商数嵌套结构（Milieu/Inquiry/Character/Event 四种线程的开启和关闭时机）

## 二、逐卷规划（卷 {vol_start}–{vol_end}）
对每一卷，提供：

*** 格式要求（严格遵守）：每卷标题行必须 ***
*** 使用 '### 卷 N：标题' 格式，N 为卷号 ***
*** 示例：'### 卷 1：废墟觉醒' ***

### 卷 1：[卷标题]
  — **叙事功能:** 本卷在全局弧线中的角色（建立/探索/压力/逆转/终结）
  — **情感弧线:** 卷初情绪状态 → 卷末情绪状态
  — **关键事件:** 本卷必须发生的 3-5 个关键事件
  — **角色移动:** 主角在本卷结束时的内在变化
  — **伏笔种子:** 本卷应埋入的跨卷伏笔（标注种植卷和预期回收卷）
  — **与前卷衔接:** 如何承接上前卷（第一卷写「无」）

### 卷 2：[卷标题]
  — （同上格式，以此类推）

## 三、伏笔种子清单
列出前 {vol_end - vol_start + 1} 卷中种植的全部跨卷伏笔：
| 编号 | 伏笔内容 | 种植卷 | 预期回收卷 | 类型 |

至少 {max(5, (vol_end - vol_start + 1) * 3)} 条伏笔种子。类型包括：物品、对话、行动、象征、结构。

【写作规则】
1. 只规划卷 {vol_start}–{vol_end} 的详细内容，其余卷仅在全书中弧线中概述
2. 卷间过渡必须有因果链——不能跳跃
3. 伏笔种子必须标记预期回收卷，种植→回收间距 ≥ 1 卷
4. 汉语简洁直接，不做文学批评式分析"""


def build_volume_outline_prompt_part2(
    vol_start: int,
    vol_end: int,
    total_volumes: int,
    chapters_per_volume: int,
    prior_output: str,
) -> str:
    """构建卷级总纲调用 2 — 中段卷规划 + 伏笔追踪。

    Args:
        prior_output: 调用 1 的全部输出（含全书弧线和前组卷的逐卷规划）。
    """
    return f"""请继续卷级总纲的第二部分。

【基本信息】
— 总卷数: {total_volumes}
— 每卷章数: {chapters_per_volume}
— 当前规划范围: 卷 {vol_start}–{vol_end}

【已完成的前段规划（全文——不可修改）】
{prior_output}

【输出要求】

## 逐卷规划（卷 {vol_start}–{vol_end}）

对每一卷，提供（格式同第一部分）：

### 卷 {vol_start}：[卷标题]
  — **叙事功能:** 本卷在全局弧线中的角色
  — **情感弧线:** 卷初情绪状态 → 卷末情绪状态
  — **关键事件:** 本卷必须发生的 3-5 个关键事件
  — **角色移动:** 主角在本卷结束时的内在变化
  — **伏笔种子:** 本卷应埋入的跨卷伏笔（标注种植卷和预期回收卷）
  — **伏笔回收:** 本卷应回收的前文伏笔（从已有伏笔种子清单中选取）
  — **与前卷衔接:** 如何承接卷 {vol_start - 1} 的结尾

## 伏笔追踪更新
— 新增伏笔种子（本卷组种植的）
— 已有伏笔的状态更新（强化/部分回收/保持）

【写作规则】
1. 保持与已完成规划的严格连续性——角色状态、伏笔线索不能断裂
2. 每个关键事件必须有明确的原因和前文铺垫
3. 汉语简洁直接"""


def build_volume_outline_prompt_part3(
    vol_start: int,
    vol_end: int,
    total_volumes: int,
    chapters_per_volume: int,
    prior_output: str,
) -> str:
    """构建卷级总纲调用 3 — 末段卷规划 + 跨卷伏笔矩阵 + 连续性契约。

    Args:
        prior_output: 调用 1+2 的全部输出。
    """
    return f"""请完成卷级总纲的第三部分（最后一部分）。

【基本信息】
— 总卷数: {total_volumes}
— 每卷章数: {chapters_per_volume}
— 当前规划范围: 卷 {vol_start}–{vol_end}（最后 {vol_end - vol_start + 1} 卷）

【已完成的前中段规划（全文——不可修改）】
{prior_output}

【输出要求】

## 一、逐卷规划（卷 {vol_start}–{vol_end}）

对每一卷，提供（格式同前）：

### 卷 {vol_start}：[卷标题]
  — **叙事功能:** 本卷在全局弧线中的角色
  — **情感弧线:** 卷初情绪状态 → 卷末情绪状态
  — **关键事件:** 本卷必须发生的 3-5 个关键事件
  — **角色移动:** 主角在本卷结束时的内在变化
  — **伏笔种子:** 本卷应埋入的伏笔（如有）
  — **伏笔回收:** 本卷应回收的前文伏笔（尤其是跨卷大伏笔的最终回收）
  — **与前卷衔接:** 如何承接

## 二、跨卷伏笔矩阵（全部 {total_volumes} 卷）

完整追踪所有跨卷伏笔的完整生命周期：

| 编号 | 伏笔内容 | 种植卷 | 强化卷 | 回收卷 | 类型 | 回收方式 |
|---|---|---|---|---|---|---|

每条伏笔必须有明确的种植→强化→回收完整路径。
最终卷必须完成所有重要伏笔的回收（允许留 1-2 条用于续作）。

## 三、连续性契约

逐卷检查卷间连接点的连续性：
— 卷 N 末章 → 卷 N+1 首章的角色位置、持有物品、当前目标必须一致
— 列出全部 {total_volumes - 1} 个卷间过渡的连续性快照

【写作规则】
1. 严格保持与已完成规划的连续性
2. 伏笔矩阵必须覆盖全部 {total_volumes} 卷
3. 连续性契约确保编排时无「跳跃」——角色不能从卷 N 末的 A 地瞬间到卷 N+1 首的 B 地（除非已交代过渡）
4. 汉语简洁直接"""


def build_volume_outline_prompt_single(
    story: str,
    world_text: str,
    characters_text: str,
    voice_text: str,
    total_chapters: int,
) -> str:
    """构建单卷卷级总纲 prompt（total_volumes=1 时使用，一次调用即可）。"""
    return f"""请为一部长篇小说构建卷级总纲。

【基本信息】
— 总卷数: 1
— 总章节数: {total_chapters}

【故事梗概】
{story}

【世界观设定】
{world_text}

【角色注册表】
{characters_text}

【文风参考】
{voice_text}

【输出格式 — 必须严格使用以下 Markdown 标题，不得修改标题文本】
你必须使用三级标题（###）作为各段的标题。以下是唯一允许的标题格式：

### 一、全书弧线
描述核心冲突的完整演化、主角内在弧线（起点→终点）、关键节拍位置（激励事件、中点逆转、一切尽失、高潮）。

### 二、卷 1 规划
  — **叙事功能:** 承载全部弧线
  — **情感弧线:** 卷初 → 卷末
  — **关键事件:** 8-12 个关键事件分布
  — **角色移动:** 主角的完整内在变化轨迹
  — **伏笔设计:** 卷内伏笔的种植与回收分布

### 三、伏笔清单
至少 10 条伏笔线索，标注种植章和回收章范围。

【写作规则】
1. 必须使用上述 ### 标题格式，不得使用粗体、数字列表或其他格式替代。
2. 汉语简洁直接，不使用 AI 套话。"""


# ============================================================
# 方案 D Step 5 新增 — 章级大纲系统 Prompt + 构建器
# ============================================================

CHAPTER_OUTLINE_SYSTEM_PROMPT = """你是一位小说章节规划师。你为指定卷的章节构建详细大纲。
每个章节大纲包含：POV、地点、节拍对应、情感弧线、try-fail 类型、具体节拍清单、伏笔种植与回收、角色移动、谎言状态。
你遵循卷级总纲的顶层约束，确保卷内节拍连贯、伏笔不冲突、角色弧线持续推进。
你的汉语写作简洁直接，不使用 AI 套话。"""


def build_chapter_outline_for_volume_prompt(
    volume_num: int,
    ch_start: int,
    ch_end: int,
    vol_section: str,
    prior_segment: str,
    prev_vol_tail: str,
    world_text: str,
    characters_text: str,
    voice_text: str,
) -> str:
    """构建单卷章级大纲的一段 prompt（第 ch_start–ch_end 章）。

    Args:
        volume_num: 当前卷号。
        ch_start: 本段起始章号（1-indexed）。
        ch_end: 本段结束章号（1-indexed）。
        vol_section: 从 outline_volume.md 提取的当前卷约束。
        prior_segment: 前段章级大纲输出（首段为空字符串）。
        prev_vol_tail: 前一卷章级大纲尾部 4000 字（第一卷为空）。
        world_text: 世界观设定（截断后）。
        characters_text: 角色注册表（截断后）。
        voice_text: 文风参考（截断后）。
    """
    return f"""请为第 {volume_num} 卷生成章级大纲（第 {ch_start}–{ch_end} 章）。

【卷级总纲约束 — 本卷必须遵循】
{vol_section}

{('【前一卷章级大纲（尾部 —— 用于跨卷衔接）】' + chr(10) + prev_vol_tail) if prev_vol_tail else ''}

{('【本卷前段章级大纲（已生成 —— 严格继承，不可冲突）】' + chr(10) + prior_segment) if prior_segment else ''}

【世界观设定】
{world_text}

【角色注册表】
{characters_text}

【文风参考】
{voice_text}

【输出要求】

对第 {ch_start} 至第 {ch_end} 章，逐章提供完整大纲：

### 第 N 章：[章节标题]
  — **POV:** 锁定哪位角色视角
  — **地点:** 关键地点（1-3 个）
  — **对应节拍:** Save the Cat 节拍（Opening Image/Setup/Catalyst/Debate/Break into Two/
     B Story/Fun and Games/Midpoint/Bad Guys Close In/All Is Lost/Dark Night of the Soul/
     Break into Three/Finale/Final Image）
  — **情感弧线:** 起始情绪 → 结束情绪
  — **try-fail 类型:** Yes-but / No-and / No-but / Yes-and
  — **节拍清单:** 本章必须完成的 3-5 个具体场景节拍（动作+目的）
  — **伏笔种植:** 本章应埋入的新伏笔（如有）
  — **伏笔回收:** 本章应回收的前文伏笔（引用卷级总纲中的伏笔编号）
  — **角色移动:** 主角（或 POV 角色）在本章结束时的内在变化
  — **谎言状态:** 主角的核心谎言在本章是被强化还是被挑战？

【写作规则】
1. 严格遵循卷级总纲约束中的关键事件和角色移动方向
2. 如有前段大纲，保持节拍连贯——不能有跳跃或矛盾
3. 如有前一卷大纲，卷间衔接点必须平滑
4. try-fail 类型多样化：60%+ 应为 Yes-but 或 No-and
5. 伏笔种植→回收间距 ≥ 3 章（或延续到后续卷）
6. 至少 1 章为「安静章节」——角色聚焦、低动作、情感丰富
7. 汉语简洁直接，不做文学批评式分析"""