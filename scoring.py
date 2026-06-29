"""Combine the three signal scores into a single p_ai and an honest confidence,
then map to an attribution tier. Implements planning.md §2 exactly.

Key idea (planning.md §2): confidence is NOT p_ai. It measures how much to trust
the direction p_ai points — driven by how *decisive* the score is and how much
the signals *agree*. Disagreeing signals collapse confidence toward "uncertain".
"""
from statistics import pstdev

from config import (
    AGREEMENT_SPREAD_CAP,
    AI_THRESHOLD,
    HUMAN_THRESHOLD,
    MIN_CONFIDENCE,
    SIGNAL_WEIGHTS,
)


def combine(signals: dict) -> dict:
    """signals: {"llm": x|None, "stylometry": y, "lexical": z} of ai_likelihoods.

    Returns {p_ai, confidence, attribution, used_signals}.
    A None signal (e.g. LLM unavailable) is dropped and its weight redistributed.
    """
    # Keep only available signals; redistribute weights so they still sum to 1.
    available = {k: v for k, v in signals.items() if v is not None}
    if not available:
        # Should never happen (heuristics never return None), but be safe.
        return {"p_ai": 0.5, "confidence": 0.0, "attribution": "uncertain", "used_signals": []}

    total_w = sum(SIGNAL_WEIGHTS[k] for k in available)
    p_ai = sum(SIGNAL_WEIGHTS[k] / total_w * v for k, v in available.items())
    p_ai = round(p_ai, 4)

    # --- confidence (planning.md §2) -----------------------------------------
    # confidence answers "how much should we trust the direction p_ai points?"
    # It combines (a) how far p_ai commits past the 0.5 fence (margin) with
    # (b) how much the signals agree. Disagreeing signals collapse confidence
    # toward "uncertain" even when the combined score looks decisive.
    conviction = p_ai if p_ai >= 0.5 else 1 - p_ai     # in [0.5, 1]
    margin = (conviction - 0.5) / 0.5                  # in [0, 1]
    scores = list(available.values())
    spread = pstdev(scores) if len(scores) > 1 else 0.0
    agreement = 1 - min(1.0, spread / AGREEMENT_SPREAD_CAP)
    confidence = round(agreement * (0.5 + 0.5 * margin), 4)

    attribution = _attribution(p_ai, confidence)
    return {
        "p_ai": p_ai,
        "confidence": confidence,
        "attribution": attribution,
        "used_signals": list(available.keys()),
    }


def _attribution(p_ai: float, confidence: float) -> str:
    """Asymmetric thresholds: harder to be called AI than to be cleared human.

    A definite label needs BOTH a clear p_ai lean past its (asymmetric) bar AND
    enough confidence. Anything else — the dead band in the middle, or a
    confident-looking score the signals disagree on — falls to 'uncertain'.
    """
    if confidence < MIN_CONFIDENCE:
        return "uncertain"
    if p_ai >= AI_THRESHOLD:
        return "likely_ai"
    if p_ai <= HUMAN_THRESHOLD:
        return "likely_human"
    return "uncertain"
