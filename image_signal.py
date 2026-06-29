"""Image-metadata modality (stretch: multi-modal support).

Provenance Guard's text pipeline can't analyze an image, but it *can* analyze the
structured metadata that travels with one. This module provides two independent
signals over a metadata dict, mirroring the text pipeline's contract
(ai_likelihood in [0,1], 1.0 = AI-generated):

  1. generator-signature — explicit markers of an AI image tool (software field,
     C2PA / provenance assertions, prompt fields). Near-conclusive when present.
  2. camera-plausibility — presence of real-capture EXIF (camera make/model,
     ISO, exposure, lens, GPS). A genuine photo carries these; an AI image
     almost never does, so their absence is (weak) evidence of generation.

Expected metadata shape (all fields optional) — what a platform would extract
from an upload's EXIF / XMP / C2PA:
  {
    "software": "Adobe Firefly", "generator": "...", "prompt": "...",
    "c2pa": {"ai_generated": true},
    "camera_make": "Canon", "camera_model": "EOS R6", "iso": 400,
    "exposure_time": "1/200", "f_number": 2.8, "lens_model": "...",
    "gps": {...}
  }

Blind spot: metadata is trivially strippable or forgeable. Absent metadata is
ambiguous (could be a scrubbed-but-real photo), which is exactly why the camera
signal contributes weakly and the system leans 'uncertain' when nothing is known.
"""
from __future__ import annotations

# Substrings that, in a software/generator/tool field, indicate AI generation.
_AI_TOOLS = [
    "midjourney", "dall-e", "dall·e", "dalle", "stable diffusion", "sdxl",
    "firefly", "imagen", "flux", "leonardo", "nightcafe", "gan",
    "generative", "ai generated", "ai-generated", "text-to-image",
]

# EXIF fields a real camera/phone capture typically carries.
_CAMERA_FIELDS = [
    "camera_make", "camera_model", "iso", "exposure_time", "f_number",
    "focal_length", "lens_model", "gps",
]


def _as_text(value) -> str:
    return str(value).lower() if value is not None else ""


def generator_signature_signal(meta: dict) -> dict:
    """Explicit AI-tool markers in software/generator/prompt/C2PA fields."""
    hay = " ".join(_as_text(meta.get(k)) for k in ("software", "generator", "tool", "prompt"))
    tool_hits = [t for t in _AI_TOOLS if t in hay]

    c2pa = meta.get("c2pa") or {}
    c2pa_ai = bool(c2pa.get("ai_generated")) if isinstance(c2pa, dict) else False
    has_prompt = bool(_as_text(meta.get("prompt")).strip())

    if c2pa_ai or tool_hits:
        ai = 0.97                       # explicit signature → near-certain AI
    elif has_prompt:
        ai = 0.8                        # a generation prompt is strong evidence
    else:
        ai = 0.35                       # no signature: mild lean human, but unsure
                                        # (absence of AI markers isn't proof —
                                        #  metadata is strippable/forgeable)

    return {
        "ai_likelihood": ai,
        "detail": {
            "ai_tool_matches": tool_hits,
            "c2pa_ai_generated": c2pa_ai,
            "has_prompt_field": has_prompt,
        },
    }


def camera_plausibility_signal(meta: dict) -> dict:
    """Presence of real-capture EXIF → human photo; absence → leans AI."""
    present = [f for f in _CAMERA_FIELDS if meta.get(f) not in (None, "", {})]
    coverage = len(present) / len(_CAMERA_FIELDS)
    # Rich camera EXIF (coverage ~1) → strongly human (ai ~0.05);
    # no camera fields at all (coverage 0) → leans AI (ai ~0.75) but not certain.
    ai = 0.75 - 0.70 * coverage
    return {
        "ai_likelihood": round(ai, 4),
        "detail": {
            "camera_fields_present": present,
            "coverage": round(coverage, 3),
        },
    }


def analyze_image_metadata(meta: dict) -> dict:
    """Run both image signals; returns {signal_name: result_dict}."""
    return {
        "generator": generator_signature_signal(meta),
        "camera": camera_plausibility_signal(meta),
    }


if __name__ == "__main__":
    ai_img = {"software": "Midjourney v6", "prompt": "a cat astronaut, cinematic"}
    real_img = {"camera_make": "Canon", "camera_model": "EOS R6", "iso": 400,
                "exposure_time": "1/200", "f_number": 2.8, "lens_model": "RF50"}
    print("ai_img  ", analyze_image_metadata(ai_img))
    print("real_img", analyze_image_metadata(real_img))
