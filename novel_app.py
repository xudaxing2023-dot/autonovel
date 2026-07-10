#!/usr/bin/env python3
"""
novel_app.py — 中文长篇小说自动生成器 交互式启动入口

用户输入顺序：
  1. 生成模式 (from_scratch / resume)
  2. 总章节数 + 分卷设置
  3. 故事来源（手动输入 / AI 种子生成 → 挑选，种子生成使用步骤 2 的章节数）
  4. 确认并启动

API 配置（模型、Key、端点）全部通过 .env 文件管理，不在此交互输入。
"""

import json
import re
import sys
from pathlib import Path

from core.config import config, OUTPUT_DIR

# ——— 种子生成 prompts ———

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
    if genre_hint:
        return f"""类型聚焦：所有 {count} 个概念必须属于「{genre_hint}」类型。
但在此类型内部，请尽可能多样化亚类型分支、调性、叙事结构。"""
    else:
        return f"""类型覆盖：{count} 个概念应覆盖至少 4 种以上的文学类型。
在现实题材、历史题材、悬疑/惊悚、科幻、奇幻/玄幻、言情/情感、武侠/仙侠
中自由选择，不要全部偏向某一类型。"""


def _build_genre_diversity(genre_hint: str | None, count: int) -> str:
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


# ——— 种子解析 ———

def _parse_seeds(raw_output: str) -> list[dict]:
    blocks = [b.strip() for b in raw_output.split("\n---") if b.strip()]
    blocks = [b.lstrip("-").strip() for b in blocks]
    seeds = []
    for block in blocks:
        title_match = re.search(r"【(\d+)】\.\s*【(.+?)】", block)
        if not title_match:
            continue
        num = int(title_match.group(1))
        title = title_match.group(2)
        hook_match = re.search(
            r"【一句话钩子】\s*\n(.+?)(?=\n【|\Z)", block, re.DOTALL)
        hook = ""
        if hook_match:
            hook = hook_match.group(1).strip()
            if len(hook) > 120:
                hook = hook[:117] + "..."
        seeds.append({
            "num": num, "title": title, "hook": hook, "full_text": block,
        })
    return seeds


# ——— 辅助打印 ———

def _print_banner():
    print()
    print("=" * 65)
    print("    🌏  中文长篇小说自动生成器  v1.2")
    print("    API 配置 → 编辑 .env 文件")
    print("=" * 65)
    print()


def _section(title: str):
    print("━" * 50)
    print(title)
    print()


# ——— .env 检测 ———

def _check_env() -> bool:
    """检测 .env 是否已配置 API Key，未配置则报错退出。"""
    from core.config import ENV_FILE
    if not ENV_FILE.exists():
        print("  ❌ 未找到 .env 文件。请在项目根目录创建 .env 文件并配置 API。")
        print("     参考格式：")
        print("     AUTONOVEL_API_KEY=your-key-here")
        print("     AUTONOVEL_API_BASE_URL=https://api.openai.com/v1")
        print("     AUTONOVEL_MODEL_NAME=deepseek-ai/deepseek-v4-flash")
        sys.exit(1)
    content = ENV_FILE.read_text(encoding="utf-8-sig")
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("AUTONOVEL_API_KEY="):
            val = line.split("=", 1)[1].strip()
            if val and val not in ("", "sk-your-api-key-here", "sk-..."):
                return True
    print("  ❌ .env 文件中未配置有效的 AUTONOVEL_API_KEY。")
    print("     请编辑 .env 文件，确保 API Key 已正确填写。")
    sys.exit(1)


# ——— 模式选择（最前面） ———

def _collect_mode() -> str:
    """步骤 1: 选择生成模式。"""
    _section("1. 生成模式：")
    print("   [1] 从头开始生成（完整流水线）")
    print("   [2] 继续上次生成（从 state.json 恢复）")
    print()
    choice = input("   请选择 [1/2] (默认: 2): ").strip()
    mode = "resume" if choice != "1" else "from_scratch"
    if mode == "resume":
        state_file = OUTPUT_DIR / "state.json"
        if not state_file.exists():
            print("   ⚠ 未找到 state.json，将从头开始生成")
            mode = "from_scratch"
    print(f"   → 模式: {'从头开始' if mode == 'from_scratch' else '继续上次'}")
    print()
    return mode


# ——— 故事梗概采集 ———

def _input_story_manually() -> str:
    _section("故事梗概 — 手动输入")
    print("   一段话描述你的故事核心（主角、世界观、核心冲突、独特之处）：")
    print()
    story = input("   > ").strip()
    while not story:
        print("   ⚠ 故事梗概不能为空，请重新输入：")
        story = input("   > ").strip()
    print()
    return story


def _generate_and_pick_seed(total_chapters: int) -> str:
    from core.api_client import call_writer
    seed_count = 8
    genre_constraint = _build_genre_constraint(None, seed_count)
    genre_diversity = _build_genre_diversity(None, seed_count)
    prompt = SEED_GENERATE_PROMPT.format(
        count=seed_count, total_chapters=total_chapters,
        genre_constraint=genre_constraint,
        genre_diversity_requirements=genre_diversity,
    )
    print()
    print(f"  ⏳ 正在调用 AI 生成 {seed_count} 个种子概念（约需 30–60 秒）...")
    print()
    try:
        raw = call_writer(prompt, system=SEED_SYSTEM_PROMPT,
                          temperature=1.0, max_total_time=600)
    except Exception as e:
        print(f"  ⚠ 种子生成失败: {e}")
        print("  将切换到手动输入模式。\n")
        return _input_story_manually()
    seeds = _parse_seeds(raw)
    if len(seeds) < 3:
        print(f"  ⚠ 解析到的概念太少（{len(seeds)} 个），将切换到手动输入模式。\n")
        return _input_story_manually()
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
            print("  → 切换到手动输入模式。\n")
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
            print(f"  → 已选: 《{selected['title']}》\n")
            return selected["full_text"]
        print("  ⚠ 编号无效，请重新输入。")


def _collect_story(total_chapters: int) -> str:
    """步骤 3: 采集故事梗概（种子生成使用用户指定的章节数）。"""
    _section("3. 故事来源：")
    print("   [1] 我自己写一段梗概")
    print("   [2] 让 AI 帮我生成一批种子概念，我从中挑选")
    print()
    choice = input("   请选择 [1/2] (默认: 1): ").strip()
    if choice == "2":
        return _generate_and_pick_seed(total_chapters)
    else:
        return _input_story_manually()


# ——— 章节和分卷配置 ———

def _collect_chapters_volumes() -> tuple[int, int, int]:
    """步骤 2: 采集总章节数 + 分卷设置。返回 (total_chapters, total_volumes, chapters_per_volume)。"""
    _section("2. 小说总章节数（建议 9–30，默认 9）：")
    ch_input = input("   > ").strip()
    total_chapters = int(ch_input) if ch_input.isdigit() and int(ch_input) > 0 else 9
    print(f"   → 总章节数: {total_chapters}")
    print()

    _section("2.1. 分卷设置:")
    print("   方案 D 始终启用分层大纲。将小说分为若干卷，每卷固定章数。")
    print("   单卷时（默认），一卷包含全部章节。")
    print()
    vol_input = input("   总卷数（默认: 1，最少 1）: ").strip()
    total_volumes = int(vol_input) if vol_input.isdigit() and int(vol_input) >= 1 else 1
    print(f"   → 总卷数: {total_volumes}")
    default_chpv = total_chapters // total_volumes
    chpv_input = input(
        f"   每卷章节数（默认: {default_chpv}，总计 {total_chapters} 章）: ").strip()
    chapters_per_volume = (
        int(chpv_input) if chpv_input.isdigit() and int(chpv_input) > 0
        else default_chpv)
    print(f"   → 每卷章数: {chapters_per_volume}")

    expected_ch = total_volumes * chapters_per_volume
    if expected_ch != total_chapters:
        print()
        print(f"   ⚠ 注意: {total_volumes} 卷 × {chapters_per_volume} 章/卷 = {expected_ch} 章")
        print(f"     与当前总章节数 {total_chapters} 不一致。")
        use_expected = input(f"     是否将总章节数改为 {expected_ch}？[Y/n]: ").strip().lower()
        if use_expected != "n":
            total_chapters = expected_ch
            print(f"     → 总章节数已更新为: {total_chapters}")
        else:
            print(f"     → 保持总章节数: {total_chapters}（卷间章节数可能不均）")
    print()
    return total_chapters, total_volumes, chapters_per_volume


# ——— 确认与启动 ———

def confirm_and_start(mode: str, story: str, total_chapters: int,
                      total_volumes: int, chapters_per_volume: int):
    """展示配置摘要，确认后启动流水线。"""
    cfg = config
    cfg.load()
    print()
    print("=" * 65)
    print("  配置摘要")
    print("=" * 65)
    print(f"  故事梗概:      {story[:60].replace(chr(10), ' ')}...")
    print(f"  总章节数:      {total_chapters} 章")
    print(f"  分卷:          {total_volumes} 卷 × {chapters_per_volume} 章/卷")
    print(f"  API 端点:      {cfg.api_base_url}")
    print(f"  模型:          {cfg.model_name}")
    print(f"  生成模式:      {'从头开始' if mode == 'from_scratch' else '继续上次'}")
    print("=" * 65)
    print()

    confirm = input("  确认以上信息无误？按 Enter 开始生成，输入 q 退出: ").strip()
    if confirm.lower() == "q":
        print("  已取消。")
        sys.exit(0)

    # 保存配置
    from datetime import datetime
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    config_data = {
        "story_summary": story,
        "total_chapters": total_chapters,
        "total_volumes": total_volumes,
        "chapters_per_volume": chapters_per_volume,
        "mode": mode,
        "started_at": datetime.now().isoformat(),
    }
    config.save(config_data)
    story_file = OUTPUT_DIR / "story_summary.txt"
    story_file.write_text(story, encoding="utf-8")

    print()
    print("=" * 65)
    print("  🚀 启动流水线 ...")
    print("=" * 65)
    print()

    from pipeline_orchestrator import run_pipeline
    run_pipeline(mode=mode)


def main():
    try:
        _print_banner()
        # 1. 检查 .env
        _check_env()
        # 2. 模式选择（最前面）
        mode = _collect_mode()
        # 3. 章节和分卷（先确定章节数，供后续种子生成使用）
        total_ch, total_vol, chpv = _collect_chapters_volumes()
        # 4. 故事梗概（种子生成可使用已确定的章节数）
        story = _collect_story(total_ch)
        # 5. 确认启动
        confirm_and_start(mode, story, total_ch, total_vol, chpv)
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
