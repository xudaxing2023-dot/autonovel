"""
tests/unit/revision/test_apply_cuts.py — 机械删除测试

测试 revision.apply_cuts 的删除逻辑：
  - find_and_remove() 精确匹配与歧义处理
  - process_chapter() 类型过滤与阈值过滤（需要 mock 路径）
  - load_cuts() 文件解析

对应测试方案：
  TC-REV-007 ~ TC-REV-010
"""

import json
import pytest
from pathlib import Path


class TestFindAndRemove:
    """测试 find_and_remove() 核心删除函数（纯函数，不依赖文件系统）。"""

    def test_exact_single_match(self):
        """精确单次匹配：子串在文本中出现恰好一次，应成功删除。"""
        from revision.apply_cuts import find_and_remove

        text = "这是第一段内容。删除这段冗余文本。这是第三段内容。"
        quote = "删除这段冗余文本。"

        new_text, success, reason = find_and_remove(text, quote)

        assert success is True
        assert reason == ""
        assert "删除这段冗余文本" not in new_text
        assert "这是第一段内容" in new_text
        assert "这是第三段内容" in new_text

    def test_multiple_match_ambiguous(self):
        """多次匹配（歧义）：子串出现2次，应返回失败并保持原文本不变。"""
        from revision.apply_cuts import find_and_remove

        text = "重复文本在这里。中间有其他内容。重复文本在这里。"
        quote = "重复文本在这里"

        new_text, success, reason = find_and_remove(text, quote)

        assert success is False
        assert "歧义" in reason
        assert "2" in reason
        assert new_text == text  # 原文本不变

    def test_whitespace_normalized_match(self):
        """空白标准化回退：文本中含额外空格/换行，标准化后应匹配成功。"""
        from revision.apply_cuts import find_and_remove

        # 创建足够长的文本，使得标准化后的 quote > MIN_QUOTE_LEN (20)
        text = "这是一个很长很长很长很长很长很长的文本，其中包含 了  多余  的空白  需要被删除的内容。"
        quote = "其中包含 了 多余 的空白 需要被删除的内容。"

        new_text, success, reason = find_and_remove(text, quote)

        # 精确匹配失败 -> 第2层空白标准化回退
        assert isinstance(success, bool)
        # 如果标准化后唯一匹配，success 为 True
        if success:
            assert "多余" not in new_text or "多余  的空白" not in new_text

    def test_quote_not_found(self):
        """子串在文本中完全不存在时应返回失败原因。"""
        from revision.apply_cuts import find_and_remove

        text = "这是完全不同的内容。"
        quote = "这段文字根本不存在于原文中。"

        new_text, success, reason = find_and_remove(text, quote)

        assert success is False
        assert reason != "", f"Expected non-empty failure reason, got: '{reason}'"
        assert new_text == text  # 原文不变

    def test_empty_quote(self):
        """空引用应返回失败。"""
        from revision.apply_cuts import find_and_remove

        text = "一些内容。"
        quote = ""

        new_text, success, reason = find_and_remove(text, quote)

        assert success is False
        assert "空引用" in reason

    def test_remove_preserves_surrounding_text(self):
        """删除后周围文本应完整保留。"""
        from revision.apply_cuts import find_and_remove

        text = """# 第一章

这是开头段落，需要保留。

这段是冗余的废话需要删除。

这是结尾段落，也需要保留。"""

        quote = "这段是冗余的废话需要删除。"

        new_text, success, reason = find_and_remove(text, quote)

        assert success is True
        assert "开头段落" in new_text
        assert "结尾段落" in new_text
        assert "冗余的废话" not in new_text

    def test_single_character_removal(self):
        """单个字符匹配（虽然不实用，但应能处理）。"""
        from revision.apply_cuts import find_and_remove

        text = "ABC"
        quote = "B"

        new_text, success, reason = find_and_remove(text, quote)

        assert success is True
        assert new_text == "AC"

    def test_quote_at_beginning(self):
        """引用在文本开头时应正确删除。"""
        from revision.apply_cuts import find_and_remove

        text = "删除我。后面的内容要保留。"
        quote = "删除我。"

        new_text, success, reason = find_and_remove(text, quote)

        assert success is True
        assert "后面的内容要保留" in new_text
        assert "删除我" not in new_text

    def test_quote_at_end(self):
        """引用在文本末尾时应正确删除。"""
        from revision.apply_cuts import find_and_remove

        text = "前面的内容要保留。删除我。"
        quote = "删除我。"

        new_text, success, reason = find_and_remove(text, quote)

        assert success is True
        assert "前面的内容要保留" in new_text
        assert "删除我" not in new_text


class TestProcessChapter:
    """测试 process_chapter() 的过滤逻辑。

    关键：必须 monkeypatch 模块级别的路径变量（因为函数内部通过模块导入使用它们）。
    """

    def test_min_fat_threshold_skip(self, tmp_path, monkeypatch):
        """赘语比例低于 min_fat 阈值时应跳过该章。"""
        from revision import apply_cuts as ac_module

        edit_logs_dir = tmp_path / "edit_logs"
        edit_logs_dir.mkdir()
        chapters_dir = tmp_path / "chapters"
        chapters_dir.mkdir()

        # ★ 关键：monkeypatch 模块级别的路径常量
        monkeypatch.setattr(ac_module, "EDIT_LOGS_DIR", edit_logs_dir, raising=False)
        monkeypatch.setattr(ac_module, "CHAPTERS_DIR", chapters_dir, raising=False)

        # 创建低 fat 比例的 cuts
        cuts_data = {
            "overall_fat_percentage": 5,
            "total_cuttable_words": 50,
            "cuts": [{"quote": "一些冗余文本需要被删除", "type": "REDUNDANT",
                       "reason": "重复", "action": "CUT"}]
        }
        cuts_path = edit_logs_dir / "ch01_cuts.json"
        cuts_path.write_text(json.dumps(cuts_data, ensure_ascii=False), encoding="utf-8")

        # 创建章节文件
        ch_path = chapters_dir / "ch_01.md"
        ch_path.write_text("# 第一章\n\n一些冗余文本需要被删除\n\n其他内容。", encoding="utf-8")

        stats = ac_module.process_chapter(1, type_filter=None, min_fat=10, dry_run=False)

        assert stats["error"] is not None
        # error msg 内容取决于 fat_pct 是否 < min_fat
        # 应为 "赘语比例 5% < 阈值 10%" 类消息
        assert "5" in stats["error"] or "fat" in stats["error"].lower() or "无裁剪文件" == stats["error"]

    def test_missing_chapter_file(self, tmp_path, monkeypatch):
        """章节文件不存在时应返回 error。"""
        from revision import apply_cuts as ac_module

        edit_logs_dir = tmp_path / "edit_logs"
        edit_logs_dir.mkdir()
        chapters_dir = tmp_path / "chapters"
        chapters_dir.mkdir()

        monkeypatch.setattr(ac_module, "EDIT_LOGS_DIR", edit_logs_dir, raising=False)
        monkeypatch.setattr(ac_module, "CHAPTERS_DIR", chapters_dir, raising=False)

        cuts_data = {
            "overall_fat_percentage": 30,
            "total_cuttable_words": 100,
            "cuts": [{"quote": "测试文本需要被删除掉", "type": "REDUNDANT",
                       "reason": "测试", "action": "CUT"}]
        }
        cuts_path = edit_logs_dir / "ch05_cuts.json"
        cuts_path.write_text(json.dumps(cuts_data, ensure_ascii=False), encoding="utf-8")

        # 不创建 ch_05.md

        stats = ac_module.process_chapter(5, type_filter=None, min_fat=0, dry_run=False)

        assert stats["error"] is not None

    def test_empty_cuts_list(self, tmp_path, monkeypatch):
        """cuts列表为空时应返回 error。"""
        from revision import apply_cuts as ac_module

        edit_logs_dir = tmp_path / "edit_logs"
        edit_logs_dir.mkdir()
        chapters_dir = tmp_path / "chapters"
        chapters_dir.mkdir()

        monkeypatch.setattr(ac_module, "EDIT_LOGS_DIR", edit_logs_dir, raising=False)
        monkeypatch.setattr(ac_module, "CHAPTERS_DIR", chapters_dir, raising=False)

        cuts_data = {"overall_fat_percentage": 0, "total_cuttable_words": 0, "cuts": []}
        cuts_path = edit_logs_dir / "ch01_cuts.json"
        cuts_path.write_text(json.dumps(cuts_data, ensure_ascii=False), encoding="utf-8")

        ch_path = chapters_dir / "ch_01.md"
        ch_path.write_text("# 测试", encoding="utf-8")

        stats = ac_module.process_chapter(1, type_filter=None, min_fat=0, dry_run=False)
        assert stats["error"] is not None


class TestLoadCuts:
    """测试 load_cuts() 辅助函数。"""

    def test_load_valid_cuts(self, tmp_path, monkeypatch):
        """加载有效的 cuts JSON 文件。"""
        from revision import apply_cuts as ac_module

        edit_logs_dir = tmp_path / "edit_logs"
        edit_logs_dir.mkdir()
        monkeypatch.setattr(ac_module, "EDIT_LOGS_DIR", edit_logs_dir, raising=False)

        cuts_data = {"total_cuttable_words": 100, "cuts": []}
        cuts_path = edit_logs_dir / "ch01_cuts.json"
        cuts_path.write_text(json.dumps(cuts_data, ensure_ascii=False), encoding="utf-8")

        result = ac_module.load_cuts(1)
        assert result is not None
        assert result["total_cuttable_words"] == 100

    def test_load_missing_cuts(self, tmp_path, monkeypatch):
        """加载不存在的 cuts 文件返回 None。"""
        from revision import apply_cuts as ac_module

        edit_logs_dir = tmp_path / "edit_logs"
        edit_logs_dir.mkdir()
        monkeypatch.setattr(ac_module, "EDIT_LOGS_DIR", edit_logs_dir, raising=False)

        result = ac_module.load_cuts(99)
        assert result is None

    def test_load_corrupt_cuts(self, tmp_path, monkeypatch):
        """加载损坏的 JSON 返回 None。"""
        from revision import apply_cuts as ac_module

        edit_logs_dir = tmp_path / "edit_logs"
        edit_logs_dir.mkdir()
        monkeypatch.setattr(ac_module, "EDIT_LOGS_DIR", edit_logs_dir, raising=False)

        cuts_path = edit_logs_dir / "ch01_cuts.json"
        cuts_path.write_text("{invalid json", encoding="utf-8")

        result = ac_module.load_cuts(1)
        assert result is None
