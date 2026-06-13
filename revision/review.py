#!/usr/bin/env python3
"""
revision/review.py — 深度审阅（替代原 Opus 审阅）

将全部手稿提交给裁判模型，产出结构化审阅报告和星级评分。
"""

import json
import sys
from datetime import datetime
from pathlib import Path

from core.config import OUTPUT_DIR, CHAPTERS_DIR, EDIT_LOGS_DIR, BRIEFS_DIR, config
from core.api_client import call_judge
from core.state_manager import step, banner
from prompts.review_prompts import build_review_prompt, REVIEW_SYSTEM_PROMPT


def run_review_loop(
    state: dict = None,
    max_tokens: int = 8192,
    max_rounds: int = 4,
    retries: int = 3,
    max_total_time: int = None,
) -> None:
    """运行深度审阅循环。"""
    banner("深度审阅循环", "-")

    chapter_files = sorted(CHAPTERS_DIR.glob("ch_*.md"))
    if not chapter_files:
        step("无章节文件，跳过深度审阅")
        return

    manuscript = "\n\n---\n\n".join(
        f.read_text(encoding="utf-8") for f in chapter_files
    )
    outline_path = OUTPUT_DIR / "outline.md"
    outline = outline_path.read_text(encoding="utf-8") if outline_path.exists() else ""

    EDIT_LOGS_DIR.mkdir(parents=True, exist_ok=True)

    for rnd in range(1, max_rounds + 1):
        banner(f"审阅回合 {rnd}/{max_rounds}", ".")

        step("提交手稿给裁判模型审阅 ...")
        prompt = build_review_prompt(manuscript, outline_text=outline)

        try:
            result = call_judge(
                prompt, system=REVIEW_SYSTEM_PROMPT, max_tokens=max_tokens,
                retries=retries, max_total_time=max_total_time,
            )
        except Exception as e:
            step(f"审阅失败: {e}")
            break

        # 保存审阅报告
        review_path = EDIT_LOGS_DIR / f"review_round{rnd}.md"
        review_path.write_text(result, encoding="utf-8")

        # 解析星级
        stars = 0
        for line in result.splitlines():
            if "★" in line and ("评分" in line or "总" in line or "overall" in line.lower()):
                stars = line.count("★")
                break

        # 解析问题数
        major_items = result.count("MAJOR") + result.count("严重") + result.count("必须")
        total_items = result.count("问题") + result.count("建议")

        # 保存结构化 JSON
        review_json = {
            "round": rnd,
            "timestamp": datetime.now().isoformat(),
            "stars": stars,
            "total_items": total_items,
            "major_items": major_items,
            "qualified_items": max(0, total_items - major_items),
            "raw_review": result,
        }
        json_path = EDIT_LOGS_DIR / f"review_round{rnd}.json"
        json_path.write_text(json.dumps(review_json, ensure_ascii=False, indent=2), encoding="utf-8")

        step(f"审阅结果: ★{'★' * stars}, "
             f"{total_items} 项 ({major_items} 严重)")

        # 停止条件
        if stars >= 4.5 and major_items == 0:
            step("★★★★½ 且无严重问题 — 小说已就绪！")
            break
        if stars >= 4 and total_items > 0 and (total_items - major_items) / max(total_items, 1) > 0.5:
            step(f"★{'★' * stars} 且多数问题可接受 — 小说已就绪！")
            break

    banner("深度审阅完成")


if __name__ == "__main__":
    run_review_loop()