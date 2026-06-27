# 【apply_diff 工具失效诊断】Bug 2 修复多次应用但文件内容不变的根因分析

> **目的**：诊断 `apply_diff` 工具为何多次报告成功但 `pipeline_orchestrator.py:438` 行内容不变
> **日期**：2026-06-25
> **类型**：无 API 调用（纯分析 + 验证）

---

## 1. 已知事实

| # | 事实 | 证据 |
|---|------|------|
| F1 | Bug 2 修复（添加 `threshold` 变量）已被 `apply_diff` 应用至少 **4 次** | 多次 `apply_diff` 调用均报告 `"modified"` |
| F2 | 每次应用后读取文件，`threshold` 行**不存在** | 4 次 `read_file` 确认 line 439 仍为 `max_tokens` |
| F3 | Bug 1 修复（`gen_brief.py` 的 `sys.exit()` → `raise`）**已被 `apply_diff` 成功写入** | `read_file` 确认 `gen_brief.py:749` 已变为 `raise FileNotFoundError` |
| F4 | Bug 2 修复在 `_verify_bug_fixes.py` 执行时**曾经生效过一次** | 验证脚本输出 `revision_cycle=1` |

### 矛盾点

**F3 vs F2**：同一个工具对 `gen_brief.py` 生效，对 `pipeline_orchestrator.py` 不生效。

**F4 vs F2**：修复曾经生效过一次，说明**修复可以被写入**，但后续运行又被覆盖了。

---

## 2. 两个假说

### 假说 A：`apply_diff` 的 SEARCH 块与文件实际内容不完全匹配

**证据**：`apply_diff` 使用精确字符串匹配。如果 SEARCH 块中的空白字符（空格/制表符/换行符）与实际文件不一致，匹配会失败。但工具仍然可能报告 "modified"（误报）。

**验证方法**：
1. 用 Python 直接读取 `pipeline_orchestrator.py:438-440` 的原始字节
2. 对比 SEARCH 块的精确字节序列
3. 确认是否存在不可见字符差异

### 假说 B：`pipeline_orchestrator.py` 被另一个进程/测试框架重新写入

**证据**：Bug 2 修复在验证脚本中曾生效（`revision_cycle=1`），但后续完整独立脚本运行时又遇到 `NameError: threshold`。可能中间有某个步骤（如测试框架的 backup/restore）覆盖了文件。

**已知的写入点**：
- `_verify_bug_fixes.py` 只写入 `config.json` 和 `state.json`，**不写入** `pipeline_orchestrator.py`
- `_run_5_7_5_standalone.py` 只调用 `write_config()`，**不写入** `pipeline_orchestrator.py`
- 测试框架的 `setUpClass`/`tearDownClass` 备份/恢复 `output/` 目录，**不操作** `pipeline_orchestrator.py`

**验证方法**：
1. 在 `pipeline_orchestrator.py` 写入 `threshold` 行后立即读取验证
2. 执行任何脚本前后对比文件 md5
3. 监控文件的最后修改时间

---

## 3. 诊断步骤

### Step 1：直接验证 SEARCH 块匹配

```python
# 读取文件的实际行
path = 'e:/2026代码文件夹/my novel/pipeline_orchestrator.py'
lines = open(path, 'r', encoding='utf-8').readlines()

# 打印 line 438-440 的 repr（显示不可见字符）
for i in [437, 438, 439]:
    print(f'line {i+1}: {repr(lines[i])}')
```

**通过标准**：确认 SEARCH 块的字符串是否与文件内容完全一致（包括缩进空格数、行尾换行符）。

### Step 2：绕过 `apply_diff` 直接写入

```python
# 直接用 Python string.replace 写入
path = 'e:/2026代码文件夹/my novel/pipeline_orchestrator.py'
content = open(path, 'r', encoding='utf-8').read()

old = 'plateau_delta = cfg.get("plateau_delta", PLATEAU_DELTA) if cfg.loaded else PLATEAU_DELTA\n    max_tokens'
new = 'plateau_delta = cfg.get("plateau_delta", PLATEAU_DELTA) if cfg.loaded else PLATEAU_DELTA\n    threshold = cfg.chapter_threshold if cfg.loaded else CHAPTER_THRESHOLD\n    max_tokens'

if old in content:
    content = content.replace(old, new)
    open(path, 'w', encoding='utf-8').write(content)
    print('replaced')
else:
    print('SEARCH string not found in file')
    # 定位差异
    idx = content.find('plateau_delta = cfg.get')
    if idx >= 0:
        print(repr(content[idx:idx+200]))
```

**通过标准**：写入后立即读取验证 `threshold` 行存在。

### Step 3：验证跨进程持久性

```python
# 写入 → 读取验证 → 启动新 Python 进程读取验证
```

**通过标准**：新进程读取到的文件包含 `threshold` 行。

---

## 4. 最快解决方案

**不依赖 `apply_diff`**，直接用 `execute_command` + Python `string.replace()` 写入修复：

```bash
python -c "
path = 'e:/2026代码文件夹/my novel/pipeline_orchestrator.py'
c = open(path, 'r', encoding='utf-8').read()
old = 'plateau_delta = cfg.get(\"plateau_delta\", PLATEAU_DELTA) if cfg.loaded else PLATEAU_DELTA\n    max_tokens'
new = 'plateau_delta = cfg.get(\"plateau_delta\", PLATEAU_DELTA) if cfg.loaded else PLATEAU_DELTA\n    threshold = cfg.chapter_threshold if cfg.loaded else CHAPTER_THRESHOLD\n    max_tokens'
c = c.replace(old, new)
open(path, 'w', encoding='utf-8').write(c)
# verify
lines = open(path).readlines()
print(lines[438].strip())
"
```

然后**立即**在同一终端进程中执行验证脚本（避免中间有其他进程覆盖）。

---

## 5. 通过标准

| 检查项 | 通过条件 |
|--------|---------|
| SEARCH 块匹配 | `repr()` 对比确认文件内容与 SEARCH 块完全一致或定位差异 |
| 直接写入成功 | 写入后立即读取验证 `threshold` 行存在 |
| 跨进程持久性 | 新 Python 进程读取到 `threshold` 行 |
| 验证脚本通过 | `_verify_bug_fixes.py` 执行后 `revision_cycle >= 1` |