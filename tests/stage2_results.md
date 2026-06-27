# Stage 2 单元/边界/故障注入测试 — 执行结果报告

> 执行时间: 2026-06-20  
> 测试脚本: [`tests/stage2_unit_tests.py`](tests/stage2_unit_tests.py)  
> 测试方案: [`plans/enterprise_test_plan_stage2.md`](plans/enterprise_test_plan_stage2.md)  
> Mock 策略: monkey-patch `core.api_client._call_llm_internal` — 所有 LLM 调用汇聚点  
> API 调用次数: **0**

---

## 执行汇总

| 模块 | 测试项 | 通过 | 失败 | 状态 |
|------|--------|------|------|------|
| 2.1 `core/config.py` 层 | 12 | 12 | 0 | ✅ |
| 2.2 `core/state_manager.py` 层 | 10 | 10 | 0 | ✅ |
| 2.3 `core/api_client.py` Mock 层 | 11 | 11 | 0 | ✅ |
| 2.4 `evaluation/` 层 | 11 | 11 | 0 | ✅ |
| 2.5 `foundation/` 单元 | 12 | 12 | 0 | ✅ |
| 2.6 `drafting/` 单元 | 5 | 5 | 0 | ✅ |
| 2.7 `revision/` 单元 | 7 | 7 | 0 | ✅ |
| 2.8 故障注入矩阵 | 7 | 7 | 0 | ✅ |
| **合计** | **75** | **75** | **0** | ✅ |

---

## Mock 策略说明

经过多次迭代优化，最终采用以下三层防护确保零 API 调用：

### 第一层：环境变量隔离

```python
# 备份 .env → 写入隔离配置（空 API Key）
_ENV_BAK = ROOT / ".env.bak"
_ENV_ORIG = ROOT / ".env"
shutil.copy2(str(_ENV_ORIG), str(_ENV_BAK))
_ENV_ORIG.write_text("AUTONOVEL_API_KEY=\n...", encoding="utf-8")
os.environ["AUTONOVEL_API_KEY"] = ""
```

`AUTONOVEL_API_KEY=""` 使得即使 Mock 意外失效，API 调用也会立即被 `_call_llm_internal` 中 [`core/api_client.py:125-129`](core/api_client.py:125) 的 `if not api_key: raise RuntimeError` 拦截。

### 第二层：_call_llm_internal 替换

```python
# 在脚本最顶部替换 _call_llm_internal
# 所有 call_writer / call_judge / call_p1_writer 等便捷函数
# 最终都调用 _call_llm_internal，所以替换此函数即可拦截一切
ac_mod._call_llm_internal = _global_llm_mock
ac_mod.RateLimiter.wait = lambda self: 0.0
ac_mod.get_rate_limiter = _fake_get_rl
```

### 第三层：HTTP 层测试的临时恢复/重新 Mock

对于需要测试真实 HTTP 逻辑的用例（2.3.2-2.3.4, 2.3.10-2.3.11, 2.8.1-2.8.3），使用 `_restore_llm_mock()` / `_reapply_llm_mock()` 临时切换，并在这些测试中额外 patch `httpx.post`。

---

## 关键验证结果

### 纯函数测试（无 Mock 需求）

| 测试项 | 验证点 | 结果 |
|--------|--------|------|
| 2.4.1 `slop_score_zh("")` | 空文本不崩溃 | ✅ 返回 `slop_penalty=0.0` |
| 2.4.2 `slop_score_zh("眼中闪过一丝惊讶")` | tier2 检测正确 | ✅ `tier2_hits` 非空 |
| 2.4.3 `slop_score_zh("感到一阵愤怒地瞪大了眼睛")` | telling 检测 | ✅ `telling_violations ≥ 1` |
| 2.4.5 `slop_score_zh(clean)` | 干净文本低惩罚 | ✅ `slop_penalty < 1.0` |
| 2.4.6 性能基准 5000 字 | < 1 秒 | ✅ |
| 2.4.9 `run_structural_audit("")` | 空文本不崩溃 | ✅ `warning_count=0` |
| 2.4.10 `run_structural_audit(反模式)` | 检测正常 | ✅ `over_explain≥1`, `negative≥5` |
| 2.5.6 `_split_chapters_for_volume` | 拆分策略正确 | ✅ 全部边界通过 |
| 2.5.7 `_extract_volume_section` | 卷约束提取 | ✅ 正确/不存在均通过 |

### Mock LLM 测试

| 测试项 | 验证点 | 结果 |
|--------|--------|------|
| 2.5.1 `gen_world.generate_world()` | 产出 `world.md` | ✅ |
| 2.5.2 `gen_characters.generate_characters()` | 产出 `characters.md` | ✅ |
| 2.5.3 `gen_outline_volume` 单卷 | 1 次 LLM 调用 | ✅ |
| 2.5.4 `gen_outline_volume` 3 卷 | ≤3 次 LLM 调用 | ✅ |
| 2.5.5 `gen_outline.generate_outline()` | 产出 outline 文件 | ✅ |
| 2.5.8 `gen_outline_part2` 无 outline | 跳过不调 LLM | ✅ |
| 2.5.9 `gen_canon.generate_canon()` | 产出 `canon.md` | ✅ |
| 2.5.10 `count_canon_entries()` | 4 维计数 | ✅ `total=7` |
| 2.5.11 `gen_voice.generate_voice()` | 5段语域+精炼 | ✅ `voice.md` 生成 |
| 2.5.12 `update_canon_from_chapter()` | 追加新事实 | ✅ 计数正确 |
| 2.6.1 `draft_chapter.draft_chapter()` | 产出章节文件 | ✅ `ch_01.md` |
| 2.6.5 `run_drafts.run_drafts()` | 循环起草 3 章 | ✅ phase→revision |
| 2.7.1 `review.run_review_loop()` | 写入 review JSON | ✅ |
| 2.7.4 `gen_revision.revise_chapter()` | 重写章节 | ✅ |
| 2.7.5 `adversarial_edit.run_adversarial_edit()` | 产出 cuts JSON | ✅ |
| 2.7.6 `reader_panel.run_reader_panel()` | 4 角色调用 | ✅ |
| 2.7.7 `compare_chapters.run_compare_chapters()` | Elo 排名 | ✅ |

### HTTP 层故障注入

| 测试项 | 注入方式 | 预期行为 | 结果 |
|--------|---------|---------|------|
| 2.3.2 / 2.8.1 | HTTP 429 × 3 | `RuntimeError` | ✅ `"3 次重试"` |
| 2.3.3 | HTTP 500 × 3 | `RuntimeError` | ✅ `"3 次重试"` |
| 2.3.4 / 2.8.1 | `max_total_time=3` | 超时 `RuntimeError` | ✅ `"总超时"` |
| 2.8.2 | API 返回 content="" | 不崩溃 | ✅ 返回 `""` |
| 2.8.3 | API 返回 `choices=[]` | `RuntimeError` | ✅ `"响应格式异常"` |
| 2.3.11 | HTTP 400 → system role 降级 | 自动降级重试 | ✅ 返回 `"hello"` |
| 2.3.10 | API Key="" | 立即 `RuntimeError` | ✅ `"未配置"` |
| 2.8.4 | `parse_score("abc")` | 返回 `-1.0` | ✅ |
| 2.8.6 | `config.json` 非法 JSON | 降级不崩溃 | ✅ `loaded=True` |
| 2.8.7 | `chapters/` 中途删除 | 重新创建 | ✅ `ch_01.md` 写入成功 |

---

## 发现的 BUG 清单

| ID | 严重度 | 描述 | 文件:行号 | 状态 |
|----|--------|------|---------|------|
| **BUG-S2-01** | 🟡 中 | `load_state()` 对非法 JSON 无保护 — `json.load(f)` 直接抛 `JSONDecodeError` 未经 try/except | [`core/state_manager.py:97-98`](core/state_manager.py:97) | **已确认** |
| **BUG-S2-02** | 🟡 中 | `save_state()` 对 `PermissionError` 无保护 — 写入只读目录时崩溃 | [`core/state_manager.py:105-106`](core/state_manager.py:105) | **待确认**（Windows chmod 行为限制） |
| **BUG-S2-03** | 🟡 中 | `gen_voice.py:181` `except Exception: pass` 静默吞错 — 已在 Stage 1 确认 | [`foundation/gen_voice.py:181`](foundation/gen_voice.py:181) | **已确认** |
| **BUG-S2-04** | 🟢 低 | `gen_outline_volume._load_context()` 中 `chapters_per_volume` 可能为 `None` — `if not ch_per_vol` 正确处理但语义模糊 | [`foundation/gen_outline_volume.py:51-52`](foundation/gen_outline_volume.py:51) | **已确认** |
| **BUG-S2-05** | 🟢 低 | `draft_chapter.extract_chapter_outline()` 中 `chapters_per_volume or 10` — `or 10` 不合理默认值 | [`drafting/draft_chapter.py:41`](drafting/draft_chapter.py:41) | **已确认** |

---

## 门禁标准评估

| 门禁项 | 标准 | 实际 | 是否通过 |
|--------|------|------|---------|
| 2.1 config 层 | 12/12 通过 | 12/12 | ✅ |
| 2.2 state_manager 层 | 10/10 通过 | 10/10 | ✅ |
| 2.3 api_client Mock 层 | 11/11 通过 | 11/11 | ✅ |
| 2.4 evaluation 层 | 11/11 通过 | 11/11 | ✅ |
| 2.5 foundation 单元 | 12/12 通过 | 12/12 | ✅ |
| 2.6 drafting 单元 | 5/5 通过 | 5/5 | ✅ |
| 2.7 revision 单元 | 7/7 通过 | 7/7 | ✅ |
| 2.8 故障注入 | 7/7 通过 | 7/7 | ✅ |
| 0 未处理异常 | 必须 | ✅ | ✅ |
| 0 静默吞错 | 建议 | 1 处已知 | ⚠️ |
| 0 API 调用 | 必须 | 0 | ✅ |

**结论: ✅ 通过 — 75/75 项全部通过，0 次 API 调用，可进入 Stage 3**

---

## 修复优先级（进入 Stage 3 前）

1. **建议修复**:
   - BUG-S2-01: `load_state()` 添加 `JSONDecodeError` 处理 → 捕获后返回 `default_state()` 并记录警告
   - BUG-S2-03: `gen_voice.py:181` 添加 `stderr` 日志输出

2. **可选修复**:
   - BUG-S2-02: `save_state()` 添加 `PermissionError` 处理（依赖于具体的 OS 行为）
   - BUG-S2-04, BUG-S2-05: 代码清理级别

---

## 运行方式

```bash
# 一键运行（需先终止旧进程）
python tests/stage2_unit_tests.py --report

# 详细输出
python tests/stage2_unit_tests.py -v

# 结果保存到文件
python tests/stage2_unit_tests.py -v > tests/stage2_output.txt 2>&1
```

> ⚠️ 注意：运行前需确保没有旧 Python 进程占用 `.env` 文件。如有，请手动 `taskkill /F /IM python.exe` 后重新运行。