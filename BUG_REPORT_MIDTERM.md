# 🐛 全流水线测试 — 中期 BUG 报告

> **状态**：⚠️ 中期报告 — 流水线仍在运行中  
> **测试范围**：3卷 × 2章/卷 = 6章 全流水线（foundation → drafting → revision → export）  
> **报告日期**：2026-07-10  
> **已运行时间**：约 62 分钟

---

## 概览

| BUG # | 标题 | 严重度 | 类别 |
|-------|------|--------|------|
| 1 | 双重阈值定义 — 配置优先级导致修改无效 | 🔴 高 | 配置/架构 |
| 2 | NVIDIA nemotron API 大 prompt 偶发失败 | 🟡 中 | API/网络 |
| 3 | state.json 步骤字段滞后 | 🟡 中 | 状态管理 |
| 4 | 运行中热修复不生效 | 🟢 低 | 设计限制 |

---

## BUG 1：双重阈值定义 — 配置优先级导致修改无效

### 严重度
🔴 **高**

### 位置
- 模块级常量：[`pipeline_orchestrator.py:62-63`](pipeline_orchestrator.py:62)
- 配置属性默认值：[`core/config.py:328`](core/config.py:328) 和 [`core/config.py:332`](core/config.py:332)

### 详情

`FOUNDATION_THRESHOLD` 和 `CHAPTER_THRESHOLD` 在两个独立位置定义，形成**双重定义**：

**定义 A — pipeline 模块级常量**（[`pipeline_orchestrator.py:62-63`](pipeline_orchestrator.py:62)）：
```python
FOUNDATION_THRESHOLD = 6.0
CHAPTER_THRESHOLD = 5.5
```

**定义 B — Config 类属性默认值**（[`core/config.py:327-328`](core/config.py:328)）：
```python
@property
def foundation_threshold(self) -> float:
    return self._data.get("foundation_threshold", 6.0)
```

**运行时决策逻辑**（[`pipeline_orchestrator.py:125`](pipeline_orchestrator.py:125)）：
```python
threshold = cfg.foundation_threshold if cfg.loaded else FOUNDATION_THRESHOLD
```

当 `config.json` 文件存在时，`cfg.loaded == True`，始终使用 `core/config.py` 的属性返回值，**完全忽略** pipeline 模块级常量。这意味着：

- 修改 [`pipeline_orchestrator.py`](pipeline_orchestrator.py) 中的常量 → ❌ 不生效
- 修改 [`core/config.py`](core/config.py) 中的属性默认值 → ✅ 生效
- 修改 `output/config.json` 中的 `foundation_threshold` 字段 → ✅ 生效

### 影响

测试时将 `FOUNDATION_THRESHOLD` 从 7.5 调低到 6.0（为加速测试流程），仅修改了 [`pipeline_orchestrator.py:62`](pipeline_orchestrator.py:62) 中的常量。由于 `config.json` 已存在且未包含 `foundation_threshold` 字段，运行时实际使用的是 [`core/config.py:328`](core/config.py:328) 的硬编码默认值 `6.0`，而非 pipeline 常量。

- 迭代 1 评分 **7.4**，刚好低于 7.5 阈值，判定未通过
- 触发了不必要的迭代 2（额外消耗 API 调用和运行时间）
- 误导调试：开发者修改了"看起来正确"的常量但未观察到预期行为

### 修复建议

**方案 A（推荐 — 单一真实来源）**：删除 pipeline 中的模块级常量，阈值统一由 `core/config.py` 管理。将 [`pipeline_orchestrator.py:125`](pipeline_orchestrator.py:125) 简化为：

```python
threshold = cfg.foundation_threshold  # cfg.load() 后始终可用
```

`core/config.py` 的属性默认值即为唯一真实来源。

**方案 B**：保留模块级常量作为**回退值**，但修改优先级逻辑，使其在 `config.json` 未显式设置该字段时使用模块级常量：

```python
threshold = cfg._data.get("foundation_threshold") or FOUNDATION_THRESHOLD
```

---

## BUG 2：NVIDIA nemotron API 大 prompt 偶发失败 — 重试无退避等待

### 严重度
🟡 **中**

### 位置
- 重试循环：[`core/api_client.py:165-293`](core/api_client.py:165)
- 超时异常处理：[`core/api_client.py:262-270`](core/api_client.py:262)

### 详情

使用 `nvidia/nemotron-3-super-120b-a12b` 模型时，大 prompt（>17,000 tokens）首次 API 调用有高概率在 ~16 秒处失败。该失败表现为 `httpx.TimeoutException`（非 HTTP 错误码），疑似 NVIDIA 服务端瞬时过载或连接重置。

**关键问题**：`httpx.TimeoutException` 异常分支（[`core/api_client.py:262-270`](core/api_client.py:262)）**缺少退避等待**：

```python
except httpx.TimeoutException:
    # ... 日志记录 ...
    last_error = RuntimeError(f"请求超时 ({attempt_timeout}s)")
    continue  # ← 无 time.sleep()，立即重试！
```

而其他异常分支均有退避：
- `httpx.RequestError`（[line 280](core/api_client.py:280)）：`time.sleep(15 * attempt)` ✅
- HTTP 4xx/5xx（[line 252](core/api_client.py:252)）：`time.sleep(15 * attempt)` ✅
- 通用 Exception（[line 292](core/api_client.py:292)）：`time.sleep(15 * attempt)` ✅

**叠加效应**：梯级递增超时（600→1200→1800→2400s）+ 无退避等待 = 单次调用最坏耗时 `600+1200+1800+2400 = 6000s`（100分钟）。

### 实际发生频率

| 步骤 | prompt 大小 | 重试次数 | 额外耗时 |
|------|------------|----------|----------|
| `gen_outline_volume` 调用 1 | 较小 | 1 次 | ~10s |
| `gen_outline` 调用 2 | 19,446 tokens | **3 次** | +438s（正常 ~90s → 实际 ~528s） |
| 评估采样 2 | 42,018 tokens | 1 次 | ~30s |

### 影响

- **流水线时间显著延长**：`gen_outline` 步骤从预期的 ~5 分钟延长到 ~13 分钟
- 无退避的重试可能加剧服务端压力，形成恶性循环
- 梯级超时机制在大 prompt 场景下被触发频率过高

### 修复建议

**方案 A（最小改动）**：为 `httpx.TimeoutException` 分支添加与其他异常一致的退避等待：

```python
except httpx.TimeoutException:
    # ... 日志 ...
    last_error = RuntimeError(f"请求超时 ({attempt_timeout}s)")
    time.sleep(15 * attempt)  # ← 添加退避
    continue
```

**方案 B（推荐）**：增加 jitter（随机抖动）避免惊群效应，并在首次失败后使用更长的初始等待：

```python
import random
wait = 15 * attempt + random.uniform(0, 10)
time.sleep(wait)
```

**方案 C**：对于大 prompt（>15,000 tokens），在首次调用前预等待 3-5 秒，给服务端连接建立更多时间。

---

## BUG 3：state.json 步骤字段滞后

### 严重度
🟡 **中**

### 位置
- 状态保存：[`core/state_manager.py:118-130`](core/state_manager.py:118)
- 步骤追踪更新逻辑：`pipeline_orchestrator.py` 中 `run_foundation()` 函数

### 详情

`foundation_step` 字段仅在**步骤完成后**才更新，导致：

1. **运行期间始终显示上一步名称**：例如实际正在执行 `gen_outline` 时，[`output/state.json`](output/state.json) 显示 `"foundation_step": "outline_volume"`（上一步）
2. **`foundation_score` 在评估完成前始终为 `0.0`**（或上一次迭代的分数）
3. **无 `in_progress` 字段**区分"正在执行"与"已完成"

当前 [`state.json`](output/state.json) 实际内容（流水线运行中快照）：
```json
{
  "phase": "foundation",
  "iteration": 2,
  "foundation_score": 7.4,
  "foundation_step": "outline_volume"
}
```
此快照拍摄时实际正在执行 `gen_outline`，但 `foundation_step` 仍为上一步 `outline_volume`。

### 影响

- **断点续传风险**：如果流水线在步骤中途崩溃，重启后会从 `foundation_step` 指示的"已完成步骤"之后恢复，可能跳过当前正在执行的步骤，导致该步骤**完全丢失**
- **外部监控盲区**：无法通过 [`state.json`](output/state.json) 精确知道当前正在执行哪个步骤
- **调试困难**：查看状态文件无法判断流水线是否卡住或正在正常运行

### 修复建议

**方案 A（推荐 — 双字段）**：增加 `in_progress_step` 字段，在步骤开始时写入，步骤完成后清除：

```python
# 步骤开始时
state["in_progress_step"] = "gen_outline"
save_state(state)

# ... 执行 gen_outline ...

# 步骤完成后
state["foundation_step"] = "gen_outline"
state["in_progress_step"] = None
save_state(state)
```

**方案 B**：在每个步骤**开始时**和**结束时**各写一次 [`state.json`](output/state.json)。开始时写入 `"foundation_step": "gen_outline"` 并附加 `_running` 后缀标记，完成后再写一次去掉后缀。

**方案 C**：引入步骤状态枚举：`pending → running → completed → failed`，替换当前单一的字符串字段。

---

## BUG 4：运行中热修复不生效

### 严重度
🟢 **低**（设计限制，非严格 BUG）

### 详情

Python 进程启动后将配置和代码加载到内存，磁盘上的代码修改不会影响运行中的进程。当测试中发现阈值、参数或逻辑需要调整时：

- ❌ 无法热修复 — 修改源码文件无效
- ❌ 无法通过信号触发重载
- ✅ 唯一方式：等待当前运行结束或手动 `Ctrl+C` 终止后重启

### 影响

- **调试效率降低**：发现配置问题后必须等待完整流水线周期结束才能验证修复
- **测试迭代周期长**：完整 foundation 阶段运行约 30-40 分钟，期间无法应用任何修复
- 与 BUG 1 叠加：发现阈值修改无效后，必须等待整个迭代完成才能重启验证

### 修复建议

**方案 A（推荐 — 配置文件热读取）**：对于阈值类配置，在每次迭代循环开始时重新从 `output/config.json` 读取，而非仅在启动时加载一次：

```python
# 每次迭代前
cfg.load()  # 重新读取 config.json
threshold = cfg.foundation_threshold  # 获取最新值
```

这样只需修改 `output/config.json` 即可在下一次迭代生效，无需重启进程。

**方案 B**：支持 `SIGHUP` 信号处理（Unix）/ `CTRL_BREAK_EVENT`（Windows），触发配置重载。

**方案 C**：在流水线关键检查点（如每次迭代开始、每章起草前）增加文件监控，检测到配置文件变更时自动重载。

---

## 测试环境信息

| 项目 | 值 |
|------|-----|
| **API 端点** | `https://integrate.api.nvidia.com/v1` |
| **模型** | `nvidia/nemotron-3-super-120b-a12b` |
| **测试配置** | 3卷 × 2章/卷 = 6章，每章 1500 字 |
| **故事名称** | 深炉永夜（科幻蒸汽朋克） |
| **已运行时间** | 约 62 分钟 |
| **当前阶段** | Foundation 迭代 2（foundation_step: outline → gen_outline 执行中） |
| **当前评分** | foundation_score: 7.4 / 阈值 7.5 |
| **操作系统** | Windows 10 |
| **Python** | `.python-version` 指定 |

---

## 附录：相关文件索引

| 文件 | 关联 BUG |
|------|----------|
| [`pipeline_orchestrator.py`](pipeline_orchestrator.py) | BUG 1（常量 + 优先级逻辑） |
| [`core/config.py`](core/config.py) | BUG 1（属性默认值） |
| [`core/api_client.py`](core/api_client.py) | BUG 2（重试/退避逻辑） |
| [`core/state_manager.py`](core/state_manager.py) | BUG 3（状态写入） |
| [`output/state.json`](output/state.json) | BUG 3（状态快照验证） |

---

> **备注**：本报告为中期快照，流水线仍在运行中。后续可能发现更多问题。最终报告将在全流水线完成后汇总所有发现。
