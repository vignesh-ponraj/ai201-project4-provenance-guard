"""Central configuration: model, storage, scoring weights and thresholds.

Every tunable number that affects a classification lives here so the scoring
behavior is auditable from one place (and matches planning.md §1–§2).
"""
import os
from dotenv import load_dotenv

load_dotenv()

# --- External services -------------------------------------------------------
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
LLM_MODEL = "llama-3.3-70b-versatile"

# --- Storage -----------------------------------------------------------------
DB_PATH = os.getenv("PROVENANCE_DB", "provenance.db")

# --- Signal weights per modality (each must sum to 1.0; planning.md §1) ------
# LLM is by far the most reliable single TEXT signal (cleanly separates the
# calibration set ~0.8 vs ~0.1), so it carries the most weight. The two
# heuristics back it up and, crucially, let us detect disagreement — which is
# what drives confidence down toward "uncertain".
TEXT_SIGNAL_WEIGHTS = {
    "llm": 0.6,
    "stylometry": 0.2,
    "lexical": 0.2,
}

# Image-metadata modality (stretch: multi-modal). An explicit generator
# signature is near-conclusive, so it dominates; camera-plausibility is the
# corroborating structural signal.
IMAGE_SIGNAL_WEIGHTS = {
    "generator": 0.65,
    "camera": 0.35,
}

# Which weight table each content_type uses.
MODALITY_WEIGHTS = {
    "text": TEXT_SIGNAL_WEIGHTS,
    "image_metadata": IMAGE_SIGNAL_WEIGHTS,
}

# Backwards-compatible alias (text was the only modality originally).
SIGNAL_WEIGHTS = TEXT_SIGNAL_WEIGHTS

# --- Confidence + label thresholds (planning.md §2) --------------------------
# Asymmetric on purpose: a false positive (calling a human's work AI) is the
# worst outcome on a writing platform, so the AI bar sits further from center
# (0.62 = 0.12 above the 0.5 fence) than the human bar (0.45 = 0.05 below it).
AI_THRESHOLD = 0.62        # p_ai must be >= this to be called "likely_ai"
HUMAN_THRESHOLD = 0.45     # p_ai must be <= this to be called "likely_human"
MIN_CONFIDENCE = 0.45      # below this, we refuse to commit -> "uncertain"

# Confidence -> human-readable band shown in the label.
CONFIDENCE_BANDS = [
    (0.66, "High"),
    (0.45, "Medium"),
    (0.00, "Low"),
]

# Spread (stdev of the per-signal scores) at which signal agreement hits zero.
AGREEMENT_SPREAD_CAP = 0.35

# --- Rate limiting (planning.md §4 / README) ---------------------------------
SUBMIT_RATE_LIMIT = "10 per minute;100 per day"

# --- Provenance certificate (stretch: verified-human credential) -------------
# Secret used to sign credential tokens (HMAC). In production this would be a
# managed secret; here it falls back to a dev default so the demo runs.
VERIFY_SECRET = os.getenv("VERIFY_SECRET", "provenance-guard-dev-secret")
# The phrase a creator must type back verbatim to complete verification — a
# lightweight presence/attention check that deters trivial scripted sign-ups.
VERIFY_PHRASE = "I am a human creator and this is my original work"
