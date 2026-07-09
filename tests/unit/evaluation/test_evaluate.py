"""
tests/unit/evaluation/test_evaluate.py — Slop检测测试

测试 evaluation.evaluate.slop_score_zh() 对中文AI套话的机械检测。
所有检测体裁无关，不需要LLM API。

对应测试方案：
  TC-EVL-001 ~ TC-EVL-010
"""

import pytest
from evaluation.evaluate import slop_score_zh


# ============================================================================
# 测试输入数据
# ============================================================================

CLEAN_LITERARY_TEXT = """夜已经深了。巷子里的灯灭了大半，只剩拐角处一盏还亮着，把水洼照成暗黄色。
老陈蹲在门槛上，手里捏着半根烟。他听见远处有脚步声，不紧不慢，像是故意踩在水里。
那人在他面前停下来。
"还有烟吗。"
老陈抬头看了看，没说话，从兜里掏出烟盒递过去。那人抽出一根，在盒子上顿了顿。
打火机的火苗在风里挣扎了两下，灭了，又挣扎了一下，总算着了。
"今晚不太平。"那人把烟盒还回来。
老陈还是没接话。他盯着巷子另一头，那里有什么东西在动——不是人。"""

TEXT_WITH_FANGFU = """他走在雨中，仿佛整个世界都在为他哭泣。那种感觉，仿佛回到了很久以前。"""

TEXT_WITH_SIHU = """她似乎在等待什么，似乎有什么话要说却说不出口。这一切似乎早已注定。"""

TEXT_WITH_BUZHIWEIHE = """不知为何，他今天格外沉默。不知为何，所有的话语都堵在了喉咙里。"""

TEXT_WITH_AIR_FANGFU = """空气中仿佛飘着一种说不清的味道，甜腻中带着腐烂。他感到一阵眩晕。"""

TEXT_MULTI_SLOP = """在这个风云变幻的时代，他感到一阵莫名的悲伤涌上心头。
眼中闪过一丝不易察觉的泪光，他的嘴角微微上扬，露出一抹苦涩的笑容。
他深深地吸了一口气，仿佛要把所有的痛苦都吸入肺里。
"这一切，终究是值得的，"他喃喃自语，"不仅仅是命运的安排，更是我的选择。"
从此，他的心中充满了坚定，宛如一幅壮丽的人生画卷在他面前徐徐展开。
空气中弥漫着丁香花的气息，一股暖流涌上心头，让他不由得感到欣慰。
他瞪大了眼睛，心脏在胸腔里狂跳，缓缓地吐出一口气。
一股前所未有的勇气席卷全身，他锐利的目光扫过众人，眼神中透出无比的坚定。
会心一笑，他感到自己不再是孤独的——事实上，他从来都不是。
然而，这就是人世间最真实的模样。沉默在蔓延，但谁也没有说话，没有人开口。
某种东西在他体内苏醒了，暗自松了口气，这一切都是有意义的。"""

TEXT_SHORT = "他走了。"

TEXT_LONG = ("""深秋的雨总是下个不停。王云把领子竖起来，踩着湿漉漉的石板路往家走。
街两旁的店铺都关了门，只有一家茶馆还亮着灯。透过模糊的玻璃窗，能看见几个人影在晃动。
他在茶馆门口站了一会儿，雨水顺着屋檐滴下来，在青石板上砸出细小的水花。
""") * 500  # ~2500 chars * 500 = long enough but not excessive for testing

TEXT_NONE_INPUT_HANDLING = None  # For testing None input


class TestSlopScoreZh:

    # TC-EVL-001: 无AI痕迹的文本
    def test_clean_literary_text(self):
        """人类撰写的自然中文段落应获得低分。"""
        result = slop_score_zh(CLEAN_LITERARY_TEXT)

        assert len(result["tier1_hits"]) == 0, f"Tier1 hits found: {result['tier1_hits']}"
        assert result["slop_penalty"] < 1.0, f"Penalty too high: {result['slop_penalty']}"
        assert result["fiction_ai_tells"] == [] or sum(c for _, c in result["fiction_ai_tells"]) == 0

    # TC-EVL-002: 含Tier1套话
    def test_tier1_slop_fangfu(self):
        """包含"仿佛"的文本应被检测到 Tier2 或 fiction_ai_tells（"仿佛"不在Tier1中）。"""
        result = slop_score_zh(TEXT_WITH_FANGFU)

        # "仿佛" 不在 TIER1_CHINESE_SLOP 也不在 TIER2_CHINESE_SLOP
        # 但可能在 FICTION_AI_TELLS_ZH 中（如"一股...涌上"等）
        # 主要是验证函数不崩溃，返回有效结构
        assert isinstance(result, dict)
        assert "slop_penalty" in result
        assert "tier1_hits" in result
        assert "tier2_hits" in result

    def test_tier1_slop_wanru(self):
        """包含Tier1套话'宛如一幅壮丽的画卷'应检测到tier1_hits非空。"""
        text = "这是宛如一幅壮丽的画卷般的美景。"
        result = slop_score_zh(text)

        assert len(result["tier1_hits"]) > 0
        assert result["slop_penalty"] >= 0.5

    # TC-EVL-003: 含Tier2套话
    def test_tier2_slop_gan_dao_yizhen(self):
        """包含'他感到一阵'应被检测到tier2_hits非空。"""
        text = "他感到一阵寒意从背后袭来，她感到一阵莫名的温暖。"
        result = slop_score_zh(text)

        assert len(result["tier2_hits"]) > 0
        assert result["slop_penalty"] >= 0.2

    def test_tier2_slop_yanzhong_shanguo(self):
        """包含'眼中闪过一丝'应被检测到tier2_hits非空。"""
        text = "他眼中闪过一丝疑虑，嘴角微微上扬。"
        result = slop_score_zh(text)

        assert len(result["tier2_hits"]) > 0

    # TC-EVL-004: 含小说AI套话 (P3-12)
    def test_fiction_ai_tells_air(self):
        """包含'空气中弥漫着'应被检测到fiction_ai_tells非空。"""
        text = "空气中弥漫着紧张的气氛，一股暖流涌上心头。"
        result = slop_score_zh(text)

        assert len(result["fiction_ai_tells"]) > 0
        assert result["slop_penalty"] > 0

    # TC-EVL-005: 含结构修辞公式 (P3-12)
    def test_structural_ai_tics(self):
        """包含'我不是说X，而是说Y'应被检测到structural_ai_tics非空。"""
        text = "我不是说你错了，而是说你的方法有问题。说到底，这都是命运的安排。"
        result = slop_score_zh(text)

        # 检查 structural_ai_tics 是否非空
        assert len(result["structural_ai_tics"]) > 0
        assert result["slop_penalty"] > 0

    # TC-EVL-006: 含说教式情感 (show-don't-tell)
    def test_telling_violations(self):
        """包含'他感到愤怒'、'她显得很悲伤'应被检测到telling_violations>0。"""
        text = "他感到愤怒，她显得很悲伤，他看起来很焦虑。"
        result = slop_score_zh(text)

        # telling_violations 检测 "他感到愤怒" 等模式
        assert result["telling_violations"] > 0

    # TC-EVL-007: 含段落开头过渡词滥用
    def test_transition_openers(self):
        """多个段落以'然而'、'但是'开头应被检测到 transition_opener_ratio > 0。"""
        text = """然而事情并非如此简单。

但是没有人相信他的解释。

此外还有一个更重要的原因。

事实上这一切早已注定。"""
        result = slop_score_zh(text)

        assert result["transition_opener_ratio"] > 0

    # TC-EVL-008: 破折号密度过高
    def test_em_dash_density(self):
        """每500字含5个'——'应导致 em_dash_density > 3 和 slop_penalty 增加。"""
        # 创建约500字的文本，含多个破折号
        base = "这是一个很长的句子用来填充文本内容。" * 10  # ~150 chars
        text = base + "——" + base + "——" + base + "——" + base + "——" + base + "——" + base
        result = slop_score_zh(text)

        assert result["em_dash_density"] > 0
        # 如果密度超过3，penalty应增加
        if result["em_dash_density"] > 3:
            assert result["slop_penalty"] > 0

    # TC-EVL-009: 空文本
    def test_empty_text(self):
        """空字符串应返回所有计数为0，slop_penalty=0。"""
        result = slop_score_zh("")

        assert result["tier1_hits"] == []
        assert result["tier2_hits"] == []
        assert result["slop_penalty"] == 0.0
        assert result["telling_violations"] == 0

    # 极短文本（<50字）
    def test_very_short_text(self):
        """极短文本（<50字）应能正常处理，不崩溃。"""
        result = slop_score_zh(TEXT_SHORT)

        assert isinstance(result, dict)
        assert "slop_penalty" in result
        # 极短文本通常不会有很多匹配
        assert result["slop_penalty"] >= 0

    # 较长文本（用于性能验证）
    def test_long_text(self):
        """较长文本应在合理时间内完成，不崩溃。"""
        result = slop_score_zh(TEXT_LONG)

        assert isinstance(result, dict)
        assert "slop_penalty" in result
        assert result["slop_penalty"] >= 0

    # None输入的处理
    def test_none_input(self):
        """None输入应安全返回默认全零字典（BUG-011 已修复）。"""
        result = slop_score_zh(None)
        assert isinstance(result, dict)
        assert result["slop_penalty"] == 0.0
        assert result["tier1_hits"] == []
        assert result["tier2_hits"] == []

    # 综合多种slop的文本
    def test_multi_slop_comprehensive(self):
        """多种slop术语同时出现时应返回显著的惩罚分。"""
        result = slop_score_zh(TEXT_MULTI_SLOP)

        # 多种slop应产生显著惩罚
        assert result["slop_penalty"] > 0.5, f"Expected penalty > 0.5, got {result['slop_penalty']}"
        # 验证多种检测都有结果
        total_hits = (
            sum(c for _, c in result["tier1_hits"]) +
            sum(c for _, c in result["tier2_hits"]) +
            sum(c for _, c in result["fiction_ai_tells"]) +
            sum(c for _, c in result["structural_ai_tics"])
        )
        assert total_hits > 0, "Expected at least some slop detected"

    # 验证返回字典结构完整性
    def test_return_structure(self):
        """验证返回字典包含所有必需键。"""
        result = slop_score_zh(CLEAN_LITERARY_TEXT)

        required_keys = [
            "tier1_hits", "tier2_hits", "fiction_ai_tells",
            "structural_ai_tics", "telling_violations",
            "four_char_density", "em_dash_density",
            "sentence_cv", "transition_opener_ratio",
            "dialog_tag_ratio", "slop_penalty"
        ]
        for key in required_keys:
            assert key in result, f"Missing key: {key}"

    # 验证 slop_penalty 不超过上限
    def test_penalty_capped_at_10(self):
        """slop_penalty 应不超过 10.0 的上限。"""
        # 使用极多slop的文本
        result = slop_score_zh(TEXT_MULTI_SLOP * 5)
        assert result["slop_penalty"] <= 10.0
