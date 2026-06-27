# novel_app.bat / novel_app.py 交互流程重构方案

## 目标

1. **"从头开始 / 继续上次"** 移到交互流程的**第一个问题**
2. **移除所有模型输入提示** —— 用户直接在 `.env` 中配置所有模型相关参数

---

## 一、当前流程 vs 目标流程

### 当前流程（`novel_app.py` `collect_input()` → `confirm_and_start()`）

```
┌─────────────────────────────────────────────────┐
│  步骤 1:  API 提供商 (NVIDIA/硅基/DeepSeek/自定义)   │
│  步骤 2:  API Key                                │
│  步骤 3:  模型名称                                │
│  步骤 3.5: 分阶段模型 P1/P2/P3 (可选)              │
│  步骤 4:  故事来源 (手动 / AI种子)                 │
│  步骤 5:  总章节数                                │
│  步骤 5.5: 分卷设置                               │
│  步骤 6:  生成模式 (从头开始 / 继续上次)  ← 太靠后   │
│  步骤 7:  判断模型 (可选)                          │
│  确认摘要 → 启动流水线                             │
└─────────────────────────────────────────────────┘
```

### 目标流程

```
┌─────────────────────────────────────────────────┐
│  ★ 步骤 1:  生成模式 (从头开始 / 继续上次)  ← 第一个 │
│      ├─ "从头开始" → 继续采集故事+章节配置           │
│      └─ "继续上次" → 检查 state.json 是否存在       │
│           ├─ 存在 → 读取已有配置，跳到确认摘要        │
│           └─ 不存在 → 提示并退回到"从头开始"         │
│                                                   │
│  ★ 步骤 2:  故事来源 (手动 / AI种子)               │
│  ★ 步骤 3:  总章节数                               │
│  ★ 步骤 4:  分卷设置                               │
│  确认摘要 → 启动流水线                              │
│                                                   │
│  (以下全部移除，改由 .env 读取)                     │
│  ✕ API 提供商                                     │
│  ✕ API Key                                       │
│  ✕ 模型名称                                       │
│  ✕ 分阶段模型 P1/P2/P3                             │
│  ✕ 判断模型                                       │
└─────────────────────────────────────────────────┘
```

---

## 二、具体修改任务

### 任务 1：`novel_app.py` — 交互流程重排

**涉及函数：** `collect_input()` / `_collect_remaining()` / `_collect_story()` / `main()`

#### 1.1 将"生成模式"移到 `collect_input()` 的最前面

修改 `collect_input()` 函数（[`novel_app.py:590`](novel_app.py:590)）：

```python
def collect_input() -> dict:
    _print_banner()

    # ============================================
    # ★ 步骤 1: 生成模式 —— 最先询问
    # ============================================
    _section("1. 生成模式：")
    print("   [1] 从头开始生成（完整流水线）")
    print("   [2] 继续上次生成（从 state.json 恢复）")
    print()
    mode_choice = input("   请选择 [1/2] (默认: 1): ").strip()
    mode = "from_scratch" if mode_choice != "2" else "resume"

    if mode == "resume":
        state_file = OUTPUT_DIR / "state.json"
        if not state_file.exists():
            print("   ⚠ 未找到 state.json，将从头开始生成")
            mode = "from_scratch"
        else:
            # 继续模式：直接加载已有配置，无需重新输入故事/章节/卷数
            cfg = config
            cfg.load()
            print(f"  ✅ 从 state.json 恢复 — 阶段: {cfg.get('phase', '?')}")
            print()
            return _build_config_from_existing(cfg, mode)

    print(f"   → 模式: 从头开始")
    print()

    # ============================================
    # ★ 步骤 2: .env 校验 —— 没有模型配不了
    # ============================================
    if not _env_has_model_config():
        print("  ❌ .env 中未配置模型。请在项目根目录的 .env 文件中设置：")
        print()
        print("     AUTONOVEL_API_BASE_URL=https://api.siliconflow.cn/v1")
        print("     AUTONOVEL_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx")
        print("     AUTONOVEL_MODEL_NAME=deepseek-ai/DeepSeek-V3")
        print()
        print("     可选分阶段模型：")
        print("     AUTONOVEL_P1_MODEL_NAME=...  # Phase 1 基础构建")
        print("     AUTONOVEL_P2_MODEL_NAME=...  # Phase 2 章节起草")
        print("     AUTONOVEL_P3_MODEL_NAME=...  # Phase 3 修订评估")
        print("     AUTONOVEL_JUDGE_MODEL_NAME=...  # 判断模型")
        print()
        sys.exit(1)

    cfg = config
    cfg.load()
    print(f"  ✅ .env 已配置:")
    print(f"     端点: {cfg.api_base_url}")
    print(f"     模型: {cfg.model_name}")
    # 展示独立 Phase 模型（如果有）
    for label, key in [("P1", "p1_model_name"), ("P2", "p2_model_name"), ("P3", "p3_model_name")]:
        val = cfg.get(key, "")
        if val:
            print(f"     {label}: {val}")
    judge_val = cfg.get("judge_model_name", "")
    if judge_val:
        print(f"     判断: {judge_val}")
    print()

    # ============================================
    # ★ 步骤 3: 故事来源
    # ============================================
    story = _collect_story()

    # ============================================
    # ★ 步骤 4: 总章节数
    # ============================================
    _section("4. 小说总章节数（建议 12–30，默认 24）：")
    ch_input = input("   > ").strip()
    total_chapters = int(ch_input) if ch_input.isdigit() and int(ch_input) > 0 else 24
    print(f"   → 总章节数: {total_chapters}")
    print()

    # ============================================
    # ★ 步骤 5: 分卷设置
    # ============================================
    _section("5. 分卷设置:")
    # ... (保持现有分卷逻辑不变)
    print()

    # 构建配置字典（模型配置全部来自 .env，不再采集）
    from datetime import datetime
    config_data = {
        "story_summary": story,
        "total_chapters": total_chapters,
        "total_volumes": total_volumes,
        "chapters_per_volume": chapters_per_volume,
        "mode": mode,
        "started_at": datetime.now().isoformat(),
    }

    return config_data
```

#### 1.2 新增 `_env_has_model_config()` 函数

替代现有 `_env_has_api_key()` 的更全面检测：

```python
def _env_has_model_config() -> bool:
    """检测 .env 是否至少配置了 API Base URL + API Key + Model Name。"""
    cfg = config
    cfg.load()
    return bool(cfg.api_base_url and cfg.api_key and cfg.model_name)
```

#### 1.3 新增 `_build_config_from_existing()` 函数

当用户选择"继续上次"时，直接从已有配置构建：

```python
def _build_config_from_existing(cfg, mode: str) -> dict:
    """从已有配置和 state.json 构建恢复模式的配置字典。"""
    from datetime import datetime
    return {
        "story_summary": cfg.story_summary,
        "total_chapters": cfg.get("total_chapters", 24),
        "total_volumes": cfg.get("total_volumes", 1),
        "chapters_per_volume": cfg.get("chapters_per_volume", 24),
        "mode": mode,
        "started_at": datetime.now().isoformat(),
    }
```

#### 1.4 简化 `confirm_and_start()` 摘要展示

移除摘要中的模型和提供商信息（这些来自 .env，用户自己配的，不需要确认），只保留：

- 故事梗概
- 总章节数
- 分卷信息
- 生成模式

#### 1.5 删除不再需要的函数

- `_collect_api_config()` — 完全移除
- `_collect_phase_configs()` — 完全移除
- 从 `_collect_remaining()` 移除判断模型采集部分
- 移除 `PRESET_PROVIDERS` 常量（或保留供参考）

---

### 任务 2：`novel_app.bat` — 可选的 .env 预检

在 `novel_app.bat`（[`novel_app.bat:1`](novel_app.bat:1)）中，启动 Python 前增加 .env 检查：

```batch
REM 检查 .env 是否存在且已配置
if not exist ".env" (
    echo ⚠ 未找到 .env 文件，正在创建模板 ...
    (
        echo # 中文长篇小说自动生成器 配置文件
        echo # 请填入你的 API 信息
        echo AUTONOVEL_API_BASE_URL=https://api.siliconflow.cn/v1
        echo AUTONOVEL_API_KEY=sk-your-api-key-here
        echo AUTONOVEL_MODEL_NAME=deepseek-ai/DeepSeek-V3
        echo # AUTONOVEL_API_INTERVAL_SECONDS=4
        echo # 可选: 分阶段模型
        echo # AUTONOVEL_P1_MODEL_NAME=
        echo # AUTONOVEL_P2_MODEL_NAME=
        echo # AUTONOVEL_P3_MODEL_NAME=
        echo # AUTONOVEL_JUDGE_MODEL_NAME=
    ) > .env
    echo ✅ 已创建 .env 模板，请编辑后重新运行。
    pause
    exit /b 0
)
```

---

### 任务 3：`novel_app.py` — `confirm_and_start()` 适配

当前 [`confirm_and_start()`](novel_app.py:629) 在保存配置时依赖 `config.save(config_data)`（内部调用 `_save_env`），但目标流程中**所有模型配置已在 .env 中**，新的 `config_data` 不应包含任何敏感键。

修改 `confirm_and_start()`：
- `config.save(config_data)` 只写入非敏感键（故事、章节、卷数、模式、时间戳）
- 不再写入任何 `_SECRET_KEYS` 中的字段

实际上 `config.save()` 的现有逻辑（[`core/config.py:116`](core/config.py:116)）本身就是：敏感键写 `.env`，非敏感键写 `config.json`。只要 `config_data` 中不含敏感键，就不会覆盖 `.env`。**逻辑上已兼容，无需修改 `core/config.py`。**

---

## 三、边界情况

| 场景 | 处理方式 |
|------|----------|
| .env 不存在 | novel_app.bat 创建模板并退出；用户编辑后重跑 |
| .env 存在但缺少模型 | novel_app.py 打印所需字段清单并退出 |
| 选择"继续上次"但 state.json 不存在 | 提示并降级为"从头开始" |
| 选择"继续上次"且 state.json 存在 | 跳过所有配置采集，直接确认摘要 |
| .env 有主模型但无分阶段模型 | 正常——所有阶段共用主模型（config 有回退链） |
| .env 有主模型但无判断模型 | 正常——评估共用写作模型 |

---

## 四、涉及文件清单

| 文件 | 修改类型 | 说明 |
|------|----------|------|
| [`novel_app.py`](novel_app.py) | **主要修改** | 重排流程、删除模型采集、新增函数 |
| [`novel_app.bat`](novel_app.bat) | 小幅修改 | 增加 .env 模板生成 |
| [`core/config.py`](core/config.py) | **无需修改** | 现有 save/load 逻辑已兼容 |

---

## 五、不改的部分

- `pipeline_orchestrator.py` — 不需要改动，它只接收 `mode` 参数
- `core/api_client.py` — 不需要改动
- `core/state_manager.py` — 不需要改动
- 所有 `foundation/` `drafting/` `revision/` `evaluation/` `export/` 模块 — 不需要改动
- `prompts/` 目录 — 不需要改动