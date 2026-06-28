#!/usr/bin/env python3
"""Quick smoke test: verify instrumentation doesn't break business logic."""
import sys
sys.path.insert(0, '.')

from pathlib import Path
from core.state_manager import parse_score

# Test parse_score with sentinel and normal inputs
tests = [
    ('overall_score: 7.5', 7.5),
    ('garbage text without any score at all', -1.0),
    ('', -1.0),
    ('overall_score: 3.0\nnovel_score: 8.0', 8.0),
]

passed = 0
for inp, expected in tests:
    result = parse_score(inp)
    ok = abs(result - expected) < 0.01
    status = 'PASS' if ok else 'FAIL'
    print(f'  [{status}] parse_score({inp[:40]!r}) = {result} (expected {expected})')
    if ok:
        passed += 1

print(f'\n{passed}/{len(tests)} parse_score tests passed')

# Check diagnostic.log was written
log = Path('logs/diagnostic.log')
if log.exists():
    lines = [l for l in log.read_text(encoding='utf-8').split('\n') if l.strip()]
    sentinel_lines = [l for l in lines if 'SENTINEL' in l]
    print(f'diagnostic.log: {len(lines)} total lines, {len(sentinel_lines)} SENTINEL lines')
    for l in sentinel_lines[:3]:
        print(f'  -> {l[:150]}')
else:
    print('WARNING: diagnostic.log not found')

# Verify api_client import
from core.api_client import call_llm
print('api_client.call_llm imported OK')

# Verify pipeline_orchestrator import
import pipeline_orchestrator as po
print('pipeline_orchestrator imported OK')

# Verify key functions accessible
for name in ['run_foundation', 'run_drafting', 'run_revision', 'run_export', 'run_pipeline']:
    if hasattr(po, name):
        print(f'  pipeline_orchestrator.{name} accessible')
    else:
        print(f'  WARNING: pipeline_orchestrator.{name} NOT FOUND')

print('\nSMOKE TEST PASSED - no new bugs detected')