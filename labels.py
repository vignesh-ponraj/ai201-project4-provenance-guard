"""Map an attribution + confidence to the reader-facing transparency label.

The three exact variants are defined in planning.md §3. Confidence is shown both
as a band word (High/Medium/Low) and a percentage, so it's meaningful to a
non-technical reader. The AI label explicitly invites appeal — honoring the
false-positive asymmetry (calling a human's work AI is the worst outcome).
"""
from config import CONFIDENCE_BANDS


def confidence_band(confidence: float) -> str:
    for threshold, name in CONFIDENCE_BANDS:
        if confidence >= threshold:
            return name
    return "Low"


def make_label(attribution: str, confidence: float) -> dict:
    band = confidence_band(confidence)
    pct = round(confidence * 100)

    if attribution == "likely_ai":
        text = (
            f"⚠ Likely AI-generated. This content shows strong signs of AI "
            f"generation. Several independent checks agreed its style and "
            f"structure closely match AI-written text. Confidence: {band} "
            f"({pct}%). No detector is perfect — if you wrote this yourself, "
            f"you can appeal this label."
        )
    elif attribution == "likely_human":
        text = (
            f"✓ Likely human-written. This content reads as human-written. "
            f"Our checks found the natural variation and individual style typical "
            f"of a human author, with no strong signs of AI generation. "
            f"Confidence: {band} ({pct}%)."
        )
    else:  # uncertain
        text = (
            f"❓ Authorship uncertain. We can't confidently say who wrote "
            f"this. Our checks either disagreed or found only weak signals. "
            f"Confidence: {band} ({pct}%). We've labeled it 'uncertain' rather "
            f"than guess — please treat the result with caution."
        )

    return {"tier": attribution, "band": band, "text": text}
