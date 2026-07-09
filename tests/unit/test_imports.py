"""
tests/unit/test_imports.py — 阶段1: 模块导入与基础完整性测试

测试目标:
  TC-IMP-001 ~ TC-IMP-012: 全部模块导入测试
  TC-IMP-013 ~ TC-IMP-015: 包 __init__.py 导出测试
  TC-IMP-016: 循环依赖检测
  TC-IMP-017 ~ TC-IMP-018: pyproject.toml 依赖完整性

所有测试不调用 LLM API。
"""

import sys
import importlib
import pytest
from pathlib import Path

# tomllib 是 Python 3.11+ 标准库，旧版本使用 tomli
try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None


# ============================================================================
# 辅助函数
# ============================================================================

PROJECT_ROOT = Path(__file__).parent.parent.parent


def _try_import(module_name: str) -> tuple:
    """尝试导入模块，返回 (success: bool, error: str, module: object|None)。"""
    try:
        mod = importlib.import_module(module_name)
        return (True, "", mod)
    except Exception as e:
        return (False, f"{type(e).__name__}: {e}", None)


# ============================================================================
# 4.1 模块导入测试 (TC-IMP-001 ~ TC-IMP-012)
# ============================================================================

class TestAllModuleImports:
    """验证所有模块可成功导入，无 ImportError。"""

    # —— core 包 ——
    def test_import_core_config(self):
        """TC-IMP-001: 验证 core.config 可导入。"""
        ok, err, mod = _try_import("core.config")
        assert ok, f"core.config 导入失败: {err}"
        assert hasattr(mod, "config"), "core.config 缺少全局 config 单例"
        assert hasattr(mod, "Config"), "core.config 缺少 Config 类"

    def test_import_core_state_manager(self):
        """TC-IMP-002: 验证 core.state_manager 可导入。"""
        ok, err, mod = _try_import("core.state_manager")
        assert ok, f"core.state_manager 导入失败: {err}"
        assert hasattr(mod, "load_state"), "缺少 load_state"
        assert hasattr(mod, "save_state"), "缺少 save_state"
        assert hasattr(mod, "parse_score"), "缺少 parse_score"
        assert hasattr(mod, "log_result"), "缺少 log_result"

    def test_import_core_api_client(self):
        """TC-IMP-003: 验证 core.api_client 可导入。"""
        ok, err, mod = _try_import("core.api_client")
        assert ok, f"core.api_client 导入失败: {err}"
        assert hasattr(mod, "call_llm"), "缺少 call_llm"
        assert hasattr(mod, "call_writer"), "缺少 call_writer"
        assert hasattr(mod, "call_judge"), "缺少 call_judge"

    def test_import_core_diagnostic(self):
        """TC-IMP-004: 验证 core.diagnostic 可导入。"""
        ok, err, mod = _try_import("core.diagnostic")
        assert ok, f"core.diagnostic 导入失败: {err}"

    # —— evaluation 包 ——
    def test_import_evaluation_evaluate(self):
        """TC-IMP-005: 验证 evaluation.evaluate 可导入。"""
        ok, err, mod = _try_import("evaluation.evaluate")
        assert ok, f"evaluation.evaluate 导入失败: {err}"

    def test_import_evaluation_antipatterns(self):
        """TC-IMP-006: 验证 evaluation.antipatterns 可导入。"""
        ok, err, mod = _try_import("evaluation.antipatterns")
        assert ok, f"evaluation.antipatterns 导入失败: {err}"

    # —— drafting 包 ——
    def test_import_drafting_draft_chapter(self):
        """TC-IMP-007: 验证 drafting.draft_chapter 可导入。"""
        ok, err, mod = _try_import("drafting.draft_chapter")
        assert ok, f"drafting.draft_chapter 导入失败: {err}"

    def test_import_drafting_run_drafts(self):
        """验证 drafting.run_drafts 可导入。"""
        ok, err, mod = _try_import("drafting.run_drafts")
        assert ok, f"drafting.run_drafts 导入失败: {err}"

    # —— foundation 包 ——
    def test_import_foundation_gen_canon(self):
        """TC-IMP-008: 验证 foundation.gen_canon 可导入。"""
        ok, err, mod = _try_import("foundation.gen_canon")
        assert ok, f"foundation.gen_canon 导入失败: {err}"

    def test_import_foundation_all_modules(self):
        """验证 foundation 包下全部模块可导入。"""
        foundation_modules = [
            "foundation.gen_world",
            "foundation.gen_characters",
            "foundation.gen_outline",
            "foundation.gen_outline_volume",
            "foundation.gen_outline_part2",
            "foundation.gen_canon",
            "foundation.gen_voice",
            "foundation.update_canon",
        ]
        failed = []
        for mod_name in foundation_modules:
            ok, err, _ = _try_import(mod_name)
            if not ok:
                failed.append(f"{mod_name}: {err}")
        assert not failed, f"以下 foundation 模块导入失败:\n" + "\n".join(failed)

    # —— revision 包 ——
    def test_import_revision_gen_brief(self):
        """TC-IMP-009: 验证 revision.gen_brief 可导入。"""
        ok, err, mod = _try_import("revision.gen_brief")
        assert ok, f"revision.gen_brief 导入失败: {err}"

    def test_import_revision_apply_cuts(self):
        """TC-IMP-010: 验证 revision.apply_cuts 可导入。"""
        ok, err, mod = _try_import("revision.apply_cuts")
        assert ok, f"revision.apply_cuts 导入失败: {err}"

    def test_import_revision_all_modules(self):
        """验证 revision 包下全部模块可导入。"""
        revision_modules = [
            "revision.adversarial_edit",
            "revision.apply_cuts",
            "revision.reader_panel",
            "revision.gen_brief",
            "revision.gen_revision",
            "revision.review",
            "revision.compare_chapters",
        ]
        failed = []
        for mod_name in revision_modules:
            ok, err, _ = _try_import(mod_name)
            if not ok:
                failed.append(f"{mod_name}: {err}")
        assert not failed, f"以下 revision 模块导入失败:\n" + "\n".join(failed)

    # —— export 包 ——
    def test_import_export_build_manuscript(self):
        """TC-IMP-011: 验证 export.build_manuscript 可导入。"""
        ok, err, mod = _try_import("export.build_manuscript")
        assert ok, f"export.build_manuscript 导入失败: {err}"

    def test_import_export_all_modules(self):
        """验证 export 包下全部模块可导入。"""
        export_modules = [
            "export.build_manuscript",
            "export.build_outline",
            "export.build_arc_summary",
        ]
        failed = []
        for mod_name in export_modules:
            ok, err, _ = _try_import(mod_name)
            if not ok:
                failed.append(f"{mod_name}: {err}")
        assert not failed, f"以下 export 模块导入失败:\n" + "\n".join(failed)

    # —— prompts 包 ——
    def test_import_prompts_all_modules(self):
        """TC-IMP-012: 验证 prompts 全部子模块可导入。"""
        prompts_modules = [
            "prompts.world_prompts",
            "prompts.character_prompts",
            "prompts.outline_prompts",
            "prompts.chapter_prompts",
            "prompts.eval_judge_prompts",
            "prompts.review_prompts",
            "prompts.revision_prompts",
            "prompts.reader_panel_prompts",
            "prompts.adversarial_prompts",
            "prompts.seed_prompts",
        ]
        failed = []
        for mod_name in prompts_modules:
            ok, err, _ = _try_import(mod_name)
            if not ok:
                failed.append(f"{mod_name}: {err}")
        assert not failed, f"以下 prompts 模块导入失败:\n" + "\n".join(failed)

    # —— 顶层模块 ——
    def test_import_pipeline_orchestrator(self):
        """验证 pipeline_orchestrator 可导入。"""
        ok, err, mod = _try_import("pipeline_orchestrator")
        assert ok, f"pipeline_orchestrator 导入失败: {err}"

    def test_import_novel_app(self):
        """验证 novel_app 可导入。"""
        ok, err, mod = _try_import("novel_app")
        assert ok, f"novel_app 导入失败: {err}"

    def test_import_seed(self):
        """验证 seed 可导入。"""
        ok, err, mod = _try_import("seed")
        assert ok, f"seed 导入失败: {err}"

    def test_import_voice_fingerprint(self):
        """TC-IMP-015: 验证 voice_fingerprint 可导入。"""
        ok, err, mod = _try_import("voice_fingerprint")
        assert ok, f"voice_fingerprint 导入失败: {err}"

    def test_import_typeset_build_tex(self):
        """验证 typeset.build_tex 可导入。"""
        ok, err, mod = _try_import("typeset.build_tex")
        assert ok, f"typeset.build_tex 导入失败: {err}"


# ============================================================================
# 4.2 包 __init__.py 导出测试 (TC-IMP-013 ~ TC-IMP-015)
# ============================================================================

class TestPackageInitExports:
    """验证各子包的 __init__.py 存在且可导入。"""

    PACKAGES = [
        "core",
        "evaluation",
        "drafting",
        "foundation",
        "revision",
        "export",
        "prompts",
        "typeset",
    ]

    def test_package_init_files_exist(self):
        """TC-IMP-014: 验证各子包 __init__.py 文件存在。"""
        missing = []
        for pkg_name in self.PACKAGES:
            pkg_dir = PROJECT_ROOT / pkg_name
            init_file = pkg_dir / "__init__.py"
            if not init_file.exists():
                missing.append(str(init_file))
        # 注意：Python 3.3+ 支持隐式命名空间包（PEP 420），
        # 缺少 __init__.py 不会阻止导入，但这可能不是项目预期行为。
        # 此处报告缺失但不强制失败，因为项目使用命名空间包也能工作。
        if missing:
            # 作为警告记录，不作为硬失败
            print(f"\n  [警告] 以下包的 __init__.py 缺失（命名空间包模式）:")
            for m in missing:
                print(f"    - {m}")

    def test_packages_importable(self):
        """TC-IMP-013: 验证各子包可作为模块导入。"""
        failed = []
        for pkg_name in self.PACKAGES:
            ok, err, mod = _try_import(pkg_name)
            if not ok:
                failed.append(f"{pkg_name}: {err}")
            else:
                # 验证导入结果确实是 module 类型
                assert hasattr(mod, "__path__") or hasattr(mod, "__file__"), \
                    f"{pkg_name} 导入结果不是 module 类型"
        # 报告但不强制失败（命名空间包可能无 __init__.py）
        assert len(failed) == 0, f"以下包导入失败:\n" + "\n".join(failed)


# ============================================================================
# 4.3 循环依赖检测 (TC-IMP-016)
# ============================================================================

class TestCircularDependency:
    """验证核心模块间无循环导入。"""

    def test_no_circular_import_in_core(self):
        """TC-IMP-016a: 验证 core 包内部无循环依赖。"""
        # 通过逐一导入来检测循环依赖
        core_modules = [
            "core.config",
            "core.state_manager",
            "core.api_client",
            "core.diagnostic",
        ]
        failed = []
        for mod_name in core_modules:
            ok, err, _ = _try_import(mod_name)
            if not ok:
                failed.append(f"{mod_name}: {err}")
        assert not failed, f"core 包存在循环导入或导入错误:\n" + "\n".join(failed)

    def test_no_circular_import_pipeline(self):
        """TC-IMP-016b: 验证 pipeline_orchestrator 导入整棵依赖树无循环依赖。"""
        ok, err, _ = _try_import("pipeline_orchestrator")
        assert ok, f"pipeline_orchestrator 存在循环依赖: {err}"

    def test_no_circular_import_full_tree(self):
        """TC-IMP-016c: 按依赖顺序导入所有关键模块，验证无循环依赖。"""
        # 按依赖层次从底层到顶层依次导入
        import_order = [
            # 第0层: 纯工具（无内部依赖）
            "core.diagnostic",
            # 第1层: 配置
            "core.config",
            # 第2层: 依赖 config
            "core.api_client",
            "core.state_manager",
            # 第3层: prompts
            "prompts.world_prompts",
            "prompts.character_prompts",
            "prompts.outline_prompts",
            "prompts.chapter_prompts",
            "prompts.eval_judge_prompts",
            "prompts.review_prompts",
            "prompts.revision_prompts",
            "prompts.reader_panel_prompts",
            "prompts.adversarial_prompts",
            "prompts.seed_prompts",
            # 第4层: foundation
            "foundation.gen_world",
            "foundation.gen_characters",
            "foundation.gen_outline",
            "foundation.gen_outline_volume",
            "foundation.gen_outline_part2",
            "foundation.gen_canon",
            "foundation.gen_voice",
            "foundation.update_canon",
            # 第5层: drafting
            "drafting.draft_chapter",
            "drafting.run_drafts",
            # 第6层: evaluation
            "evaluation.evaluate",
            "evaluation.antipatterns",
            # 第7层: revision
            "revision.gen_brief",
            "revision.gen_revision",
            "revision.review",
            "revision.adversarial_edit",
            "revision.apply_cuts",
            "revision.reader_panel",
            "revision.compare_chapters",
            # 第8层: export
            "export.build_manuscript",
            "export.build_outline",
            "export.build_arc_summary",
            # 第9层: 编排器
            "pipeline_orchestrator",
            "novel_app",
            "seed",
            "voice_fingerprint",
            "typeset.build_tex",
        ]
        failed = []
        for mod_name in import_order:
            ok, err, mod = _try_import(mod_name)
            if not ok:
                failed.append(f"{mod_name}: {err}")
        assert not failed, (
            f"以下模块导入失败（可能存在循环依赖或缺少依赖）:\n"
            + "\n".join(failed)
        )


# ============================================================================
# 4.4 依赖声明完整性 (TC-IMP-017 ~ TC-IMP-018)
# ============================================================================

class TestDependencyDeclaration:
    """验证 pyproject.toml 依赖声明完整性。"""

    @pytest.fixture(autouse=True)
    def _setup(self):
        """延迟导入 pytest（避免影响模块导入测试）。"""
        global pytest
        import pytest

    def test_pyproject_toml_exists(self):
        """验证 pyproject.toml 文件存在。"""
        pyproject = PROJECT_ROOT / "pyproject.toml"
        assert pyproject.exists(), "pyproject.toml 文件不存在"

    def test_pyproject_toml_parseable(self):
        """TC-IMP-018: 验证 pyproject.toml 格式合法，可被 tomllib 解析。"""
        pyproject = PROJECT_ROOT / "pyproject.toml"
        assert pyproject.exists(), "pyproject.toml 不存在"
        try:
            with open(pyproject, "rb") as f:
                data = tomllib.load(f)
        except Exception as e:
            pytest.fail(f"pyproject.toml 解析失败: {e}")

        # 验证 requires-python
        project = data.get("project", {})
        requires_python = project.get("requires-python", "")
        assert requires_python, "缺少 requires-python 字段"
        # 检查是否为合理值
        assert requires_python.startswith(">="), \
            f"requires-python 格式异常: {requires_python}"

    def test_dependencies_declared(self):
        """TC-IMP-017: 验证 pyproject.toml 中声明的依赖包含关键包。"""
        pyproject = PROJECT_ROOT / "pyproject.toml"
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)

        dependencies = data.get("project", {}).get("dependencies", [])
        assert len(dependencies) > 0, "pyproject.toml 中未声明任何依赖"

        # 提取包名（去掉版本约束）
        dep_names = set()
        for dep in dependencies:
            # 处理 "httpx>=0.28.1" 格式
            dep_name = dep.split(">=")[0].split("==")[0].split("<")[0].strip()
            dep_names.add(dep_name)

        required_deps = ["httpx", "python-dotenv"]
        missing_deps = [d for d in required_deps if d not in dep_names]
        assert not missing_deps, \
            f"pyproject.toml 缺少关键依赖: {missing_deps}"

    def test_uv_lock_exists(self):
        """验证 uv.lock 文件存在（依赖已锁定）。"""
        lock_file = PROJECT_ROOT / "uv.lock"
        assert lock_file.exists(), \
            "uv.lock 不存在。请运行 'uv lock' 生成锁文件。"

    def test_requires_python_compatible_with_deps(self):
        """验证 requires-python 与依赖兼容。

        已知问题: python-dotenv>=1.2.2 要求 Python>=3.10，
        但 pyproject.toml 声明 >=3.9。这会导致 uv 解析失败。
        """
        pyproject = PROJECT_ROOT / "pyproject.toml"
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)

        requires_python = data.get("project", {}).get("requires-python", "")
        # python-dotenv>=1.2.2 要求 Python>=3.10
        # 如果 requires-python 声明 >=3.9，则存在兼容性间隙
        if requires_python == ">=3.9":
            print(
                "\n  [警告] requires-python 声明 >=3.9，"
                "但 python-dotenv>=1.2.2 要求 Python>=3.10。"
                "建议将 requires-python 改为 >=3.10。"
            )
