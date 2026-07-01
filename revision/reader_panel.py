#!/usr/bin/env python3
"""
revision/reader_panel.py — 读者评审团（整本评审，对齐原版）

4 位读者各独立评审整本小说，产出结构化 JSON，
找出读者分歧作为共识修订驱动源。

对齐原版 autonovel-原版/reader_panel.py (245行):
  整本 arc_summary → 4 位读者各评审一次 → find_disagreements → 保存 JSON

用法: python reader_panel.py
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

from core.config import config, CHAPTERS_DIR, EDIT_LOGS_DIR
from core.api_client import call_judge, call_writer
from core.state_manager import step
from prompts.reader_panel_prompts import READER_ROLES, build_novel_reader_prompt


# =============================================================================
# JSON 解析（三级回退）
# =============================================================================

def _parse_json_response(text: str) -> dict:
    """从 LLM 响应中提取 JSON 对象。"""
    if not text or not text.strip():
        return {}

    text = text.strip()

    if text.startswith("```"):
        text = re.sub(r'^```\w*\n?', '', text)
        text = re.sub(r'\n?```$', '', text)
        text = text.strip()

    start = text.find('{')
    if start == -1:
        start = text.find('[')
    if start == -1:
        return {}

    try:
        return json.loads(text[start:], strict=False)
    except json.JSONDecodeError:
        pass

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

    try:
        return json.loads(text[start:], strict=False)
    except json.JSONDecodeError:
        return {}


# =============================================================================
# 构建整本小说摘要（对齐原版 build_arc_summary.py）
# =============================================================================

def _build_arc_summary(chapter_files: list) -> str:
    """构建整本小说的逐章摘要。

    完全对齐原版 build_arc_summary.py (113行) 的 arc_summary.md 格式:
      — 小说前提
      — 每章: LLM 3 句话摘要 + 开头 500 字 + 结尾 500 字 + 最长 3 句对话 + 字数统计
    """
    cfg = config
    cfg.load()
    premise = cfg.story_summary

    parts = [f"# 小说前提\n{premise}\n\n---"]

    summary_system = (
        "你精确地总结小说章节。只陈述：发生了什么、什么改变了、"
        "留下了什么未解的问题。不评价。不赞扬。只陈述事件和转变。"
    )

    for cf in sorted(chapter_files):
        text = cf.read_text(encoding="utf-8")
        ch_num = int(cf.stem.split("_")[1])
        chars = len(text.replace(" ", "").replace("\n", ""))

        # LLM 3 句话摘要
        try:
            summary = call_writer(
                f"用恰好 3 句话总结本章。发生了什么、什么改变了、"
                f"什么未解问题留下。\n\n第 {ch_num} 章:\n{text[:5000]}",
                system=summary_system,
                max_tokens=200,
            )
        except Exception:
            summary = "(摘要生成失败)"

        head = text[:500]
        tail = text[-500:] if len(text) > 1000 else ""

        # 提取最长 3 句对话
        dialogue = re.findall(r'["「]([^"」]{15,})["」]', text)
        dialogue.sort(key=len, reverse=True)
        top_dialogue = dialogue[:3]

        entry = f"### 第 {ch_num} 章 ({chars} 字)\n"
        entry += f"**摘要:** {summary.strip()}\n\n"
        entry += f"**开头:** {head}...\n\n"
        if tail:
            entry += f"**结尾:** ...{tail}\n\n"
        if top_dialogue:
            entry += "**关键对话:**\n"
            for d in top_dialogue:
                entry += f'> "{d}"\n\n'
        parts.append(entry)

        step(f"  第 {ch_num} 章: 摘要 ({chars} 字)")

    result = "\n---\n\n".join(parts)
    step(f"小说摘要已构建: {len(chapter_files)} 章, {len(result)} 字")
    return result


# =============================================================================
# disagreements 检测（对齐原版 find_disagreements）
# =============================================================================

def _find_disagreements_structured(
    results: dict,
    chapter_list: list,
) -> list:
    """从结构化评审结果中找出读者分歧。

    对齐原版 find_disagreements(): 对每个 question，
    收集每个读者提及的章节号，找出部分标记的章节。
    """
    question_keys = [
        "momentum_loss", "cut_candidate", "thinnest_character", "worst_scene",
    ]
    disagreements: list = []

    for question in question_keys:
        chapters_mentioned: dict[str, set] = {}
        for reader_key, answers in results.items():
            text = answers.get(question, "")
            if not text:
                chapters_mentioned[reader_key] = set()
                continue
            chs = set()
            for m in re.finditer(
                r'(?:第\s*(\d+)\s*章|Ch\.?\s*(\d+)|Chapter\s+(\d+))',
                text, re.IGNORECASE,
            ):
                num = int(m.group(1) or m.group(2) or m.group(3))
                if num in chapter_list:
                    chs.add(num)
            chapters_mentioned[reader_key] = chs

        all_chs: set = set()
        for chs in chapters_mentioned.values():
            all_chs.update(chs)

        for ch in all_chs:
            flagged_by = [r for r, chs in chapters_mentioned.items() if ch in chs]
            not_flagged = [r for r, chs in chapters_mentioned.items() if ch not in chs]
            if flagged_by and not_flagged:
                disagreements.append({
                    "question": question,
                    "chapter": ch,
                    "flagged_by": flagged_by,
                    "not_flagged": not_flagged,
                })

    return disagreements


# =============================================================================
# 主编排函数
# =============================================================================

def run_reader_panel(
    max_tokens: int = 4096,
    retries: int = 3,
    max_total_time: int = None,
) -> None:
    """运行读者评审团。

    对齐原版 main(): 构建摘要 → 4 位读者各评审一次 → 找分歧 → 保存。
    """
    EDIT_LOGS_DIR.mkdir(parents=True, exist_ok=True)

    chapter_files = sorted(CHAPTERS_DIR.glob("ch_*.md"))
    if not chapter_files:
        step("无章节文件，跳过读者评审")
        return

    chapter_nums = [int(cf.stem.split("_")[1]) for cf in chapter_files]
    total = len(chapter_files)

    # 1. 构建整本小说摘要
    novel_summary = _build_arc_summary(chapter_files)

    step(f"读者评审团: {len(READER_ROLES)} 位读者评审整本小说 ({total} 章) ...")

    # 2. 每位读者评审一次整本小说（共 4 次 API 调用）
    results = {}
    for role_key, role_info in READER_ROLES.items():
        step(f"  {role_info['name']} 评审中 ...")
        prompt = build_novel_reader_prompt(novel_summary, total, role_info)
        try:
            response = call_judge(
                prompt,
                system=role_info["system"],
                max_tokens=max_tokens,
                retries=retries,
                max_total_time=max_total_time,
            )
            parsed = _parse_json_response(response)
            results[role_key] = parsed
            step(f"  {role_info['name']} 评审完成 ✓ ({len(parsed)} 字段)")
        except Exception as e:
            step(f"  {role_info['name']} 评审失败: {e}")
            results[role_key] = {}

    # 3. 找分歧
    disagreements = _find_disagreements_structured(results, chapter_nums)

    # 4. 保存
    panel_data = {
        "timestamp": datetime.now().isoformat(),
        "readers": results,
        "disagreements": disagreements,
    }
    log_path = EDIT_LOGS_DIR / "reader_panel.json"
    log_path.write_text(
        json.dumps(panel_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    step(f"读者评审完成: {len(disagreements)} 个分歧")
    for d in disagreements:
        step(f"  第 {d['chapter']} 章 [{d['question']}]: "
             f"{len(d['flagged_by'])}/{len(READER_ROLES)} 位读者标记 "
             f"({', '.join(d['flagged_by'])})")


if __name__ == "__main__":
    run_reader_panel()
