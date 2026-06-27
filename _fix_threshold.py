#!/usr/bin/env python3
"""修复 pipeline_orchestrator.py: 添加缺失的 threshold 变量"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

path = r"e:\2026代码文件夹\my novel\pipeline_orchestrator.py"
content = open(path, "r", encoding="utf-8").read()

old = (
    'plateau_delta = cfg.get("plateau_delta", PLATEAU_DELTA) if cfg.loaded else PLATEAU_DELTA\n'
    '    max_tokens = cfg.max_tokens_per_call if cfg.loaded else 16000\n'
    '    total = get_total_chapters(state)'
)
new = (
    'plateau_delta = cfg.get("plateau_delta", PLATEAU_DELTA) if cfg.loaded else PLATEAU_DELTA\n'
    '    threshold = cfg.chapter_threshold if cfg.loaded else CHAPTER_THRESHOLD\n'
    '    max_tokens = cfg.max_tokens_per_call if cfg.loaded else 16000\n'
    '    total = get_total_chapters(state)'
)

if old not in content:
    print("ERROR: old block not found in file!")
    # Try to locate what's there
    idx = content.find('plateau_delta = cfg.get')
    if idx >= 0:
        print(repr(content[idx:idx+300]))
    sys.exit(1)

content = content.replace(old, new)
open(path, "w", encoding="utf-8").write(content)

# Verify
verify = open(path, "r", encoding="utf-8").read()
if "threshold = cfg.chapter_threshold" in verify:
    print("SUCCESS: threshold variable added to pipeline_orchestrator.py")
    lines = verify.split("\n")
    for i in range(437, 442):
        print(f"  line {i+1}: {lines[i]}")
else:
    print("FAILED: threshold not found after writing")
    sys.exit(1)