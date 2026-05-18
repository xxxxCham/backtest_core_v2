"""Module-ID: agents.builder_model_profiles

Purpose: Profils de guidage mono-LLM pour le Strategy Builder.

Role in pipeline: prompt shaping / génération mono-LLM

Dependencies: utils.model_loader.normalize_model_name

Read-if: Vous voulez adapter les garde-fous de génération à un modèle précis.

Skip-if: Vous modifiez seulement le runtime ou le backtest.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from utils.model_loader import normalize_model_name

BuilderPromptPhase = Literal["proposal", "code"]


@dataclass(frozen=True)
class BuilderModelPromptProfile:
    model_name: str
    rationale: str
    proposal_rules: tuple[str, ...] = ()
    code_rules: tuple[str, ...] = ()


_MONO_LLM_MODEL_PROFILES: dict[str, BuilderModelPromptProfile] = {
    "qwen3.6:35b": BuilderModelPromptProfile(
        model_name="qwen3.6:35b",
        rationale="Observed mono-LLM failures are dominated by Python syntax drift, especially incomplete or over-nested blocks.",
        proposal_rules=(
            "Keep the proposal JSON compact and explicit; one concrete hypothesis is better than long narrative text.",
            "Prefer one primary setup with a small number of hard filters instead of stacking many optional conditions.",
        ),
        code_rules=(
            "Prefer short, flat Python blocks with boolean masks over nested conditional trees.",
            "Never leave an if/elif/else branch empty, partial, or implied; remove the branch if it is not strictly required.",
            "Reuse simple local variables already defined in the preamble instead of introducing many new aliases.",
        ),
    ),
    "gemma4:26b": BuilderModelPromptProfile(
        model_name="gemma4:26b",
        rationale="Observed mono-LLM failures are dominated by undefined local variables and Builder-contract violations.",
        proposal_rules=(
            "Prefer stable indicator combinations and avoid proposing helper concepts that are not direct indicators or parameters.",
        ),
        code_rules=(
            "Every local variable must be defined before first use; never reference helper aliases that were not assigned explicitly in the previous lines.",
            "Do not use while loops, indexed .iloc[i] access, or custom state machines; keep the implementation fully vectorized.",
            "Prefer direct names from the indicator contract and params dict instead of inventing shorthand names mid-function.",
        ),
    ),
    "deepseek-r1:32b": BuilderModelPromptProfile(
        model_name="deepseek-r1:32b",
        rationale="Observed mono-LLM failures are dominated by incorrect access to dict-based indicators and invalid indicator sub-keys.",
        proposal_rules=(
            "Keep the indicator set compact when dict-based indicators are involved, and avoid mixing too many advanced indicators in one idea.",
        ),
        code_rules=(
            "For every dict indicator, always read a valid sub-key from the contract before any comparison or np.nan_to_num call.",
            "Never invent sub-keys such as macd['line'], swing compared directly, or markov_switching used without an explicit field.",
            "If an indicator is documented as a plain array, use it directly and never treat it like a dict.",
        ),
    ),
    "lfm2:24b": BuilderModelPromptProfile(
        model_name="lfm2:24b",
        rationale="Observed mono-LLM failures are dominated by violations of the signals contract, especially 2D/DataFrame-like writes.",
        proposal_rules=(
            "Think in terms of one executable signal stream only: long_mask activates +1.0 and short_mask activates -1.0 on the same 1D series.",
        ),
        code_rules=(
            "signals must remain a 1D pd.Series from start to finish; never treat it like a DataFrame with long/short columns.",
            "Never write signals.loc[mask, 'long'] or signals.loc[mask, 'short']; always use full-length boolean masks then signals[mask] = 1.0 or -1.0.",
            "Define long_mask and short_mask explicitly as full-length boolean arrays before assigning entries.",
        ),
    ),
    "deepseek-moe-16b-local:latest": BuilderModelPromptProfile(
        model_name="deepseek-moe-16b-local:latest",
        rationale="Observed mono-LLM failures include hallucinated pseudo-indicators that do not exist in the Builder registry.",
        proposal_rules=(
            "Every used_indicators entry must be copied verbatim from the available registry list; never invent pseudo-features such as price or raw volume.",
        ),
        code_rules=(
            "Use only registry indicators exposed by required_indicators; price comes from df columns, not from indicators['price'] or similar pseudo-indicators.",
        ),
    ),
    "qwen3.6:27b": BuilderModelPromptProfile(
        model_name="qwen3.6:27b",
        rationale=(
            "Dense 27B with top-tier agentic coding (SWE-bench Verified 77.2%) and integrated reasoning. "
            "Primary observed risks: semantic comparisons on dict indicators ('supertrend == bullish'), "
            "invented sub-keys on plain arrays (tsi 'signal' line), over-engineered conditional cascades "
            "that dilute the trading edge. Repair pipeline auto-fixes string comparisons and injects "
            "derived signals — emphasize trusting the contracts and keeping logic flat."
        ),
        proposal_rules=(
            "Trust the indicator contracts in 'Critical Contracts': supertrend.direction is INT, markov_switching.regime is INT, tsi is a 1D array (no signal sub-key).",
            "Express ONE strong hypothesis with 2-3 hard filters at most; avoid stacking 5+ optional conditions that erode the edge.",
            "Use stable indicator names from the registry verbatim; do not invent helper indicators or pseudo-features.",
            "Reasoning is integrated — be concise in the proposal JSON, the model already deliberates internally.",
        ),
        code_rules=(
            "supertrend['direction'] is INT 1 (bullish) / -1 (bearish). NEVER write supertrend == 'bullish' or direction == 'bear'; use indicators['supertrend']['direction'] == 1 / == -1.",
            "markov_switching['regime'] is INT (0/1). NEVER compare to strings ('bull', 'risk_on'); use indicators['markov_switching']['regime'] == 1.",
            "tsi has NO 'signal' sub-key. If a TSI cross is needed, the names tsi_signal / tsi_crosses_above_signal / tsi_crosses_below_signal are AUTO-INJECTED by the repair pipeline — use them directly without re-implementing.",
            "Prefer flat boolean masks (long_mask, short_mask) over nested if/elif/else cascades; the runtime consumes a 1D signals pd.Series.",
            "Vectorize fully: no for-loops over df.iloc[i], no while loops, no per-bar Python state machines.",
            "Define every local variable before first use; do not reference helper aliases that were not assigned by the preamble or by your own previous lines.",
        ),
    ),
}


def resolve_builder_model_prompt_profile(model_name: str | None) -> BuilderModelPromptProfile | None:
    normalized_model_name = normalize_model_name(str(model_name or "").strip())
    if not normalized_model_name:
        return None
    return _MONO_LLM_MODEL_PROFILES.get(normalized_model_name)


def build_builder_model_prompt_guidance(
    model_name: str | None,
    *,
    phase: BuilderPromptPhase,
    builder_execution_mode: str = "",
) -> dict[str, Any]:
    normalized_execution_mode = str(builder_execution_mode or "").strip().lower()
    if normalized_execution_mode != "mono_single_llm":
        return {
            "mono_llm_profile_active": False,
            "mono_llm_model_name": "",
            "mono_llm_profile_rationale": "",
            "mono_llm_profile_rules": [],
        }

    profile = resolve_builder_model_prompt_profile(model_name)
    if profile is None:
        return {
            "mono_llm_profile_active": False,
            "mono_llm_model_name": normalize_model_name(str(model_name or "").strip()) or str(model_name or "").strip(),
            "mono_llm_profile_rationale": "",
            "mono_llm_profile_rules": [],
        }

    rules = list(profile.proposal_rules if phase == "proposal" else profile.code_rules)
    return {
        "mono_llm_profile_active": bool(rules),
        "mono_llm_model_name": profile.model_name,
        "mono_llm_profile_rationale": profile.rationale,
        "mono_llm_profile_rules": rules,
    }
