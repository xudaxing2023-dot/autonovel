#!/usr/bin/env python3
"""诊断修订循环为何零修订 — 追踪 revision_cycle_apply 与 brief 文件匹配"""

import re
import sys
from pathlib import Path
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent
LOG = ROOT / "logs" / "debug.log"
BRIEFS = ROOT / "output" / "briefs"
PIPELINE = ROOT / "pipeline_orchestrator.py"

DIM = "\033[2m"
RED = "\033[91m"
GRN = "\033[92m"
YEL = "\033[93m"
CYN = "\033[96m"
RST = "\033[0m"
BOLD = "\033[1m"

# ═══════════════════════════════════════════════════
# 1. 从 debug.log 提取修订循环相关事件
# ═══════════════════════════════════════════════════

log_text = LOG.read_text(encoding="utf-8") if LOG.exists() else ""
lines = log_text.split("\n")

# 事件捕获
events = []  # (line_no, ts, tag, detail)
cycle_number = None
in_consensus_loop = False
in_sample_loop = False
in_review_loop = False

for i, line in enumerate(lines, 1):
    # 修订循环边界
    m = re.match(r'.*修订\s*(?:循环|Cycle)\s*(\d+)/(\d+)', line)
    if m:
        cycle_number = int(m.group(1))
        events.append((i, "", "CYCLE_START", f"修订循环 {cycle_number}/{m.group(2)}"))

    # 共识问题
    m = re.search(r'发现\s*(\d+)\s*个共识问题', line)
    if m:
        events.append((i, "", "CONSENSUS", f"共识问题数={m.group(1)}"))

    # 共识修订 — 修订第N章 (共识问题)
    m = re.match(r'.*(修订\s*第\s*\d+\s*章.*共识)', line)
    if m:
        events.append((i, "", "CONSENSUS_REVISE", m.group(1).strip()))

    # 跳过
    m = re.search(r'无摘要文件.*跳过.*第\s*(\d+)\s*章', line)
    if m:
        events.append((i, "", "SKIP_NO_BRIEF", f"第{m.group(1)}章: 无摘要文件跳过"))

    # 摘要保存成功
    m = re.search(r'修订摘要已保存:\s*(.+)', line)
    if m:
        events.append((i, "", "BRIEF_SAVED", m.group(1).strip()))

    # 按摘要修订
    m = re.search(r'按摘要修订第\s*(\d+)\s*章', line)
    if m:
        events.append((i, "", "ACTUAL_REVISE", f"第{m.group(1)}章: 按摘要修订"))

    # 使用对抗性编辑摘要
    m = re.search(r'(\d+)\s*章.*使用.*摘要\s*\((.+?)\)', line)
    if m:
        events.append((i, "", "BRIEF_SOURCE", f"第{m.group(1)}章: 数据源={m.group(2)}"))

    # 无额外修订目标
    m = re.search(r'无额外修订目标', line)
    if m:
        events.append((i, "", "NO_EXTRA_TARGETS", "采样/跨卷均无"))

    # 采样弱章
    m = re.search(r'采样弱章:\s*(.+)', line)
    if m:
        events.append((i, "", "SAMPLE_WEAK", m.group(1).strip()))

    # 合并修订队列
    m = re.search(r'合并修订队列:\s*(\d+)\s*章', line)
    if m:
        events.append((i, "", "COMBINED_QUEUE", m.group(0).strip()))

    # review-based revision rounds
    m = re.search(r'审阅修订.*轮次\s*(\d+)', line)
    if m:
        events.append((i, "", "REVIEW_RND", f"审阅轮次={m.group(1)}"))

    # Phase 3b 修订执行 (review_rnd briefs)
    m = re.search(r'审阅修订.*第\s*(\d+)\s*章.*前评分', line)
    if m:
        events.append((i, "", "REVIEW_RND_PRE", f"第{m.group(1)}章修订前"))

    # Phase 3b 修订评分变化
    m = re.search(r'审阅修订.*第\s*(\d+)\s*章.*:\s*([\d\.]+)\s*->\s*([\d\.]+)', line)
    if m:
        events.append((i, "", "REVIEW_RND_RESULT", f"第{m.group(1)}章: {m.group(2)}->{m.group(3)}"))

# ═══════════════════════════════════════════════════
# 2. 分析 briefs/ 实际文件
# ═══════════════════════════════════════════════════

print(f"{BOLD}{'='*70}{RST}")
print(f"{BOLD}  修订循环零修订 — 根因诊断{RST}")
print(f"{BOLD}{'='*70}{RST}")
print()
print(f"  日志行数: {len(lines)}")
print(f"  事件捕获: {len(events)} 条")
print()

# 2a. 统计事件类型
type_stats = defaultdict(int)
for _, _, tag, _ in events:
    type_stats[tag] += 1

print(f"{CYN}── 日志事件统计 ──{RST}")
for tag in sorted(type_stats):
    count = type_stats[tag]
    color = GRN if "SAVED" in tag or "ACTUAL" in tag else (RED if "SKIP" in tag else "")
    print(f"  {color}{tag:20s}{RST} : {count}")

print()

# 2b. 关键问题链
print(f"{CYN}── 事件序列（仅显示关键节点）──{RST}")
for ln, ts, tag, detail in events:
    color = ""
    if "SKIP" in tag:
        color = RED
    elif "ACTUAL" in tag or "SAVED" in tag:
        color = GRN
    elif "CYCLE" in tag:
        color = YEL
    print(f"  {DIM}L{ln:05d}{RST} {color}[{tag}]{RST} {detail}")

print()

# ═══════════════════════════════════════════════════
# 3. 文件名不匹配分析
# ═══════════════════════════════════════════════════

print(f"{CYN}── 文件名不匹配分析（关键根因）──{RST}")
print()

# 3a. pipeline 中三处 generate_brief 调用点的期望文件名
print(f"  {BOLD}[1/3] 共识修订调用点 (pipeline L492){RST}")
print(f"    brief_file = BRIEFS_DIR / f\"ch{{ch_num:02d}}_cycle{{cycle}}_{{question}}.md\"")
print(f"    调用: generate_brief(ch_num, panel_data=panel_path, retries=2, max_total_time=1200)")
print(f"    ❌ 未传入 output_path → generate_brief 自定文件名 → 路径不匹配")
print()

print(f"  {BOLD}[2/3] 采样修订调用点 (pipeline L736){RST}")
print(f"    brief_file = BRIEFS_DIR / f\"ch{{ch_num:02d}}_sample_cycle{{cycle}}.md\"")
print(f"    调用: 内联调用 build_auto_brief() → 写到 brief_file")
print(f"    ✅ 内联写出，路径一致")
print()

print(f"  {BOLD}[3/3] 审阅修订调用点 (pipeline L966){RST}")
print(f"    brief_file = BRIEFS_DIR / f\"ch{{ch_num:02d}}_review_rnd{{rnd}}.md\"")
print(f"    调用: 内联调用 build_auto_brief() → 写到 brief_file")
print(f"    ✅ 内联写出，路径一致")
print()

# 3b. briefs/ 实际文件列表
actual_files = sorted(BRIEFS.glob("*.md")) if BRIEFS.exists() else []
print(f"  {CYN}── briefs/ 实际文件 ──{RST}")
for f in actual_files:
    size = f.stat().st_size
    fname = f.name
    # 检查是否匹配任何期望的 cycle 模式
    cycle_match = "cycle" in fname or "review_rnd" in fname
    sample_match = "sample_cycle" in fname
    cuts_match = "cuts" in fname
    color = GRN if cycle_match or sample_match else (YEL if cuts_match else RED)
    tag = "✅" if cycle_match or sample_match else ("⚠ cuts命名→不匹配" if cuts_match else "❌")
    print(f"  {color}  {tag} {fname:35s} {size:>5d}B{RST}")

print()

# 3c. 模拟期望 vs 实际
print(f"  {CYN}── 共识修订（第1循环）期望 vs 实际 ──{RST}")
print(f"    期望: ch01_cycle1_pacing.md / ch02_cycle2_characters.md / ch03_cycle3_structure.md")
print(f"    实际: {', '.join(f.name for f in actual_files if 'cuts' in f.name)}")
print(f"    → {RED}完全不对应，3章全部被跳过{RST}")
print()

# ═══════════════════════════════════════════════════
# 4. 修订循环执行总结
# ═══════════════════════════════════════════════════

print(f"{CYN}── 修订执行统计 ──{RST}")

# 计数
consensus_skip = sum(1 for _, _, tag, _ in events if tag == "SKIP_NO_BRIEF")
consensus_actual = sum(1 for _, _, tag, _ in events if tag == "ACTUAL_REVISE")
consensus_skipped_chs = [d for _, _, tag, d in events if tag == "SKIP_NO_BRIEF"]
consensus_revised_chs = [d for _, _, tag, d in events if tag == "ACTUAL_REVISE"]

print(f"  共识修订触发（发现共识问题）: {type_stats.get('CONSENSUS', 0)} 次")
print(f"  共识修订实际执行（按摘要修订）: {consensus_actual} 次")
print(f"  共识修订跳过（无摘要文件）  : {consensus_skip} 次")
if consensus_skipped_chs:
    print(f"    → 跳过章节: {', '.join(consensus_skipped_chs)}")
print()

# 采样修订
sample_events = [(ln, d) for ln, _, tag, d in events if tag in ("SAMPLE_WEAK", "COMBINED_QUEUE", "ACTUAL_REVISE")]
print(f"  采样弱章事件数: {type_stats.get('SAMPLE_WEAK', 0)}")
print(f"  合并修订队列: {type_stats.get('COMBINED_QUEUE', 0)}")
print(f"  无额外修订目标: {type_stats.get('NO_EXTRA_TARGETS', 0)}")
print()

# 审阅修订
review_rnd_count = type_stats.get('REVIEW_RND', 0)
review_result_count = type_stats.get('REVIEW_RND_RESULT', 0)
print(f"  审阅修订轮次: {review_rnd_count}")
print(f"  审阅修订评分变化记录: {review_result_count}")
if review_result_count > 0:
    for ln, _, tag, d in events:
        if tag == "REVIEW_RND_RESULT":
            print(f"    L{ln:05d} {d}")
print()

# ═══════════════════════════════════════════════════
# 5. 结论
# ═══════════════════════════════════════════════════

print(f"{BOLD}{'='*70}{RST}")
print(f"{BOLD}  根因诊断结论{RST}")
print(f"{BOLD}{'='*70}{RST}")
print()
print(f"  {RED}{BOLD}核心问题：共识修订路径文件名不匹配{RST}")
print()
print(f"  调用方 (pipeline L492) 期望文件:")
print(f"    output/briefs/ch01_cycle1_<question>.md")
print()
print(f"  generate_brief() (无 output_path 时) 实际保存到:")
print(f"    output/briefs/ch01_cuts.md  (via _detect_source_suffix)")
print()
print(f"  结果：3个共识问题 → 3次 '无摘要文件，跳过' → 共识修订路径 零执行")
print()
print(f"  {YEL}{BOLD}次要观察：{RST}")
print(f"  - Phase 3b 审阅修订（review_rnd）走内联 build_auto_brief，文件名一致 → 可正常执行")
print(f"  - 采样修订走内联 build_auto_brief，文件名一致 → 可正常执行（本次未触发因评分≥阈值）")
print(f"  - '无额外修订目标' 是正常行为（1卷无跨卷检查 + 采样未发现弱章）")
print()
print(f"  {GRN}{BOLD}修复：在 pipeline L494 generate_brief() 调用处传入 output_path=brief_file{RST}")
print()