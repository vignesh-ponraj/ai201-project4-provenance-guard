"""Signal 3 — lexical fingerprint (stretch: ensemble 3rd signal, pure Python).

Captures *surface lexical patterns* that instruction-tuned models over-produce:
boilerplate connective phrases, formulaic sentence openers, and uniform
punctuation. Distinct from the LLM (semantic) and stylometry (statistical)
families. Returns an AI-likelihood in [0,1].

Blind spot: a human deliberately writing formal/academic prose trips it; trivial
to evade by paraphrase.
"""
import re

_WORD = re.compile(r"[A-Za-z']+")
_SENTENCE_SPLIT = re.compile(r"[.!?]+(?:\s+|$)")

# Phrases AI assistants lean on far more than individual humans.
_TELL_PHRASES = [
    "it is important to note", "it's important to note", "it is worth noting",
    "furthermore", "moreover", "in conclusion", "overall", "in summary",
    "on the other hand", "as a result", "in today's world", "navigate the",
    "delve into", "tapestry", "realm of", "plays a crucial role",
    "plays a vital role", "a wide range of", "it is essential", "ensure that",
    "when it comes to", "the world of", "a testament to", "rich history",
]


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]


def lexical_signal(text: str) -> dict:
    lower = text.lower()
    words = _WORD.findall(lower)
    sentences = _sentences(text)
    n_words = max(1, len(words))

    # --- (a) AI "tell" phrase density (per 100 words) ------------------------
    hits = sum(lower.count(p) for p in _TELL_PHRASES)
    per_100 = hits / n_words * 100
    # 0 hits -> 0.0; ~2+ tells per 100 words -> saturated 1.0.
    tell_ai = min(1.0, per_100 / 2.0)

    # --- (b) sentence-opener diversity ---------------------------------------
    openers = [
        (_WORD.findall(s.lower()) or [""])[0] for s in sentences
    ]
    if len(openers) >= 2:
        opener_diversity = len(set(openers)) / len(openers)
        # Low diversity (repeated openers) reads more formulaic/AI.
        opener_ai = 1.0 - opener_diversity
    else:
        opener_ai = 0.5  # neutral when too few sentences

    # --- (c) punctuation variety ---------------------------------------------
    # Humans use a mix (?, !, —, ...); flat all-period text reads more AI.
    punct = [c for c in text if c in "?!;:—-…()\"'"]
    punct_variety = len(set(punct))
    punct_ai = 1.0 - min(1.0, punct_variety / 4.0)

    ai_likelihood = round(0.5 * tell_ai + 0.3 * opener_ai + 0.2 * punct_ai, 4)
    return {
        "ai_likelihood": ai_likelihood,
        "detail": {
            "tell_phrase_hits": hits,
            "tells_per_100w": round(per_100, 3),
            "opener_diversity": round(1.0 - opener_ai, 3) if len(openers) >= 2 else None,
            "punctuation_variety": punct_variety,
        },
    }


if __name__ == "__main__":
    ai = ("Artificial intelligence represents a transformative paradigm shift. "
          "It is important to note that the benefits are numerous. Furthermore, "
          "stakeholders must collaborate. In conclusion, we must ensure that "
          "responsible deployment plays a crucial role.")
    human = ("ok so i finally tried that ramen place — honestly? underwhelming! "
             "broth was fine but WAY too salty... won't go back (unless dragged).")
    print("ai   ", lexical_signal(ai))
    print("human", lexical_signal(human))
