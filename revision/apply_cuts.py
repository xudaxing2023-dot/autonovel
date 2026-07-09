#!/usr/bin/env python3
"""
revision/apply_cuts.py — 应用机械裁剪

根据 edit_logs 中对抗性编辑产出的结构化 cuts.json，
精确匹配章节原文并删除指定段落。

对齐原版 autonovel-原版/apply_cuts.py (270行)，
适配中文：字符计数、中文字符级 MIN_QUOTE_LEN、SLOP 类型。

用法:
  python apply_cuts.py all                                   # 全章节
  python apply_cuts.py 5                                     # 第 5 章
  python apply_cuts.py all --types OVER-EXPLAIN REDUNDANT    # 按类型过滤
  python apply_cuts.py all --min-fat 17                      # 赘语阈值
"""

import json
import re
import sys
from pathlib import Path

from core.config import CHAPTERS_DIR, EDIT_LOGS_DIR
from core.state_manager import step

VALID_TYPES = {"FAT", "REDUNDANT", "OVER-EXPLAIN", "TELL", "SLOP", "STRUCTURAL", "GENERIC"}
MIN_QUOTE_LEN = 20  # 中文字符


# =============================================================================
# 辅助函数
# =============================================================================

def char_count(text: str) -> int:
    """中文字符计数（去掉空白和换行）。"""
    return len(text.replace(" ", "").replace("\n", "").replace("\r", ""))


def load_cuts(chapter_num: int) -> dict | None:
    """加载单章裁剪清单 JSON。返回 None 表示文件不存在或解析失败。"""
    cuts_file = EDIT_LOGS_DIR / f"ch{chapter_num:02d}_cuts.json"
    if not cuts_file.exists():
        return None
    try:
        return json.loads(cuts_file.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError) as exc:
        step(f"  ⚠ 解析失败 {cuts_file.name}: {exc}")
        return None


def chapter_path(chapter_num: int) -> Path:
    """构造章节文件路径。"""
    return CHAPTERS_DIR / f"ch_{chapter_num:02d}.md"


def find_and_remove(text: str, quote: str) -> tuple[str, bool, str]:
    """在 text 中查找并删除 quote。

    两层匹配策略：
      1. 精确子串匹配（必须唯一）
      2. 空白标准化回退（合并连续空白后正则匹配）

    返回 (新文本, 成功与否, 失败原因)。
    """
    if not quote or not quote.strip():
        return text, False, "空引用"

    # 第1层：精确子串匹配
    count = text.count(quote)
    if count == 1:
        text = text.replace(quote, "", 1)
        return text, True, ""
    if count > 1:
        return text, False, f"歧义 ({count} 处匹配)"

    # 第2层：空白标准化回退
    ws = re.compile(r"\s+")
    norm_quote = ws.sub(" ", quote).strip()
    if len(norm_quote) < MIN_QUOTE_LEN:
        return text, False, "标准化后引用过短"

    tokens = norm_quote.split()
    if not tokens:
        return text, False, "标准化后无有效词"

    pattern = r"\s+".join(re.escape(t) for t in tokens)
    matches = list(re.finditer(pattern, text))
    if len(matches) == 1:
        m = matches[0]
        text = text[:m.start()] + text[m.end():]
        return text, True, ""
    if len(matches) > 1:
        return text, False, f"标准化后歧义 ({len(matches)} 处匹配)"

    return text, False, "未找到"


def collapse_blank_lines(text: str) -> str:
    """合并 3 个及以上连续空行为 2 个（即保留一个空行）。"""
    return re.sub(r"\n{3,}", "\n\n", text)


def discover_chapters() -> list[int]:
    """扫描 edit_logs/ 下所有有 cuts.json 文件的章节号。"""
    nums = set()
    for p in EDIT_LOGS_DIR.glob("ch*_cuts.json"):
        m = re.match(r"ch(\d+)_cuts\.json", p.name)
        if m:
            nums.add(int(m.group(1)))
    return sorted(nums)


# =============================================================================
# 逐章处理
# =============================================================================

def process_chapter(
    chapter_num: int,
    type_filter: set | None,
    min_fat: int,
    dry_run: bool = False,
) -> dict:
    """逐章处理裁剪。

    Args:
        chapter_num: 章节号
        type_filter: 允许裁剪的类型集合（None = 全部类型）
        min_fat: 赘语比例阈值（低于此值跳过该章）
        dry_run: True 时只统计不修改文件

    Returns:
        {"applied": N, "failed": N, "skipped": N, "chars_removed": N, "error": str|None}
    """
    stats = {
        "applied": 0, "failed": 0, "skipped": 0,
        "chars_removed": 0, "error": None,
    }

    # 加载裁剪清单
    data = load_cuts(chapter_num)
    if data is None:
        stats["error"] = "无裁剪文件"
        return stats

    # 检查赘语比例阈值
    fat_pct = data.get("overall_fat_percentage", 0)
    if fat_pct < min_fat:
        stats["error"] = f"赘语比例 {fat_pct}% < 阈值 {min_fat}%"
        return stats

    cuts = data.get("cuts", [])
    if not cuts:
        stats["error"] = "裁剪清单无条目"
        return stats

    # 加载章节文本
    ch_path = chapter_path(chapter_num)
    if not ch_path.exists():
        stats["error"] = f"章节文件不存在: {ch_path.name}"
        return stats

    text = ch_path.read_text(encoding="utf-8-sig")
    original_chars = char_count(text)

    # 逐个处理裁剪条目
    for cut in cuts:
        quote = cut.get("quote", "")
        cut_type = cut.get("type", "UNKNOWN")
        reason = cut.get("reason", "")

        # 类型过滤
        if type_filter and cut_type not in type_filter:
            stats["skipped"] += 1
            continue

        # 跳过过短引用
        if len(quote.strip()) < MIN_QUOTE_LEN:
            stats["skipped"] += 1
            continue

        # dry-run 模式：只统计不修改
        if dry_run:
            stats["applied"] += 1
            stats["chars_removed"] += char_count(quote)
            continue

        # 执行删除
        new_text, success, fail_reason = find_and_remove(text, quote)
        if success:
            removed = char_count(quote)
            stats["applied"] += 1
            stats["chars_removed"] += removed
            text = new_text
        else:
            stats["failed"] += 1
            preview = quote[:60].replace("\n", " ")
            step(f"    FAIL [{cut_type}] {fail_reason}: {preview}...")

    # 写回文件
    if not dry_run and stats["applied"] > 0:
        text = collapse_blank_lines(text)
        ch_path.write_text(text, encoding="utf-8")
        new_chars = char_count(text)
        step(f"  ch{chapter_num:02d}: {original_chars} → {new_chars} 字 "
             f"(-{stats['chars_removed']} 字)")

    return stats


# =============================================================================
# 主编排（兼容 pipeline_orchestrator 接口）
# =============================================================================

def run_apply_cuts(
    target: str = "all",
    types: list = None,
    min_fat: int = 15,
) -> None:
    """应用机械裁剪。

    对 pipeline_orchestrator.py 的兼容接口，
    两处调用点：Phase 3 Step 2（全章节）、Phase 3b（单章）。

    Args:
        target: "all" 或章节号字符串（如 "5"）
        types: 裁剪类型列表，默认 ["OVER-EXPLAIN", "REDUNDANT"]
        min_fat: 赘语比例阈值（百分比），低于此值的章节跳过
    """
    if types is None:
        types = ["OVER-EXPLAIN", "REDUNDANT"]

    type_filter = set(types)
    step(f"机械裁剪: 类型={types}, 赘语阈值≥{min_fat}%")

    # 确定待处理章节
    if target == "all":
        chapters = discover_chapters()
        if not chapters:
            step("  无裁剪文件，跳过")
            return
    else:
        try:
            chapters = [int(target)]
        except ValueError:
            step(f"  无效章节号: {target}")
            return

    # 汇总统计
    totals = {"applied": 0, "failed": 0, "skipped": 0, "chars_removed": 0}

    for ch_num in chapters:
        stats = process_chapter(ch_num, type_filter, min_fat, dry_run=False)
        if stats["error"]:
            step(f"  ch{ch_num:02d}: {stats['error']}")
        for k in totals:
            totals[k] += stats[k]

    step(f"机械裁剪完成: 应用 {totals['applied']}, "
         f"失败 {totals['failed']}, 跳过 {totals['skipped']}, "
         f"删除约 {totals['chars_removed']} 字")


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "all"
    run_apply_cuts(target)
