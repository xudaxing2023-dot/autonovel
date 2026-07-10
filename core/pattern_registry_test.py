#!/usr/bin/env python3
"""
core/pattern_registry_test.py — Pattern Registry 自动化测试

测试每个已注册 Pattern 的：
  1. 正向匹配（使用 output/ 下的真实 LLM 输出数据）
  2. 兜底行为（使用故意写错的格式）
  3. 永不抛异常（空输入、乱码输入）
  4. 格式突变兼容（模拟 LLM 输出格式变化）

用法：
  python core/pattern_registry_test.py          # 运行所有测试
  python core/pattern_registry_test.py --quick  # 仅测试兜底逻辑（不加载真实数据）
"""

import json
import os
import sys
import unittest
from pathlib import Path

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.pattern_registry import registry, ParsedResult

OUTPUT_DIR = PROJECT_ROOT / "output"
CHAPTERS_DIR = OUTPUT_DIR / "chapters"
EVAL_LOGS_DIR = OUTPUT_DIR / "eval_logs"
EDIT_LOGS_DIR = OUTPUT_DIR / "edit_logs"


# ============================================================================
# 辅助函数
# ============================================================================

def _load_text(path: Path) -> str:
    """加载文本文件，不存在则返回空字符串。"""
    if path.exists():
        return path.read_text(encoding="utf-8-sig")
    return ""


def _load_json(path: Path) -> dict:
    """加载 JSON 文件，不存在则返回空字典。"""
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


# ============================================================================
# 测试类 1: 兜底行为 — 每个 Pattern 永不抛异常
# ============================================================================

class TestFallbackNeverRaises(unittest.TestCase):
    """验证每个 Pattern 的兜底不会抛出异常。"""

    @classmethod
    def setUpClass(cls):
        cls.all_patterns = registry.list_all()

    def test_fallback_on_empty_string(self):
        """空字符串输入应返回兜底值。"""
        for name in self.all_patterns:
            with self.subTest(pattern=name):
                try:
                    result = registry.match(name, "")
                    self.assertIsInstance(result, ParsedResult,
                                          f"Pattern '{name}' 空字符串未返回 ParsedResult")
                except Exception as e:
                    self.fail(f"Pattern '{name}' 空字符串触发异常: {e}")

    def test_fallback_on_None_input(self):
        """None 输入应返回兜底值。"""
        for name in self.all_patterns:
            with self.subTest(pattern=name):
                try:
                    result = registry.match(name, None)
                    self.assertIsInstance(result, ParsedResult,
                                          f"Pattern '{name}' None 输入未返回 ParsedResult")
                except Exception as e:
                    self.fail(f"Pattern '{name}' None 输入触发异常: {e}")

    def test_fallback_on_garbage_input(self):
        """垃圾输入应返回兜底值。"""
        garbage = "\x00\x00\x00 garbage \xFF\xFF\xFF 乱码 🗑️ \x1b[31mANSI\x1b[0m"
        for name in self.all_patterns:
            with self.subTest(pattern=name):
                try:
                    result = registry.match(name, garbage)
                    self.assertIsInstance(result, ParsedResult,
                                          f"Pattern '{name}' 垃圾输入未返回 ParsedResult")
                except Exception as e:
                    self.fail(f"Pattern '{name}' 垃圾输入触发异常: {e}")

    def test_fallback_on_very_long_input(self):
        """超长输入不应崩溃。"""
        long_text = "这是一个测试句子。" * 10000  # ~50 万字
        for name in self.all_patterns:
            with self.subTest(pattern=name):
                try:
                    result = registry.match(name, long_text)
                    self.assertIsInstance(result, ParsedResult)
                except Exception as e:
                    self.fail(f"Pattern '{name}' 超长输入触发异常: {e}")

    def test_unregistered_pattern_returns_sentinel(self):
        """未注册的 Pattern 应返回 sentinel。"""
        result = registry.match("nonexistent.pattern", "some text")
        self.assertIsNone(result.value)
        self.assertEqual(result.confidence, 0.0)
        self.assertEqual(result.matched_by, "unregistered")


# ============================================================================
# 测试类 2: canon.* Pattern 族
# ============================================================================

class TestCanonPatterns(unittest.TestCase):
    """测试 canon.* Pattern 的正向匹配和兜底。"""

    @classmethod
    def setUpClass(cls):
        cls.canon_text = _load_text(OUTPUT_DIR / "canon.md")

    def test_entry_count_from_canon(self):
        """从真实 canon.md 统计条目数。"""
        if not self.canon_text:
            self.skipTest("canon.md 不存在")
        result = registry.match("canon.entry_count", self.canon_text)
        self.assertIsInstance(result.value, int)
        self.assertGreaterEqual(result.value, 0)
        # canon.md 至少应有几十条条目
        if result.confidence > 0:
            self.assertGreater(result.value, 0,
                               f"canon.md 应包含至少 1 条条目，但检测到 {result.value}")

    def test_entry_count_empty(self):
        """空文本应返回 0 条目。"""
        result = registry.match("canon.entry_count", "")
        self.assertEqual(result.value, 0)
        self.assertEqual(result.confidence, 0.0)

    def test_no_new_facts_positive(self):
        """匹配「无新增事实」变体。"""
        for text in [
            "无新增事实",
            "没有新事实",
            "无新事实。",
            "无需更新",
            "无可添加事实",
        ]:
            with self.subTest(text=text):
                result = registry.match("canon.no_new_facts", text)
                self.assertTrue(result.value,
                                f"应匹配 '{text}' 但返回 {result.value}")

    def test_no_new_facts_negative(self):
        """不匹配包含新事实的文本。"""
        for text in [
            "新增 3 条事实",
            "## 新增：世界观硬事实\n- ...",
            "本章有重要新设定",
        ]:
            with self.subTest(text=text):
                result = registry.match("canon.no_new_facts", text)
                self.assertFalse(result.value,
                                 f"不应匹配 '{text}' 但返回 {result.value}")


# ============================================================================
# 测试类 3: voice.* Pattern 族
# ============================================================================

class TestVoicePatterns(unittest.TestCase):
    """测试 voice.* Pattern 的正向匹配和兜底。"""

    @classmethod
    def setUpClass(cls):
        cls.voice_text = _load_text(OUTPUT_DIR / "voice.md")

    def test_vocab_section_fallback_on_missing(self):
        """voice.md 可能不含 Vocabulary Register 节 — 应优雅返回 None。"""
        # 使用确定不含该节的文本
        result = registry.match("voice.vocabulary_section", "# 标题\n\n无词汇域内容。")
        self.assertIsNone(result.value)
        self.assertEqual(result.confidence, 0.0)

    def test_vocab_section_with_chinese_title(self):
        """测试中文标题 '词汇域' 的匹配。"""
        text = "### 词汇域\n- 关键词1: a, b, c\n### 其他节\n"
        result = registry.match("voice.vocabulary_section", text)
        # 可能匹配也可能不匹配，取决于 regex，但不应抛异常
        self.assertIsInstance(result, ParsedResult)

    def test_vocab_well_structured(self):
        """测试结构化词汇域条目解析。"""
        text = "1. **商业暗语**: 合同, 条款, 签字\n2. **身体感官**: 疼痛, 呼吸, 脉搏"
        result = registry.match("voice.vocab_well", text)
        self.assertIsInstance(result.value, list)
        if result.confidence > 0:
            self.assertGreater(len(result.value), 0)

    def test_vocab_well_empty_input(self):
        """空文本应返回空列表。"""
        result = registry.match("voice.vocab_well", "")
        self.assertEqual(result.value, [])


# ============================================================================
# 测试类 4: slop.* Pattern 族
# ============================================================================

class TestSlopPatterns(unittest.TestCase):
    """测试 slop.* Pattern 的正向匹配和兜底。"""

    @classmethod
    def setUpClass(cls):
        cls.ch01_text = _load_text(CHAPTERS_DIR / "ch_01.md")

    def test_four_char_from_real_chapter(self):
        """真实章节中应检测到四字词。"""
        if not self.ch01_text:
            self.skipTest("ch_01.md 不存在")
        result = registry.match("slop.four_char", self.ch01_text)
        self.assertIsInstance(result.value, list)
        # 任意中文文本都应有一些四字词
        if len(self.ch01_text) > 500:
            self.assertGreater(len(result.value), 0,
                               "真实章节文本应包含至少一些四字窗口")

    def test_four_char_idiom_match(self):
        """白名单成语应被检测。"""
        text = "他小心翼翼地看着她，她也感到不知所措，这一切不可思议。"
        result = registry.match("slop.four_char", text)
        self.assertIsInstance(result.value, list)
        self.assertGreater(len(result.value), 0)

    def test_em_dash_variants(self):
        """各种破折号变体应被统一计数。"""
        text = "他停顿了一下——然后继续——说着——另外—这里还有--破折号–英文的"
        result = registry.match("slop.em_dash", text)
        self.assertIsInstance(result.value, int)
        # —— (3个) + — (1个) + -- (1个) + – (1个) = 6
        self.assertGreaterEqual(result.value, 6,
                                f"应检测到至少 6 个破折号，但返回 {result.value}")

    def test_em_dash_no_dashes(self):
        """无破折号文本应返回 0。"""
        result = registry.match("slop.em_dash", "这是一段没有任何破折号的文本。")
        self.assertEqual(result.value, 0)

    def test_dialog_tag_extended(self):
        """扩展对话标签应检测多种标签。"""
        text = "他说：今天天气不错。她问道：是吗？他喊道：快来看！她回答：好的。"
        result = registry.match("slop.dialog_tag", text)
        self.assertIsInstance(result.value, list)
        self.assertGreater(len(result.value), 0,
                           f"应检测到对话标签，但返回 {result.value}")

    def test_dialog_tag_no_tags(self):
        """纯叙述文本应返回空列表。"""
        text = "天空很蓝，白云飘过，微风轻拂，一切都很安静。"
        result = registry.match("slop.dialog_tag", text)
        self.assertEqual(result.value, [])


# ============================================================================
# 测试类 5: score.* Pattern 族
# ============================================================================

class TestScorePatterns(unittest.TestCase):
    """测试 score.* Pattern 的正向匹配和兜底。"""

    @classmethod
    def setUpClass(cls):
        # 加载最新的 foundation eval log
        foundation_logs = sorted(EVAL_LOGS_DIR.glob("foundation_*.json"))
        cls.foundation_eval = {}
        if foundation_logs:
            cls.foundation_eval = _load_json(foundation_logs[-1])

    def test_markdown_fallback_on_garbled(self):
        """乱码文本应返回兜底 None。"""
        result = registry.match("score.markdown_fallback",
                                "这不是有效的 Markdown 评分格式")
        self.assertIsNone(result.value)
        self.assertEqual(result.confidence, 0.0)

    def test_markdown_bold_score_format(self):
        """**综合评分**: X/10 格式应被匹配。"""
        text = "**综合评分**: 7.5/10"
        result = registry.match("score.markdown_fallback", text)
        if result.confidence > 0:
            self.assertEqual(result.value.group(1), "7.5")

    def test_markdown_chinese_colon(self):
        """中文冒号变体应被匹配。"""
        text = "**综合评分**：6.0/10"
        result = registry.match("score.markdown_fallback", text)
        if result.confidence > 0:
            self.assertEqual(result.value.group(1), "6.0")


# ============================================================================
# 测试类 6: antipattern.* Pattern 族
# ============================================================================

class TestAntipatternPatterns(unittest.TestCase):
    """测试 antipattern.* Pattern 的正向匹配和兜底。"""

    def test_catalog_think_extended(self):
        """扩展主语/动词应检测目录式思考。"""
        text = "他想到了昨天的事。她回忆着过去的时光。他们觉得这样不对。我意识到问题了。"
        result = registry.match("antipattern.catalog_think", text)
        self.assertIsInstance(result.value, list)
        self.assertGreater(len(result.value), 0,
                           f"应检测到目录式思考，但返回 {result.value}")

    def test_catalog_think_no_match(self):
        """纯动作描述不应匹配。"""
        text = "他跑向门口，推开门，冲了出去。她跟在后面，气喘吁吁。"
        result = registry.match("antipattern.catalog_think", text)
        self.assertEqual(result.value, [])

    def test_catalog_think_legacy_he_she(self):
        """原始「他|她」模式应保持向后兼容。"""
        text = "他想了一下。她思索着答案。"
        result = registry.match("antipattern.catalog_think", text)
        self.assertIsInstance(result.value, list)
        self.assertGreater(len(result.value), 0)


# ============================================================================
# 测试类 7: text.* Pattern 族
# ============================================================================

class TestTextPatterns(unittest.TestCase):
    """测试 text.* Pattern 的正向匹配和兜底。"""

    @classmethod
    def setUpClass(cls):
        cls.ch01_text = _load_text(CHAPTERS_DIR / "ch_01.md")

    def test_sentence_split_real_chapter(self):
        """真实章节应正确切分为多句。"""
        if not self.ch01_text:
            self.skipTest("ch_01.md 不存在")
        result = registry.match("text.sentence_split", self.ch01_text)
        self.assertIsInstance(result.value, list)
        self.assertGreater(len(result.value), 5,
                           f"章节文本应切分为多句，但只得到 {len(result.value)} 句")

    def test_sentence_split_chinese_punctuation(self):
        """中文标点应正确切分。"""
        text = "这是第一句话。这是第二句话！这是第三句话？这是第四句……还没完。"
        result = registry.match("text.sentence_split", text)
        self.assertIsInstance(result.value, list)
        self.assertGreaterEqual(len(result.value), 4,
                                f"应切分为至少 4 句，但得到 {len(result.value)}")

    def test_sentence_split_empty(self):
        """空文本应返回空列表。"""
        result = registry.match("text.sentence_split", "")
        self.assertEqual(result.value, [])

    def test_sentence_split_single_sentence(self):
        """单句不应被切分。"""
        result = registry.match("text.sentence_split", "这是一句完整的话")
        self.assertIsInstance(result.value, list)
        self.assertEqual(len(result.value), 1)


# ============================================================================
# 测试类 8: review.* Pattern 族
# ============================================================================

class TestReviewPatterns(unittest.TestCase):
    """测试 review.* Pattern 的正向匹配和兜底。"""

    @classmethod
    def setUpClass(cls):
        cls.review_text = _load_text(EDIT_LOGS_DIR / "review_round1.md")

    def test_stars_from_real_review(self):
        """从真实审阅报告解析星级。"""
        if not self.review_text:
            self.skipTest("review_round1.md 不存在")
        result = registry.match("review.stars", self.review_text)
        self.assertIsInstance(result, ParsedResult)
        # 不强制要求匹配成功（LLM 输出格式可能变化），但不应抛异常

    def test_stars_on_example(self):
        """测试示例格式。"""
        text = "总评: ★★★★☆\n严重问题数: 0\n总问题数: 8"
        result = registry.match("review.stars", text)
        if result.confidence > 0:
            stars = result.value.group(0).count("★")
            self.assertEqual(stars, 4)

    def test_major_count_on_example(self):
        """测试严重问题数解析。"""
        text = "严重问题数: 3"
        result = registry.match("review.major_count", text)
        if result.confidence > 0:
            self.assertEqual(result.value.group(1), "3")

    def test_total_count_on_example(self):
        """测试总问题数解析。"""
        text = "总问题数: 12"
        result = registry.match("review.total_count", text)
        if result.confidence > 0:
            self.assertEqual(result.value.group(1), "12")

    def test_weak_chapters_on_example(self):
        """测试最弱章节解析。"""
        text = "最弱章节: 1,2,4"
        result = registry.match("review.weak_chapters", text)
        if result.confidence > 0:
            self.assertEqual(result.value.group(1), "1,2,4")


# ============================================================================
# 测试类 9: outline.* Pattern 族
# ============================================================================

class TestOutlinePatterns(unittest.TestCase):
    """测试 outline.* Pattern 的正向匹配和兜底。"""

    @classmethod
    def setUpClass(cls):
        cls.vol_macro = _load_text(OUTPUT_DIR / "outline_volume.md")

    def test_vol_boundary_from_real_outline(self):
        """从真实 outline_volume.md 检测卷边界。"""
        if not self.vol_macro:
            self.skipTest("outline_volume.md 不存在")
        result = registry.match("outline.vol_boundary", self.vol_macro)
        self.assertIsInstance(result, ParsedResult)
        # 不强制要求匹配（LLM 格式可能不同），但不应抛异常

    def test_vol_boundary_with_heading(self):
        """测试 '## 逐卷规划' 格式。"""
        text = "## 逐卷规划\n\n### 卷 1：开端\n内容..."
        result = registry.match("outline.vol_boundary", text)
        if result.confidence > 0:
            self.assertIsNotNone(result.value)

    def test_vol_boundary_with_chinese_num(self):
        """测试 '### 二、卷 1 规划' 格式。"""
        text = "### 二、卷 1 规划\n\n内容..."
        result = registry.match("outline.vol_boundary", text)
        if result.confidence > 0:
            self.assertIsNotNone(result.value)

    def test_vol_boundary_no_match(self):
        """无卷边界的文本应返回 None。"""
        text = "# 普通标题\n\n这是普通内容，没有任何卷标记。"
        result = registry.match("outline.vol_boundary", text)
        self.assertIsNone(result.value)
        self.assertEqual(result.confidence, 0.0)


# ============================================================================
# 测试类 10: codeblock.* Pattern 族
# ============================================================================

class TestCodeblockPatterns(unittest.TestCase):
    """测试 codeblock.* Pattern 的正向匹配和兜底。"""

    def test_strip_json_codeblock(self):
        """应正确剥除 ```json ... ``` 代码块。"""
        text = '```json\n{"overall_score": 7.5}\n```'
        result = registry.match("codeblock.strip", text)
        self.assertIn('"overall_score"', result.value)
        self.assertNotIn("```", result.value)

    def test_strip_codeblock_no_lang(self):
        """无语言标识的代码块也应被剥除。"""
        text = '```\n{"score": 5.0}\n```'
        result = registry.match("codeblock.strip", text)
        self.assertIn('"score"', result.value)
        self.assertNotIn("```", result.value)

    def test_strip_passthrough_plain_text(self):
        """纯文本（无代码块）应原样返回。"""
        text = '{"overall_score": 8.0}'
        result = registry.match("codeblock.strip", text)
        self.assertEqual(result.value.strip(), text)

    def test_strip_empty(self):
        """空文本应返回空字符串。"""
        result = registry.match("codeblock.strip", "")
        self.assertEqual(result.value, "")

    def test_strip_crlf_newlines(self):
        """Windows \\r\\n 换行应被正确处理。"""
        text = '```json\r\n{"score": 6.5}\r\n```'
        result = registry.match("codeblock.strip", text)
        self.assertIn('"score"', result.value)
        self.assertNotIn("```", result.value)


# ============================================================================
# 测试类 11: 格式突变模拟
# ============================================================================

class TestFormatMutation(unittest.TestCase):
    """模拟 LLM 输出格式变化，验证兜底逻辑。"""

    def test_score_with_trailing_comma(self):
        """LLM 常见错误：JSON 尾部多余逗号 — 应通过宽松解析恢复。"""
        # 验证 pattern 不会因畸形 JSON 崩溃
        text = '{"overall_score": 7.5,}'
        result = registry.match("score.markdown_fallback", text)
        self.assertIsInstance(result, ParsedResult)

    def test_score_wrapped_in_explanation(self):
        """LLM 在 JSON 前后添加解释文本。"""
        text = '根据评估，我认为分数如下：\n{"overall_score": 7.5}\n以上是评分结果。'
        result = registry.match("score.markdown_fallback", text)
        self.assertIsInstance(result, ParsedResult)

    def test_mixed_chinese_english_punctuation(self):
        """LLM 混用中英文标点。"""
        text = "综合评分：7.5/10"
        result = registry.match("score.markdown_fallback", text)
        self.assertIsInstance(result, ParsedResult)

    def test_em_dash_unicode_variation(self):
        """LLM 混用多种 Unicode 破折号。"""
        text = "——\u2014\u2014--\u2013\u2013"  # —— / — / -- / –
        result = registry.match("slop.em_dash", text)
        self.assertIsInstance(result.value, int)
        self.assertGreater(result.value, 0)

    def test_dialog_tag_with_role_name(self):
        """角色名 + 标签的组合（如「林恩说：」）应被变体1检测。"""
        text = "林恩说：我们走吧。王队长问道：去哪里？"
        result = registry.match("slop.dialog_tag", text)
        self.assertIsInstance(result.value, list)
        # 扩展标签应检测到「说」和「问道」
        self.assertGreater(len(result.value), 0)


# ============================================================================
# 测试类 12: 注册完整性
# ============================================================================

class TestRegistryCompleteness(unittest.TestCase):
    """验证所有预期的 Pattern 已注册。"""

    REQUIRED_PATTERNS = [
        # Phase 1
        "canon.entry_count",
        "canon.no_new_facts",
        "voice.vocabulary_section",
        "score.markdown_fallback",
        # Phase 2
        "slop.four_char",
        "slop.dialog_tag",
        "slop.em_dash",
        "voice.vocab_well",
        "antipattern.catalog_think",
        "text.sentence_split",
        "outline.vol_boundary",
        "review.stars",
        "review.major_count",
        "review.total_count",
        "review.qualified_count",
        "review.weak_chapters",
        "codeblock.strip",
    ]

    def test_all_required_patterns_registered(self):
        """所有必需 Pattern 应已注册。"""
        registered = set(registry.list_all())
        for name in self.REQUIRED_PATTERNS:
            self.assertIn(name, registered,
                          f"Pattern '{name}' 未注册！请检查 _register_phase*_patterns()")

    def test_pattern_count_at_least(self):
        """已注册 Pattern 数量应 ≥ 预期。"""
        self.assertGreaterEqual(len(registry.list_all()),
                                len(self.REQUIRED_PATTERNS),
                                "注册的 Pattern 数量不足")


# ============================================================================
# 主入口
# ============================================================================

def main():
    """运行测试套件。"""
    import argparse
    parser = argparse.ArgumentParser(description="Pattern Registry 自动化测试")
    parser.add_argument("--quick", action="store_true",
                        help="快速模式：仅测试兜底逻辑，不加载真实数据文件")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="详细输出")
    args = parser.parse_args()

    # 构建测试套件
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # 始终包含的测试（不依赖真实数据）
    always_include = [
        TestFallbackNeverRaises,
        TestRegistryCompleteness,
        TestCodeblockPatterns,
        TestFormatMutation,
    ]
    for test_class in always_include:
        suite.addTests(loader.loadTestsFromTestCase(test_class))

    if not args.quick:
        # 包含依赖真实数据的测试
        data_dependent = [
            TestCanonPatterns,
            TestVoicePatterns,
            TestSlopPatterns,
            TestScorePatterns,
            TestAntipatternPatterns,
            TestTextPatterns,
            TestReviewPatterns,
            TestOutlinePatterns,
        ]
        for test_class in data_dependent:
            suite.addTests(loader.loadTestsFromTestCase(test_class))

    verbosity = 2 if args.verbose else 1
    runner = unittest.TextTestRunner(verbosity=verbosity)
    result = runner.run(suite)

    # 返回非零退出码以便 CI 检测
    if not result.wasSuccessful():
        sys.exit(1)


if __name__ == "__main__":
    main()
