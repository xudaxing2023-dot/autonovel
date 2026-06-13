#!/usr/bin/env python3
"""验证脚本 — 阶段 1: 静态检查"""
import py_compile
import os
import sys

root = r'e:\my novel'
# 排除不需要编译的旧文件
exclude = {
    'gen_audiobook.py', 'gen_art.py', 'gen_art_directions.py',
    'gen_audiobook_script.py', 'gen_cover_composite.py',
    'gen_cover_print.py', 'seed.py', 'voice_fingerprint.py',
}

ok = 0
fail = 0
results = []

for dirpath, dirnames, filenames in os.walk(root):
    for fn in filenames:
        if fn.endswith('.py') and fn not in exclude:
            fp = os.path.join(dirpath, fn)
            rel = os.path.relpath(fp, root)
            try:
                py_compile.compile(fp, doraise=True)
                results.append(f"OK  {rel}")
                ok += 1
            except py_compile.PyCompileError as e:
                results.append(f"FAIL {rel} — {e}")
                fail += 1

print("\n".join(results))
print(f"\n=== 语法检查: {ok} OK, {fail} FAIL ===")

if fail:
    sys.exit(1)