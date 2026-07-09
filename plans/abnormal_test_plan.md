# autonovel-zh v1.2 — 全流水线异常与BUG发现测试方案

> **版本**: v1.0  
> **日期**: 2026-07-09  
> **测试框架**: pytest (>=8.0)  
> **核心约束**: 所有测试不调用LLM API，使用mock/fixture/本地数据  
> **测试用例总数**: 108个  
> **覆盖风险点**: 25个 (高7 / 中7 / 低6 / 架构5)

---

## 目录

1. [风险点清单](#1-风险点清单)
2. [测试环境与约定](#2-测试环境与约定)
3. [测试Fixture设计](#3-测试fixture设计)
4. [阶段1: 模块导入与基础完整性测试](#4-阶段1-模块导入与基础完整性测试)
5. [阶段2: 配置与状态管理异常测试](#5-阶段2-配置与状态管理异常测试)
6. [阶段3: 各子模块纯逻辑单元测试](#6-阶段3-各子模块纯逻辑单元测试)
7. [阶段4: 管道串联与数据流完整性测试](#7-阶段4-管道串联与数据流完整性测试)
8. [阶段5: 边界条件与错误处理测试](#8-阶段5-边界条件与错误处理测试)
9. [预期测试文件结构](#9-预期测试文件结构)
10. [执行顺序建议](#10-执行顺序建议)
11. [附录: 测试用例索引](#11-附录-测试用例索引)

---

## 1. 风险点清单

共识别25个风险点，按严重程度分为4级：

### 高风险 (P0/P1 — 阻塞性/高风险, 7个)

| 编号 | 风险点 | 位置 | 描述 |
|------|--------|------|------|
| **R01** | Config单例未加载时访问属性 | [`core/config.py:63-81`](core/config.py:63) | `config.load()` 未调用前访问属性返回空值/默认值，可能静默失败 |
| **R02** | `parse_score()` 格式解析失败抛异常 | [`core/state_manager.py:357-404`](core/state_manager.py:357) | LLM不遵守JSON格式时，三级回退可能全部失败抛出 `ValueError` |
| **R03** | `load_state()` 返回损坏JSON时静默回退 | [`core/state_manager.py:98-112`](core/state_manager.py:98) | JSON损坏时返回 `default_state()`，丢失全部进度状态 |
| **R04** |章节大纲正则匹配失败 | [`drafting/draft_chapter.py:51-58`](drafting/draft_chapter.py:51) | 大纲格式变化时正则匹配不到章节条目，返回"未找到"占位文本 |
| **R05** | `apply_cuts` 歧义匹配导致错误删除 | [`revision/apply_cuts.py:56-95`](revision/apply_cuts.py:56) | 引用在章节中出现多次时无法定位，跳过删除；空白标准化回退可能匹配错误位置 |
| **R06** | Windows编码 `sys.stdout.reconfigure` 管道模式崩溃 | [`pipeline_orchestrator.py:25-26`](pipeline_orchestrator.py:25) | 在管道/重定向环境中 `reconfigure` 抛出 `OSError` |
| **R07** | `results.tsv` 中score负值哨兵未正确拦截 | [`core/state_manager.py:305-333`](core/state_manager.py:305) | `-1.0` 哨兵检测依赖于 `isinstance(score, (int, float)) and score < 0`，字符串"score"不触发 |

### 中风险 (P2 — 中风险, 7个)

| 编号 | 风险点 | 位置 | 描述 |
|------|--------|------|------|
| **R08** | `count_canon_entries()` 节标题匹配不完整 | [`foundation/gen_canon.py:72-111`](foundation/gen_canon.py:72) | 只匹配 `## 一、世界观` 等固定标题，LLM生成的其他格式标题被忽略 |
| **R09** | `evaluate_chapter_stable()` 中位数边界 | [`core/state_manager.py:445-467`](core/state_manager.py:445) | 所有采样都失败时返回0.0，与真实评分0.0无法区分 |
| **R10** | `build_manuscript()` 空章节处理 | [`export/build_manuscript.py:15-48`](export/build_manuscript.py:15) | 空章节被 `continue` 跳过，导致目录编号与实际章节错位 |
| **R11** | 模型tier自动推断边界 | [`core/config.py:376-387`](core/config.py:376) | 新模型名不匹配任何已知列表时默认为"low"，导致不合理的低阈值 |
| **R12** | `_parse_json_response()` 花括号深度匹配 | [`evaluation/evaluate.py:35-99`](evaluation/evaluate.py:35) | 第3层回退可能截断嵌套JSON中的内层对象 |
| **R13** | `build_*_brief()` 数据源缺失时的fallback质量 | [`revision/gen_brief.py:258-965`](revision/gen_brief.py:258) | 三类brief构建器依赖外部JSON文件，缺失时生成含占位文本的摘要 |
| **R14** | `git_add_commit()` 文件备份模式下 `shlex.split` | [`core/state_manager.py:161-167`](core/state_manager.py:161) | 路径含空格时 `shlex.split` 后 `subprocess.run` 可能找不到文件 |

### 低风险 (P3 — 低风险, 6个)

| 编号 | 风险点 | 位置 | 描述 |
|------|--------|------|------|
| **R15** | `slop_score_zh()` 正则匹配性能 | [`evaluation/evaluate.py:222-341`](evaluation/evaluate.py:222) | 30+个正则对超长文本(>10万字)可能性能退化 |
| **R16** | `backup_snapshot()` 跨驱动器复制 | [`core/state_manager.py:227-263`](core/state_manager.py:227) | `shutil.copy2` 在跨驱动器场景可能失败 |
| **R17** | `.env` 中 `api_interval_seconds` 非数字值 | [`core/config.py:91-95`](core/config.py:91) | `ValueError` 被捕获后回退为4.0，不提示用户 |
| **R18** | `_resolve_outline_path()` 卷号计算溢出 | [`evaluation/evaluate.py:344-381`](evaluation/evaluate.py:344) | `chapters_per_volume=0` 时除零错误 |
| **R19** | `chapter_path()` 零章编号 | [`revision/gen_brief.py:45-47`](revision/gen_brief.py:45) | `ch=0` 时生成 `ch_00.md`，非标准命名 |
| **R20** | `extract_voice_rules()` 空voice.md | [`revision/gen_brief.py:90-159`](revision/gen_brief.py:90) | voice.md为空时返回列表仅含一条fallback文本 |

### 架构风险 (P2 — 架构, 5个)

| 编号 | 风险点 | 位置 | 描述 |
|------|--------|------|------|
| **R21** | 全局单例 `config` 在模块导入时预创建目录 | [`core/config.py:424-433`](core/config.py:424) | 在只读文件系统中导入 `core.config` 即崩溃 |
| **R22** | 模块间路径常量不一致 | 多个文件 | `CHAPTERS_DIR`/`BRIEFS_DIR` 等在 `core/config.py` 定义，但部分模块硬编码路径 |
| **R23** | Phase间状态传递缺少schema验证 | [`pipeline_orchestrator.py`](pipeline_orchestrator.py:1) | `state` dict在各phase间传递无类型/键校验 |
| **R24** | `_parse_panel_consensus()` 正则匹配章节号 | [`pipeline_orchestrator.py:413-415`](pipeline_orchestrator.py:413) | `第?\s*(\d+)\s*章` 无法匹配 `第三章` 等中文数字 |
| **R25** | filesystem race: `save_state()` 无原子写入 | [`core/state_manager.py:115-127`](core/state_manager.py:115) | `json.dump` 直接覆盖，写入过程中崩溃导致state.json损坏 |

---

## 2. 测试环境与约定

### 2.1 测试框架

- **pytest** >= 8.0
- **pytest-mock** (用于 `mocker` fixture)
- **pytest-cov** (覆盖率报告)
- **unittest.mock** (标准库mock，用于 `patch`/`MagicMock`)

### 2.2 Mock策略

| 组件 | Mock方式 | 说明 |
|------|----------|------|
| `call_llm()` / `call_writer()` / `call_judge()` | `unittest.mock.patch` | 所有API调用函数必须mock，返回fixture数据 |
| `httpx.Client` | `unittest.mock.patch` | 网络层mock |
| `subprocess.run` | `unittest.mock.patch` | Git命令mock |
| `load_dotenv()` | `unittest.mock.patch` | 环境变量加载mock |
| 文件系统 | `tmp_path` / `tmp_path_factory` | pytest内置临时目录fixture |

### 2.3 命名规范

```
tests/
├── unit/                          # 单元测试
│   ├── core/                      # test_config.py, test_state_manager.py, test_api_client.py
│   ├── evaluation/                # test_evaluate.py, test_antipatterns.py
│   ├── drafting/                  # test_draft_chapter.py
│   ├── foundation/                # test_gen_canon.py
│   ├── revision/                  # test_gen_brief.py, test_apply_cuts.py
│   ├── export/                    # test_build_manuscript.py
│   └── prompts/                   # test_chapter_prompts.py, test_eval_judge_prompts.py
├── integration/                   # 集成测试
│   └── test_pipeline_flow.py
├── fixtures/                      # 测试数据
│   ├── canon/                     # canon.md fixture变体
│   ├── eval_logs/                 # 模拟评估日志JSON
│   ├── edit_logs/                 # 模拟cuts/panel JSON
│   ├── chapters/                  # 模拟章节文件
│   ├── state/                     # state.json fixture变体
│   ├── config/                    # config.json / .env fixture变体
│   ├── edge_cases/                # 边界条件数据（空文件、超长文本、特殊字符等）
│   └── prompts/                   # 模拟prompt输出
└── conftest.py                    # 共享fixture和pytest配置
```

### 2.4 优先级定义

| 优先级 | 含义 | 建议执行频率 |
|--------|------|-------------|
| **P0** | 阻塞性 — 影响流水线运行或数据安全 | 每次commit前 |
| **P1** | 高风险 — 可能导致静默数据损坏或错误传播 | 每次push前 |
| **P2** | 中风险 — 影响特定场景的正确性或鲁棒性 | 每日CI |
| **P3** | 低风险 — 边界条件或非关键路径 | 每周CI |

---

## 3. 测试Fixture设计

### 3.1 原则

1. **最小化**: 每个fixture仅包含测试所需的最小数据
2. **可读性**: fixture数据使用人类可读的中文文本
3. **可变异**: 使用 `tmp_path` 确保测试间隔离
4. **代表性**: 覆盖正常、异常、边界三类数据

### 3.2 关键Fixture清单

#### 3.2.1 canon.md 变体 (用于 `test_gen_canon.py`)

| Fixture名 | 描述 | 条目数 |
|-----------|------|--------|
| `canon_full_450` | 标准格式，450条目（超过阈值400） | 450 |
| `canon_partial_200` | 标准格式，200条目（低于阈值400） | 200 |
| `canon_empty` | 空文件 | 0 |
| `canon_no_sections` | 无 `##` 节标题，仅有条目 | 50 |
| `canon_alt_format` | 使用 `-` 和 `*` 替代 `—` 作为bullet | 100 |
| `canon_mixed_bullets` | 混用 `—`、`-`、`*` 三种bullet | 80 |
| `canon_only_world` | 仅有"一、世界观"节 | 50 |
| `canon_extra_section` | 含"五、矛盾标注"之外的额外节（如"六、附录"） | 120 |

#### 3.2.2 state.json 变体 (用于 `test_state_manager.py`)

| Fixture名 | 描述 |
|-----------|------|
| `state_default` | `default_state()` 返回的初始状态 |
| `state_foundation_complete` | Foundation完成，phase=foundation, chapters_total=24 |
| `state_drafting_mid` | 起草中途，chapters_drafted=12 |
| `state_corrupt_json` | 无效JSON（中途截断） |
| `state_missing_keys` | 有效JSON但缺少 `phase` 等关键键 |
| `state_extra_keys` | 含未知额外键 |
| `state_empty` | 空JSON对象 `{}` |

#### 3.2.3 评估日志JSON (用于 `test_gen_brief.py` / `test_evaluate.py`)

| Fixture名 | 描述 |
|-----------|------|
| `eval_chapter_high` | 单章评估: overall_score=8.5, 所有维度≥7 |
| `eval_chapter_low` | 单章评估: overall_score=4.2, 多个维度≤5 |
| `eval_chapter_no_dimensions` | 单章评估: 缺少维度字段 |
| `eval_full_weak_ch3` | 全文评估: weakest_chapter=3, novel_score=6.8 |
| `eval_full_no_weakest` | 全文评估: 缺少 weakest_chapter 字段 |

#### 3.2.4 章节文件 (用于 `test_build_manuscript.py` / `test_draft_chapter.py`)

| Fixture名 | 描述 |
|-----------|------|
| `chapters_normal_10` | 10个连续章节 ch_01.md ~ ch_10.md，含标题和内容 |
| `chapters_with_gaps` | 缺少 ch_05.md 和 ch_08.md |
| `chapters_empty_mid` | ch_04.md 为空文件 |
| `chapters_no_title` | 章节首行非 `#` 标题 |
| `chapters_out_of_order` | 文件命名顺序与实际内容顺序不一致 |
| `chapters_special_names` | 含中文文件名如 `ch_第一章.md` |

#### 3.2.5 config.json / .env 变体 (用于 `test_config.py`)

| Fixture名 | 描述 |
|-----------|------|
| `env_full` | 完整 .env，所有键都有值 |
| `env_minimal` | 最小 .env，仅 `api_key` + `api_base_url` |
| `env_empty` | 空 .env |
| `env_missing` | .env 文件不存在 |
| `env_invalid_interval` | `api_interval_seconds=abc` |
| `config_json_full` | 完整 config.json |
| `config_json_partial` | 仅含部分键 |
| `config_json_corrupt` | JSON语法错误 |
| `config_json_missing` | config.json 不存在 |

#### 3.2.6 边界条件数据 (用于阶段5)

| Fixture名 | 描述 |
|-----------|------|
| `text_empty` | 空字符串 |
| `text_100k_chars` | 10万汉字长文本 |
| `text_emoji` | 含emoji的文本 😀🔥📖 |
| `text_windows_paths` | 含Windows路径的文本 `C:\Users\...` |
| `text_special_chars` | 含特殊字符: `\x00`, `\r\n`, 全角符号 |
| `outline_100_chapters` | 100章的大纲 |
| `characters_100` | 100个角色的注册表 |
| `voice_50_rules` | voice.md含50条规则 |

---

## 4. 阶段1: 模块导入与基础完整性测试

> **目标**: 验证所有Python模块可成功导入，`__init__.py` 正确导出，无循环依赖，`pyproject.toml` 声明完整。  
> **用例数**: 18  
> **执行时间**: < 5秒

### 4.1 模块导入测试 (TC-IMP-001 ~ TC-IMP-012)

| ID | 测试目标 | 输入 | 预期输出 | 优先级 | 风险点 |
|----|----------|------|----------|--------|--------|
| **TC-IMP-001** | 验证 `core.config` 可导入 | `import core.config` | 无 `ImportError` | P0 | R21 |
| **TC-IMP-002** | 验证 `core.state_manager` 可导入 | `import core.state_manager` | 无 `ImportError` | P0 | — |
| **TC-IMP-003** | 验证 `core.api_client` 可导入 | `import core.api_client` | 无 `ImportError` | P0 | — |
| **TC-IMP-004** | 验证 `core.diagnostic` 可导入 | `import core.diagnostic` | 无 `ImportError` | P1 | — |
| **TC-IMP-005** | 验证 `evaluation.evaluate` 可导入 | `import evaluation.evaluate` | 无 `ImportError` | P0 | — |
| **TC-IMP-006** | 验证 `evaluation.antipatterns` 可导入 | `import evaluation.antipatterns` | 无 `ImportError` | P1 | — |
| **TC-IMP-007** | 验证 `drafting.draft_chapter` 可导入 | `import drafting.draft_chapter` | 无 `ImportError` | P0 | — |
| **TC-IMP-008** | 验证 `foundation.gen_canon` 可导入 | `import foundation.gen_canon` | 无 `ImportError` | P1 | — |
| **TC-IMP-009** | 验证 `revision.gen_brief` 可导入 | `import revision.gen_brief` | 无 `ImportError` | P0 | — |
| **TC-IMP-010** | 验证 `revision.apply_cuts` 可导入 | `import revision.apply_cuts` | 无 `ImportError` | P0 | — |
| **TC-IMP-011** | 验证 `export.build_manuscript` 可导入 | `import export.build_manuscript` | 无 `ImportError` | P1 | — |
| **TC-IMP-012** | 验证 `prompts` 全部子模块可导入 | 逐个导入 `prompts.*` 包下9个模块 | 全部成功，无 `ImportError` | P1 | — |

### 4.2 导出完整性测试 (TC-IMP-013 ~ TC-IMP-015)

| ID | 测试目标 | 输入 | 预期输出 | 优先级 | 风险点 |
|----|----------|------|----------|--------|--------|
| **TC-IMP-013** | 验证 `core/__init__.py` 正确导出公共API | `from core import config, state_manager, api_client` | 三个模块均可通过包级别导入 | P2 | — |
| **TC-IMP-014** | 验证各子包 `__init__.py` 存在且非空 | 检查 `evaluation/`, `drafting/`, `foundation/`, `revision/`, `export/`, `prompts/` 的 `__init__.py` | 文件存在（允许为空 `__init__.py`） | P2 | — |
| **TC-IMP-015** | 验证 `voice_fingerprint` 可导入 | `import voice_fingerprint` | 无 `ImportError` | P2 | — |

### 4.3 循环依赖检测 (TC-IMP-016)

| ID | 测试目标 | 输入 | 预期输出 | 优先级 | 风险点 |
|----|----------|------|----------|--------|--------|
| **TC-IMP-016** | 验证核心模块间无循环导入 | `import pipeline_orchestrator` (导入整棵依赖树) | 无 `ImportError` 因循环依赖 | P0 | R22 |

### 4.4 依赖声明完整性 (TC-IMP-017 ~ TC-IMP-018)

| ID | 测试目标 | 输入 | 预期输出 | 优先级 | 风险点 |
|----|----------|------|----------|--------|--------|
| **TC-IMP-017** | 验证 `pyproject.toml` 中声明的依赖可安装 | 解析 `pyproject.toml` 的 `dependencies` 列表 | 包含 `httpx>=0.28.1`, `python-dotenv>=1.2.2` | P1 | — |
| **TC-IMP-018** | 验证 `pyproject.toml` 格式合法 | `tomllib.load()` 或手动解析 | 无解析错误；`requires-python >= 3.9` | P2 | — |

---

## 5. 阶段2: 配置与状态管理异常测试

> **目标**: 全面测试 `Config` 单例、`load_state`/`save_state`、`log_result`、`parse_score`、`evaluate_chapter_stable` 在各种异常条件下的行为。  
> **用例数**: 28  
> **执行时间**: < 30秒

### 5.1 Config 加载异常测试 (TC-CFG-001 ~ TC-CFG-009)

| ID | 测试目标 | 输入 | 预期输出 | 优先级 | 风险点 |
|----|----------|------|----------|--------|--------|
| **TC-CFG-001** | `.env` 缺失时的Config行为 | 删除 `.env` 文件，调用 `config.load()` | `config.loaded=True`, `api_key=""`, `api_base_url` 为默认值 | P0 | R01 |
| **TC-CFG-002** | `config.json` 缺失时的Config行为 | 删除 `config.json`，调用 `config.load()` | `config.loaded=True`, 仅加载 `.env` 中的值，非敏感键使用各属性默认值 | P0 | R01 |
| **TC-CFG-003** | `.env` 和 `config.json` 同时缺失 | 两个文件都不存在 | `config.loaded=True`, 所有属性返回硬编码默认值 | P0 | R01 |
| **TC-CFG-004** | `config.json` 损坏（无效JSON） | `config.json` 内容为 `{invalid json` | 静默跳过，只使用 `.env` 的值，不崩溃 | P1 | R01 |
| **TC-CFG-005** | `config.json` 含未知额外键 | `config.json` 中含 `{"unknown_field": 123}` | 未知字段被加载到 `_data` 中，可通过 `config.get("unknown_field")` 访问 | P2 | — |
| **TC-CFG-006** | `config.json` 含敏感键（不会被覆盖） | `config.json` 中写 `{"api_key": "evil_key"}` | `.env` 中的 `api_key` 不被覆盖 | P1 | — |
| **TC-CFG-007** | `api_interval_seconds` 为非数字值 | `.env` 中 `AUTONOVEL_API_INTERVAL_SECONDS=abc` | `config.api_interval_seconds` 返回 `4.0`，无异常 | P2 | R17 |
| **TC-CFG-008** | `config.load()` 多次调用 | 连续调用 `config.load()` 3次 | `_loaded=True` 后的调用立即返回缓存 `_data`，不重复读取文件 | P2 | — |
| **TC-CFG-009** | `config.save()` 写入后 `config.load()` 重载 | `config.save({"novel_title": "测试"}); config.load()` | 新加载包含刚保存的键 | P2 | — |

### 5.2 模型tier推断测试 (TC-CFG-010 ~ TC-CFG-013)

| ID | 测试目标 | 输入 | 预期输出 | 优先级 | 风险点 |
|----|----------|------|----------|--------|--------|
| **TC-CFG-010** | 已知high模型推断 | `model_name="deepseek-ai/DeepSeek-V3"` | `config.model_tier == "high"` | P1 | R11 |
| **TC-CFG-011** | 已知medium模型推断 | `model_name="Qwen2.5-32B-Instruct"` | `config.model_tier == "medium"` | P1 | R11 |
| **TC-CFG-012** | 未知模型推断为low | `model_name="some-new-model-2026"` | `config.model_tier == "low"` | P1 | R11 |
| **TC-CFG-013** | `apply_model_tier_defaults()` 设置正确阈值 | tier=high | `foundation_threshold=7.5, chapter_threshold=6.0, max_foundation_iters=10` | P1 | R11 |

### 5.3 `load_state()` / `save_state()` 异常测试 (TC-STM-001 ~ TC-STM-006)

| ID | 测试目标 | 输入 | 预期输出 | 优先级 | 风险点 |
|----|----------|------|----------|--------|--------|
| **TC-STM-001** | `state.json` 不存在 | 删除 `state.json`，调用 `load_state()` | 返回 `default_state()`，包含所有默认键 | P0 | R03 |
| **TC-STM-002** | `state.json` JSON损坏 | `state.json` 内容为 `{"phase": "foundation`（截断） | 返回 `default_state()`，不抛异常 | P0 | R03 |
| **TC-STM-003** | `state.json` 缺少关键键 | `state.json` 内容为 `{"phase": "drafting"}`（缺少 `iteration` 等） | 返回的dict仅含 `phase`，其他键调用者通过 `.get()` 获取默认值 | P1 | R03 |
| **TC-STM-004** | `save_state()` 写入到只读目录 | `OUTPUT_DIR` 权限为只读 | `IOError` 被 `_debug_log` 记录，不向上传播异常 | P1 | R25 |
| **TC-STM-005** | 快速连续 `save_state()` 5次 | 循环调用5次 `save_state()` | 所有写入成功，最终 `state.json` 内容为最后一次写入，无损坏 | P2 | R25 |
| **TC-STM-006** | `state.json` 含嵌套unicode/emoji | `state["current_focus"] = "测试🎯"` | `save_state()` 和 `load_state()` 正确保留emoji | P2 | — |

### 5.4 `log_result()` 测试 (TC-STM-007 ~ TC-STM-010)

| ID | 测试目标 | 输入 | 预期输出 | 优先级 | 风险点 |
|----|----------|------|----------|--------|--------|
| **TC-STM-007** | 首次调用写入TSV头 | `results.tsv` 不存在，调用 `log_result("abc", "foundation", 7.5, 1000, "keep", "")` | `results.tsv` 首行为header，第二行为数据行 | P0 | R07 |
| **TC-STM-008** | score=-1.0哨兵转error | `log_result("abc", "ch01", -1.0, 500, "keep", "test")` | `display_score="N/A"`, `display_status="error"`, description含"[评分解析失败]" | P1 | R07 |
| **TC-STM-009** | score=0.0正常记录 | `log_result("abc", "ch01", 0.0, 500, "discard", "test")` | `display_score=0.0`, `display_status="discard"` | P1 | R07 |
| **TC-STM-010** | 空 `results.tsv`（0字节）追加 | `results.tsv` 存在但为空，调用 `log_result()` | 先写入header再写入数据行 | P2 | — |

### 5.5 `parse_score()` 解析鲁棒性测试 (TC-PRS-001 ~ TC-PRS-008)

| ID | 测试目标 | 输入 | 预期输出 | 优先级 | 风险点 |
|----|----------|------|----------|--------|--------|
| **TC-PRS-001** | 纯JSON格式 | `'{"overall_score": 7.5}'` | 返回 `7.5` | P0 | R02 |
| **TC-PRS-002** | JSON在markdown代码块中 | `'```json\n{"overall_score": 6.0}\n```'` | 返回 `6.0` | P0 | R02 |
| **TC-PRS-003** | JSON前后有额外文本 | `'前导文本 {"overall_score": 8.2} 后续文本'` | 返回 `8.2` | P0 | R02 |
| **TC-PRS-004** | `**综合评分**: 7.5/10` 格式 | `'**综合评分**: 7.5/10'` | 返回 `7.5` | P1 | R02 |
| **TC-PRS-005** | `key: value` 格式 | `'overall_score: 8.0'` | 返回 `8.0` | P1 | R02 |
| **TC-PRS-006** | 纯数字 | `'7.5'` | 抛出 `ValueError`（无key匹配） | P1 | R02 |
| **TC-PRS-007** | 中文数字 | `'综合评分：七点五'` | 抛出 `ValueError` | P2 | R02 |
| **TC-PRS-008** | 空字符串 | `''` | 抛出 `ValueError` | P1 | R02 |

### 5.6 `evaluate_chapter_stable()` 中位数测试 (TC-STM-011 ~ TC-STM-013)

| ID | 测试目标 | 输入 | 预期输出 | 优先级 | 风险点 |
|----|----------|------|----------|--------|--------|
| **TC-STM-011** | 3次采样正常返回中位数 | mock `evaluate_chapter` 返回分数 [8.0, 6.0, 7.0] | 中位数 `7.0` | P1 | R09 |
| **TC-STM-012** | 含负值(-1.0)的采样被过滤 | mock返回 [8.0, -1.0, 7.0] | 中位数 `7.5`（有效值[7.0, 8.0]的中位数） | P1 | R09 |
| **TC-STM-013** | 全部采样失败 | mock全部抛异常 | 返回 `0.0` | P1 | R09 |

### 5.7 备份与恢复测试 (TC-STM-014 ~ TC-STM-016)

| ID | 测试目标 | 输入 | 预期输出 | 优先级 | 风险点 |
|----|----------|------|----------|--------|--------|
| **TC-STM-014** | git可用时 `git_add_commit` | mock `git_available()=True`, `subprocess.run` 返回成功 | `_git_run` 被调用，返回短哈希 | P1 | R14 |
| **TC-STM-015** | git不可用时 `git_add_commit` 回退文件备份 | mock `git_available()=False` | `backup_snapshot()` 被调用，创建 `backups/{timestamp}/` 目录 | P0 | R14 |
| **TC-STM-016** | `backup_snapshot()` 备份所有关键文件 | 在 `OUTPUT_DIR` 创建 `world.md`, `state.json` 等文件 | `backups/{timestamp}/` 下包含对应副本 + `chapters/` 子目录 + `label.txt` | P1 | R16 |

---

## 6. 阶段3: 各子模块纯逻辑单元测试

> **目标**: 对每个子模块的核心纯逻辑函数进行独立单元测试，不依赖LLM API。  
> **用例数**: 36  
> **执行时间**: < 60秒

### 6.1 Foundation — `count_canon_entries()` 测试 (TC-FND-001 ~ TC-FND-006)

| ID | 测试目标 | 输入 | 预期输出 | 优先级 | 风险点 |
|----|----------|------|----------|--------|--------|
| **TC-FND-001** | 标准格式计数 | `canon_full_450` fixture | `total=450`, `world>0`, `character>0`, `timeline>0`, `rules>0` | P0 | R08 |
| **TC-FND-002** | 空canon文件 | `canon_empty` fixture (0字节) | `{"total": 0, "world": 0, "character": 0, "timeline": 0, "rules": 0}` | P1 | R08 |
| **TC-FND-003** | canon文件不存在 | 路径指向不存在的文件 | `{"total": 0, "world": 0, ...}` 全部为0，不崩溃 | P1 | R08 |
| **TC-FND-004** | 无节标题但有条目 | `canon_no_sections` fixture | `total=0`（因为 `current_section` 始终为None，条目未被计数） | P1 | R08 |
| **TC-FND-005** | 混用 `—`、`-`、`*` bullet | `canon_mixed_bullets` fixture | 三种bullet均被正确计数 | P1 | R08 |
| **TC-FND-006** | 含额外节（如"六、附录"） | `canon_extra_section` fixture | 额外节的条目不被计入 `total`（未在 `sections` dict中定义） | P2 | R08 |

### 6.2 Drafting — 章节号计算与大纲提取测试 (TC-DRF-001 ~ TC-DRF-006)

| ID | 测试目标 | 输入 | 预期输出 | 优先级 | 风险点 |
|----|----------|------|----------|--------|--------|
| **TC-DRF-001** | `extract_chapter_outline()` 标准格式 `### 第 N 章` | 大纲文本含 `### 第 5 章 深渊之眼\n内容...\n### 第 6 章`，chapter_num=5 | 返回 `### 第 5 章 深渊之眼\n内容...` | P0 | R04 |
| **TC-DRF-002** | `extract_chapter_outline()` 英文格式 `### Ch N:` | 大纲文本含 `### Ch 3: Title\n...\n### Ch 4:`，chapter_num=3 | 返回匹配内容 | P1 | R04 |
| **TC-DRF-003** | `extract_chapter_outline()` 最后一章 | chapter_num=24（最后一章），无后续 `### 第 25 章` | 匹配到 `## 伏笔` 或文件末尾为止 | P1 | R04 |
| **TC-DRF-004** | `extract_chapter_outline()` 大纲文件不存在 | `outline_volume1.md` 和 `outline.md` 均不存在 | `load_file()` 返回空字符串，正则匹配失败，返回 `"(第 N 章大纲未找到)"` | P1 | R04 |
| **TC-DRF-005** | `extract_chapter_outline()` 章节号0 | chapter_num=0 | `vol_num` 计算为 `(0-1)//ch_per_vol+1`，可能为0或负数，路径异常 | P2 | R18 |
| **TC-DRF-006** | `extract_next_chapter_preview()` 最终章 | chapter_num=24 (total_chapters=24) | `extract_chapter_outline(25)` 返回"未找到"，最终返回 `"(最终章)"` | P1 | — |

### 6.3 Evaluation — `slop_score_zh()` 机械检测测试 (TC-EVL-001 ~ TC-EVL-010)

| ID | 测试目标 | 输入 | 预期输出 | 优先级 | 风险点 |
|----|----------|------|----------|--------|--------|
| **TC-EVL-001** | 无AI痕迹的文本 | 人类撰写的自然中文段落（300字） | `tier1_hits=[]`, `slop_penalty≈0`, `fiction_tell_count=0` | P0 | R15 |
| **TC-EVL-002** | 含Tier1套话 | 文本含"宛如一幅壮丽的画卷" | `tier1_hits` 非空, `slop_penalty >= 0.5` | P0 | R15 |
| **TC-EVL-003** | 含Tier2套话 | 文本含"他感到一阵寒意"、"眼中闪过一丝疑虑" | `tier2_hits` 非空, `slop_penalty >= 0.4` | P1 | R15 |
| **TC-EVL-004** | 含小说AI套话 (P3-12) | 文本含"空气中弥漫着紧张的气氛"、"一股暖流涌上心头" | `fiction_ai_tells` 非空, `slop_penalty` 增加 | P1 | R15 |
| **TC-EVL-005** | 含结构修辞公式 (P3-12) | 文本含"我不是说你错了，而是说你的方法有问题" | `structural_ai_tics` 非空, `slop_penalty` 增加 | P1 | R15 |
| **TC-EVL-006** | 含说教式情感 (show-don't-tell) | 文本含"他感到愤怒"、"她显得很悲伤" | `telling_violations > 0` | P1 | R15 |
| **TC-EVL-007** | 含段落开头过渡词滥用 | 多个段落以"然而"、"但是"、"此外"开头 | `transition_opener_ratio > 0` | P2 | R15 |
| **TC-EVL-008** | 破折号密度过高 | 文本每500字含5个"——" | `em_dash_density > 3`, `slop_penalty` 增加 | P2 | R15 |
| **TC-EVL-009** | 空文本 | `text=""` | 所有计数为0，`char_count=1`（防除零），`slop_penalty=0` | P1 | R15 |
| **TC-EVL-010** | 超长文本性能 | 10万汉字长文本 | `slop_score_zh()` 在可接受时间内完成（如 < 5秒），不抛出异常 | P2 | R15 |

### 6.4 Evaluation — `run_structural_audit()` 7项检测测试 (TC-EVL-011 ~ TC-EVL-017)

| ID | 测试目标 | 输入 | 预期输出 | 优先级 | 风险点 |
|----|----------|------|----------|--------|--------|
| **TC-EVL-011** | 过度解释检测 (OVER-EXPLAIN) | 文本含3+处"这意味着"、"说白了" | `over_explain.count >= 3`, warnings含"过度解释" | P1 | — |
| **TC-EVL-012** | 三连罗列检测 (TRIADIC LISTING) | 文本含连续三个结构相似的短句 | `triadic_listing.count >= 2`, warnings非空 | P1 | — |
| **TC-EVL-013** | 否定断言检测 (NEGATIVE-ASSERTION) | 文本含6+处"他没有..." | `negative_assertions.count > 5`, warnings含"否定断言过多" | P1 | — |
| **TC-EVL-014** | 比喻拐杖检测 (SIMILE CRUTCH) | 文本每千字含3+个比喻词 | `simile_crutch.per_1000_chars > 2.5`, warnings非空 | P1 | — |
| **TC-EVL-015** | 段落均匀化检测 (PARAGRAPH UNIFORMITY) | 连续3+段长度差<20% | `paragraph_uniformity.uniform_streak_ratio > 0.5` | P1 | — |
| **TC-EVL-016** | 分隔符滥用检测 (SECTION BREAK ABUSE) | 文本含3+个 `---` 分隔符 | `section_break_abuse.excessive == True` | P2 | — |
| **TC-EVL-017** | 目录式思考检测 (CATALOGING-BY-THINKING) | 文本含多处理科式"他想到了..." | `catalog_thinking.per_1000_chars > 1.5` | P2 | — |

### 6.5 Revision — `build_*_brief()` 数据聚合测试 (TC-REV-001 ~ TC-REV-006)

| ID | 测试目标 | 输入 | 预期输出 | 优先级 | 风险点 |
|----|----------|------|----------|--------|--------|
| **TC-REV-001** | `build_panel_brief()` 正常数据 | 提供完整 `reader_panel.json` + 章节文件 | 输出含 `# 修订摘要: 第N章`、`【核心问题】`、`【保留项】`、`【修订项】`、`【文风规则】`、`【字数目标】` | P0 | R13 |
| **TC-REV-002** | `build_panel_brief()` panel不存在 | `reader_panel.json` 缺失 | `load_panel()` 返回None → `sys.exit()` 被调用 | P1 | R13 |
| **TC-REV-003** | `build_eval_brief()` 无评估日志 | 无 `chapter_NN_*.json` 和 `full_*.json` | `sys.exit()` 被调用 | P1 | R13 |
| **TC-REV-004** | `build_cuts_brief()` cuts为空 | `chNN_cuts.json` 含0条目 | 正常生成摘要，核心问题区显示0字可删除 | P2 | R13 |
| **TC-REV-005** | `build_auto_brief()` 三源全部可用 | panel + eval + cuts 数据齐全 | 摘要包含三源交叉引用内容 | P0 | R13 |
| **TC-REV-006** | `build_auto_brief()` 无 `weakest_chapter` 字段 | `full_eval` JSON缺少 `weakest_chapter` 键 | `KeyError` 被捕获并抛出明确错误信息 | P1 | R13 |

### 6.6 Revision — `apply_cuts` 机械删除测试 (TC-REV-007 ~ TC-REV-010)

| ID | 测试目标 | 输入 | 预期输出 | 优先级 | 风险点 |
|----|----------|------|----------|--------|--------|
| **TC-REV-007** | `find_and_remove()` 精确单次匹配 | text含唯一子串 `"删除这段冗余文本"` | 子串被删除，返回 `(new_text, True, "")` | P0 | R05 |
| **TC-REV-008** | `find_and_remove()` 多次匹配（歧义） | text含2处相同子串 | 返回 `(text, False, "歧义 (2 处匹配)")`，原文本不变 | P0 | R05 |
| **TC-REV-009** | `find_and_remove()` 空白标准化回退 | text中匹配子串含额外空格 | normalize后匹配唯一，成功删除 | P1 | R05 |
| **TC-REV-010** | `process_chapter()` 赘语比例低于阈值 | `overall_fat_percentage=10`, `min_fat=15` | 跳过该章，返回 `error="赘语比例 10% < 阈值 15%"` | P2 | — |

### 6.7 Export — `build_manuscript()` 文件拼接测试 (TC-EXP-001 ~ TC-EXP-005)

| ID | 测试目标 | 输入 | 预期输出 | 优先级 | 风险点 |
|----|----------|------|----------|--------|--------|
| **TC-EXP-001** | 正常拼接10章 | `chapters_normal_10` fixture | `manuscript.md` 包含目录 + 10章，分隔符 `---`，总字数正确 | P0 | R10 |
| **TC-EXP-002** | 无章节文件 | `CHAPTERS_DIR` 为空 | `step("无章节文件，跳过")` 被调用，不创建 `manuscript.md` | P1 | R10 |
| **TC-EXP-003** | 中间有空章节 | `chapters_empty_mid` fixture (ch_04.md 为空) | ch_04 被 `continue` 跳过，目录编号与实际章节错位 | P1 | R10 |
| **TC-EXP-004** | 章节首行无 `#` 标题 | `chapters_no_title` fixture | 自动添加 `# 第 N 章` 前缀 | P1 | — |
| **TC-EXP-005** | 章节文件乱序 | 文件系统返回顺序与命名不一致 | `sorted(CHAPTERS_DIR.glob("ch_*.md"))` 按字符串排序保证顺序 | P2 | — |

### 6.8 Prompts — `build_*_prompt()` 输出格式测试 (TC-PRM-001 ~ TC-PRM-003)

| ID | 测试目标 | 输入 | 预期输出 | 优先级 | 风险点 |
|----|----------|------|----------|--------|--------|
| **TC-PRM-001** | `build_chapter_prompt()` 所有参数非空 | 提供全部参数（voice, world, characters, outline, canon, prev_context） | prompt包含所有节标题：【文风定义】、【本章大纲】、【下一章预告】、【前文回顾】、【世界观设定】、【角色注册表】、【正典】 | P0 | — |
| **TC-PRM-002** | `build_chapter_prompt()` canon为空时不输出正典节 | `canon_text=""` | prompt不含 `【正典（已确立的硬事实——不可违反）】` 节 | P1 | — |
| **TC-PRM-003** | `build_foundation_eval_prompt()` 可选参数为空 | `canon_text=""`, `mystery_text=""` | prompt不含 `【正典硬事实】` 和 `【核心谜团】` 节，其余13个评分维度完整 | P1 | — |

---

## 7. 阶段4: 管道串联与数据流完整性测试

> **目标**: 验证全流水线各阶段间的数据约定一致性和阶段调度逻辑。使用mock替换各阶段函数。  
> **用例数**: 14  
> **执行时间**: < 30秒

### 7.1 数据流契约测试 (TC-FLW-001 ~ TC-FLW-005)

| ID | 测试目标 | 输入 | 预期输出 | 优先级 | 风险点 |
|----|----------|------|----------|--------|--------|
| **TC-FLW-001** | Foundation→Drafting state传递 | mock `run_foundation()` 返回 `state` 含 `phase="drafting"`, `chapters_total=24` | `run_drafting(state)` 从 `state["chapters_drafted"]+1` 开始起草 | P0 | R23 |
| **TC-FLW-002** | Drafting→Revision state传递 | mock `run_drafting()` 返回 `state` 含 `phase="revision"`, `chapters_drafted=24` | `run_revision(state)` 读取 `state["novel_score"]` 作为 `prev_score` | P0 | R23 |
| **TC-FLW-003** | Revision→Export state传递 | mock `run_revision()` 返回 `state` 含 `phase="export"`, `novel_score=7.5` | `run_export(state)` 使用 `state.get("novel_score", "?")` 记录到 results.tsv | P1 | R23 |
| **TC-FLW-004** | 中断恢复：state含部分进度 | `state["phase"]="drafting"`, `state["chapters_drafted"]=12` | `run_pipeline(mode="resume")` 从 `PHASE_ORDER` 中 `drafting` 开始，起草第13章 | P0 | R23 |
| **TC-FLW-005** | 中断恢复：已完成流水线 | `state["phase"]="complete"` | `run_pipeline(mode="resume")` 打印提示并直接返回，不执行任何phase | P1 | R23 |

### 7.2 文件路径约定一致性测试 (TC-FLW-006 ~ TC-FLW-009)

| ID | 测试目标 | 输入 | 预期输出 | 优先级 | 风险点 |
|----|----------|------|----------|--------|--------|
| **TC-FLW-006** | 所有模块使用相同的 `OUTPUT_DIR` | 检查 `core/config.py`、`drafting/draft_chapter.py`、`evaluation/evaluate.py`、`revision/gen_brief.py`、`export/build_manuscript.py` | 全部 `from core.config import OUTPUT_DIR`，无硬编码路径 | P0 | R22 |
| **TC-FLW-007** | 所有模块使用相同的 `CHAPTERS_DIR` | 检查各模块 | 全部 `from core.config import CHAPTERS_DIR` | P0 | R22 |
| **TC-FLW-008** | 章节文件命名格式一致 | 各模块写入和读取章节 | 写入: `ch_{N:02d}.md`，读取: glob `ch_*.md` | P1 | R22 |
| **TC-FLW-009** | 评估日志命名格式一致 | `evaluation/evaluate.py:442` vs `revision/gen_brief.py:175` | 写入: `chapter_{ch:02d}_{ts}.json`，读取: glob `chapter_{ch:02d}_*.json` | P1 | R22 |

### 7.3 阶段调度逻辑测试 (TC-FLW-010 ~ TC-FLW-014)

| ID | 测试目标 | 输入 | 预期输出 | 优先级 | 风险点 |
|----|----------|------|----------|--------|--------|
| **TC-FLW-010** | `from_scratch` 模式验证梗概存在 | `config.story_summary=""`, `output/story_summary.txt` 不存在 | `sys.exit(1)` 被调用 | P0 | — |
| **TC-FLW-011** | `from_scratch` 模式清理旧产物 | `output/` 下有旧章节和state | 所有旧产物被删除：chapters/, briefs/, edit_logs/, eval_logs/, backups/ 目录被 `shutil.rmtree` | P1 | — |
| **TC-FLW-012** | KeyboardInterrupt 保存state后退出 | 在 `run_foundation` 执行中触发 `KeyboardInterrupt` | `save_state(state)` 被调用，`debug_log("USER_INTERRUPT")` 被调用，`sys.exit(130)` | P1 | — |
| **TC-FLW-013** | Phase异常传播 | mock `run_drafting()` 抛出 `RuntimeError` | 异常被 `except Exception` 捕获，`save_state(state)` 后重新 `raise` | P1 | — |
| **TC-FLW-014** | 修订循环上限参数传递 | `run_pipeline(max_cycles=3)` | `run_revision(state, max_cycles=3)`，最终修订循环不超过3 | P2 | — |

---

## 8. 阶段5: 边界条件与错误处理测试

> **目标**: 测试极端输入、特殊字符、并发模拟、Windows兼容性等边界条件。  
> **用例数**: 22  
> **执行时间**: < 60秒

### 8.1 空文件/缺失文件场景 (TC-EDG-001 ~ TC-EDG-005)

| ID | 测试目标 | 输入 | 预期输出 | 优先级 | 风险点 |
|----|----------|------|----------|--------|--------|
| **TC-EDG-001** | `load_file()` 文件不存在 | `drafting/draft_chapter.py:27-31` — 路径指向不存在文件 | 返回 `""`，不抛异常 | P1 | — |
| **TC-EDG-002** | 所有章节文件缺失时 `evaluate_full()` | `CHAPTERS_DIR` 为空 | 返回 `"novel_score: 0.0\n"` | P2 | — |
| **TC-EDG-003** | `world.md` 缺失时 `evaluate_foundation()` | `OUTPUT_DIR/world.md` 不存在 | `world=""`, 评估prompt中世界观部分为空 | P1 | — |
| **TC-EDG-004** | 所有大纲文件缺失时 `_load_outline()` | 无 `outline.md` 也无 `outline_volume*.md` | 返回 `""` | P1 | — |
| **TC-EDG-005** | `voice.md` 缺失时 `extract_voice_rules()` | `voice.md` 不存在 | 返回 `["(voice.md 未找到)"]` | P2 | R20 |

### 8.2 超长文本输入 (TC-EDG-006 ~ TC-EDG-009)

| ID | 测试目标 | 输入 | 预期输出 | 优先级 | 风险点 |
|----|----------|------|----------|--------|--------|
| **TC-EDG-006** | 100章大纲提取 | `outline_100_chapters` fixture，提取第50章 | `extract_chapter_outline(50)` 正确返回第50章内容 | P2 | R04 |
| **TC-EDG-007** | 100个角色的canon计数 | world+characters含100个角色的设定 | `count_canon_entries()` 返回合理数值，不OOM | P2 | — |
| **TC-EDG-008** | 100章手稿拼接 | `chapters_normal_100` | `build_manuscript()` 成功生成，目录含100条 | P2 | — |
| **TC-EDG-009** | 单章3万字 | 章节文件含30000汉字 | `slop_score_zh()` 和 `run_structural_audit()` 在合理时间内完成 | P2 | R15 |

### 8.3 特殊字符处理 (TC-EDG-010 ~ TC-EDG-014)

| ID | 测试目标 | 输入 | 预期输出 | 优先级 | 风险点 |
|----|----------|------|----------|--------|--------|
| **TC-EDG-010** | Windows路径作为文本内容 | 文本含 `C:\Users\测试\output\chapters\ch_01.md` | `slop_score_zh()` 不误匹配路径中的反斜杠 | P2 | — |
| **TC-EDG-011** | 中文文件名支持 | `CHAPTERS_DIR` 路径含中文字符 | `Path.read_text(encoding="utf-8")` 正常工作 | P1 | — |
| **TC-EDG-012** | emoji在章节文本中 | 章节含 `😀🔥📖💀` | `word_count()` 将emoji计为1字符（`len()` 行为），`save_state()` 正确序列化 | P2 | — |
| **TC-EDG-013** | 章节标题含特殊字符 | 标题为 `# 第1章：测试——"引号"与'单引号'` | `build_manuscript()` 目录正确渲染 | P3 | — |
| **TC-EDG-014** | `.env` 值含 `=` 号 | `AUTONOVEL_API_KEY=key=with=equals` | `load_dotenv` 正确解析，`config.api_key` 为完整值 | P2 | — |

### 8.4 JSON解析容错 (TC-EDG-015 ~ TC-EDG-018)

| ID | 测试目标 | 输入 | 预期输出 | 优先级 | 风险点 |
|----|----------|------|----------|--------|--------|
| **TC-EDG-015** | `_parse_json_response()` 嵌套JSON含 `}` 在字符串中 | `'{"text": "包含}右花括号"}'` | 第3层回退正确匹配外层花括号 | P1 | R12 |
| **TC-EDG-016** | `_parse_json_response()` 深度嵌套 (5层) | 5层嵌套JSON对象 | 全部正确解析，`json.loads` 或深度匹配均成功 | P2 | R12 |
| **TC-EDG-017** | `_parse_json_response()` 多余字段 | JSON含未定义的额外字段 | 正常解析，额外字段被保留在返回dict中 | P2 | — |
| **TC-EDG-018** | `_parse_json_response()` 缺少必需字段 | JSON缺少 `overall_score` | 返回dict不含该键，调用者通过 `.get()` 安全访问 | P2 | — |

### 8.5 并发与Windows兼容性 (TC-EDG-019 ~ TC-EDG-022)

| ID | 测试目标 | 输入 | 预期输出 | 优先级 | 风险点 |
|----|----------|------|----------|--------|--------|
| **TC-EDG-019** | 快速连续写入 `save_state()` | 5个线程同时调用 `save_state()` | 所有写入完成，最终文件内容为其中之一，不损坏 | P2 | R25 |
| **TC-EDG-020** | 快速连续追加 `log_result()` | 5个线程同时调用 `log_result()` | TSV行数正确，无交错写入（取决于OS缓冲，至少不崩溃） | P2 | — |
| **TC-EDG-021** | Windows管道模式下 `sys.stdout.reconfigure` | mock `sys.platform="win32"`, `sys.stdout.encoding="utf-8"` (已是utf-8) | `reconfigure` 不报错或异常被静默捕获 | P0 | R06 |
| **TC-EDG-022** | `sys.stdout.reconfigure` 在非tty环境 | mock `sys.stdout.reconfigure` 抛出 `OSError` | 异常被多处 `try/except` 捕获不导致崩溃 | P0 | R06 |

---

## 9. 预期测试文件结构

```
tests/
├── __init__.py                                     # (已存在)
├── conftest.py                                     # 全局fixture: tmp_path, mock_config, mock_llm
│
├── unit/
│   ├── __init__.py                                 # (已存在)
│   ├── core/
│   │   ├── __init__.py                             # (已存在)
│   │   ├── test_config.py                          # TC-CFG-001 ~ TC-CFG-013 (13个)
│   │   ├── test_state_manager.py                   # TC-STM-001 ~ TC-STM-016 + TC-PRS-001 ~ TC-PRS-008 (24个)
│   │   └── test_api_client.py                      # RateLimiter基本测试 (2个，可选)
│   │
│   ├── evaluation/
│   │   ├── __init__.py                             # (已存在)
│   │   ├── test_slop_score.py                      # TC-EVL-001 ~ TC-EVL-010 (10个)
│   │   ├── test_antipatterns.py                    # TC-EVL-011 ~ TC-EVL-017 (7个)
│   │   └── test_json_parse.py                      # JSON解析三级回退测试 (5个，含TC-EDG-015~018)
│   │
│   ├── drafting/
│   │   ├── __init__.py
│   │   └── test_draft_chapter.py                   # TC-DRF-001 ~ TC-DRF-006 (6个)
│   │
│   ├── foundation/
│   │   ├── __init__.py
│   │   └── test_gen_canon.py                       # TC-FND-001 ~ TC-FND-006 (6个)
│   │
│   ├── revision/
│   │   ├── __init__.py
│   │   ├── test_gen_brief.py                       # TC-REV-001 ~ TC-REV-006 (6个)
│   │   └── test_apply_cuts.py                      # TC-REV-007 ~ TC-REV-010 (4个)
│   │
│   ├── export/
│   │   ├── __init__.py
│   │   └── test_build_manuscript.py                # TC-EXP-001 ~ TC-EXP-005 (5个)
│   │
│   └── prompts/
│       ├── __init__.py                             # (已存在)
│       ├── test_chapter_prompts.py                 # TC-PRM-001 ~ TC-PRM-002 (2个)
│       └── test_eval_judge_prompts.py              # TC-PRM-003 (1个)
│
├── integration/
│   ├── __init__.py
│   └── test_pipeline_flow.py                       # TC-FLW-001 ~ TC-FLW-014 (14个)
│
├── edge/
│   ├── __init__.py
│   └── test_boundary.py                            # TC-EDG-001 ~ TC-EDG-022 (22个)
│
├── architecture/
│   ├── __init__.py                                 # (已存在)
│   └── test_imports.py                             # TC-IMP-001 ~ TC-IMP-018 (18个)
│
└── fixtures/
    ├── __init__.py
    ├── conftest.py                                 # fixture定义（共享测试数据工厂）
    ├── canon/
    │   ├── full_450.md
    │   ├── partial_200.md
    │   ├── no_sections.md
    │   ├── alt_format.md
    │   ├── mixed_bullets.md
    │   ├── only_world.md
    │   └── extra_section.md
    ├── eval_logs/
    │   ├── chapter_03_high.json
    │   ├── chapter_03_low.json
    │   ├── chapter_03_no_dimensions.json
    │   ├── full_weak_ch3.json
    │   └── full_no_weakest.json
    ├── edit_logs/
    │   ├── ch03_cuts_normal.json
    │   ├── ch03_cuts_empty.json
    │   └── reader_panel_full.json
    ├── chapters/
    │   ├── normal_10/       (ch_01.md ~ ch_10.md)
    │   ├── with_gaps/       (缺少 ch_05.md, ch_08.md)
    │   ├── empty_mid/       (ch_04.md 为空)
    │   ├── no_title/        (首行非#标题)
    │   └── special_names/   (边界命名)
    ├── state/
    │   ├── default.json
    │   ├── foundation_complete.json
    │   ├── drafting_mid.json
    │   ├── corrupt.json
    │   ├── missing_keys.json
    │   └── empty.json
    ├── config/
    │   ├── env_full
    │   ├── env_minimal
    │   ├── config_full.json
    │   ├── config_partial.json
    │   └── config_corrupt.json
    ├── edge_cases/
    │   ├── empty.md                                 # (已存在)
    │   ├── text_100k.txt
    │   ├── text_emoji.md
    │   ├── text_special_chars.md
    │   ├── outline_100_chapters.md
    │   └── characters_100.md
    └── prompts/
        ├── chapter_prompt_baseline.txt
        └── foundation_eval_baseline.txt
```

---

## 10. 执行顺序建议

```
Phase 0: 环境准备
  ├── 0.1 验证pytest安装和配置
  ├── 0.2 验证所有fixture目录和文件就位
  └── 0.3 运行 TC-IMP-001~018 (模块导入，最快，最先发现问题)

Phase 1: 核心基础设施
  ├── 1.1 test_config.py (TC-CFG-001~013)  [Config是全局单例，必须先验证]
  ├── 1.2 test_state_manager.py (TC-STM-001~016)  [状态管理核心]
  └── 1.3 test_state_manager.py (TC-PRS-001~008)  [分数解析，影响所有评估]

Phase 2: 子模块纯逻辑
  ├── 2.1 test_slop_score.py (TC-EVL-001~010)  [机械检测，无外部依赖]
  ├── 2.2 test_antipatterns.py (TC-EVL-011~017)  [反模式检测]
  ├── 2.3 test_json_parse.py  [JSON解析]
  ├── 2.4 test_gen_canon.py (TC-FND-001~006)  [正典计数]
  ├── 2.5 test_draft_chapter.py (TC-DRF-001~006)  [大纲提取]
  ├── 2.6 test_gen_brief.py (TC-REV-001~006)  [摘要生成]
  ├── 2.7 test_apply_cuts.py (TC-REV-007~010)  [机械裁剪]
  ├── 2.8 test_build_manuscript.py (TC-EXP-001~005)  [手稿导出]
  └── 2.9 test_*_prompts.py (TC-PRM-001~003)  [Prompt格式]

Phase 3: 管道集成
  └── 3.1 test_pipeline_flow.py (TC-FLW-001~014)  [数据流契约]

Phase 4: 边界条件
  └── 4.1 test_boundary.py (TC-EDG-001~022)  [边界条件和错误处理]
```

---

## 11. 附录: 测试用例索引

### 按模块统计

| 模块 | 用例数 | ID范围 |
|------|--------|--------|
| 模块导入 | 18 | TC-IMP-001 ~ TC-IMP-018 |
| Config | 13 | TC-CFG-001 ~ TC-CFG-013 |
| StateManager + parse_score | 24 | TC-STM-001 ~ TC-STM-016 + TC-PRS-001 ~ TC-PRS-008 |
| Foundation | 6 | TC-FND-001 ~ TC-FND-006 |
| Drafting | 6 | TC-DRF-001 ~ TC-DRF-006 |
| Evaluation (slop + antipatterns) | 17 | TC-EVL-001 ~ TC-EVL-017 |
| Revision (brief + cuts) | 10 | TC-REV-001 ~ TC-REV-010 |
| Export | 5 | TC-EXP-001 ~ TC-EXP-005 |
| Prompts | 3 | TC-PRM-001 ~ TC-PRM-003 |
| Pipeline Flow | 14 | TC-FLW-001 ~ TC-FLW-014 |
| Boundary | 22 | TC-EDG-001 ~ TC-EDG-022 |
| **总计** | **108** | |

### 按优先级统计

| 优先级 | 数量 | 占比 |
|--------|------|------|
| P0 (阻塞性) | 26 | 24% |
| P1 (高风险) | 48 | 44% |
| P2 (中风险) | 31 | 29% |
| P3 (低风险) | 3 | 3% |

### 风险点覆盖矩阵

| 风险点 | 覆盖用例 |
|--------|----------|
| R01 (Config未加载) | TC-CFG-001, 002, 003, 004 |
| R02 (parse_score失败) | TC-PRS-001~008 |
| R03 (load_state损坏) | TC-STM-001, 002, 003 |
| R04 (大纲正则失败) | TC-DRF-001~005, TC-EDG-006 |
| R05 (apply_cuts歧义) | TC-REV-007, 008, 009 |
| R06 (Windows编码) | TC-EDG-021, 022 |
| R07 (哨兵拦截) | TC-STM-008, 009 |
| R08 (canon计数) | TC-FND-001~006 |
| R09 (中位数边界) | TC-STM-011, 012, 013 |
| R10 (空章节错位) | TC-EXP-001~003 |
| R11 (model tier) | TC-CFG-010~013 |
| R12 (JSON深度匹配) | TC-EDG-015, 016 |
| R13 (brief数据源缺失) | TC-REV-001~006 |
| R14 (git cmd转义) | TC-STM-014, 015 |
| R15 (slop性能) | TC-EVL-001~010 |
| R16 (备份跨驱动器) | TC-STM-016 |
| R17 (interval非数字) | TC-CFG-007 |
| R18 (除零错误) | TC-DRF-005 |
| R19 (零章编号) | TC-REV-007~010 中包含边界测试 |
| R20 (空voice) | TC-EDG-005 |
| R21 (只读FS崩溃) | TC-IMP-001 |
| R22 (路径不一致) | TC-FLW-006~009 |
| R23 (state schema) | TC-FLW-001~005 |
| R24 (中文数字匹配) | TC-FLW-014 (间接覆盖) |
| R25 (非原子写入) | TC-STM-005, TC-EDG-019 |

---

*本方案由 autonovel-zh 架构审计生成，所有测试用例设计为在无LLM API环境下可独立运行。*
