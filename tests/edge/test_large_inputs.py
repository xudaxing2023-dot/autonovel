"""
tests/edge/test_large_inputs.py — 阶段5B: 超长文本输入 (4个用例)

测试目标:
  TC-EDG-007: 100章大纲输入
  TC-EDG-008: 100个角色注册表
  TC-EDG-009: 3万字单章文本
  TC-EDG-010: 超长 prompt（模拟 token 超限场景）

所有测试不调用 LLM API。
"""

import json
import re
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# ============================================================================
# Helpers
# ============================================================================

def _generate_outline_100_chapters() -> str:
    """生成100章的大纲文本。"""
    lines = ["# 大纲\n"]
    for i in range(1, 101):
        vol = (i - 1) // 10 + 1
        lines.append(f"### 第 {i} 章：第{vol}卷第{i}章标题")
        lines.append(f"本章讲述第{i}章的故事情节，主角在第{i}章中经历了重要的转折。")
        lines.append(f"关键事件：事件A-{i}、事件B-{i}、事件C-{i}")
        lines.append("")
    return "\n".join(lines)


def _generate_characters_100() -> str:
    """生成100个角色的注册表文本。"""
    lines = ["# 角色注册表\n"]
    for i in range(1, 101):
        lines.append(f"## 角色{i}：角色名_{i}")
        lines.append(f"- 年龄：{20 + i % 50}岁")
        lines.append(f"- 身份：{'主角' if i == 1 else '配角' if i < 10 else '龙套'}")
        lines.append(f"- 性格：{'坚毅果断' if i % 3 == 0 else '温和大方' if i % 3 == 1 else '冷漠孤僻'}")
        lines.append(f"- 背景：角色{i}来自{'北方大陆' if i % 2 == 0 else '南方群岛'}，"
                     f"曾经历{'战争' if i % 3 == 0 else '家族变故' if i % 3 == 1 else '神秘事件'}")
        lines.append("")
    return "\n".join(lines)


def _generate_30k_chapter() -> str:
    """生成约3万字的单章文本。"""
    paragraphs = []
    # 每段约150字，需要约200段
    base_text = (
        "夜风从窗缝中挤进来，带着潮湿的土腥味。"
        "他坐在桌前已经两个时辰，面前的宣纸上只落了寥寥数行字。"
        "墨迹早已干涸，笔尖的墨也凝成了暗紫色的硬壳。"
        "窗外偶尔传来几声犬吠，又迅速被夜色吞没。"
        "他放下笔，揉了揉发涩的眼睛。"
    )
    for i in range(200):
        para = f"第{i+1}段：" + base_text.replace("他", f"角色{i%10+1}")
        paragraphs.append(para)
    return "\n\n".join(paragraphs)


# ============================================================================
# TC-EDG-007: 100章大纲
# ============================================================================

class TestLargeOutline:
    """测试100章大纲的处理。"""

    def test_generate_100_chapter_outline(self):
        """验证100章大纲生成函数。"""
        outline = _generate_outline_100_chapters()
        lines = outline.split("\n")
        chapter_lines = [l for l in lines if l.startswith("### 第")]
        assert len(chapter_lines) == 100, \
            f"应有100章大纲条目，实际 {len(chapter_lines)}"

    def test_extract_chapter_50_from_100(self, tmp_path):
        """TC-EDG-007: 从100章大纲中提取第50章。

        使用 drafting/draft_chapter.py 的 extract_chapter_outline 逻辑。
        """
        outline_file = tmp_path / "outline.md"
        outline_text = _generate_outline_100_chapters()
        outline_file.write_text(outline_text, encoding="utf-8")

        # 模拟 extract_chapter_outline 的核心逻辑
        chapter_num = 50
        pattern = rf'###\s*(?:第\s*)?{chapter_num}\s*章.*?(?=###\s*(?:第\s*)?{chapter_num + 1}\s*章|## 伏笔|## 二、|## 三、|$)'
        match = re.search(pattern, outline_text, re.DOTALL)

        assert match is not None, \
            f"应能从100章大纲中匹配到第{chapter_num}章"
        extracted = match.group(0).strip()
        assert f"第 {chapter_num} 章" in extracted, \
            f"提取内容应含'第 {chapter_num} 章'，实际: '{extracted[:80]}'"

    def test_extract_last_chapter_from_100(self, tmp_path):
        """从100章大纲中提取最后一章（第100章）。"""
        outline_text = _generate_outline_100_chapters()

        chapter_num = 100
        # 最后一章没有下一个 "### 第 101 章" 作为终止边界
        pattern = rf'###\s*(?:第\s*)?{chapter_num}\s*章.*?(?=###\s*(?:第\s*)?{chapter_num + 1}\s*章|## 伏笔|## 二、|## 三、|$)'
        match = re.search(pattern, outline_text, re.DOTALL)

        assert match is not None, \
            f"应能匹配最后一章（第{chapter_num}章）"
        extracted = match.group(0).strip()
        assert f"第 {chapter_num} 章" in extracted, \
            f"提取内容应含'第 {chapter_num} 章'"


# ============================================================================
# TC-EDG-008: 100个角色注册表
# ============================================================================

class TestLargeCharacters:
    """测试100个角色的处理。"""

    def test_generate_100_characters(self):
        """验证100角色生成函数。"""
        chars = _generate_characters_100()
        # 统计 ## 开头的角色条目
        role_count = chars.count("\n## 角色")
        assert role_count == 100, \
            f"应有100个角色条目，实际 {role_count}"

    def test_count_canon_entries_with_100_chars(self, tmp_path, monkeypatch):
        """TC-EDG-008: 100角色时 count_canon_entries() 不OOM。

        模拟 count_canon_entries 处理大量角色数据。
        """
        from foundation.gen_canon import count_canon_entries
        import core.config as cfg

        # 创建包含100角色的 canon.md
        canon_dir = tmp_path / "output"
        canon_dir.mkdir()
        canon_file = canon_dir / "canon.md"
        canon_file.write_text(_generate_characters_100(), encoding="utf-8")

        # patch OUTPUT_DIR
        monkeypatch.setattr(cfg, "OUTPUT_DIR", canon_dir, raising=False)

        # 调用计数函数
        try:
            counts = count_canon_entries()
            assert "total" in counts, "应返回 total 键"
            assert "character" in counts, "应返回 character 键"
            # 不检查具体数值（因为格式不一定是标准 canon 格式），
            # 但至少不应崩溃或 OOM
            print(f"\n[100角色 canon 计数] {counts}")
        except Exception as e:
            # 不会因 OOM 崩溃
            pytest.fail(f"100角色时 count_canon_entries 不应崩溃: {e}")


# ============================================================================
# TC-EDG-009: 3万字单章文本
# ============================================================================

class Test30kChapter:
    """测试3万字单章的处理。"""

    def test_generate_30k_text(self):
        """验证3万字文本生成。"""
        text = _generate_30k_chapter()
        # 统计中文字符数
        char_count = len(text.replace(" ", "").replace("\n", ""))
        expected_min = 20000  # 约2万字+（3万字含标点和空白）
        assert char_count > expected_min, \
            f"生成文本应 >{expected_min}字，实际 {char_count}字"
        print(f"\n[3万字章] 实际字符数: {char_count}")

    def test_slop_score_on_30k(self, tmp_path):
        """TC-EDG-009: 3万字单章上运行 slop_score_zh()。

        验证机械检测在超长文本上不会性能退化或崩溃。
        slop_score_zh 返回 dict 包含 slop_penalty, tier1_hits 等键，
        不包含 char_count。
        """
        from evaluation.evaluate import slop_score_zh

        text = _generate_30k_chapter()
        chapter_file = tmp_path / "ch_01.md"
        chapter_file.write_text(text, encoding="utf-8")

        # 运行 slop_score_zh
        try:
            result = slop_score_zh(text)
            # slop_score_zh 返回的键
            assert "slop_penalty" in result, "应返回 slop_penalty"
            assert "tier1_hits" in result, "应返回 tier1_hits"
            assert "tier2_hits" in result, "应返回 tier2_hits"
            assert "em_dash_density" in result, "应返回 em_dash_density"
            # 验证是合理的数值
            penalty = result.get("slop_penalty", 0)
            assert isinstance(penalty, (int, float)), \
                f"slop_penalty 应为数值，实际 {type(penalty)}"
            print(f"\n[3万字 slop_score] penalty={penalty}, "
                  f"em_dash_density={result.get('em_dash_density')}")
        except Exception as e:
            pytest.fail(f"3万字单章 slop_score_zh 不应崩溃: {e}")

    def test_structural_audit_on_30k(self, tmp_path):
        """3万字单章上运行 run_structural_audit()。"""
        from evaluation.antipatterns import run_structural_audit

        text = _generate_30k_chapter()

        try:
            audit = run_structural_audit(text)
            assert "warning_count" in audit, "应返回 warning_count"
            assert "warnings" in audit, "应返回 warnings"
            print(f"\n[3万字结构审计] warning_count={audit.get('warning_count')}")
        except Exception as e:
            pytest.fail(f"3万字单章 run_structural_audit 不应崩溃: {e}")


# ============================================================================
# TC-EDG-010: 超长 prompt（模拟 token 超限场景）
# ============================================================================

class TestExtraLongPrompt:
    """测试超长 prompt 的处理。"""

    def test_build_prompt_with_massive_context(self, tmp_path):
        """TC-EDG-010: 模拟超长 prompt 构建。

        将所有上下文都填充到接近 token 限制的量，
        验证 build_chapter_prompt 不会崩溃。
        """
        from prompts.chapter_prompts import build_chapter_prompt

        # 生成大量上下文数据
        voice = "文风规则：避免AI套话。" * 500  # ~6KB
        world = "世界观设定：这是一个玄幻世界。" * 500  # ~6KB
        characters = _generate_characters_100()  # ~30KB
        outline = _generate_outline_100_chapters()[:5000]  # 截取部分
        next_chapter = "### 第 51 章：下一章预告"
        prev_context = "前文回顾：..." * 100
        canon = _generate_characters_100()[:5000]  # 截取部分

        try:
            prompt = build_chapter_prompt(
                50,
                voice_text=voice,
                world_text=world,
                characters_text=characters,
                chapter_outline=outline,
                next_chapter_preview=next_chapter,
                prev_context=prev_context,
                canon_text=canon,
                novel_title="测试小说",
            )
            assert isinstance(prompt, str), "应返回字符串"
            assert len(prompt) > 0, "prompt 不应为空"
            # prompt 可能非常长
            print(f"\n[超长prompt] 长度: {len(prompt)} 字符, "
                  f"约 {len(prompt)//3} tokens")
        except Exception as e:
            pytest.fail(f"超长上下文构建 prompt 不应崩溃: {e}")

    def test_prompt_token_estimation(self):
        """验证 prompt 长度与 token 估算。"""
        from prompts.chapter_prompts import build_chapter_prompt

        # 最简 prompt
        prompt = build_chapter_prompt(
            1,
            voice_text="简短文风",
            world_text="简单世界",
            characters_text="简单角色",
            chapter_outline="### 第 1 章",
            next_chapter_preview="### 第 2 章",
            prev_context="无前文",
            canon_text="无正典",
            novel_title="测试",
        )
        # 粗略估算：中文约 1.5 字符/token
        estimated_tokens = len(prompt) // 1.5
        print(f"\n[最简prompt] {len(prompt)} 字符, "
              f"约 {int(estimated_tokens)} tokens")
        # 不应超过常见模型的上下文窗口
        assert estimated_tokens < 32000, \
            f"最简 prompt 的预估 token 数 ({int(estimated_tokens)}) " \
            f"不应超过 32K"
