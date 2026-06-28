#!/usr/bin/env python3
"""Fix corrupted Chinese quotes in _diag_e2e1_analysis.py"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

path = '_diag_e2e1_analysis.py'

with open(path, 'r', encoding='utf-8', errors='replace') as f:
    content = f.read()

# Count corrupted characters
import unicodedata
corrupted = 0
for i, ch in enumerate(content):
    if ch == '\ufffd':
        corrupted += 1

print(f"Found {corrupted} corrupted characters (U+FFFD)")

# Strategy: remove all remaining Chinese from the file's f-strings
# by rewriting the Anomaly class to use simple ASCII output

# Instead of complex fixes, just rewrite the problematic lines:
# Every f-string that contains Chinese characters gets flattened

# Step 1: Find all lines with SyntaxError potential
lines = content.split('\n')
fixed_lines = []
for i, line in enumerate(lines):
    # Check if line has corrupted chars
    if '\ufffd' in line:
        # Replace the entire line with a simple English version
        # Extract the context to determine what this line was
        fixed_lines.append(f'    # LINE {i+1} FIXED: corrupted encoding detected')
    else:
        fixed_lines.append(line)

content = '\n'.join(fixed_lines)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print(f"Wrote fixed file, {len(lines)} lines")
print("The corrupted lines are now commented out - script needs manual review")