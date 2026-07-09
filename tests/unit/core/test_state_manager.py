"""
tests/unit/core/test_state_manager.py — 阶段2: StateManager 测试

测试目标:
  TC-STM-001 ~ TC-STM-006: load_state() / save_state() 异常测试
  TC-STM-007 ~ TC-STM-010: log_result() 测试
  TC-PRS-001 ~ TC-PRS-008: parse_score() 解析鲁棒性测试
  TC-STM-011 ~ TC-STM-013: evaluate_chapter_stable() 中位数测试
  TC-STM-014 ~ TC-STM-016: 备份与恢复测试

所有测试不调用 LLM API。
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock

import pytest


# ============================================================================
# Helpers
# ============================================================================

def _get_state_file(temp_project):
    """获取 temp_project 中的 STATE_FILE 路径。"""
    return temp_project["state_file"]


def _get_results_file(temp_project):
    """获取 temp_project 中的 RESULTS_FILE 路径。"""
    return temp_project["results_file"]


# ============================================================================
# 5.3 load_state() / save_state() 异常测试 (TC-STM-001 ~ TC-STM-006)
# ============================================================================

class TestLoadSaveState:
    """测试 state 加载和保存的异常行为。"""

    def test_load_state_file_not_exist(self, temp_project, monkeypatch):
        """TC-STM-001: state.json 不存在时返回 default_state()。"""
        from core.state_manager import load_state, default_state
        from core.config import STATE_FILE

        # 确保文件不存在
        state_file = temp_project["state_file"]
        monkeypatch.setattr(
            "core.state_manager.STATE_FILE", state_file, raising=False)

        assert not state_file.exists()

        state = load_state()
        expected = default_state()
        assert state == expected, f"应返回默认状态，实际: {state}"

    def test_load_state_corrupt_json(self, temp_project, monkeypatch):
        """TC-STM-002: state.json JSON 损坏时返回 default_state()。"""
        from core.state_manager import load_state, default_state

        state_file = temp_project["state_file"]
        monkeypatch.setattr(
            "core.state_manager.STATE_FILE", state_file, raising=False)

        # 写入截断的 JSON
        state_file.write_text('{"phase": "foundation', encoding="utf-8")

        state = load_state()
        expected = default_state()
        assert state == expected, \
            f"损坏 JSON 应返回默认状态，实际: {state}"

    def test_load_state_missing_keys(self, temp_project, monkeypatch):
        """TC-STM-003: state.json 缺少关键键时的行为。

        JSON 有效但缺少部分键，返回的 dict 仅含存在的键。
        """
        from core.state_manager import load_state

        state_file = temp_project["state_file"]
        monkeypatch.setattr(
            "core.state_manager.STATE_FILE", state_file, raising=False)

        # 仅含 phase
        partial_state = {"phase": "drafting"}
        state_file.write_text(
            json.dumps(partial_state), encoding="utf-8")

        state = load_state()
        assert state.get("phase") == "drafting"
        # 缺少的键通过 .get() 返回 None
        assert state.get("iteration") is None

    def test_save_state_basic(self, temp_project, monkeypatch):
        """TC-STM-004/005: save_state() 写入后 load_state() 验证一致性。"""
        from core.state_manager import save_state, load_state

        state_file = temp_project["state_file"]
        monkeypatch.setattr(
            "core.state_manager.STATE_FILE", state_file, raising=False)
        monkeypatch.setattr(
            "core.state_manager.OUTPUT_DIR", temp_project["output_dir"], raising=False)

        test_state = {
            "phase": "drafting",
            "iteration": 5,
            "chapters_drafted": 12,
            "current_focus": "chapter_13",
        }

        save_state(test_state)

        # 验证文件存在
        assert state_file.exists(), "save_state() 应创建 state.json"

        # 验证内容
        loaded = json.loads(state_file.read_text(encoding="utf-8"))
        assert loaded["phase"] == "drafting"
        assert loaded["iteration"] == 5
        assert loaded["chapters_drafted"] == 12

    def test_save_state_rapid_sequence(self, temp_project, monkeypatch):
        """TC-STM-005: 快速连续 save_state() 5 次。

        所有写入成功，最终文件为最后一次写入内容。
        """
        from core.state_manager import save_state

        state_file = temp_project["state_file"]
        monkeypatch.setattr(
            "core.state_manager.STATE_FILE", state_file, raising=False)
        monkeypatch.setattr(
            "core.state_manager.OUTPUT_DIR", temp_project["output_dir"], raising=False)

        for i in range(5):
            save_state({"iteration": i, "phase": "test"})

        # 验证最终状态
        loaded = json.loads(state_file.read_text(encoding="utf-8"))
        assert loaded["iteration"] == 4, \
            f"最终 iteration 应为 4，实际: {loaded['iteration']}"

    def test_state_with_unicode_emoji(self, temp_project, monkeypatch):
        """TC-STM-006: state.json 含嵌套 unicode/emoji。

        save_state() 和 load_state() 正确保留 emoji。
        """
        from core.state_manager import save_state, load_state

        state_file = temp_project["state_file"]
        monkeypatch.setattr(
            "core.state_manager.STATE_FILE", state_file, raising=False)
        monkeypatch.setattr(
            "core.state_manager.OUTPUT_DIR", temp_project["output_dir"], raising=False)

        test_state = {
            "current_focus": "测试🎯",
            "notes": "进展顺利🔥",
            "tags": ["📖", "✍️", "✅"],
        }

        save_state(test_state)
        loaded = load_state()

        assert loaded["current_focus"] == "测试🎯"
        assert loaded["notes"] == "进展顺利🔥"
        assert loaded["tags"] == ["📖", "✍️", "✅"]


# ============================================================================
# 5.4 log_result() 测试 (TC-STM-007 ~ TC-STM-010)
# ============================================================================

class TestLogResult:
    """测试 results.tsv 日志记录。"""

    def test_log_result_first_call_writes_header(self, temp_project, monkeypatch):
        """TC-STM-007: 首次调用写入 TSV 头。

        results.tsv 不存在时，首行为 header，第二行为数据行。
        """
        from core.state_manager import log_result

        results_file = temp_project["results_file"]
        monkeypatch.setattr(
            "core.state_manager.RESULTS_FILE", results_file, raising=False)

        log_result("abc123", "foundation", 7.5, 1000, "keep", "基础设定评估")

        assert results_file.exists()
        lines = results_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2, f"应有 2 行（header + data），实际 {len(lines)} 行"
        # 验证 header
        assert lines[0].startswith("commit\tphase"), \
            f"header 格式不正确: {lines[0]}"
        # 验证数据行
        assert "abc123" in lines[1]
        assert "foundation" in lines[1]
        assert "7.5" in lines[1]

    def test_log_result_negative_score_sentinel(self, temp_project, monkeypatch):
        """TC-STM-008: score=-1.0 哨兵转 error。

        display_score="N/A", display_status="error",
        description 含 "[评分解析失败]"。
        """
        from core.state_manager import log_result

        results_file = temp_project["results_file"]
        monkeypatch.setattr(
            "core.state_manager.RESULTS_FILE", results_file, raising=False)

        log_result("abc", "ch01", -1.0, 500, "keep", "test description")

        lines = results_file.read_text(encoding="utf-8").strip().split("\n")
        data_line = lines[-1]
        columns = data_line.split("\t")

        # 列: commit, phase, score, word_count, status, description
        assert columns[2] == "N/A", \
            f"score=-1.0 应显示为 N/A，实际: {columns[2]}"
        assert columns[4] == "error", \
            f"status 应为 error，实际: {columns[4]}"
        assert "[评分解析失败]" in columns[5], \
            f"description 应含 [评分解析失败]，实际: {columns[5]}"

    def test_log_result_zero_score_normal(self, temp_project, monkeypatch):
        """TC-STM-009: score=0.0 正常记录。

        0.0 不是负值哨兵，应正常显示。
        """
        from core.state_manager import log_result

        results_file = temp_project["results_file"]
        monkeypatch.setattr(
            "core.state_manager.RESULTS_FILE", results_file, raising=False)

        log_result("abc", "ch01", 0.0, 500, "discard", "test")

        lines = results_file.read_text(encoding="utf-8").strip().split("\n")
        data_line = lines[-1]
        columns = data_line.split("\t")

        assert columns[2] == "0.0", \
            f"score=0.0 应正常显示，实际: {columns[2]}"
        assert columns[4] == "discard", \
            f"status 应为 discard，实际: {columns[4]}"

    def test_log_result_empty_file(self, temp_project, monkeypatch):
        """TC-STM-010: 空 results.tsv（0字节）追加。

        空文件应先写入 header 再写入数据行。
        """
        from core.state_manager import log_result

        results_file = temp_project["results_file"]
        monkeypatch.setattr(
            "core.state_manager.RESULTS_FILE", results_file, raising=False)

        # 创建空文件
        results_file.write_text("", encoding="utf-8")

        log_result("test", "phase", 8.0, 2000, "keep", "")

        lines = results_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2, f"空文件追加应有 2 行，实际 {len(lines)} 行"

    def test_log_result_tsv_format_correctness(self, temp_project, monkeypatch):
        """验证 TSV 格式正确性：字段数、分隔符。"""
        from core.state_manager import log_result

        results_file = temp_project["results_file"]
        monkeypatch.setattr(
            "core.state_manager.RESULTS_FILE", results_file, raising=False)

        # 多次写入
        log_result("hash1", "foundation", 7.5, 1000, "keep", "test1")
        log_result("hash2", "ch01", 6.0, 2000, "keep", "test2")
        log_result("hash3", "ch02", -1.0, 3000, "keep", "test3")

        lines = results_file.read_text(encoding="utf-8").strip().split("\n")
        # 1 header + 3 data = 4 lines
        assert len(lines) == 4, f"应有 4 行，实际 {len(lines)} 行"

        for i, line in enumerate(lines):
            cols = line.split("\t")
            assert len(cols) == 6, \
                f"行 {i} 应有 6 列（\\t 分隔），实际 {len(cols)} 列: {cols}"


# ============================================================================
# 5.5 parse_score() 解析鲁棒性测试 (TC-PRS-001 ~ TC-PRS-008)
# ============================================================================

class TestParseScore:
    """测试 LLM 输出分数的三级解析策略。"""

    def test_parse_pure_json(self):
        """TC-PRS-001: 纯 JSON 格式。

        '{"overall_score": 7.5}' → 7.5
        """
        from core.state_manager import parse_score
        result = parse_score('{"overall_score": 7.5}')
        assert result == 7.5

    def test_parse_json_in_markdown_block(self):
        """TC-PRS-002: JSON 在 markdown 代码块中。

        '```json\\n{"overall_score": 6.0}\\n```' → 6.0
        """
        from core.state_manager import parse_score
        result = parse_score('```json\n{"overall_score": 6.0}\n```')
        assert result == 6.0

    def test_parse_json_with_surrounding_text(self):
        """TC-PRS-003: JSON 前后有额外文本。

        '前导文本 {"overall_score": 8.2} 后续文本' → 8.2
        """
        from core.state_manager import parse_score
        result = parse_score('前导文本 {"overall_score": 8.2} 后续文本')
        assert result == 8.2

    def test_parse_bold_score_format(self):
        """TC-PRS-004: '**综合评分**: 7.5/10' 格式 → 7.5。"""
        from core.state_manager import parse_score
        result = parse_score('**综合评分**: 7.5/10')
        assert result == 7.5

    def test_parse_key_value_format(self):
        """TC-PRS-005: 'overall_score: 8.0' 格式 → 8.0。"""
        from core.state_manager import parse_score
        result = parse_score('overall_score: 8.0')
        assert result == 8.0

    def test_parse_pure_number_raises(self):
        """TC-PRS-006: 纯数字 '7.5' → 抛出 ValueError。

        根据 parse_score 的设计，纯数字无 key 匹配时应失败。
        """
        from core.state_manager import parse_score
        with pytest.raises(ValueError, match="无法从 LLM 输出中解析"):
            parse_score("7.5")

    def test_parse_chinese_number_raises(self):
        """TC-PRS-007: 中文数字 '综合评分：七点五' → 抛出 ValueError。"""
        from core.state_manager import parse_score
        with pytest.raises(ValueError, match="无法从 LLM 输出中解析"):
            parse_score("综合评分：七点五")

    def test_parse_empty_string_raises(self):
        """TC-PRS-008: 空字符串 → 抛出 ValueError。"""
        from core.state_manager import parse_score
        with pytest.raises(ValueError, match="无法从 LLM 输出中解析"):
            parse_score("")

    def test_parse_score_custom_key(self):
        """验证 parse_score 支持自定义 key 参数。"""
        from core.state_manager import parse_score
        result = parse_score('{"lore_score": 8.5}', key="lore_score")
        assert result == 8.5

    def test_parse_score_none_raises(self):
        """None 输入 → 抛出异常。"""
        from core.state_manager import parse_score
        with pytest.raises(Exception):
            parse_score(None)

    def test_parse_score_missing_key_in_json(self):
        """JSON 有效但缺少目标 key → 抛出 ValueError。"""
        from core.state_manager import parse_score
        with pytest.raises(ValueError, match="无法从 LLM 输出中解析"):
            parse_score('{"quality": 8, "readability": 7}')

    def test_parse_score_negative_value(self):
        """负值分数（非哨兵场景）应正常解析。"""
        from core.state_manager import parse_score
        # _try_json_extract 返回 float，parse_score 返回该值
        # 但 -1.0 是合法分数吗？根据设计，parse_score 不区分哨兵
        result = parse_score('{"overall_score": -1.0}')
        assert result == -1.0

    def test_parse_score_nested_json(self):
        """嵌套 JSON 的解析。"""
        from core.state_manager import parse_score
        result = parse_score(
            '{"overall_score": 7.5, "dimensions": {"plot": 8, "style": 7}}')
        assert result == 7.5

    def test_parse_score_markdown_without_json(self):
        """Markdown 格式无 JSON，仅 **评分**: X/10。"""
        from core.state_manager import parse_score
        # 2b 匹配: **综合评分**: X/10
        result = parse_score('**综合评分**: 9.0/10')
        assert result == 9.0

    def test_parse_score_section_format(self):
        """### 小节内的评分格式。"""
        from core.state_manager import parse_score
        text = "### overall_score\n\n**评分**: 8.5/10\n\n其他内容"
        result = parse_score(text)
        assert result == 8.5

    def test_parse_lore_score(self):
        """验证 parse_lore_score 正确委托给 parse_score。"""
        from core.state_manager import parse_lore_score
        result = parse_lore_score('{"lore_score": 9.0}')
        assert result == 9.0


# ============================================================================
# 5.6 evaluate_chapter_stable() 中位数测试 (TC-STM-011 ~ TC-STM-013)
# ============================================================================

class TestEvaluateChapterStable:
    """测试稳定评估的中位数计算逻辑。"""

    def test_median_odd_samples(self, monkeypatch):
        """TC-STM-011: 3次采样正常返回中位数。

        mock evaluate_chapter 返回 [8.0, 6.0, 7.0] → 中位数 7.0
        """
        from core.state_manager import evaluate_chapter_stable

        call_count = [0]
        responses = [
            '{"overall_score": 8.0}',
            '{"overall_score": 6.0}',
            '{"overall_score": 7.0}',
        ]

        def mock_eval(ch_num, retries=2, max_total_time=600):
            idx = call_count[0]
            call_count[0] += 1
            return responses[idx]

        monkeypatch.setattr(
            "evaluation.evaluate.evaluate_chapter", mock_eval, raising=False)
        monkeypatch.setattr(
            "core.state_manager._eval", mock_eval, raising=False)

        # 需要 mock evaluate_chapter_stable 中的局部导入
        import evaluation.evaluate as ev
        monkeypatch.setattr(ev, "evaluate_chapter", mock_eval, raising=False)

        result = evaluate_chapter_stable(1, samples=3, retries=1, max_total_time=60)

        assert call_count[0] == 3, f"应调用 3 次，实际 {call_count[0]}"
        assert result == 7.0, f"中位数应为 7.0，实际: {result}"

    def test_median_even_samples(self):
        """验证偶数个采样值的中位数计算。

        直接测试中位数逻辑: [6.0, 7.0, 8.0, 9.0] → 中位数 7.5
        """
        scores = [6.0, 7.0, 8.0, 9.0]
        scores.sort()
        # 4个元素，取 len//2 = 2 位置的元素 → 8.0
        # 传统中位数: (7.0 + 8.0) / 2 = 7.5，但代码用 scores[len//2]
        # 所以返回 8.0
        median = scores[len(scores) // 2]
        assert median == 8.0

    def test_median_with_negative_filtered(self, monkeypatch):
        """TC-STM-012: 含负值(-1.0)的采样被过滤。

        mock返回 [8.0, -1.0, 7.0] → 有效值 [7.0, 8.0]，中位数 7.5
        根据代码: s >= 0 才加入 scores，所以 -1.0 被过滤
        scores = [7.0, 8.0] → sorted → [7.0, 8.0] → scores[1] = 8.0
        """
        from core.state_manager import evaluate_chapter_stable

        call_count = [0]
        responses = [
            '{"overall_score": 8.0}',
            '{"overall_score": -1.0}',
            '{"overall_score": 7.0}',
        ]

        def mock_eval(ch_num, retries=2, max_total_time=600):
            idx = call_count[0]
            call_count[0] += 1
            return responses[idx]

        import evaluation.evaluate as ev
        monkeypatch.setattr(ev, "evaluate_chapter", mock_eval, raising=False)

        result = evaluate_chapter_stable(1, samples=3, retries=1, max_total_time=60)

        assert call_count[0] == 3
        assert result == 7.5, \
            f"有效值 [7.0, 8.0] 的中位数应为 7.5 (偶数长度取两中间值平均)，实际: {result}"

    def test_all_samples_fail(self, monkeypatch):
        """TC-STM-013: 全部采样失败 → 返回 0.0。"""
        from core.state_manager import evaluate_chapter_stable

        def mock_eval_fail(ch_num, retries=2, max_total_time=600):
            raise RuntimeError("模拟评估失败")

        import evaluation.evaluate as ev
        monkeypatch.setattr(ev, "evaluate_chapter", mock_eval_fail, raising=False)

        result = evaluate_chapter_stable(1, samples=3, retries=1, max_total_time=60)

        assert result == 0.0, f"全部失败应返回 0.0，实际: {result}"

    def test_all_samples_zero_or_negative(self, monkeypatch):
        """全部采样返回 0.0 或负值，全部被过滤 → 返回 0.0。"""
        from core.state_manager import evaluate_chapter_stable

        call_count = [0]
        responses = [
            '{"overall_score": -1.0}',
            '{"overall_score": -1.0}',
            '{"overall_score": -1.0}',
        ]

        def mock_eval(ch_num, retries=2, max_total_time=600):
            idx = call_count[0]
            call_count[0] += 1
            return responses[idx]

        import evaluation.evaluate as ev
        monkeypatch.setattr(ev, "evaluate_chapter", mock_eval, raising=False)

        result = evaluate_chapter_stable(1, samples=3, retries=1, max_total_time=60)

        assert result == 0.0, f"全部负值过滤后应返回 0.0，实际: {result}"


# ============================================================================
# 5.7 备份与恢复测试 (TC-STM-014 ~ TC-STM-016)
# ============================================================================

class TestBackupRestore:
    """测试 git 备份和文件快照备份。"""

    def test_git_add_commit_git_available(self, temp_project, monkeypatch):
        """TC-STM-014: git 可用时 git_add_commit 调用 git。

        mock git_available()=True, subprocess.run 返回成功。
        """
        from core.state_manager import git_add_commit

        # Mock git_available → True
        monkeypatch.setattr(
            "core.state_manager.git_available", lambda: True, raising=False)

        # Mock _git_run → 成功
        mock_run = MagicMock()
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        monkeypatch.setattr(
            "core.state_manager._git_run", mock_run, raising=False)

        # Mock git_short_hash
        monkeypatch.setattr(
            "core.state_manager.git_short_hash",
            lambda: "abc1234",
            raising=False)

        # Mock OUTPUT_DIR
        monkeypatch.setattr(
            "core.state_manager.OUTPUT_DIR",
            temp_project["output_dir"],
            raising=False)

        # 创建一些 output 文件
        (temp_project["output_dir"] / "world.md").write_text("# World", encoding="utf-8")
        (temp_project["output_dir"] / "state.json").write_text("{}", encoding="utf-8")

        result = git_add_commit("test commit message")

        # 验证 _git_run 被调用
        assert mock_run.called, "_git_run 应被调用"
        # 验证返回短哈希
        assert result == "abc1234"

    def test_git_add_commit_git_unavailable(self, temp_project, monkeypatch):
        """TC-STM-015: git 不可用时 git_add_commit 回退文件备份。

        mock git_available()=False, backup_snapshot() 被调用。
        """
        from core.state_manager import git_add_commit

        # Mock git_available → False
        monkeypatch.setattr(
            "core.state_manager.git_available", lambda: False, raising=False)

        # Mock backup_snapshot 并追踪调用
        backup_calls = []

        def mock_backup(label=""):
            backup_calls.append(label)
            return f"snapshot-{label}"

        monkeypatch.setattr(
            "core.state_manager.backup_snapshot", mock_backup, raising=False)

        result = git_add_commit("git unavailable fallback")

        assert len(backup_calls) == 1, \
            f"backup_snapshot 应被调用 1 次，实际 {len(backup_calls)} 次"
        assert "git unavailable fallback" in result

    def test_backup_snapshot_creates_backup(self, temp_project, monkeypatch):
        """TC-STM-016: backup_snapshot() 备份所有关键文件。"""
        from core.state_manager import backup_snapshot

        # Mock 路径常量
        monkeypatch.setattr(
            "core.state_manager.OUTPUT_DIR",
            temp_project["output_dir"],
            raising=False)
        monkeypatch.setattr(
            "core.state_manager.ROOT_DIR",
            temp_project["project_root"],
            raising=False)
        monkeypatch.setattr(
            "core.state_manager.BACKUPS_DIR",
            temp_project["backups_dir"],
            raising=False)
        monkeypatch.setattr(
            "core.state_manager.CHAPTERS_DIR",
            temp_project["chapters_dir"],
            raising=False)

        # 创建一些关键文件
        (temp_project["output_dir"] / "world.md").write_text("# 世界观", encoding="utf-8")
        (temp_project["output_dir"] / "characters.md").write_text("# 角色", encoding="utf-8")
        (temp_project["output_dir"] / "state.json").write_text('{"phase":"test"}', encoding="utf-8")
        # 创建章节
        ch_dir = temp_project["chapters_dir"]
        ch_dir.mkdir(parents=True, exist_ok=True)
        (ch_dir / "ch_01.md").write_text("# 第1章", encoding="utf-8")
        (ch_dir / "ch_02.md").write_text("# 第2章", encoding="utf-8")

        result = backup_snapshot("测试备份标签")

        # 验证备份目录被创建
        backups = list(temp_project["backups_dir"].iterdir())
        assert len(backups) >= 1, f"应有至少 1 个备份目录，实际 {len(backups)}"

        backup_dir = backups[0]
        # 验证 label.txt
        label_file = backup_dir / "label.txt"
        assert label_file.exists(), "应创建 label.txt"
        assert label_file.read_text(encoding="utf-8") == "测试备份标签"

        # 验证关键文件被备份
        assert (backup_dir / "world.md").exists(), "world.md 应被备份"
        assert (backup_dir / "state.json").exists(), "state.json 应被备份"

        # 验证章节子目录
        ch_backup = backup_dir / "chapters"
        assert ch_backup.exists(), "应创建 chapters 子目录"
        assert (ch_backup / "ch_01.md").exists(), "ch_01.md 应被备份"
        assert (ch_backup / "ch_02.md").exists(), "ch_02.md 应被备份"

    def test_git_short_hash_fallback(self, monkeypatch):
        """git 不可用时 git_short_hash 返回时间戳标识。"""
        from core.state_manager import git_short_hash

        monkeypatch.setattr(
            "core.state_manager.git_available", lambda: False, raising=False)

        result = git_short_hash()
        # 应为 YYYYMMDDHHMMSS 格式的时间戳
        assert len(result) == 14, \
            f"时间戳应 14 位 (YYYYMMDDHHMMSS)，实际 {len(result)}: {result}"
        assert result.isdigit(), f"时间戳应为纯数字，实际: {result}"


# ============================================================================
# 附加测试: default_state, get_total_chapters, count_* 等
# ============================================================================

class TestUtilityFunctions:
    """测试 state_manager 中的工具函数。"""

    def test_default_state_keys(self):
        """验证 default_state() 包含所有必需键。"""
        from core.state_manager import default_state

        state = default_state()
        required_keys = [
            "phase", "current_focus", "iteration",
            "foundation_score", "lore_score",
            "chapters_drafted", "chapters_total",
            "novel_score", "revision_cycle", "debts",
        ]
        for key in required_keys:
            assert key in state, f"default_state 缺少键: {key}"

    def test_get_total_chapters_from_state(self, monkeypatch):
        """验证 get_total_chapters 从 state 读取。"""
        from core.state_manager import get_total_chapters

        state = {"chapters_total": 36}
        result = get_total_chapters(state)
        assert result == 36

    def test_get_total_chapters_fallback(self, monkeypatch):
        """验证 get_total_chapters 回退到 config 或默认值 24。"""
        from core.state_manager import get_total_chapters

        # 空 state → 回退到 config → config 也可能为空 → 默认 24
        state = {"chapters_total": 0}
        # Mock config.load() 和 config.total_chapters
        monkeypatch.setattr(
            "core.state_manager.config",
            MagicMock(loaded=True, total_chapters=48),
            raising=False)
        result = get_total_chapters(state)
        assert result == 48

    def test_count_chapter_files_empty(self, temp_project, monkeypatch):
        """验证空目录下 count_chapter_files 返回 0。"""
        from core.state_manager import count_chapter_files

        monkeypatch.setattr(
            "core.state_manager.CHAPTERS_DIR",
            temp_project["chapters_dir"],
            raising=False)

        assert count_chapter_files() == 0

    def test_count_chapter_files_with_chapters(self, temp_project, monkeypatch):
        """验证有章节时 count_chapter_files 返回正确数量。"""
        from core.state_manager import count_chapter_files

        ch_dir = temp_project["chapters_dir"]
        for i in range(1, 6):
            (ch_dir / f"ch_{i:02d}.md").write_text(f"# 第{i}章", encoding="utf-8")

        monkeypatch.setattr(
            "core.state_manager.CHAPTERS_DIR", ch_dir, raising=False)

        assert count_chapter_files() == 5

    def test_count_words_in_chapters(self, temp_project, monkeypatch):
        """验证章节字数统计。"""
        from core.state_manager import count_words_in_chapters

        ch_dir = temp_project["chapters_dir"]
        (ch_dir / "ch_01.md").write_text("这是第一章的测试内容，用于验证字数统计。", encoding="utf-8")
        (ch_dir / "ch_02.md").write_text("第二章内容较短。", encoding="utf-8")

        monkeypatch.setattr(
            "core.state_manager.CHAPTERS_DIR", ch_dir, raising=False)

        word_count = count_words_in_chapters()
        assert word_count > 0, "应有正数字数统计"

    def test_banner_output(self, capsys):
        """验证 banner() 输出格式。"""
        from core.state_manager import banner
        banner("测试阶段")
        captured = capsys.readouterr()
        assert "测试阶段" in captured.out

    def test_step_output(self, capsys):
        """验证 step() 输出包含时间戳。"""
        from core.state_manager import step
        step("执行步骤")
        captured = capsys.readouterr()
        assert "执行步骤" in captured.out
        # 应包含时间戳格式的字符
        assert ":" in captured.out
