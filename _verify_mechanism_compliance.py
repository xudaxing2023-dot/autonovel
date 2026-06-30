#!/usr/bin/env python3
"""
全流水线机制合规性诊断 —— 映射 PROGRAM_ZH.md 每条机制到自动化检查。

用法:
    python _verify_mechanism_compliance.py

- 零 API 调用，纯文件检查
- 检查 output/ 目录下的 state.json / config.json / results.tsv / 所有 .md 文件 / briefs/
- 参考 logs/debug.log 做运行轨迹验证
"""

import json
import re
import sys

# Windows 控制台 GBK 编码兼容
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
from datetime import datetime
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).parent
OUTPUT = ROOT / "output"
LOGS = ROOT / "logs"

PASS = "✅"
FAIL = "❌"
WARN = "⚠️"
INFO = "📋"

results: list[tuple[str, str, str]] = []  # (status, check_id, message)


def check(status: bool, check_id: str, msg: str):
    results.append((PASS if status else FAIL, check_id, msg))
    print(f"  {PASS if status else FAIL} {check_id}: {msg}")


def warn(msg: str):
    print(f"  {WARN} {msg}")


def info(msg: str):
    print(f"  {INFO} {msg}")


# ═══════════════════════════════════════════════════════════════
print("=" * 65)
print("  全流水线机制合规性诊断")
print(f"  基准: PROGRAM_ZH.md")
print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 65)

# ── 加载数据 ──
state = {}
config = {}
tsv_rows = []
canon_text = ""
voice_text = ""

try:
    state = json.loads((OUTPUT / "state.json").read_text(encoding="utf-8"))
    print(f"\n  state.json: phase={state.get('phase')}, "
          f"drafted={state.get('chapters_drafted')}/{state.get('chapters_total')}, "
          f"score={state.get('novel_score')}")
except Exception as e:
    print(f"  {FAIL} 无法加载 state.json: {e}")

try:
    config = json.loads((OUTPUT / "config.json").read_text(encoding="utf-8"))
except Exception:
    pass

try:
    rp = OUTPUT / "results.tsv"
    if rp.exists():
        for line in rp.read_text(encoding="utf-8").splitlines():
            if line.startswith("#") or line.startswith("commit"):
                continue
            parts = line.split("\t")
            if len(parts) >= 6:
                tsv_rows.append(tuple(parts[:6]))
except Exception:
    pass

try:
    canon_path = OUTPUT / "canon.md"
    if canon_path.exists():
        canon_text = canon_path.read_text(encoding="utf-8")
except Exception:
    pass

try:
    vp = OUTPUT / "voice.md"
    if vp.exists():
        voice_text = vp.read_text(encoding="utf-8")
except Exception:
    pass


# ═══════════════════════════════════════════════════════════════
# Phase 1: Foundation 基础构建
# ═══════════════════════════════════════════════════════════════
print(f"\n{'─' * 50}")
print("  PHASE 1: FOUNDATION (基础构建)")
print(f"{'─' * 50}")

# M1.1: 文件产出
foundation_files = {
    "world.md": 5000, "characters.md": 5000, "outline_volume.md": 5000,
    "outline.md": 1000, "canon.md": 5000, "voice.md": 1000,
}
for fn, minsize in foundation_files.items():
    fp = OUTPUT / fn
    ok = fp.exists() and fp.stat().st_size >= minsize
    check(ok, f"M1.1-{fn}", f"产出 {fn} (≥{minsize}B): {fp.stat().st_size if fp.exists() else 'MISSING'}B")

# M1.2: foundation_score 存在且非零
fs = state.get("foundation_score", 0)
check(fs > 0, "M1.2-score", f"foundation_score={fs} (应 > 0)")

# M1.3: canon 条目数
# 从 canon.md 计数
canon_world = len(re.findall(r"^### .*世界观", canon_text, re.M))
canon_char = len(re.findall(r"^### .*角色", canon_text, re.M))
canon_timeline = len(re.findall(r"^### .*时间线", canon_text, re.M))
canon_rules = len(re.findall(r"^### .*规则", canon_text, re.M))
canon_entries = len(re.findall(r"^— ", canon_text, re.MULTILINE))
canon_total = canon_entries if canon_entries > 0 else (canon_world + canon_char + canon_timeline + canon_rules)
info(f"canon.md: {canon_entries} 条 (— 开头), 节: 世界观{canon_world} 角色{canon_char} 时间线{canon_timeline} 规则{canon_rules}")

# M1.4: canon_entry_count in state — ★ P1 修复验证
cec = state.get("canon_entry_count", -1)
if cec > 0:
    check(True, "M1.4-canon-counter", f"state.canon_entry_count={cec} (已追踪) ✓")
else:
    check(cec > 0, "M1.4-canon-counter",
          f"state.canon_entry_count={cec} — Foundation 未写 counter（P1 Bug）")

# M1.5: results.tsv 中 foundation 阶段存在
found_rows = [r for r in tsv_rows if r[1] == "foundation"]
check(len(found_rows) > 0, "M1.5-tsv-foundation",
      f"results.tsv 中 foundation 记录: {len(found_rows)} 行")
keep_f = [r for r in found_rows if r[4] == "keep"]
discard_f = [r for r in found_rows if r[4] == "discard"]
info(f"  foundation keep={len(keep_f)}, discard={len(discard_f)}")

# M1.6: voice.md Part 2 存在（文风发现）
check("Part 2" in voice_text or "文风指纹" in voice_text or "语域" in voice_text,
      "M1.6-voice-part2", "voice.md 包含 Part 2 / 文风指纹")


# ═══════════════════════════════════════════════════════════════
# Phase 2: Drafting 草拟
# ═══════════════════════════════════════════════════════════════
print(f"\n{'─' * 50}")
print("  PHASE 2: DRAFTING (草拟)")
print(f"{'─' * 50}")

total_ch = state.get("chapters_total", config.get("total_chapters", 3))

# M2.1: 章节文件
chapters_dir = OUTPUT / "chapters"
for ch in range(1, total_ch + 1):
    cf = chapters_dir / f"ch_{ch:02d}.md"
    ok = cf.exists() and cf.stat().st_size >= 500
    size = cf.stat().st_size if cf.exists() else 0
    wc = 0
    if ok:
        wc = len(cf.read_text(encoding="utf-8").replace(" ", "").replace("\n", ""))
    check(ok, f"M2.1-ch{ch:02d}", f"ch_{ch:02d}.md: {size}B, {wc}字")

# M2.2: 章节数量匹配
cd = state.get("chapters_drafted", 0)
check(cd == total_ch, "M2.2-count",
      f"chapters_drafted={cd} == chapters_total={total_ch}")

# M2.3: results.tsv 每个章节有记录
for ch in range(1, total_ch + 1):
    ch_rows = [r for r in tsv_rows if r[1] == f"ch{ch:02d}"]
    keep_ch = [r for r in ch_rows if r[4] == "keep"]
    check(len(keep_ch) >= 1, f"M2.3-tsv-ch{ch:02d}",
          f"ch{ch:02d}: {len(keep_ch)} keep (共 {len(ch_rows)} 行)")

# M2.4: canon 增量 — 每章后 canon 应该增长
clu = state.get("canon_last_updated_ch", 0)
check(clu > 0, "M2.4-canon-growth",
      f"canon_last_updated_ch={clu} (应 ≥ 1，表示至少一章追加了正典)")

# M2.5: debts 记录
debts = state.get("debts", [])
info(f"debts: {len(debts)} 条 — {debts[:3] if debts else '(空)'}")

# M2.6: 章节字数合理性
for ch in range(1, total_ch + 1):
    cf = chapters_dir / f"ch_{ch:02d}.md"
    if cf.exists():
        wc = len(cf.read_text(encoding="utf-8").replace(" ", "").replace("\n", ""))
        check(wc >= 1000, f"M2.6-wc-ch{ch:02d}",
              f"ch_{ch:02d} 字数={wc} (应 ≥ 1000)")


# ═══════════════════════════════════════════════════════════════
# Phase 3: Revision 修订
# ═══════════════════════════════════════════════════════════════
print(f"\n{'─' * 50}")
print("  PHASE 3: REVISION (修订)")
print(f"{'─' * 50}")

# M3.1: 对抗性编辑产物
edit_logs = OUTPUT / "edit_logs"
adversarial_files = sorted(edit_logs.glob("ch*_cuts.json")) if edit_logs.exists() else []
check(len(adversarial_files) > 0, "M3.1-adversarial",
      f"对抗性编辑 cuts JSON: {len(adversarial_files)} 个文件")

# M3.2: 读者评审团
panel_file = edit_logs / "reader_panel.json"
check(panel_file.exists(), "M3.2-reader-panel",
      f"reader_panel.json: {'存在' if panel_file.exists() else '缺失'}")
if panel_file.exists():
    try:
        panel = json.loads(panel_file.read_text(encoding="utf-8"))
        readers = len(panel.get("readers", {}))
        disagreements = len(panel.get("disagreements", []))
        check(readers >= 2, "M3.2-readers",
              f"评审团读者数: {readers} (应 ≥ 2)")
        info(f"  disagreements: {disagreements} 条")
    except Exception:
        warn("reader_panel.json 解析失败")

# M3.3: 修订循环执行
rc = state.get("revision_cycle", 0)
check(rc >= 1, "M3.3-revision-cycles",
      f"revision_cycle={rc} (应 ≥ 1，表示至少执行了一轮修订)")

# M3.4: 修订评分记录
rev_keep = [r for r in tsv_rows if "rev" in r[1] and r[4] == "keep"]
rev_discard = [r for r in tsv_rows if "rev" in r[1] and r[4] == "discard"]
info(f"修订 keep={len(rev_keep)}, discard={len(rev_discard)} (回退={len(rev_discard)}次)")

# M3.5: 全文评估存在
full_evals = sorted((OUTPUT / "eval_logs").glob("*_full.json")) if (OUTPUT / "eval_logs").exists() else []
check(len(full_evals) > 0, "M3.5-full-eval",
      f"全文评估 JSON: {len(full_evals)} 个")

# M3.6: novel_score 更新
ns = state.get("novel_score", 0)
check(ns > 0, "M3.6-novel-score", f"novel_score={ns} (应 > 0)")

# M3.7: 平台期检测
# 从 results.tsv 看 revision-cycle-* 行判断
cycle_rows = [r for r in tsv_rows if "revision-cycle" in r[1]]
if len(cycle_rows) >= 2:
    scores = [float(r[2]) for r in cycle_rows if r[2].replace('.','').replace('-','').isdigit()]
    info(f"修订循环评分序列: {scores}")


# ═══════════════════════════════════════════════════════════════
# Phase 4: Export 导出
# ═══════════════════════════════════════════════════════════════
print(f"\n{'─' * 50}")
print("  PHASE 4: EXPORT (导出)")
print(f"{'─' * 50}")

# M4.1: manuscript.md
mp = OUTPUT / "manuscript.md"
check(mp.exists() and mp.stat().st_size >= 1000, "M4.1-manuscript",
      f"manuscript.md: {mp.stat().st_size if mp.exists() else 0}B")
if mp.exists():
    mtext = mp.read_text(encoding="utf-8")
    ch_count = sum(1 for _ in re.finditer(r"第\s*\d+\s*章", mtext))
    check(ch_count >= total_ch, "M4.1-chapters-in-manuscript",
          f"manuscript 包含 {ch_count}/{total_ch} 章标题")

# M4.2: arc_summary.md
ap = OUTPUT / "arc_summary.md"
check(ap.exists() and ap.stat().st_size >= 500, "M4.2-arc-summary",
      f"arc_summary.md: {ap.stat().st_size if ap.exists() else 0}B")

# M4.3: phase = complete
check(state.get("phase") == "complete", "M4.3-phase-complete",
      f"phase={state.get('phase')} (应为 complete)")

# M4.4: results.tsv export 阶段
export_rows = [r for r in tsv_rows if r[1] == "export"]
check(len(export_rows) > 0, "M4.4-tsv-export",
      f"results.tsv export 记录: {len(export_rows)} 行")


# ═══════════════════════════════════════════════════════════════
# 跨阶段机制检查
# ═══════════════════════════════════════════════════════════════
print(f"\n{'─' * 50}")
print("  跨阶段机制检查")
print(f"{'─' * 50}")

# X1: state.json 字段完整性
required_fields = [
    "phase", "foundation_score", "chapters_drafted", "chapters_total",
    "novel_score", "revision_cycle", "canon_entry_count",
    "total_volumes", "chapters_per_volume",
]
for field in required_fields:
    val = state.get(field, "MISSING")
    ok = val != "MISSING"
    check(ok, f"X1-{field}", f"state.{field}={val}")

# X2: results.tsv 列完整性
if tsv_rows:
    stages = set(r[1] for r in tsv_rows)
    expected = {"foundation"} | {f"ch{ch:02d}" for ch in range(1, total_ch + 1)} | {"revision-cycle-1", "export"}
    missing_stages = expected - stages
    # 部分阶段可能有不同命名
    info(f"results.tsv 阶段: {sorted(stages)}")
    if missing_stages:
        warn(f"可能缺少阶段: {missing_stages} (可能是命名差异)")

# X3: 零崩溃
crash_found = False
debug_log = LOGS / "debug.log"
if debug_log.exists():
    log_text = debug_log.read_text(encoding="utf-8")
    crash_count = log_text.count("[CRASH]")
    check(crash_count == 0, "X3-zero-crash", f"CRASH 次数: {crash_count}")

# X4: briefs 不为空占位符 ★
briefs_dir = OUTPUT / "briefs"
if briefs_dir.exists():
    brief_files = sorted(briefs_dir.glob("*.md"))
    empty_briefs = []
    placeholder_briefs = []
    for bf in brief_files:
        text = bf.read_text(encoding="utf-8")
        lines = [l for l in text.split("\n") if l.strip()]
        if len(lines) <= 5:
            placeholder_briefs.append(bf.name)
        elif "0 字可删除" in text and "0 处" in text and "修订项" in text:
            # cuts brief with no actual content
            rev_items = text.split("## 【修订项】")[-1].split("## ")[0] if "## 【修订项】" in text else ""
            if len(rev_items.strip()) < 20:
                empty_briefs.append(bf.name)

    check(len(placeholder_briefs) == 0, "X4-placeholder-briefs",
          f"占位符摘要 ({len(placeholder_briefs)} 个)" +
          (f": {placeholder_briefs[:3]}..." if placeholder_briefs else ""))
    if empty_briefs:
        warn(f"修订项为空的摘要 ({len(empty_briefs)} 个): {empty_briefs[:3]}...")

# X5: 章节文件非空
empty_chapters = []
for ch in range(1, total_ch + 1):
    cf = chapters_dir / f"ch_{ch:02d}.md"
    if cf.exists():
        text = cf.read_text(encoding="utf-8").strip()
        if len(text) < 100:
            empty_chapters.append(f"ch_{ch:02d}")
check(len(empty_chapters) == 0, "X5-empty-chapters",
      f"空/过短章节: {empty_chapters if empty_chapters else '无'}")


# ═══════════════════════════════════════════════════════════════
# 汇总
# ═══════════════════════════════════════════════════════════════
print(f"\n{'=' * 65}")
passed = sum(1 for s, _, _ in results if s == PASS)
failed = sum(1 for s, _, _ in results if s == FAIL)
total = len(results)
print(f"  结果: {passed}/{total} 通过, {failed} 失败")

if failed > 0:
    print(f"\n  失败项:")
    for s, cid, msg in results:
        if s == FAIL:
            print(f"    {FAIL} {cid}: {msg}")

print(f"{'=' * 65}")
print(f"\n  ⚠ 注意: 这是一个静态文件检查。")
print(f"  无法验证的机制 (需要运行时插桩):")
print(f"    - 上下文加载 (voice+world+characters+大纲)")
print(f"    - 评估→最弱维度→针对性修订的闭环")
print(f"    - 文风指纹实时检测")
print(f"    - git reset/回退是否正确执行")
print(f"  建议: 运行 _run_stage4_e2e1.py 并检查 debug.log 以获取完整运行时验证。")
sys.exit(0 if failed == 0 else 1)
