# Step 1 实施方案：config + state 扩展

> 基于 [plan_D_layered_outline_incremental_canon.md](plans/plan_D_layered_outline_incremental_canon.md) Step 1
> 版本：v1.0
> 日期：2026-06-19
> 依赖：无

---

## 一、目标

为方案 D 的分层大纲 + Phase 分离模型配置提供底层基础设施：

1. `.env` 可配置 Phase 1/2/3 各自独立的 API Key / Base URL / Model Name
2. 代码侧通过便捷属性读取 Phase 配置，空值时自动回退到共用配置
3. state.json 新增卷级字段，支持卷感知流程编排
4. 完全向后兼容——老 `.env` 无需任何改动即可正常运行

---

## 二、涉及文件

| 文件 | 操作 | 说明 |
|---|---|---|
| [`core/config.py`](core/config.py:36) | 修改 | _SECRET_KEYS 追加 Phase 映射（已提交✅）+ 新增便捷属性 + 新增卷级字段 |
| [`core/state_manager.py`](core/state_manager.py:71) | 修改 | default_state() 新增 6 个卷级字段 |
| [`.env`](.env:1) | 修改 | 新增 Phase 分离配置注释模板段 |

---

## 三、详细修改

### 3.1 — 已完成 ✅

`core/config.py` 的 `_SECRET_KEYS` 已追加 10 个 Phase 分离映射键：

```python
"p1_api_key":           "AUTONOVEL_P1_API_KEY",
"p1_api_base_url":      "AUTONOVEL_P1_API_BASE_URL",
"p1_model_name":        "AUTONOVEL_P1_MODEL_NAME",
"p2_api_key":           "AUTONOVEL_P2_API_KEY",
"p2_api_base_url":      "AUTONOVEL_P2_API_BASE_URL",
"p2_model_name":        "AUTONOVEL_P2_MODEL_NAME",
"p2_ctx_api_key":       "AUTONOVEL_P2_CTX_API_KEY",
"p2_ctx_api_base_url":  "AUTONOVEL_P2_CTX_API_BASE_URL",
"p2_ctx_model_name":    "AUTONOVEL_P2_CTX_MODEL_NAME",
"p3_api_key":           "AUTONOVEL_P3_API_KEY",
"p3_api_base_url":      "AUTONOVEL_P3_API_BASE_URL",
"p3_model_name":        "AUTONOVEL_P3_MODEL_NAME",
```

### 3.2 — core/config.py 新增 Phase 便捷属性（带回退逻辑）

在 `Config` 类中 `# ——— 判断模型独立配置` 区域之后新增 12 个 property。

**回退逻辑**：

| Phase | 查询优先级 |
|---|---|
| P1 | `p1_*` → 共用 `*` |
| P2 | `p2_*` → 共用 `*` |
| P2_CTX | `p2_ctx_*` → `p2_*` → 共用 `*` |
| P3 | `p3_*` → 共用 `*` |

**新增属性清单**：

```python
# ============================================================
# Phase 分离模型配置（方案 D）
# ============================================================

# --- Phase 1: 基础构建 ---

@property
def p1_api_key(self) -> str:
    return self._data.get("p1_api_key") or self.api_key

@property
def p1_api_base_url(self) -> str:
    return self._data.get("p1_api_base_url") or self.api_base_url

@property
def p1_model_name(self) -> str:
    return self._data.get("p1_model_name") or self.model_name

# --- Phase 2: 章节起草 ---

@property
def p2_api_key(self) -> str:
    return self._data.get("p2_api_key") or self.api_key

@property
def p2_api_base_url(self) -> str:
    return self._data.get("p2_api_base_url") or self.api_base_url

@property
def p2_model_name(self) -> str:
    return self._data.get("p2_model_name") or self.model_name

# --- Phase 2 上下文模型（可选：canon 增量追加等大上下文任务）---

@property
def p2_ctx_api_key(self) -> str:
    return self._data.get("p2_ctx_api_key") or self._data.get("p2_api_key") or self.api_key

@property
def p2_ctx_api_base_url(self) -> str:
    return self._data.get("p2_ctx_api_base_url") or self._data.get("p2_api_base_url") or self.api_base_url

@property
def p2_ctx_model_name(self) -> str:
    return self._data.get("p2_ctx_model_name") or self._data.get("p2_model_name") or self.model_name

# --- Phase 3: 修订评估 ---

@property
def p3_api_key(self) -> str:
    return self._data.get("p3_api_key") or self.api_key

@property
def p3_api_base_url(self) -> str:
    return self._data.get("p3_api_base_url") or self.api_base_url

@property
def p3_model_name(self) -> str:
    return self._data.get("p3_model_name") or self.model_name
```

### 3.3 — core/config.py 新增卷级字段

在 `Config` 类 `total_chapters` 属性之后新增：

```python
# ============================================================
# 卷级配置（方案 D）
# ============================================================

@property
def total_volumes(self) -> int:
    """总卷数。0 表示不使用卷级结构，回退到原版扁平大纲。"""
    return self._data.get("total_volumes", 0)

@property
def chapters_per_volume(self) -> int:
    """每卷章节数。"""
    return self._data.get("chapters_per_volume", 0)
```

### 3.4 — core/state_manager.py default_state() 新增卷级字段

在 `default_state()` 函数返回字典末尾追加 6 个字段：

```python
# === 方案 D 新增 ===
"total_volumes": 0,
"chapters_per_volume": 0,
"current_volume": 1,
"volumes_outlined": 0,
"canon_entry_count": 0,
"canon_last_updated_ch": 0,
```

需要同时更新 `_GIT_TRACKED_GLOBS` 添加新的大纲文件名模式（供后续 Step 5 使用）：

```
# 不在此 Step 修改——Step 5 生成 outline_volume{N}.md 时再处理
```

### 3.5 — .env 新增 Phase 分离配置段

在 `.env` 文件末尾追加 4 个配置段，共 12 个变量，全部留空默认值。

```bash
# ============================================================
# Phase 1 — 基础构建（world/characters/outline/canon/voice）
# 建议: NVIDIA NIM 免费模型
# 留空则共用上述 AUTONOVEL_API_KEY / AUTONOVEL_API_BASE_URL / AUTONOVEL_MODEL_NAME
# ============================================================

AUTONOVEL_P1_API_KEY=
AUTONOVEL_P1_API_BASE_URL=
AUTONOVEL_P1_MODEL_NAME=

# ============================================================
# Phase 2 — 章节起草（需要大上下文窗口）
# 建议: 有 1M 上下文的模型（NVIDIA NIM 免费或付费均可）
# 留空则共用上述写作模型
# ============================================================

AUTONOVEL_P2_API_KEY=
AUTONOVEL_P2_API_BASE_URL=
AUTONOVEL_P2_MODEL_NAME=

# Phase 2 — 上下文模型（可选，用于 canon 增量追加等大上下文任务）
# 留空则共用 P2 模型；P2 也留空则回退到共用写作模型

AUTONOVEL_P2_CTX_API_KEY=
AUTONOVEL_P2_CTX_API_BASE_URL=
AUTONOVEL_P2_CTX_MODEL_NAME=

# ============================================================
# Phase 3 — 修订评估（对抗编辑、读者评审、全文评估）
# 建议: NVIDIA NIM 免费模型（评估任务不需要大上下文）
# 留空则共用上述写作模型
# ============================================================

AUTONOVEL_P3_API_KEY=
AUTONOVEL_P3_API_BASE_URL=
AUTONOVEL_P3_MODEL_NAME=
```

---

## 四、不需要修改的地方

| 模块 | 原因 |
|---|---|
| `Config._load_env()` | `_SECRET_KEYS` 循环已自动覆盖新键 |
| `Config._save_env()` | `set_key` 循环已自动覆盖新键 |
| `Config._save_config_json()` | 新键被 `_SECRET_KEYS` 拦截，自动写入 `.env` 而非 `config.json` |
| `Config.load()` | 无逻辑变更 |
| `state_manager.py` 除 `default_state()` 之外的函数 | `save_state`/`load_state` 通用 JSON 序列化，新字段自动兼容 |
| `novel_app.bat` | 仅启动 python，不变 |

---

## 五、回退兼容性验证清单

| 场景 | 预期结果 |
|---|---|
| 老 `.env` 仅 `AUTONOVEL_API_KEY` | `p1_api_key` 回退到共用 Key，正常运行 |
| `.env` 仅填 P1、留空 P2/P3 | P1 用独立配置，P2/P3 回退到共用配置 |
| `.env` 填 P2_CTX、留空 P2 | `p2_ctx_*` 回退到 P2 → 共用 |
| `state.json` 从旧版加载（无卷级字段） | `default_state()` 提供默认值，JSON 加载也自动缺省 |
| `total_volumes = 0` | 表示不使用卷级结构，后续 Step 7 pipeline 走回退路径 |

---

## 六、执行顺序

```
1. core/config.py  追加 12 个便捷属性 + 2 个卷级字段
2. core/state_manager.py  追加 6 个 default_state 字段
3. .env  追加 4 个 Phase 配置段
```

全部完成后运行 `python -c "from core.config import config; config.load(); print(config.p1_model_name)"` 验证回退逻辑。