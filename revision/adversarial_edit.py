#!/usr/bin/env python3
"""
revision/adversarial_edit.py — 对抗性编辑

对章节执行「削减 N 字」裁判，产出分类裁剪清单。
用法: python adversarial_edit.py all        # 全章节
       python adversarial_edit.py 5          # 第 5 章
"""

import json
import sys
from datetime import datetime
from pathlib import Path

from core.config import OUTPUT_DIR, CHAPTERS_DIR, EDIT_LOGS_DIR
from core.api_client import call_judge
from core.state_manager import step
from prompts.adversarial_prompts import build_adversarial_prompt, ADVERSARIAL_SYSTEM_PROMPT


def run_adversarial_edit(
    target: str = "all",
    max_tokens: int = 4096,
    retries: int = 3,
    max_total_time: int = None,
) -> None:
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
            prompt, system=ADVERSARIAL_SYSTEM_PROMPT, max_tokens=max_tokens,
            retries=retries, max_total_time=max_total_time,
        )

        cuts_path = EDIT_LOGS_DIR / f"ch{ch_num:02d}_cuts.json"
        cuts_data = {
            "chapter": ch_num,
            "timestamp": datetime.now().isoformat(),
            "raw_output": result,
        }
        cuts_path.write_text(json.dumps(cuts_data, ensure_ascii=False, indent=2), encoding="utf-8")
        step(f"对抗性编辑 第 {ch_num} 章 完成 ✓ (编辑清单: {cuts_path})")

    step("对抗性编辑全部完成 ✓")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "all"
    run_adversarial_edit(target)