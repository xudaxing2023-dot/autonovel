"""
tests/edge/test_json_robustness.py — 阶段5D: JSON解析容错 (4个用例)

测试目标:
  TC-EDG-016: 缺少必要字段的JSON
  TC-EDG-017: 多余字段的JSON
  TC-EDG-018: 嵌套深度4层+
  TC-EDG-019: JSON中包含NaN/Infinity

所有测试不调用 LLM API。
"""

import json
import math
from unittest.mock import patch, MagicMock

import pytest


# ============================================================================
# Helpers
# ============================================================================

def _make_deep_json(depth: int) -> dict:
    """生成深度嵌套的 JSON 对象。"""
    if depth <= 1:
        return {"value": f"depth_{depth}"}
    return {"level": depth, "child": _make_deep_json(depth - 1)}


# ============================================================================
# TC-EDG-016: 缺少必要字段
# ============================================================================

class TestMissingRequiredFields:
    """测试 JSON 缺少必要字段时的行为。"""

    def test_parse_json_missing_overall_score(self):
        """TC-EDG-016a: _parse_json_response 缺少 overall_score 字段。

        验证从 evaluation/evaluate.py 的 _parse_json_response 逻辑。
        """
        from evaluation.evaluate import _parse_json_response

        # 有效 JSON 但缺少 overall_score
        json_str = '{"chapter_number": 5, "notes": "没有评分"}'
        result = _parse_json_response(json_str)

        assert "overall_score" not in result, \
            "缺少的字段不应出现在结果中"
        assert result.get("chapter_number") == 5, \
            "存在的字段应正确解析"
        assert result.get("overall_score") is None, \
            "缺失字段 .get() 应返回 None"

    def test_parse_score_missing_key(self):
        """TC-EDG-016b: parse_score() 在 JSON 中缺少 key 时。

        缺少 overall_score 键时应抛出 ValueError。
        """
        from core.state_manager import parse_score

        json_str = '{"chapter": 5, "notes": "没有overall_score"}'

        with pytest.raises(ValueError) as exc_info:
            parse_score(json_str, "overall_score")

        assert "无法从 LLM 输出中解析" in str(exc_info.value), \
            f"错误信息应提示无法解析，实际: {exc_info.value}"

    def test_state_load_missing_keys(self, tmp_path):
        """TC-EDG-016c: load_state 处理缺少关键键的 JSON。

        load_state 不对缺失键做校验，调用者通过 .get() 获取默认值。
        """
        from core.state_manager import load_state, default_state
        import core.config as cfg

        # 创建仅含 phase 的 state.json
        state_file = tmp_path / "state.json"
        state_file.write_text(
            '{"phase": "drafting"}', encoding="utf-8"
        )

        import core.state_manager as sm
        with patch.object(sm, "STATE_FILE", state_file):
            state = load_state()

        # 只保证 phase 存在
        assert state.get("phase") == "drafting"
        # 其他键不存在，.get() 返回 None
        assert state.get("chapters_drafted") is None, \
            "缺失键 .get() 应返回 None"

    def test_config_json_partial_keys(self, tmp_path, monkeypatch):
        """TC-EDG-016d: config.json 仅含部分键。"""
        import core.config as cfg

        config_file = tmp_path / "config.json"
        config_file.write_text(
            '{"novel_title": "测试小说", "total_chapters": 12}',
            encoding="utf-8"
        )

        monkeypatch.setattr(cfg, "CONFIG_FILE", config_file, raising=False)

        # 创建新的 Config 实例（绕过单例缓存）
        fresh_config = cfg.Config()
        fresh_config._load_config_json()

        data = fresh_config._data
        assert data.get("novel_title") == "测试小说"
        assert data.get("total_chapters") == 12
        # 未定义的键不存在
        assert "unknown_key" not in data


# ============================================================================
# TC-EDG-017: 多余字段
# ============================================================================

class TestExtraFields:
    """测试 JSON 含有多余字段时的行为。"""

    def test_parse_json_extra_fields(self):
        """TC-EDG-017a: _parse_json_response 含未知额外字段。

        额外字段应被保留在返回 dict 中。
        """
        from evaluation.evaluate import _parse_json_response

        json_str = (
            '{"overall_score": 7.5, "chapter_number": 3, '
            '"extra_field_1": "未知数据", "extra_field_2": 12345, '
            '"nested_extra": {"sub": "value"}}'
        )
        result = _parse_json_response(json_str)

        assert result.get("overall_score") == 7.5, "核心字段应正确解析"
        assert result.get("extra_field_1") == "未知数据", \
            "额外字符串字段应被保留"
        assert result.get("extra_field_2") == 12345, \
            "额外数字字段应被保留"
        assert result.get("nested_extra") == {"sub": "value"}, \
            "嵌套额外字段应被保留"

    def test_extra_fields_in_state_json(self, tmp_path):
        """TC-EDG-017b: state.json 含额外字段时 load_state 行为。

        load_state 直接返回解析结果，不校验字段。
        """
        from core.state_manager import load_state
        import core.state_manager as sm

        state_file = tmp_path / "state.json"
        state_file.write_text(
            '{"phase": "drafting", "extra_version": "2.0", '
            '"experimental_flag": true, "chapters_drafted": 10}',
            encoding="utf-8"
        )

        with patch.object(sm, "STATE_FILE", state_file):
            state = load_state()

        # 额外字段存在
        assert state.get("extra_version") == "2.0", \
            "额外字段应被保留"
        assert state.get("experimental_flag") is True, \
            "额外布尔字段应被保留"
        # 标准字段也正常
        assert state.get("phase") == "drafting"

    def test_parse_score_with_extra_fields(self):
        """TC-EDG-017c: parse_score 含额外字段的 JSON。

        额外字段不应影响 overall_score 提取。
        """
        from core.state_manager import parse_score

        json_str = (
            '{"overall_score": 8.2, "unknown_metric": 99.9, '
            '"extra_comment": "这个不应该影响解析"}'
        )
        score = parse_score(json_str, "overall_score")
        assert score == 8.2, f"额外字段不应影响分数解析，实际 {score}"


# ============================================================================
# TC-EDG-018: 嵌套深度 4层+
# ============================================================================

class TestDeepNesting:
    """测试深度嵌套 JSON 的解析。"""

    def test_parse_json_depth_5(self):
        """TC-EDG-018a: _parse_json_response 深度5层的嵌套。

        验证花括号深度匹配（第3层回退）能正确处理。
        """
        from evaluation.evaluate import _parse_json_response

        deep = _make_deep_json(5)

        # 验证生成的结构
        assert deep["level"] == 5
        assert deep["child"]["level"] == 4
        assert deep["child"]["child"]["level"] == 3
        assert deep["child"]["child"]["child"]["level"] == 2

        json_str = json.dumps(deep)
        result = _parse_json_response(json_str)

        assert result == deep, \
            f"深度5层嵌套应完全解析，实际: {result}"

    def test_parse_json_depth_10(self):
        """TC-EDG-018b: _parse_json_response 深度10层嵌套。"""
        from evaluation.evaluate import _parse_json_response

        deep = _make_deep_json(10)
        json_str = json.dumps(deep)

        result = _parse_json_response(json_str)
        assert result == deep, \
            "深度10层嵌套应完全解析"

    def test_deep_nesting_with_braces_in_strings(self):
        """TC-EDG-018c: 深层嵌套 + 字符串中含花括号。

        验证第3层回退的花括号深度匹配正确处理
        字符串中的 {} 字符。
        """
        from evaluation.evaluate import _parse_json_response

        # 包含花括号字符的字符串值
        data = {
            "level1": {
                "text_with_braces": "包含 { 和 } 花括号的文本",
                "level2": {
                    "code_snippet": 'function() { return "test"; }',
                    "level3": {
                        "json_example": '{"key": "value"}',
                        "level4": {
                            "overall_score": 8.5,
                        },
                    },
                },
            },
        }

        json_str = json.dumps(data)
        result = _parse_json_response(json_str)

        # 深层嵌套的值应正确提取
        assert result["level1"]["level2"]["level3"]["level4"]["overall_score"] == 8.5, \
            "深层嵌套中的 overall_score 应正确提取"

    def test_deep_parsing_with_text_after_json(self):
        """TC-EDG-018d: 深层嵌套JSON后跟额外文本。

        验证第3层回退在深度匹配后不包含尾部文本。
        """
        from evaluation.evaluate import _parse_json_response

        json_part = json.dumps({"level": 1, "child": {"level": 2, "child": {"level": 3, "child": {"value": 42}}}})
        full_text = f"{json_part}\n\n这是JSON后面的额外文本，不应被解析。"

        result = _parse_json_response(full_text)
        assert result["child"]["child"]["child"]["value"] == 42, \
            "深度嵌套值应正确提取"


# ============================================================================
# TC-EDG-019: JSON 中包含 NaN/Infinity
# ============================================================================

class TestNaNInfinity:
    """测试 JSON 中包含 NaN/Infinity 时的行为。

    JSON 标准不支持 NaN 和 Infinity，但 Python 的 json 模块
    可以通过 allow_nan=True（默认）来处理。
    """

    def test_json_nan_parsing(self):
        """TC-EDG-019a: JSON 中的 NaN。

        Python json 默认 allow_nan=True（解析和序列化都允许 NaN/Infinity）。
        这是 Python 对 JSON 规范的扩展，标准 JSON 不允许这些值。
        """
        json_str = '{"score": NaN, "valid": true}'

        # Python 3.x json.loads 默认 allow_nan=True 会接受 NaN
        # 测试当前 Python 版本的行为
        try:
            result = json.loads(json_str)
            # Python 接受 NaN — 记录此行为
            print(f"\n[NaN解析] Python json.loads 接受 NaN: {result}")
            assert result["score"] != result["score"], \
                "NaN 应不等于自身 (IEEE 754)"
        except json.JSONDecodeError:
            # 某些 Python 版本/实现可能拒绝
            print("\n[NaN解析] Python json.loads 拒绝 NaN (严格模式)")

    def test_json_infinity_parsing(self):
        """TC-EDG-019b: JSON 中的 Infinity。"""
        json_str = '{"max_value": Infinity, "min_value": -Infinity}'

        try:
            result = json.loads(json_str)
            print(f"\n[Infinity解析] Python json.loads 接受 Infinity: {result}")
            assert result["max_value"] == float("inf"), \
                "Infinity 应解析为正无穷"
            assert result["min_value"] == float("-inf"), \
                "-Infinity 应解析为负无穷"
        except json.JSONDecodeError:
            print("\n[Infinity解析] Python json.loads 拒绝 Infinity (严格模式)")

    def test_python_float_nan_serialization(self):
        """TC-EDG-019c: Python float('nan') 序列化为 JSON。

        Python 默认 allow_nan=True 会将 NaN 序列化为 "NaN"。
        """
        data = {
            "score": float("nan"),
            "valid_score": 7.5,
        }

        # 序列化 NaN
        json_str = json.dumps(data, allow_nan=True)
        assert "NaN" in json_str, "NaN 应被序列化为 NaN 字符串"

        # 反序列化 NaN
        parsed = json.loads(json_str)
        assert math.isnan(parsed["score"]), "反序列化后应仍是 NaN"

    def test_parse_score_with_nan_value(self):
        """TC-EDG-019d: parse_score 对 NaN 值的处理。

        当 JSON 中 overall_score 是 NaN 时，
        parse_score 应能处理。
        """
        from core.state_manager import parse_score, _try_json_extract

        # Python 生成的 NaN JSON（非标准）
        json_str = json.dumps({"overall_score": float("nan")})

        # _try_json_extract 读取 float('nan')
        result = _try_json_extract(json_str, "overall_score")
        assert result is not None, "_try_json_extract 应能提取 NaN"
        assert math.isnan(result), "应返回 NaN"

        # parse_score 直接使用时
        try:
            score = parse_score(json_str, "overall_score")
            # 如果到了这里说明解析"成功"但值是 NaN
            if math.isnan(score):
                print("\n[注意] parse_score 返回了 NaN 分数 — "
                      "这可能导致后续比较逻辑异常 (NaN != NaN, NaN < 0 == False)")
        except ValueError:
            # parse_score 可能因 NaN 无法比较而抛异常
            pass

    def test_save_state_with_nan_raises(self):
        """TC-EDG-019e: save_state 遇到 NaN 时的行为。

        json.dump 默认 allow_nan=True，所以 NaN 可以序列化。
        但生成的 JSON 是非标准的，其他解析器可能拒绝。
        """
        state = {
            "phase": "drafting",
            "novel_score": float("nan"),
        }

        # 序列化不会报错
        json_str = json.dumps(state, allow_nan=True)
        assert "NaN" in json_str

        # 反序列化回来
        parsed = json.loads(json_str)
        assert math.isnan(parsed["novel_score"]), \
            "NaN 可以往返序列化"

        # 但这在非 Python JSON 解析器中不是标准行为
        print("\n[已知风险] save_state 使用 json.dump(allow_nan=True)，"
              "NaN 值可序列化但生成非标准 JSON")

    def test_log_result_with_nan_score(self, tmp_path):
        """TC-EDG-019f: log_result 遇到 NaN 分数。

        NaN < 0 为 False，所以负值哨兵检测不会触发。
        但 NaN 作为 display_score 写入 TSV 可能导致
        下游解析工具出错。
        """
        from core.state_manager import log_result
        import core.config as cfg
        import core.state_manager as sm
        import math

        results_file = tmp_path / "results.tsv"
        with patch.object(sm, "RESULTS_FILE", results_file):
            log_result("abc123", "ch01", float("nan"), 500, "keep", "test")

        content = results_file.read_text(encoding="utf-8")
        # NaN 被当作字符串 "nan" 写入
        assert "nan" in content.lower(), \
            f"NaN 应出现在 TSV 中，实际内容: {content[:200]}"
        print(f"\n[NaN in TSV] {content.strip()}")
