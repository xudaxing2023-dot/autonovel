#!/usr/bin/env python3
"""
revision/adversarial_edit.py — 对抗性编辑

对章节执行「削减 N 字」裁判，产出分类裁剪清单。
用法: python adversarial_edit.py all        # 全章节
       python adversarial_edit.py 5          # 第 5 章
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

from core.config import OUTPUT_DIR, CHAPTERS_DIR, EDIT_LOGS_DIR
from core.api_client import call_judge
from core.state_manager import step
from prompts.adversarial_prompts import build_adversarial_prompt, ADVERSARIAL_SYSTEM_PROMPT


def _parse_json_response(text: str) -> dict:
    """从 LLM 响应中提取 JSON 对象。

    三级回退策略：
      1. 剥除 ```json ... ``` markdown 代码块 → json.loads()
      2. 从首个 { 或 [ 开始直接 json.loads()
      3. 花括号深度匹配（处理 LLM 在 JSON 后追加额外文本的情况）

    返回解析出的 dict；解析失败返回空 dict。
    """
    if not text or not text.strip():
        return {}

    text = text.strip()

    # 第1层：剥除 markdown 代码块标记
    if text.startswith("```"):
        text = re.sub(r'^```\w*\n?', '', text)
        text = re.sub(r'\n?```$', '', text)
        text = text.strip()

    # 第2层：从第一个 { 或 [ 开始尝试直接解析
    start = text.find('{')
    if start == -1:
        start = text.find('[')
    if start == -1:
        step(f"  ⚠ JSON 解析失败: 响应中未找到 {{ 或 [")
        return {}

    try:
        return json.loads(text[start:], strict=False)
    except json.JSONDecodeError:
        pass  # 回退到深度匹配

    # 第3层：花括号/方括号深度匹配
    depth = 0
    in_string = False
    escape = False
    open_char = text[start]
    close_char = '}' if open_char == '{' else ']'

    for i in range(start, len(text)):
        c = text[i]
        if escape:
            escape = False
            continue
        if c == '\\' and in_string:
            escape = True
            continue
        if c == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == open_char:
            depth += 1
        elif c == close_char:
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1], strict=False)
                except json.JSONDecodeError:
                    break

    # 最终尝试宽松解析
    try:
        return json.loads(text[start:], strict=False)
    except json.JSONDecodeError:
        step(f"  ⚠ JSON 解析失败: 所有回退策略均失败，响应前200字: {text[:200]}")
        return {}


def run_adversarial_edit(
    target: str = "all",
    retries: int = 3,
    max_total_time: int = None) -> None:
    """运行对抗性编辑。"""
    EDIT_LOGS_DIR.mkdir(parents=True, exist_ok=True)

    if target == "all":
        chapter_files = sorted(CHAPTERS_DIR.glob("ch_*.md"))
    else:
        ch_num = int(target)
        ch_file = CHAPTERS_DIR / f"ch_{ch_num:02d}.md"
        chapter_files = [ch_file] if ch_file.exists() else []

    if not chapter_files:
        step("无章节文件可供编辑")
        return

    total_chapters = len(chapter_files)
    for idx, ch_file in enumerate(chapter_files, 1):
        ch_text = ch_file.read_text(encoding="utf-8")
        ch_num = int(ch_file.stem.split("_")[1])

        step(f"对抗性编辑 第 {ch_num} 章 ({idx}/{total_chapters}) ...")
        prompt = build_adversarial_prompt(ch_text, cut_target=300)

        result = call_judge(
            prompt, system=ADVERSARIAL_SYSTEM_PROMPT,
            retries=retries, max_total_time=max_total_time)

        # 解析 JSON 响应
        parsed = _parse_json_response(result)

        cuts_path = EDIT_LOGS_DIR / f"ch{ch_num:02d}_cuts.json"

        # 构建结构化数据：展开 parsed 的所有字段到顶层
        cuts_data = {
            "chapter": ch_num,
            "timestamp": datetime.now().isoformat(),
            "raw_output": result,  # 保留原始响应用于调试
        }
        if parsed:
            cuts_data.update(parsed)  # 展开 cuts, total_cuttable_words, 等
            cut_count = len(parsed.get("cuts", []))
            fat_pct = parsed.get("overall_fat_percentage", "?")
            step(f"对抗性编辑 第 {ch_num} 章: "
                 f"发现 {cut_count} 处可删改, 赘语比例 {fat_pct}%")
        else:
            step(f"对抗性编辑 第 {ch_num} 章: JSON 解析失败，仅保存原始响应")

        cuts_path.write_text(
            json.dumps(cuts_data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        step(f"对抗性编辑 第 {ch_num} 章 完成 ✓ (编辑清单: {cuts_path})")

    step("对抗性编辑全部完成 ✓")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "all"
    run_adversarial_edit(target)