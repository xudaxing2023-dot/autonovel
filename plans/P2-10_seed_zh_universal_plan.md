# P2-10: 种子概念生成器中文化 & 全类型通用化 — 详细实施方案

## 1. 现状分析

### 1.1 当前 `seed.py` 的问题

| # | 问题 | 严重度 | 所在位置 |
|---|------|--------|---------|
| A1 | 直接调用 Anthropic Messages API，未使用 `core/api_client.py` | 🔴 致命 | [`seed.py:27-56`](../seed.py:27) |
| A2 | System prompt 固定为「fantasy novelist」，引用全是奇幻作家（Tolkien, Le Guin, Rothfuss 等） | 🔴 致命 | [`seed.py:39-46`](../seed.py:39) |
| A3 | `GENERATE_PROMPT` 包含 MAGIC/COST 字段 + Sanderson 第二定律引用 | 🔴 严重 | [`seed.py:72-73`](../seed.py:72) |
| A4 | 多样性要求含「非人类中心世界」「非欧洲风格设定」等奇幻专属约束 | 🟡 中等 | [`seed.py:83-87`](../seed.py:83) |
| A5 | 避免列表含「天选之人预言」「黑暗领主」「中世纪欧洲+精灵矮人」「魔法学院」 | 🟡 中等 | [`seed.py:89-95`](../seed.py:89) |
| A6 | `RIFF_PROMPT` 同样硬编码「fantasy novel」+ MAGIC/COST | 🟡 中等 | [`seed.py:97-115`](../seed.py:97) |
| A7 | 输出提示仍引用 WORKFLOW.md Step 2（英文原版流程） | 🟢 轻微 | [`seed.py:142`](../seed.py:140) |
| A8 | 无类型参数，无法指定生成特定类型（科幻/悬疑/言情等）的小说概念 | 🟡 中等 | 整体 |

### 1.2 当前 seed 在流水线中的角色

```
┌──────────────────────────────────────────────────────────────────┐
│                    两条入口路径                                   │
├──────────────────────────────────────────────────────────────────┤
│  路径A: novel_app.py                                             │
│    用户手写梗概 → config.json / story_summary.txt                │
│    → pipeline_orchestrator.py (mode=from_scratch)                │
│                                                                  │
│  路径B: seed.py (当前)                                           │
│    AI 生成10个概念 → 用户挑选 → 保存到 seed.txt                  │
│    → run_pipeline.py --from-scratch (检查 seed.txt 存在)         │
│    → foundation/gen_*.py 读取 cfg.story_summary 或 seed.txt      │
└──────────────────────────────────────────────────────────────────┘
```

**关键发现**：`novel_app.py` 已经通过 `config.story_summary` 提供梗概，`foundation/` 下所有生成器均从 `cfg.story_summary` 读取。`seed.txt` 仅被 `run_pipeline.py --from-scratch` 检查存在性和 `gen_canon.py`/`gen_outline.py`（根目录旧版）读取。新版 `foundation/gen_*.py` 已全部走 `config.story_summary`。

### 1.3 与 `autonovel_zh_refactor_plan.md` 的冲突

原重构方案（[`plans/autonovel_zh_refactor_plan.md:97`](../plans/autonovel_zh_refactor_plan.md:97)）建议「seed.py → **移除**，改为由用户手工输入故事梗概」。但 P2-10 要求保留并增强 seed.py。**本方案按 P2-10 需求执行：保留 seed.py，中文化并通用化。**

---

## 2. 设计方案

### 2.1 核心原则

1. **类型无关 (Genre-Agnostic)**：Prompt 不含任何特定类型假设（不预设奇幻/科幻/言情等）
2. **类型自适应 (Genre-Adaptive)**：可选 `--genre` 参数聚焦特定类型，无参数时生成跨类型多样化概念
3. **中文原生**：所有 prompt 和输出均为简体中文
4. **API 统一**：通过 `core/api_client.call_writer()` 调用，支持所有已配置的 API 提供商
5. **向下兼容**：保留 `--count` 和 `--riff` 参数，输出仍建议保存到 `seed.txt`

### 2.2 类型分类体系

不预设具体类型列表，而是在 prompt 中要求 LLM 覆盖以下大类：

| 大类 | 说明 | 示例亚类型 |
|------|------|-----------|
| 现实题材 | 基于现实世界、无超自然元素 | 都市、乡土、职场、校园、家庭伦理 |
| 历史题材 | 基于真实历史时期 | 历史演义、历史架空、年代文 |
| 悬疑/惊悚 | 以悬念、解谜为核心驱动 | 推理、犯罪、心理惊悚、谍战 |
| 科幻 | 以科学/技术假说为核心 | 硬科幻、赛博朋克、太空歌剧、末世 |
| 奇幻/玄幻 | 以超自然规则体系为核心 | 东方玄幻、西方奇幻、都市异能 |
| 言情/情感 | 以人物关系与情感弧线为核心 | 纯爱、虐恋、破镜重圆、先婚后爱 |
| 武侠/仙侠 | 以中国传统武学/修仙体系为核心 | 传统武侠、修仙、修真 |

### 2.3 架构变更

```
变更前:
seed.py
  ├── 直接 import httpx
  ├── 硬编码 ANTHROPIC_API_KEY / API_BASE_URL / WRITER_MODEL
  ├── call_writer() 内部函数 (Anthropic Messages API)
  ├── GENERATE_PROMPT (英文, 奇幻)
  └── RIFF_PROMPT (英文, 奇幻)

变更后:
seed.py
  ├── from core.api_client import call_writer    ← 统一 API 客户端
  ├── from core.config import config              ← 统一配置
  ├── GENERATE_PROMPT (中文, 类型无关)
  ├── RIFF_PROMPT (中文, 类型无关)
  └── 新增 --genre 参数
```

---

## 3. 实施步骤

### 3.1 步骤概览

```
S1: API 层迁移
S2: 系统提示重写
S3: GENERATE_PROMPT 重写
S4: RIFF_PROMPT 重写
S5: 输出与交互中文化
S6: 添加 --genre 参数
S7: CLI 入口整合测试
```

### 3.2 详细变更

---

#### S1: API 层迁移 — `seed.py`

**变更前** (L1-56):
```python
#!/usr/bin/env python3
"""
seed.py -- Generate fantasy novel seed concepts.
...
"""
import argparse, json, os, sys
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")

WRITER_MODEL = os.environ.get("AUTONOVEL_WRITER_MODEL", "claude-sonnet-4-6-20250217")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
API_BASE_URL = os.environ.get("AUTONOVEL_API_BASE_URL", "https://api.anthropic.com")
ANTHROPIC_BETA = "context-1m-2025-08-07"

def call_writer(prompt, max_tokens=4000):
    import httpx
    headers = { ... }  # Anthropic Messages API
    ...
```

**变更后**:
```python
#!/usr/bin/env python3
"""
seed.py — 中文小说种子概念生成器

支持所有长篇小说类型（玄幻/科幻/悬疑/历史/言情/武侠/都市/现实…）。
通过 LLM 批量生成高创意度的小说核心概念，帮助作者快速获得灵感起点。

用法:
  uv run python seed.py                        # 跨类型生成 10 个概念
  uv run python seed.py --count=5              # 生成 5 个概念
  uv run python seed.py --genre 科幻           # 只生成科幻概念
  uv run python seed.py --riff "一个关于记忆可以作为货币流通的世界"  # 围绕已有想法展开
"""

import argparse
import sys
from pathlib import Path

from core.api_client import call_writer
from core.config import config

BASE_DIR = Path(__file__).parent
```

**关键变更**：
- 删除所有 `dotenv`/`httpx`/`os.environ` 导入
- 删除 `call_writer()` 内部函数
- 导入 [`core/api_client.py`](../core/api_client.py) 的 `call_writer`
- 导入 [`core/config.py`](../core/config.py) 的 `config`

---

#### S2: 系统提示重写 — `seed.py` system prompt

**变更前** (L39-46):
```python
"system": (
    "You are a fantasy novelist with deep knowledge of the genre's "
    "best works -- Tolkien, Le Guin, Rothfuss, Wolfe, Jemisin, Peake, "
    "Susanna Clarke, Andrew Peterson, Sofia Samatar. You generate "
    "novel concepts that are SPECIFIC, SURPRISING, and STRUCTURALLY "
    "SOUND. You never propose generic medieval Europe + elves. Each "
    "concept should make a reader think 'I've never seen THAT before.'"
),
```

**变更后**:
```python
SEED_SYSTEM_PROMPT = """你是一位跨越多个文学类型的小说概念设计师。你深谙各种类型的叙事传统——
从金庸的武侠世界到刘慈欣的科幻想象，从东野圭吾的悬疑架构到张爱玲的情感洞察，
从马伯庸的历史演绎到猫腻的玄幻构筑。

你生成的小说概念具备以下特质：
— 具体 (SPECIFIC)：给出可感知的细节，而非空洞的类型标签
— 意外 (SURPRISING)：颠覆类型的常见套路，制造认知冲击
— 结构自洽 (STRUCTURALLY SOUND)：核心设定、冲突、主题三者形成闭环
— 高张力 (HIGH-STAKES)：个人困境与世界/社会/系统层面的力量产生不可调和的矛盾

你绝对不会生成：
— 纯套路堆砌（穿越重生打脸、霸总甜宠、退婚逆袭 等纯爽文模板）
— 缺乏真正道德模糊感的善恶二元对立
— 依赖巧合而非角色选择驱动的剧情
— "灵感枯竭时随便想的"那种模糊概念

每个概念都应让读者产生"我从未见过这样的故事——但我立刻就想读"的感受。"""

# 注意: 移除 system prompt 中对特定作者/类型的过度列举，
# 使用「跨越多个文学类型」替代「fantasy novelist」
```

**关键变更**：
- 奇幻 novelist → 跨类型概念设计师
- 英文奇幻作者 → 中文各类型代表作者
- 反例：中世纪欧洲+精灵 → 中文网文套路（穿越重生打脸、霸总甜宠等）
- 保留核心理念：SPECIFIC / SURPRISING / STRUCTURALLY SOUND

---

#### S3: GENERATE_PROMPT 重写 — `seed.py` `GENERATE_PROMPT`

**变更前** (L59-95):
```python
GENERATE_PROMPT = """Generate {count} fantasy novel seed concepts. ...

For EACH concept, provide:

NUMBER. TITLE ...
HOOK: ...
WORLD: What makes this world different? ...
MAGIC/COST: What is the core speculative element and what does it COST? ...
TENSION: ...
THEME: ...
WHY IT'S NOT GENERIC: ...

Aim for DIVERSITY across the {count} concepts:
  - At least one with a non-human-centric world
  - At least one that's more literary/quiet than epic
  - At least one with an unusual narrative structure idea
  - At least one set outside the typical European-inspired setting
  - Mix of tones: dark, warm, weird, melancholy, whimsical

DO NOT generate:
  - Chosen one prophecies ...
  - Dark lord / ultimate evil ...
  - Medieval Europe + elves/dwarves/orcs
  - "Academy" or "school for magic" settings
  - Love triangles as the central plot
"""
```

**变更后（核心结构）**:
```python
GENERATE_PROMPT = """请生成 {count} 个中文长篇小说种子概念。每个概念应是一个完整的小说核心构想，
足以支撑一部 {total_chapters} 章左右的长篇小说。

{genre_constraint}

对每个概念，提供以下字段：

【编号】. 【暂定书名】（有感染力、不落俗套的工作标题）

【一句话钩子】
让读者立刻产生阅读欲望的一句话。必须具体且意外，
避免"在一个……的世界里"这类万能句式。
给出一个具体的、可感知的画面或悖论。

【世界/背景】
这部小说的世界有什么不同？
— 如果是现实/历史题材：具体的时间、地点、社会环境有什么独特之处？
— 如果是科幻/奇幻/玄幻题材：核心设定是什么？这个世界因它而产生了怎样的
  感官上可触摸的变化？（盐碱地、倒悬的塔、会迁徙的城市、能记住一切的海…）
— 如果是悬疑/惊悚题材：这个世界的规则裂缝在哪里？正常表象下隐藏着什么？

【核心机制与代价】
这部小说最核心的叙事引擎是什么？
— 如果是超自然题材：核心设定元素的规则和限制是什么？
  限制比能力更重要——使用它必须付出什么代价？这个代价如何制造困境？
— 如果是现实题材：推动故事的核心机制是什么？（阶级壁垒？信息不对称？
  时间压力？道德困境？）这个机制的约束力如何制造不可逃避的张力？
— 如果是悬疑题材：隐藏真相的机制是什么？为什么真相如此难以触及？

【核心冲突】
必须同时具备两个层面并在彼此之间产生张力：
— 个人层面：一个特定角色面临的、具体的、迫切的困境
— 系统层面：影响整个世界观/社会/群体的更大力量
— 两者的关系：为什么解决个人困境必然会触及系统层面的问题？
  （反之亦然）

【主题问题】
这个故事探索什么问题？不是一个说教式的答案，而是一个
真正没有简单答案的问题——一个你会愿意和读者争论的问题。

【为什么不是套路】
一句话说明：在所属类型中，这个概念打破了什么常规？
它提供了什么类型的读者自认为想要、但实际上从未见过的东西？

---

跨概念多样性要求（共 {count} 个概念）：

{genre_diversity_requirements}

调性多样性要求：
— 至少包含：冷峻/温暖/诡异/悲怆/诙谐 中的三种以上
— 允许"难归类"的混合调性（如：表面诙谐内核悲凉）

叙事视角多样性：
— 至少包含两种以上的叙事距离（全知/限知/多重/不可靠叙述者）
— 至少一个概念尝试非传统的叙事结构（时间折叠/多线汇聚/碎片拼图/环形叙事等）

绝对不要生成：
— 纯套路爽文模板（穿越后用现代知识碾压古人/退婚打脸逆袭流/
  霸总甜宠带球跑/系统加持一路升级）
— 完全善恶二元的道德框架（除非有真正深刻的颠覆性处理）
— 依赖巧合而非角色主动选择推动的关键转折
— "灵感枯竭时随手写的"模糊概念（必须具体到能看见画面）
"""
```

**关键变更**：
| 原字段 | 新字段 | 变更理由 |
|--------|--------|---------|
| MAGIC/COST | 核心机制与代价 | 通用化：科幻→技术代价，悬疑→信息不对称，现实→道德困境 |
| Sanderson 第二定律 | 限制比能力更重要 | 保留核心洞察，去掉专有名词 |
| WORLD (奇幻专属) | 世界/背景 (分类讨论) | 对现实/历史/科幻/悬疑/奇幻各有针对性提示 |
| 奇幻多样性列表 | `{genre_diversity_requirements}` | 动态注入，依 `--genre` 参数变化 |
| 奇幻反例列表 | 中文网文套路反例列表 | 穿越重生打脸/霸总甜宠/退婚逆袭等 |

---

#### S4: RIFF_PROMPT 重写 — `seed.py` `RIFF_PROMPT`

**变更前** (L97-115):
```python
RIFF_PROMPT = """I have a seed idea for a fantasy novel:

"{idea}"

Generate 5 variations on this concept. Keep what's interesting about
the core idea but push it in different directions. For each variation:

NUMBER. TITLE
HOOK: One sentence.
HOW IT DIFFERS: What did you change from the original seed and why?
WORLD: Concrete, sensory world details.
MAGIC/COST: The speculative element and its cost.
TENSION: Personal + cosmic conflict.
THEME: The question it explores.

Make the variations genuinely different from each other -- don't just
tweak surface details. Change the protagonist, the setting, the tone,
the structure, the thematic focus.
"""
```

**变更后**:
```python
RIFF_PROMPT = """我有一个小说种子概念：

"{idea}"

请围绕这个核心概念，生成 5 个不同的变体。保留原概念中最有趣的内核，
但将它推向完全不同的方向。

对每个变体，提供：

【编号】. 【暂定书名】

【一句话钩子】

【与原版的区别】
你改变了什么？为什么这个改变值得探索？
（不是微调表面细节，而是改变：主角的身份/立场、故事的时代/地点、
  核心冲突的本质、情感调性、叙事结构）

【世界/背景】
具体、可感知的世界细节。让人能看见、听见、闻到这个世界。

【核心机制与代价】
推动叙事的核心引擎及其约束条件。代价如何制造真正的困境？

【核心冲突】
个人与系统两个层面的冲突如何相互牵制？

【主题问题】
这个故事真正在追问什么？

---

必须保证 5 个变体之间存在真正的差异——改变的不是细节装饰，
而是故事的 DNA：主角是谁、冲突的本质、调性的底色、结构的骨骼、
主题追问的方向。

至少一个变体将原概念的类型完全翻转（如果原是幻想类→尝试现实类表达；
如果原是现实类→尝试幻想类隐喻）。
至少一个变体彻底改变主角的社会位置（如果原是上位者→底层视角；
如果原是局外人→局内人视角）。
"""
```

**关键变更**：
- 移除「fantasy novel」声明
- MAGIC/COST → 核心机制与代价
- 新增「类型翻转」「社会位置翻转」等创意激发约束
- 中文表达

---

#### S5: 输出与交互中文化 — `seed.py` `main()`

**变更前** (L118-147):
```python
def main():
    parser = argparse.ArgumentParser(description="Generate novel seed concepts")
    ...
    if not ANTHROPIC_API_KEY:
        print("ERROR: Set ANTHROPIC_API_KEY in .env first")
        sys.exit(1)

    if args.riff:
        print(f"Riffing on: {args.riff}\n")
        ...
    else:
        print(f"Generating {args.count} seed concepts...\n")
        ...

    result = call_writer(prompt, max_tokens=8000)
    print(result)
    print("\n" + "=" * 60)
    print("To pick a seed, copy the concept you like into seed.txt:")
    print("  nano seed.txt")
    print("Or remix several concepts into your own seed.")
    print("Then proceed to Step 2 in WORKFLOW.md.")
```

**变更后**:
```python
def main():
    parser = argparse.ArgumentParser(
        description="中文小说种子概念生成器 — 适用于所有长篇小说类型",
    )
    parser.add_argument("--count", type=int, default=10,
                        help="生成概念数量（默认: 10）")
    parser.add_argument("--riff", type=str, default=None,
                        help="围绕已有想法展开 5 个变体")
    parser.add_argument("--genre", type=str, default=None,
                        help="指定类型聚焦（如: 科幻、悬疑、言情、历史、武侠、都市、现实）。留空则跨类型生成。")
    args = parser.parse_args()

    # 加载配置确认 API 可用
    cfg = config
    cfg.load()
    if not cfg.api_key:
        print("❌ 错误: 未配置 API Key。请先运行 novel_app.bat 完成配置。")
        sys.exit(1)

    total_chapters = cfg.total_chapters if cfg.loaded else 24

    if args.riff:
        banner(f"围绕核心概念展开 5 个变体")
        print(f"  核心概念: {args.riff}\n")
        prompt = RIFF_PROMPT.format(idea=args.riff)
    else:
        genre_hint = args.genre
        genre_constraint = _build_genre_constraint(genre_hint, args.count)
        genre_diversity = _build_genre_diversity(genre_hint, args.count)
        banner(f"生成 {args.count} 个种子概念")
        if genre_hint:
            print(f"  类型聚焦: {genre_hint}\n")
        else:
            print(f"  类型覆盖: 跨类型多样化生成\n")
        prompt = GENERATE_PROMPT.format(
            count=args.count,
            total_chapters=total_chapters,
            genre_constraint=genre_constraint,
            genre_diversity_requirements=genre_diversity,
        )

    step("调用 LLM 生成种子概念 ...")
    result = call_writer(
        prompt,
        system=SEED_SYSTEM_PROMPT,
        max_tokens=12000,  # 10个概念需要更长输出
        temperature=1.0,   # 保持高创意温度
        max_total_time=600,
    )

    print(result)
    print()
    print("=" * 65)
    print("下一步:")
    print("  1. 从上述概念中选择一个你最感兴趣的")
    print("  2. 复制该概念到 seed.txt（项目根目录）")
    print("  3. 运行 novel_app.bat 启动完整流水线")
    print("     或运行 uv run python run_pipeline.py --from-scratch")
    print()
    print("你也可以混合多个概念中的元素，创造属于你自己的独特种子。")
    print("=" * 65)
```

---

#### S6: 添加辅助函数 — `seed.py`

新增两个函数用于动态构建 prompt 的类型约束部分：

```python
def _build_genre_constraint(genre_hint: str | None, count: int) -> str:
    """构建类型约束段落。"""
    if genre_hint:
        return f"""类型聚焦：所有 {count} 个概念必须属于「{genre_hint}」类型。
但在此类型内部，请尽可能多样化亚类型分支、调性、叙事结构。"""
    else:
        return f"""类型覆盖：{count} 个概念应覆盖至少 4 种以上的文学类型。
在现实题材、历史题材、悬疑/惊悚、科幻、奇幻/玄幻、言情/情感、武侠/仙侠
中自由选择，不要全部偏向某一类型。"""


def _build_genre_diversity(genre_hint: str | None, count: int) -> str:
    """构建多样性要求段落。"""
    if genre_hint:
        # 单类型内部多样化
        return f"""类型内部多样性（{genre_hint}类型内）：
— 至少覆盖 2 种不同的亚类型分支或子方向
— 至少包含一个「安静/文学化」的概念和一个「强情节/高概念」的概念
— 时代背景至少横跨 2 种（古代/近代/现代/近未来/架空时间）
— 至少一个概念以非典型主角为中心（非青年/非强者/非"天选"）"""
    else:
        # 跨类型多样化
        return f"""跨类型多样性要求：
— 至少包含 4 种不同文学类型
— 每种类型不超过 {max(3, count // 3)} 个概念
— 至少一个现实/历史题材（无超自然元素）
— 至少一个科幻或奇幻/玄幻题材
— 至少一个悬疑/惊悚题材
— 至少一个以情感关系为核心驱动的题材"""
```

---

#### S7: CLI 入口确认 — 无需变更下游文件

`seed.py` 作为独立脚本运行，输出到 stdout，下游消费不受影响：

- `run_pipeline.py --from-scratch` 仅检查 `seed.txt` 是否存在 → 无需变更
- `foundation/gen_*.py` 全部通过 `cfg.story_summary` 读取 → 无需变更
- `novel_app.py` 独立收集用户梗概 → 无需变更
- `gen_canon.py`（根目录旧版）读取根目录 `seed.txt` → 无需变更（向后兼容）

---

## 4. 变更范围汇总

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| [`seed.py`](../seed.py) | 🔴 重写 | 148行→约220行；API层/系统提示/两个核心prompt/main全部重写 |
| 其他文件 | 无变更 | P2-10 仅涉及 seed.py |

### 变更明细

| 原代码块 | 变更 | 新代码块 |
|---------|------|---------|
| L1-9: 文件头注释 | 重写 | 中文，强调全类型适用 |
| L11-24: 导入 + 环境变量 | 替换 | `from core.api_client import call_writer` + `from core.config import config` |
| L27-56: `call_writer()` | 删除 | 不再需要，由 core 提供 |
| L39-46: system prompt | 重写 | `SEED_SYSTEM_PROMPT` 常量，跨类型 |
| L59-95: `GENERATE_PROMPT` | 重写 | 中文化 + 类型自适应 + `{genre_constraint}` + `{genre_diversity_requirements}` |
| L97-115: `RIFF_PROMPT` | 重写 | 中文化 + 类型无关 + 创意翻转约束 |
| L118-147: `main()` | 重写 | 新增 `--genre` 参数 + 调用 `call_writer` + 辅助函数 + 中文输出 |
| 新增 | 新增 | `_build_genre_constraint()` / `_build_genre_diversity()` 辅助函数 |

---

## 5. 类型覆盖验证矩阵

实施后应通过以下场景验证：

| 测试场景 | 命令 | 预期 |
|---------|------|------|
| 基础生成 | `python seed.py --count=5` | 5 个概念，跨 ≥4 种类型 |
| 类型聚焦 | `python seed.py --genre 科幻 --count=5` | 5 个概念，全部科幻，亚类型多样 |
| 类型聚焦(悬疑) | `python seed.py --genre 悬疑 --count=5` | 5 个概念，全部悬疑，亚类型多样 |
| 类型聚焦(言情) | `python seed.py --genre 言情 --count=5` | 5 个概念，全部言情，无超自然 |
| 变体展开 | `python seed.py --riff "一个律师发现所有案子都与20年前同一事件有关"` | 5 个变体，含类型翻转 |
| 无 API Key | `python seed.py`（未配置 config.json） | 明确的中文错误提示 |
| API 错误 | `python seed.py`（错误 API Key） | 由 core.api_client 统一处理重试/超时 |

---

## 6. 与已有 P0/P1/P2 任务的兼容性

| 已完成任务 | 兼容性 | 说明 |
|-----------|--------|------|
| P0-1 Writer/Judge 分离 | ✅ | seed.py 使用 `call_writer`，不涉及 judge |
| P0-3b 跨文件去奇幻化 | ✅ | seed.py 作为全新中文 prompt，零奇幻假设 |
| P2-9 Voice Discovery | ✅ | seed.py 输出是粗粒度概念，不影响 voice |

---

## 7. 实施优先级

| 步骤 | 优先级 | 原因 |
|------|--------|------|
| S1: API 层迁移 | 🔴 P0 | 不迁移则无法在中文项目中运行 |
| S2: 系统提示重写 | 🔴 P0 | 奇幻 → 跨类型是核心需求 |
| S3: GENERATE_PROMPT 重写 | 🔴 P0 | 核心 prompt，决定生成质量 |
| S4: RIFF_PROMPT 重写 | 🟡 P1 | 变体展开功能 |
| S5: 输出交互中文化 | 🟡 P1 | 用户体验 |
| S6: --genre 参数 | 🟢 P2 | 便利性增强 |
| S7: 测试 | 🟡 P1 | 质量保证 |

所有步骤在一个实现周期内完成（seed.py 是单文件脚本，约 220 行）。