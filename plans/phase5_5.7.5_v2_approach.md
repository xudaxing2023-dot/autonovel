# 【5.7.5 v2 方案】全新执行策略

> **目的**：绕开反复失败的死循环，用全新方式完成 5.7.5
> **核心变更**：放弃 `apply_diff`，一次性用 Python 脚本修复全部 Bug，分级验证

---

## 1. 已知的全部 Bug（一次修复）

| # | 文件 | 行号 | 问题 | 修复 |
|---|------|------|------|------|
| B1 | `revision/gen_brief.py` | 749 | `sys.exit()` 静默杀死进程 | `raise FileNotFoundError(...)` |
| B2 | `revision/gen_brief.py` | 754 | `sys.exit()` 同上 | `raise ValueError(...)` |
| B3 | `pipeline_orchestrator.py` | 438 | `threshold` 变量未定义 | `threshold = cfg.chapter_threshold if cfg.loaded else CHAPTER_THRESHOLD` |

## 2. 新执行策略：3 层验证

```
Layer 1 — 最小验证 (~15min API):
  复用现有4章 → 只跑 run_revision(max_cycles=1)
  通过标准: revision_cycle ≥ 1

Layer 2 — 中验证 (~25min API):
  从头跑 Foundation + Drafting + Revision cycle 1
  通过标准: 中断1+2+3 全部通过

Layer 3 — 完整验证 (~40min API):
  5步全流程 Foundation → Drafting → Revision → Export → Complete
  通过标准: 全部5步通过
```

## 3. 一次性修复脚本

创建 `_fix_all_bugs.py`，在一个 Python 进程中修复全部 3 个 Bug。

## 4. 放弃 `apply_diff`

全部用 Python 脚本 `string.replace()` 直接写入文件，确保修复立即生效。

## 5. 环境管理

每个 Layer 执行前自动清理 `output/` 目录，避免残留污染。