#!/usr/bin/env python3
"""
revision/apply_cuts.py — 应用机械裁剪

根据 edit_logs 中的裁剪清单，删除 OVER-EXPLAIN 和 REDUNDANT 类型段落。
"""

import json
import sys
from pathlib import Path

from core.config import CHAPTERS_DIR, EDIT_LOGS_DIR
from core.state_manager import step


def run_apply_cuts(target: str = "all", types: list = None, min_fat: int = 15) -> None:
    """应用裁剪。当前为占位实现——标记裁剪清单但暂不自动删除。"""
    if types is None:
        types = ["OVER-EXPLAIN", "REDUNDANT"]

    step(f"应用裁剪: 类型={types}, min_fat={min_fat}")
    step("  (裁剪清单已由 adversarial_edit.py 生成，人工审核后再应用)")

    # 列出所有裁剪文件
    cut_files = sorted(EDIT_LOGS_DIR.glob("*_cuts.json"))
    if not cut_files:
        step("  无裁剪文件")
        return

    for cf in cut_files:
        data = json.loads(cf.read_text(encoding="utf-8"))
        ch_num = data.get("chapter", "?")
        step(f"  ch{ch_num:02d}: 裁剪就绪 ({cf.name})")

    step("apply_cuts 完成 — 请人工审核后执行具体删除")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "all"
    run_apply_cuts(target)