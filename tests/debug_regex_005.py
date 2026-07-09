#!/usr/bin/env python3
"""BUG-005 诊断脚本：验证 _extract_volume_section() 的 regex 匹配逻辑。"""
import re
import sys
from pathlib import Path

# Force UTF-8 output
sys.stdout.reconfigure(encoding='utf-8')

# ── 1. 读取实际的 outline_volume.md ──
actual_path = Path("output/outline_volume.md")
actual_text = actual_path.read_text(encoding="utf-8-sig") if actual_path.exists() else ""
print(f"=== outline_volume.md ({len(actual_text)} chars) ===")
# Print raw bytes of interesting lines
for i, line in enumerate(actual_text.split('\n'), 1):
    if '卷' in line:
        print(f"Line {i}: {line.rstrip()!r}")
        print(f"  bytes: {line.rstrip().encode('utf-8')!r}")

print()

# ── 2. 测试原始 regex ──
volume_num = 1

patterns = [
    (rf'^#{{2,3}}\s*[^\n]*?卷\s*{volume_num}[^\n]*$', r'^#{2,3}\s', "标题格式"),
    (rf'^\*\*[^*\n]*?卷\s*{volume_num}[^*\n]*\*\*\s*$', r'^(\*\*|#{2,3})\s', "粗体格式"),
    (rf'^[^\n]*卷\s*{volume_num}[^\n]*$', r'^(\*\*|#{2,3}|##)\s', "任意行格式"),
]

print("=== 原始 regex 测试 ===")
for heading_pat, next_pat, desc in patterns:
    match = re.search(heading_pat, actual_text, re.MULTILINE)
    status = "MATCH" if match else "NO MATCH"
    print(f"[{desc}] {status}")
    if match:
        print(f"  matched: {match.group()!r}")
        start = match.start()
        remaining = actual_text[match.end():]
        next_marker = re.search(next_pat, remaining, re.MULTILINE)
        if next_marker:
            end = match.end() + next_marker.start()
            extracted = actual_text[start:end].strip()
            print(f"  extracted: {len(extracted)} chars, starts with: {extracted[:80]!r}")
        else:
            extracted = actual_text[start:].strip()
            print(f"  extracted (to EOF): {len(extracted)} chars")
    else:
        # Debug individual lines
        for line in actual_text.split('\n'):
            line_clean = line.rstrip('\r')
            if '卷' in line_clean:
                m = re.search(heading_pat, line_clean, re.MULTILINE)
                if m:
                    print(f"  BUT matches line: {line_clean!r}")
                else:
                    # Try with $ removed
                    m2 = re.search(heading_pat.replace('$', ''), line_clean)
                    if m2:
                        print(f"  matches without $: {line_clean!r}")
                        print(f"  $ prevents match, line ends with: {line_clean[-5:].encode('utf-8')!r}")

print()

# ── 3. 测试改进后的 regex ──
print("=== 改进 regex 测试 ===")
improved_patterns = [
    (rf'^#{{2,3}}\s*[^\n]*?卷\s*{volume_num}\b[^\n]*$', r'^#{2,3}\s', "标题+\\b"),
    (rf'^\*\*[^*\n]*?卷\s*{volume_num}\b[^*\n]*\*\*\s*$', r'^(\*\*|#{2,3})\s', "粗体+\\b"),
    (rf'^[^\n]*?卷\s*{volume_num}\b[^\n]*$', r'^(\*\*|#{2,3}|##)\s', "任意行+\\b"),
]

for heading_pat, next_pat, desc in improved_patterns:
    match = re.search(heading_pat, actual_text, re.MULTILINE)
    status = "MATCH" if match else "NO MATCH"
    print(f"[{desc}] {status}: {heading_pat!r}")
    if match:
        print(f"  matched: {match.group()!r}")

print()

# ── 4. 测试各种卷标题格式 ──
print("=== 各种卷标题格式兼容性测试 ===")
test_lines = [
    "### 卷 1：时空的裂缝",
    "### 一、卷 1 规划",  
    "### 二、卷 1 规划",
    "## 卷 1 规划（3章，约12000字）",
    "**卷 1：开端**",
    "### 卷 2：真相浮现",
    "## 卷 2 规划（3章，约12000字）",
    "### 三、卷 1 详细规划",
    "## 卷一：迷雾重重",
    "### 第一卷：开端",
]

for vol_num in [1, 2]:
    print(f"\n--- 卷 {vol_num} ---")
    for line in test_lines:
        m = re.search(rf'^#{{2,3}}\s*[^\n]*?卷\s*{vol_num}\b[^\n]*$', line)
        heading = "HEADING" if m else "-"
        m2 = re.search(rf'^\*\*[^*\n]*?卷\s*{vol_num}\b[^*\n]*\*\*\s*$', line)
        bold = "BOLD" if m2 else "-"
        has_vol = "VOL" if re.search(rf'卷\s*{vol_num}\b', line) else "-"
        print(f"  {heading:8s} {bold:6s} {has_vol:5s} | {line!r}")

print("\n=== 诊断完成 ===")
