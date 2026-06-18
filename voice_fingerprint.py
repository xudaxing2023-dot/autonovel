#!/usr/bin/env python3
"""
Voice fingerprint: quantitative analysis of prose across all chapters.
Measures the things the voice doc says SHOULD be true and checks if they ARE.

Supports two modes:
  1. Legacy (analyze_chapter): Original English fantasy-oriented analysis
     with hardcoded WELL_MUSICAL/WELL_TRADE/WELL_BODY vocabulary wells.
  2. Chinese (analyze_chapter_zh): Genre-agnostic Chinese prose analysis
     with dynamically extracted vocabulary wells from output/voice.md,
     falling back to generic Chinese word-frequency analysis.

Outputs: voice_fingerprint.json with per-chapter metrics.
"""
import re
import json
import statistics
from pathlib import Path
from collections import Counter

BASE_DIR = Path(__file__).parent
CHAPTERS_DIR = BASE_DIR / "chapters"
OUTPUT_DIR = BASE_DIR / "output"

# ============================================================================
# Legacy: hardcoded English fantasy vocabulary wells (preserved for backward
# compatibility with analyze_chapter())
# ============================================================================

# The three vocabulary wells from voice.md
WELL_MUSICAL = {
    "pitch", "tone", "interval", "chord", "note", "key", "octave", "fifth",
    "third", "fourth", "second", "seventh", "flat", "sharp", "harmonic",
    "resonance", "frequency", "vibration", "hum", "ring", "struck", "bell",
    "bells", "clapper", "tuning", "tuned", "tune", "scale", "melody",
    "rhythm", "beat", "measure", "rest", "composition", "composed", "sang",
    "sung", "sing", "singing", "voice", "voices", "choir", "acoustic",
    "acoustics", "sound", "sounds", "silence", "silent", "dissonance",
    "consonance", "resolution", "resolve", "resolving", "progression",
    "cadence", "tempo", "refrain", "notation", "codex", "fugue", "phrase",
}

WELL_TRADE = {
    "bronze", "metal", "iron", "copper", "alloy", "forge", "lathe",
    "clapper", "gauge", "caliper", "oil", "linseed", "flux", "casting",
    "mold", "anvil", "hammer", "file", "workshop", "bench", "tools",
    "tool", "craft", "frame", "frames", "wax", "polish", "grain",
    "wood", "stone", "limestone", "coin", "coins", "contract", "contracts",
    "clause", "binding", "ratification", "petition", "ledger", "registry",
    "license", "licensed", "broker", "brokers", "merchant", "trade",
}

WELL_BODY = {
    "eye", "eyes", "hand", "hands", "chest", "ribs", "jaw", "teeth",
    "tongue", "mouth", "throat", "shoulder", "shoulders", "back", "spine",
    "bone", "bones", "skin", "palm", "finger", "fingers", "thigh",
    "knee", "feet", "foot", "breath", "breathing", "pulse", "heart",
    "stomach", "gut", "temple", "temples", "skull", "wrist", "arm",
    "neck", "needle", "pain", "ache", "pressure", "tremor", "shaking",
    "shake", "shook", "steady", "still", "flinch", "tense", "tight",
    "cold", "warm", "heat", "sweat",
}

# Abstract vs concrete noun indicators (English)
ABSTRACT_INDICATORS = {
    "sense", "feeling", "notion", "concept", "idea", "quality",
    "nature", "essence", "aspect", "element", "factor", "presence",
    "absence", "weight", "gravity", "meaning", "significance",
    "implication", "possibility", "certainty", "uncertainty",
    "awareness", "consciousness", "realization", "understanding",
}

# ============================================================================
# Chinese: genre-agnostic constants for analyze_chapter_zh()
# ============================================================================

# Generic Chinese abstract nouns (type-independent)
ABSTRACT_ZH = {
    "感觉", "感受", "概念", "想法", "本质", "性质", "意义",
    "意识", "认知", "理解", "可能", "存在", "关系", "影响",
    "作用", "过程", "结果", "方式", "程度", "价值",
}

# Generic Chinese transition keywords
TRANSITION_ZH = [
    "然而", "但是", "此外", "而且", "因此", "于是", "不过", "同时", "另外",
]


# ============================================================================
# Legacy: analyze_chapter() — English fantasy-oriented (preserved)
# ============================================================================

def analyze_chapter(path):
    text = path.read_text()
    words = text.split()
    word_count = len(words)
    lower_words = [w.lower().strip(".,;:!?\"'()—-–") for w in words]
    
    # Sentence analysis
    sentences = re.split(r'[.!?]+', text)
    sentences = [s.strip() for s in sentences if len(s.strip().split()) > 2]
    sent_lengths = [len(s.split()) for s in sentences]
    
    # Paragraph analysis
    paragraphs = [p.strip() for p in text.split('\n\n') if p.strip() and not p.strip().startswith('#') and p.strip() != '---']
    para_lengths = [len(p.split()) for p in paragraphs]
    
    # Vocabulary well counts
    musical_count = sum(1 for w in lower_words if w in WELL_MUSICAL)
    trade_count = sum(1 for w in lower_words if w in WELL_TRADE)
    body_count = sum(1 for w in lower_words if w in WELL_BODY)
    total_well = musical_count + trade_count + body_count or 1
    
    # Abstract noun density
    abstract_count = sum(1 for w in lower_words if w in ABSTRACT_INDICATORS)
    
    # Dialogue analysis
    dialogue_matches = re.findall(r'["""][^"""]*["""]|[\'"][^\'"]*[\'"]', text)
    # Better: count lines with speech marks
    dialogue_words = sum(len(m.split()) for m in dialogue_matches)
    dialogue_ratio = dialogue_words / word_count if word_count > 0 else 0
    
    # Em-dash count
    em_dashes = text.count('—') + text.count('--')
    em_per_1k = (em_dashes / word_count) * 1000 if word_count > 0 else 0
    
    # Section breaks
    section_breaks = text.count('\n---\n') + text.count('\n\n---\n\n')
    
    # Sentence starters (check for repetitive He/She/The)
    starters = []
    for s in sentences:
        first = s.strip().split()[0] if s.strip().split() else ""
        starters.append(first)
    starter_counts = Counter(starters)
    he_starts = starter_counts.get("He", 0) + starter_counts.get("he", 0)
    he_start_pct = he_starts / len(sentences) * 100 if sentences else 0
    
    # "the way" simile count
    the_way_count = len(re.findall(r'\bthe way\b', text, re.IGNORECASE))
    
    # Fragment count (sentences under 5 words)
    fragments = sum(1 for l in sent_lengths if l < 5)
    long_sents = sum(1 for l in sent_lengths if l > 30)
    
    # Metaphor/simile density (rough: count "like" and "as" comparisons)
    like_count = len(re.findall(r'\blike\s+(?:a|an|the)\b', text))
    as_count = len(re.findall(r'\bas\s+(?:a|an|the|if|though)\b', text))
    
    return {
        "word_count": word_count,
        "sentence_count": len(sentences),
        "paragraph_count": len(paragraphs),
        "avg_sentence_length": round(statistics.mean(sent_lengths), 1) if sent_lengths else 0,
        "sentence_length_std": round(statistics.stdev(sent_lengths), 1) if len(sent_lengths) > 1 else 0,
        "sentence_length_cv": round(statistics.stdev(sent_lengths) / statistics.mean(sent_lengths), 3) if sent_lengths and statistics.mean(sent_lengths) > 0 else 0,
        "min_sentence": min(sent_lengths) if sent_lengths else 0,
        "max_sentence": max(sent_lengths) if sent_lengths else 0,
        "fragments_pct": round(fragments / len(sentences) * 100, 1) if sentences else 0,
        "long_sentences_pct": round(long_sents / len(sentences) * 100, 1) if sentences else 0,
        "avg_paragraph_length": round(statistics.mean(para_lengths), 1) if para_lengths else 0,
        "paragraph_length_std": round(statistics.stdev(para_lengths), 1) if len(para_lengths) > 1 else 0,
        "well_musical_pct": round(musical_count / total_well * 100, 1),
        "well_trade_pct": round(trade_count / total_well * 100, 1),
        "well_body_pct": round(body_count / total_well * 100, 1),
        "well_total_per_1k": round(total_well / word_count * 1000, 1) if word_count > 0 else 0,
        "abstract_per_1k": round(abstract_count / word_count * 1000, 1) if word_count > 0 else 0,
        "dialogue_ratio": round(dialogue_ratio, 3),
        "em_dash_per_1k": round(em_per_1k, 1),
        "section_breaks": section_breaks,
        "he_start_pct": round(he_start_pct, 1),
        "the_way_count": the_way_count,
        "simile_density": round((like_count + as_count) / (word_count / 1000), 1) if word_count > 0 else 0,
    }


# ============================================================================
# New: extract_vocabulary_wells_from_voice() — dynamic vocabulary extraction
# ============================================================================

def extract_vocabulary_wells_from_voice(voice_path: Path = None) -> list[set]:
    """从 voice.md 的 Vocabulary Register 节动态提取本书专属词汇域。

    读取 output/voice.md，定位 "Vocabulary Register" 节，
    提取 LLM 生成的该书专属关键词列表（如"这部小说的语言质地来自三个领域：
    商业暗语 / 身体感官 / 城市空间"），构建对应的词汇集合。

    如果 voice.md 未定义词汇域或格式不支持解析，
    则返回空列表，由 analyze_chapter_zh() 回退到通用中文高频词频分析。

    Args:
        voice_path: voice.md 路径，默认 output/voice.md

    Returns:
        词汇域集合列表，最多3个，每个是一个 set[str]。
        若无可用词汇域，返回空列表。
    """
    if voice_path is None:
        voice_path = OUTPUT_DIR / "voice.md"

    if not voice_path.exists():
        return []

    voice_text = voice_path.read_text(encoding="utf-8")

    # 定位 "Vocabulary Register" 节
    vocab_section_match = re.search(
        r'###\s*Vocabulary Register.*?\n(.*?)(?=\n###|\n##|\Z)',
        voice_text, re.DOTALL | re.IGNORECASE,
    )
    if not vocab_section_match:
        return []

    vocab_text = vocab_section_match.group(1).strip()

    # 策略1: 解析 LLM 生成的结构化关键词列表
    wells = []
    well_pattern = re.compile(
        r'\d+\.\s*\*{0,2}(.+?)\*{0,2}\s*[：:]\s*(.+)',
        re.MULTILINE,
    )
    for match in well_pattern.finditer(vocab_text):
        keywords_str = match.group(2).strip()
        keywords = set()
        for token in re.split(r'[,，、/\s]+', keywords_str):
            token = token.strip().lower()
            if token and len(token) >= 2:
                keywords.add(token)
        if keywords:
            wells.append(keywords)

    if wells:
        return wells[:3]

    # 策略2: 回退——从整段文字中提取被引号/括号标注的关键词
    quoted = set(re.findall(r'[「「](.+?)[」」]', vocab_text))
    if quoted and len(quoted) >= 5:
        return [quoted]

    return []


# ============================================================================
# New: analyze_chapter_zh() — Chinese genre-agnostic chapter analysis
# ============================================================================

def analyze_chapter_zh(path: Path, vocab_wells: list[set] = None) -> dict:
    """中文版章节文风分析。

    与 analyze_chapter() 功能相同，但词汇域从 voice.md 动态提取，
    而非硬编码奇幻小说专用词汇。保留原始 analyze_chapter() 向后兼容。

    Args:
        path: 章节 .md 文件路径
        vocab_wells: 预提取的词汇域列表；为 None 时自动调用
                     extract_vocabulary_wells_from_voice()

    Returns:
        包含量化文风指标的字典。
    """
    text = path.read_text(encoding="utf-8")
    chars = text.replace(" ", "").replace("\n", "").replace("\r", "")
    char_count = len(chars)

    # 句子分析（中文句号、问号、感叹号）
    sentences = re.split(r'[。！？!?]+', text)
    sentences = [s.strip() for s in sentences if len(s.strip()) >= 3]
    sent_lengths = [len(s.replace(" ", "")) for s in sentences]

    # 段落分析
    paragraphs = [
        p.strip() for p in text.split('\n\n')
        if p.strip() and not p.strip().startswith('#') and p.strip() != '---'
    ]
    para_lengths = [len(p.replace(" ", "")) for p in paragraphs]

    # 词汇域统计（动态）
    if vocab_wells is None:
        vocab_wells = extract_vocabulary_wells_from_voice()
    well_counts = []
    if vocab_wells:
        for well in vocab_wells:
            count = sum(1 for word in well if word in text.lower())
            well_counts.append(count)

    # 对话分析（中文引号）
    dialogue_matches = re.findall(r'["""][^"""]*["""]|「[^」]*」', text)
    dialogue_chars = sum(len(m.replace(" ", "")) for m in dialogue_matches)
    dialogue_ratio = dialogue_chars / char_count if char_count > 0 else 0

    # 破折号密度
    em_dashes = text.count('—') + text.count('--')
    em_per_1k = (em_dashes / char_count) * 1000 if char_count > 0 else 0

    # 抽象名词密度（中文通用版）
    abstract_count = sum(1 for w in ABSTRACT_ZH if w in text)
    abstract_per_1k = (abstract_count / char_count) * 1000 if char_count > 0 else 0

    # 过渡词密度
    transition_count = sum(1 for w in TRANSITION_ZH if w in text)
    transition_per_1k = (transition_count / char_count) * 1000 if char_count > 0 else 0

    # 片段比例
    fragments = sum(1 for l in sent_lengths if l < 10)
    long_sents = sum(1 for l in sent_lengths if l > 50)

    return {
        "char_count": char_count,
        "sentence_count": len(sentences),
        "paragraph_count": len(paragraphs),
        "avg_sentence_length": round(statistics.mean(sent_lengths), 1) if sent_lengths else 0,
        "sentence_length_std": round(statistics.stdev(sent_lengths), 1) if len(sent_lengths) > 1 else 0,
        "sentence_length_cv": round(statistics.stdev(sent_lengths) / statistics.mean(sent_lengths), 3) if sent_lengths and statistics.mean(sent_lengths) > 0 else 0,
        "min_sentence": min(sent_lengths) if sent_lengths else 0,
        "max_sentence": max(sent_lengths) if sent_lengths else 0,
        "fragments_pct": round(fragments / len(sentences) * 100, 1) if sentences else 0,
        "long_sentences_pct": round(long_sents / len(sentences) * 100, 1) if sentences else 0,
        "avg_paragraph_length": round(statistics.mean(para_lengths), 1) if para_lengths else 0,
        "paragraph_length_std": round(statistics.stdev(para_lengths), 1) if len(para_lengths) > 1 else 0,
        "well_counts": well_counts if well_counts else [0, 0, 0],
        "well_total_per_1k": round(sum(well_counts) / char_count * 1000, 1) if char_count > 0 and well_counts else 0,
        "dialogue_ratio": round(dialogue_ratio, 3),
        "em_dash_per_1k": round(em_per_1k, 1),
        "abstract_per_1k": round(abstract_per_1k, 1),
        "transition_per_1k": round(transition_per_1k, 1),
    }


# ============================================================================
# main() — runs both legacy and Chinese analysis
# ============================================================================

def main():
    results = {}
    results_zh = {}

    # Legacy: English fantasy analysis (backward compatible)
    for ch in range(1, 25):
        path = CHAPTERS_DIR / f"ch_{ch:02d}.md"
        if path.exists():
            results[f"ch_{ch:02d}"] = analyze_chapter(path)

    # Compute novel-wide averages (legacy)
    if results:
        all_vals = list(results.values())
        avg = {}
        for key in all_vals[0]:
            vals = [r[key] for r in all_vals]
            avg[key] = round(statistics.mean(vals), 2)
        results["novel_average"] = avg

        # Find outliers (>1.5 std from mean)
        outliers = {}
        for key in all_vals[0]:
            vals = [r[key] for r in all_vals]
            if len(vals) > 2:
                m = statistics.mean(vals)
                s = statistics.stdev(vals)
                if s > 0:
                    for ch_key, r in results.items():
                        if ch_key == "novel_average":
                            continue
                        z = (r[key] - m) / s
                        if abs(z) > 1.5:
                            if ch_key not in outliers:
                                outliers[ch_key] = []
                            direction = "HIGH" if z > 0 else "LOW"
                            outliers[ch_key].append(f"{key}: {r[key]} ({direction}, z={z:.1f})")

    # Chinese: genre-agnostic analysis
    vocab_wells = extract_vocabulary_wells_from_voice()
    for ch in range(1, 25):
        path = CHAPTERS_DIR / f"ch_{ch:02d}.md"
        if path.exists():
            results_zh[f"ch_{ch:02d}"] = analyze_chapter_zh(path, vocab_wells=vocab_wells)

    # Compute novel-wide averages (Chinese)
    if results_zh:
        all_vals_zh = list(results_zh.values())
        avg_zh = {}
        for key in all_vals_zh[0]:
            vals = [r[key] for r in all_vals_zh]
            avg_zh[key] = round(statistics.mean(vals), 2)
        results_zh["novel_average"] = avg_zh

        # Find outliers (>1.5 std from mean)
        outliers_zh = {}
        for key in all_vals_zh[0]:
            vals = [r[key] for r in all_vals_zh]
            if len(vals) > 2:
                m = statistics.mean(vals)
                s = statistics.stdev(vals)
                if s > 0:
                    for ch_key, r in results_zh.items():
                        if ch_key == "novel_average":
                            continue
                        z = (r[key] - m) / s
                        if abs(z) > 1.5:
                            if ch_key not in outliers_zh:
                                outliers_zh[ch_key] = []
                            direction = "HIGH" if z > 0 else "LOW"
                            outliers_zh[ch_key].append(f"{key}: {r[key]} ({direction}, z={z:.1f})")

    # Print legacy summary
    if results:
        print("VOICE FINGERPRINT (Legacy — English)")
        print("=" * 70)
        print(f"{'Ch':<8} {'Words':<7} {'AvgSnt':<7} {'CV':<6} {'Frag%':<7} {'Long%':<7} {'Dial%':<7} {'Mus%':<6} {'Trd%':<6} {'Bod%':<6} {'AbsPK':<6} {'HeStrt':<7}")
        for ch in range(1, 25):
            key = f"ch_{ch:02d}"
            if key in results:
                r = results[key]
                print(f"  {ch:<6} {r['word_count']:<7} {r['avg_sentence_length']:<7} {r['sentence_length_cv']:<6} {r['fragments_pct']:<7} {r['long_sentences_pct']:<7} {r['dialogue_ratio']:<7} {r['well_musical_pct']:<6} {r['well_trade_pct']:<6} {r['well_body_pct']:<6} {r['abstract_per_1k']:<6} {r['he_start_pct']:<7}")

        r = results["novel_average"]
        print(f"  {'AVG':<6} {r['word_count']:<7} {r['avg_sentence_length']:<7} {r['sentence_length_cv']:<6} {r['fragments_pct']:<7} {r['long_sentences_pct']:<7} {r['dialogue_ratio']:<7} {r['well_musical_pct']:<6} {r['well_trade_pct']:<6} {r['well_body_pct']:<6} {r['abstract_per_1k']:<6} {r['he_start_pct']:<7}")

        print(f"\n\nOUTLIERS (>1.5σ from mean):")
        for ch_key in sorted(outliers.keys()):
            print(f"  {ch_key}:")
            for o in outliers[ch_key]:
                print(f"    {o}")

    # Print Chinese summary
    if results_zh:
        print("\n\nVOICE FINGERPRINT (Chinese — Genre-Agnostic)")
        print("=" * 70)
        if vocab_wells:
            well_names = [f"Well{i+1}" for i in range(len(vocab_wells))]
            print(f"  动态词汇域: {len(vocab_wells)} 个 (来自 output/voice.md Vocabulary Register)")
        else:
            print("  词汇域: 通用中文词频分析 (output/voice.md 未定义 Vocabulary Register)")
        print(f"{'Ch':<8} {'Chars':<7} {'AvgSnt':<7} {'CV':<6} {'Frag%':<7} {'Long%':<7} {'Dial%':<7} {'WellPK':<7} {'AbsPK':<6} {'TrnsPK':<7}")
        for ch in range(1, 25):
            key = f"ch_{ch:02d}"
            if key in results_zh:
                r = results_zh[key]
                print(f"  {ch:<6} {r['char_count']:<7} {r['avg_sentence_length']:<7} {r['sentence_length_cv']:<6} {r['fragments_pct']:<7} {r['long_sentences_pct']:<7} {r['dialogue_ratio']:<7} {r['well_total_per_1k']:<7} {r['abstract_per_1k']:<6} {r['transition_per_1k']:<7}")

        if "novel_average" in results_zh:
            r = results_zh["novel_average"]
            print(f"  {'AVG':<6} {r['char_count']:<7} {r['avg_sentence_length']:<7} {r['sentence_length_cv']:<6} {r['fragments_pct']:<7} {r['long_sentences_pct']:<7} {r['dialogue_ratio']:<7} {r['well_total_per_1k']:<7} {r['abstract_per_1k']:<6} {r['transition_per_1k']:<7}")

        if 'outliers_zh' in dir() and outliers_zh:
            print(f"\n\nOUTLIERS — Chinese (>1.5σ from mean):")
            for ch_key in sorted(outliers_zh.keys()):
                print(f"  {ch_key}:")
                for o in outliers_zh[ch_key]:
                    print(f"    {o}")

    # Save full results
    out_path = BASE_DIR / "edit_logs" / "voice_fingerprint.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "legacy": {"chapters": results, "outliers": outliers} if results else {},
        "chinese": {"chapters": results_zh, "outliers": outliers_zh} if results_zh else {},
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"\nSaved to {out_path}")

if __name__ == "__main__":
    main()
