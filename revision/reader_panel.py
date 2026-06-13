#!/usr/bin/env python3
"""
revision/reader_panel.py — 读者评审团

4 种读者角色分别评审全部章节，汇总共识问题。
"""

import json
import sys
from datetime import datetime
from pathlib import Path

from core.config import CHAPTERS_DIR, EDIT_LOGS_DIR
from core.api_client import call_judge
from core.state_manager import step
from prompts.reader_panel_prompts import READER_ROLES, READER_SYSTEM_PROMPT, build_reader_panel_prompt


def run_reader_panel(
    max_tokens: int = 4096,
    retries: int = 3,
    max_total_time: int = None,
) -> None:
    """运行读者评审团。"""
    EDIT_LOGS_DIR.mkdir(parents=True, exist_ok=True)

    chapter_files = sorted(CHAPTERS_DIR.glob("ch_*.md"))
    if not chapter_files:
        step("无章节文件，跳过读者评审")
        return

    # 限制评审章节数量，避免 API 开销过大
    max_chapters_to_review = min(len(chapter_files), 8)
    selected = chapter_files[:max_chapters_to_review]
    total_reviews = len(READER_ROLES) * len(selected)

    step(f"读者评审团: {len(READER_ROLES)} 位读者 × {len(selected)} 章 (共 {total_reviews} 次评审) ...")

    panel_data = {
        "timestamp": datetime.now().isoformat(),
        "readers": {},
        "disagreements": [],
    }

    review_count = 0
    for role_key, role_info in READER_ROLES.items():
        step(f"  {role_info['name']} 评审中 ...")
        reader_answers = {}

        for ch_file in selected:
            ch_num = int(ch_file.stem.split("_")[1])
            ch_text = ch_file.read_text(encoding="utf-8")

            prompt = build_reader_panel_prompt(ch_num, ch_text, reader_role=role_info)

            try:
                response = call_judge(
                    prompt, system=READER_SYSTEM_PROMPT, max_tokens=max_tokens,
                    retries=retries, max_total_time=max_total_time,
                )
            except Exception as e:
                step(f"    第 {ch_num} 章评审失败: {e}")
                response = f"(评审失败: {e})"

            reader_answers[f"ch{ch_num:02d}"] = {
                "chapter": ch_num,
                "response": response,
            }

        panel_data["readers"][role_key] = reader_answers
        step(f"  {role_info['name']} 评审完成 ✓")

    # 找出被多位读者共同标记的章节
    disagreements = []
    for ch_file in selected:
        ch_num = int(ch_file.stem.split("_")[1])
        flagged_by = []
        for role_key, answers in panel_data["readers"].items():
            key = f"ch{ch_num:02d}"
            if key in answers:
                resp = answers[key].get("response", "").lower()
                # 检测负面信号
                negative_markers = ["薄弱", "拖沓", "跳跃", "说教", "过度解释",
                                   "AI 痕迹", "套话", "不自然", "出戏", "逻辑矛盾"]
                if any(m in resp for m in negative_markers):
                    flagged_by.append(role_key)

        if len(flagged_by) >= 2:
            disagreements.append({
                "chapter": ch_num,
                "flagged_by": flagged_by,
                "count": len(flagged_by),
                "question": "共识问题",
            })

    panel_data["disagreements"] = disagreements

    log_path = EDIT_LOGS_DIR / "reader_panel.json"
    log_path.write_text(json.dumps(panel_data, ensure_ascii=False, indent=2), encoding="utf-8")

    step(f"读者评审完成: {len(disagreements)} 个共识问题")
    for d in disagreements:
        step(f"  第 {d['chapter']} 章: {d['count']} 位读者标记 ({', '.join(d['flagged_by'])})")


if __name__ == "__main__":
    run_reader_panel()