"""Signal 2 — stylometric burstiness (pure Python, no external libraries).

Captures the *statistical structure* of the text: how much sentence length
varies and how diverse the vocabulary is. Human prose is bursty (long sentences
beside short ones) and lexically varied; AI prose trends uniform. Returns an
AI-likelihood in [0,1] where 1.0 = very AI-like (uniform, mid-diversity).

Blind spot: needs ~40+ words to mean anything; flags terse/repetitive human
writing (poetry) as AI. We surface `reliable` so scoring can react.
"""
import re
from statistics import mean, pstdev

_SENTENCE_SPLIT = re.compile(r"[.!?]+(?:\s+|$)")
_WORD = re.compile(r"[A-Za-z']+")


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]


def _words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def stylometry_signal(text: str) -> dict:
    words = _words(text)
    sentences = _sentences(text)

    if len(words) < 5 or not sentences:
        # Not enough to analyze — stay neutral and flag as unreliable.
        return {
            "ai_likelihood": 0.5,
            "detail": {"reliable": False, "reason": "too short"},
        }

    # --- (a) sentence-length variation -> "burstiness" (primary metric) ------
    lengths = [len(_words(s)) for s in sentences] or [len(words)]
    avg_len = mean(lengths)
    # Coefficient of variation: stdev relative to mean. Human writing is bursty
    # (cv >= ~0.65); AI is uniform (cv <= ~0.25). Linear map between the two.
    cv = (pstdev(lengths) / avg_len) if avg_len and len(lengths) > 1 else 0.0
    burstiness_ai = max(0.0, min(1.0, (0.65 - cv) / (0.65 - 0.25)))

    # --- (b) type-token ratio (vocabulary diversity, secondary metric) -------
    # AI prose clusters in a mid TTR band (~0.45–0.6). Very high TTR is mostly
    # an artifact of SHORT text (every word happens to be unique), so we treat
    # it as weak evidence, not a strong "human" vote. Hence the gentle 0.45
    # half-width and the small 0.25 weight below.
    ttr = len(set(words)) / len(words)
    ttr_ai = 1.0 - min(1.0, abs(ttr - 0.5) / 0.45)

    raw = 0.75 * burstiness_ai + 0.25 * ttr_ai

    # On short text the heuristics are unreliable, so pull the score halfway
    # back to neutral (0.5). This keeps a haiku or terse snippet from producing
    # a confident vote in either direction (planning.md §5, edge case 1).
    reliable = len(words) >= 40
    ai_likelihood = raw if reliable else 0.5 + (raw - 0.5) * 0.5

    return {
        "ai_likelihood": round(ai_likelihood, 4),
        "detail": {
            "reliable": reliable,
            "sentence_count": len(sentences),
            "avg_sentence_len": round(avg_len, 2),
            "length_cv": round(cv, 4),
            "type_token_ratio": round(ttr, 4),
        },
    }


if __name__ == "__main__":  # quick manual check (Milestone 4 verification)
    samples = {
        "ai": "Artificial intelligence represents a transformative paradigm shift. "
              "It is important to note that the benefits are numerous. Furthermore, "
              "stakeholders must collaborate to ensure responsible deployment.",
        "human": "ok so i finally tried that ramen place downtown and honestly? "
                 "underwhelming. the broth was fine but WAY too much sodium and i "
                 "was thirsty for hours. probably won't go back unless dragged.",
    }
    for name, t in samples.items():
        print(name, stylometry_signal(t))
