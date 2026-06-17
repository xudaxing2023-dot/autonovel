# _phase5_test.py --live 死机修复方案

## 诊断结论

`--live` 模式下主线程被数百次同步 `httpx.post(timeout=600)` 完全占用，Windows 检测到消息泵无响应后弹出「窗口未响应」对话框。

**核心问题**：`--live` 的 3 个子测试（5.7.1/5.7.2/5.7.3）各自跑完整流水线，累计可达 400+ 次同步 API 调用，每次阻塞时间上限为 600s × 3 次重试 = 30 分钟。

## 修复清单

### P0-1: Foundation 子模块加 max_total_time=300

**文件**：`foundation/gen_world.py`, `foundation/gen_characters.py`, `foundation/gen_outline.py`, `foundation/gen_outline_part2.py`, `foundation/gen_canon.py`, `foundation/gen_voice.py`

**改动**：每个 `call_writer(prompt, system=..., max_tokens=...)` 增加 `max_total_time=300`。

**效果**：单次 API 调用从理论无限阻塞变为最多 5 分钟上限。

### P0-2: --live 测试配置注入 max_foundation_iters=3 + total_chapters=1

**文件**：`_phase5_test.py` 中 `test_5_7_live_boundary()` 及其 3 个子函数

**改动**：
- 所有 live 场景 config 增加 `"max_foundation_iters": 3`
- 所有 `total_chapters` 改为 1
- 5.7.2 和 5.7.3 场景简化（避免 resume 后重复跑 foundation）

**效果**：Foundation 从 20 轮最多降到 3 轮，drafting 从多章降到 1 章。

### P1: config.load() 加缓存守卫

**文件**：`core/config.py`

**改动**：`Config.load()` 开头加 `if self._loaded: return self._data`

**效果**：消除每次 `call_llm` 调用中的冗余文件 I/O。

## 合并效果

| 指标 | 修复前（最坏） | 修复后（最坏） |
|------|--------------|--------------|
| Foundation 迭代 | 20 轮 × 7 API = 140 次 | 3 轮 × 7 API = 21 次 |
| 单次 API 超时上限 | 无限制 (~30min/次) | 5 分钟/次 |
| 3 场景总 API 调用 | ~400+ | ~80 |
| 总阻塞时间上限 | 不可接受 | ~400 分钟（约 6.5h），仍有改进空间 |
| config.load() 冗余 I/O | 每 API 调用 1 次 | 仅首次 1 次 |

**注意**：修复后 --live 仍需要较长时间（主要受 RateLimiter 4s 间隔和 API 响应时间影响），但主线程不会再被单个调用无限占用。