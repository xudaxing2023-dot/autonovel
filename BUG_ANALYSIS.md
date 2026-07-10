# BUG 深度分析报告

> 生成时间：2026-07-10
> 分析范围：全流水线测试发现的 9 个 BUG
> 分析模式：源码追溯 + 真伪判断 + 根因定位 + 修复建议

---

## BUG 1: 双重阈值定义 — 配置优先级导致修改无效

### 现象描述

[`pipeline_orchestrator.py:62-63`](pipeline_orchestrator.py:62) 定义了模块级常量 `FOUNDATION_THRESHOLD = 7.5` / `CHAPTER_THRESHOLD = 7.0`，而 [`core/config.py:327-332`](core/config.py:327) 的 Config 属性默认值也是完全相同的 7.5/7.0。运行时通过三元表达式选择：

```python
# pipeline_orchestrator.py:125
threshold = cfg.foundation_threshold if cfg.loaded else FOUNDATION_THRESHOLD
```

config.json 中设置了 `foundation_threshold: 6.0` 和 `chapter_threshold: 5.5`（宽松测试值），但配置优先级链中存在认知歧义。

### 逻辑链追溯

1. **Config 加载**：[`core/config.py:69-81`](core/config.py:69) — `cfg.load()` 从 `.env` 和 `config.json` 加载数据；若 `_loaded=True` 则直接返回缓存，不重新读取磁盘。
2. **阈值属性**：[`core/config.py:327-332`](core/config.py:327) — `foundation_threshold` 属性从 `_data` 字典读取，默认值 7.5；`chapter_threshold` 默认值 7.0。
3. **阈值选择**：[`pipeline_orchestrator.py:125`](pipeline_orchestrator.py:125) — 若 `cfg.loaded=True`（config.json 存在且已加载），使用 Config 属性值；否则使用模块常量。
4. **实际行为**：由于 config.json 存在，`cfg.loaded` 始终为 `True`，模块常量永不被使用。用户在 config.json 中修改的 `foundation_threshold: 6.0` 会被正确读取。
5. **章节阈值**：[`pipeline_orchestrator.py:369`](pipeline_orchestrator.py:369) — 同样的三元模式，config.json 的 `chapter_threshold: 5.5` 被正确使用。
6. **slop 阈值**：[`pipeline_orchestrator.py:404`](pipeline_orchestrator.py:404) — slop_penalty_threshold 也从 Config 读取，默认值 3.0，config.json 设为 6.0（测试放宽）。

### 真伪判断

**不是真正的 BUG，而是设计上的认知陷阱。**

- Config 加载机制工作正常：config.json 中的阈值（6.0/5.5/6.0）被正确读取和使用。
- 模块级常量（7.5/7.0）仅在 Config 未加载时充当 fallback，这是合理的防御性编程。
- **真正的风险点**：Config 加载后缓存（`_loaded=True`），运行时修改 config.json 不会生效（见 BUG 4）。
- 两个默认值（模块常量 vs Config 属性默认值）必须保持同步，否则会产生静默行为差异：当 config.json 缺少某字段时，Config 属性返回 `_data.get("foundation_threshold", 7.5)` = 7.5，与模块常量一致。当前它们恰好相同，但如果未来有人只改一处，就会产生歧义。

### 根因定位

- **文件**: [`pipeline_orchestrator.py:62-63`](pipeline_orchestrator.py:62) + [`core/config.py:327-332`](core/config.py:327)
- **问题**: 阈值定义存在两处（模块常量 + Config 属性默认值），虽当前值一致，但缺乏单一事实来源（Single Source of Truth），存在未来不一致的风险。

### 修复建议

**方案 A（推荐）：统一到 Config 单一来源**
删除 `pipeline_orchestrator.py` 中的模块常量，所有阈值统一从 Config 读取。当 Config 未加载时使用 Config 属性默认值（即 `_data.get("key", default)` 中的 default）。

```python
# pipeline_orchestrator.py 修改
# 删除 FOUNDATION_THRESHOLD / CHAPTER_THRESHOLD / MAX_FOUNDATION_ITERS 等模块常量
# 改为：
cfg = config
cfg.load()
threshold = cfg.foundation_threshold  # 属性默认值 7.5 作为 fallback
```

影响范围：仅 `pipeline_orchestrator.py` 内部；需同步删除 [`pipeline_orchestrator.py:62-68`](pipeline_orchestrator.py:62) 的所有重复常量定义。

**方案 B：模块常量作为权威来源，Config 从模块常量读取默认值**
Config 属性改为 `return self._data.get("foundation_threshold", FOUNDATION_THRESHOLD)`，但需要在 config.py 中引用 pipeline_orchestrator 的常量（循环导入风险）。

**方案 C：最小改动 — 添加注释警告**
在模块常量处添加注释 "注意：修改此值需同步修改 core/config.py 中对应属性的默认值"。

### 优先级建议

**可延后** — 当前行为正确，但技术债务需记录。建议随下一次重构一并处理。

---

## BUG 2: API 超时异常分支缺少退避等待

### 现象描述

[`core/api_client.py:262-270`](core/api_client.py:262) 中 `httpx.TimeoutException` 异常分支缺少 `time.sleep()` 退避，而同一函数中其他异常分支（`httpx.RequestError` 行 280、通用 HTTP 错误 行 252/259、通用 Exception 行 292）均有 `time.sleep(15 * attempt)`。

### 逻辑链追溯

1. **重试循环**：[`core/api_client.py:165`](core/api_client.py:165) — `for attempt in range(1, retries + 1)` 控制重试。
2. **梯级超时**：[`core/api_client.py:183`](core/api_client.py:183) — `attempt_timeout = timeout * attempt`，即 600→1200→1800→2400s。
3. **异常处理分支对比**：
   - **TimeoutException** (行 262-270)：记录日志、打印消息、`last_error = ...`、`continue` — **没有 `time.sleep()`**。
   - **RequestError** (行 272-281)：记录日志、打印消息、`last_error = e`、`time.sleep(15 * attempt)`、`continue` ✓
   - **HTTP 4xx/5xx** (行 233-260)：均有 `time.sleep(15 * attempt)` ✓
   - **通用 Exception** (行 283-293)：`time.sleep(15 * attempt)` ✓

4. **叠加效应分析**：
   - 超时已经等了 `attempt_timeout` 秒（如第 1 次 600s），如果立即重试，下一个 `attempt_timeout` 会增至 1200s（梯级递增），但这只是请求超时上限，不代表实际等待时间。
   - 缺少退避意味着超时后立刻发起下一次请求，如果服务端正处于过载状态，会加剧问题。
   - 其他异常（如网络错误）等待 `15 * attempt` 秒后再重试，是合理的指数退避。

### 真伪判断

**是真 BUG。** 这是一个明确的代码遗漏：`httpx.TimeoutException` 分支缺少 `time.sleep(15 * attempt)` 退避等待。对比同一函数内其他所有异常分支均有的退避行为，此处明显是编写时遗漏。

### 根因定位

- **文件**: [`core/api_client.py:262-270`](core/api_client.py:262)
- **具体问题**: `except httpx.TimeoutException:` 分支（行 262-270）中第 269 行 `continue` 之前缺少 `time.sleep(15 * attempt)`。

### 修复建议

**方案 A（推荐）：添加退避等待，与其他异常分支对齐**

```python
# core/api_client.py:262-270 修改为：
except httpx.TimeoutException:
    latency_s = round(time.time() - t_call_start, 1)
    _debug_log("API_RETRY", f"超时 ({attempt_timeout}s)",
               data={"attempt": attempt, "model": model,
                     "latency_s": latency_s, "max_retries": retries,
                     "error": f"Timeout ({attempt_timeout}s)"})
    _stderr_print(f"  [API] 调用失败，重试 {attempt}/{retries}{total_info} — 超时 ({attempt_timeout}s)")
    last_error = RuntimeError(f"请求超时 ({attempt_timeout}s)")
    if attempt < retries:
        time.sleep(15 * attempt)  # ← 添加退避
    continue
```

影响范围：仅 `_call_llm_internal()` 函数内的超时重试行为；使超时后的重试间隔与其他异常一致，降低服务端压力。

### 优先级建议

**紧急修复** — 代码遗漏，影响 API 调用稳定性。超时后立即重试可能加剧 API 服务端过载，导致连续超时直至耗尽所有重试。

---

## BUG 3: state.json 步骤字段滞后

### 现象描述

`foundation_step` 字段仅在步骤完成后更新。流水线运行期间读取 [`output/state.json`](output/state.json) 看到的始终是上一步名称。最终 state.json 显示 `foundation_step: "voice"` 但全流水线已完成。无 `in_progress` 字段区分"正在执行"与"已完成"。

### 逻辑链追溯

1. **默认状态**：[`core/state_manager.py:97`](core/state_manager.py:97) — `"foundation_step": None`。
2. **步骤执行**：[`pipeline_orchestrator.py:172-303`](pipeline_orchestrator.py:172) — 每个步骤（world → characters → outline_volume → outline → outline_part2 → canon → voice）执行完成后才设置 `state["foundation_step"]`。
3. **赋值时序**：
   - 步骤开始：无状态写入，`foundation_step` 仍是上一步的名称
   - 步骤完成：`state["foundation_step"] = "world"`（行 183）；`save_state(state)`（行 185）
   - 步骤运行中：state.json 显示上一步名称
4. **断点续传逻辑**：[`pipeline_orchestrator.py:172`](pipeline_orchestrator.py:172) — `if _use_resume and completed_step and _STEP_ORDER.index("world") <= _STEP_ORDER.index(completed_step):` 跳过已完成步骤。
   - 如果某步骤中途崩溃（如 LLM 调用超时），`foundation_step` 仍是上一步名称
   - Restart 后会从"已完成的上一步之后"继续，**正确跳过了上一步，但会重新执行崩溃的步骤**
   - 实际上这是正确的行为：崩溃的步骤未标记完成，restart 后会重新执行

5. **跨迭代行为**：[`pipeline_orchestrator.py:138-141`](pipeline_orchestrator.py:138) — 新迭代开始时重置 `foundation_step = None`，确保同迭代断点续传仅在迭代 1（from_scratch 模式）生效（行 169）。

6. **state.json 最终状态**（实际观察）：
   ```json
   {
     "phase": "complete",
     "foundation_step": "voice",
     ...
   }
   ```
   `phase: "complete"` 但 `foundation_step: "voice"`（上一步），因为 Phase 切换时重置了 phase 但未清理 foundation_step。

### 真伪判断

**部分是设计意图，部分是 BUG。**
- `foundation_step` 记录"最后完成的步骤"是设计意图——用于同迭代断点续传。
- **真正的 BUG**：缺少 `in_progress_step` 字段区分"正在执行"与"已完成"。无法从 state.json 判断当前是否在执行某个步骤。
- **次要问题**：Phase 完成后 `foundation_step` 未清理，保留了过时信息。

### 根因定位

- **文件**: [`pipeline_orchestrator.py:172-303`](pipeline_orchestrator.py:172) 中所有 `state["foundation_step"] = ...` 赋值点
- **文件**: [`core/state_manager.py:97`](core/state_manager.py:97) — 默认状态中无 `in_progress_step` 字段
- **问题**: 状态模型缺少"正在执行"的语义表达

### 修复建议

**方案 A（推荐）：增加 in_progress_step 字段**

在步骤开始时写入 `state["in_progress_step"] = "world"`，步骤完成时写入 `state["foundation_step"] = "world"` 并清除 `state["in_progress_step"] = None`。

```python
# pipeline_orchestrator.py 步骤执行前添加：
state["in_progress_step"] = "world"
save_state(state)

# 步骤完成后：
state["foundation_step"] = "world"
state["in_progress_step"] = None
save_state(state)
```

影响范围：需修改所有 7 个 Foundation 步骤的执行块（约 7 处）；`default_state()` 需增加 `"in_progress_step": None`。

**方案 B：Phase 切换时清理 foundation_step**

```python
# pipeline_orchestrator.py:347 之后添加：
state["foundation_step"] = None  # 清理已完成 Phase 的步骤标记
```

### 优先级建议

**建议修复** — 对调试和监控有价值，但不影响核心功能。断点续传逻辑本身是正确的。

---

## BUG 4: 运行中热修复不生效

### 现象描述

Python 进程启动后内存中的代码/配置不变，修改磁盘文件不会影响运行中进程。运行中修改 config.json 的阈值参数不会生效。

### 逻辑链追溯

1. **Config 加载缓存**：[`core/config.py:71`](core/config.py:71) — `if self._loaded: return self._data`，一旦加载完成，后续 `cfg.load()` 调用直接返回缓存。
2. **调用模式**：[`pipeline_orchestrator.py:123`](pipeline_orchestrator.py:123) — `cfg.load()` 在 `run_foundation()` 开始时调用一次；[`pipeline_orchestrator.py:368`](pipeline_orchestrator.py:368) — `cfg.load()` 在 `run_drafting()` 开始时调用一次。
3. **阈值读取**：在每个函数开始时（如 `run_foundation` 行 125、`run_drafting` 行 369）通过 `cfg.foundation_threshold if cfg.loaded else ...` 读取。但这些值被读取到局部变量后，在函数执行期间不再更新。
4. **迭代内行为**：`run_foundation()` 的主体是一个 `for i in range(...)` 循环，阈值 `threshold` 在循环外读取一次（行 125），循环内不变。`run_drafting()` 类似（行 369 在 `for ch in range(...)` 循环外）。

### 真伪判断

**这是设计限制，不是 BUG。** Python 进程内修改磁盘文件不会自动同步到内存，这是所有运行时系统的固有特性。但可以通过设计改进来缓解：

- 当前设计：配置在函数入口处一次性读取
- 改进方向：在关键决策点（如每次迭代开始、每章开始）重新读取配置

### 根因定位

- **文件**: [`core/config.py:71`](core/config.py:71) — `_loaded` 标志阻止重新读取
- **文件**: [`pipeline_orchestrator.py:125`](pipeline_orchestrator.py:125) 和 369 — 阈值在循环外一次性读取
- **问题**: 缺乏周期性配置刷新机制

### 修复建议

**方案 A：添加 Config.reload() 方法，在关键决策点调用**

```python
# core/config.py
def reload(self) -> dict:
    """强制重新加载配置（跳过缓存）。"""
    self._loaded = False
    return self.load()
```

然后在每章开始前（`run_drafting` 循环内）调用 `cfg.reload()`。

影响范围：需在 `run_drafting()` 和 `run_foundation()` 的循环体内添加 `cfg.reload()` 调用。

**方案 B：每次属性访问都读取 _data（无缓存）**
不推荐 — 会影响性能且无法解决"代码热修复"问题。

**方案 C：添加命令行信号处理（SIGHUP/SIGUSR1）触发重载**
过度设计，不推荐。

### 优先级建议

**可延后** — 这是 Python 运行时的固有限制。当前配置在每 Phase 开始时重新加载已足够。如需运行中调整，建议先停止流水线、修改配置、再 resume。

---

## BUG 5: 章节评估 JSON 解析失败导致管道崩溃（🔴 最严重）

### 现象描述

第 4 章首次评估时，LLM 返回的 JSON 无法被 [`_try_json_extract()`](core/state_manager.py:410) 的三种策略解析到 `overall_score` 字段，[`parse_score()`](core/state_manager.py:360) 抛出 `ValueError`（行 403-407），导致全管道崩溃。

### 逻辑链追溯

#### 1. 调用链路

```
pipeline_orchestrator.py:398    eval_result = evaluate_chapter(ch)
pipeline_orchestrator.py:399    score = parse_score(eval_result, "overall_score")
                                     ↓
state_manager.py:373            json_score = _try_json_extract(stdout, key)
                                     ↓
state_manager.py:410-447        _try_json_extract() — 三种策略
                                     ↓ 全部返回 None
state_manager.py:403-407        raise ValueError(...)  ← 💥 崩溃点
```

#### 2. evaluate_chapter() 的返回逻辑

[`evaluation/evaluate.py:470-553`](evaluation/evaluate.py:470)中 `evaluate_chapter()`:
- 调用 LLM 获取 `result`（字符串，LLM 的原始 JSON 响应）
- 使用**自己的** `_parse_json_response()`（行 36-100，evaluate.py 内）解析 JSON 并保存 eval log
- **返回 `result`（原始 LLM stdout）**，而不是解析后的 dict

#### 3. 两套独立的 JSON 解析器

| 函数 | 位置 | 用途 | 策略 |
|------|------|------|------|
| `_parse_json_response()` | [`evaluate.py:36-100`](evaluation/evaluate.py:36) | 保存 eval log 时解析 | markdown 剥离 → 首个 `{`/`[` → 花括号深度匹配 |
| `_try_json_extract()` | [`state_manager.py:410-447`](core/state_manager.py:410) | `parse_score()` 提取分数 | direct_loads → fenced_block → brace_extract |

这两个函数策略不完全相同，存在一个成功、另一个失败的可能。但更关键的问题是：**即使 JSON 解析成功，`overall_score` 字段也可能不在其中。**

#### 4. 实际证据分析

查看 [`chapter_04_20260710_202753.json`](output/eval_logs/chapter_04_20260710_202753.json)（第 4 章最早评估日志），`raw_output` 字段包含完整的 JSON，内有 9 个维度评分（prose_quality, pacing, character_voice, dialogue, scene_craft, plants_seeded, canon_compliance, lore_integration, engagement）。但 `raw_output` 字符串中**没有顶层 `overall_score` 字段**。

查看 [`chapter_04_20260710_210158.json`](output/eval_logs/chapter_04_20260710_210158.json)（后续评估），该文件中 `raw_judge_score: 6`、`slop_penalty_applied: 5.38`、`overall_score: 0.62`（调整后）。这说明 LLM **有时**会在响应中包含 `overall_score`，有时不包含。

**关键发现**：eval_judge_prompts.py 构建的 prompt 要求 LLM 输出包含 `overall_score` 的 JSON，但 LLM 可能不遵守此格式。当 LLM 遗漏 `overall_score` 时：
1. `_parse_json_response()`（evaluate.py）成功解析 JSON dict，保存 eval log
2. `_try_json_extract()`（state_manager.py）三种策略都成功解析 JSON dict，但 `key in data` 检查失败（dict 中无 `overall_score`），返回 `None`
3. `parse_score()` 的 Markdown fallback 策略也找不到匹配
4. **抛出 `ValueError`，管道崩溃**

#### 5. 崩溃的致命性

[`pipeline_orchestrator.py:397-399`](pipeline_orchestrator.py:397) 中：
```python
eval_result = evaluate_chapter(ch)   # 不会崩溃（总是返回字符串）
score = parse_score(eval_result, "overall_score")  # 💥 可能崩溃
```

这两行**不在 try/except 保护范围内**。`draft_chapter()` 的异常被捕获（行 382-386），但 `evaluate_chapter()` + `parse_score()` 没有保护。一旦 `parse_score()` 抛出 `ValueError`，整个 `run_drafting()` 函数崩溃，所有已完成的章节工作可能丢失（取决于 git 提交状态）。

### 真伪判断

**这是真 BUG，且是最严重的管道崩溃风险。**

- ✅ 真实可复现：LLM 不保证遵守 JSON schema，遗漏字段是常见行为
- ✅ 崩溃路径确认：`parse_score()` 无异常保护，`ValueError` 直接传播到顶层
- ✅ 影响严重：单次 LLM 格式偏差即可导致数小时的管道运行报废
- ✅ 证据确凿：eval log 中存在缺少 `overall_score` 字段的 LLM 响应实例

### 根因定位

- **主因**: [`pipeline_orchestrator.py:398-399`](pipeline_orchestrator.py:398) — `evaluate_chapter()` + `parse_score()` 调用无异常保护
- **次因**: [`core/state_manager.py:403-407`](core/state_manager.py:403) — `parse_score()` 对所有失败情况一律抛出 `ValueError`，无降级策略
- **根本原因**: [eval_judge_prompts.py](prompts/eval_judge_prompts.py) 的 prompt 无法 100% 约束 LLM 输出格式

### 修复建议

**方案 A（推荐，防御性）：在 pipeline 侧添加 try/except 包裹**

```python
# pipeline_orchestrator.py:397-399 修改为：
eval_result = evaluate_chapter(ch)
try:
    score = parse_score(eval_result, "overall_score")
except ValueError as e:
    step(f"⚠ 评分解析失败: {e}，使用默认评分 0.0 并重试")
    score = 0.0
    # 可选：保存原始输出到 debug 文件
```

影响范围：仅 `pipeline_orchestrator.py` 行 399 附近；需同时在修订阶段的 `evaluate_chapter_stable()` 调用（行 811, 823）处添加类似保护。

**方案 B（根因修复）：parse_score() 添加降级策略**

```python
# core/state_manager.py:402 之后，raise ValueError 之前：
# 策略 4: 尝试从已解析的 JSON 计算综合分数
try:
    data = json.loads(stdout.strip())
    dims = [v for k, v in data.items() if isinstance(v, dict) and "score" in v]
    if dims:
        avg = sum(d["score"] for d in dims) / len(dims)
        return round(avg, 1)
except Exception:
    pass
# 策略 5: 返回 0.0 作为 sentinel 值而非崩溃
return 0.0  # sentinel，调用方自行处理
```

影响范围：需修改 `parse_score()` 的契约——返回 0.0 表示解析失败（但 0.0 也可能是有效评分）。更好的做法是返回 `Optional[float]`，调用方检查 `None`。

**方案 C（双重防御）：方案 A + 方案 B 同时实施**

在 `parse_score()` 中添加降级策略（避免崩溃），同时在 pipeline 侧添加 try/except（双重保险）。

### 优先级建议

**紧急修复** 🔴 — 这是 9 个 BUG 中影响最严重的。单次 LLM 输出格式偏差即可导致数小时的管道运行完全报废。建议实施方案 C（双重防御）。

---

## BUG 6: canon_last_updated_ch 字段始终为 0

### 现象描述

[`output/state.json`](output/state.json) 中 `canon_entry_count: 644`（有大量正典数据）但 `canon_last_updated_ch: 0`（未记录最后更新章节）。

### 逻辑链追溯

1. **正典更新入口**：[`pipeline_orchestrator.py:517-528`](pipeline_orchestrator.py:517) — 在质量门禁全部通过后才执行 `update_canon_from_chapter()`。
2. **正典更新条件**：
   ```python
   new_count = update_canon_from_chapter(ch, ch_text)
   if new_count > 0:
       state["canon_entry_count"] = state.get("canon_entry_count", 0) + new_count
       state["canon_last_updated_ch"] = ch  # ← 行 527
       save_state(state)
   ```
3. **canon_entry_count=644 的来源**：[`pipeline_orchestrator.py:273-278`](pipeline_orchestrator.py:273)和行 321：Foundation 阶段结束时通过 `count_canon_entries()` 统计现有 canon.md 的条目数并写入 state。这 644 条是在 Foundation 阶段由 `gen_canon.py` 一次性生成的，**不是通过 `update_canon_from_chapter()` 逐章追加的**。
4. **质量门禁路径分析**：[`pipeline_orchestrator.py:430-531`](pipeline_orchestrator.py:430):
   - 行 434-511：文风指纹检查 + 结构反模式审计
   - 行 498-504：`voice_severe and anti_severe` → `drafted = False; continue`，**跳过正典更新**
   - 行 507-511：`anti_severe` → `drafted = False; continue`，**跳过正典更新**
   - 行 513-530：所有门禁通过 → 执行正典更新
5. **关键发现**：如果质量门禁触发重写（`drafted = False; continue`），正典更新块（行 513-530）被跳过。如果所有章节都因门禁不断重写直到 `max_attempts` 耗尽，最终走行 541-555 的"尽力而为"路径——该路径**也没有调用 `update_canon_from_chapter()`**。
6. **另一种可能**：`update_canon_from_chapter()` 返回 0（行 67-69），因为 LLM 判断"无新增事实"。这会导致 `if new_count > 0:` 条件不满足，`canon_last_updated_ch` 不被更新。

### 真伪判断

**是真 BUG，但根因可能有两种。**

- **根因 A（更可能）**：Foundation 阶段生成了 644 条 canon 条目，但 Drafting 阶段的质量门禁阻止了 `update_canon_from_chapter()` 的正常执行。所有章节的正典更新都被跳过，因此 `canon_last_updated_ch` 保持默认值 0。
- **根因 B（次要可能）**：`update_canon_from_chapter()` 每次都返回 0（LLM 判断无新增事实），`if new_count > 0:` 条件永不满足。

### 根因定位

- **主因**: [`pipeline_orchestrator.py:498-511`](pipeline_orchestrator.py:498) — 质量门禁触发重写时跳过正典更新；行 541-555 — "尽力而为"路径也未执行正典更新
- **次因**: [`pipeline_orchestrator.py:520`](pipeline_orchestrator.py:520) — `if new_count > 0:` 门槛过于严格
- **文件**: [`foundation/update_canon.py:67-69`](foundation/update_canon.py:67) — 可能返回 0

### 修复建议

**方案 A（推荐）："尽力而为"路径也执行正典更新**

```python
# pipeline_orchestrator.py:541-555 的 "尽力而为" 路径中添加：
if not drafted:
    step(f"⚠ 警告: 第 {ch}/{total} 章全部 {max_attempts} 次尝试失败，保留最后结果继续")
    # ... 现有代码 ...
    
    # ★ 添加：即使质量不达标，也尝试提取正典（降低后续章节偏离风险）
    try:
        from foundation.update_canon import update_canon_from_chapter
        ch_text = ch_file.read_text(encoding="utf-8-sig")
        new_count = update_canon_from_chapter(ch, ch_text)
        if new_count > 0:
            state["canon_entry_count"] = state.get("canon_entry_count", 0) + new_count
            state["canon_last_updated_ch"] = ch
            save_state(state)
    except Exception as e:
        step(f"正典更新跳过: {e}")
```

**方案 B：追踪最后一次成功更新的章节（而非最后一次尝试）**

无论 `new_count` 是否为 0，都记录 `canon_last_attempted_ch`（用于调试）。保留 `canon_last_updated_ch` 仅在有新增时更新。

### 优先级建议

**建议修复** — 不影响核心功能（正典数据本身在 Foundation 阶段已完整生成），但影响状态追踪的准确性，对调试和监控不利。

---

## BUG 7: 文风指纹持续告警 — "无对话" + "破折号密度过高"

### 现象描述

第 4、5、6 章均有 `dialogue_ratio=0`（无对话）和破折号密度 19-29/千字（正常≤5）的告警。门禁逻辑在 ≥3 项警告时标记为 `voice_severe`。

### 逻辑链追溯

#### 1. 对话检测逻辑

[`voice_fingerprint.py:286-288`](voice_fingerprint.py:286):
```python
dialogue_matches = re.findall(r'["""][^"""]*["""]|「[^」]*」', text)
dialogue_chars = sum(len(m.replace(" ", "")) for m in dialogue_matches)
dialogue_ratio = dialogue_chars / char_count if char_count > 0 else 0
```

对话检测使用正则 `["""][^"""]*["""]|「[^」]*」`，匹配英文双引号或中文直角引号包裹的内容。**未检测以下中文引号格式**：
- `"..."`（中文弯引号，U+201C/U+201D，区别于 `"..."` U+0022）
- `'...'`（中文弯单引号）
- 无引号的自由间接引语

#### 2. 破折号检测逻辑

[`voice_fingerprint.py:291-292`](voice_fingerprint.py:291):
```python
em_dashes = text.count('—') + text.count('--')
em_per_1k = (em_dashes / char_count) * 1000 if char_count > 0 else 0
```

破折号密度阈值设为 5/千字，这在中文小说中可能过于严格。许多文学性强的中文小说使用大量破折号表示停顿、转折、插入语。

#### 3. 门禁逻辑

[`pipeline_orchestrator.py:447-465`](pipeline_orchestrator.py:447):
```python
warnings = []
if dialogue_ratio == 0:        warnings.append("无对话")
if dialogue_ratio > 0.6:       warnings.append(f"对话过多 ({dialogue_ratio:.1%})")
if em_dash_per_1k > 5:         warnings.append(f"破折号密度过高 ({em_dash_per_1k:.1f}/千字)")
if abstract_per_1k > 30:       warnings.append(f"抽象名词密度过高 ({abstract_per_1k:.1f}/千字)")
if transition_per_1k > 15:     warnings.append(f"过渡词密度过高 ({transition_per_1k:.1f}/千字)")

if len(warnings) >= 3:         voice_severe = True  # 行 465
```

#### 4. 为什么只有第 4-6 章出现

第 4-6 章的小说内容可能是"地下探险/核心揭露"场景，这些场景：
- 以主角独白和内心活动为主，天然对话较少
- 场景张力强，作者/模型倾向使用破折号增加节奏感和断裂感
- 相比之下，第 1-3 章可能有更多角色互动场景

这是**模型生成内容特征**的反映，不一定是检测算法的误报。

### 真伪判断

**混合问题：部分检测算法缺陷 + 部分模型生成质量问题。**

- **对话检测是真缺陷**：正则表达式不覆盖所有中文引号格式。如果模型使用了 `"..."`（弯引号）格式，对话检测会漏掉。但 `dialogue_ratio=0` 意味着确实没有匹配到任何引号包裹的对话——这可能是因为章节确实对话很少。
- **破折号阈值是真问题**：5/千字的阈值在中文创意写作中过于严格。破折号是中文文学的有效表达工具。
- **门禁阈值（≥3 项）总体合理**：但 `dialogue_ratio == 0` 的检测过于二元（完全无对话），应改为 `dialogue_ratio < 0.05`（极少对话）。

### 根因定位

- **文件**: [`voice_fingerprint.py:286`](voice_fingerprint.py:286) — 对话检测正则不覆盖中文弯引号 `"..."` 和 `'...'`
- **文件**: [`voice_fingerprint.py:292`](voice_fingerprint.py:292) — 破折号密度 5/千字阈值可能偏低
- **文件**: [`pipeline_orchestrator.py:453`](pipeline_orchestrator.py:453) — `dialogue_ratio == 0` 过于严格

### 修复建议

**方案 A（推荐）：改进对话检测 + 调整阈值**

```python
# voice_fingerprint.py:286 — 扩展引号匹配
dialogue_matches = re.findall(
    r'["""][^"""]*["""]|「[^」]*」|'
    r'\u201c[^\u201d]*\u201d|'   # 中文左弯引号 "..." 
    r'\u2018[^\u2019]*\u2019',    # 中文左弯单引号 '...'
    text
)
```

```python
# pipeline_orchestrator.py:291 — 调整破折号阈值
if em_dash_per_1k > 10:   # 从 5 提升到 10
    warnings.append(...)
```

```python
# pipeline_orchestrator.py:453 — 使用范围阈值
if dialogue_ratio < 0.02:  # 从 == 0 改为 < 0.02
    warnings.append("对话极少")
```

**方案 B：将对话检测改为 LLM 辅助（高成本）**
调用 LLM 识别对话段落，而非纯正则匹配。成本过高，不推荐。

### 优先级建议

**建议修复** — 改善检测准确性，减少误报，避免因对话/破折号特征误判导致不必要的重写。

---

## BUG 8: slop_penalty 偏高

### 现象描述

第 3 章 slop_penalty=3.95，第 4 章 slop_penalty=5.18。默认阈值 3.0 时会被拒绝。测试用阈值 6.0 时通过。

### 逻辑链追溯

#### 1. slop_penalty 计算

[`evaluation/evaluate.py:327-342`](evaluation/evaluate.py:327):
```python
penalty = 0.0
penalty += sum(c for _, c in tier1_hits) * 0.5    # Tier1: 每个 0.5
penalty += sum(c for _, c in tier2_hits) * 0.2    # Tier2: 每个 0.2
if em_density > 3:
    penalty += (em_density - 3) * 0.5              # 破折号惩罚
if dialog_ratio > 0.6:
    penalty += (dialog_ratio - 0.6) * 5            # 对话标签惩罚
penalty += min(fiction_tell_count * 0.3, 2.0)      # AI 套话（上限 2.0）
penalty += min(structural_tic_count * 0.5, 2.0)    # 修辞公式（上限 2.0）
penalty += min(telling_count * 0.2, 1.5)           # 说教情感（上限 1.5）
if transition_ratio > 0.3:
    penalty += min(transition_ratio * 2, 1.0)      # 过渡词（上限 1.0）
if sentence_cv < 0.3:
    penalty += 1.0                                  # 句子均匀化
penalty = min(10.0, penalty)
```

#### 2. 破折号贡献分析

第 4 章的 `em_dash_density` 在 eval log 中显示为 10.15（202753 文件）和 13.76（210158 文件）。破折号惩罚 = `(13.76 - 3) * 0.5 = 5.38`，仅此一项就超出了默认阈值 3.0。

**破折号惩罚是 slop_penalty 偏高的最大贡献者。**

#### 3. 破折号密度计算

[`evaluation/evaluate.py:277-278`](evaluation/evaluate.py:277):
```python
em_count = len(EM_DASH_PATTERN.findall(text))  # EM_DASH_PATTERN = r'——'
em_density = (em_count / char_count) * 1000 if char_count else 0
```

只匹配 `——`（U+2014 U+2014 双连字符），不匹配 `—`（单个 em dash）。中文破折号通常是 `——`，检测规则正确。

#### 4. 阈值差异

- 默认阈值 3.0：[`core/config.py:364`](core/config.py:364) — `slop_penalty_threshold` 默认 3.0
- config.json 设为 6.0（测试放宽）

### 真伪判断

**检测算法正确，阈值设计偏保守。破折号惩罚权重过大是主要问题。**

- slop_penalty 计算逻辑正确，各惩罚项都有上限保护
- **破折号惩罚无上限**（公式 `(em_density - 3) * 0.5`），在高破折号密度章节中贡献过大
- 默认阈值 3.0 较为保守，适合最终质检；测试阶段使用 6.0 合理

### 根因定位

- **文件**: [`evaluation/evaluate.py:330-331`](evaluation/evaluate.py:330) — 破折号惩罚无上限，在高密度场景贡献过大
- **文件**: [`core/config.py:364`](core/config.py:364) — 默认阈值 3.0 偏低
- **关联**: 破折号密度高可能来自模型风格特征（BUG 7），而非真正的 AI 套话

### 修复建议

**方案 A（推荐）：为破折号惩罚添加上限**

```python
# evaluation/evaluate.py:330-331
if em_density > 3:
    penalty += min((em_density - 3) * 0.5, 3.0)  # 添加上限 3.0
```

影响范围：仅影响破折号密度较高（>9/千字）的章节评分。

**方案 B：提高默认阈值**

```python
# core/config.py:363
def slop_penalty_threshold(self) -> float:
    return self._data.get("slop_penalty_threshold", 5.0)  # 从 3.0 改为 5.0
```

**方案 C：区分"AI 套话"和"风格特征"的惩罚**
破折号不应归入 AI 套话检测，应单独评估（在文风指纹中已有破折号密度检查）。从 slop_penalty 中移除破折号惩罚，完全依赖文风指纹（voice_fingerprint.py）的破折号检测。

### 优先级建议

**建议修复** — slop_penalty 的破折号惩罚与文风指纹的破折号检测重叠，导致双重惩罚。建议方案 C（移除重叠检测）或方案 A（添加上限）。

---

## BUG 9: 修订过程偶发评分倒退

### 现象描述

修订循环中出现两次评分倒退：Ch2: 7.0→6.5（循环1），Ch6: 7.0→6.0（循环2），均被 `git_reset_hard` 回退。

### 逻辑链追溯

#### 1. 修订流程

[`pipeline_orchestrator.py:806-845`](pipeline_orchestrator.py:806):
```python
for idx, item in enumerate(consensus_items):
    ch_num = item["chapter"]
    # ...
    pre_score = evaluate_chapter_stable(ch_num)    # 修订前评分（3次中位数）
    # ... 生成 brief ...
    revise_chapter(ch_num, brief_file, ...)         # 执行修订
    post_score = evaluate_chapter_stable(ch_num)    # 修订后评分（3次中位数）
    
    if post_score >= pre_score:
        git_add_commit(...)   # 接受修订
    else:
        git_reset_hard("HEAD")  # 回退修订
```

#### 2. 评分稳定性措施

[`core/state_manager.py:454-495`](core/state_manager.py:454)中 `evaluate_chapter_stable()`:
```python
def evaluate_chapter_stable(ch_num, retries=3, samples=3):
    scores = []
    for _ in range(samples):
        result = _eval(ch_num, ...)
        s = parse_score(result, "overall_score")
        if s >= 0:
            scores.append(s)
    return statistics.median(scores) if scores else 0.0
```

使用 3 次评估取中位数，已做了降噪处理。

#### 3. 修订 prompt 构建

[`revision/gen_revision.py:19-66`](revision/gen_revision.py:19):
```python
def revise_chapter(ch_num, brief_file, retries=5, max_total_time=None):
    brief_text = brief_path.read_text(...)
    voice = voice_path.read_text(...)
    world = world_path.read_text(...)
    chars = chars_path.read_text(...)
    old_text = old_path.read_text(...)
    prev_tail = prev_path.read_text(...)
    next_head = next_path.read_text(...)
    outline_text = ...  # 从 outline.md 提取本章大纲
    
    prompt = build_revision_prompt(ch_num, brief_text, voice_text=voice,
        world_text=world, characters_text=chars,
        old_chapter_text=old_text,
        prev_chapter_tail=prev_tail,
        next_chapter_head=next_head,
        outline_text=outline_text)
    
    result = call_writer(prompt, system=REVISION_SYSTEM_PROMPT, retries=5, ...)
    old_path.write_text(result, encoding="utf-8")
```

修订使用 `call_writer`（writing 模型），没有调用评估裁判模型验证修订质量后再写入。修订结果直接覆盖原文件。

#### 4. git_reset_hard 回退机制

[`core/state_manager.py`](core/state_manager.py) 中的 `git_reset_hard("HEAD")`:
- 将工作区重置到当前 HEAD commit
- 撤销 `revise_chapter()` 写入的文件变更
- **前提**：修订前有 git commit（行 833 在评分提升时才 commit）

如果修订前没有单独的 commit（即修订前的章节状态 = HEAD），`git_reset_hard("HEAD")` 能正确回退到修订前状态。✅

#### 5. 评分倒退的根因分析

评分倒退的三种可能原因：

| 原因 | 可能性 | 说明 |
|------|--------|------|
| LLM 评分随机波动 | **高** | 即使 3 次中位数，LLM 评分仍有 0.5-1.0 分的自然波动。6.5 vs 7.0 的差异在噪声范围内 |
| 修订质量不稳定 | **中** | 修订模型（writer model）可能在改写时引入新问题（如破坏上下文衔接） |
| 修订方向错误 | **低** | brief 基于读者评审团共识，但共识可能指向错误方向 |

### 真伪判断

**主要是 LLM 评分固有波动，非代码 BUG。回退机制工作正常。**

- `evaluate_chapter_stable()` 已使用 3 次中位数降噪，但 0.5 分的波动无法完全消除
- `git_reset_hard("HEAD")` 回退逻辑正确
- 回退后章节恢复到修订前状态，无数据丢失
- **潜在改进点**：评分比较过于严格（`post_score >= pre_score`，无容忍区间），0.1 分的微小下降也会触发回退

### 根因定位

- **文件**: [`pipeline_orchestrator.py:832`](pipeline_orchestrator.py:832) — `if post_score >= pre_score:` 无容忍区间
- **次因**: LLM 评估的固有随机性，难以完全消除
- **文件**: [`revision/gen_revision.py:68-69`](revision/gen_revision.py:68) — 修订结果直接写入文件，无中间验证

### 修复建议

**方案 A（推荐）：添加评分比较容忍区间**

```python
# pipeline_orchestrator.py:832
TOLERANCE = 0.3  # 容忍 LLM 评分波动
if post_score >= pre_score - TOLERANCE:
    # 接受修订（评分基本持平或提升）
    commit_hash = git_add_commit(...)
else:
    # 显著倒退才回退
    step(f"修订使评分显著下降 ({post_score} < {pre_score} - {TOLERANCE})，回退")
    git_reset_hard("HEAD")
```

影响范围：减少因 LLM 评分噪声导致的误回退。容忍区间 0.3 与 `PLATEAU_DELTA`（行 68）一致。

**方案 B：增加评估样本数**

```python
# state_manager.py:458 — evaluate_chapter_stable() 的 samples 参数
samples: int = 5  # 从 3 增加到 5
```

影响范围：每次评估多 2 次 LLM 调用，增加时间和成本，但进一步降噪。

### 优先级建议

**建议修复** — 当前机制正确（回退保护数据），但过于敏感。0.1-0.5 分的波动在 LLM 评估中是正常的，不应触发回退。

---

## 总结与优先级排序

| 优先级 | BUG | 标题 | 类型 | 影响 |
|--------|-----|------|------|------|
| 🔴 紧急 | 5 | JSON 解析崩溃 | 真 BUG | 管道崩溃，数据丢失风险 |
| 🟠 紧急 | 2 | API 超时无退避 | 真 BUG | API 调用稳定性 |
| 🟡 建议 | 6 | canon_last_updated_ch=0 | 真 BUG | 状态追踪不准确 |
| 🟡 建议 | 8 | slop_penalty 偏高 | 阈值设计 | 评分准确性 |
| 🟡 建议 | 9 | 修订评分倒退 | 设计改进 | 误回退 |
| 🟢 可延后 | 1 | 双重阈值定义 | 技术债务 | 代码可维护性 |
| 🟢 可延后 | 3 | state.json 步骤滞后 | 部分设计意图 | 调试便利性 |
| 🟢 可延后 | 4 | 热修复不生效 | 设计限制 | 运维便利性 |
| 🔵 混合 | 7 | 文风指纹告警 | 检测算法 + 生成质量 | 误报 |

**建议修复顺序**：BUG 5 → BUG 2 → BUG 6 → BUG 8 → BUG 9 → BUG 7 → BUG 1/3/4
