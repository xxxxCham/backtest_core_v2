"""
Analyse statistique des archives live Builder pour extraire le vocabulaire réel
des LLMs (hypothèses, marqueurs, patterns de fuite prompt, accès indicateurs, etc.)
"""
import re
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

ARCHIVES_DIR = Path(
    r"C:\Users\o3-Pro\Documents\backtest_results\_builder_sessions\_live_thoughts_archives"
)

# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

def iter_real_sessions(d: Path):
    """Yield only real session files (exclude test stubs)."""
    for f in sorted(d.glob("2026*.md")):
        yield f


def parse_file(path: Path) -> dict:
    """Parse un fichier archive et retourne les sections utiles."""
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    result = {
        "file": path.name,
        "model": "",
        "objective": "",
        "market": "",
        "hypotheses": [],
        "entry_long": [],
        "entry_short": [],
        "risk_mgmt": [],
        "indicators_used": [],
        "change_types": [],
        "stream_proposal_lines": [],
        "stream_code_lines": [],
        "stream_retry_lines": [],
        "stream_analysis_lines": [],
        "diagnostics": [],
        "analysis_decisions": [],
        "warn_lines": [],
        "info_lines": [],
        "error_lines": [],
        "fallback_lines": [],
    }

    for line in lines:
        stripped = line.strip()

        # Header
        if stripped.startswith("MODELE"):
            result["model"] = stripped.split(":", 1)[-1].strip()
        elif stripped.startswith("OBJECTIF"):
            result["objective"] = stripped.split(":", 1)[-1].strip()
        elif stripped.startswith("MARCHE"):
            result["market"] = stripped.split(":", 1)[-1].strip()

        # PROPOSAL blocks
        elif "Hypothese" in stripped and ":" in stripped:
            h = stripped.split(":", 1)[-1].strip()
            if h:
                result["hypotheses"].append(h)
        elif "Long" in stripped and ":" in stripped and "[PROPOSAL]" not in stripped:
            result["entry_long"].append(stripped.split(":", 1)[-1].strip())
        elif "Short" in stripped and ":" in stripped and "[PROPOSAL]" not in stripped:
            result["entry_short"].append(stripped.split(":", 1)[-1].strip())
        elif "Risque" in stripped and ":" in stripped:
            result["risk_mgmt"].append(stripped.split(":", 1)[-1].strip())
        elif "Indicateurs" in stripped and ":" in stripped:
            inds = stripped.split(":", 1)[-1].strip()
            result["indicators_used"].append(inds)
        elif "Change type" in stripped and ":" in stripped:
            result["change_types"].append(stripped.split(":", 1)[-1].strip())

        # STREAM lines
        elif "[STREAM] IDEA" in stripped or "[STREAM] LIVE proposal" in stripped:
            content = stripped.split(" - ", 1)[-1] if " - " in stripped else ""
            result["stream_proposal_lines"].append(content)
        elif "[STREAM] CODE" in stripped:
            content = stripped.split(" - ", 1)[-1] if " - " in stripped else ""
            result["stream_code_lines"].append(content)
        elif "[STREAM] RETRY" in stripped:
            content = stripped.split(" - ", 1)[-1] if " - " in stripped else ""
            result["stream_retry_lines"].append(content)
        elif "[STREAM] ANALYSE" in stripped or "[ANALYSE]" in stripped:
            content = stripped.split(" - ", 1)[-1] if " - " in stripped else stripped
            result["stream_analysis_lines"].append(content)

        # Diagnostics, warnings, errors
        elif "[DIAG]" in stripped:
            result["diagnostics"].append(stripped)
        elif "[WARN]" in stripped:
            result["warn_lines"].append(stripped)
        elif "[INFO]" in stripped:
            result["info_lines"].append(stripped)
        elif "[ERROR]" in stripped:
            result["error_lines"].append(stripped)
        elif "fallback" in stripped.lower() or "Fallback" in stripped:
            result["fallback_lines"].append(stripped)

    return result


# ---------------------------------------------------------------------------
# Analysis functions
# ---------------------------------------------------------------------------

def analyze_hypotheses(sessions: List[dict]) -> dict:
    """Analyse le vocabulaire des hypothèses."""
    all_hypotheses = []
    for s in sessions:
        all_hypotheses.extend(s["hypotheses"])

    # Word frequency (lowercase)
    word_counter = Counter()
    bigram_counter = Counter()
    for h in all_hypotheses:
        words = re.findall(r"[a-zA-ZÀ-ÿ]{3,}", h.lower())
        word_counter.update(words)
        for i in range(len(words) - 1):
            bigram_counter[(words[i], words[i + 1])] += 1

    # Placeholder / filler detection
    placeholder_patterns = []
    filler_re = re.compile(
        r"(ajustement structurel|diagnostic pr[eé]c[eé]dent|fallback contractuel|"
        r"proposition g[eé]n[eé]r[eé]e automatiquement|maintenir la progression|"
        r"sortie llm|pas exploitable|structural adjustment|based on previous|"
        r"automatically generated|placeholder|generic|default strategy|"
        r"simple strategy|basic approach)",
        re.IGNORECASE,
    )
    for h in all_hypotheses:
        if filler_re.search(h):
            placeholder_patterns.append(h[:120])

    return {
        "total_hypotheses": len(all_hypotheses),
        "unique_hypotheses": len(set(all_hypotheses)),
        "top_50_words": word_counter.most_common(50),
        "top_30_bigrams": [(f"{a} {b}", c) for (a, b), c in bigram_counter.most_common(30)],
        "placeholder_count": len(placeholder_patterns),
        "placeholder_samples": placeholder_patterns[:10],
    }


def analyze_entry_logic(sessions: List[dict]) -> dict:
    """Analyse les patterns d'entrée long/short."""
    long_patterns = []
    short_patterns = []
    for s in sessions:
        long_patterns.extend(s["entry_long"])
        short_patterns.extend(s["entry_short"])

    # Extract indicator references from logic
    indicator_re = re.compile(r"\b([a-z_]+)\s*[<>=!]|\b([a-z_]+)\s+crosses?\b|\bindicators?\[.([a-z_]+).\]", re.I)

    long_indicators = Counter()
    short_indicators = Counter()
    for p in long_patterns:
        for m in indicator_re.finditer(p):
            ind = m.group(1) or m.group(2) or m.group(3)
            if ind:
                long_indicators[ind.lower()] += 1
    for p in short_patterns:
        for m in indicator_re.finditer(p):
            ind = m.group(1) or m.group(2) or m.group(3)
            if ind:
                short_indicators[ind.lower()] += 1

    # Direction markers
    direction_words_long = Counter()
    direction_words_short = Counter()
    dir_re_long = re.compile(
        r"\b(haussier|bullish|long|buy|acheter|hausse|monte|supérieur|above|upward|achat)\b", re.I
    )
    dir_re_short = re.compile(
        r"\b(baissier|bearish|short|sell|vendre|baisse|descend|inférieur|below|downward|vente)\b", re.I
    )
    for p in long_patterns:
        direction_words_long.update(m.group().lower() for m in dir_re_long.finditer(p))
    for p in short_patterns:
        direction_words_short.update(m.group().lower() for m in dir_re_short.finditer(p))

    return {
        "total_long": len(long_patterns),
        "total_short": len(short_patterns),
        "long_indicators_freq": long_indicators.most_common(20),
        "short_indicators_freq": short_indicators.most_common(20),
        "direction_in_long": direction_words_long.most_common(20),
        "direction_in_short": direction_words_short.most_common(20),
        "sample_long": long_patterns[:15],
        "sample_short": short_patterns[:15],
    }


def analyze_stream_leakage(sessions: List[dict]) -> dict:
    """Detect prompt leakage / reasoning-out-loud in STREAM lines."""
    all_stream = []
    for s in sessions:
        all_stream.extend(s["stream_code_lines"])
        all_stream.extend(s["stream_retry_lines"])

    leakage_patterns = Counter()
    leakage_re_en = re.compile(
        r"(let me think|let me start|looking back|wait,? no|wait,? maybe|"
        r"so perhaps|i need to|i should|the user|looking at|but in the|"
        r"so the required|so in the|perhaps also|additionally|"
        r"now,? the|next,? the|these are just examples|"
        r"first,? the|okay,? i|from the problem|the focus is on|"
        r"here'?s a completed|here is the|voici la version|"
        r"i have included|note that this|"
        r"the user must be able|the strategy seems|"
        r"i don'?t see those|so maybe i should|"
        r"but let me think|for example,? if)",
        re.IGNORECASE,
    )
    leakage_re_fr = re.compile(
        r"(laissez-moi|permettez-moi|je vais|commençons par|"
        r"d'?abord|premièrement|réfléchissons|"
        r"il faut que|n'?oublie pas|voyons|attendez|"
        r"en fait|par exemple|regardons|"
        r"voici le code|code corrigé|ci-dessous|"
        r"il semble que|dans ce cas)",
        re.IGNORECASE,
    )

    en_matches = []
    fr_matches = []
    for line in all_stream:
        for m in leakage_re_en.finditer(line):
            leakage_patterns[m.group().lower()] += 1
            en_matches.append(m.group().lower())
        for m in leakage_re_fr.finditer(line):
            leakage_patterns[m.group().lower()] += 1
            fr_matches.append(m.group().lower())

    # Natural language lines (non-code lines in code stream)
    nl_lines = []
    code_indicator = re.compile(r"(def |class |import |return |if |for |while |=\s|np\.|pd\.|\.iloc|\.values)")
    for line in all_stream:
        if line and not code_indicator.search(line) and len(line) > 20:
            nl_lines.append(line[:150])

    return {
        "total_stream_lines": len(all_stream),
        "leakage_freq": leakage_patterns.most_common(30),
        "en_leakage_samples": list(set(en_matches))[:20],
        "fr_leakage_samples": list(set(fr_matches))[:20],
        "natural_language_in_code_count": len(nl_lines),
        "nl_samples": nl_lines[:30],
    }


def analyze_indicator_access_patterns(sessions: List[dict]) -> dict:
    """Analyse les patterns d'accès aux indicateurs dans le code stream."""
    all_code = []
    for s in sessions:
        all_code.extend(s["stream_code_lines"])
        all_code.extend(s["stream_retry_lines"])

    # indicators["xxx"] and indicators["xxx"]["yyy"]
    dict_access = Counter()
    dict_access_re = re.compile(r'indicators\[.(\w+).\](?:\[.(\w+).\])?')
    for line in all_code:
        for m in dict_access_re.finditer(line):
            key = m.group(1)
            subkey = m.group(2)
            if subkey:
                dict_access[f'{key}.{subkey}'] += 1
            else:
                dict_access[key] += 1

    # Dot-notation access (the bug pattern)
    dot_access = Counter()
    dot_re = re.compile(r'\b(\w+)\.(upper|lower|middle|tenkan|kijun|senkou_a|senkou_b|'
                        r'chikou|span_a|span_b|direction|supertrend|signal|histogram|'
                        r'adx|plus_di|minus_di|swing_high|swing_low|r1|s1|r2|s2|'
                        r'net_bias|smart_leg_bullish|smart_leg_bearish|'
                        r'fast_k|fast_d|slowk|slowd|macd_line|signal_line)\b')
    for line in all_code:
        for m in dot_re.finditer(line):
            dot_access[f'{m.group(1)}.{m.group(2)}'] += 1

    # ParameterSpec patterns
    param_spec_patterns = Counter()
    ps_re = re.compile(r'ParameterSpec\(([^)]+)\)')
    for line in all_code:
        for m in ps_re.finditer(line):
            param_spec_patterns[m.group(1)[:80]] += 1

    return {
        "dict_access_top30": dict_access.most_common(30),
        "dot_access_top30": dot_access.most_common(30),
        "param_spec_samples": param_spec_patterns.most_common(15),
    }


def analyze_diagnostics_and_decisions(sessions: List[dict]) -> dict:
    """Analyse les diagnostics et décisions d'analyse."""
    all_diag = []
    all_analysis = []
    all_warn = []
    all_error = []
    all_fallback = []
    for s in sessions:
        all_diag.extend(s["diagnostics"])
        all_analysis.extend(s["stream_analysis_lines"])
        all_warn.extend(s["warn_lines"])
        all_error.extend(s["error_lines"])
        all_fallback.extend(s["fallback_lines"])

    # Diagnostic categories
    diag_cats = Counter()
    diag_re = re.compile(r'\[DIAG\]\s*(\w+)')
    for d in all_diag:
        m = diag_re.search(d)
        if m:
            diag_cats[m.group(1)] += 1

    # Analysis decisions
    decision_re = re.compile(r'decision=(\w+)')
    decisions = Counter()
    for a in all_analysis:
        m = decision_re.search(a)
        if m:
            decisions[m.group(1)] += 1

    return {
        "diagnostic_categories": diag_cats.most_common(20),
        "analysis_decisions": decisions.most_common(10),
        "warn_count": len(all_warn),
        "error_count": len(all_error),
        "fallback_count": len(all_fallback),
        "warn_samples": all_warn[:10],
        "error_samples": all_error[:10],
        "fallback_samples": all_fallback[:10],
    }


def analyze_risk_management(sessions: List[dict]) -> dict:
    """Analyse le vocabulaire de gestion du risque."""
    all_risk = []
    for s in sessions:
        all_risk.extend(s["risk_mgmt"])

    word_counter = Counter()
    for r in all_risk:
        words = re.findall(r"[a-zA-ZÀ-ÿ_-]{3,}", r.lower())
        word_counter.update(words)

    # ATR patterns
    atr_patterns = Counter()
    atr_re = re.compile(r'(\d+\.?\d*)\s*x?\s*atr', re.I)
    for r in all_risk:
        for m in atr_re.finditer(r):
            atr_patterns[f"{m.group(1)}x ATR"] += 1

    return {
        "total_risk_entries": len(all_risk),
        "top_words": word_counter.most_common(30),
        "atr_multipliers": atr_patterns.most_common(10),
        "samples": all_risk[:15],
    }


def analyze_models_and_objectives(sessions: List[dict]) -> dict:
    """Répartition par modèle et type d'objectif."""
    model_counter = Counter()
    obj_lang = Counter()
    for s in sessions:
        model_counter[s["model"] or "unknown"] += 1
        obj = s["objective"]
        if re.search(r"[àâéèêëïîôùûüçœæ]|(?:stratégie|indicateur|acheter|vendre)", obj, re.I):
            obj_lang["FR"] += 1
        elif obj:
            obj_lang["EN"] += 1

    return {
        "models": model_counter.most_common(10),
        "objective_language": dict(obj_lang),
    }


def analyze_indicators_requested(sessions: List[dict]) -> dict:
    """Quels indicateurs sont réellement demandés et utilisés."""
    all_inds = Counter()
    for s in sessions:
        for ind_line in s["indicators_used"]:
            for ind in re.split(r"[,\s]+", ind_line):
                ind = ind.strip().lower()
                if ind and len(ind) > 1:
                    all_inds[ind] += 1

    return {
        "indicator_frequency": all_inds.most_common(30),
    }


def analyze_repetition_patterns(sessions: List[dict]) -> dict:
    """Détecte les patterns de répétition/boucle dans les streams."""
    repetition_events = []
    for s in sessions:
        for line in s["info_lines"]:
            if "répétition" in line.lower() or "repetition" in line.lower():
                repetition_events.append({"file": s["file"], "line": line[:120]})

    # Count models with repetition
    model_rep = Counter()
    for s in sessions:
        has_rep = any("répétition" in l.lower() or "repetition" in l.lower() for l in s["info_lines"])
        if has_rep:
            model_rep[s["model"]] += 1

    return {
        "total_repetition_events": len(repetition_events),
        "by_model": model_rep.most_common(10),
        "samples": repetition_events[:10],
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    files = list(iter_real_sessions(ARCHIVES_DIR))
    print(f"=== Analyse de {len(files)} fichiers d'archives live ===\n")

    sessions = [parse_file(f) for f in files]

    report = {}

    print("1. Modèles et objectifs...")
    report["models_objectives"] = analyze_models_and_objectives(sessions)

    print("2. Hypothèses...")
    report["hypotheses"] = analyze_hypotheses(sessions)

    print("3. Entry logic...")
    report["entry_logic"] = analyze_entry_logic(sessions)

    print("4. Indicateurs demandés...")
    report["indicators_requested"] = analyze_indicators_requested(sessions)

    print("5. Patterns d'accès indicateurs dans le code...")
    report["indicator_access"] = analyze_indicator_access_patterns(sessions)

    print("6. Fuites de prompt / raisonnement à voix haute...")
    report["stream_leakage"] = analyze_stream_leakage(sessions)

    print("7. Diagnostics et décisions...")
    report["diagnostics_decisions"] = analyze_diagnostics_and_decisions(sessions)

    print("8. Gestion du risque...")
    report["risk_management"] = analyze_risk_management(sessions)

    print("9. Patterns de répétition...")
    report["repetition"] = analyze_repetition_patterns(sessions)

    # Serialize
    output_path = Path(__file__).parent / "archive_analysis_report.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nRapport JSON sauvegardé : {output_path}")

    # Console summary
    print("\n" + "=" * 72)
    print("RESUME")
    print("=" * 72)

    mo = report["models_objectives"]
    print(f"\nModèles utilisés ({len(mo['models'])}) :")
    for m, c in mo["models"]:
        print(f"  {m:40s} {c:3d} sessions")
    print(f"Langue objectifs : {mo['objective_language']}")

    h = report["hypotheses"]
    print(f"\nHypothèses : {h['total_hypotheses']} total, {h['unique_hypotheses']} uniques")
    print(f"  Placeholders détectés : {h['placeholder_count']}")
    print(f"  Top 20 mots :")
    for w, c in h["top_50_words"][:20]:
        print(f"    {w:25s} {c:4d}")

    el = report["entry_logic"]
    print(f"\nLogique d'entrée : {el['total_long']} long, {el['total_short']} short")
    print(f"  Indicateurs les plus référencés (long) :")
    for w, c in el["long_indicators_freq"][:10]:
        print(f"    {w:20s} {c:4d}")
    print(f"  Mots directionnels dans long :")
    for w, c in el["direction_in_long"][:10]:
        print(f"    {w:20s} {c:4d}")
    print(f"  Mots directionnels dans short :")
    for w, c in el["direction_in_short"][:10]:
        print(f"    {w:20s} {c:4d}")

    ir = report["indicators_requested"]
    print(f"\nIndicateurs demandés dans proposals :")
    for w, c in ir["indicator_frequency"][:15]:
        print(f"    {w:20s} {c:4d}")

    ia = report["indicator_access"]
    print(f"\nAccès dict indicators[] dans le code :")
    for w, c in ia["dict_access_top30"][:15]:
        print(f"    {w:35s} {c:4d}")
    print(f"  Accès dot-notation (pattern de bug) :")
    for w, c in ia["dot_access_top30"][:15]:
        print(f"    {w:35s} {c:4d}")

    sl = report["stream_leakage"]
    print(f"\nFuites de prompt / NL dans code : {sl['natural_language_in_code_count']} lignes NL")
    print(f"  Patterns de fuite détectés :")
    for w, c in sl["leakage_freq"][:15]:
        print(f"    {w:40s} {c:4d}")

    dd = report["diagnostics_decisions"]
    print(f"\nDiagnostics :")
    for w, c in dd["diagnostic_categories"][:10]:
        print(f"    {w:25s} {c:4d}")
    print(f"  Décisions d'analyse :")
    for w, c in dd["analysis_decisions"]:
        print(f"    {w:15s} {c:4d}")
    print(f"  Warnings: {dd['warn_count']}, Errors: {dd['error_count']}, Fallbacks: {dd['fallback_count']}")

    rm = report["risk_management"]
    print(f"\nGestion du risque : {rm['total_risk_entries']} entrées")
    print(f"  Top mots :")
    for w, c in rm["top_words"][:15]:
        print(f"    {w:20s} {c:4d}")
    print(f"  Multiplicateurs ATR :")
    for w, c in rm["atr_multipliers"]:
        print(f"    {w:15s} {c:4d}")

    rp = report["repetition"]
    print(f"\nBoucles de répétition : {rp['total_repetition_events']} événements")
    for m, c in rp["by_model"]:
        print(f"    {m:40s} {c:3d}")

    print("\n✅ Analyse terminée.")


if __name__ == "__main__":
    main()
