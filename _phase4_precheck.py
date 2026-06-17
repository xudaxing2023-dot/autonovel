#!/usr/bin/env python3
"""
阶段4 快速预检模块 — 零 API 调用的静态/单元级验证。

验证测试2/3/4 的代码路径正确性，在投入 ¥2.50 + 2h 之前快速排查代码缺陷。

用法：
  python _phase4_precheck.py          # 全部预检
  python _phase4_precheck.py --test 4 # 只预检测试4 (文件备份)
  python _phase4_precheck.py --test 3 # 只预检测试3 (Resume)
  python _phase4_precheck.py --test 2 # 只预检测试2 (12章)
"""

import inspect
import json
import sys
import tempfile
import traceback
from pathlib import Path

# Windows 控制台编码
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

OUTPUT = ROOT / "output"
CHAPTERS = OUTPUT / "chapters"
BACKUPS = OUTPUT / "backups"
CONFIG_FILE = OUTPUT / "config.json"


# ============================================================================
# 辅助函数
# ============================================================================

def print_results(results: list, test_name: str):
    """打印预检结果汇总。"""
    print(f"\n{'─' * 50}")
    print(f"  [RESULTS] {test_name}")
    print(f"{'─' * 50}")
    passed = 0
    failed = 0
    for name, ok, msg in results:
        status = "[OK]" if ok else "[FAIL]"
        if ok:
            passed += 1
        else:
            failed += 1
        print(f"  {status} {name}: {msg}")
    print(f"  --------")
    print(f"  通过: {passed}, 失败: {failed}, 总计: {passed + failed}")


def _header(category: str):
    print(f"\n{'=' * 60}")
    print(f"  预检 — P{category}")
    print(f"{'=' * 60}")


# ============================================================================
# P1: 测试4 (文件备份) 预检
# ============================================================================

def precheck_4_file_backup() -> list:
    """P1: 验证文件备份/恢复机制代码路径。"""
    _header("1")
    results = []

    from core.state_manager import (
        backup_snapshot, restore_latest, _has_git, git_available,
    )

    # P1.1 backup_snapshot() 目录创建 + 文件复制
    with tempfile.TemporaryDirectory() as tmp:
        tmp_out = Path(tmp) / "output"
        tmp_chapters = tmp_out / "chapters"
        tmp_chapters.mkdir(parents=True)
        tmp_backups = tmp_out / "backups"
        (tmp_out / "world.md").write_text("# World\n测试世界观", encoding="utf-8")
        (tmp_out / "state.json").write_text('{"phase":"test"}', encoding="utf-8")
        (tmp_chapters / "ch_01.md").write_text("# Ch1\n内容", encoding="utf-8")

        import core.state_manager as _sm
        _orig_out = _sm.OUTPUT_DIR
        _orig_ch = _sm.CHAPTERS_DIR
        _orig_bk = _sm.BACKUPS_DIR
        try:
            _sm.OUTPUT_DIR = tmp_out
            _sm.CHAPTERS_DIR = tmp_chapters
            _sm.BACKUPS_DIR = tmp_backups

            snap_id = backup_snapshot("precheck backup test")
            snaps = sorted([d for d in tmp_backups.iterdir() if d.is_dir()],
                           key=lambda p: p.name)
            has_files = False
            if snaps:
                latest_snap = snaps[-1]
                has_files = (latest_snap / "world.md").exists() and \
                    (latest_snap / "state.json").exists() and \
                    (latest_snap / "chapters" / "ch_01.md").exists()
            results.append(("P1.1 backup_snapshot 文件复制",
                            len(snaps) > 0 and has_files,
                            f"{len(snaps)} 快照, 文件完整={has_files}"))
        finally:
            _sm.OUTPUT_DIR = _orig_out
            _sm.CHAPTERS_DIR = _orig_ch
            _sm.BACKUPS_DIR = _orig_bk

    # P1.2 restore_latest() 恢复逻辑
    with tempfile.TemporaryDirectory() as tmp:
        tmp_out = Path(tmp) / "output"
        tmp_chapters = tmp_out / "chapters"
        tmp_chapters.mkdir(parents=True)
        tmp_backups = tmp_out / "backups"

        snap_dir = tmp_backups / "20260615_000000"
        snap_dir.mkdir(parents=True)
        (snap_dir / "world.md").write_text("RESTORED_WORLD", encoding="utf-8")
        (snap_dir / "label.txt").write_text("test", encoding="utf-8")
        (snap_dir / "chapters").mkdir()
        (snap_dir / "chapters" / "ch_01.md").write_text("RESTORED_CH1", encoding="utf-8")

        import core.state_manager as _sm2
        _o2, _c2, _b2 = _sm2.OUTPUT_DIR, _sm2.CHAPTERS_DIR, _sm2.BACKUPS_DIR
        try:
            _sm2.OUTPUT_DIR = tmp_out
            _sm2.CHAPTERS_DIR = tmp_chapters
            _sm2.BACKUPS_DIR = tmp_backups

            ok = restore_latest()
            restored_ok = ok and \
                (tmp_out / "world.md").read_text(encoding="utf-8") == "RESTORED_WORLD" and \
                (tmp_chapters / "ch_01.md").read_text(encoding="utf-8") == "RESTORED_CH1"
            results.append(("P1.2 restore_latest 正确恢复",
                            restored_ok,
                            "恢复成功 [v]" if restored_ok else "恢复失败"))
        finally:
            _sm2.OUTPUT_DIR = _o2
            _sm2.CHAPTERS_DIR = _c2
            _sm2.BACKUPS_DIR = _b2

    # P1.3 test_4_file_backup_mode finally 块确保 .git 恢复
    from _phase4_test import test_4_file_backup_mode
    t4_src = inspect.getsource(test_4_file_backup_mode)
    has_finally_git = "git_backup_path.exists()" in t4_src and \
        "shutil.move" in t4_src
    results.append(("P1.3 finally 块恢复 .git",
                    has_finally_git,
                    "存在" if has_finally_git else "缺失"))

    # P1.4 空 backups/ restore_latest() 返回 False
    with tempfile.TemporaryDirectory() as tmp:
        tmp_out = Path(tmp) / "output"
        tmp_out.mkdir()
        tmp_backups = tmp_out / "backups"
        tmp_backups.mkdir()

        import core.state_manager as _sm4
        _o4, _b4 = _sm4.OUTPUT_DIR, _sm4.BACKUPS_DIR
        try:
            _sm4.OUTPUT_DIR = tmp_out
            _sm4.BACKUPS_DIR = tmp_backups
            ok = restore_latest()
            results.append(("P1.4 空backups/ restore_latest 返回False",
                            not ok,
                            f"返回 {ok} (预期 False)"))
        finally:
            _sm4.OUTPUT_DIR = _o4
            _sm4.BACKUPS_DIR = _b4

    # P1.5 _GIT_AVAILABLE 缓存正确
    import core.state_manager as _sm5
    _orig_cache = _sm5._GIT_AVAILABLE
    try:
        _sm5._GIT_AVAILABLE = None
        r1 = git_available()
        r2 = git_available()  # 第二次应使用缓存
        results.append(("P1.5 _GIT_AVAILABLE 缓存",
                        r1 == r2,
                        f"一致: {r1}"))
    finally:
        _sm5._GIT_AVAILABLE = _orig_cache

    # P1.6 _has_git subprocess 检测
    hg_src = inspect.getsource(_has_git)
    has_subprocess_git = 'subprocess.run' in hg_src and 'git' in hg_src
    results.append(("P1.6 _has_git subprocess 检测 git",
                    has_subprocess_git,
                    "存在" if has_subprocess_git else "缺失"))

    print_results(results, "预检P1: 测试4 (文件备份) 代码路径")
    return results


# ============================================================================
# P2: 测试3 (Resume) 预检
# ============================================================================

def precheck_3_resume() -> list:
    """P2: 验证 Resume 恢复流程代码路径。"""
    _header("2")
    results = []

    # P2.1 run_foundation 结尾设 phase="drafting"
    from pipeline_orchestrator import run_foundation
    f_src = inspect.getsource(run_foundation)
    has_phase_drafting = 'phase\"] = \"drafting\"' in f_src or \
                         "phase'] = 'drafting'" in f_src
    results.append(("P2.1 run_foundation 设 phase=drafting",
                    has_phase_drafting,
                    "存在" if has_phase_drafting else "不存在"))

    # P2.2 PHASE_ORDER + start_idx 跳过逻辑
    from pipeline_orchestrator import PHASE_ORDER, run_pipeline
    p_src = inspect.getsource(run_pipeline)
    expected_order = ["foundation", "drafting", "revision", "export"]
    has_phase_logic = "PHASE_ORDER" in p_src and "start_idx" in p_src
    results.append(("P2.2 PHASE_ORDER + start_idx 跳过逻辑",
                    has_phase_logic and PHASE_ORDER == expected_order,
                    f"PHASE_ORDER={'→'.join(PHASE_ORDER)}" if has_phase_logic
                    else "缺失"))

    # P2.3 Foundation 时间戳比对
    from _phase4_test import test_3_resume_recovery
    t3_src = inspect.getsource(test_3_resume_recovery)
    has_ts_check = "foundation_timestamps" in t3_src and "st_mtime" in t3_src
    results.append(("P2.3 Foundation 时间戳比对逻辑",
                    has_ts_check,
                    "存在" if has_ts_check else "缺失"))

    # P2.4 state.phase="complete" 时 resume 拒绝
    has_complete_guard = 'phase\") == \"complete\"' in p_src or \
                         "phase'] == 'complete'" in p_src
    results.append(("P2.4 phase=complete 时 resume 拒绝",
                    has_complete_guard,
                    "存在守卫" if has_complete_guard else "缺失"))

    # P2.5 run_drafting 从 chapters_drafted+1 开始
    from pipeline_orchestrator import run_drafting
    d_src = inspect.getsource(run_drafting)
    has_start_chapter = 'start_chapter' in d_src and 'chapters_drafted' in d_src
    results.append(("P2.5 run_drafting start_chapter=drafted+1",
                    has_start_chapter,
                    "存在" if has_start_chapter else "缺失"))

    print_results(results, "预检P2: 测试3 (Resume) 代码路径")
    return results


# ============================================================================
# P3: 测试2 (12章) 预检
# ============================================================================

def precheck_2_twelve() -> list:
    """P3: 验证 12 章规模相关代码路径。"""
    _header("3")
    results = []

    # P3.1 count_words_in_chapters() 统计正确
    with tempfile.TemporaryDirectory() as tmp:
        ch_dir = Path(tmp) / "chapters"
        ch_dir.mkdir()
        for i in range(1, 13):
            (ch_dir / f"ch_{i:02d}.md").write_text(
                f"# 第{i}章\n\n这是第{i}章的内容。" * 100, encoding="utf-8")
        import core.state_manager as sm
        _orig_chapters = sm.CHAPTERS_DIR
        try:
            sm.CHAPTERS_DIR = ch_dir
            wc = sm.count_words_in_chapters()
            results.append(("P3.1 count_words_in_chapters 统计12章",
                            wc > 10000,
                            f"{wc} 字 (预期 > 10000)"))
        finally:
            sm.CHAPTERS_DIR = _orig_chapters

    # P3.2 write_config(total_chapters=12) 写入正确
    from _phase4_test import write_config, CONFIG_FILE as _CFG, OUTPUT as _OUT
    with tempfile.TemporaryDirectory() as tmp:
        tmp_out = Path(tmp) / "output"
        tmp_cfg = tmp_out / "config.json"
        # monkey-patch via import
        import _phase4_test as _p4
        _orig_cfg = _p4.CONFIG_FILE
        _orig_out = _p4.OUTPUT
        try:
            _p4.CONFIG_FILE = tmp_cfg
            _p4.OUTPUT = tmp_out
            _p4.write_config(total_chapters=12)
            data = json.loads(tmp_cfg.read_text(encoding="utf-8"))
            ch = data.get("total_chapters", 0)
            results.append(("P3.2 write_config total_chapters=12",
                            ch == 12, f"total_chapters={ch}"))
        finally:
            _p4.CONFIG_FILE = _orig_cfg
            _p4.OUTPUT = _orig_out

    # P3.3 build_manuscript 可导入
    try:
        from export.build_manuscript import build_manuscript as _bm
        results.append(("P3.3 build_manuscript 可导入",
                        _bm is not None, "import 成功"))
    except Exception as e:
        results.append(("P3.3 build_manuscript 可导入",
                        False, str(e)))

    # P3.4 get_total_chapters 从 config 读取
    import core.config as _cfg_mod
    import core.state_manager as _sm_mod
    _orig_data = dict(_cfg_mod.config._data)
    _orig_loaded = _cfg_mod.config._loaded
    _orig_load = _cfg_mod.config.load
    try:
        _cfg_mod.config._data = {"total_chapters": 12}
        _cfg_mod.config._loaded = True
        # 阻止 cfg.load() 重新从文件读取覆盖 mock 数据
        _cfg_mod.config.load = lambda: _cfg_mod.config._data
        total = _sm_mod.get_total_chapters({"chapters_total": 0})
        results.append(("P3.4 get_total_chapters 从config读=12",
                        total == 12, f"total={total}"))
    finally:
        _cfg_mod.config._data = _orig_data
        _cfg_mod.config._loaded = _orig_loaded
        _cfg_mod.config.load = _orig_load

    # P3.5 MIN_REVISION_CYCLES 常量
    from pipeline_orchestrator import MIN_REVISION_CYCLES
    results.append(("P3.5 MIN_REVISION_CYCLES=3",
                    MIN_REVISION_CYCLES == 3,
                    f"MIN_REVISION_CYCLES={MIN_REVISION_CYCLES}"))

    print_results(results, "预检P3: 测试2 (12章) 代码路径")
    return results


# ============================================================================
# 调度 & 主入口
# ============================================================================

PRECHECK_MAP = {
    4: ("P1: 测试4 文件备份", precheck_4_file_backup),
    3: ("P2: 测试3 Resume", precheck_3_resume),
    2: ("P3: 测试2 12章", precheck_2_twelve),
}


def run_prechecks(tests: list) -> dict:
    """运行指定测试编号的预检。返回 {name: results}。"""
    all_results = {}
    for t in tests:
        if t in PRECHECK_MAP:
            label, fn = PRECHECK_MAP[t]
            try:
                all_results[label] = fn()
            except Exception as e:
                print(f"\n  [FAIL] 预检 {label} 异常: {e}")
                traceback.print_exc()
                all_results[label] = [("异常", False, str(e))]
        else:
            print(f"  [WARN] 未知预检编号: {t}")

    # 汇总
    grand_pass = sum(1 for res_list in all_results.values()
                     for _, ok, _ in res_list if ok)
    grand_fail = sum(1 for res_list in all_results.values()
                     for _, ok, _ in res_list if not ok)
    print(f"\n{'=' * 60}")
    print(f"  [PRECHECK SUMMARY] 阶段4 预检汇总 (零 API 调用)")
    print(f"{'=' * 60}")
    for test_name, res_list in all_results.items():
        p = sum(1 for _, ok, _ in res_list if ok)
        f = sum(1 for _, ok, _ in res_list if not ok)
        print(f"  {test_name}: {p}[OK] {f}[FAIL] ({p+f} 项)")
    print(f"  --------")
    print(f"  总计: {grand_pass}[OK] {grand_fail}[FAIL] ({grand_pass + grand_fail} 项)")
    return all_results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="阶段4 快速预检 — 零 API 调用的静态/单元级验证")
    parser.add_argument("--test", type=int, choices=[2, 3, 4],
                        help="只预检指定测试")
    args = parser.parse_args()

    if args.test:
        tests = [args.test]
    else:
        tests = [4, 3, 2]  # 按推荐顺序

    run_prechecks(tests)