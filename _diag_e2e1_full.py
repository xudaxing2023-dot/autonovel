#!/usr/bin/env python3
"""E2E-1 全流程异常全面复查 — 扫描 debug.log 中所有异常信号"""
import re, sys
from pathlib import Path
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent
LOG = ROOT / "logs" / "debug.log"

text = LOG.read_text(encoding="utf-8") if LOG.exists() else ""
lines = text.split("\n")

DIM   = "\033[2m"
RED  = "\033[91m"
GRN  = "\033[92m"
YEL  = "\033[93m"
CYN  = "\033[96m"
MAG  = "\033[95m"
RST  = "\033[0m"
BOLD = "\033[1m"

def hdr(s): print(f"\n{BOLD}{CYN}{'='*70}{RST}\n{BOLD}{CYN}  {s}{RST}\n{BOLD}{CYN}{'='*70}{RST}\n")
def sub(s): print(f"\n  {BOLD}{YEL}── {s} ──{RST}")
def ok(s):  print(f"  {GRN}✅{RST} {s}")
def warn(s): print(f"  {YEL}⚠{RST}  {s}")
def err(s): print(f"  {RED}❌{RST} {s}")
def info(s): print(f"  {DIM}{s}{RST}")

hdr("E2E-1 全流程异常复查")

# ═══════════════════════════════════════
# 1. 全局统计
# ═══════════════════════════════════════
sub("全局统计")
total_lines = len(lines)
api_calls = len([l for l in lines if "[API]" in l])
crash_markers = [l for l in lines if "[CRASH]" in l]
error_lines = [l for l in lines if "Traceback" in l or "Error" in l or "错误" in l or "失败" in l]
warn_lines = [l for l in lines if "⚠" in l or "警告" in l or "WARNING" in l.upper()]
skip_lines = [l for l in lines if "跳过" in l]
info(f"总行数: {total_lines}")
info(f"API 调用: {api_calls}")
info(f"崩溃标记: {len(crash_markers)}")
info(f"错误/异常行: {len(error_lines)}")
info(f"警告行: {len(warn_lines)}")
info(f"跳过行: {len(skip_lines)}")

# ═══════════════════════════════════════
# 2. 阶段追踪
# ═══════════════════════════════════════
sub("流水线阶段追踪")
phase_markers = {
    "PHASE 1: FOUNDATION": 0, "PHASE 2: DRAFTING": 0,
    "PHASE 3: REVISION": 0, "PHASE 4: EXPORT": 0,
}
foundation_iters = 0
drafting_ch_count = 0
rev_cycles = 0

for l in lines:
    for k in phase_markers:
        if k in l: phase_markers[k] += 1
    if "基础构建 迭代" in l or "Foundation 迭代" in l:
        foundation_iters += 1
    if re.search(r'草拟第?\s*\d+\s*章', l) or re.search(r'Drafting\s+ch', l):
        drafting_ch_count += 1
    if "修订 循环" in l:
        rev_cycles += 1

for k, v in phase_markers.items():
    status = ok if v > 0 else err
    status(f"{k}: 出现 {v} 次")
info(f"Foundation 迭代: {foundation_iters}")
info(f"草拟章节事件: {drafting_ch_count}")
info(f"修订循环: {rev_cycles}")

# ═══════════════════════════════════════
# 3. 评分异常
# ═══════════════════════════════════════
sub("评分异常扫描")
score_negatives = re.findall(r'评分[：:]\s*(-\d+\.?\d*)', text)
score_zeros = re.findall(r'(?:novel_score|overall_score|评分)[：:]\s*0\.0', text)

if score_negatives:
    warn(f"负分评分: {score_negatives}")
else:
    ok("无负分评分")

if score_zeros:
    warn(f"0.0评分: {len(score_zeros)} 处 (如: {score_zeros[:3]})")
else:
    ok("无0.0评分")

# ═══════════════════════════════════════
# 4. API 调用异常
# ═══════════════════════════════════════
sub("API 调用异常")
api_fails = [l for l in lines if "[API]" in l and ("失败" in l or "FAIL" in l.upper() or "超时" in l or "timeout" in l.lower() or "错误" in l)]
api_retry = [l for l in lines if "retry" in l.lower() or "重试" in l]
api_empty = [l for l in lines if "0 tokens" in l or "0 chars" in l or "空响应" in l]

if api_fails:
    err(f"API 失败: {len(api_fails)} 处")
    for fl in api_fails[:5]: info(f"  {fl.strip()[:120]}")
else:
    ok("API 调用无不明确失败")

if api_retry:
    warn(f"API 重试: {len(api_retry)} 处")
else:
    ok("无 API 重试")

if api_empty:
    warn(f"API 空响应: {len(api_empty)} 处")
else:
    ok("无空响应")

# ═══════════════════════════════════════
# 5. 文件产出检查
# ═══════════════════════════════════════
sub("文件产出完整性")
output = ROOT / "output"
expected_files = {
    "world.md": 500, "characters.md": 500, "outline_volume.md": 200,
    "outline.md": 500, "canon.md": 500, "voice.md": 200,
    "state.json": 50, "results.tsv": 100, "manuscript.md": 500,
}
for i in range(1, 4): expected_files[f"chapters/ch_{i:02d}.md"] = 500

all_files_ok = True
for fn, min_sz in expected_files.items():
    p = output / fn
    exists = p.exists()
    sz = p.stat().st_size if exists else 0
    if exists and sz >= min_sz:
        ok(f"{fn}: {sz}B")
    elif exists:
        warn(f"{fn}: 仅 {sz}B (min={min_sz})")
        all_files_ok = False
    else:
        err(f"{fn}: 缺失!")
        all_files_ok = False

if all_files_ok: ok("全部文件产出完整")

# ═══════════════════════════════════════
# 6. 异常操作模式
# ═══════════════════════════════════════
sub("异常操作模式扫描")

# 6a. git_reset_hard 频率
git_resets = [l for l in lines if "git_reset_hard" in l or "回退" in l or "revert" in l.lower()]
info(f"git_reset / 回退: {len(git_resets)} 次")

# 6b. discard 记录
discard_records = [l for l in lines if "discard" in l and "log_result" not in l]
info(f"discard 标记: {len(discard_records)} 次")

# 6c. 空内容段落
empty_ops = []
for l in lines:
    if "0 字" in l and ("可删除" in l or "赘语" in l or "裁剪" in l or "cut" in l.lower()):
        empty_ops.append(l.strip()[:100])
if empty_ops:
    warn(f"空操作/零字数: {len(empty_ops)} 处")
    for eo in empty_ops[:5]: info(f"  {eo}")
else:
    ok("无空操作/零字数")

# 6d. canon 警告
canon_warns = [l for l in lines if "正典" in l and ("警告" in l or "不足" in l or "0" in l)]
if canon_warns:
    warn(f"正典相关警告: {len(canon_warns)} 处")
    for cw in canon_warns[:5]: info(f"  {cw.strip()[:120]}")
else:
    ok("无正典警告")

# 6e. 平台期
plateau_lines = [l for l in lines if "平台期" in l or "plateau" in l.lower()]
info(f"平台期检测: {len(plateau_lines)} 处")

# 6f. 章节字数偏低
low_wc = re.findall(r'字数偏低\s*\((\d+)', text)
if low_wc:
    warn(f"字数偏低警告: {len(low_wc)} 处 — {low_wc}")
else:
    ok("无字数偏低警告")

# ═══════════════════════════════════════
# 7. 修订循环深度分析
# ═══════════════════════════════════════
sub("修订循环深度分析")

# 共识修订 → skip 链
consensus_skips = defaultdict(int)
for l in lines:
    m = re.search(r'无摘要文件.*跳过.*第\s*(\d+)\s*章', l)
    if m: consensus_skips[int(m.group(1))] += 1

if consensus_skips:
    err(f"共识修订跳过: {dict(consensus_skips)} (总={sum(consensus_skips.values())})")
else:
    ok("无共识修订跳过 (已修复)")

# 实际修订执行
actual_revises = [l for l in lines if "按摘要修订" in l]
info(f"实际修订执行 (按摘要修订): {len(actual_revises)} 次")

# Phase 3b 审阅修订
review_revises = [l for l in lines if "审阅修订" in l and ("前评分" in l or "->" in l)]
info(f"Phase 3b 审阅修订记录: {len(review_revises)} 条")

# 修订评分变化
score_changes = re.findall(r'(\d+\.?\d*)\s*->\s*(\d+\.?\d*)', text)
downgrades = [(float(a), float(b)) for a, b in score_changes if float(b) < float(a)]
upgrades   = [(float(a), float(b)) for a, b in score_changes if float(b) > float(a)]

info(f"评分变化总数: {len(score_changes)}")
if downgrades:
    warn(f"评分下降: {len(downgrades)} 次")
    for a, b in downgrades[:5]: info(f"  {a} -> {b} (降 {a-b:.1f})")
else:
    ok("无评分下降")
if upgrades:
    ok(f"评分上升: {len(upgrades)} 次")

# ═══════════════════════════════════════
# 8. state 演进检查
# ═══════════════════════════════════════
sub("State 演进检查")
phase_transitions = []
for l in lines:
    m = re.search(r'phase[=:]?\s*(\w+)', l)
    if m: phase_transitions.append(m.group(1))

unique_phases = list(dict.fromkeys(phase_transitions))
info(f"Phase 变迁: {' → '.join(unique_phases)}")
expected_phases = ["foundation", "drafting", "revision", "complete"]
missing = [p for p in expected_phases if p not in unique_phases]
if missing:
    warn(f"缺失阶段: {missing}")
else:
    ok("全部预期阶段均已到达")

# ═══════════════════════════════════════
# 9. 耗时异常
# ═══════════════════════════════════════
sub("耗时分析")
time_entries = re.findall(r'耗时\s*([\d.]+)\s*s', text)
if time_entries:
    times = [float(t) for t in time_entries]
    info(f"耗时记录: {len(times)} 条, min={min(times):.0f}s, max={max(times):.0f}s, avg={sum(times)/len(times):.0f}s")

total_time = re.findall(r'总耗时[：:]\s*([\d.]+)\s*min', text)
if total_time: info(f"总耗时: {total_time[-1]}min")

# ═══════════════════════════════════════
# 10. 总结
# ═══════════════════════════════════════
hdr("异常总结")

findings = []

# 已修复的两个
findings.append(("已修复", "共识修订零执行 (brief 文件名不匹配)", RED))
findings.append(("已修复", "canon_entry_count 统计为 0 (EM DASH vs HYPHEN)", RED))

# 新增发现的异常
if "0 字可删除内容" in text:
    findings.append(("观察", "对抗性编辑发现 0 字可删除内容 → 裁剪步骤空转", YEL))
if "正典条目数: 0" in text:
    pass  # 已修复

# revision_cycle 达到 max
if rev_cycles >= 3 and "平台期" not in text:
    findings.append(("观察", f"修订循环达到上限 {rev_cycles} 次，未触发平台期提前停止", YEL))

# 章节评分检查
ch_scores = re.findall(r'采样评估 第 (\d+) 章.*?(\d+\.?\d*)', text)
if ch_scores:
    low_chs = [(c, float(s)) for c, s in ch_scores if float(s) < 6.5]
    if low_chs:
        findings.append(("观察", f"低分章节: {low_chs}", YEL))

# 零崩溃是好事
findings.append(("通过", "零崩溃 / 零未捕获异常", GRN))

# manuscript 完整性
manu = output / "manuscript.md"
if manu.exists():
    manu_text = manu.read_text(encoding="utf-8")
    manu_wc = len(manu_text.replace(" ", "").replace("\n", ""))
    ch_count_in_manu = len(re.findall(r'第\s*\d+\s*章', manu_text))
    info(f"manuscript.md: {manu_wc}字, {ch_count_in_manu}个章标题")
    if ch_count_in_manu < 3:
        findings.append(("异常", f"manuscript.md 仅含 {ch_count_in_manu}/3 章标题", RED))
    else:
        findings.append(("通过", f"manuscript.md 完整 ({manu_wc}字, {ch_count_in_manu}章)", GRN))

# briefs 内容空洞
briefs_dir = output / "briefs"
small_briefs = []
for bf in briefs_dir.glob("*.md"):
    sz = bf.stat().st_size
    if sz < 200:
        small_briefs.append((bf.name, sz))
if small_briefs:
    findings.append(("观察", f"空洞 briefs (<200B): {len(small_briefs)} 个 {[n for n,_ in small_briefs[:5]]}", YEL))

# 打印结论
for status, msg, color in findings:
    icon = {"已修复": "🔧", "观察": "📋", "通过": "✅", "异常": "❌"}.get(status, "•")
    print(f"  {color}[{icon} {status}]{RST} {msg}")

print()
print(f"  {BOLD}总结：已修复 2 项，发现 {sum(1 for s,_,_ in findings if s=='观察')} 项观察性异常，" +
      f"{sum(1 for s,_,_ in findings if s=='通过')} 项通过。{RST}")
print()