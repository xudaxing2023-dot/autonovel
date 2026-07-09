#!/usr/bin/env python3
"""
revision/compare_chapters.py — Elo 章节锦标赛

两两对比章节，用 LLM 裁判判定胜负，构建 Elo 排名。
"""
import json
import sys
import random
from datetime import datetime
from pathlib import Path

from core.config import CHAPTERS_DIR, EDIT_LOGS_DIR
from core.api_client import call_judge
from core.state_manager import step


COMPARE_SYSTEM_PROMPT = """你是一位公正的文学裁判。你会同时阅读两段小说章节并判定哪一段更优秀。
你只基于文字品质、节奏、情感效果来评判——不基于内容偏好。
你的回答格式必须是: WINNER: A 或 WINNER: B，然后附一句话简短理由。"""


def run_compare_chapters() -> None:
    """运行章节 Elo 锦标赛。"""
    EDIT_LOGS_DIR.mkdir(parents=True, exist_ok=True)

    chapter_files = sorted(CHAPTERS_DIR.glob("ch_*.md"))
    if len(chapter_files) < 2:
        step("章节数不足 2，跳过锦标赛")
        return

    # 简易 Elo 初始化
    elo = {f.stem: 1000 for f in chapter_files}
    K = 32

    # 随机配对，每对比较一次
    pairs = []
    stems = list(elo.keys())
    random.shuffle(stems)
    for i in range(0, len(stems) - 1, 2):
        pairs.append((stems[i], stems[i + 1]))

    if not pairs:
        step("无法配对，跳过锦标赛")
        return

    step(f"Elo 锦标赛: {len(pairs)} 对比较 ...")

    results = []
    for a_stem, b_stem in pairs:
        a_path = CHAPTERS_DIR / f"{a_stem}.md"
        b_path = CHAPTERS_DIR / f"{b_stem}.md"

        a_text = a_path.read_text(encoding="utf-8-sig")[:3000]
        b_text = b_path.read_text(encoding="utf-8-sig")[:3000]

        prompt = f"""请判定以下两段章节谁更优秀：

=== 章节 A ===
{a_text}

=== 章节 B ===
{b_text}

请严格只输出: WINNER: A 或 WINNER: B，然后一句话理由。"""

        step(f"  比较: {a_stem} vs {b_stem} ...")
        try:
            result = call_judge(prompt, system=COMPARE_SYSTEM_PROMPT)
        except Exception as e:
            step(f"  比较失败: {e}")
            continue

        if "WINNER: A" in result.upper():
            elo[a_stem] += K
            elo[b_stem] -= K
            winner = a_stem
        elif "WINNER: B" in result.upper():
            elo[a_stem] -= K
            elo[b_stem] += K
            winner = b_stem
        else:
            winner = "undecided"

        results.append({
            "a": a_stem, "b": b_stem, "winner": winner,
            "judge_response": result[:200],
        })

    # 排序
    ranking = sorted(elo.items(), key=lambda x: -x[1])

    tournament_data = {
        "timestamp": datetime.now().isoformat(),
        "pairs_compared": len(pairs),
        "ranking": [{"chapter": k, "elo": v} for k, v in ranking],
        "results": results,
    }

    log_path = EDIT_LOGS_DIR / "tournament_results.json"
    log_path.write_text(json.dumps(tournament_data, ensure_ascii=False, indent=2), encoding="utf-8")

    step(f"Elo 锦标赛完成:")
    for ch, score in ranking[:5]:
        step(f"  #{ranking.index((ch, score))+1}: {ch} ({score})")


if __name__ == "__main__":
    run_compare_chapters()