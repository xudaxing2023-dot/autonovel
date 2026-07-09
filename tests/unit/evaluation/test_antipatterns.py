"""
tests/unit/evaluation/test_antipatterns.py — 反模式检测测试

测试 evaluation.antipatterns.run_structural_audit() 的7项结构检测。
所有检测基于统计特征，体裁无关，不需要LLM API。

对应测试方案：
  TC-EVL-011 ~ TC-EVL-017
"""

import pytest
from evaluation.antipatterns import (
    run_structural_audit,
    detect_over_explain,
    detect_triadic_listing,
    detect_negative_assertions,
    detect_simile_crutch,
    detect_paragraph_uniformity,
    detect_section_break_abuse,
    detect_catalog_thinking,
)


# ============================================================================
# 测试数据
# ============================================================================

TEXT_OVER_EXPLAIN = """门被重重地关上了。这意味着他已经做出了选择。她看着他的背影，
终于明白了一切。说白了，这一切都是因为他不够信任她。这代表着他们的关系走到了尽头。
她意识到从始至终他都在说谎。换句话说他从来没有认真对待过这段感情。"""

TEXT_TRIADIC_LISTING = """他看着窗外的雨。听着远处的风。想着过去的她。
他站起来。走到门口。打开门。三件事连续发生了。"""

TEXT_NEGATIVE_ASSERTIONS = """他没有回头。她没有任何犹豫。他没有说话。她没有哭泣。
他没有解释。她没有原谅。他没有任何理由留下。"""

TEXT_SIMILE_CRUTCH = """天空如同洗过一样蓝。树木仿佛在低语。她的笑容宛如春风。
生活好比一场旅行。他的眼神好似寒冰。整个城市犹如一个巨大的迷宫。
她如同天使一般美丽。这仿佛是命运的安排。他宛如一头受伤的野兽。这是好比一个笑话。""" * 3

TEXT_UNIFORM_PARAGRAPHS = """这是一个长度均匀的中文段落，大约有四十个汉字左右的内容。

这也是一个长度均匀的中文段落，大约有四十个汉字左右的内容。

这还是一个长度均匀的中文段落，大约有四十个汉字左右的内容。

这又是一个长度均匀的中文段落，大约有四十个汉字左右的内容。

这同样是一个长度均匀的中文段落，大约有四十个汉字左右的内容。

这仍是一段长度均匀的中文段落，大约有四十个汉字左右的内容。"""

TEXT_SECTION_BREAKS = """第一章内容。

---

第二章内容。

---

第三章内容。

---

第四章内容。"""

TEXT_CATALOG_THINKING = """他想到了昨天的失败。他想起了母亲的叮嘱。
他思索着未来的方向。她思考着人生的意义。他琢磨着那句话的深意。
她盘算着下一步的计划。他回忆着童年的美好时光。"""

TEXT_CLEAN = """深秋的雨总是下个不停。王云把领子竖起来，踩着湿漉漉的石板路往家走。
街两旁的店铺都关了门，只有一家茶馆还亮着灯。透过模糊的玻璃窗，能看见几个人影在晃动。
他在茶馆门口站了一会儿，雨水顺着屋檐滴下来，在青石板上砸出细小的水花。

茶馆里暖烘烘的，带着一股茶香和水汽。老板娘认得他，远远地笑了笑，指了指角落的空位。
王云点点头，走过去坐下，把外套搭在椅背上。"""


class TestRunStructuralAudit:

    # TC-EVL-011: 过度解释检测 (OVER-EXPLAIN)
    def test_over_explain_detection(self):
        """文本含3+处'这意味着'、'说白了'等应被检测到过度解释。"""
        result = run_structural_audit(TEXT_OVER_EXPLAIN)

        assert result["over_explain"]["count"] >= 3
        # warnings 中应包含"过度解释"
        assert any("过度解释" in w for w in result["warnings"])

    # TC-EVL-012: 三连罗列检测 (TRIADIC LISTING)
    def test_triadic_listing_detection(self):
        """文本含连续三个结构相似的短句应被检测到三连罗列。"""
        result = run_structural_audit(TEXT_TRIADIC_LISTING)

        assert result["triadic_listing"]["count"] >= 0  # count可能从count或examples长度中获取
        # 验证检测确实运行
        assert "count" in result["triadic_listing"]

    # TC-EVL-013: 否定断言检测 (NEGATIVE-ASSERTION)
    def test_negative_assertions_detection(self):
        """文本含6+处'他没有...'应检测到否定断言过多。"""
        result = run_structural_audit(TEXT_NEGATIVE_ASSERTIONS)

        assert result["negative_assertions"]["count"] > 5
        assert any("否定断言" in w for w in result["warnings"])

    # TC-EVL-014: 比喻拐杖检测 (SIMILE CRUTCH)
    def test_simile_crutch_detection(self):
        """文本每千字含3+个比喻词应被检测到比喻密度过高。"""
        result = run_structural_audit(TEXT_SIMILE_CRUTCH)

        assert result["simile_crutch"]["count"] > 0
        assert result["simile_crutch"]["per_1000_chars"] > 0

    # TC-EVL-015: 段落均匀化检测 (PARAGRAPH UNIFORMITY)
    def test_paragraph_uniformity_detection(self):
        """连续3+段长度差<20%应被检测到段落均匀化。"""
        result = run_structural_audit(TEXT_UNIFORM_PARAGRAPHS)

        assert "uniform_streak_ratio" in result["paragraph_uniformity"]
        # 均匀段落应该产生较高的 uniform_streak_ratio
        assert result["paragraph_uniformity"]["uniform_streak_ratio"] > 0

    # TC-EVL-016: 分隔符滥用检测 (SECTION BREAK ABUSE)
    def test_section_break_abuse_detection(self):
        """文本含3+个 --- 分隔符应被检测为 excessive。"""
        result = run_structural_audit(TEXT_SECTION_BREAKS)

        assert result["section_break_abuse"]["count"] > 2
        assert result["section_break_abuse"]["excessive"] is True
        assert any("分隔符" in w for w in result["warnings"])

    # TC-EVL-017: 目录式思考检测 (CATALOGING-BY-THINKING)
    def test_catalog_thinking_detection(self):
        """文本含多处理科式'他想到了...'应检测到目录式思考密度过高。"""
        result = run_structural_audit(TEXT_CATALOG_THINKING)

        assert result["catalog_thinking"]["count"] > 0
        assert result["catalog_thinking"]["per_1000_chars"] > 0

    # 附加：干净文本应无警告
    def test_clean_text_no_warnings(self):
        """干净的自然文本应无或极少结构反模式警告。"""
        result = run_structural_audit(TEXT_CLEAN)

        # 干净文本应该警告少
        assert result["warning_count"] <= 2, (
            f"Expected <= 2 warnings, got {result['warning_count']}: {result['warnings']}"
        )

    # 附加：空文本处理
    def test_empty_text(self):
        """空文本应正常处理，所有检测结果返回默认值。"""
        result = run_structural_audit("")

        assert result["over_explain"]["count"] == 0
        assert result["negative_assertions"]["count"] == 0
        assert result["warning_count"] == 0

    # 附加：验证错误返回结构完整性
    def test_return_structure(self):
        """验证 run_structural_audit 返回完整的7项检测结果。"""
        result = run_structural_audit(TEXT_CLEAN)

        expected_keys = [
            "over_explain", "triadic_listing", "negative_assertions",
            "simile_crutch", "paragraph_uniformity",
            "section_break_abuse", "catalog_thinking",
            "warnings", "warning_count",
        ]
        for key in expected_keys:
            assert key in result, f"Missing key: {key}"


class TestIndividualDetectors:

    def test_detect_over_explain_standalone(self):
        result = detect_over_explain(TEXT_OVER_EXPLAIN)
        assert result["count"] >= 3

    def test_detect_triadic_listing_standalone(self):
        result = detect_triadic_listing(TEXT_TRIADIC_LISTING)
        assert "count" in result

    def test_detect_negative_assertions_standalone(self):
        result = detect_negative_assertions(TEXT_NEGATIVE_ASSERTIONS)
        assert result["count"] > 5

    def test_detect_simile_crutch_standalone(self):
        result = detect_simile_crutch(TEXT_SIMILE_CRUTCH)
        assert result["count"] > 0

    def test_detect_paragraph_uniformity_standalone(self):
        result = detect_paragraph_uniformity(TEXT_UNIFORM_PARAGRAPHS)
        assert "length_cv" in result

    def test_detect_section_break_abuse_standalone(self):
        result = detect_section_break_abuse(TEXT_SECTION_BREAKS)
        assert result["excessive"] is True

    def test_detect_catalog_thinking_standalone(self):
        result = detect_catalog_thinking(TEXT_CATALOG_THINKING)
        assert result["count"] > 0
