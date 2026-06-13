#!/usr/bin/env python3
"""
阶段4：端到端验证 — 完整流水线测试

测试项：
  测试1: 3章 from_scratch（DeepSeek-V4-Flash）
  测试2: 12章 from_scratch（DeepSeek-V4-Flash）
  测试3: Resume 中断恢复（Foundation → 模拟中断 → resume）
  测试4: 无 Git 文件备份模式

用法：
  python _phase4_test.py --test 1    # 只跑测试1（3章）
  python _phase4_test.py --test 2    # 只跑测试2（12章）
  python _phase4_test.py --test 3    # 只跑测试3（Resume）
  python _phase4_test.py --test 4    # 只跑测试4（文件备份）
  python _phase4_test.py --all       # 按顺序跑全部（预计2小时+）
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from queue import Queue, Empty

# Windows 控制台 GBK 编码不支持 emoji，强制使用 UTF-8
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ============================================================================
# 路径
# ============================================================================
ROOT = Path(r"e:/my novel")
sys.path.insert(0, str(ROOT))

OUTPUT = ROOT / "output"
CHAPTERS = OUTPUT / "chapters"
BACKUPS = OUTPUT / "backups"
EDIT_LOGS = OUTPUT / "edit_logs"
EVAL_LOGS = OUTPUT / "eval_logs"
BRIEFS = OUTPUT / "briefs"

CONFIG_FILE = OUTPUT / "config.json"
STATE_FILE = OUTPUT / "state.json"
RESULTS_FILE = OUTPUT / "results.tsv"
MANUSCRIPT_FILE = OUTPUT / "manuscript.md"

MODEL = "deepseek-ai/DeepSeek-V4-Flash"

# ============================================================================
# 辅助函数
# ============================================================================

def load_existing_api_key() -> tuple:
    """从已有 config.json 读取 API Key，避免硬编码。"""
    cfg_path = ROOT / "output" / "config.json"
    if cfg_path.exists():
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            return (
                data.get("api_key", ""),
                data.get("api_base_url", "https://api.siliconflow.cn/v1"),
            )
        except Exception:
            pass
    return "", "https://api.siliconflow.cn/v1"


def write_config(total_chapters: int, model_name: str = MODEL) -> None:
    """写入测试用 config.json。"""
    api_key, api_base = load_existing_api_key()
    if not api_key:
        print("[WARN] 未能从已有 config.json 读取 api_key，"
              "请确认 output/config.json 中存在有效 api_key")
    cfg = {
        "story_summary": (
            "一个年轻程序员在2049年的上海发现自己写的AI系统已经觉醒，"
            "他必须在36小时内找到并解除它，否则它将接管全球网络。"
            "悬疑科幻风格，节奏紧凑。"
        ),
        "total_chapters": total_chapters,
        "api_base_url": api_base,
        "api_key": api_key,
        "model_name": model_name,
        "api_interval_seconds": 4,
        "mode": "from_scratch",
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    json.dump(cfg, open(CONFIG_FILE, "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)
    print(f"  [CONFIG] total_chapters={total_chapters}, model={model_name}")


def reset_state() -> None:
    """重置 state.json 为默认状态。"""
    from core.state_manager import default_state, save_state
    save_state(default_state())
    print("  [STATE] 已重置为默认状态")


def clean_output(keep_config: bool = True) -> None:
    """清空所有生成输出，可选保留 config.json。"""
    dirs = [CHAPTERS, BRIEFS, EDIT_LOGS, EVAL_LOGS, BACKUPS]
    for d in dirs:
        if d.exists():
            shutil.rmtree(str(d))
            print(f"  [CLEAN] 已删除 {d.relative_to(ROOT)}")
    files = ["manuscript.md", "state.json", "results.tsv",
             "story_summary.txt", "world.md", "characters.md",
             "outline.md", "canon.md", "voice.md", "MYSTERY.md"]
    for fn in files:
        fp = OUTPUT / fn
        if fp.exists():
            fp.unlink()
            print(f"  [CLEAN] 已删除 {fn}")


def run_pipeline(mode: str = "from_scratch") -> tuple:
    """
    以子进程方式运行 pipeline_orchestrator，实时流式输出。

    使用独立线程读取 stdout 到队列 + 主线程轮询，
    彻底消除 Popen stdout 阻塞死锁风险。
    无超时限制——流水线自然完成，用户可按 Ctrl+C 随时中断。

    返回 (exit_code, elapsed_seconds, output_lines)。
    """
    print(f"\n{'=' * 70}")
    print(f"  [START] 启动流水线: pipeline_orchestrator --mode {mode}")
    print(f"{'=' * 70}")
    sys.stdout.flush()

    t0 = time.time()

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.Popen(
        [sys.executable, "-u", str(ROOT / "pipeline_orchestrator.py"),
         "--mode", mode],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
    )

    captured_lines = []
    line_queue: Queue = Queue()
    reader_done = threading.Event()

    def _reader_thread():
        """独立线程读取 stdout，避免主线程阻塞。"""
        try:
            for raw_line in proc.stdout:
                line = raw_line.decode("utf-8", errors="replace").rstrip("\n")
                line_queue.put(line)
        except Exception:
            pass
        finally:
            reader_done.set()
            # 确保主线程不会在 queue.get 上无限等
            line_queue.put(None)

    reader = threading.Thread(target=_reader_thread, daemon=True)
    reader.start()

    try:
        while True:
            # 主线程轮询：检查子进程是否退出
            poll_rc = proc.poll()
            if poll_rc is not None:
                # 子进程已退出，排空剩余队列
                reader.join(timeout=5)
                while True:
                    try:
                        line = line_queue.get_nowait()
                        if line is None:
                            break
                        try:
                            print(line, flush=True)
                        except UnicodeEncodeError:
                            print(line.encode("ascii", errors="replace").decode("ascii"), flush=True)
                        captured_lines.append(line)
                    except Empty:
                        break
                break

            # 非阻塞消费队列中的行
            try:
                line = line_queue.get(timeout=2.0)
                if line is None:
                    break
                try:
                    print(line, flush=True)
                except UnicodeEncodeError:
                    print(line.encode("ascii", errors="replace").decode("ascii"), flush=True)
                captured_lines.append(line)
            except Empty:
                # 2秒无输出，继续轮询
                pass

    except KeyboardInterrupt:
        proc.kill()
        proc.wait()
        captured_lines.append("[INTERRUPT] 用户中断")
        print("[INTERRUPT] 用户中断", flush=True)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()

    elapsed = time.time() - t0
    return proc.returncode, elapsed, captured_lines


def verify_file(path: Path, min_bytes: int = 100,
                label: str = "") -> tuple:
    """验证文件存在且 >= min_bytes。返回 (label, ok, message)。"""
    if not path.exists():
        return label, False, f"{label} 不存在"
    size = path.stat().st_size
    if size < min_bytes:
        return label, False, f"{label} 过小 ({size} < {min_bytes} bytes)"
    return label, True, f"{label} [v] ({size} bytes)"


def print_results(results: list, test_name: str, elapsed: float) -> None:
    """打印测试结果汇总。"""
    print(f"\n{'=' * 60}")
    print(f"  [RESULTS] {test_name} 结果 ({elapsed:.0f}s)")
    print(f"{'=' * 60}")
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


# ============================================================================
# Test 1: 3章 from_scratch
# ============================================================================

def test_1_three_chapters() -> list:
    """最小化流水线 3 章 from_scratch。"""
    print("\n" + "=" * 70)
    print("  测试 1: 最小化流水线 -- 3 章 from_scratch (DeepSeek-V4-Flash)")
    print("=" * 70)

    clean_output(keep_config=False)
    write_config(total_chapters=3)
    reset_state()

    rc, elapsed, lines = run_pipeline("from_scratch")

    results = []
    results.append(("流水线退出码", rc == 0,
                    f"exit={rc} ({elapsed/60:.1f}min)"))

    # Foundation 文件
    foundation_checks = [
        (OUTPUT / "world.md", 500, "world.md"),
        (OUTPUT / "characters.md", 200, "characters.md"),
        (OUTPUT / "outline.md", 300, "outline.md"),
        (OUTPUT / "canon.md", 200, "canon.md"),
        (OUTPUT / "voice.md", 300, "voice.md"),
    ]
    for path, min_b, label in foundation_checks:
        results.append(verify_file(path, min_b, label))

    # 章节文件
    for ch in range(1, 4):
        ch_path = CHAPTERS / f"ch_{ch:02d}.md"
        results.append(verify_file(ch_path, 500, f"ch_{ch:02d}.md"))

    # 手稿
    results.append(verify_file(MANUSCRIPT_FILE, 1000,
                                "manuscript.md"))

    # 手稿内容验证：必须包含 3 章分隔符
    if MANUSCRIPT_FILE.exists():
        text = MANUSCRIPT_FILE.read_text(encoding="utf-8")
        sep_count = text.count("---")
        results.append(("手稿包含章节分隔", sep_count >= 2,
                        f"分隔符数={sep_count}"))

    # state.json
    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        phase = state.get("phase", "?")
        drafted = state.get("chapters_drafted", 0)
        total = state.get("chapters_total", 0)
        score = state.get("novel_score", 0)
        revision_cycle = state.get("revision_cycle", 0)
        results.append(("state.phase=complete", phase == "complete", f"phase={phase}"))
        results.append(("state.chapters_drafted=3", drafted == 3, f"drafted={drafted}"))
        results.append(("state.chapters_total=3", total == 3, f"total={total}"))
        results.append(("state.novel_score>0", score > 0, f"score={score}"))
        results.append(("state.revision_cycle>=3", revision_cycle >= 3,
                        f"cycles={revision_cycle}"))

    # results.tsv
    if RESULTS_FILE.exists():
        lines = RESULTS_FILE.read_text(encoding="utf-8").strip().split("\n")
        results.append(("results.tsv 有记录", len(lines) > 1,
                        f"{len(lines)} 行"))

    print_results(results, "测试1: 3章 from_scratch", elapsed)
    return results


# ============================================================================
# Test 2: 12章 from_scratch
# ============================================================================

def test_2_twelve_chapters() -> list:
    """完整流水线 12 章 from_scratch。"""
    print("\n" + "=" * 70)
    print("  测试 2: 完整流水线 -- 12 章 from_scratch (DeepSeek-V4-Flash)")
    print("=" * 70)

    clean_output(keep_config=False)
    write_config(total_chapters=12)
    reset_state()

    rc, elapsed, lines = run_pipeline("from_scratch")

    results = []
    results.append(("流水线退出码", rc == 0,
                    f"exit={rc} ({elapsed/60:.1f}min)"))

    # Foundation 文件
    for label in ["world.md", "characters.md", "outline.md",
                   "canon.md", "voice.md"]:
        results.append(verify_file(OUTPUT / label, 300, label))

    # 所有 12 章
    all_chapters_ok = True
    for ch in range(1, 13):
        label, ok, msg = verify_file(CHAPTERS / f"ch_{ch:02d}.md", 500,
                              f"ch_{ch:02d}.md")
        if not ok:
            all_chapters_ok = False
        results.append((f"ch_{ch:02d}.md", ok, msg))
    results.append(("全部12章文件存在", all_chapters_ok,
                    "[v]" if all_chapters_ok else "[FAIL] 缺失"))

    # 手稿
    results.append(verify_file(MANUSCRIPT_FILE, 3000,
                                "manuscript.md"))

    # 总字数
    from core.state_manager import count_words_in_chapters
    total_words = count_words_in_chapters()
    results.append(("总字数 >= 24000", total_words >= 24000,
                    f"{total_words} 字"))

    # state.json
    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        phase = state.get("phase", "?")
        drafted = state.get("chapters_drafted", 0)
        total = state.get("chapters_total", 0)
        score = state.get("novel_score", 0)
        revision_cycle = state.get("revision_cycle", 0)
        results.append(("state.phase=complete", phase == "complete",
                        f"phase={phase}"))
        results.append(("state.chapters_drafted=12", drafted == 12,
                        f"drafted={drafted}"))
        results.append(("state.chapters_total=12", total == 12,
                        f"total={total}"))
        results.append(("state.novel_score>0", score > 0,
                        f"score={score}"))
        results.append(("state.revision_cycle>=3",
                        revision_cycle >= 3, f"cycles={revision_cycle}"))

    # results.tsv 行数
    if RESULTS_FILE.exists():
        lines = RESULTS_FILE.read_text(encoding="utf-8").strip().split("\n")
        results.append(("results.tsv 记录数", len(lines) >= 10,
                        f"{len(lines)} 行"))

    print_results(results, "测试2: 12章 from_scratch", elapsed)
    return results


# ============================================================================
# Test 3: Resume 中断恢复
# ============================================================================

def test_3_resume_recovery() -> list:
    """
    模拟中断恢复:
    1. 运行 Foundation（Phase 1）
    2. 手动设置 state.phase = "drafting"（模拟 Ctrl+C 在 Foundation 结束后中断）
    3. 以 --mode resume 继续
    """
    print("\n" + "=" * 70)
    print("  测试 3: Resume 中断恢复 (DeepSeek-V4-Flash)")
    print("=" * 70)

    clean_output(keep_config=False)
    write_config(total_chapters=3)
    reset_state()

    # ============ Phase A: 运行 Foundation ============
    print("\n  -- Phase A: 运行 Foundation 阶段 --")
    from core.config import config as cfg
    from core.state_manager import load_state, save_state, step
    from pipeline_orchestrator import run_foundation

    cfg.load()
    state = load_state()

    t0_foundation = time.time()
    try:
        state = run_foundation(state)
    except Exception as e:
        print(f"  [ERROR] Foundation 失败: {e}")
        traceback.print_exc()
        return [("Foundation 执行", False, str(e))]
    foundation_elapsed = time.time() - t0_foundation

    # 验证 Foundation 产物
    foundation_results = []
    for label in ["world.md", "characters.md", "outline.md",
                   "canon.md", "voice.md"]:
        label, ok, msg = verify_file(OUTPUT / label, 200, label)
        foundation_results.append((f"Foundation: {label}", ok, msg))

    print(f"\n  Foundation 完成 ({foundation_elapsed:.0f}s)")
    for name, ok, msg in foundation_results:
        print(f"  {'[OK]' if ok else '[FAIL]'} {msg}")

    if not all(ok for _, ok, _ in foundation_results):
        return foundation_results

    # ============ Phase B: 模拟中断，修改 state ============
    print("\n  -- Phase B: 模拟 Ctrl+C 中断 --")
    state = load_state()
    # run_foundation 已经设置 phase="drafting"，此处显式确认
    state["phase"] = "drafting"
    state["current_focus"] = "chapter_drafting"
    save_state(state)
    print(f"  [SIMULATE] state.phase = drafting (模拟 Foundation 后中断)")
    print(f"  [SIMULATE] state.chapters_drafted = {state.get('chapters_drafted', 0)}")

    # 记录 Foundation 产物时间戳用于后续验证
    foundation_timestamps = {}
    for label in ["world.md", "characters.md", "outline.md",
                   "canon.md", "voice.md"]:
        path = OUTPUT / label
        if path.exists():
            foundation_timestamps[label] = path.stat().st_mtime

    # ============ Phase C: Resume 继续 ============
    print("\n  -- Phase C: --mode resume 继续 --")
    # 强制 overwrite config mode 为 resume（不影响 pipeline 的 --mode 参数）
    cfg_data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    cfg_data["mode"] = "resume"
    json.dump(cfg_data, open(CONFIG_FILE, "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)

    rc, elapsed, lines = run_pipeline("resume")

    results = []
    results.append(("Resume 退出码", rc == 0,
                    f"exit={rc} ({elapsed/60:.1f}min)"))

    # 验证 Foundation 产物未被二次生成（时间戳不变）
    for label, ts in foundation_timestamps.items():
        path = OUTPUT / label
        if path.exists():
            new_ts = path.stat().st_mtime
            unchanged = abs(new_ts - ts) < 2  # 允许 2 秒浮动
            results.append((f"Foundation {label} 未二次生成",
                            unchanged,
                            "时间戳不变 [v]" if unchanged
                            else f"时间戳已变 ({ts:.0f} -> {new_ts:.0f})"))

    # 验证章节
    for ch in range(1, 4):
        results.append(verify_file(CHAPTERS / f"ch_{ch:02d}.md", 500,
                                   f"ch_{ch:02d}.md"))

    # 验证手稿
    results.append(verify_file(MANUSCRIPT_FILE, 500,
                                "manuscript.md"))

    # 验证 state 到达 complete
    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        results.append(("state.phase=complete",
                        state.get("phase") == "complete",
                        f"phase={state.get('phase', '?')}"))
        results.append(("state.chapters_drafted=3",
                        state.get("chapters_drafted", 0) == 3,
                        f"drafted={state.get('chapters_drafted', 0)}"))

    # 验证日志中无 "从头开始生成" 横幅
    log_text = "\n".join(lines)
    from_scratch_banner = "从头开始生成" in log_text
    results.append(("Resume 无from_scratch横幅",
                    not from_scratch_banner,
                    "未出现" if not from_scratch_banner else "[FAIL] 出现了"))

    print_results(results, "测试3: Resume 中断恢复", elapsed)
    return results


# ============================================================================
# Test 4: 无 Git 文件备份模式
# ============================================================================

def test_4_file_backup_mode() -> list:
    """
    验证无 Git 环境下文件快照备份：
    1. 临时重命名 .git 目录
    2. 运行 3 章流水线
    3. 验证 backups/ 目录正确生成
    4. 验证 restore_latest() 正确恢复
    5. 恢复 .git 目录
    """
    print("\n" + "=" * 70)
    print("  测试 4: 无 Git 文件备份模式 (DeepSeek-V4-Flash)")
    print("=" * 70)

    results = []
    git_disabled = False
    git_backup_path = ROOT / ".git_disabled_backup"
    git_path = ROOT / ".git"

    try:
        # Step 1: 临时禁用 Git
        if git_path.exists():
            print("\n  -- Step 1: 临时重命名 .git --")
            try:
                if git_backup_path.exists():
                    shutil.rmtree(str(git_backup_path))
                shutil.move(str(git_path), str(git_backup_path))
                git_disabled = True
                print(f"  [GIT] .git -> .git_disabled_backup")
            except PermissionError as e:
                print(f"  [WARN] 无法重命名 .git (权限): {e}")
                results.append(("禁用Git", False, str(e)))
        else:
            print("  [GIT] 无 .git 目录，无需禁用")
            git_disabled = True  # 本来就无 git

        if not git_disabled:
            results.append(("Git环境", False, "无法禁用Git"))
            return results

        results.append(("禁用Git", True, ".git 已重命名"))

        # Step 2: 运行流水线
        print("\n  -- Step 2: 运行 3 章流水线 --")
        clean_output(keep_config=True)
        write_config(total_chapters=3)
        reset_state()

        rc, elapsed, lines = run_pipeline("from_scratch")
        results.append(("流水线退出码", rc == 0,
                        f"exit={rc} ({elapsed/60:.1f}min)"))

        # Step 3: 验证备份目录
        print("\n  -- Step 3: 验证备份目录 --")
        if BACKUPS.exists():
            snapshots = sorted(
                [d for d in BACKUPS.iterdir() if d.is_dir()],
                key=lambda p: p.name,
            )
            results.append(("backups/ 存在snapshot",
                            len(snapshots) > 0,
                            f"{len(snapshots)} 个快照"))

            for snap in snapshots:
                # 检查 label.txt
                label_file = snap / "label.txt"
                has_label = label_file.exists()
                # 检查关键文件
                key_files = ["state.json", "world.md", "characters.md"]
                missing_keys = [f for f in key_files
                                if not (snap / f).exists()]
                # 检查 chapters 子目录
                ch_dir = snap / "chapters"
                has_chapters = ch_dir.exists() and \
                    len(list(ch_dir.glob("ch_*.md"))) > 0
                print(f"  [SNAP] {snap.name}: label={'[v]' if has_label else '[x]'}, "
                      f"chapters={'[v]' if has_chapters else '[x]'}, "
                      f"missing={missing_keys if missing_keys else '无'}")

            # 汇总
            latest = snapshots[-1] if snapshots else None
            if latest:
                label_ok = (latest / "label.txt").exists()
                chapters_ok = (latest / "chapters").exists() and \
                    len(list((latest / "chapters").glob("ch_*.md"))) > 0
                results.append(("最新快照有label", label_ok,
                                "[v]" if label_ok else "[x]"))
                results.append(("最新快照有章节", chapters_ok,
                                "[v]" if chapters_ok else "[x]"))
        else:
            results.append(("backups/ 目录", False, "不存在"))

        # Step 4: 验证 restore_latest()
        print("\n  -- Step 4: 验证 restore_latest() --")
        from core.state_manager import restore_latest

        # 先删除一个章节文件来验证恢复
        ch1_path = CHAPTERS / "ch_01.md"
        ch1_backup = None
        if ch1_path.exists():
            ch1_backup = ch1_path.read_text(encoding="utf-8")
            ch1_path.unlink()
            print(f"  [TEST] 删除 ch_01.md 以测试恢复")

        restored = restore_latest()
        results.append(("restore_latest()", restored,
                        "成功" if restored else "失败"))

        if restored and ch1_path.exists():
            restored_content = ch1_path.read_text(encoding="utf-8")
            match = (restored_content == ch1_backup) if ch1_backup else False
            results.append(("恢复后ch_01.md一致",
                            match,
                            "内容一致 [v]" if match else "内容不同 [FAIL]"))
        elif not restored:
            results.append(("恢复后ch_01.md", False, "restore_latest 失败"))

        # 验证控制台日志中有备份模式提示
        log_text = "\n".join(lines)
        has_backup_msg = ("文件快照备份" in log_text)
        results.append(("日志有备份模式提示",
                        has_backup_msg,
                        "有" if has_backup_msg else "无"))

    finally:
        # Step 5: 恢复 .git 目录
        if git_backup_path.exists():
            print("\n  -- Step 5: 恢复 .git 目录 --")
            try:
                if git_path.exists():
                    shutil.rmtree(str(git_path))
                shutil.move(str(git_backup_path), str(git_path))
                print("  [GIT] .git_disabled_backup -> .git 已恢复")
                results.append(("恢复Git目录", True, ".git 已恢复"))
            except Exception as e:
                print(f"  [ERROR] 恢复 .git 失败: {e}")
                print(f"  请手动重命名 {git_backup_path} -> {git_path}")
                results.append(("恢复Git目录", False, str(e)))

    print_results(results, "测试4: 无 Git 文件备份", elapsed)
    return results


# ============================================================================
# 主入口
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="阶段4：端到端验证测试脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
测试说明:
  --test 1   测试1: 3章 from_scratch (约25min, ~¥0.50)
  --test 2   测试2: 12章 from_scratch (约1.5h, ~¥1.50)
  --test 3   测试3: Resume 中断恢复 (约25min, ~¥0.50)
  --test 4   测试4: 无 Git 文件备份 (约25min, ~¥0.50)
  --all      按顺序全部执行 (约2h+, ~¥3.00)

推荐执行顺序: 4 → 3 → 1 → 2
  (4 先跑因为它涉及 .git 操作，需要确保能恢复)
        """,
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--test", type=int, choices=[1, 2, 3, 4],
                       help="指定运行哪个测试")
    group.add_argument("--all", action="store_true",
                       help="按顺序运行全部测试")
    args = parser.parse_args()

    if not args.test and not args.all:
        parser.print_help()
        sys.exit(0)

    # 验证 API Key 存在
    api_key, api_base = load_existing_api_key()
    if not api_key:
        print("[FATAL] 无法从 output/config.json 读取 api_key。")
        print("请先运行 novel_app.bat 完成 API 配置，"
              "或手动编辑 output/config.json。")
        sys.exit(1)
    print(f"  [OK] API: {api_base}, Key: {api_key[:10]}...")

    # 确保 output 目录存在
    OUTPUT.mkdir(parents=True, exist_ok=True)

    overall_start = datetime.now()
    all_results = {}

    tests_to_run = []
    if args.all:
        tests_to_run = [4, 3, 1, 2]  # 按推荐顺序
    else:
        tests_to_run = [args.test]

    for t in tests_to_run:
        try:
            if t == 1:
                all_results["test1"] = test_1_three_chapters()
            elif t == 2:
                all_results["test2"] = test_2_twelve_chapters()
            elif t == 3:
                all_results["test3"] = test_3_resume_recovery()
            elif t == 4:
                all_results["test4"] = test_4_file_backup_mode()
        except KeyboardInterrupt:
            print(f"\n  [WARN] 测试 {t} 被用户中断")
            all_results[f"test{t}"] = [("中断", False, "KeyboardInterrupt")]
            if not args.all:
                break
        except subprocess.TimeoutExpired:
            print(f"\n  [WARN] 测试 {t} 超时")
            all_results[f"test{t}"] = [("超时", False, "TimeoutExpired")]
        except Exception as e:
            print(f"\n  [FAIL] 测试 {t} 异常: {e}")
            traceback.print_exc()
            all_results[f"test{t}"] = [("异常", False, str(e))]

    # 汇总报告
    overall_elapsed = (datetime.now() - overall_start).total_seconds()
    print("\n" + "=" * 70)
    print(f"  [SUMMARY] 阶段4 测试汇总 ({overall_elapsed/60:.1f}min)")
    print("=" * 70)

    grand_pass = 0
    grand_fail = 0
    for test_name, res_list in all_results.items():
        p = sum(1 for _, ok, _ in res_list if ok)
        f = sum(1 for _, ok, _ in res_list if not ok)
        grand_pass += p
        grand_fail += f
        print(f"  {test_name}: {p}[OK] {f}[FAIL] ({p+f} 项)")

    print(f"  --------")
    print(f"  总计: {grand_pass}[OK] {grand_fail}[FAIL] ({grand_pass + grand_fail} 项)")
    print(f"  耗时: {overall_elapsed/60:.1f} 分钟")

    # 写入 JSON 报告
    report = {
        "timestamp": datetime.now().isoformat(),
        "model": MODEL,
        "total_passed": grand_pass,
        "total_failed": grand_fail,
        "total_checks": grand_pass + grand_fail,
        "elapsed_minutes": round(overall_elapsed / 60, 1),
        "tests": {},
    }
    for test_name, res_list in all_results.items():
        report["tests"][test_name] = [
            {"name": name, "ok": ok, "message": msg}
            for name, ok, msg in res_list
        ]

    report_path = ROOT / "phase4_report.json"
    json.dump(report, open(report_path, "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)
    print(f"\n  [FILE] 详细报告: {report_path}")


if __name__ == "__main__":
    main()
