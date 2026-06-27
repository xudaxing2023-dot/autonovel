#!/usr/bin/env python3
"""Fix gen_brief.py: replace sys.exit() with raise in build_auto_brief()"""
path = r"e:\2026代码文件夹\my novel\revision\gen_brief.py"
content = open(path, "r", encoding="utf-8").read()

# Fix 1: sys.exit at line 749
content = content.replace(
    '    if full_eval_path is None:\n        sys.exit("错误: eval_logs/ 中未找到 *_full.json")',
    '    if full_eval_path is None:\n        raise FileNotFoundError("eval_logs/ 中未找到 *_full.json — 请先执行 evaluate_full 或采样评估")'
)

# Fix 2: sys.exit at line 754
content = content.replace(
    '    if ch is None:\n        sys.exit("错误: 全文评估中未包含 \'weakest_chapter\' 字段")',
    '    if ch is None:\n        raise ValueError("全文评估中未包含 \'weakest_chapter\' 字段")'
)

open(path, "w", encoding="utf-8").write(content)

# Verify
verify = open(path, "r", encoding="utf-8").read()
if "raise FileNotFoundError" in verify and "raise ValueError" in verify:
    print("SUCCESS: both sys.exit() replaced with raise")
else:
    print("FAILED: one or both replacements not found")