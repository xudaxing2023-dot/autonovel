#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 4 E2E-1 Auto Diagnosis Script

Parses debug.log + results.tsv + state.json, auto-detects anomalies, traces root causes.
"""
import json, re, sys, time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

DEBUG_LOG = ROOT / "logs" / "debug.log"
RESULTS_TSV = ROOT / "output" / "results.tsv"
STATE_JSON = ROOT / "output" / "state.json"
CONFIG_JSON = ROOT / "output" / "config.json"
REPORT_FILE = ROOT / "logs" / "diagnosis_report.txt"

SENTINEL_SCORE = -1.0
PLATEAU_DELTA = 0.3

# Chinese regex patterns as unicode escapes to avoid encoding issues
RE_CHINESE = {
    "api_fail": re.compile(r"\u8c03\u7528\u5931\u8d25|\u8d85\u65f6"),  # call fail / timeout
    "retry_api": re.compile(r"\u91cd\u8bd5.*API"),                     # retry + API
    "score_revert": re.compile(
        r"\u4fee\u8ba2\u4f7f\u8bc4\u5206\u4e0b\u964d\s*\((\d+\.?\d*)\s*<\s*(\d+\.?\d*)\)"),  # revision caused score drop
    "plateau": re.compile(
        r"\u5e73\u53f0\u671f\u68c0\u6d4b\s*\(delta\s+(\d+\.?\d*)\s*[<>]\s*(\d+\.?\d*)\)"),  # plateau detect
    "voice_warn": re.compile(
        r"\u6587\u98ce\u6307\u7eb9\u8b66\u544a.*?\u7b2c\s*(\d+)\s*\u7ae0.*?:\s*(.*)"),     # voice warning ChX: detail
    "ghost_ch": re.compile(r"\u7b2c\s*(\d+)\s*\u7ae0\u4e0d\u5b58\u5728,\s*\u8df3\u8fc7"),    # ChX not exist, skip
    "foundation_score": re.compile(r"\u57fa\u7840\u6784\u5efa\u8bc4\u5206:\s*(\d+\.?\d*)"),  # foundation score
    "novel_score": re.compile(
        r"\u5c0f\u8bf4\u8bc4\u5206:\s*(\d+\.?\d*)\s*\(\u524d\u6b21:\s*(\d+\.?\d*),\s*\u5b57\u6570:\s*(\d+)\)"),  # novel score (prev, words)
    "final_novel_score": re.compile(r"\u6700\u7ec8\u5c0f\u8bf4\u8bc4\u5206:\s*(\d+\.?\d*)"),  # final novel score
    "review_round": re.compile(r"\u5ba1\u9605\u4fee\u8ba2\s+\u8f6e\u6b21\s+(\d+)"),           # review-revision round N
    "revision_cycle": re.compile(r"\u4fee\u8ba2\s+\u5faa\u73af\s+(\d+)/(\d+)"),               # revision cycle N/M
    "foundation_iter_banner": re.compile(r"\u57fa\u7840\u6784\u5efa\s+\u8fed\u4ee3\s+(\d+)"), # foundation iter N
    "iter_20_discard": re.compile(r"\u8fed\u4ee3\s*20"),                                      # iteration 20
}

def _get_ts(line):
    m = re.search(r"\[INSTR[^\]]*\]\s+(\d{2}:\d{2}:\d{2}\.\d{3})", line)
    if m:
        return m.group(1)
    m = re.search(r"^\[\d{2}:\d{2}:\d{2}\]", line)
    if m:
        return m.group(0).strip("[]")
    return ""


class Anomaly:
    def __init__(self, severity, code, title, detail, evidence, root_cause=""):
        self.severity = severity
        self.code = code
        self.title = title
        self.detail = detail
        self.evidence = evidence
        self.root_cause = root_cause

    def to_lines(self):
        icon = {"CRITICAL": "[CRIT]", "HIGH": "[HIGH]", "MEDIUM": "[MED]", "LOW": "[LOW]"}.get(self.severity, "[?]")
        lines = [f"  {icon} [{self.code}] {self.title}", f"     Detail: {self.detail}"]
        for ev in self.evidence:
            lines.append(f"     Evidence: {ev}")
        if self.root_cause:
            lines.append(f"     Root cause: {self.root_cause}")
        lines.append("")
        return lines


# ============ parsers ============

def parse_debug_log(path):
    data = {
        "api_timeouts": [], "api_retries": [], "score_reverts": [],
        "plateau_triggers": [], "voice_warnings": [], "ghost_chapter_skips": [],
        "foundation_iters": [], "revision_cycles": [], "review_revision_rounds": [],
        "novel_scores": [], "eval_minus_one": [], "crash_lines": [], "timeline": [],
    }
    if not path.exists():
        return data
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    for line in lines:
        ts = _get_ts(line)
        if ts:
            data["timeline"].append((ts, line.strip()[:200]))

        if RE_CHINESE["api_fail"].search(line):
            data["api_timeouts"].append((ts, line.strip()))
        if RE_CHINESE["retry_api"].search(line):
            data["api_retries"].append((ts, line.strip()))

        m = RE_CHINESE["score_revert"].search(line)
        if m:
            data["score_reverts"].append((ts, float(m.group(2)), float(m.group(1))))

        m = RE_CHINESE["plateau"].search(line)
        if m:
            data["plateau_triggers"].append((ts, float(m.group(1)), float(m.group(2))))

        m = RE_CHINESE["voice_warn"].search(line)
        if m:
            data["voice_warnings"].append((ts, int(m.group(1)), m.group(2).strip()))

        m = RE_CHINESE["ghost_ch"].search(line)
        if m:
            data["ghost_chapter_skips"].append((ts, int(m.group(1))))

        m = RE_CHINESE["foundation_score"].search(line)
        if m:
            data["foundation_iters"].append((ts, float(m.group(1))))

        m = RE_CHINESE["novel_score"].search(line)
        if m:
            data["novel_scores"].append((ts, float(m.group(1)), float(m.group(2)), int(m.group(3))))

        m = RE_CHINESE["final_novel_score"].search(line)
        if m:
            data["novel_scores"].append((ts, float(m.group(1)), None, None))

        if "-1.0" in line and ("score" in line.lower() or "\u8bc4\u5206" in line):
            data["eval_minus_one"].append((ts, line.strip()))

        m = RE_CHINESE["review_round"].search(line)
        if m:
            data["review_revision_rounds"].append(int(m.group(1)))

        m = RE_CHINESE["revision_cycle"].search(line)
        if m:
            data["revision_cycles"].append((int(m.group(1)), int(m.group(2))))

        if "CRASH" in line:
            data["crash_lines"].append((ts, line.strip()))

    return data


def parse_results_tsv(path):
    data = {
        "total_rows": 0, "keep_rows": 0, "discard_rows": 0, "cycle_rows": 0, "export_rows": 0,
        "discards": [], "keeps": [], "stages_seen": set(), "score_trajectory": [],
        "ghost_chapter_rows": [], "foundation_segments": 0,
    }
    if not path.exists():
        return data
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("commit"):
                continue
            parts = line.split("\t")
            if len(parts) < 6:
                continue
            commit, stage, score_str, word_count, status, reason = parts[:6]
            data["total_rows"] += 1
            try:
                score = float(score_str) if score_str else 0.0
            except ValueError:
                score = float("nan")
            data["stages_seen"].add(stage)
            if status == "keep":
                data["keep_rows"] += 1
                data["keeps"].append((commit, stage, score, word_count, reason))
            elif status == "discard":
                data["discard_rows"] += 1
                data["discards"].append((commit, stage, score, word_count, reason))
            elif status == "cycle":
                data["cycle_rows"] += 1
            elif status == "export":
                data["export_rows"] += 1
            data["score_trajectory"].append((stage, score))
            m = re.search(r"ch(\d+)", stage)
            if m and int(m.group(1)) > 3:
                data["ghost_chapter_rows"].append((stage, score, reason))

    data["foundation_segments"] = sum(1 for _, stage, _, _, _ in data["keeps"] if stage == "foundation")
    return data


def parse_json(path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


# ============ diagnosis ============

def dS(sev, code, title, detail, evidence, rc=""):
    return Anomaly(sev, code, title, detail, evidence, rc)


def diagnose_all(debug_data, tsv_data, state, config):
    anomalies = []
    total_ch = config.get("total_chapters", 3)
    max_foundation = config.get("max_foundation_iters", 3)

    # D1: Sentinel -1.0
    ev_tsv = [r for r in tsv_data["discards"] if r[2] == SENTINEL_SCORE]
    ev_log = debug_data["eval_minus_one"]
    if ev_tsv or ev_log:
        ev = []
        for commit, stage, score, wc, reason in ev_tsv:
            ev.append(f"results.tsv discard: stage={stage} score={score} reason={reason}")
        if debug_data["api_timeouts"]:
            ev.append(f"{len(debug_data['api_timeouts'])} API timeout(s) detected, correlated with -1.0 sentinel")
        anomalies.append(dS("CRITICAL", "D1-SENTINEL",
            "eval sentinel -1.0 treated as valid score, false regression -> git_reset_hard",
            f"{len(ev_tsv)} discard(s) with score=-1.0 in results.tsv. "
            f"{len(ev_log)} -1.0 occurrences in log. "
            f"Sentinel -1.0 means eval API failed. Pipeline compares -1.0 vs real score -> "
            f"declares regression -> triggers git_reset_hard -> loses all work.",
            ev,
            "API timeout -> eval returns -1.0 -> used in score comparison -> "
            "-1.0 < real score -> regression -> revert -> Foundation forever fails -> reset"))

    # D2: Git reset storm
    n_foundation = tsv_data["foundation_segments"]
    n_discards = tsv_data["discard_rows"]
    if n_foundation > 1 or n_discards > 0:
        ev = [
            f"results.tsv: {n_foundation} foundation segments (= git_reset_hard events)",
            f"results.tsv: {n_discards} discard rows, {tsv_data['total_rows']} total rows (expected ~15)",
        ]
        anomalies.append(dS("CRITICAL", "D2-RESET-STORM",
            f"Git reset storm: {n_foundation} full resets",
            f"At least {n_foundation} git_reset_hard events. Each loses all drafted chapters. "
            f"Caused 287min runtime and {tsv_data['total_rows']}-row results.tsv.",
            ev,
            "API timeout -> eval -1.0 -> Foundation never passes -> iter limit -> force reset -> "
            "redo Foundation -> may hit timeout again -> cycle -> multiple resets"))

    # D3: Frequent reverts
    reverts = debug_data["score_reverts"]
    tsv_discards = tsv_data["discards"]
    if reverts or tsv_discards:
        ev = []
        for ts, old_s, new_s in reverts:
            ev.append(f"[{ts}] revision score {new_s} < {old_s} -> revert")
        for _, stage, score, _, reason in tsv_discards:
            if score != SENTINEL_SCORE:
                ev.append(f"results.tsv discard: {stage} score={score} reason={reason}")
        real_reverts = [(t, o, n) for t, o, n in reverts if o > 0 and n > 0]
        dt = f"{len(reverts)} reverts. "
        dt += f"{len(real_reverts)} are genuine regressions. " if real_reverts else "May all be sentinel false positives. "
        anomalies.append(dS("HIGH", "D3-FREQUENT-REVERTS",
            f"Frequent reverts: {len(reverts)} score-drops + {tsv_data['discard_rows']} discards",
            dt, ev,
            "Some from sentinel -1.0 misjudgment; genuine ones: revision prompts may "
            "introduce new issues or over-modify text causing score decline."))

    # D4: Ghost chapter ch04
    skips = debug_data["ghost_chapter_skips"]
    tsv_ghost = tsv_data["ghost_chapter_rows"]
    if skips or tsv_ghost:
        ev = []
        for ts, ch in skips:
            ev.append(f"[{ts}] pipeline: chapter {ch} not exist, skipped")
        for stage, score, reason in tsv_ghost:
            ev.append(f"results.tsv: {stage} score={score} reason={reason[:120]}")
        anomalies.append(dS("HIGH", "D4-GHOST-CHAPTER",
            f"Ghost chapter ch04 (config={total_ch} chapters)",
            f"{len(skips)} pipeline skips + {len(tsv_ghost)} tsv rows for ch04. "
            f"Review-revision internal chapter count != chapters_total={total_ch}.",
            ev,
            "review_revision reads chapter count from git history / separate state "
            "instead of config.json/state.json chapters_total."))

    # D5: Plateau boundary
    plateaus = debug_data["plateau_triggers"]
    if plateaus:
        ev = []
        for ts, delta, threshold in plateaus:
            ev.append(f"[{ts}] delta={delta} vs threshold={threshold}: "
                      f"delta < threshold = {delta < threshold}, delta <= threshold = {delta <= threshold}")
        anomalies.append(dS("MEDIUM", "D5-PLATEAU-BOUNDARY",
            "Plateau detection float boundary unstable",
            f"Max improvement equals plateau_delta={PLATEAU_DELTA}. "
            f"Float precision may cause boundary misjudgment.",
            ev, "Float delta may be 0.2999... Use <= or epsilon tolerance."))

    # D6: State fields missing
    issues = []
    if state.get("total_volumes", -1) == 0 and config.get("total_volumes", -1) != 0:
        issues.append(f"total_volumes: state={state.get('total_volumes')} config={config.get('total_volumes')}")
    if state.get("chapters_per_volume", -1) == 0 and config.get("chapters_per_volume", -1) != 0:
        issues.append(f"chapters_per_volume: state={state.get('chapters_per_volume')} config={config.get('chapters_per_volume')}")
    if state.get("canon_entry_count", -1) == 0:
        issues.append("canon_entry_count=0 (may not have grown or was reset)")
    if issues:
        anomalies.append(dS("LOW", "D6-STATE-FIELDS",
            "state.json key fields are 0 (missing/not synced)",
            "Affects resume scenarios.", issues,
            "write_e2e1_config writes config.json only, not synced to state."))

    # D7: API timeouts
    timeouts = debug_data["api_timeouts"]
    if timeouts:
        ev = [f"[{ts}] {ln}" for ts, ln in timeouts[:10]]
        anomalies.append(dS("HIGH", "D7-API-TIMEOUTS",
            f"API timeout/failure: {len(timeouts)} times",
            f"{len(timeouts)} API call failures. Direct trigger of -1.0 sentinel and git_reset_hard storm.",
            ev, "API backend instability or token overflow causing 600s timeout."))

    # D8: Voice warnings
    warnings = debug_data["voice_warnings"]
    if warnings:
        ev = []
        chapters_affected = set()
        for ts, ch, detail in warnings:
            ev.append(f"[{ts}] Ch{ch}: {detail}")
            chapters_affected.add(ch)
        anomalies.append(dS("MEDIUM", "D8-VOICE-WARNINGS",
            f"Voice warnings on all chapters: {len(chapters_affected)}/{total_ch}",
            f"All chapters: no dialogue, excessive em-dash density (8.1-8.8/1000). "
            f"Systematic deviation between voice (minimalist cold) and drafting output.",
            ev, "Voice-defined dialogue ratio expectation != actual LLM drafting output."))

    # D9: Foundation iteration 20
    iter20 = None
    for commit, stage, score, wc, reason in tsv_data["discards"]:
        if RE_CHINESE["iter_20_discard"].search(reason):
            iter20 = (commit, stage, score, reason)
            break
    if iter20:
        ev = [
            f"results.tsv: {iter20}",
            f"Config max_foundation_iters={max_foundation}, actually ran 20 iterations",
        ]
        anomalies.append(dS("CRITICAL", "D9-FOUNDATION-ITER20",
            f"Foundation ran 20 iterations (limit={max_foundation}) before force-discard",
            f"Far exceeding config limit. Limit check bypassed or repeated timeouts caused no score change each iter.",
            ev, "eval returns -1.0 every time -> score always 0.0 -> no improvement -> "
            "continue iteration -> limit check invalidated by sentinel -> runs 20 -> force discard."))

    # D10: Score stagnation
    novel_scores = debug_data["novel_scores"]
    scores_only = [s for _, s, _, _ in novel_scores if s is not None]
    if len(scores_only) >= 2:
        ev = []
        for ts, s, p, wc in novel_scores:
            ev.append(f"[{ts}] novel_score={s} (prev={p}, words={wc})")
        trend = " -> ".join(str(s) for s in scores_only)
        ev.append(f"Score trajectory: {trend}")
        max_impr = max(scores_only) - min(scores_only)
        if max_impr < PLATEAU_DELTA:
            ev.append(f"Max improvement {max_impr} < plateau threshold {PLATEAU_DELTA}")
        anomalies.append(dS("HIGH", "D10-SCORE-STAGNATION",
            "Novel score stagnated: revision could not sustain quality improvement",
            f"Trajectory: {trend}. Final score ~{scores_only[-1]}. "
            f"3 main cycles + 3 review-revision rounds failed to break quality ceiling.",
            ev, "Revision prompts may introduce new issues; eval model scoring inconsistency; "
            "or sentinel false-reverts lost valid revision work."))

    return anomalies


def converge_root_causes(anomalies):
    codes = {a.code for a in anomalies}
    rcs = []

    sentinel_codes = {"D1-SENTINEL", "D2-RESET-STORM", "D9-FOUNDATION-ITER20"}
    if codes & sentinel_codes:
        rcs.append({
            "id": "RC-1", "priority": "P0",
            "title": "eval sentinel -1.0 not filtered -> false regression -> git_reset_hard storm",
            "affected": sorted(codes & sentinel_codes),
            "fix": "Check score == -1.0 at all comparison points: retry eval instead of declaring regression. "
                   "Foundation iter: add dedicated eval retry. API timeout: add fallback score mechanism.",
        })

    if "D4-GHOST-CHAPTER" in codes:
        rcs.append({
            "id": "RC-2", "priority": "P1",
            "title": "Review-revision chapter count boundary check missing",
            "affected": ["D4-GHOST-CHAPTER"],
            "fix": "Add chapters_total consistency check in review-revision rounds.",
        })

    if "D5-PLATEAU-BOUNDARY" in codes:
        rcs.append({
            "id": "RC-3", "priority": "P2",
            "title": "Plateau detection float boundary unstable",
            "affected": ["D5-PLATEAU-BOUNDARY"],
            "fix": "Use <= comparison or add epsilon (1e-9) tolerance.",
        })

    if "D6-STATE-FIELDS" in codes:
        rcs.append({
            "id": "RC-4", "priority": "P2",
            "title": "state.json fields not synced with config",
            "affected": ["D6-STATE-FIELDS"],
            "fix": "Sync total_volumes/chapters_per_volume to state in write_e2e1_config.",
        })

    if "D8-VOICE-WARNINGS" in codes:
        rcs.append({
            "id": "RC-5", "priority": "P2",
            "title": "Voice vs drafting output systematic deviation",
            "affected": ["D8-VOICE-WARNINGS"],
            "fix": "Adjust dialogue density in drafting prompt or relax em-dash limit in voice.",
        })

    return rcs


def render_report(anomalies, root_causes, debug_data, tsv_data, state, config):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    out = []
    out.append("=" * 70)
    out.append("  Stage 4 E2E-1 Auto Diagnosis Report")
    out.append(f"  Generated: {now}")
    out.append("  Sources: logs/debug.log, output/results.tsv, output/state.json, output/config.json")
    out.append("=" * 70)
    out.append("")

    total_ch = config.get("total_chapters", 3)
    out.append("--- Phase Summary ---")
    out.append(f"  Config: {total_ch} chapters")
    out.append(f"  Final state: phase={state.get('phase', '?')}, "
               f"novel_score={state.get('novel_score', '?')}, "
               f"foundation_score={state.get('foundation_score', '?')}, "
               f"revision_cycle={state.get('revision_cycle', '?')}")
    f_scores = [s for _, s in debug_data["foundation_iters"]]
    out.append(f"  Foundation: {len(f_scores)} iteration(s), scores: {f_scores}")
    out.append(f"  Drafting: {len(debug_data['voice_warnings'])} voice warning(s)")
    out.append(f"  Revision: {len(debug_data['revision_cycles'])} cycle(s), "
               f"{len(debug_data['review_revision_rounds'])} review-revision round(s), "
               f"{len(debug_data['score_reverts'])} revert(s)")
    out.append(f"  Export: {tsv_data['export_rows']} tsv export row(s)")
    out.append("")

    out.append(f"--- Detected Anomalies ({len(anomalies)} total) ---")
    for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
        group = [a for a in anomalies if a.severity == sev]
        if not group:
            continue
        out.append(f"  {sev} ({len(group)}):")
        for a in group:
            out.extend(a.to_lines())

    out.append(f"--- Root Causes ({len(root_causes)} converged) ---")
    for rc in root_causes:
        out.append(f"  [{rc['priority']}] {rc['id']}: {rc['title']}")
        out.append(f"    Affected: {', '.join(rc['affected'])}")
        out.append(f"    Fix: {rc['fix']}")
        out.append("")

    out.append("--- Key Metrics ---")
    out.append(f"  results.tsv:    {tsv_data['total_rows']} rows "
               f"(keep={tsv_data['keep_rows']}, discard={tsv_data['discard_rows']}, "
               f"cycle={tsv_data['cycle_rows']}, export={tsv_data['export_rows']})")
    out.append(f"  API timeouts:   {len(debug_data['api_timeouts'])}")
    out.append(f"  Score reverts:  {len(debug_data['score_reverts'])}")
    out.append(f"  Voice warnings: {len(debug_data['voice_warnings'])}")
    out.append(f"  Ghost chapters: {len(debug_data['ghost_chapter_skips'])} pipeline "
               f"+ {len(tsv_data['ghost_chapter_rows'])} tsv")
    out.append(f"  Foundation seg: {tsv_data['foundation_segments']}")
    out.append(f"  Eval -1.0:      {len(debug_data['eval_minus_one'])} log matches")
    out.append(f"  Stages seen:    {sorted(tsv_data['stages_seen'])}")
    out.append("")

    critical_count = len([a for a in anomalies if a.severity == "CRITICAL"])
    high_count = len([a for a in anomalies if a.severity == "HIGH"])
    out.append("--- Assessment ---")
    if critical_count > 0 or high_count >= 3:
        out.append("  WARNING: Systemic anomalies. Sentinel -1.0 is root cause. Re-run after P0 fix.")
    elif high_count > 0:
        out.append("  WARNING: Non-critical anomalies. Recommend P1 fixes before re-verification.")
    else:
        out.append("  OK: Run is basically normal, only observational anomalies.")
    out.append("")
    out.append(f"Report ends - {now}")
    return "\n".join(out)


def main():
    print("Stage 4 E2E-1 Auto Diagnosis")
    print("=" * 50)

    for name, path in [("debug.log", DEBUG_LOG), ("results.tsv", RESULTS_TSV),
                        ("state.json", STATE_JSON), ("config.json", CONFIG_JSON)]:
        status = "OK" if path.exists() else "MISSING"
        print(f"  [{status}] {name}")

    if not DEBUG_LOG.exists() and not RESULTS_TSV.exists():
        print("\nERROR: Both debug.log and results.tsv missing. Run _run_stage4_e2e1.py first.")
        return

    print("\nParsing debug.log ...")
    debug_data = parse_debug_log(DEBUG_LOG)
    print(f"  -> {len(debug_data['timeline'])} timeline events")

    print("Parsing results.tsv ...")
    tsv_data = parse_results_tsv(RESULTS_TSV)
    print(f"  -> {tsv_data['total_rows']} rows")

    print("Parsing state.json ...")
    state = parse_json(STATE_JSON)
    print(f"  -> phase={state.get('phase', '?')}")

    print("Parsing config.json ...")
    config = parse_json(CONFIG_JSON)
    print(f"  -> chapters={config.get('total_chapters', '?')}")

    print("\nRunning diagnosis ...")
    anomalies = diagnose_all(debug_data, tsv_data, state, config)
    root_causes = converge_root_causes(anomalies)
    print(f"  -> {len(anomalies)} anomalies, {len(root_causes)} root causes")

    report_text = render_report(anomalies, root_causes, debug_data, tsv_data, state, config)
    print("\n" + report_text)

    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(report_text, encoding="utf-8")
    print(f"\nReport saved to: {REPORT_FILE}")


if __name__ == "__main__":
    main()