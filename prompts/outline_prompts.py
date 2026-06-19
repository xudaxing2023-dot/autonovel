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

{('【核心谜团（仅作者知道——读者逐步发现）】' + mystery_text[:3000]) if mystery_text else ''}

{('【世界观设定】' + world_text[:4000]) if world_text else ''}

{('【角色注册表】' + characters_text[:4000]) if characters_text else ''}

{('【文风身份】' + voice_part2[:2000]) if voice_part2 else ''}

{('【叙事技艺参考】' + craft_text[:3000]) if craft_text else '请参考以下结构原则：\n— Save the Cat 节拍表 (Opening Image/Catalyst/Midpoint/All Is Lost/Finale)\n— try-fail 循环 (Yes-but / No-and 占 60%+)\n— MICE 商数 (Milieu/Inquiry/Character/Event 四线程嵌套关闭)\n— 伏笔种植与回收 (Plant → Reinforce → Payoff，间距 ≥ 3 章)'}

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