# 中文重构版 → 英文原版质量对齐 — 执行追踪

## 状态
- 当前批次: P3 (第4批)
- 完成: 17/17 — ✅ 全部完成
- 最后更新: 2026-06-18

---

## P0 阻塞级（不改则评分形同虚设）

- [x] **P0-1** Writer/Judge 模型分离 — `core/config.py` + `core/api_client.py`
  - `core/config.py`: 新增 `judge_model_name` / `judge_api_base_url` / `judge_api_key` 属性
  - `core/api_client.py`: `call_judge()` 使用独立配置 + `_call_with_judge_config()` 内部函数
  - **下一步**: `novel_app.py` 收集判断模型配置

- [x] **P0-2** 评估 Prompt 全面升级 — `prompts/eval_judge_prompts.py`
  - 注入 SCORING CALIBRATION（评分校准矩阵）
  - MANDATORY gap+fix（每个维度必须输出最大弱点+具体改进方案）
  - CROSS-CHECKS（引文测试/对话默读/场景vs概述/AI模式检查/获得vs给予）
  - FINAL CHECK（总分>7则重读gap列表，降分）

- [x] **P0-3** Foundation 评估 6→13维 — `prompts/eval_judge_prompts.py` 的 `build_foundation_eval_prompt()`
  - lore 拆为5个维度: power_system_or_social_structure, world_history_or_era_context, geography_and_culture, lore_interconnection, iceberg_depth
  - character 补到3个维度: character_depth, character_distinctiveness, character_secrets
  - craft 补到3个维度: internal_consistency, voice_clarity, canon_coverage
  - 额外输出: slop_in_planning_docs, contradictions_found, top_3_improvements

- [x] **P0-3a** Foundation 去奇幻化（6处修复） — `prompts/eval_judge_prompts.py` 的 `build_foundation_eval_prompt()`
  - 🔴 A1 (L122): 维度1描述中「力量」→「世界观核心规则」通用化
  - 🔴 A2 (L144): 维度4描述中「力量体系」→「核心设定元素」
  - 🟡 A3 (L113-117): 类型自适应分类去掉「奇幻」标签，改为「虚构世界类 / 现实世界类」通用二分法
  - 🟡 A4 (L133): 「酷但情节无关」→「装饰性但情节无关」
  - 🟡 A5 (L223): overall_score 公式补充现实题材替代权重
  - 🟡 A6 (L143): 维度4互联性测试以现实类为主描述，架空类作为分支

- [x] **P0-4** Chapter 评估 5→9维 + 强制字段 — `prompts/eval_judge_prompts.py` 的 `build_chapter_eval_prompt()`
  - 补充维度: plants_seeded, canon_compliance, lore_integration, engagement
  - 强制字段: three_weakest_sentences, three_strongest_sentences, ai_patterns_detected, top_3_revisions, new_canon_entries

- [x] **P0-4a** Chapter 去奇幻化（1处修复） — `prompts/eval_judge_prompts.py` 的 `build_chapter_eval_prompt()`
  - 🔴 A7 (L369): 维度8「力量体系/社会规则」→「世界观核心规则/社会规则」

- [x] **P0-5** Full Novel 改为章节摘要拼接 + 补充维度 — `prompts/eval_judge_prompts.py` 的 `build_full_novel_eval_prompt()`
  - 每章首尾500字摘要拼接（替代全文截断25000字）
  - 补充维度: world_consistency, voice_consistency, weakest_chapter, top_suggestion

- [x] **P0-5a** Full Novel 去奇幻化（1处修复） — `prompts/eval_judge_prompts.py` 的 `build_full_novel_eval_prompt()`
  - 🔴 A8 (L505): 维度3「力量/魔法/社会体系」→「世界观核心规则（无论力量体系、社会制度或时代背景）」

- [x] **P0-3b** 跨文件去奇幻化（6处修复） — `prompts/world_prompts.py` + `foundation/gen_canon.py`
  - 🔴 B1 (`world_prompts.py` L31): fallback 规则描述「力量/魔法体系」→「核心规则/特殊体系」
  - 🔴 B2 (`world_prompts.py` L39): 章节标题「力量/魔法/科技体系」→「核心规则/特殊体系」
  - 🟡 B3 (`world_prompts.py` L45): 子节描述补充「/特殊资源」
  - 🟡 B4 (`world_prompts.py` L74): 指引「力量体系」→「核心规则」
  - 🔴 B5 (`world_prompts.py` L84): 系统 prompt「Sanderson 魔法三定律」→「Sanderson 世界观构建定律」，「力量」→「能力」，「模糊魔法」→「模糊设定」
  - 🟡 B6 (`gen_canon.py` L54): 正典标题「力量/魔法/科技体系」→「核心规则/特殊体系」

## P1 核心差距（修订闭环）

- [x] **P1-6** gen_brief 重写 91→1127行 — `revision/gen_brief.py`
  - panel/eval/cuts 三源交叉引用 + 主导模式分析 + voice_rules提取 + 字数目标计算
  - 已实现: extract_voice_rules(), panel_mentions_for_chapter(), build_panel_brief(), build_eval_brief(), build_cuts_brief(), build_auto_brief()

- [x] **P1-7** Phase 3b 审阅闭环 — `pipeline_orchestrator.py` 的 `run_review_loop()` 之后
  - 审阅 → gen_brief → gen_revision → apply_cuts → git commit
  - 已实现: `_parse_review_weak_chapters()` (L583), `_run_review_revision_loop()` (L635)

- [x] **P1-8** Elo 锦标赛集成 — `pipeline_orchestrator.py` 的 `run_revision()` 中调用 `revision/compare_chapters.py`
  - 已实现: `_elo_target_weaks()` (L333), Step 5.5 Elo 锦标赛 + 底部章节修订 (L456-548)

## P2 功能补缺

- [x] **P2-9** Voice Discovery 子循环 — `foundation/gen_voice.py` + `voice_fingerprint.py` + `pipeline_orchestrator.py`
  - 5段语域试验 → 评估 → 选择 → 精炼 → exemplar + anti-exemplar
  - `foundation/gen_voice.py`: 新增 `generate_5_registers()`, `evaluate_registers()`, `refine_voice()` 子函数；`generate_voice()` 主循环编排
  - `voice_fingerprint.py`: 新增 `extract_vocabulary_wells_from_voice()` 动态词汇域提取 + `analyze_chapter_zh()` 中文版文风分析；保留原有 `WELL_*` 和 `analyze_chapter()` 向后兼容
  - `pipeline_orchestrator.py`: `run_drafting()` 每章起草后集成 `analyze_chapter_zh()` 文风一致性检查
  - 微调: Vocabulary Register 描述 "这个世界" → "这部小说的语言质地"，完全体裁无关

- [x] **P2-10** 种子概念生成器中文化 — `seed.py`（根目录）
   - --count/--riff/--genre 支持，生成中文种子概念
   - S1-S6 全部实现 + S7 CLI 验证测试通过
   - 新增: stdout UTF-8 编码修复 + `_build_genre_constraint()` / `_build_genre_diversity()` 辅助函数

- [x] **P2-11** Pipeline 机制补充 — `pipeline_orchestrator.py` + `evaluation/antipatterns.py`
  - 子项 A: canon 400+ 门槛 — `foundation/gen_canon.py` 新增 `count_canon_entries()` + `pipeline_orchestrator.py` `run_foundation()` 中验证
  - 子项 B: slop 扫描闭环 — `evaluation/evaluate.py` 新增 `get_last_slop_penalty()` + `pipeline_orchestrator.py` `run_drafting()` 中 slop_penalty 参与保留/丢弃决策
  - 子项 C: 反模式注入 — `evaluation/antipatterns.py` (新建) 7种体裁无关结构反模式检测器 + `pipeline_orchestrator.py` `run_drafting()` 中每章审计
  - 配置: `core/config.py` 新增 `canon_min_entries`, `slop_penalty_threshold`, `antipattern_max_warnings`

## P3 精细校准

- [x] **P3-12** 机械 slop 增强 — `evaluation/evaluate.py` 的 `slop_score_zh()`
  - 新增: FICTION_AI_TELLS_ZH (14+ 小说AI套话) + STRUCTURAL_AI_TICS_ZH (7 修辞公式) + TELLING_PATTERNS_ZH (说教式情感) + TRANSITION_OPENERS_ZH (过渡词比例)
  - 惩罚分公式更新: 四项加权 (上限仍 10.0) + sentence_cv < 0.3 惩罚
  - evaluate_chapter() 打印行同步更新

- [x] **P3-13** Judge 独立配置字段 — `core/config.py` + `novel_app.py`
  - `core/config.py`: judge_model_name/judge_api_base_url/judge_api_key（P0-1 已完成）
  - `novel_app.py`: collect_input() 新增步骤 8 可选判断模型收集 + config_data 写入 + confirm_and_start() 摘要展示