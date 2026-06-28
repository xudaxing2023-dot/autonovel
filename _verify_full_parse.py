#!/usr/bin/env python3
import json, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
data = json.load(open("output/eval_logs/full_20260627_133635.json", "r", encoding="utf-8"))
from evaluation.evaluate import _parse_full_eval_result
r = _parse_full_eval_result(data["raw_output"])
print("novel_score:", r.get("novel_score"))
print("weakest_chapter:", r.get("weakest_chapter"))
print("weakest_dimension:", r.get("weakest_dimension"))
print("top_suggestion:", len(r.get("top_suggestion", "")))
for k, v in r.items():
    if isinstance(v, dict):
        print(f"{k}: score={v.get('score')} note_len={len(v.get('note',''))} fix_len={len(v.get('fix',''))}")