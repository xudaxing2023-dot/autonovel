#!/usr/bin/env python3
"""E2E-1 深度诊断 — 低分章节 / 空洞 briefs / 负分评分"""
import re, sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).parent

# ── 1. 采样评估分数 ──
print("═══ 采样评估分数 ═══")
log_text = (ROOT / "logs" / "debug.log").read_text(encoding="utf-8")
for m in re.finditer(r'采样评估\s+第\s+(\d+)\s+章.*?([\d.]+)', log_text):
    print(f"  第{m.group(1)}章: {m.group(2)}")

# ── 2. 空洞 briefs ──
print("\n═══ briefs/ 内容检查 ═══")
briefs_dir = ROOT / "output" / "briefs"
for bf in sorted(briefs_dir.glob("*.md")):
    text = bf.read_text(encoding="utf-8")
    sz = len(text)
    first_line = text.split("\n")[0].strip()
    tag = "EMPTY" if sz < 200 else "OK"
    print(f"  [{tag}] {bf.name:35s} {sz:>5d}B | {first_line[:80]}")

# ── 3. 负分评分 ──
print("\n═══ 负分评分上下文 ═══")
lines = log_text.split("\n")
for i, l in enumerate(lines):
    if "-1.0" in l and ("评分" in l or "score" in l.lower()):
        ctx_start = max(0, i-1)
        ctx_end = min(len(lines), i+2)
        print(f"  L{i+1}: {l.strip()[:120]}")
        for j in range(ctx_start, ctx_end):
            if j != i:
                print(f"    L{j+1}: {lines[j].strip()[:120]}")

# ── 4. results.tsv 中的 discard 详情 ──
print("\n═══ results.tsv discard 行 ═══")
tsv_path = ROOT / "output" / "results.tsv"
if tsv_path.exists():
    for line in tsv_path.read_text(encoding="utf-8").split("\n"):
        if "discard" in line:
            parts = line.split("\t")
            if len(parts) >= 6:
                print(f"  stage={parts[1]} score={parts[2]} reason={parts[5][:100]}")

# ── 5. Phase 3b review_rnd briefs 内容 ──
print("\n═══ Phase 3b review_rnd briefs 深度内容 ═══")
for bf in sorted(briefs_dir.glob("ch*_review_rnd*.md")):
    text = bf.read_text(encoding="utf-8")
    print(f"\n  --- {bf.name} ({len(text)}B) ---")
    # 打印前8行或全部
    lines_b = text.split("\n")
    for lb in lines_b[:8]:
        print(f"    {lb}")

# ── 6. Foundation 迭代次数确认 ──
print("\n═══ Foundation 迭代详情 ═══")
for m in re.finditer(r'(基础构建|Foundation).*迭代\s*(\d+)', log_text):
    print(f"  {m.group(0)}")
for m in re.finditer(r'基础构建评分[：:]\s*([\d.]+)', log_text):
    print(f"  Foundation评分: {m.group(1)}")

# ── 7. manuscript 章标题计数 ──
print("\n═══ manuscript.md 章标题 ═══")
manu = ROOT / "output" / "manuscript.md"
if manu.exists():
    mt = manu.read_text(encoding="utf-8")
    ch_titles = re.findall(r'第\s*\d+\s*章[^\n]*', mt)
    print(f"  章标题数: {len(ch_titles)}")
    for t in ch_titles:
        print(f"    {t.strip()[:60]}")