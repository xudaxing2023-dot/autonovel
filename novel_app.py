#!/usr/bin/env python3
"""
novel_app.py — 中文长篇小说自动生成器 交互式启动入口

用户输入：
  1. API 提供商选择 (NVIDIA / 硅基流动 / DeepSeek / 自定义)
  2. API Key
  3. 模型名称
  3.5. 分阶段模型配置（方案 D 新增——可选，Phase 1/2/3 各自独立）
  4. 故事来源（手动输入 / AI 种子生成 → 挑选）
  5. 总章节数
  5.5. 分卷设置（方案 D 新增——总卷数 + 每卷章数，默认 1 卷含全部章节）
  6. 生成模式 (从头开始 / 继续上次)
  7. 判断模型（可选，留空则共用写作模型）

然后启动 pipeline_orchestrator.py。
"""

import json
import re
import sys
from pathlib import Path

from core.config import config, OUTPUT_DIR

# ——— 种子生成 prompts（从 seed.py 提取，避免循环依赖） ———

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

SEED_GENERATE_PROMPT = """请生成 {count} 个中文长篇小说种子概念。每个概念应是一个完整的小说核心构想，
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
— "灵感枯竭时随手写的"模糊概念（必须具体到能看见画面）"""


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
        return f"""类型内部多样性（{genre_hint}类型内）：
— 至少覆盖 2 种不同的亚类型分支或子方向
— 至少包含一个"安静/文学化"的概念和一个"强情节/高概念"的概念
— 时代背景至少横跨 2 种（古代/近代/现代/近未来/架空时间）
— 至少一个概念以非典型主角为中心（非青年/非强者/非"天选"）"""
    else:
        max_per_genre = max(3, count // 3)
        return f"""跨类型多样性要求：
— 至少包含 4 种不同文学类型
— 每种类型不超过 {max_per_genre} 个概念
— 至少一个现实/历史题材（无超自然元素）
— 至少一个科幻或奇幻/玄幻题材
— 至少一个悬疑/惊悚题材
— 至少一个以情感关系为核心驱动的题材"""


# ——— 预设 API 提供商 ———

PRESET_PROVIDERS = {
    "1": {
        "name": "NVIDIA NIM",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "default_model": "meta/llama-3.3-70b-instruct",
    },
    "2": {
        "name": "硅基流动 (SiliconFlow)",
        "base_url": "https://api.siliconflow.cn/v1",
        "default_model": "deepseek-ai/DeepSeek-V3",
    },
    "3": {
        "name": "DeepSeek 官方",
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
    },
    "4": {
        "name": "自定义",
        "base_url": "",  # 用户输入
        "default_model": "",
    },
}

# ——— 种子解析 ———

def _parse_seeds(raw_output: str) -> list[dict]:
    """解析 LLM 种子概念输出，返回 {num, title, hook, full_text} 列表。"""
    # 用 --- 分割各概念
    blocks = [b.strip() for b in raw_output.split("\n---") if b.strip()]
    # 去掉可能的前导 ---
    blocks = [b.lstrip("-").strip() for b in blocks]

    seeds = []
    for block in blocks:
        # 提取编号和书名: 【X】. 【书名】
        title_match = re.search(r"【(\d+)】\.\s*【(.+?)】", block)
        if not title_match:
            continue
        num = int(title_match.group(1))
        title = title_match.group(2)

        # 提取一句话钩子（位于 【一句话钩子】 之后，到下一个 【...】 或末尾）
        hook_match = re.search(
            r"【一句话钩子】\s*\n(.+?)(?=\n【|\Z)", block, re.DOTALL
        )
        hook = ""
        if hook_match:
            hook = hook_match.group(1).strip()
            # 截断过长的钩子用于预览
            if len(hook) > 120:
                hook = hook[:117] + "..."

        seeds.append({
            "num": num,
            "title": title,
            "hook": hook,
            "full_text": block,
        })

    return seeds


# ——— 辅助打印 ———

def _print_banner():
    print()
    print("=" * 65)
    print("    🌏  中文长篇小说自动生成器  v1.1")
    print("    支持: NVIDIA NIM / 硅基流动 / DeepSeek / 自定义")
    print("=" * 65)
    print()


def _section(title: str):
    """打印章节分隔。"""
    print("━" * 50)
    print(title)
    print()


# ——— .env 检测 ———

def _env_has_api_key() -> bool:
    """检测 .env 文件是否已配置 API Key。"""
    from core.config import ENV_FILE
    if not ENV_FILE.exists():
        return False
    content = ENV_FILE.read_text(encoding="utf-8")
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("AUTONOVEL_API_KEY="):
            val = line.split("=", 1)[1].strip()
            # 排除空值、占位符和示例值
            if val and val not in ("", "sk-your-api-key-here", "sk-..."):
                return True
    return False


# ——— API 配置采集（步骤 1–3） ———

def _collect_api_config() -> dict:
    """采集 API 配置，保存临时 config 以供种子生成使用。返回临时配置字典。"""

    print("首先配置 API 连接信息：")
    print()

    # 1. API 提供商
    _section("1. API 提供商选择：")
    for key, prov in PRESET_PROVIDERS.items():
        print(f"   [{key}] {prov['name']}")
    print()
    provider_choice = input("   请选择 [1/2/3/4] (默认: 2): ").strip()
    if provider_choice not in PRESET_PROVIDERS:
        provider_choice = "2"
    provider = PRESET_PROVIDERS[provider_choice]
    print(f"   → 已选: {provider['name']}")
    print()

    # 2. API Key
    _section(f"2. {provider['name']} API Key：")
    if provider_choice == "1":
        print("   (从 https://build.nvidia.com 获取)")
    elif provider_choice == "2":
        print("   (从 https://siliconflow.cn 获取)")
    elif provider_choice == "3":
        print("   (从 https://platform.deepseek.com 获取)")
    print()
    api_key = input("   > ").strip()
    while not api_key:
        print("   ⚠ API Key 不能为空，请重新输入：")
        api_key = input("   > ").strip()
    print()

    # 3. API Base URL（仅自定义）
    if provider_choice == "4":
        _section("3. API 端点 URL（例如 https://api.example.com/v1）：")
        base_url = input("   > ").strip()
        while not base_url:
            print("   ⚠ 端点 URL 不能为空：")
            base_url = input("   > ").strip()
    else:
        base_url = provider["base_url"]
    print()

    # 4. 模型名称
    _section(f"3. 模型名称（默认: {provider['default_model']}）：")
    model_name = input("   > ").strip()
    if not model_name:
        model_name = provider["default_model"]
    print(f"   → 模型: {model_name}")
    print()

    temp_config = {
        "api_base_url": base_url.rstrip("/"),
        "api_key": api_key,
        "model_name": model_name,
        "provider": provider["name"],
        "api_interval_seconds": 4,
    }

    # 保存临时配置，以便种子生成可调用 API
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    config.save(temp_config)

    return temp_config


# ——— 分阶段模型配置采集（方案 D 步骤 3.5） ———

def _collect_phase_configs() -> dict:
    """采集 Phase 1/2/3 各自的模型配置（可选——留空则共用写作模型）。

    返回 dict 的键名与 core/config.py _SECRET_KEYS 一致：
      p1_api_key, p1_api_base_url, p1_model_name,
      p2_api_key, p2_api_base_url, p2_model_name,
      p3_api_key, p3_api_base_url, p3_model_name.
    空值项不会被写入 .env，自动走 config 回退链。
    不采集 P2_CTX（高级选项，用户可手动编辑 .env）。
    """
    _section("3.5. 分阶段模型配置（可选——留空全部字段则共用上述写作模型）:")

    print("   Phase 1 (基础构建): world/characters/outline/canon/voice 生成。")
    print("   Phase 2 (章节起草): 需要大上下文窗口（建议用 1M 上下文模型）。")
    print("   Phase 3 (修订评估): 对抗编辑/读者评审/全文评估。")
    print("   P1 和 P3 建议用免费模型；P2 建议用有大上下文的模型。")
    print()

    # --- Phase 1 ---
    print("   --- Phase 1: 基础构建 ---")
    p1_model = input("   [可选] 模型名称: ").strip()
    p1_key   = input("   [可选] API Key:   ").strip()
    p1_url   = input("   [可选] API 端点:  ").strip()
    print()

    # --- Phase 2 ---
    print("   --- Phase 2: 章节起草 ---")
    p2_model = input("   [可选] 模型名称: ").strip()
    p2_key   = input("   [可选] API Key:   ").strip()
    p2_url   = input("   [可选] API 端点:  ").strip()
    print()

    # --- Phase 3 ---
    print("   --- Phase 3: 修订评估 ---")
    p3_model = input("   [可选] 模型名称: ").strip()
    p3_key   = input("   [可选] API Key:   ").strip()
    p3_url   = input("   [可选] API 端点:  ").strip()
    print()

    return {
        "p1_model_name": p1_model, "p1_api_key": p1_key, "p1_api_base_url": p1_url,
        "p2_model_name": p2_model, "p2_api_key": p2_key, "p2_api_base_url": p2_url,
        "p3_model_name": p3_model, "p3_api_key": p3_key, "p3_api_base_url": p3_url,
    }


# ——— 故事梗概采集（步骤 4） ———

def _input_story_manually() -> str:
    """让用户手动输入故事梗概。"""
    _section("故事梗概 — 手动输入")
    print("   一段话描述你的故事核心（主角、世界观、核心冲突、独特之处）：")
    print()
    story = input("   > ").strip()
    while not story:
        print("   ⚠ 故事梗概不能为空，请重新输入：")
        story = input("   > ").strip()
    print()
    return story


def _generate_and_pick_seed(temp_config: dict) -> str:
    """调用 LLM 生成种子概念 → 展示列表 → 用户挑选 → 返回选中概念的全文。"""
    from core.api_client import call_writer

    seed_count = 8
    total_chapters = 24  # 种子生成用默认值，实际章节数后面再收集

    genre_constraint = _build_genre_constraint(None, seed_count)
    genre_diversity = _build_genre_diversity(None, seed_count)

    prompt = SEED_GENERATE_PROMPT.format(
        count=seed_count,
        total_chapters=total_chapters,
        genre_constraint=genre_constraint,
        genre_diversity_requirements=genre_diversity,
    )

    print()
    print("  ⏳ 正在调用 AI 生成 {0} 个种子概念（约需 30–60 秒）...".format(seed_count))
    print()

    try:
        raw = call_writer(
            prompt,
            system=SEED_SYSTEM_PROMPT,
            max_tokens=12000,
            temperature=1.0,
            max_total_time=600,
        )
    except Exception as e:
        print(f"  ⚠ 种子生成失败: {e}")
        print("  将切换到手动输入模式。")
        print()
        return _input_story_manually()

    seeds = _parse_seeds(raw)

    if len(seeds) < 3:
        print("  ⚠ 解析到的概念太少（{0} 个），将切换到手动输入模式。".format(len(seeds)))
        print()
        return _input_story_manually()

    # 展示列表
    print("━" * 50)
    print("  🌱  AI 生成的种子概念 — 请挑选一个：")
    print("━" * 50)
    print()
    for s in seeds:
        hook_preview = s["hook"][:80] + "..." if len(s["hook"]) > 80 else s["hook"]
        print(f"  [{s['num']}] 《{s['title']}》")
        print(f"      {hook_preview}")
        print()

    print("  [0] 都不满意，让我自己输入梗概")
    print()

    while True:
        choice = input("  请输入编号 (默认: 1): ").strip()
        if choice == "0" or choice.lower() == "q":
            print("  → 切换到手动输入模式。")
            print()
            return _input_story_manually()
        if not choice:
            choice = "1"

        try:
            num = int(choice)
        except ValueError:
            print("  ⚠ 请输入有效编号。")
            continue

        matched = [s for s in seeds if s["num"] == num]
        if matched:
            selected = matched[0]
            print(f"  → 已选: 《{selected['title']}》")
            print()
            # 返回完整概念文本作为故事梗概
            return selected["full_text"]

        print("  ⚠ 编号无效，请重新输入。")


def _collect_story() -> str:
    """采集故事梗概——让用户选择来源方式。"""
    _section("故事来源：")

    print("   [1] 我自己写一段梗概")
    print("   [2] 让 AI 帮我生成一批种子概念，我从中挑选")
    print()
    choice = input("   请选择 [1/2] (默认: 1): ").strip()

    if choice == "2":
        return _generate_and_pick_seed({})
    else:
        return _input_story_manually()


# ——— 剩余配置采集（步骤 5–7） ———

def _collect_remaining(temp_config: dict, story: str) -> dict:
    """采集章节数、卷数、生成模式、判断模型，构建最终配置。"""
    # 4. 总章节数（不变）
    _section("4. 小说总章节数（建议 12–30，默认 24）：")
    ch_input = input("   > ").strip()
    total_chapters = int(ch_input) if ch_input.isdigit() and int(ch_input) > 0 else 24
    print(f"   → 总章节数: {total_chapters}")
    print()

    # ★ 步骤 4.5: 分卷设置（方案 D 新增）★
    _section("4.5. 分卷设置:")
    print("   方案 D 始终启用分层大纲。将小说分为若干卷，每卷固定章数。")
    print("   单卷时（默认），一卷包含全部章节，功能等价于原版扁平大纲。")
    print()
    vol_input = input("   总卷数（默认: 1，最少 1）: ").strip()
    total_volumes = int(vol_input) if vol_input.isdigit() and int(vol_input) >= 1 else 1

    print(f"   → 总卷数: {total_volumes}")
    # 默认每卷章数 = 总章节数 / 总卷数（整除，用户可覆盖）
    default_chpv = total_chapters // total_volumes
    chpv_input = input(
        f"   每卷章节数（默认: {default_chpv}，总计 {total_chapters} 章）: "
    ).strip()
    chapters_per_volume = (
        int(chpv_input) if chpv_input.isdigit() and int(chpv_input) > 0
        else default_chpv
    )
    print(f"   → 每卷章数: {chapters_per_volume}")

    # 一致性校验
    expected_ch = total_volumes * chapters_per_volume
    if expected_ch != total_chapters:
        print()
        print(
            f"   ⚠ 注意: {total_volumes} 卷 × {chapters_per_volume} 章/卷"
            f" = {expected_ch} 章"
        )
        print(f"     与当前总章节数 {total_chapters} 不一致。")
        use_expected = input(
            f"     是否将总章节数改为 {expected_ch}？[Y/n]: "
        ).strip().lower()
        if use_expected != "n":
            total_chapters = expected_ch
            print(f"     → 总章节数已更新为: {total_chapters}")
        else:
            print(
                f"     → 保持总章节数: {total_chapters}"
                f"（卷间章节数可能不均）"
            )
    print()

    # 5. 生成模式（不变——仅 _section 标题编号微调）
    _section("5. 生成模式：")
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
            # 继续模式：从已有 config 读取故事梗概
            cfg = config
            cfg.load()
            story = cfg.story_summary or story

    print(f"   → 模式: {'从头开始' if mode == 'from_scratch' else '继续上次'}")
    print()

    # 7. 判断模型（可选）
    _section("6. 判断模型（可选，留空则使用写作模型进行评估）：")
    print("   为避免 AI 自评自夸偏差，可配置独立的高判断力模型。")
    print("   留空全部字段 = 写作模型兼做判断。")
    print()
    judge_model_name = input(
        "   [可选] 判断模型名称（例如 deepseek-ai/DeepSeek-V3）：\n   > "
    ).strip()
    if judge_model_name:
        print(f"   → 判断模型: {judge_model_name}")
    else:
        print(f"   → 判断模型: [共用写作模型]")
    judge_api_base_url = input(
        "   [可选] 判断模型 API 端点（留空则使用上述写作端点）：\n   > "
    ).strip()
    if judge_api_base_url:
        print(f"   → 判断端点: {judge_api_base_url}")
    judge_api_key = input(
        "   [可选] 判断模型 API Key（留空则使用上述写作 Key）：\n   > "
    ).strip()
    if judge_api_key:
        print(f"   → 判断 Key:  已输入")
    print()

    # 构建最终配置
    from datetime import datetime

    config_data = {
        **temp_config,
        "story_summary": story,
        "total_chapters": total_chapters,
        # ★ 方案 D 新增
        "total_volumes": total_volumes,
        "chapters_per_volume": chapters_per_volume,
        "mode": mode,
        "started_at": datetime.now().isoformat(),
        "judge_model_name": judge_model_name,
        "judge_api_base_url": judge_api_base_url,
        "judge_api_key": judge_api_key,
    }

    return config_data


# ——— 主采集流程 ———

def collect_input() -> dict:
    """收集所有用户输入，返回配置字典。"""
    _print_banner()

    # Part 1: API 配置（如果 .env 已有 Key 则跳过）
    if _env_has_api_key():
        cfg = config
        cfg.load()
        temp_config = {
            "api_base_url": cfg.api_base_url,
            "api_key": cfg.api_key,
            "model_name": cfg.model_name,
            "provider": "（.env 已配置）",
            "api_interval_seconds": cfg.api_interval_seconds,
        }
        print(f"  ✅ 检测到 .env 已配置 API Key，跳过连接设置。")
        print(f"     端点: {cfg.api_base_url}")
        print(f"     模型: {cfg.model_name}")
        print()
    else:
        temp_config = _collect_api_config()

    # Part 1.5: 分阶段模型配置（方案 D 新增——全部可选）
    phase_configs = _collect_phase_configs()
    for k, v in phase_configs.items():
        if v:
            temp_config[k] = v

    # Part 2: 故事梗概
    story = _collect_story()

    # Part 3: 剩余配置（含卷数）
    config_data = _collect_remaining(temp_config, story)

    return config_data


# ——— 确认与启动 ———

def confirm_and_start(config_data: dict):
    """展示配置摘要，确认后启动流水线。"""
    print()
    print("=" * 65)
    print("  配置摘要")
    print("=" * 65)
    print(f"  故事梗概:      {config_data['story_summary'][:60].replace(chr(10), ' ')}...")
    print(f"  总章节数:      {config_data['total_chapters']} 章")

    # ★ 方案 D: 分卷信息（始终显示，方案 D 默认启用分层大纲）
    total_vol = config_data.get("total_volumes", 1)
    chpv = config_data.get("chapters_per_volume", 0)
    print(f"  分卷:          {total_vol} 卷 × {chpv} 章/卷")

    print(f"  提供商:        {config_data['provider']}")
    print(f"  API 端点:      {config_data['api_base_url']}")
    print(f"  模型:          {config_data['model_name']}")

    # ★ 方案 D: Phase 独立模型（仅当有独立配置时显示）
    for phase_label, prefix in [("P1 模型", "p1"), ("P2 模型", "p2"), ("P3 模型", "p3")]:
        model_key = f"{prefix}_model_name"
        phase_model = config_data.get(model_key, "")
        if phase_model:
            print(f"  {phase_label}:      [独立] {phase_model}")

    judge_display = config_data.get('judge_model_name', '')
    if judge_display:
        print(f"  判断模型:      [独立] {judge_display}")
    else:
        print(f"  判断模型:      [共用写作模型]")
    print(f"  API 间隔:      {config_data['api_interval_seconds']} 秒")
    print(f"  生成模式:      {'从头开始' if config_data['mode'] == 'from_scratch' else '继续上次'}")
    print("=" * 65)
    print()

    confirm = input("  确认以上信息无误？按 Enter 开始生成，输入 q 退出: ").strip()
    if confirm.lower() == "q":
        print("  已取消。")
        sys.exit(0)

    # 保存最终配置（Phase 敏感键自动写入 .env，卷级非敏感键写入 config.json）
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    config.save(config_data)

    # 保存梗概到独立文件
    story_file = OUTPUT_DIR / "story_summary.txt"
    story_file.write_text(config_data["story_summary"], encoding="utf-8")

    print()
    print("=" * 65)
    print("  🚀 启动流水线 ...")
    print("=" * 65)
    print()

    # 启动流水线
    from pipeline_orchestrator import run_pipeline
    run_pipeline(mode=config_data["mode"])


def main():
    try:
        config_data = collect_input()
        confirm_and_start(config_data)
    except KeyboardInterrupt:
        print("\n\n  已取消。")
        sys.exit(130)
    except Exception as e:
        print(f"\n  ❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()