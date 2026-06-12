#!/usr/bin/env python3
"""
novel_app.py — 中文长篇小说自动生成器 交互式启动入口

用户输入：
  1. 故事梗概
  2. 总章节数
  3. API 提供商选择 (NVIDIA / 硅基流动 / DeepSeek / 自定义)
  4. API Key
  5. 模型名称
  6. 生成模式 (从头开始 / 继续上次)

然后启动 pipeline_orchestrator.py。
"""

import json
import sys
from pathlib import Path

from core.config import config, OUTPUT_DIR

# 预设 API 提供商
PRESET_PROVIDERS = {
    "1": {
        "name": "NVIDIA NIM",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "default_model": "meta/llama-3.3-70b-instruct",
        "note": "每月 1000 次免费调用",
    },
    "2": {
        "name": "硅基流动 (SiliconFlow)",
        "base_url": "https://api.siliconflow.cn/v1",
        "default_model": "deepseek-ai/DeepSeek-V3",
        "note": "注册送 14 元额度",
    },
    "3": {
        "name": "DeepSeek 官方",
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
        "note": "注册送 500 万 tokens",
    },
    "4": {
        "name": "自定义",
        "base_url": "",  # 用户输入
        "default_model": "",
        "note": "适用于任何 OpenAI 兼容 API",
    },
}


def print_banner():
    print()
    print("=" * 65)
    print("    🌏  中文长篇小说自动生成器  v1.0")
    print("    基于 NousResearch/autonovel 重构")
    print("    支持: NVIDIA NIM / 硅基流动 / DeepSeek / 自定义")
    print("=" * 65)
    print()


def collect_input():
    """收集所有用户输入，返回配置字典。"""
    print_banner()

    print("请输入以下信息（直接回车使用默认值）：")
    print()

    # 1. 故事梗概
    print("━" * 50)
    print("1. 故事梗概")
    print("   一段话描述你的故事核心（主角、世界观、核心冲突、独特之处）：")
    print()
    story = input("   > ").strip()
    while not story:
        print("   ⚠ 故事梗概不能为空，请重新输入：")
        story = input("   > ").strip()
    print()

    # 2. 总章节数
    print("━" * 50)
    print("2. 小说总章节数（建议 12-30，默认 24）：")
    print()
    ch_input = input("   > ").strip()
    total_chapters = int(ch_input) if ch_input.isdigit() and int(ch_input) > 0 else 24
    print(f"   → 总章节数: {total_chapters}")
    print()

    # 3. API 提供商
    print("━" * 50)
    print("3. API 提供商选择：")
    print()
    for key, prov in PRESET_PROVIDERS.items():
        print(f"   [{key}] {prov['name']:<30} {prov['note']}")
    print()
    provider_choice = input("   请选择 [1/2/3/4] (默认: 2 硅基流动): ").strip()
    if provider_choice not in PRESET_PROVIDERS:
        provider_choice = "2"
    provider = PRESET_PROVIDERS[provider_choice]
    print(f"   → 已选: {provider['name']}")
    print()

    # 4. API Key
    print("━" * 50)
    print(f"4. {provider['name']} API Key：")
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

    # 5. API Base URL（仅自定义模式）
    if provider_choice == "4":
        print("━" * 50)
        print("5. API 端点 URL（例如 https://api.example.com/v1）：")
        print()
        base_url = input("   > ").strip()
        while not base_url:
            print("   ⚠ 端点 URL 不能为空：")
            base_url = input("   > ").strip()
    else:
        base_url = provider["base_url"]
    print()

    # 6. 模型名称
    print("━" * 50)
    default_model = provider["default_model"]
    print(f"6. 模型名称（默认: {default_model}）：")
    print()
    model_name = input("   > ").strip()
    if not model_name:
        model_name = default_model
    print(f"   → 模型: {model_name}")
    print()

    # 7. 生成模式
    print("━" * 50)
    print("7. 生成模式：")
    print("   [1] 从头开始生成（完整流水线）")
    print("   [2] 继续上次生成（从 state.json 恢复）")
    print()
    mode_choice = input("   请选择 [1/2] (默认: 1): ").strip()
    mode = "from_scratch" if mode_choice != "2" else "resume"

    # 检查继续模式是否有 state
    if mode == "resume":
        state_file = OUTPUT_DIR / "state.json"
        if not state_file.exists():
            print("   ⚠ 未找到 state.json，将从头开始生成")
            mode = "from_scratch"

    print(f"   → 模式: {'从头开始' if mode == 'from_scratch' else '继续上次'}")
    print()

    # 构建配置
    config_data = {
        "story_summary": story,
        "total_chapters": total_chapters,
        "api_base_url": base_url.rstrip("/"),
        "api_key": api_key,
        "model_name": model_name,
        "api_interval_seconds": 4,
        "mode": mode,
        "provider": provider["name"],
        "started_at": "",  # 在 pipeline 启动时填入
    }

    return config_data


def confirm_and_start(config_data: dict):
    """展示配置摘要，确认后启动流水线。"""
    print()
    print("=" * 65)
    print("  配置摘要")
    print("=" * 65)
    print(f"  故事梗概:      {config_data['story_summary'][:60]}...")
    print(f"  总章节数:      {config_data['total_chapters']} 章")
    print(f"  提供商:        {config_data['provider']}")
    print(f"  API 端点:      {config_data['api_base_url']}")
    print(f"  模型:          {config_data['model_name']}")
    print(f"  API 间隔:      {config_data['api_interval_seconds']} 秒")
    print(f"  生成模式:      {'从头开始' if config_data['mode'] == 'from_scratch' else '继续上次'}")
    print("=" * 65)
    print()

    confirm = input("  确认以上信息无误？按 Enter 开始生成，输入 q 退出: ").strip()
    if confirm.lower() == "q":
        print("  已取消。")
        sys.exit(0)

    # 保存配置
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    from datetime import datetime
    config_data["started_at"] = datetime.now().isoformat()
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