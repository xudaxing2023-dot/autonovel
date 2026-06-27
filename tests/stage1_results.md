# Stage 1 静态分析 — 执行结果报告

> 执行时间: 2026-06-20  
> 分析工具: [`tests/stage1_analysis.py`](tests/stage1_analysis.py)  
> 覆盖文件: 38 个 `.py` 文件  
> 通过标准: 0 语法错误, 0 导入断裂, 0 死代码严重项

---

## 执行汇总

| 检查项 | 状态 | 详情 |
|--------|------|------|
| 1.1 py_compile 全量编译 | ✅ 通过 | 38/38 文件编译成功 |
| 1.2.2 裸 except | ✅ 通过 | 0 个裸 except |
| 1.2.3 静默吞错 | ⚠️ 警告 | 1 处 (gen_voice.py:181) |
| 1.2.4 read_text 安全性 | ✅ 通过 | 所有调用有保护 |
| 1.3.1 三方依赖 | ✅ 通过 | httpx + python-dotenv 覆盖 |
| 1.3.2 死代码 | ⚠️ 警告 | 3 处 (call_p3_judge / 代码重复 / 路径偏离) |
| 1.3.3 路径拼接 | ⚠️ 警告 | 1 处 (voice_fingerprint.py) |
| 1.4.1 SECRET_KEYS | ✅ 通过 | 19/19 映射 + Config 属性正确 |
| 1.4.2 Phase 回退链 | ✅ 通过 | 逻辑正确 |
| 1.4.3 default_state | ⚠️ 警告 | state["review_revision_round"] 未定义 |
| 1.5 硬编码审计 | ✅ 通过 | 76 个模块级常量已登记 |
| 1.6.1 Python 3.9 兼容性 | ❌ 失败 | 6 处 PEP 604 (X \| None) 语法 |
| 1.6.4 循环依赖 | ✅ 通过 | 0 循环依赖 |
| 1.6.5 敏感信息泄露 | ✅ 通过 | 0 处泄露 |

**结论: ⚠️ 通过(有阻塞性问题需修复) — 修复 1.6.1 PEP 604 语法后可进入 Stage 2**

---

## 发现的 BUG 清单

| ID | 严重度 | 描述 | 文件:行号 | 状态 |
|----|--------|------|---------|------|
| **BUG-S1-01** | 🔴 高 | Python 3.9 兼容性: 6 处 PEP 604 `X \| None` 语法，与 `pyproject.toml` 中 `requires-python = ">=3.9"` 冲突 | 见下方详细列表 | **NEW — 6处(比方案预计多4处)** |
| **BUG-S1-02** | 🟡 中 | 死代码: `call_p3_judge()` 仅定义未被引用 | [`core/api_client.py:492-508`](core/api_client.py:492) | 已确认 |
| **BUG-S1-03** | 🟡 中 | 静默吞错: `except Exception: pass` 隐藏 JSON 解析失败 | [`foundation/gen_voice.py:181`](foundation/gen_voice.py:181) | 已确认 |
| **BUG-S1-04** | 🟡 中 | 代码重复: SEED prompts + 辅助函数 | [`novel_app.py:28-201`](novel_app.py:28) ↔ [`seed.py:29-196`](seed.py:29) | 已确认 |
| **BUG-S1-05** | 🟢 低 | 路径偏离: 局部路径常量 | [`voice_fingerprint.py:21-23`](voice_fingerprint.py:21) | 已确认 |
| **BUG-S1-06** | 🟢 低 | 文档不一致: SECRET_KEYS 14→19, default_state 15→16 | [`enterprise_test_plan.md`](plans/enterprise_test_plan.md) | 已确认 |
| **BUG-S1-07** | 🟡 中 | **NEW** — default_state 缺失字段: `pipeline_orchestrator.py` 写入 `state["review_revision_round"]` 但 `default_state()` 未定义 | [`pipeline_orchestrator.py:1057`](pipeline_orchestrator.py:1057) | **新发现** |

---

### BUG-S1-01 详细: PEP 604 语法位置 (共6处)

| # | 文件:行号 | 代码 | 
|---|---------|------|
| 1 | [`evaluation/evaluate.py:274`](evaluation/evaluate.py:274) | `def _resolve_outline_path(chapter_num: int \| None = None) -> tuple:` |
| 2 | [`evaluation/evaluate.py:314`](evaluation/evaluate.py:314) | `def _load_outline(chapter_num: int \| None = None) -> str:` |
| 3 | [`novel_app.py:110`](novel_app.py:110) | `def _build_genre_constraint(genre_hint: str \| None, count: int) -> str:` |
| 4 | [`novel_app.py:121`](novel_app.py:121) | `def _build_genre_diversity(genre_hint: str \| None, count: int) -> str:` |
| 5 | [`seed.py:166`](seed.py:166) | `def _build_genre_constraint(genre_hint: str \| None, count: int) -> str:` |
| 6 | [`seed.py:177`](seed.py:177) | `def _build_genre_diversity(genre_hint: str \| None, count: int) -> str:` |

**修复方案**: 将所有 `str | None` 替换为 `Optional[str]`，并在文件头部添加 `from typing import Optional`。

---

### BUG-S1-07 详细: default_state 缺失字段

[`pipeline_orchestrator.py:1057`](pipeline_orchestrator.py:1057) 写入:
```python
state["review_revision_round"] = rnd
```

但 [`core/state_manager.py:71-90`](core/state_manager.py:71) 的 `default_state()` 返回的 16 个字段中不包含 `review_revision_round`。

虽然 Python dict 允许动态添加键（`load_state()` 从已存在的 state.json 加载会包含此键），但缺少初始定义意味着:
1. `from_scratch` 模式首次运行时不会初始化此字段
2. 日志/监控脚本如果遍历 `default_state().keys()` 会遗漏

**修复方案**: 在 `default_state()` 中添加 `"review_revision_round": 0`。

---

## 门禁标准评估

| 门禁项 | 标准 | 实际 | 是否通过 |
|--------|------|------|---------|
| 0 语法错误 | 必须 | 38/38 py_compile OK | ✅ |
| 0 导入断裂 | 必须 | 0 断裂 (全部通过 AST + py_compile) | ✅ |
| 0 死代码严重项 | 必须 | 3 处非阻塞性警告 | ⚠️ 可接受 |
| 0 配置不一致 | 建议 | 1 处 default_state 缺失字段 | ⚠️ 需修复 |
| Python 版本兼容 | 必须 | 6 处 PEP 604 vs >=3.9 | ❌ **阻塞** |

---

## 修复优先级

1. **立即修复** (阻塞 Stage 2):
   - BUG-S1-01: 6 处 `str | None` → `Optional[str]` (3 个文件: `evaluate.py`, `novel_app.py`, `seed.py`)

2. **建议修复** (进入 Stage 2 前):
   - BUG-S1-07: `default_state()` 添加 `review_revision_round`
   - BUG-S1-03: `gen_voice.py:181` 添加日志

3. **可选修复** (不阻塞):
   - BUG-S1-02: 集成 `call_p3_judge()` 或标记为预留
   - BUG-S1-04: 抽取共享 prompts 到独立模块
   - BUG-S1-05: 统一路径引用
   - BUG-S1-06: 更新文档

---

## 自动化分析脚本

[`tests/stage1_analysis.py`](tests/stage1_analysis.py) — 可在修复后重新运行验证:

```bash
python tests/stage1_analysis.py