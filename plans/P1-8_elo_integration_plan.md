# P1-8: Elo 锦标赛集成 — 详细方案

## 目标

将 [`revision/compare_chapters.py`](../revision/compare_chapters.py) 的 `run_compare_chapters()` 集成到 [`pipeline_orchestrator.py`](../pipeline_orchestrator.py) 的 `run_revision()` 中，使修订循环能利用 Elo 排名发现弱章节并进行针对性修订。

## 现状分析

### 已有代码

| 文件 | 行数 | 功能 |
|------|------|------|
| [`revision/compare_chapters.py`](revision/compare_chapters.py:23) | 109行 | `run_compare_chapters(max_tokens)` — 单轮随机配对，K=32 简易 Elo，保存 `tournament_results.json` |
| [`compare_chapters.py`](compare_chapters.py:131) | 218行 | 英文原版 `run_tournament(chapters)` — Swiss 4 轮，加权 Elo 公式，结构化 JSON 输出 |

### 当前 gap

两个版本都已存在，但 `pipeline_orchestrator.py` 的 `run_revision()`（第310行起）**从未调用任何一个**——Elo 锦标赛是独立工具，运行结果不被修订流程消费。

### 两个 compare_chapters.py 的关系

- 根目录 [`compare_chapters.py`](compare_chapters.py) 是英文原版遗产代码，使用 Anthropic API 直接调用
- [`revision/compare_chapters.py`](revision/compare_chapters.py) 是中文重构版，已适配 `core.api_client.call_judge()`
- **集成应使用 `revision/compare_chapters.py`**

---

## 集成方案

### 集成位置：Phase 3a 修订循环内

在 `run_revision()` 的每个修订循环中，共识驱动修订（Step 5）完成后、全文评估（Step 6）前，插入 Elo 锦标赛步骤：

```
现有 Step 5: 共识驱动逐章修订
    ↓
新增 Step 5.5: Elo 锦标赛 → 底部分数章节修订
    ↓
现有 Step 6: 全文评估
```

### 修订流程图

```mermaid
flowchart TD
    A[修订循环开始] --> B[Step 1: adversarial_edit 全部]
    B --> C[Step 2: apply_cuts 全部]
    C --> D[Step 3: reader_panel]
    D --> E[Step 4: parse_consensus]
    E --> F[Step 5: 共识驱动逐章修订]
    F --> G[Step 5.5: Elo 锦标赛]
    G --> G1[run_compare_chapters]
    G1 --> G2[解析 tournament_results.json]
    G2 --> G3[取底部 min(3, n/3) 章节]
    G3 --> G4{章节已在 Step 5 修订过?}
    G4 -->|是| G5[跳过]
    G4 -->|否| G6[pre_eval → build_auto_brief → revise → post_eval → commit/rollback]
    G5 --> G4
    G6 --> G4
    G4 --> H[Step 6: 全文评估]
    H --> I[Step 7: 平台期检测]
    I -->|继续| A
    I -->|平台期| J[Phase 3b]
```

### 修改文件

仅修改 [`pipeline_orchestrator.py`](pipeline_orchestrator.py) — `run_revision()` 函数体内。

### 不修改的文件

- [`revision/compare_chapters.py`](revision/compare_chapters.py) — 保持不变，作为工具被调用
- [`compare_chapters.py`](compare_chapters.py) — 英文原版遗产，不触碰

---

## 实现步骤

### 步骤 1: 新增辅助函数 `_elo_target_weaks()`

在 `run_revision()` 函数体内，`_parse_panel_consensus()` 下方（约第307行后），新增：

```python
def _elo_target_weaks(skip_chapters: set = None, max_targets: int = 3) -> list:
    """解析 Elo 锦标赛结果，返回底部章节编号列表。

    读取 EDIT_LOGS_DIR/tournament_results.json，按 Elo 升序取底部章节，
    排除已在 skip_chapters 中的章节，最多返回 max_targets 个。
    """
    if skip_chapters is None:
        skip_chapters = set()

    tournament_path = EDIT_LOGS_DIR / "tournament_results.json"
    if not tournament_path.exists():
        return []

    try:
        data = json.loads(tournament_path.read_text(encoding="utf-8"))
        ranking = data.get("ranking", [])
    except Exception:
        return []

    # 按 Elo 升序（最弱在前）
    sorted_asc = sorted(ranking, key=lambda x: x.get("elo", 1000))
    targets = []
    for item in sorted_asc:
        ch_num = item.get("chapter", "")
        # 提取数字
        if isinstance(ch_num, str):
            ch_str = ch_num.replace("ch_", "").lstrip("0") or "0"
            ch_num = int(ch_str) if ch_str.isdigit() else 0
        if ch_num and ch_num not in skip_chapters:
            targets.append(ch_num)
        if len(targets) >= max_targets:
            break
    return targets
```

### 步骤 2: 在修订循环内插入 Step 5.5

在现有 Step 5（共识驱动修订，约第421行 `# Step 6` 注释前）和 Step 6 之间插入：

```python
        # Step 5.5: Elo 锦标赛 + 底部分数章节修订
        step("运行 Elo 章节锦标赛 ...")
        try:
            from revision.compare_chapters import run_compare_chapters
            run_compare_chapters(max_tokens=max_tokens)
            step("Elo 锦标赛 完成 ✓")
        except Exception as e:
            step(f"Elo 锦标赛跳过: {e}")

        # 获取已修订章节集合（共识驱动修订过的）
        revised_in_cycle = {item["chapter"] for item in consensus_items}

        # 解析 Elo 底部章节
        elo_targets = _elo_target_weaks(skip_chapters=revised_in_cycle, max_targets=3)
        if elo_targets:
            step(f"Elo 底部章节: {elo_targets}")

        for ch_num in elo_targets:
            ch_file = CHAPTERS_DIR / f"ch_{ch_num:02d}.md"
            if not ch_file.exists():
                continue

            banner(f"  Elo 驱动修订 第 {ch_num} 章 [底部排名]", ".")

            # 修订前评估
            try:
                pre_eval = evaluate_chapter(ch_num, retries=2, max_total_time=600)
                pre_score = parse_score(pre_eval, "overall_score")
            except Exception:
                pre_score = 0

            step(f"第 {ch_num} 章 Elo 修订前评分: {pre_score}")

            # 生成修订摘要
            brief_file = BRIEFS_DIR / f"ch{ch_num:02d}_elo_cycle{cycle}.md"
            try:
                ch, brief_text = build_auto_brief()
                brief_file.write_text(brief_text, encoding="utf-8")
                if not brief_text.strip():
                    raise ValueError("空摘要")
            except Exception:
                brief_content = (
                    f"# 修订摘要: 第 {ch_num} 章 (Elo 驱动)\n\n"
                    f"## 来源: Elo 锦标赛 循环 {cycle}\n\n"
                    f"Elo 排名显示本章为全书最弱章节之一。"
                    f"请大幅提升文字品质、节奏和情感效果。\n"
                )
                brief_file.write_text(brief_content, encoding="utf-8")

            # 执行修订
            step(f"按摘要修订第 {ch_num} 章 (retries=2, 总超时=1200s) ...")
            try:
                revise_chapter(ch_num, brief_file, max_tokens=max_tokens,
                               retries=2, max_total_time=1200)
            except Exception as e:
                step(f"Elo 修订第 {ch_num} 章失败: {e}")
                continue

            # 修订后评估
            try:
                post_eval = evaluate_chapter(ch_num, retries=2, max_total_time=600)
                post_score = parse_score(post_eval, "overall_score")
            except Exception:
                post_score = 0

            word_count = (
                len(ch_file.read_text(encoding="utf-8")
                     .replace(" ", "").replace("\n", ""))
            )

            step(f"第 {ch_num} 章 Elo: {pre_score} -> {post_score}")

            # 提交或回退
            if post_score >= pre_score:
                commit_hash = git_add_commit(
                    f"Elo修订 循环{cycle}: ch{ch_num:02d} "
                    f"{pre_score}->{post_score}"
                )
                log_result(commit_hash, f"elo-rev-ch{ch_num:02d}", post_score,
                           word_count, "keep",
                           f"Elo 循环 {cycle}: ch{ch_num:02d} "
                           f"{pre_score}->{post_score}")
                step(f"Elo 修订 第 {ch_num} 章 完成 ✓ ({pre_score} -> {post_score})")
            else:
                step(f"Elo 修订使评分下降 ({post_score} < {pre_score})，回退")
                git_reset_hard("HEAD")
                log_result("reverted", f"elo-rev-ch{ch_num:02d}", post_score,
                           word_count, "discard",
                           f"Elo 循环 {cycle}: ch{ch_num:02d} "
                           f"倒退 {pre_score}->{post_score}")
```

### 步骤 3: 更新 run_revision() 导入

在 `run_revision()` 顶部（第326-331行）的惰性导入中补充：

```python
    from revision.compare_chapters import run_compare_chapters   # 新增
    from revision.gen_brief import build_auto_brief              # 新增（P1-7 已用到）
```

但 `build_auto_brief` 可能已在 P1-7 的 Phase 3b 部分被导入。当前第329行只导入了 `generate_brief`，需确认是否需要同时导入 `build_auto_brief`。由于 Step 5.5 在 Phase 3a 循环内，而 `build_auto_brief` 的导入在 Phase 3b 内部函数中，所以 Step 5.5 需要自己导入。

**修改第326-331行**：

```python
    from revision.adversarial_edit import run_adversarial_edit
    from revision.apply_cuts import run_apply_cuts
    from revision.reader_panel import run_reader_panel
    from revision.gen_brief import generate_brief, build_auto_brief
    from revision.gen_revision import revise_chapter
    from evaluation.evaluate import evaluate_chapter, evaluate_full
```

---

## 边界情况处理

| 边界情况 | 处理策略 |
|---------|---------|
| `tournament_results.json` 不存在 | `_elo_target_weaks()` 返回空列表，跳过 |
| 章节数 < 2 | `run_compare_chapters()` 内部已处理（step 输出后 return） |
| Elo 底部章节与共识章节重合 | `skip_chapters` 集合排除，避免重复修订 |
| `build_auto_brief()` 失败 | fallback 最小摘要（与 P1-7 一致的策略） |
| Elo 修订评分下降 | `git_reset_hard("HEAD")` 回退 + log_result |
| API 调用超时 | `run_compare_chapters()` 内部 try/except + 已通过 call_judge 的 retries |

---

## 与 Phase 3a 共识驱动修订的互补关系

| 维度 | 共识驱动 (Step 5) | Elo 驱动 (Step 5.5) |
|------|-------------------|---------------------|
| 触发源 | reader_panel 共识问题 | 章节间两两比较排名 |
| 识别方式 | 读者直接点名弱章节 | 系统性排名，底部章节 |
| 修订数量 | 最多 5 个共识章节 | 最多 3 个（排除已修订） |
| 摘要来源 | panel_data 驱动 | --auto 三源交叉引用 |
| 本质 | 定性的、外部读者视角 | 定量的、内部比较视角 |

---

## 测试验证点

1. `_elo_target_weaks()` 在无 tournament_results.json 时返回 `[]`
2. `_elo_target_weaks()` 正确排除 skip_chapters 中的章节
3. Elo 锦标赛在章节数 < 2 时静默跳过
4. Elo 驱动修订与共识驱动修订不重复处理同一章节
5. 修订评分改进后正确 commit，退步后正确 rollback