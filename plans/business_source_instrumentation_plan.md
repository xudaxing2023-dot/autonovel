# 业务源码插桩方案

## 目标

在业务源码的关键故障路口埋入诊断日志，使任何异常通过路口时自动记录上下文，
不再需要每次出现新异常都写诊断脚本手动追查。

## 日志膨胀对策

每轮程序执行前清空 `logs/diagnostic.log`（不是 debug.log），只保留当前运行诊断数据。
测试脚本的 `debug.log`（详细时间线）仍按现有机制运行。

```
logs/
  diagnostic.log    ← 业务插桩日志（每轮覆盖）
  debug.log         ← 测试脚本时间线日志（追加）
  diagnosis_report.txt ← 诊断分析脚本输出（每轮覆盖）
```

## 插桩基础设施

在 `core/` 下新建极简模块 `diagnostic.py`：

```python
# core/diagnostic.py
"""业务插桩基础设施 — 零依赖，极简"""

import sys
import time
from datetime import datetime
from pathlib import Path

LOG_PATH = Path(__file__).parent.parent / "logs" / "diagnostic.log"

def _ensure():
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

def diag(event: str, detail: str = "", data: dict = None):
    """通用诊断日志 — 写入 diagnostic.log，每行 flush"""
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    entry = f"[{ts}] [{event}] {detail}"
    if data:
        entry += f" | {_fmt(data)}"
    _ensure()
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(entry + "\n")
        f.flush()
    print(f"  [DIAG] {entry}", file=sys.stderr)

def _fmt(data: dict, max_v=200) -> str:
    """安全格式化，截断长值"""
    parts = []
    for k, v in data.items():
        s = str(v)
        if len(s) > max_v:
            s = s[:max_v] + "..."
        parts.append(f"{k}={s}")
    return ", ".join(parts)
```

## 插桩点清单（共 18 个路口，7 个文件）

### Tier 1 — 哨兵值与故障分叉（6 点）

| # | 文件 | 函数/位置 | 事件码 | 插桩内容 |
|---|------|----------|--------|---------|
| 1 | `core/state_manager.py:389` | `parse_score()` 返回 -1.0 | `SENTINEL_PARSE` | 原始输入前200字符、key参数 |
| 2 | `core/state_manager.py:192` | `git_reset_hard()` 调用前 | `GIT_RESET` | ref参数、调用栈摘要（最后3帧） |
| 3 | `pipeline_orchestrator.py:148` | Foundation 评分比较前 | `FOUNDATION_SCORE_CMP` | score, best_score, iter, threshold |
| 4 | `pipeline_orchestrator.py:163` | Foundation 丢弃时 | `FOUNDATION_DISCARD` | score, best_score, iter, phase |
| 5 | `pipeline_orchestrator.py:337` | 章节 Draft 丢弃重试 | `DRAFT_DISCARD` | chapter, score, threshold, attempt |
| 6 | `pipeline_orchestrator.py:814` | `evaluate_full` novel_score < 0 | `NOVEL_SCORE_NEG` | full_eval前200字符 |

### Tier 2 — 修订回退路口（4 点）

| # | 文件 | 函数/位置 | 事件码 | 插桩内容 |
|---|------|----------|--------|---------|
| 7 | `pipeline_orchestrator.py:533` | Path A 修订回退 | `REV_BACK_A` | ch_num, pre_score, post_score, cycle |
| 8 | `pipeline_orchestrator.py:797` | Path B 修订回退 | `REV_BACK_B` | ch_num, pre_score, post_score, cycle, reason |
| 9 | `pipeline_orchestrator.py:1029` | Path C 审阅修订回退 | `REV_BACK_C` | ch_num, pre_score, post_score, rnd |
| 10 | `pipeline_orchestrator.py:813` | 平台期检测 | `PLATEAU_DETECT` | current_score, prev_score, delta, threshold |

### Tier 3 — 异常吞噬点（5 点，仅关键吞异常）

| # | 文件 | 行号 | 事件码 | 插桩内容 |
|---|------|------|--------|---------|
| 11 | `pipeline_orchestrator.py:735` | `pre_score = 0` exc | `PRE_EVAL_FAIL` | ch_num, exc_type, exc_msg |
| 12 | `pipeline_orchestrator.py:776` | `post_score = 0` exc | `POST_EVAL_FAIL` | ch_num, exc_type, exc_msg |
| 13 | `pipeline_orchestrator.py:966` | Path C `pre_score = 0` exc | `PRE_EVAL_C_FAIL` | ch_num, exc_type, exc_msg |
| 14 | `pipeline_orchestrator.py:1009` | Path C `post_score = 0` exc | `POST_EVAL_C_FAIL` | ch_num, exc_type, exc_msg |
| 15 | `core/api_client.py:248` | API 调用异常 | `API_EXCEPTION` | exc_type, exc_msg, attempt, model |

### Tier 4 — 状态不一致（3 点）

| # | 文件 | 函数/位置 | 事件码 | 插桩内容 |
|---|------|----------|--------|---------|
| 16 | `pipeline_orchestrator.py:132` | Foundation canon 不足警告 | `CANON_LOW` | canon_total, threshold |
| 17 | `pipeline_orchestrator.py:945` | 章节不存在跳过 | `CHAPTER_MISSING` | ch_num, chapters_total, weak_chapters |
| 18 | `pipeline_orchestrator.py:172` | 总章节数确定 | `CHAPTERS_TOTAL` | total, volumes_outlined, ch_per_vol |

## 实施步骤

### Step 1: 创建 core/diagnostic.py (约 40 行)

### Step 2: 在 7 个文件追加 import

仅在需要插桩的文件顶部追加一行：
```python
from core.diagnostic import diag  # 业务插桩
```

涉及文件：
- `core/state_manager.py`
- `core/api_client.py`
- `pipeline_orchestrator.py`
- （其余 4 个文件为 pipeline_orchestrator 的子模块，当前 18 个点全部在以上 3 个文件中）

### Step 3: 逐个埋点（共 18 处，每处 1-3 行）

### Step 4: 语法验证 + 空跑验证

## 关于日志膨胀的回答

用户提出「每跑一遍删一次日志」。这个策略可行，方案如下：

- `diagnostic.log` 每次运行开头清空（在 `pipeline_orchestrator.py` 入口或 `diagnostic.py` 的 `_ensure()` 中增加覆盖模式参数）
- 或者在 `novel_app.py` / `main.py` 启动时清空
- **不建议手动删文件** — 手动删除容易遗漏，建议自动化

实现方式（二选一）：
```python
# 方式A: 每次 import core.diagnostic 时清空（最自动化）
# 在 _ensure() 加上首次写入时清空

# 方式B: 在 main.py / novel_app.py 启动时调用
from core.diagnostic import clear_log
clear_log()
```

## 原则

- 每个插桩点 ≤ 3 行代码
- 不使用 `except` 包装（避免插桩本身成为异常源）
- 字符串拼接，不用 f-string 计算复杂表达式
- 日志行格式：`[时间] [事件码] 描述 | key=截断值`
- 总写入量：每轮约 50-200 行（取决于迭代次数），约 30KB-100KB