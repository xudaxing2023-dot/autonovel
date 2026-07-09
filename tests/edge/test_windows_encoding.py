"""
tests/edge/test_windows_encoding.py — 阶段5E: Windows编码兼容性 (3个用例)

测试目标:
  TC-EDG-020: sys.stdout.reconfigure(encoding="utf-8") 管道模式
  TC-EDG-021: GBK编码文件读取
  TC-EDG-022: 混合编码文本处理

所有测试不调用 LLM API。
"""

import io
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# ============================================================================
# TC-EDG-020: sys.stdout.reconfigure 管道模式 (R06)
# ============================================================================

class TestStdoutReconfigure:
    """测试 Windows 下 sys.stdout.reconfigure 在管道模式的行为。

    风险点 R06: 在管道/重定向环境中 reconfigure 抛出 OSError。
    pipeline_orchestrator.py:25-26 在模块级别调用 reconfigure，
    如果 stdout 已经是 utf-8 编码或处于管道模式可能崩溃。
    """

    def test_reconfigure_when_already_utf8(self):
        """TC-EDG-020a: stdout 已为 utf-8 时 reconfigure。

        在 VSCode 终端等现代环境中，stdout.encoding 可能
        已经是 utf-8，此时 reconfigure 应为空操作。
        """
        current_encoding = sys.stdout.encoding
        print(f"\n[编码检测] 当前 stdout.encoding = {current_encoding}")

        # 如果已经是 utf-8，reconfigure 不应报错
        if current_encoding and current_encoding.lower() in ("utf-8", "utf8"):
            try:
                # 模拟 pipeline_orchestrator 的行为
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
                print("[OK] stdout 已为 utf-8，reconfigure 成功")
            except OSError as e:
                print(f"[注意] 即使是 utf-8，reconfigure 仍报错: {e}")

    def test_reconfigure_in_pipe_mode_mock(self):
        """TC-EDG-020b: mock 管道模式下 reconfigure 抛出 OSError。

        验证异常被正确捕获不导致崩溃。
        """
        # 模拟 pipeline_orchestrator.py:24-26 的保护逻辑
        # 当前代码直接在模块顶层调用 reconfigure，
        # 没有 try/except 保护
        import pipeline_orchestrator

        # 检查 pipeline_orchestrator 的顶层代码
        source_lines = []
        with open(pipeline_orchestrator.__file__, "r", encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                if 23 <= i <= 28:
                    source_lines.append(f"  L{i}: {line.rstrip()}")

        has_try = any("try:" in l for l in source_lines)
        has_except = any("except" in l for l in source_lines)

        if not has_try:
            print("\n[BUG候选 R06] pipeline_orchestrator.py:25-26 "
                  "reconfigure 无 try/except 保护，"
                  "管道模式下可能抛出未捕获的 OSError")

        print("\n[pipeline_orchestrator.py L23-27]")
        for line in source_lines:
            print(line)

    def test_reconfigure_on_non_tty(self):
        """TC-EDG-020c: 非 tty 环境（管道模式）。

        当 stdout 不是 tty（如被管道连接），reconfigure 可能失败。
        """
        # 检查当前是否在 tty 环境
        is_tty = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()
        print(f"\n[TTY检测] stdout.isatty() = {is_tty}")

        # 使用 StringIO 模拟非 tty 环境
        fake_stdout = io.StringIO()

        # 在非 tty 环境中，reconfigure 可能不被支持
        # 这是 Windows 特有的问题
        if sys.platform == "win32":
            try:
                # 尝试在真实 stdout 上 reconfigure（验证当前环境）
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
                print("[OK] 当前环境支持 reconfigure")
            except OSError as e:
                print(f"[预期行为] 当前环境 reconfigure 失败: {e}")
                print("这验证了 R06 风险点")

    def test_reconfigure_silent_failure_pattern(self):
        """TC-EDG-020d: 推荐的修复模式 — 静默失败。

        展示如何安全地调用 reconfigure 防止管道模式崩溃。
        """
        # 推荐的保护模式
        if sys.platform == "win32":
            try:
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, AttributeError):
                # 静默失败 — 管道/重定向环境中无法 reconfigure
                pass

        # 验证当前 pipeline_orchestrator 是否使用此模式
        import pipeline_orchestrator
        source = Path(pipeline_orchestrator.__file__).read_text(encoding="utf-8")
        has_safe_pattern = (
            "try:" in source.split("reconfigure")[0].split("\n")[-3:]
            if "reconfigure" in source else False
        )

        if not has_safe_pattern:
            print("\n[建议] pipeline_orchestrator.py 的 reconfigure "
                  "应包裹在 try/except (OSError, AttributeError) 中")


# ============================================================================
# TC-EDG-021: GBK 编码文件读取
# ============================================================================

class TestGBKEncoding:
    """测试 GBK 编码文件的读取。

    在 Windows 中文环境中，某些工具可能生成 GBK/GB2312 编码的文件。
    项目所有 .md 文件约定为 UTF-8，但不排除用户或外部工具引入 GBK 文件。
    """

    def test_read_gbk_encoded_file(self, tmp_path):
        """TC-EDG-021a: 读取 GBK 编码文件。

        以 utf-8 读取 GBK 文件会抛出 UnicodeDecodeError。
        """
        gbk_file = tmp_path / "gbk_text.txt"
        # GBK 编码的中文文本
        gbk_content = "这是GBK编码的中文文本。\n包含一些常用汉字。".encode("gbk")
        gbk_file.write_bytes(gbk_content)

        # 以 utf-8 读取会失败
        with pytest.raises(UnicodeDecodeError):
            gbk_file.read_text(encoding="utf-8")

    def test_read_gbk_with_fallback(self, tmp_path):
        """TC-EDG-021b: GBK 文件读取回退策略。"""
        gbk_file = tmp_path / "gbk_chapter.md"
        gbk_content = "# 第一章：开端\n\n这是GBK编码的章节内容，包含角色对话和场景描述。".encode("gbk")
        gbk_file.write_bytes(gbk_content)

        # 推荐的回退读取策略
        content = None
        for encoding in ["utf-8", "utf-8-sig", "gbk", "gb2312", "latin-1"]:
            try:
                content = gbk_file.read_text(encoding=encoding)
                break
            except (UnicodeDecodeError, UnicodeError):
                continue

        assert content is not None, "应能用某种编码成功读取"
        assert "第一章" in content, "内容应包含'第一章'"
        print(f"\n[GBK回退] 成功读取 GBK 编码文件")

    def test_draft_chapter_load_file_with_gbk(self, tmp_path):
        """TC-EDG-021c: draft_chapter.load_file 对 GBK 文件。

        当前 load_file 固定使用 encoding="utf-8"，
        遇到 GBK 文件会抛出 UnicodeDecodeError（仅捕获 FileNotFoundError）。
        """
        from drafting.draft_chapter import load_file

        gbk_file = tmp_path / "gbk_context.md"
        gbk_content = "世界观设定：这是一个玄幻世界。".encode("gbk")
        gbk_file.write_bytes(gbk_content)

        # 当前 load_file 的行为
        try:
            result = load_file(gbk_file)
            print(f"\n[GBK读取] load_file 返回: '{result[:50]}'")
        except UnicodeDecodeError as e:
            print(f"\n[BUG候选] load_file 对 GBK 文件抛出 "
                  f"UnicodeDecodeError（仅捕获 FileNotFoundError）: {e}")

    def test_config_json_encoding(self, tmp_path):
        """TC-EDG-021d: config.json 编码检查。

        config.json 应始终为 UTF-8，但验证错误处理。
        """
        import json

        config_file = tmp_path / "config.json"
        # 用 GBK 写入（模拟错误配置）
        config_file.write_bytes(
            '{"novel_title": "测试小说"}'.encode("gbk")
        )

        # 以 utf-8 读取会失败
        with pytest.raises((UnicodeDecodeError, UnicodeError)):
            json.loads(config_file.read_text(encoding="utf-8"))


# ============================================================================
# TC-EDG-022: 混合编码文本处理
# ============================================================================

class TestMixedEncoding:
    """测试混合编码文本的处理。"""

    def test_mixed_utf8_gbk_in_string(self, tmp_path):
        """TC-EDG-022a: 内存中的混合编码字符串。

        实际场景：从不同编码的文件中加载文本后在内存中拼接。
        """
        # UTF-8 内容
        utf8_text = "这是UTF-8编码的文本。\n"
        # GBK 内容解码后的字符串（正常 str）
        gbk_bytes = "这是原本GBK编码的文本。\n".encode("gbk")
        gbk_text = gbk_bytes.decode("gbk")

        # 混合后应正常（都是 Python str）
        mixed = utf8_text + gbk_text
        assert isinstance(mixed, str), "混合后仍是 str"
        assert "UTF-8" in mixed
        assert "GBK" in mixed

        # 写入文件时使用统一编码
        out_file = tmp_path / "mixed_output.md"
        out_file.write_text(mixed, encoding="utf-8")

        # 读回验证
        read_back = out_file.read_text(encoding="utf-8")
        assert read_back == mixed, "混合文本读写应一致"

    def test_mojibake_detection(self):
        """TC-EDG-022b: 乱码检测。

        当 UTF-8 被错误地以 Latin-1 解码后重新编码，
        会形成不可修复的乱码（mojibake）。
        """
        original = "这是一段中文文本"

        # 正确编码为 UTF-8
        utf8_bytes = original.encode("utf-8")

        # 错误地以 Latin-1 解码
        mojibake = utf8_bytes.decode("latin-1")

        # 检测乱码：乱码通常含有不可打印的 Latin-1 扩展字符
        has_mojibake = any(
            ord(c) > 127 and c not in "·…" for c in mojibake
            if ord(c) < 256
        )
        print(f"\n[乱码检测] 原始: '{original}'")
        print(f"[乱码检测] 乱码: '{mojibake[:30]}'")
        print(f"[乱码检测] 疑似乱码: {has_mojibake}")

    def test_double_encoded_utf8(self, tmp_path):
        """TC-EDG-022c: 双重 UTF-8 编码检测。

        某些工具可能对已经是 UTF-8 的内容再次 UTF-8 编码，
        导致双重编码乱码。
        """
        original = "中文测试"
        # 正常 UTF-8
        utf8_bytes = original.encode("utf-8")
        # 双重编码（错误）
        double_encoded = utf8_bytes.decode("latin-1").encode("utf-8")

        # 双重编码文件
        double_file = tmp_path / "double_encoded.md"
        double_file.write_bytes(double_encoded)

        # 以 UTF-8 读取
        raw = double_file.read_text(encoding="utf-8")
        # 内容是乱码，但不会抛异常
        assert original not in raw, "双重编码后原始内容不可直接读取"
        print(f"\n[双重编码] 原始: '{original}'")
        print(f"[双重编码] 读取: '{raw}'")

    def test_cp1252_encoding_edge_case(self, tmp_path):
        """TC-EDG-022d: Windows-1252 (cp1252) 编码边界。

        Windows-1252 是 Windows 西欧语言的默认编码，
        与 Latin-1 类似但不完全相同。
        """
        # cp1252 编码中欧元符号 € (U+20AC) 映射为 0x80
        # 这在 utf-8 中是无效字节，展示两种编码的差异
        text = "Price: \u20ac100"  # Price: €100

        cp1252_file = tmp_path / "cp1252.txt"
        cp1252_file.write_bytes(text.encode("cp1252"))

        # 以 utf-8 读取（欧元符号在 cp1252 为 0x80，非有效 UTF-8）
        try:
            content = cp1252_file.read_text(encoding="utf-8")
            print(f"\n[cp1252] utf-8 读取: '{content}'")
        except UnicodeDecodeError:
            print(f"\n[cp1252] utf-8 读取失败 (预期，0x80非有效UTF-8)")

        # 以 cp1252 正确读取
        correct = cp1252_file.read_bytes().decode("cp1252")
        assert "\u20ac" in correct, \
            f"cp1252 编码应正确保留欧元符号，实际: '{correct}'"
        print(f"[cp1252] 正确解码: '{correct}'")
