# P1-6: `gen_brief.py` 重写计划（91行 → 400+行）

## 目标

将 [`revision/gen_brief.py`](../revision/gen_brief.py)（当前 91 行）对齐英文原版 [`gen_brief.py`](../gen_brief.py)（854 行）的架构和逻辑，实现 panel/eval/cuts 三源交叉引用的完整修订摘要生成。

## 英文原版核心架构

```
gen_brief.py (854行)
├── 辅助函数 (L26-119)
│   ├── load_json()           - JSON 文件加载
│   ├── chapter_path()        - 章节路径构造
│   ├── chapter_text()        - 章节文本读取
│   ├── chapter_title()       - 从 md 首行提取标题
│   ├── word_count()          - 中/英文字数统计
│   ├── extract_voice_rules() - 从 voice.md 提取写作规则
│   ├── latest_full_eval()    - 查找最新全文评估 JSON
│   ├── latest_chapter_eval() - 查找最新单章评估 JSON
│   ├── load_panel()          - 加载评审团 JSON
│   └── load_cuts()           - 加载对抗性编辑 JSON
│
├── panel_mentions_for_chapter() (L126-166)
│   └── 从 reader_panel.json 按章节提取7个维度的读者反馈
│
├── build_panel_brief() (L173-342)
│   ├── 主导模式分析（COMPRESS/DRAMATIZE/TIGHTEN/REVISE）
│   ├── PROBLEM 区：flagged_issues + negative_keys（截断至400字）
│   ├── WHAT TO KEEP 区：best_scene + tightest_passage + strongest_sentences
│   ├── WHAT TO CHANGE 区：按问题类型编号 → 提取 Fix: 建议
│   ├── VOICE RULES 区：extract_voice_rules() 9条规则
│   └── TARGET 区：按 brief_type 计算目标字数（55%/85%/100%）
│
├── build_eval_brief() (L345-488)
│   ├── 优先单章评估，回退全文评估
│   ├── PROBLEM 区：overall_score + weakest_dimension + ≤7分维度含 fix
│   ├── AI 模式检测 + weakest_sentences + pacing_note
│   ├── WHAT TO KEEP 区：strongest_sentences + tightest_passage
│   ├── WHAT TO CHANGE 区：top_3_revisions + ≤7分维度 fix + top_suggestion
│   ├── 按分数确定类型：≤5→REWRITE, ≤7→FIX, >7→POLISH
│   └── TARGET 区：当前字数保持
│
├── build_cuts_brief() (L491-603)
│   ├── 按类型分组 cuts：REDUNDANT/OVER-EXPLAIN/FAT/TELL/GENERIC/OTHER
│   ├── 主导模式分析（按 cut 频率排序）
│   ├── PROBLEM 区：total_cuttable_words + fat_pct + verdict + loosest_passage
│   ├── WHAT TO KEEP 区：tightest_passage + strongest_sentences
│   ├── WHAT TO CHANGE 区：逐条编号，含 quote/reason/action/rewrite
│   └── TARGET 区：wc - total_cuttable
│
├── build_auto_brief() (L606-784)
│   ├── 从全文评估自动选择 weakest_chapter
│   ├── 三源交叉引用：
│   │   ├── Full eval：weakest_chapter + weakest_dimension + 维度注释
│   │   ├── Per-chapter eval：score + top_3_revisions + AI_patterns
│   │   ├── Panel：flagged_issues + worst_scene/momentum_loss/cut_candidate
│   │   └── Cuts：total_cuttable_words + fat_pct + priority cuts (REDUNDANT/OVER-EXPLAIN)
│   ├── VOICE RULES 区
│   └── TARGET 区
│
└── main() + CLI (L791-853)
    ├── --panel CH
    ├── --eval CH
    ├── --cuts CH
    ├── --auto
    └── --dry-run
```

## P1-6 执行步骤

### 步骤 1: 重写辅助函数层
- [ ] 1.1 实现 `load_json(path)` — 加载 JSON 文件
- [ ] 1.2 实现 `chapter_title(text)` — 从中文标题行提取章节标题（适配中文 `# 第X章 ...` 格式）
- [ ] 1.3 实现 `word_count(text)` — 中文字数统计（char count，非英文 word count）
- [ ] 1.4 实现 `extract_voice_rules()` — 从 `output/voice.md` 提取6-9条核心写作规则（中文化）
- [ ] 1.5 实现 `latest_full_eval()` — 查找 `eval_logs/` 下最新 `*_full.json`
- [ ] 1.6 实现 `latest_chapter_eval(ch)` — 查找 `eval_logs/` 下最新单章评估
- [ ] 1.7 实现 `load_panel()` — 加载 `edit_logs/reader_panel.json`
- [ ] 1.8 实现 `load_cuts(ch)` — 加载 `edit_logs/ch{ch:02d}_cuts.json`

### 步骤 2: 实现 `panel_mentions_for_chapter()`（~45行）
- [ ] 2.1 从 panel JSON 的 `readers` 字段遍历所有读者
- [ ] 2.2 用中文兼容正则匹配章节号（"第X章" / "Ch.X" / "ch_X"）
- [ ] 2.3 按7个维度归类：momentum_loss, worst_scene, cut_candidate, best_scene, thinnest_character, missing_scene, earned_ending
- [ ] 2.4 提取 disagreements 中匹配章节的 flagged_issues

### 步骤 3: 实现 `build_panel_brief()`（~170行）
- [ ] 3.1 主导模式分析：按 negative_keys 优先级确定 brief_type
  - cut_candidate → COMPRESS
  - worst_scene → DRAMATIZE
  - momentum_loss → TIGHTEN
  - 其他 → REVISE
- [ ] 3.2 构建 PROBLEM 区：flagged_issues + 三个负面维度（截断至中文约400字）
- [ ] 3.3 构建 WHAT TO KEEP 区：best_scene + cuts/tightest_passage + eval/strongest_sentences
- [ ] 3.4 构建 WHAT TO CHANGE 区：按类型编号，尝试提取 "Fix:" / "修改方案:" 模式
- [ ] 3.5 构建 VOICE RULES 区：调用 extract_voice_rules()
- [ ] 3.6 构建 TARGET 区：COMPRESS→55%, TIGHTEN→85%, DRAMATIZE→100%, REVISE→当前字数

### 步骤 4: 实现 `build_eval_brief()`（~145行）
- [ ] 4.1 优先加载单章评估 JSON，回退全文评估
- [ ] 4.2 提取 overall_score + weakest_dimension 作为问题摘要
- [ ] 4.3 遍历9维度：voice_adherence, beat_coverage, character_voice, plants_seeded, prose_quality, continuity, canon_compliance, lore_integration, engagement
- [ ] 4.4 ≤7分维度提取 weakest_moment + fix 到 PROBLEM 和 CHANGE 区
- [ ] 4.5 提取 top_3_revisions 到 CHANGE 区
- [ ] 4.6 提取 ai_patterns_detected + three_weakest_sentences
- [ ] 4.7 提取 three_strongest_sentences 到 KEEP 区
- [ ] 4.8 交叉引用 full eval 的 weakest_chapter + top_suggestion + pacing_note
- [ ] 4.9 按分数确定 brief_type：≤5→REWRITE, ≤7→FIX, >7→POLISH

### 步骤 5: 实现 `build_cuts_brief()`（~115行）
- [ ] 5.1 加载 cuts JSON，按 type 分组（REDUNDANT, OVER-EXPLAIN, FAT, TELL, GENERIC, OTHER）
- [ ] 5.2 主导模式分析：统计各类型数量，找 dominant pattern
- [ ] 5.3 构建 PROBLEM 区：total_cuttable_words + fat_pct + verdict + loosest_passage
- [ ] 5.4 构建 WHAT TO KEEP 区：tightest_passage + 交叉引用 eval strongests
- [ ] 5.5 构建 WHAT TO CHANGE 区：按类型分组，逐条编号（quote→reason→action→rewrite）
- [ ] 5.6 构建 TARGET 区：当前字数 - total_cuttable

### 步骤 6: 实现 `build_auto_brief()`（~180行）
- [ ] 6.1 从全文评估自动选择 weakest_chapter
- [ ] 6.2 三源交叉引用（核心价值）：
  - Full eval: weakest_chapter + weakest_dimension + 维度注释 + top_suggestion
  - Per-chapter eval: overall_score + ≤7分维度 fix + top_3_revisions + AI_patterns
  - Panel: flagged_issues + worst_scene/momentum_loss/cut_candidate
  - Cuts: total_cuttable_words + fat_pct + priority cuts (REDUNDANT/OVER-EXPLAIN)
- [ ] 6.3 合并 KEEP 区：best_scene + tightest_passage + strongest_sentences
- [ ] 6.4 合并 CHANGE 区：priority cuts + top_3_revisions + top_suggestion
- [ ] 6.5 VOICE RULES + TARGET 区

### 步骤 7: 重写 `generate_brief()` 主函数 + CLI
- [ ] 7.1 重构 `generate_brief()` 为原版架构的包装函数（保持 pipeline_orchestrator 兼容）
- [ ] 7.2 实现 CLI：`--panel/--eval/--cuts/--auto/--dry-run`
- [ ] 7.3 确保输出路径与 pipeline_orchestrator 期望一致（`briefs/ch{ch:02d}_*.md`）

### 步骤 8: 适配中文环境
- [ ] 8.1 所有 prompt/标签中文化（PROBLEM→【核心问题】，WHAT TO KEEP→【保留项】，等）
- [ ] 8.2 中文正则：章节匹配适配"第X章"/"Ch.X"/"ch_X"
- [ ] 8.3 voice_rules 提取适配中文 voice.md 格式
- [ ] 8.4 中文字数统计（字符数替代英文 word count）
- [ ] 8.5 中文 Fix 模式提取（"修改方案:" / "建议:" 等中文引导词）

### 步骤 9: 验证与集成
- [ ] 9.1 确保 `pipeline_orchestrator.py` 中的 `generate_brief()` 调用无需修改
- [ ] 9.2 确保 `_phase3_test.py` 的 Test 11 通过
- [ ] 9.3 移除根目录 `gen_brief.py` 或标记为已废弃

## 文件变更清单

| 文件 | 操作 | 行数变化 |
|------|------|---------|
| `revision/gen_brief.py` | 完全重写 | 91 → ~500 行 |
| `gen_brief.py`（根目录） | 添加废弃标记注释 | 可选 |

## 不做的事情（留给 P1-7/P1-8）

- 不修改 `pipeline_orchestrator.py` 的修订流程（P1-7 负责）
- 不修改 `revision/compare_chapters.py` 或集成 Elo（P1-8 负责）
- 不修改 `evaluation/evaluate.py`（P0 已完成，P3 负责）