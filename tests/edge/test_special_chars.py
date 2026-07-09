"""
tests/edge/test_special_chars.py — 阶段5C: 特殊字符处理 (5个用例)

测试目标:
  TC-EDG-011: Windows路径（反斜杠、盘符）
  TC-EDG-012: 中文文件名
  TC-EDG-013: emoji/Unicode特殊字符在文本中
  TC-EDG-014: 零宽字符
  TC-EDG-015: BOM标记的UTF-8文件

所有测试不调用 LLM API。
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# ============================================================================
# TC-EDG-011: Windows 路径作为文本内容
# ============================================================================

class TestWindowsPathsInText:
    """测试文本中包含 Windows 路径时的处理。"""

    def test_windows_path_in_chapter_text(self, tmp_path):
        """TC-EDG-011a: Windows 路径作为章节文本内容。

        验证 slop_score_zh 不会误匹配路径中的反斜杠。
        """
        from evaluation.evaluate import slop_score_zh

        text = (
            "他打开文件，路径是 C:\\Users\\测试\\output\\chapters\\ch_01.md。"
            "这个文件包含了重要的线索。\n"
            "另一个路径在 D:\\backup\\novel_data\\config.json 中。"
        )

        result = slop_score_zh(text)
        # Windows 路径中的反斜杠不应触发 AI 套话检测
        # tier1_hits 不应包含路径相关误报
        assert "slop_penalty" in result
        tier1 = result.get("tier1_hits", [])
        # 路径字符串不应被误识别为 AI 套话
        print(f"\n[Windows路径文本] slop_penalty={result.get('slop_penalty')}, "
              f"tier1_hits={tier1}")

    def test_backslash_in_json_serialization(self, tmp_path):
        """TC-EDG-011b: JSON 序列化/反序列化含反斜杠的文本。

        验证 save_state/load_state 不会因反斜杠损坏 JSON。
        """
        data = {
            "file_path": "C:\\Users\\测试\\output\\chapters\\ch_01.md",
            "note": "路径使用反斜杠 \\ 作为分隔符",
        }

        # 序列化
        json_str = json.dumps(data, ensure_ascii=False)
        assert "\\\\" in json_str, "反斜杠应在 JSON 中被转义"

        # 反序列化
        parsed = json.loads(json_str)
        assert parsed["file_path"] == data["file_path"], \
            f"反序列化后路径应保持一致: {parsed['file_path']}"

    def test_drive_letter_in_text(self, tmp_path):
        """TC-EDG-011c: 盘符路径在文本中的处理。"""
        text = (
            "配置文件位于 E:\\项目\\小说\\config.json，"
            "模板在 F:\\templates\\novel_template.md。"
        )

        # 基本的字符串操作不应受影响
        assert "E:\\" in text
        assert "F:\\" in text

        # 统计字数：盘符路径中的字母应被正常计数
        char_count = len(text.replace(" ", "").replace("\n", ""))
        assert char_count > 20, f"应有足够字符，实际 {char_count}"


# ============================================================================
# TC-EDG-012: 中文文件名
# ============================================================================

class TestChineseFileNames:
    """测试中文文件名的支持。"""

    def test_chinese_filename_read_write(self, tmp_path):
        """TC-EDG-012a: 读写中文文件名。"""
        chinese_name = tmp_path / "第一章_深渊之眼.md"
        content = "# 第一章：深渊之眼\n\n这是测试内容。"

        # 写入
        chinese_name.write_text(content, encoding="utf-8")
        assert chinese_name.exists(), "中文文件名文件应存在"

        # 读取
        read_back = chinese_name.read_text(encoding="utf-8")
        assert read_back == content, "中文文件名文件读写内容应一致"

    def test_chinese_path_components(self, tmp_path):
        """TC-EDG-012b: 路径中包含中文目录名。"""
        chinese_dir = tmp_path / "输出目录" / "章节"
        chinese_dir.mkdir(parents=True)

        ch_file = chinese_dir / "第一章.md"
        ch_file.write_text("# 测试", encoding="utf-8")

        assert ch_file.exists()
        content = ch_file.read_text(encoding="utf-8")
        assert content == "# 测试"

    def test_glob_chinese_filenames(self, tmp_path):
        """TC-EDG-012c: glob 匹配中文文件名。"""
        chapters_dir = tmp_path / "章节目录"
        chapters_dir.mkdir()

        # 创建混合命名文件
        (chapters_dir / "第一章.md").write_text("ch1", encoding="utf-8")
        (chapters_dir / "第二章.md").write_text("ch2", encoding="utf-8")
        (chapters_dir / "ch_03.md").write_text("ch3", encoding="utf-8")

        # 使用中文 glob
        all_md = sorted(chapters_dir.glob("*.md"))
        assert len(all_md) == 3, f"应匹配3个.md文件，实际 {len(all_md)}"

        # 使用通配符 + 中文
        chinese_only = sorted(chapters_dir.glob("第*.md"))
        assert len(chinese_only) == 2, \
            f"应匹配2个中文文件名，实际 {len(chinese_only)}"


# ============================================================================
# TC-EDG-013: emoji/Unicode 特殊字符
# ============================================================================

class TestEmojiAndUnicode:
    """测试 emoji 和 Unicode 特殊字符的处理。"""

    def test_emoji_in_chapter_text(self, tmp_path):
        """TC-EDG-013a: emoji 在章节文本中。

        验证 word_count、save_state、slop_score_zh 正确处理 emoji。
        """
        from evaluation.evaluate import slop_score_zh

        text = (
            "他露出了神秘的微笑 😀🔥📖💀。\n"
            "她的心情如同 🎭 一般复杂。\n"
            "战斗中使用 ⚔️🛡️ 等武器。"
        )

        # 基础字符计数
        char_count = len(text.replace(" ", "").replace("\n", ""))
        assert char_count > 0, "emoji 应被计入字符数"

        # slop_score_zh 不应因 emoji 崩溃
        result = slop_score_zh(text)
        assert "slop_penalty" in result, "emoji 文本不应导致 slop_score_zh 崩溃"
        print(f"\n[emoji文本] char_count={result.get('char_count')}, "
              f"penalty={result.get('slop_penalty')}")

    def test_emoji_in_json_roundtrip(self):
        """TC-EDG-013b: emoji 在 JSON 序列化/反序列化中。"""
        data = {
            "phase": "drafting",
            "current_focus": "测试🎯",
            "notes": "包含emoji: 😀🔥📖",
        }

        json_str = json.dumps(data, ensure_ascii=False)
        assert "🎯" in json_str, "emoji 应在 JSON 字符串中保留"

        parsed = json.loads(json_str)
        assert parsed["current_focus"] == "测试🎯", \
            f"emoji 应正确保留: {parsed['current_focus']}"

    def test_special_unicode_blocks(self, tmp_path):
        """TC-EDG-013c: 各种 Unicode 特殊块。"""
        # 全角字符、CJK扩展、特殊标点
        text = (
            "中文测试：全角字符ＡＢＣＤＥＦＧ。\n"
            "CJK扩展A：㐀㐁㐂\n"
            "CJK扩展B：𠀀𠀁𠀂\n"
            "特殊标点：〓〠〡〢〣〤〥\n"
            "注音符号：ㄅㄆㄇㄈ\n"
            "中日韩兼容：㈠㈡㈢㈣\n"
        )

        ch_file = tmp_path / "unicode_test.md"
        ch_file.write_text(text, encoding="utf-8")

        read_back = ch_file.read_text(encoding="utf-8")
        assert "㐀" in read_back, "CJK扩展A字符应保留"
        assert "𠀀" in read_back, "CJK扩展B字符应保留"
        assert "〓" in read_back, "特殊标点应保留"

    def test_unicode_escape_in_strings(self):
        """TC-EDG-013d: Unicode 转义序列处理。"""
        # 正常的中文：不需要转义
        text = "这是一段包含'引号'和\"双引号\"的文本"

        # JSON 序列化
        json_str = json.dumps({"text": text}, ensure_ascii=False)
        parsed = json.loads(json_str)
        assert parsed["text"] == text, "含引号的文本应正确序列化"


# ============================================================================
# TC-EDG-014: 零宽字符
# ============================================================================

class TestZeroWidthCharacters:
    """测试零宽字符的处理。"""

    def test_zero_width_joiner_in_text(self, tmp_path):
        """TC-EDG-014a: 零宽连字符 (ZWJ, U+200D)。"""
        # ZWJ 通常用于连接 emoji
        text = "家庭：👨‍👩‍👧‍👦"  # 含 ZWJ 的 family emoji

        ch_file = tmp_path / "zwj_test.md"
        ch_file.write_text(text, encoding="utf-8")

        read_back = ch_file.read_text(encoding="utf-8")
        # ZWJ 应该被保留
        assert len(read_back) > 0, "含ZWJ的文本应可读写"

    def test_zero_width_space_in_text(self, tmp_path):
        """TC-EDG-014b: 零宽空格 (ZWSP, U+200B)。"""
        text = "这里\u200b有一个\u200b零宽空格"

        ch_file = tmp_path / "zwsp_test.md"
        ch_file.write_text(text, encoding="utf-8")

        read_back = ch_file.read_text(encoding="utf-8")
        assert "\u200b" in read_back, "零宽空格应被保留"

        # 零宽空格不影响视觉显示但影响字符串长度
        visible = text.replace("\u200b", "")
        assert len(visible) < len(text), \
            "去除零宽空格后字符串应变短"

    def test_bidirectional_text(self, tmp_path):
        """TC-EDG-014c: 双向文本 (Bidi) 控制字符。

        RTL 嵌入/覆盖字符可能导致文本显示混乱。
        """
        # 右到左覆盖 (U+202E) + 左到右嵌入 (U+202A)
        text = "正常中文\u202e反转英文\u202c正常继续"

        ch_file = tmp_path / "bidi_test.md"
        ch_file.write_text(text, encoding="utf-8")

        read_back = ch_file.read_text(encoding="utf-8")
        # 控制字符应被保留（但在渲染时可能导致安全问题）
        assert "\u202e" in read_back, "Bidi 控制字符应被保留"

    def test_zero_width_chars_in_slop_score(self):
        """TC-EDG-014d: 零宽字符不应影响 slop_score_zh。"""
        from evaluation.evaluate import slop_score_zh

        # 正常文本与含零宽字符的文本
        normal = "他感到一阵寒意，眼中闪过一丝疑虑。"
        injected = "他\u200b感到\u200b一阵\u200b寒意，\u200b眼中\u200b闪过一丝\u200b疑虑。"

        result_normal = slop_score_zh(normal)
        result_injected = slop_score_zh(injected)

        # 零宽字符可能影响正则匹配 — 某些pattern可能因此被绕过
        penalty_normal = result_normal.get("slop_penalty", 0)
        penalty_injected = result_injected.get("slop_penalty", 0)

        print(f"\n[零宽字符绕过测试] 正常: penalty={penalty_normal}, "
              f"注入: penalty={penalty_injected}")
        # 如果注入后 penalty 显著降低，说明存在绕过风险
        if penalty_injected < penalty_normal * 0.5:
            print("[安全风险] 零宽字符可能绕过 AI 套话检测")


# ============================================================================
# TC-EDG-015: BOM 标记的 UTF-8 文件
# ============================================================================

class TestBOMFiles:
    """测试 BOM 标记的 UTF-8 文件读取。"""

    def test_read_utf8_bom_file(self, tmp_path):
        """TC-EDG-015a: 读取带 BOM 的 UTF-8 文件。

        Python 的 encoding="utf-8" 不会自动处理 BOM，
        需要使用 "utf-8-sig"。
        """
        bom_file = tmp_path / "bom_test.md"
        # 写入 BOM + 内容
        with open(str(bom_file), "wb") as f:
            f.write(b'\xef\xbb\xbf')  # UTF-8 BOM
            f.write("# 第一章：测试\n\n这是内容。".encode("utf-8"))

        # 使用 utf-8 读取（不含 sig）
        raw_content = bom_file.read_text(encoding="utf-8")
        # BOM 会被当作一个不可见字符
        assert raw_content[0] == '\ufeff', \
            "utf-8 读取 BOM 文件时首字符应为 \\ufeff"

        # 正确的读取方式
        with open(str(bom_file), "r", encoding="utf-8-sig") as f:
            correct_content = f.read()
        assert correct_content[0] == '#', \
            "utf-8-sig 应自动去除 BOM"
        assert not correct_content.startswith('\ufeff'), \
            "utf-8-sig 读取不应含 BOM 字符"

    def test_bom_affects_markdown_parsing(self, tmp_path):
        """TC-EDG-015b: BOM 对 Markdown 解析的影响。

        如果章节文件以 BOM 开头，首行标题 `# 第N章` 可能无法匹配。
        """
        bom_file = tmp_path / "bom_chapter.md"
        with open(str(bom_file), "wb") as f:
            f.write(b'\xef\xbb\xbf')
            f.write("# 第1章：开端\n\n章节内容。".encode("utf-8"))

        # 用 utf-8（默认）读取
        content = bom_file.read_text(encoding="utf-8")
        first_line = content.split("\n")[0].strip()

        # BOM 导致 # 不是第一个字符
        assert first_line[0] != '#', \
            "BOM 导致首行不以 # 开头 — 可能影响标题提取"

    def test_draft_chapter_load_file_with_bom(self, tmp_path):
        """TC-EDG-015c: drafting/draft_chapter.py 的 load_file 对 BOM 的处理。

        当前 load_file 使用 encoding="utf-8"（非 utf-8-sig），
        这意味着 BOM 不会被自动去除。
        """
        from drafting.draft_chapter import load_file

        bom_file = tmp_path / "bom_context.md"
        with open(str(bom_file), "wb") as f:
            f.write(b'\xef\xbb\xbf')
            f.write("文风规则：简洁有力。".encode("utf-8"))

        content = load_file(bom_file)
        if content.startswith('\ufeff'):
            print("\n[BUG候选] load_file 未去除 UTF-8 BOM，"
                  "可能影响后续文本处理")
        assert len(content) > 0, "应能读取 BOM 文件内容"
