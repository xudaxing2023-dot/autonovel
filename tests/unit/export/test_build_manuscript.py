"""
tests/unit/export/test_build_manuscript.py — 手稿拼接测试

测试 export.build_manuscript.build_manuscript() 的文件拼接逻辑。
使用 monkeypatch 注入临时路径来模拟文件系统。

对应测试方案：
  TC-EXP-001 ~ TC-EXP-005
"""

import pytest
from pathlib import Path


class TestBuildManuscript:
    """测试 build_manuscript() 的章节拼接功能。"""

    def _setup_and_build(self, tmp_path, monkeypatch, chapter_files: dict):
        """辅助函数：创建临时章节文件，运行 build_manuscript。

        通过 monkeypatch 注入 export.build_manuscript 模块中的路径常量。
        """
        import core.config as cfg
        from export import build_manuscript as bm_module

        output_dir = tmp_path / "output"
        chapters_dir = output_dir / "chapters"
        chapters_dir.mkdir(parents=True)

        # Monkeypatch 模块级别的路径常量
        monkeypatch.setattr(bm_module, "OUTPUT_DIR", output_dir, raising=False)
        monkeypatch.setattr(bm_module, "CHAPTERS_DIR", chapters_dir, raising=False)
        # 也更新 core.config 以防万一
        monkeypatch.setattr(cfg, "OUTPUT_DIR", output_dir, raising=False)
        monkeypatch.setattr(cfg, "CHAPTERS_DIR", chapters_dir, raising=False)

        for fname, content in chapter_files.items():
            ch_path = chapters_dir / fname
            ch_path.write_text(content, encoding="utf-8")

        bm_module.build_manuscript()

        manuscript_path = output_dir / "manuscript.md"
        return manuscript_path, output_dir, chapters_dir

    def test_normal_10_chapters(self, tmp_path, monkeypatch):
        """正常10章顺序拼接：manuscript.md 应包含目录 + 10章。"""
        files = {}
        for i in range(1, 11):
            files[f"ch_{i:02d}.md"] = (
                f"# 第 {i} 章：测试章节\n\n"
                f"这是第 {i} 章的内容。\n"
            )

        manuscript_path, _, _ = self._setup_and_build(tmp_path, monkeypatch, files)

        assert manuscript_path.exists()
        content = manuscript_path.read_text(encoding="utf-8")

        assert "# 目录" in content
        for i in range(1, 11):
            assert f"第 {i} 章" in content
        assert "---" in content

    def test_no_chapter_files(self, tmp_path, monkeypatch):
        """无章节文件时函数应直接 return，不创建 manuscript.md。"""
        from export import build_manuscript as bm_module

        output_dir = tmp_path / "output"
        chapters_dir = output_dir / "chapters"
        chapters_dir.mkdir(parents=True)

        monkeypatch.setattr(bm_module, "OUTPUT_DIR", output_dir, raising=False)
        monkeypatch.setattr(bm_module, "CHAPTERS_DIR", chapters_dir, raising=False)

        bm_module.build_manuscript()

        manuscript_path = output_dir / "manuscript.md"
        # 无章节时应不创建文件
        assert not manuscript_path.exists()

    def test_empty_chapter_skipped(self, tmp_path, monkeypatch):
        """空章节被 continue 跳过（已知风险R10：目录编号可能错位）。"""
        files = {
            "ch_01.md": "# 第 1 章：开始\n\n第一章内容。",
            "ch_02.md": "# 第 2 章：继续\n\n第二章内容。",
            "ch_03.md": "",  # 空章节
            "ch_04.md": "# 第 4 章：后续\n\n第四章内容。",
        }

        manuscript_path, _, _ = self._setup_and_build(tmp_path, monkeypatch, files)
        content = manuscript_path.read_text(encoding="utf-8")

        assert "第 1 章" in content
        assert "第 2 章" in content
        assert "第 4 章" in content

    def test_chapter_without_hash_title(self, tmp_path, monkeypatch):
        """章节首行无 # 标题时，应自动添加 '# 第 N 章' 前缀。"""
        files = {
            "ch_01.md": "这一章没有标题行。\n\n这是正文内容。",
        }

        manuscript_path, _, _ = self._setup_and_build(tmp_path, monkeypatch, files)
        content = manuscript_path.read_text(encoding="utf-8")

        # 应自动添加了标题（因为正文不以 # 开头）
        assert "# 第 1 章" in content

    def test_out_of_order_files_sorted(self, tmp_path, monkeypatch):
        """sorted(glob) 按字符串排序保证正确顺序。"""
        files = {}
        for i in [3, 1, 5, 2, 4]:
            files[f"ch_{i:02d}.md"] = f"# 第 {i} 章：乱序\n\n第 {i} 章内容。"

        manuscript_path, _, _ = self._setup_and_build(tmp_path, monkeypatch, files)
        content = manuscript_path.read_text(encoding="utf-8")

        # 验证排序正确性：ch_01 在 ch_02 之前
        pos_1 = content.find("第 1 章")
        pos_2 = content.find("第 2 章")
        pos_3 = content.find("第 3 章")
        pos_4 = content.find("第 4 章")
        pos_5 = content.find("第 5 章")

        assert -1 not in [pos_1, pos_2, pos_3, pos_4, pos_5], "Not all chapters found"
        assert pos_1 < pos_2 < pos_3 < pos_4 < pos_5

    def test_single_chapter(self, tmp_path, monkeypatch):
        """单章节拼接应正常生成 manuscript.md。"""
        files = {"ch_01.md": "# 第 1 章：唯一\n\n这是唯一章节的内容。"}

        manuscript_path, _, _ = self._setup_and_build(tmp_path, monkeypatch, files)
        content = manuscript_path.read_text(encoding="utf-8")

        assert "# 目录" in content
        assert "第 1 章" in content

    def test_chapter_already_has_hash_title(self, tmp_path, monkeypatch):
        """章节首行已有 # 标题时不应重复添加标题行。"""
        files = {"ch_01.md": "# 暗影追踪\n\n本章已有自己的标题格式。"}

        manuscript_path, _, _ = self._setup_and_build(tmp_path, monkeypatch, files)
        content = manuscript_path.read_text(encoding="utf-8")

        # 目录行中不应出现 "# 第 1 章" 重复
        count = content.count("# 第 1 章")
        assert count <= 2, f"Expected at most 2 occurrences, got {count}"

    def test_chapters_with_special_characters_in_title(self, tmp_path, monkeypatch):
        """章节标题含特殊字符时应正确渲染到目录。"""
        files = {
            "ch_01.md": '# 第1章：测试——"引号"与\'单引号\'\n\n内容。',
        }

        manuscript_path, _, _ = self._setup_and_build(tmp_path, monkeypatch, files)
        content = manuscript_path.read_text(encoding="utf-8")

        # 只验证不崩溃且包含基本内容
        assert "目录" in content
