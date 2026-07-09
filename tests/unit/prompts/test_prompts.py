"""
tests/unit/prompts/test_prompts.py — Prompt格式验证测试

测试各 build_*_prompt() 函数的输出格式：
  - build_world_prompt() 包含必要字段
  - build_character_prompt() 包含必要字段
  - build_chapter_prompt() 包含必要字段
  - build_outline_prompt() 包含必要字段
  - prompt中无不必要的空值占位符
  - prompt长度合理

注意：prompt测试只需验证输出字符串格式，不需要真实LLM调用。

对应测试方案：
  TC-PRM-001 ~ TC-PRM-003
"""

import pytest
from unittest.mock import patch, MagicMock


# ============================================================================
# build_chapter_prompt 测试
# ============================================================================

class TestBuildChapterPrompt:

    # TC-PRM-001: 所有参数非空
    def test_all_params_present(self):
        """当所有参数非空时，prompt应包含所有节标题。"""
        from prompts.chapter_prompts import build_chapter_prompt

        prompt = build_chapter_prompt(
            chapter_num=5,
            voice_text="测试文风定义文本",
            world_text="测试世界观设定文本",
            characters_text="测试角色注册表文本",
            chapter_outline="### 第 5 章\n测试大纲内容",
            next_chapter_preview="### 第 6 章\n下一章预览",
            prev_context="【第 4 章全文】\n前章内容...",
            canon_text="测试正典内容",
            novel_title="测试小说",
        )

        # 验证必要字段
        assert "第 5 章" in prompt
        assert "【文风定义（严格遵守）】" in prompt
        assert "【本章大纲（逐项完成）】" in prompt
        assert "【下一章预告" in prompt
        assert "【前文回顾" in prompt
        assert "【世界观设定】" in prompt
        assert "【角色注册表】" in prompt
        assert "【正典（已确立的硬事实——不可违反）】" in prompt
        assert "【写作指令】" in prompt

    # TC-PRM-002: canon为空时不输出正典节
    def test_canon_empty_omitted(self):
        """canon_text=""时，prompt不应包含正典节。"""
        from prompts.chapter_prompts import build_chapter_prompt

        prompt = build_chapter_prompt(
            chapter_num=5,
            voice_text="测试文风",
            world_text="测试世界观",
            characters_text="测试角色",
            chapter_outline="测试大纲",
            next_chapter_preview="下一章预览",
            prev_context="前文回顾",
            canon_text="",  # 空
            novel_title="",
        )

        assert "【正典（已确立的硬事实——不可违反）】" not in prompt

    def test_novel_title_empty_omitted(self):
        """novel_title=""时，不应输出'小说名称：'。"""
        from prompts.chapter_prompts import build_chapter_prompt

        prompt = build_chapter_prompt(
            chapter_num=5,
            voice_text="测试文风",
            world_text="测试世界观",
            characters_text="测试角色",
            chapter_outline="测试大纲",
            next_chapter_preview="下一章预览",
            prev_context="前文回顾",
            novel_title="",  # 空
        )

        assert "小说名称：" not in prompt

    def test_novel_title_present(self):
        """novel_title非空时应出现在prompt中。"""
        from prompts.chapter_prompts import build_chapter_prompt

        prompt = build_chapter_prompt(
            chapter_num=5,
            voice_text="测试文风",
            world_text="测试世界观",
            characters_text="测试角色",
            chapter_outline="测试大纲",
            next_chapter_preview="下一章预览",
            prev_context="前文回顾",
            novel_title="深渊之眼",
        )

        assert "小说名称：《深渊之眼》" in prompt

    def test_prompt_length_reasonable(self):
        """prompt长度应在合理范围内（约2000-10000 char）。"""
        from prompts.chapter_prompts import build_chapter_prompt

        prompt = build_chapter_prompt(
            chapter_num=5,
            voice_text="测试文风定义文本。这是200字的测试文本。" * 2,
            world_text="世界观设定文本。" * 50,
            characters_text="角色信息文本。" * 50,
            chapter_outline="大纲内容文本。" * 20,
            next_chapter_preview="下一章预告。" * 5,
            prev_context="前章内容回顾。" * 20,
            canon_text="正典内容。" * 30,
            novel_title="测试小说",
        )

        # prompt应该不太短（至少500字）
        assert len(prompt) > 500
        # 也不应过长（< 50000 字）
        assert len(prompt) < 50000

    def test_minimal_params(self):
        """最小参数调用不应崩溃。"""
        from prompts.chapter_prompts import build_chapter_prompt

        prompt = build_chapter_prompt(
            chapter_num=1,
            voice_text="",
            world_text="",
            characters_text="",
            chapter_outline="",
            next_chapter_preview="",
            prev_context="",
        )

        assert isinstance(prompt, str)
        assert len(prompt) > 0
        assert "第 1 章" in prompt


# ============================================================================
# build_world_prompt 测试
# ============================================================================

class TestBuildWorldPrompt:

    def test_contains_required_sections(self):
        """prompt应包含世界观构建的必要部分。"""
        from prompts.world_prompts import build_world_prompt

        prompt = build_world_prompt(
            seed_text="这是一个测试故事梗概。",
            voice_part2="现代都市题材，冷峻克制的叙事风格。",
            craft_text="叙事技艺参考：展示而非说教。",
        )

        assert "世界观设定文档" in prompt
        assert "【故事梗概】" in prompt
        assert "【文档结构" in prompt
        # 应包含必要章节标题
        assert "宇宙观" in prompt or "历史" in prompt
        assert "核心规则" in prompt or "特殊体系" in prompt

    def test_minimal_params(self):
        """最小参数调用不应崩溃。"""
        from prompts.world_prompts import build_world_prompt

        prompt = build_world_prompt(seed_text="")

        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_prompt_length_reasonable(self):
        """prompt不应过长。"""
        from prompts.world_prompts import build_world_prompt

        prompt = build_world_prompt(
            seed_text="长故事梗概。" * 100,
            voice_part2="长文风定义。" * 100,
            craft_text="长技艺参考。" * 100,
        )

        # 不应超过50000字（因为 craft_text 和 voice_part2 会被截断）
        assert len(prompt) < 50000


# ============================================================================
# build_character_prompt 测试
# ============================================================================

class TestBuildCharacterPrompt:

    def test_contains_required_sections(self):
        """prompt应包含角色设计的必要部分。"""
        from prompts.character_prompts import build_character_prompt

        prompt = build_character_prompt(
            seed_text="这是一个测试故事梗概。",
            world_text="测试世界观设定。",
            voice_part2="测试文风身份。",
        )

        assert "角色注册表" in prompt
        assert "【故事梗概】" in prompt
        assert "【角色设计规范" in prompt

    def test_minimal_params(self):
        """最小参数调用不应崩溃。"""
        from prompts.character_prompts import build_character_prompt

        prompt = build_character_prompt(seed_text="")

        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_world_text_empty_omitted(self):
        """world_text为空时不应出现世界观设定节。"""
        from prompts.character_prompts import build_character_prompt

        prompt = build_character_prompt(
            seed_text="测试故事",
            world_text="",
        )

        assert "【世界观设定】" not in prompt


# ============================================================================
# build_outline_prompt 测试
# ============================================================================

class TestBuildOutlinePrompt:

    def test_contains_required_sections(self):
        """prompt应包含大纲生成的必要部分。"""
        from prompts.outline_prompts import build_outline_prompt

        prompt = build_outline_prompt(
            seed_text="这是一个测试故事梗概。",
            world_text="测试世界观。",
            characters_text="测试角色。",
            mystery_text="测试谜团。",
            voice_part2="测试文风。",
        )

        assert "章节大纲" in prompt
        assert "【故事梗概】" in prompt
        assert "幕结构" in prompt or "幕结构规划" in prompt

    def test_minimal_params(self):
        """最小参数调用不应崩溃。"""
        from prompts.outline_prompts import build_outline_prompt

        prompt = build_outline_prompt(seed_text="")

        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_prompt_length_reasonable(self):
        """prompt不应过长。"""
        from prompts.outline_prompts import build_outline_prompt

        prompt = build_outline_prompt(
            seed_text="长故事。" * 100,
            world_text="长世界观。" * 100,
            characters_text="长角色。" * 100,
        )

        assert len(prompt) < 50000


# ============================================================================
# 无空值占位符测试
# ============================================================================

class TestNoEmptyPlaceholders:

    def test_chapter_prompt_no_double_empty_lines(self):
        """prompt中不应有过多的连续空行（空值占位符会导致）。"""
        from prompts.chapter_prompts import build_chapter_prompt

        prompt = build_chapter_prompt(
            chapter_num=5,
            voice_text="测试文风定义。",
            world_text="世界观。",
            characters_text="角色。",
            chapter_outline="大纲。",
            next_chapter_preview="预告。",
            prev_context="前文。",
            canon_text="",  # 空 — 应被条件排除
            novel_title="",  # 空 — 应被条件排除
        )

        # 不应有3个以上连续空行
        lines = prompt.split("\n")
        consecutive_empty = 0
        max_consecutive = 0
        for line in lines:
            if line.strip() == "":
                consecutive_empty += 1
                max_consecutive = max(max_consecutive, consecutive_empty)
            else:
                consecutive_empty = 0

        assert max_consecutive <= 3, (
            f"Found {max_consecutive} consecutive empty lines (max allowed: 3)"
        )

    def test_world_prompt_no_orphan_labels(self):
        """prompt中不应有裸露的标签（如 '小说名称：' 后面没有值）。"""
        from prompts.world_prompts import build_world_prompt

        prompt = build_world_prompt(
            seed_text="测试",
            voice_part2="",  # 空
            craft_text="",  # 空
        )

        # 空的 voice_part2 应导致 "【文风身份】" 行不出现在 prompt 中
        assert "【文风身份】" not in prompt
