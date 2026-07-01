#!/usr/bin/env python3
"""
revision/gen_brief.py — 修订摘要生成器（中文重构版）

从评审团反馈、评估结果、对抗性编辑三源交叉引用，
为最需要修订的章节生成结构化修订摘要。

用法:
  python revision/gen_brief.py --panel 12    # 评审团反馈摘要
  python revision/gen_brief.py --eval 12     # 评估结果摘要
  python revision/gen_brief.py --cuts 12     # 对抗性编辑摘要
  python revision/gen_brief.py --auto        # 自动选择最弱章节 + 三源合并
  python revision/gen_brief.py --dry-run     # 仅输出到 stdout，不保存

架构对齐英文原版 gen_brief.py (854 行):
  辅助函数 → panel_mentions_for_chapter() → 四种 build_*_brief()
  → build_auto_brief() 三源交叉引用 → CLI
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional

from core.config import OUTPUT_DIR, CHAPTERS_DIR, BRIEFS_DIR, EDIT_LOGS_DIR, EVAL_LOGS_DIR
from core.state_manager import step

# voice.md 路径
VOICE_PATH = OUTPUT_DIR / "voice.md"


# =============================================================================
# 辅助函数
# =============================================================================

def load_json(path: Path) -> dict:
    """加载 JSON 文件，文件不存在时退出报错。"""
    if not path.exists():
        sys.exit(f"错误: JSON 文件不存在: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def chapter_path(ch: int) -> Path:
    """构造章节文件路径。"""
    return CHAPTERS_DIR / f"ch_{ch:02d}.md"


def chapter_text(ch: int) -> str:
    """读取章节全文。"""
    p = chapter_path(ch)
    if not p.exists():
        sys.exit(f"错误: 章节文件不存在: {p}")
    return p.read_text(encoding="utf-8")


def chapter_title(text: str) -> str:
    """从 Markdown 首行提取章节标题。

    支持格式:
      # 第3章 标题
      # Chapter 3: Title
      # 第三章 标题
    """
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#"):
            # 去掉开头的 # 号
            title = re.sub(r"^#+\s*", "", line)
            # 去掉中文章节号前缀
            title = re.sub(
                r"第\s*[一二三四五六七八九十\d]+章\s*[:：—–-]*\s*",
                "", title
            )
            # 去掉英文章节号前缀
            title = re.sub(
                r"Chapter\s+(\d+|[A-Z][a-z]+(?:-[A-Z][a-z]+)*)\s*[:：—–-]*\s*",
                "", title, flags=re.IGNORECASE
            )
            return title.strip() if title.strip() else "无标题"
    return "无标题"


def word_count(text: str) -> int:
    """中文字符计数（去掉空白后的字符数）。"""
    return len(text.replace(" ", "").replace("\n", "").replace("\r", ""))


def extract_voice_rules() -> list[str]:
    """从 output/voice.md 动态提取核心写作规则。

    不做硬编码——解析 voice.md 中的规则列表：
      Part 1: 「通用写作规则」编号列表 (1-8)
      Part 2: 「本小说文风规则」编号列表 (1-10)
      Part 2: 「文风特征清单」编号列表 (1-8)

    返回规则字符串列表，最多 15 条。
    """
    if not VOICE_PATH.exists():
        return ["(voice.md 未找到)"]

    voice_text = VOICE_PATH.read_text(encoding="utf-8")
    rules: list[str] = []

    # 匹配模式: "1. **规则名**：规则描述" 或 "1. **规则名** — 规则描述"
    # 或 "1. 规则描述（可能跨行）"
    rule_pattern = re.compile(
        r"^\d+\.\s*\*{0,2}(.+?)\*{0,2}\s*[：:—–]\s*(.+)",
        re.MULTILINE
    )

    # 在 Part 1 的「通用写作规则」和 Part 2 的文风规则区域提取
    # 首先定位 "通用写作规则" 和 "文风规则" / "文风特征清单" 区域
    sections_to_extract = [
        r"###?\s*通用写作规则",
        r"###?\s*文风特征清单",
        r"###?\s*本小说文风规则",
    ]

    for section_header in sections_to_extract:
        section_match = re.search(
            section_header + r"\s*\n(.*?)(?=\n#{1,4}\s|\Z)",
            voice_text, re.DOTALL
        )
        if section_match:
            section_text = section_match.group(1)
            for m in rule_pattern.finditer(section_text):
                rule_name = m.group(1).strip()
                rule_desc = m.group(2).strip()
                # 截断过长描述
                if len(rule_desc) > 120:
                    rule_desc = rule_desc[:120] + "…"
                full_rule = f"{rule_name}: {rule_desc}"
                if full_rule not in rules:  # 去重
                    rules.append(full_rule)

    # 如果没有提取到规则，回退到从 Part 1 的 Tier 规则
    if not rules:
        # 提取 Part 1 中 "### 通用写作规则" 后的编号列表
        part1_match = re.search(
            r"###\s*通用写作规则\s*\n(.*?)(?=\n---|\Z)",
            voice_text, re.DOTALL
        )
        if part1_match:
            part1 = part1_match.group(1)
            for line in part1.splitlines():
                line = line.strip()
                if re.match(r"^\d+\.", line):
                    # 去掉编号
                    rule = re.sub(r"^\d+\.\s*", "", line)
                    if len(rule) > 10 and rule not in rules:
                        rules.append(rule[:200])

    if not rules:
        rules.append("(未能从 voice.md 提取规则)")

    # 最多返回 15 条
    return rules[:15]


def latest_full_eval() -> Optional[Path]:
    """查找 eval_logs/ 下最新的 full_*.json。"""
    if not EVAL_LOGS_DIR.exists():
        return None
    fulls = sorted(EVAL_LOGS_DIR.glob("full_*.json"))
    return fulls[-1] if fulls else None


def latest_chapter_eval(ch: int) -> Optional[Path]:
    """查找 eval_logs/ 下最新的单章评估 JSON。"""
    if not EVAL_LOGS_DIR.exists():
        return None
    # 匹配 chapter_{ch:02d}_*.json（evaluate.py 的实际命名规范）
    matches = sorted(EVAL_LOGS_DIR.glob(f"chapter_{ch:02d}_*.json"))
    return matches[-1] if matches else None


def load_panel() -> Optional[dict]:
    """加载评审团 JSON。"""
    p = EDIT_LOGS_DIR / "reader_panel.json"
    if not p.exists():
        return None
    return load_json(p)


def load_cuts(ch: int) -> Optional[dict]:
    """加载对抗性编辑结果 JSON。"""
    p = EDIT_LOGS_DIR / f"ch{ch:02d}_cuts.json"
    if not p.exists():
        return None
    return load_json(p)


# =============================================================================
# 评审团反馈提取 — panel_mentions_for_chapter()
# =============================================================================

def panel_mentions_for_chapter(panel: dict, ch: int) -> dict:
    """从 reader_panel.json 提取指定章节的所有读者反馈。

    按 7 个维度归类:
      momentum_loss, worst_scene, cut_candidate, best_scene,
      thinnest_character, missing_scene, earned_ending

    同时提取 disagreements 中匹配章节的 flagged_issues。

    返回: {"mentions": {...}, "flagged_issues": [...]}
    """
    readers = panel.get("readers", {})
    disagreements = panel.get("disagreements", [])

    mentions: dict[str, list[str]] = {
        "momentum_loss": [],
        "worst_scene": [],
        "cut_candidate": [],
        "best_scene": [],
        "thinnest_character": [],
        "missing_scene": [],
        "earned_ending": [],
    }

    # 中文兼容正则: "第3章" / "Ch.3" / "ch_3" / "Chapter 3"
    ch_re = re.compile(
        rf"\b(?:第\s*{ch}\s*章|Ch\.?\s*{ch}|ch_?\s*{ch}|Chapter\s+{ch})\b",
        re.IGNORECASE
    )

    for reader_name, reader_data in readers.items():
        for key in mentions:
            text = reader_data.get(key, "")
            if not isinstance(text, str):
                continue
            if ch_re.search(text):
                mentions[key].append(f"[{reader_name}] {text}")

    # 提取 disagreements 中匹配章节的 flagged_issues
    flagged_issues: list[str] = []
    for d in disagreements:
        if d.get("chapter") == ch:
            q = d.get("question", "")
            flagged = d.get("flagged_by", [])
            count = len(flagged)
            flagged_issues.append(
                f"{q}: {count}/4 位读者标记 ({', '.join(flagged)})"
            )

    return {
        "mentions": mentions,
        "flagged_issues": flagged_issues,
    }


# =============================================================================
# build_panel_brief() — 评审团反馈摘要 (~170 行逻辑)
# =============================================================================

def build_panel_brief(ch: int) -> str:
    """基于评审团反馈生成修订摘要。"""
    panel = load_panel()
    if panel is None:
        sys.exit("错误: edit_logs/reader_panel.json 未找到")

    text = chapter_text(ch)
    title = chapter_title(text)
    wc = word_count(text)
    info = panel_mentions_for_chapter(panel, ch)
    mentions = info["mentions"]
    flagged = info["flagged_issues"]
    voice_rules = extract_voice_rules()

    # ——— 主导模式分析 ———
    negative_keys = ["momentum_loss", "worst_scene", "cut_candidate"]
    if len(mentions.get("cut_candidate", [])) > 0:
        brief_type = "COMPRESS（压缩）"
    elif len(mentions.get("worst_scene", [])) > 0:
        brief_type = "DRAMATIZE（场景化）"
    elif len(mentions.get("momentum_loss", [])) > 0:
        brief_type = "TIGHTEN（收紧）"
    else:
        brief_type = "REVISE（修订）"

    # ——— 【核心问题】区 ———
    problem_parts: list[str] = []
    if flagged:
        problem_parts.append(
            "评审团对本节的争议标记:\n"
            + "\n".join(f"- {f}" for f in flagged)
        )
    for key in negative_keys:
        if mentions.get(key):
            label_map = {
                "momentum_loss": "节奏拖沓",
                "worst_scene": "最弱场景",
                "cut_candidate": "建议删减",
            }
            problem_parts.append(f"### {label_map.get(key, key)}")
            for m in mentions[key]:
                # 截断过长引用至约 300 中文字符
                if len(m) > 350:
                    m = m[:350] + "…"
                problem_parts.append(m)

    if not problem_parts:
        problem_parts.append(
            f"评审团对第 {ch} 章未提出具体负面反馈。"
            "可结合 --eval 或 --cuts 获取针对性建议。"
        )

    # ——— 【保留项】区 ———
    keep_parts: list[str] = []
    if mentions.get("best_scene"):
        for m in mentions["best_scene"]:
            if len(m) > 350:
                m = m[:350] + "…"
            keep_parts.append(m)

    # 交叉引用 cuts 中的 tightest_passage
    cuts_data = load_cuts(ch)
    if cuts_data and cuts_data.get("tightest_passage"):
        keep_parts.append(
            f'最紧致段落（对抗性编辑）: "{cuts_data["tightest_passage"]}"'
        )

    # 交叉引用 eval 中的 strongest_sentences
    ch_eval_path = latest_chapter_eval(ch)
    if ch_eval_path:
        ch_eval = load_json(ch_eval_path)
        strongest = ch_eval.get("three_strongest_sentences", [])
        if strongest:
            keep_parts.append("最佳句子（评估）:")
            for s in strongest:
                keep_parts.append(f'- "{s}"')

    if not keep_parts:
        keep_parts.append(
            f"(未找到第 {ch} 章的具体保留项。修订前请复查最强段落。)"
        )

    # ——— 【修订项】区 ———
    change_parts: list[str] = []
    change_num = 1

    # 按问题类型生成编号修订建议
    if mentions.get("momentum_loss"):
        change_parts.append(
            f"{change_num}. **节奏**: 解决评审团指出的节奏拖沓问题——"
            "收紧或重组拖沓的场景。"
        )
        change_num += 1

    if mentions.get("worst_scene"):
        for m in mentions["worst_scene"]:
            # 尝试提取中文修改建议引导词
            fix_match = re.search(
                r"(?:修改方案|建议|修复|改进|改写)[:：]\s*(.+)",
                m, re.IGNORECASE | re.DOTALL
            )
            if fix_match:
                fix_text = fix_match.group(1).strip()
                if len(fix_text) > 200:
                    fix_text = fix_text[:200] + "…"
            else:
                # 回退：从读者名后面提取正文
                raw = m.split("]", 1)[-1].strip() if "]" in m else m
                fix_text = (raw[:200] + "…") if len(raw) > 200 else raw
            change_parts.append(f"{change_num}. **场景化**: {fix_text}")
            change_num += 1
            break

    if mentions.get("cut_candidate"):
        change_parts.append(
            f"{change_num}. **压缩**: 评审团认为本章可删减。"
            "将核心节拍压缩到更少字数；删除重复说明。"
        )
        change_num += 1

    if mentions.get("thinnest_character"):
        change_parts.append(
            f"{change_num}. **深化角色**: 评审团指出本章角色单薄。"
            "增加内心活动、身体特征或一个复杂化时刻。"
        )
        change_num += 1

    if mentions.get("missing_scene"):
        change_parts.append(
            f"{change_num}. **补充缺失节拍**: 评审团指出本章附近存在场景空缺。"
        )
        for m in mentions["missing_scene"]:
            snippet = m[:250] + "…" if len(m) > 250 else m
            change_parts.append(f"   {snippet}")
        change_num += 1

    if not change_parts:
        change_parts.append(
            "(评审团未给出具体修订建议。请结合 --eval 或 --cuts 获取可操作条目。)"
        )

    # ——— 【字数目标】区 ———
    if brief_type.startswith("COMPRESS"):
        target_wc = int(wc * 0.55)
        target_note = f"约 {target_wc} 字（从当前 {wc} 字压缩）"
    elif brief_type.startswith("DRAMATIZE"):
        target_note = f"约 {wc} 字（重组结构，保持当前长度）"
    elif brief_type.startswith("TIGHTEN"):
        target_wc = int(wc * 0.85)
        target_note = f"约 {target_wc} 字（从当前 {wc} 字收紧）"
    else:
        target_note = f"约 {wc} 字（当前长度，根据修订范围调整）"

    # ——— 组装 ———
    brief = f"# 修订摘要: 第 {ch} 章 — {title} ({brief_type})\n\n"
    brief += "## 【核心问题】\n"
    brief += "\n\n".join(problem_parts) + "\n\n"
    brief += "## 【保留项】\n"
    brief += "\n".join(keep_parts) + "\n\n"
    brief += "## 【修订项】\n"
    brief += "\n".join(change_parts) + "\n\n"
    brief += "## 【文风规则】\n"
    brief += "\n".join(f"- {r}" for r in voice_rules) + "\n\n"
    brief += "## 【字数目标】\n"
    brief += target_note + "\n"

    return brief


# =============================================================================
# build_eval_brief() — 评估结果摘要 (~145 行逻辑)
# =============================================================================

def build_eval_brief(ch: int) -> str:
    """基于评估结果生成修订摘要。"""
    ch_eval_path = latest_chapter_eval(ch)
    full_eval_path = latest_full_eval()

    if ch_eval_path is None and full_eval_path is None:
        sys.exit(f"错误: 未找到第 {ch} 章的评估日志")

    text = chapter_text(ch)
    title = chapter_title(text)
    wc = word_count(text)
    voice_rules = extract_voice_rules()

    problem_parts: list[str] = []
    keep_parts: list[str] = []
    change_parts: list[str] = []
    change_num = 1

    # ——— 单章评估数据 ———
    if ch_eval_path:
        ch_eval = load_json(ch_eval_path)

        overall = ch_eval.get("overall_score", "?")
        weakest_dim = ch_eval.get("weakest_dimension", "未知")
        problem_parts.append(
            f"单章评估得分: **{overall}/10**。最弱维度: **{weakest_dim}**。"
        )

        # 逐维度分析 ≤7 分的维度
        dim_keys = [
            "voice_adherence", "beat_coverage", "character_voice",
            "plants_seeded", "prose_quality", "continuity",
            "canon_compliance", "lore_integration", "engagement",
        ]
        dim_label_map = {
            "voice_adherence": "文风一致性",
            "beat_coverage": "节拍覆盖",
            "character_voice": "角色声音",
            "plants_seeded": "伏笔种植",
            "prose_quality": "文笔质量",
            "continuity": "连续性",
            "canon_compliance": "正典一致性",
            "lore_integration": "世界观融入",
            "engagement": "吸引力",
        }

        for dk in dim_keys:
            dim = ch_eval.get(dk)
            if not dim or not isinstance(dim, dict):
                continue
            score = dim.get("score", "?")
            weakest = dim.get("weakest_moment", "")
            fix = dim.get("fix", "")
            label = dim_label_map.get(dk, dk)

            if score != "?" and int(score) <= 7:
                if weakest:
                    problem_parts.append(
                        f"**{label}** ({score}/10): {weakest}"
                    )
                if fix:
                    change_parts.append(f"{change_num}. [{label}] {fix}")
                    change_num += 1

        # top_3_revisions
        top_revs = ch_eval.get("top_3_revisions", [])
        for rev in top_revs:
            change_parts.append(f"{change_num}. {rev}")
            change_num += 1

        # AI 模式检测
        ai_patterns = ch_eval.get("ai_patterns_detected", [])
        if ai_patterns:
            problem_parts.append("**检测到的 AI 模式:**")
            for pat in ai_patterns:
                problem_parts.append(f"- {pat}")

        # 最佳句子
        strongest = ch_eval.get("three_strongest_sentences", [])
        if strongest:
            keep_parts.append("最佳句子（评估）:")
            for s in strongest:
                keep_parts.append(f'- "{s}"')

        # 最弱句子
        weakest_sents = ch_eval.get("three_weakest_sentences", [])
        if weakest_sents:
            problem_parts.append("**最弱句子:**")
            for s in weakest_sents:
                problem_parts.append(f'- "{s}"')

    # ——— 全文评估上下文 ———
    if full_eval_path:
        full_eval = load_json(full_eval_path)
        weakest_ch = full_eval.get("weakest_chapter")
        top_sug = full_eval.get("top_suggestion", "")
        novel_score = full_eval.get("novel_score", "?")

        if weakest_ch == ch:
            problem_parts.insert(
                0,
                f"**这是全小说最弱章节**（全小说评分: {novel_score}/10）。"
            )
        if top_sug and (weakest_ch == ch or ch_eval_path is None):
            change_parts.append(
                f"{change_num}. [全文评估首要建议] {top_sug}"
            )
            change_num += 1

        # 节奏曲线注释
        pacing = full_eval.get("pacing_curve", {})
        pacing_note = pacing.get("note", "")
        ch_re = re.compile(
            rf"\b(?:第\s*{ch}\s*章|Ch\.?\s*{ch}|Chapter\s+{ch})\b",
            re.IGNORECASE
        )
        if ch_re.search(pacing_note):
            problem_parts.append(f"**节奏注释（全文评估）:** {pacing_note}")

    # ——— 交叉引用 cuts 的保留项 ———
    cuts_data = load_cuts(ch)
    if cuts_data and cuts_data.get("tightest_passage"):
        keep_parts.append(
            f'最紧致段落（对抗性编辑）: "{cuts_data["tightest_passage"]}"'
        )

    if not keep_parts:
        keep_parts.append("(修订前请复查章节最强段落。)")

    if not change_parts:
        change_parts.append(
            "(评估未给出具体修订条目。请结合 --panel 或 --cuts。)")

    # ——— 按分数确定类型 ———
    if ch_eval_path:
        ch_eval = load_json(ch_eval_path)
        overall = ch_eval.get("overall_score", 10)
        if overall <= 5:
            brief_type = "REWRITE（重写）"
        elif overall <= 7:
            brief_type = "FIX（修复）"
        else:
            brief_type = "POLISH（润色）"
    else:
        brief_type = "FIX（修复）"

    target_note = (
        f"约 {wc} 字（当前长度: {wc}；根据修订范围调整）"
    )

    # ——— 组装 ———
    brief = f"# 修订摘要: 第 {ch} 章 — {title} ({brief_type})\n\n"
    brief += "## 【核心问题】\n"
    brief += "\n\n".join(problem_parts) + "\n\n"
    brief += "## 【保留项】\n"
    brief += "\n".join(keep_parts) + "\n\n"
    brief += "## 【修订项】\n"
    brief += "\n".join(change_parts) + "\n\n"
    brief += "## 【文风规则】\n"
    brief += "\n".join(f"- {r}" for r in voice_rules) + "\n\n"
    brief += "## 【字数目标】\n"
    brief += target_note + "\n"

    return brief


# =============================================================================
# build_cuts_brief() — 对抗性编辑摘要 (~115 行逻辑)
# =============================================================================

def build_cuts_brief(ch: int) -> str:
    """基于对抗性编辑结果生成修订摘要。"""
    cuts_data = load_cuts(ch)
    if cuts_data is None:
        sys.exit(f"错误: edit_logs/ch{ch:02d}_cuts.json 未找到")

    text = chapter_text(ch)
    title = chapter_title(text)
    wc = word_count(text)
    voice_rules = extract_voice_rules()

    cuts = cuts_data.get("cuts", [])
    total_cuttable = cuts_data.get("total_cuttable_words", 0)
    tightest = cuts_data.get("tightest_passage", "")
    loosest = cuts_data.get("loosest_passage", "")
    fat_pct = cuts_data.get("overall_fat_percentage", 0)
    verdict = cuts_data.get("one_sentence_verdict", "")

    # ——— 按类型分组 ———
    cut_types: dict[str, list[dict]] = {}
    for c in cuts:
        t = c.get("type", "OTHER")
        cut_types.setdefault(t, []).append(c)

    # 主导模式分析
    type_counts = {t: len(cs) for t, cs in cut_types.items()}
    dominant = max(type_counts, key=type_counts.get) if type_counts else "混合"

    # 类型标签映射
    type_label_map = {
        "REDUNDANT": "冗余",
        "OVER-EXPLAIN": "过度解释",
        "FAT": "赘语",
        "TELL": "说教(tell)",
        "GENERIC": "套话/通用",
        "OTHER": "其他",
    }

    brief_type = "TIGHTEN（收紧）"

    # ——— 【核心问题】区 ———
    problem_parts: list[str] = []
    problem_parts.append(
        f"对抗性编辑发现 **{total_cuttable} 字可删除内容** "
        f"（赘语比例 {fat_pct}%），共 {len(cuts)} 处。"
    )
    if verdict:
        problem_parts.append(f"判决: {verdict}")

    problem_parts.append(
        f"\n主导模式: **{type_label_map.get(dominant, dominant)}** "
        f"（{type_counts.get(dominant, 0)} 处）"
    )
    for t, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        if t != dominant:
            problem_parts.append(
                f"- {type_label_map.get(t, t)}: {count} 处"
            )

    if loosest:
        problem_parts.append(f'\n**最松散段落:**\n> {loosest}')

    # ——— 【保留项】区 ———
    keep_parts: list[str] = []
    if tightest:
        keep_parts.append(
            f'**最紧致段落**（请勿修改）:\n> {tightest}'
        )

    # 交叉引用 eval 最佳句子
    ch_eval_path = latest_chapter_eval(ch)
    if ch_eval_path:
        ch_eval = load_json(ch_eval_path)
        strongest = ch_eval.get("three_strongest_sentences", [])
        if strongest:
            keep_parts.append("\n最佳句子（评估）:")
            for s in strongest:
                keep_parts.append(f'- "{s}"')

    if not keep_parts:
        keep_parts.append("(修订前请复查章节最强段落。)")

    # ——— 【修订项】区 ———
    change_parts: list[str] = []
    change_num = 1

    priority_order = ["REDUNDANT", "OVER-EXPLAIN", "FAT", "TELL", "GENERIC", "OTHER"]
    for cut_type in priority_order:
        type_cuts = cut_types.get(cut_type, [])
        if not type_cuts:
            continue
        label = type_label_map.get(cut_type, cut_type)
        change_parts.append(f"\n### {label} ({len(type_cuts)} 处)")
        for c in type_cuts:
            quote = c.get("quote", "")
            reason = c.get("reason", "")
            action = c.get("action", "CUT")
            rewrite = c.get("rewrite")

            # 截断过长引用
            if len(quote) > 150:
                quote = quote[:150] + "…"

            entry = f'{change_num}. `"{quote}"`\n'
            entry += f"   原因: {reason}\n"
            if action == "REWRITE" and rewrite:
                entry += f'   → 改写为: "{rewrite}"'
            elif action == "CUT":
                entry += "   → 直接删除"
            change_parts.append(entry)
            change_num += 1

    # ——— 【字数目标】区 ———
    target_wc = wc - total_cuttable
    target_note = (
        f"约 {target_wc} 字（从当前 {wc} 字删除约 {total_cuttable} 字）。"
        f"收紧 {fat_pct}% 赘语，保留最强节拍。"
    )

    # ——— 组装 ———
    brief = f"# 修订摘要: 第 {ch} 章 — {title} ({brief_type})\n\n"
    brief += "## 【核心问题】\n"
    brief += "\n".join(problem_parts) + "\n\n"
    brief += "## 【保留项】\n"
    brief += "\n".join(keep_parts) + "\n\n"
    brief += "## 【修订项】\n"
    brief += "\n".join(change_parts) + "\n\n"
    brief += "## 【文风规则】\n"
    brief += "\n".join(f"- {r}" for r in voice_rules) + "\n\n"
    brief += "## 【字数目标】\n"
    brief += target_note + "\n"

    return brief


# =============================================================================
# build_auto_brief() — 三源交叉引用自动摘要 (~180 行逻辑)
# =============================================================================

def build_auto_brief() -> tuple[int, str]:
    """自动选择最弱章节，合并 panel + eval + cuts 三源数据生成摘要。

    返回: (章节号, 摘要文本)
    """
    full_eval_path = latest_full_eval()
    if full_eval_path is None:
        raise FileNotFoundError("eval_logs/ 中未找到 *_full.json — 请先执行 evaluate_full 或采样评估")

    full_eval = load_json(full_eval_path)
    ch = full_eval.get("weakest_chapter")
    if ch is None:
        raise KeyError("全文评估中未包含 'weakest_chapter' 字段 — 评估结果可能不完整")

    step(f"自动识别最弱章节: 第 {ch} 章")
    step(f"  来源: {full_eval_path.name}")

    top_sug = full_eval.get("top_suggestion", "")
    weakest_dim = full_eval.get("weakest_dimension", "")
    novel_score = full_eval.get("novel_score", "?")

    text = chapter_text(ch)
    title = chapter_title(text)
    wc = word_count(text)
    voice_rules = extract_voice_rules()

    problem_parts: list[str] = []
    keep_parts: list[str] = []
    change_parts: list[str] = []
    change_num = 1

    # ——— 全文评估上下文 ———
    problem_parts.append(
        f"**全小说最弱章节**（小说评分: {novel_score}/10，"
        f"最弱维度: {weakest_dim}）。"
    )
    if top_sug:
        problem_parts.append(f"**全文评估首要建议:** {top_sug}")

    # 全文评估维度中提及本章的注释
    dim_keys = [
        "arc_completion", "pacing_curve", "theme_coherence",
        "foreshadowing_resolution", "world_consistency", "voice_consistency",
        "overall_engagement",
    ]
    dim_label_map = {
        "arc_completion": "弧线完成度",
        "pacing_curve": "节奏曲线",
        "theme_coherence": "主题一致性",
        "foreshadowing_resolution": "伏笔回收",
        "world_consistency": "世界观一致性",
        "voice_consistency": "文风一致性",
        "overall_engagement": "整体吸引力",
    }
    ch_re = re.compile(
        rf"\b(?:第\s*{ch}\s*章|Ch\.?\s*{ch}|Chapter\s+{ch})\b",
        re.IGNORECASE
    )
    for dk in dim_keys:
        dim = full_eval.get(dk, {})
        note = dim.get("note", "")
        if ch_re.search(note):
            score = dim.get("score", "?")
            label = dim_label_map.get(dk, dk)
            problem_parts.append(f"**{label}** ({score}/10): {note}")

    # ——— 单章评估 ———
    ch_eval_path = latest_chapter_eval(ch)
    if ch_eval_path:
        ch_eval = load_json(ch_eval_path)
        overall = ch_eval.get("overall_score", "?")
        problem_parts.append(f"\n单章评估得分: **{overall}/10**")

        # ≤7 分维度的 fix
        dim_keys_ch = [
            "voice_adherence", "beat_coverage", "character_voice",
            "plants_seeded", "prose_quality", "engagement",
        ]
        dim_label_ch = {
            "voice_adherence": "文风一致性",
            "beat_coverage": "节拍覆盖",
            "character_voice": "角色声音",
            "plants_seeded": "伏笔种植",
            "prose_quality": "文笔质量",
            "engagement": "吸引力",
        }
        for dk in dim_keys_ch:
            dim = ch_eval.get(dk)
            if not dim or not isinstance(dim, dict):
                continue
            score = dim.get("score", "?")
            fix = dim.get("fix", "")
            if score != "?" and int(score) <= 7 and fix:
                label = dim_label_ch.get(dk, dk)
                change_parts.append(f"{change_num}. [{label}] {fix}")
                change_num += 1

        # top_3_revisions
        for rev in ch_eval.get("top_3_revisions", []):
            change_parts.append(f"{change_num}. {rev}")
            change_num += 1

        # AI 模式
        ai_patterns = ch_eval.get("ai_patterns_detected", [])
        if ai_patterns:
            problem_parts.append("\n**检测到的 AI 模式:**")
            for pat in ai_patterns:
                problem_parts.append(f"- {pat}")

        # 最佳/最弱句子
        strongest = ch_eval.get("three_strongest_sentences", [])
        if strongest:
            keep_parts.append("最佳句子（评估）:")
            for s in strongest:
                keep_parts.append(f'- "{s}"')

        weakest_sents = ch_eval.get("three_weakest_sentences", [])
        if weakest_sents:
            problem_parts.append("\n**最弱句子:**")
            for s in weakest_sents:
                problem_parts.append(f'- "{s}"')

    # ——— 评审团交叉引用 ———
    panel = load_panel()
    if panel:
        info = panel_mentions_for_chapter(panel, ch)
        mentions = info["mentions"]
        flagged = info["flagged_issues"]

        if flagged:
            problem_parts.append("\n**评审团标记:**")
            for f in flagged:
                problem_parts.append(f"- {f}")

        neg_label_map = {
            "worst_scene": "评审团 — 最弱场景",
            "momentum_loss": "评审团 — 节奏拖沓",
            "cut_candidate": "评审团 — 建议删减",
        }
        for key, label in neg_label_map.items():
            if mentions.get(key):
                problem_parts.append(f"\n**{label}:**")
                for m in mentions[key]:
                    snippet = m[:300] + "…" if len(m) > 300 else m
                    problem_parts.append(snippet)

        if mentions.get("best_scene"):
            for m in mentions["best_scene"]:
                snippet = m[:300] + "…" if len(m) > 300 else m
                keep_parts.append(f"评审团最佳场景提及: {snippet}")

    # ——— 对抗性编辑交叉引用 ———
    cuts_data = load_cuts(ch)
    if cuts_data:
        total_cuttable = cuts_data.get("total_cuttable_words", 0)
        fat_pct = cuts_data.get("overall_fat_percentage", 0)
        tightest = cuts_data.get("tightest_passage", "")
        verdict = cuts_data.get("one_sentence_verdict", "")

        if total_cuttable:
            problem_parts.append(
                f"\n**对抗性编辑:** {total_cuttable} 字可删除 ({fat_pct}% 赘语)。"
                f" {verdict}"
            )
        if tightest:
            keep_parts.append(
                f'\n最紧致段落（对抗性编辑）:\n> {tightest}'
            )

        # 优先级最高的 cuts（REDUNDANT, OVER-EXPLAIN）前 5 条
        cuts_list = cuts_data.get("cuts", [])
        priority_cuts = [
            c for c in cuts_list
            if c.get("type") in ("REDUNDANT", "OVER-EXPLAIN")
        ]
        for c in priority_cuts[:5]:
            quote = c.get("quote", "")[:120]
            reason = c.get("reason", "")
            action = c.get("action", "CUT")
            rewrite = c.get("rewrite")
            entry = f'{change_num}. `"{quote}…"` — {reason}'
            if action == "REWRITE" and rewrite:
                entry += f'\n   → 改写为: "{rewrite}"'
            elif action == "CUT":
                entry += "\n   → 直接删除"
            change_parts.append(entry)
            change_num += 1

    # ——— 全文评估首要建议作为最终条目 ———
    if top_sug:
        # 去重检查
        if not any(top_sug in cp for cp in change_parts):
            change_parts.append(
                f"{change_num}. [首要 — 全文评估] {top_sug}"
            )
            change_num += 1

    if not keep_parts:
        keep_parts.append("(修订前请复查章节最强段落。)")
    if not change_parts:
        change_parts.append(
            "(未自动检测到具体修订条目。建议人工审查。)"
        )

    brief_type = "AUTO-FIX（自动修复）"
    target_note = (
        f"约 {wc} 字（当前: {wc}；根据修订范围调整）"
    )

    # ——— 组装 ———
    brief = f"# 修订摘要: 第 {ch} 章 — {title} ({brief_type})\n\n"
    brief += "## 【核心问题】\n"
    brief += "\n".join(problem_parts) + "\n\n"
    brief += "## 【保留项】\n"
    brief += "\n".join(keep_parts) + "\n\n"
    brief += "## 【修订项】\n"
    brief += "\n".join(change_parts) + "\n\n"
    brief += "## 【文风规则】\n"
    brief += "\n".join(f"- {r}" for r in voice_rules) + "\n\n"
    brief += "## 【字数目标】\n"
    brief += target_note + "\n"

    return ch, brief


# =============================================================================
# generate_brief() — 兼容 pipeline_orchestrator 的包装函数
# =============================================================================

def generate_brief(
    chapter_num: int = 0,
    panel_data: Optional[Path] = None,
    output_path: Optional[Path] = None,
    max_tokens: int = 4096,
    retries: int = 3,
    max_total_time: int = None,
) -> Optional[Path]:
    """为指定章节生成修订摘要。

    保持与 pipeline_orchestrator 兼容的接口。
    chapter_num=0 时自动选择最弱章节。

    返回: 保存的摘要文件路径，失败返回 None。
    """
    BRIEFS_DIR.mkdir(parents=True, exist_ok=True)

    try:
        if chapter_num == 0:
            ch, brief_text = build_auto_brief()
        else:
            # 根据可用数据源选择构建器
            cuts_path = EDIT_LOGS_DIR / f"ch{chapter_num:02d}_cuts.json"
            ch_eval_path = latest_chapter_eval(chapter_num)
            ch_file = CHAPTERS_DIR / f"ch_{chapter_num:02d}.md"

            if not ch_file.exists():
                step(f"第 {chapter_num} 章文件不存在，跳过")
                return None

            # 优先级: eval > cuts (需有实际条目) > panel > auto
            if ch_eval_path:
                step(f"第 {chapter_num} 章: 使用评估摘要 (--eval)")
                brief_text = build_eval_brief(chapter_num)
            elif cuts_path.exists():
                # ★ 检查 cuts 是否真的有内容（而非 0 条目空壳）
                try:
                    cuts_data = json.loads(cuts_path.read_text(encoding="utf-8"))
                    total_cuttable = cuts_data.get("total_cuttable_words", 0)
                    if total_cuttable > 0:
                        step(f"第 {chapter_num} 章: 使用对抗性编辑摘要 (--cuts)")
                        brief_text = build_cuts_brief(chapter_num)
                    elif panel_data and panel_data.exists():
                        step(f"第 {chapter_num} 章: cuts 无内容，回退评审团摘要 (--panel)")
                        brief_text = build_panel_brief(chapter_num)
                    else:
                        step(f"第 {chapter_num} 章: cuts 无内容，尝试自动模式")
                        full_eval_path = latest_full_eval()
                        if full_eval_path:
                            ch, brief_text = build_auto_brief()
                            if ch != chapter_num:
                                step(f"自动模式选择了第 {ch} 章而非第 {chapter_num} 章")
                        else:
                            raise ValueError("无可用数据源")
                except Exception:
                    # cuts 解析失败，回退 panel 或 auto
                    if panel_data and panel_data.exists():
                        step(f"第 {chapter_num} 章: cuts 解析失败，回退评审团摘要 (--panel)")
                        brief_text = build_panel_brief(chapter_num)
                    else:
                        raise
            elif panel_data and panel_data.exists():
                step(f"第 {chapter_num} 章: 使用评审团摘要 (--panel)")
                brief_text = build_panel_brief(chapter_num)
            else:
                step(f"第 {chapter_num} 章: 无可用的评估/裁剪/评审团数据，尝试自动模式")
                full_eval_path = latest_full_eval()
                if full_eval_path:
                    ch, brief_text = build_auto_brief()
                    if ch != chapter_num:
                        step(f"自动模式选择了第 {ch} 章而非第 {chapter_num} 章")
                else:
                    step(f"第 {chapter_num} 章: 无任何可用数据源，创建最小摘要")
                    text = chapter_text(chapter_num) if ch_file.exists() else "(无章节文本)"
                    brief_text = (
                        f"# 修订摘要: 第 {chapter_num} 章\n\n"
                        f"## 【核心问题】\n"
                        f"(无可用的评估、评审团或对抗性编辑数据。"
                        f"请先运行相关评估流程。)\n\n"
                        f"## 【保留项】\n(手动审查)\n\n"
                        f"## 【修订项】\n(手动审查)\n\n"
                        f"## 【字数目标】\n"
                        f"当前约 {word_count(text)} 字\n"
                    )

        # 确定输出路径
        if output_path:
            save_path = output_path
        else:
            # 按来源标记文件名
            suffix = _detect_source_suffix(chapter_num if chapter_num > 0 else ch)
            save_path = BRIEFS_DIR / f"ch{chapter_num:02d}_{suffix}.md"

        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_text(brief_text, encoding="utf-8")
        step(f"修订摘要已保存: {save_path}")
        return save_path

    except Exception as e:
        step(f"摘要生成失败: {e}")
        return None


def _detect_source_suffix(ch: int) -> str:
    """检测主要数据源，返回文件名后缀标签。"""
    if latest_chapter_eval(ch):
        return "eval"
    if (EDIT_LOGS_DIR / f"ch{ch:02d}_cuts.json").exists():
        return "cuts"
    if (EDIT_LOGS_DIR / "reader_panel.json").exists():
        return "panel"
    return "auto"


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="从评审团/评估/对抗性编辑生成修订摘要"
    )
    parser.add_argument("--panel", type=int, metavar="章节号",
                        help="基于评审团反馈生成章节摘要")
    parser.add_argument("--eval", type=int, metavar="章节号",
                        help="基于评估结果生成章节摘要")
    parser.add_argument("--cuts", type=int, metavar="章节号",
                        help="基于对抗性编辑结果生成章节摘要")
    parser.add_argument("--auto", action="store_true",
                        help="自动识别最弱章节，合并三源数据生成摘要")
    parser.add_argument("--dry-run", action="store_true",
                        help="仅输出到 stdout，不保存文件")

    args = parser.parse_args()

    # 校验: 只能使用一种模式
    modes = sum([
        args.panel is not None,
        args.eval is not None,
        args.cuts is not None,
        args.auto,
    ])
    if modes == 0:
        parser.print_help()
        sys.exit(1)
    if modes > 1:
        sys.exit("错误: 请只指定 --panel, --eval, --cuts, --auto 中的一种")

    # 生成
    if args.panel is not None:
        ch = args.panel
        brief_text = build_panel_brief(ch)
        suffix = "panel"
    elif args.eval is not None:
        ch = args.eval
        brief_text = build_eval_brief(ch)
        suffix = "eval"
    elif args.cuts is not None:
        ch = args.cuts
        brief_text = build_cuts_brief(ch)
        suffix = "cuts"
    else:  # --auto
        ch, brief_text = build_auto_brief()
        suffix = "auto"

    if args.dry_run:
        print(brief_text)
        return

    # 保存
    BRIEFS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = BRIEFS_DIR / f"ch{ch:02d}_{suffix}.md"
    out_path.write_text(brief_text, encoding="utf-8")
    print(f"已保存: {out_path}", file=sys.stderr)
    print(f"章节: 第 {ch} 章", file=sys.stderr)
    print(f"类型: {suffix}", file=sys.stderr)
    print(f"摘要长度: {word_count(brief_text)} 字", file=sys.stderr)


if __name__ == "__main__":
    main()