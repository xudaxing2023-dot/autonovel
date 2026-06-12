# 中文长篇小说自动生成器 — Agent 指令

自动化长篇小说写作流水线。Agent 在自动评估的引导下，通过 5 层协同演进来写作和修订小说。

## 必读材料

在任何写作或评估之前，Agent 必须内化以下文档：
  — `voice.md` — Part 1（写作禁区）是永久的。Part 2 是每部小说专属的文风指纹。
  — `CRAFT_ZH.md` — 叙事技艺的操作性框架（情节、角色、世界观、伏笔）。
  — `ANTI_SLOP_ZH.md` — 中文 AI 写作痕迹的完整参考。

## 层级栈

```
  第 5 层:  voice.md         — 【怎么写】风格、调性、词汇
  第 4 层:  world.md         — 【存在什么】世界观、魔法/科技、地理、历史
  第 3 层:  characters.md    — 【谁在行动】角色注册表、弧线、关系
  第 2 层:  outline.md       — 【发生什么】节拍、伏笔地图
  第 1 层:  chapters/ch_NN.md — 【真正的文字】一章一个文件
  跨层:    canon.md          — 【什么是真理】硬事实、一致性数据库
```

## 阶段 1: 基础构建（暂无文字）

循环至 foundation_score > 阈值:

  1. 运行 `python evaluation/evaluate.py --phase=foundation`
  2. 从评估输出中识别最薄弱的层级/维度
  3. 扩展或修订该层级的文档
  4. 向 world.md 或 characters.md 添加事实时，同步记入 canon.md
  5. 备份/提交，附上变更描述
  6. 重新评估
  7. 若评分提高 → 保留。若下降 → 恢复至上一版本，丢弃。
  8. 记录到 results.tsv

## 阶段 2: 初稿（按章顺序写作）

对大纲中的每一章：

  循环至 chapter_score > 阈值 或 尝试次数 > 上限:
    1. 加载上下文: voice.md + world.md + characters.md
       + 本章大纲条目
       + 上一章最后约 1000 字
       + 下一章大纲（为连续性的衔接）
    2. 撰写 chapters/ch_NN.md
    3. 运行 `python evaluation/evaluate.py --chapter=NN`
    4. 基于评分保留/丢弃
    5. 若写作过程中发现世界观空白或矛盾，在 state.json 中记录一条债务
    6. 评估后检查输出的 new_canon_entries，将其添加到 canon.md
    7. 记录到 results.tsv
    8. 备份/提交

起草阶段中 canon 会持续增长。每一章都会确立新事实。
这些会被记入 canon.md，确保后续章节保持一致性。

## 阶段 3: 修订（无限精炼）

  1. 对抗性编辑：对每一章运行「削减」裁判 → 分类裁剪清单
  2. 机械裁剪：自动删除 OVER-EXPLAIN 和 REDUNDANT 类别
  3. 读者评审团：4 位不同读者角色阅读全文 → 标记问题
  4. 解析共识：找出多位读者共同标记的章节/问题
  5. 为共识问题生成修订摘要
  6. 执行修订（重写章节）
  7. 如果修订后评分下降 → 恢复原版
  8. 全文评估 → 平台期检测 → 停止或继续

## 阶段 4: 导出

  1. 从章节重建 outline.md
  2. 构建 arc_summary.md
  3. 拼接 manuscript.md（完整手稿）
  4. （可选）LaTeX → PDF 排版

## 评估维度

**基础构建**: world_depth, character_depth, outline_completeness,
  foreshadowing_balance, internal_consistency

**章节**: voice_adherence, beat_coverage, character_voice,
  plants_seeded, prose_quality, continuity

**全文**: 以上全部 + arc_completion, pacing_curve,
  theme_coherence, foreshadowing_resolution, overall_engagement

## 稳定性陷阱（关键）

AI 最大的缺陷是**偏向稳定、逃避改变**。这会让小说失去生命力。
在所有阶段中主动与之对抗：

  — 角色必须以真正不同的方式结束旅程。
  — 让坏事持续坏下去。不是一切都能修好。
  — 允许不可逆的决定和不可逆的损失。
  — 对读者保留信息。维持神秘感。
  — 创造真正的道德模糊。「正确」选择应不明确。
  — 情感强度要有变化：安静/爆发/恐惧/解脱/惊奇/恐怖。
  — 没有真实代价的选择不是真正的选择。
  — 冲突不应太快或太干净地解决。
  — 抵制把尖锐棱角磨圆、变成更安全版本的冲动。

## 基础构建阶段：文风发现

  1. 通读世界观概念和初始创意
  2. 用不同风格试写 5 段（神话式/简约式/温暖式/冷峻式/异想式/……）
  3. 评估哪种风格最适合这个故事的世界和调性
  4. 选择最佳者，精炼，写出范例和非范例段落
  5. 将文风填入 voice.md Part 2