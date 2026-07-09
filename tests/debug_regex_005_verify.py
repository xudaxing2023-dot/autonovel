#!/usr/bin/env python3
"""BUG-005 验证脚本：测试改进后的 _extract_volume_section() 解析逻辑。"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

# ── 导入改进后的函数 ──
sys.path.insert(0, str(Path(__file__).parent.parent))
from foundation.gen_outline import (
    _cn_to_arabic,
    _build_volume_patterns,
    _extract_volume_section,
)

# ── 1. 测试中文数字转换 ──
print("=== 1. 中文数字转换测试 ===")
cn_tests = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
    "十一": 11, "十二": 12, "十五": 15, "十九": 19,
    "二十": 20, "二十一": 21, "二十五": 25, "三十": 30,
    "九十九": 99, "一百": None,
}
all_pass = True
for cn, expected in cn_tests.items():
    result = _cn_to_arabic(cn)
    status = "✓" if result == expected else "✗"
    if result != expected:
        all_pass = False
    print(f"  {status} _cn_to_arabic('{cn}') = {result} (expected {expected})")
print(f"  {'全部通过' if all_pass else '存在失败'}")

# ── 2. 测试实际文件解析 ──
print("\n=== 2. 实际 outline_volume.md 解析测试 ===")
actual_path = Path("output/outline_volume.md")
actual_text = actual_path.read_text(encoding="utf-8-sig")

for vol_num in [1, 2]:
    section = _extract_volume_section(actual_text, vol_num)
    if section:
        print(f"  卷 {vol_num}: 提取成功 ({len(section)} chars)")
        print(f"    首行: {section.split(chr(10))[0][:80]}")
    else:
        print(f"  卷 {vol_num}: 未找到约束段（这在总卷数 > 实际提纲卷数时是预期的）")

# ── 3. 测试各种标题格式 ──
print("\n=== 3. 各种标题格式兼容性测试 ===")
test_cases = [
    # (文本, 卷号, 是否应该找到)
    ("### 卷 1：时空的裂缝\n内容...\n### 卷 2：真相浮现", 1, True),
    ("### 卷 1：时空的裂缝\n内容...\n### 卷 2：真相浮现", 2, True),
    ("### 一、卷 1 规划\n内容...\n### 二、卷 2 规划", 1, True),
    ("### 一、卷 1 规划\n内容...\n### 二、卷 2 规划", 2, True),
    ("### 二、卷 1 规划\n内容...\n### 三、伏笔清单", 1, True),
    ("## 卷 1 规划（3章，约12000字）\n内容...", 1, True),
    ("**卷 1：开端**\n内容...", 1, True),
    ("### 卷一：迷雾重重\n内容...\n### 卷二：真相浮现", 1, True),
    ("### 卷一：迷雾重重\n内容...\n### 卷二：真相浮现", 2, True),
    # 第N卷 模式
    ("### 第一卷：开端\n内容...\n### 第二卷：发展", 1, True),
    ("### 第一卷：开端\n内容...\n### 第二卷：发展", 2, True),
    ("### 第1卷：开端\n内容...\n### 第2卷：发展", 1, True),
    ("### 第1卷：开端\n内容...\n### 第2卷：发展", 2, True),
    ("### 三、卷 1 详细规划\n内容...", 1, True),
    # 不应该匹配的（卷号不匹配 / 边界测试）
    ("### 卷 1：时空的裂缝", 10, False),
    ("### 卷 10：开端", 1, False),  # \b 边界测试：卷10不应匹配卷1
    ("### 卷 2：真相浮现", 1, False),
    ("### 第一卷：开端", 2, False),  # 第一卷 ≠ 卷2
    ("### 第十卷：终结", 1, False),
]

all_ok = True
for text, vol_num, should_find in test_cases:
    result = _extract_volume_section(text, vol_num)
    found = bool(result)
    status = "✓" if found == should_find else "✗"
    if found != should_find:
        all_ok = False
        print(f"  {status} 卷{vol_num} should_find={should_find} found={found}")
        print(f"    文本: {text.split(chr(10))[0][:80]}")
    else:
        if found:
            first_line = result.split('\n')[0][:60]
            print(f"  {status} 卷{vol_num} found: {first_line}")

print(f"\n  {'全部通过' if all_ok else '存在失败'}")

# ── 4. 模式构建验证 ──
print("\n=== 4. 模式构建验证 ===")
for vol_num in [1, 2, 10]:
    patterns = _build_volume_patterns(vol_num)
    print(f"  卷 {vol_num}: {len(patterns)} 个模式")
    for i, (hp, np) in enumerate(patterns):
        print(f"    [{i+1}] heading: {hp!r}")
        print(f"        next:    {np!r}")

print("\n=== 验证完成 ===")
