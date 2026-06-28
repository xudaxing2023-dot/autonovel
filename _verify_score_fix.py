"""verify parse_score() fallback fix - ASCII-safe output."""
import sys, io
sys.path.insert(0, ".")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from core.state_manager import parse_score

samples = [
    ("## score: 6.5", 6.5),
    ("### 15. overall_score\n\n**score**: 7.0/10", 7.0),
    ("**score**: **5.5/10**", 5.5),
    ("score: 8.2", 8.2),
    ("overall_score: 6.5", 6.5),
    ("hello world no score", -1.0),
    ("**score**: 7/10\n## score: 6.5/10", 6.5),
]

passed = 0
failed = 0
for text, expected in samples:
    result = parse_score(text, "overall_score")
    ok = abs(result - expected) < 0.01
    if ok:
        passed += 1
    else:
        failed += 1
    preview = text[:70].replace("\n", "\\n")
    print(f"  {'OK' if ok else '!!'} {preview} -> {result} (expected {expected})")

print(f"\n  {passed}/{passed+failed} passed")