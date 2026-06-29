"""Provenance Guard — Flask API.

Core endpoints:
  POST /submit  {text|metadata, creator_id, content_type?} -> classify + label
  POST /appeal  {content_id, creator_reasoning}            -> status: under_review
  GET  /log?limit=N                                         -> recent audit entries
  GET  /health                                             -> liveness

Stretch endpoints:
  POST /verify/start    {creator_id}                  -> verification challenge
  POST /verify/complete {challenge_id, typed_phrase}  -> issue verified-human credential
  GET  /creator/<creator_id>/credential               -> credential status / badge
  GET  /analytics                                     -> detection-pattern metrics (JSON)
  GET  /dashboard                                     -> analytics rendered as HTML

Submission flow (planning.md Architecture): rate limit -> per-modality signals
-> scoring -> label -> persist + audit -> respond (with creator badge).
"""
import json
import uuid
from datetime import datetime, timezone

from flask import Flask, jsonify, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

import analytics
import audit
import credentials
import db
from config import MODALITY_WEIGHTS, SUBMIT_RATE_LIMIT
from image_signal import analyze_image_metadata
from labels import make_label
from llm_signal import llm_signal
from lexical_signal import lexical_signal
from scoring import combine
from stylometry_signal import stylometry_signal

app = Flask(__name__)
db.init_db()

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# --- detection pipelines per modality ----------------------------------------
def _run_text_pipeline(text: str):
    """Return (full_signals_with_detail, scores_only)."""
    full = {
        "llm": llm_signal(text),
        "stylometry": stylometry_signal(text),
        "lexical": lexical_signal(text),
    }
    scores = {k: v["ai_likelihood"] for k, v in full.items()}
    return full, scores


def _run_image_pipeline(metadata: dict):
    full = analyze_image_metadata(metadata)
    scores = {k: v["ai_likelihood"] for k, v in full.items()}
    return full, scores


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/submit", methods=["POST"])
@limiter.limit(SUBMIT_RATE_LIMIT)
def submit():
    body = request.get_json(silent=True) or {}
    creator_id = (body.get("creator_id") or "").strip()
    content_type = (body.get("content_type") or "text").strip()

    if not creator_id:
        return jsonify({"error": "'creator_id' is required"}), 400
    if content_type not in MODALITY_WEIGHTS:
        return jsonify({"error": f"unsupported content_type: {content_type}",
                        "supported": list(MODALITY_WEIGHTS)}), 400

    # --- run the modality-appropriate detection pipeline ---------------------
    if content_type == "text":
        text = (body.get("text") or "").strip()
        if not text:
            return jsonify({"error": "'text' is required for content_type=text"}), 400
        full_signals, scores = _run_text_pipeline(text)
        stored_text = text
    else:  # image_metadata
        metadata = body.get("metadata")
        if not isinstance(metadata, dict) or not metadata:
            return jsonify({"error": "'metadata' (object) is required for "
                                     "content_type=image_metadata"}), 400
        full_signals, scores = _run_image_pipeline(metadata)
        stored_text = body.get("text") or json.dumps(metadata, ensure_ascii=False)

    # --- combine -> p_ai, confidence, attribution ----------------------------
    result = combine(scores, MODALITY_WEIGHTS[content_type])
    label = make_label(result["attribution"], result["confidence"])

    content_id = str(uuid.uuid4())
    db.save_content({
        "content_id": content_id,
        "creator_id": creator_id,
        "content_type": content_type,
        "text": stored_text,
        "attribution": result["attribution"],
        "confidence": result["confidence"],
        "p_ai": result["p_ai"],
        "signals": scores,
        "status": "classified",
        "created_at": _utcnow(),
    })
    audit.log_classification(content_id, creator_id, content_type, result, scores)

    # Verified-human badge is creator-identity context; it never overrides the
    # classification above (planning.md / README — provenance certificate).
    badge = credentials.badge_for(creator_id)

    signals_out = {
        name: {"ai_likelihood": res["ai_likelihood"], **res["detail"]}
        for name, res in full_signals.items()
    }
    return jsonify({
        "content_id": content_id,
        "content_type": content_type,
        "attribution": result["attribution"],
        "confidence": result["confidence"],
        "label": label,
        "signals": signals_out,
        "p_ai": result["p_ai"],
        "status": "classified",
        "creator": badge or {"verified_human": False},
    })


@app.route("/appeal", methods=["POST"])
def appeal():
    body = request.get_json(silent=True) or {}
    content_id = (body.get("content_id") or "").strip()
    reasoning = (body.get("creator_reasoning") or "").strip()

    if not content_id:
        return jsonify({"error": "'content_id' is required"}), 400
    if not reasoning:
        return jsonify({"error": "'creator_reasoning' is required"}), 400

    original = db.get_content(content_id)
    if not original:
        return jsonify({"error": f"unknown content_id: {content_id}"}), 404

    db.update_status(content_id, "under_review")
    audit.log_appeal(content_id, reasoning, original)

    return jsonify({
        "content_id": content_id,
        "status": "under_review",
        "message": "Appeal received. This content is now under human review.",
    })


@app.route("/log", methods=["GET"])
def log():
    limit = request.args.get("limit", default=20, type=int)
    return jsonify({"entries": db.recent_audit(limit)})


# --- provenance certificate (stretch) ----------------------------------------
@app.route("/verify/start", methods=["POST"])
def verify_start():
    body = request.get_json(silent=True) or {}
    creator_id = (body.get("creator_id") or "").strip()
    if not creator_id:
        return jsonify({"error": "'creator_id' is required"}), 400
    return jsonify(credentials.start_verification(creator_id))


@app.route("/verify/complete", methods=["POST"])
def verify_complete():
    body = request.get_json(silent=True) or {}
    challenge_id = (body.get("challenge_id") or "").strip()
    typed_phrase = body.get("typed_phrase") or ""
    if not challenge_id:
        return jsonify({"error": "'challenge_id' is required"}), 400

    res = credentials.complete_verification(challenge_id, typed_phrase)
    if not res["ok"]:
        return jsonify({"error": res["error"]}), res["status"]
    return jsonify({
        "verified_human": True,
        "creator_id": res["creator_id"],
        "credential_id": res["credential_id"],
        "verified_at": res["issued_at"],
        "badge": res["badge"]["label"],
        "message": "Verification complete. You are now a Verified Human Creator.",
    })


@app.route("/creator/<creator_id>/credential", methods=["GET"])
def creator_credential(creator_id):
    badge = credentials.badge_for(creator_id)
    if not badge:
        return jsonify({"creator_id": creator_id, "verified_human": False}), 200
    return jsonify({"creator_id": creator_id, **badge})


# --- analytics dashboard (stretch) -------------------------------------------
@app.route("/analytics", methods=["GET"])
def analytics_json():
    return jsonify(analytics.compute())


@app.route("/dashboard", methods=["GET"])
def dashboard():
    return analytics.render_html(analytics.compute())


if __name__ == "__main__":
    # use_reloader=False -> single process (the debug reloader otherwise spawns a
    # child, which complicates clean restarts). Port is overridable; note macOS
    # may run AirPlay Receiver on *:5000, but 127.0.0.1:5000 still resolves here.
    import os
    port = int(os.getenv("PORT", "5000"))
    app.run(host="127.0.0.1", port=port, debug=True, use_reloader=False)
