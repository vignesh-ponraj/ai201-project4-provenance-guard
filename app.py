"""Provenance Guard — Flask API.

Endpoints:
  POST /submit  {text, creator_id}        -> classify + transparency label
  POST /appeal  {content_id, creator_reasoning} -> flip status to under_review
  GET  /log?limit=N                       -> recent audit entries
  GET  /health                            -> liveness

The submission flow (planning.md Architecture): rate limit -> 3 signals ->
scoring -> label -> persist + audit -> respond.
"""
import uuid
from datetime import datetime, timezone

from flask import Flask, jsonify, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

import audit
import db
from config import SUBMIT_RATE_LIMIT
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


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/submit", methods=["POST"])
@limiter.limit(SUBMIT_RATE_LIMIT)
def submit():
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()
    creator_id = (body.get("creator_id") or "").strip()

    if not text:
        return jsonify({"error": "'text' is required"}), 400
    if not creator_id:
        return jsonify({"error": "'creator_id' is required"}), 400

    # --- run the three detection signals -------------------------------------
    llm = llm_signal(text)
    style = stylometry_signal(text)
    lexical = lexical_signal(text)
    signal_scores = {
        "llm": llm["ai_likelihood"],
        "stylometry": style["ai_likelihood"],
        "lexical": lexical["ai_likelihood"],
    }

    # --- combine -> p_ai, confidence, attribution ----------------------------
    result = combine(signal_scores)
    label = make_label(result["attribution"], result["confidence"])

    content_id = str(uuid.uuid4())
    db.save_content({
        "content_id": content_id,
        "creator_id": creator_id,
        "text": text,
        "attribution": result["attribution"],
        "confidence": result["confidence"],
        "p_ai": result["p_ai"],
        "llm_score": signal_scores["llm"],
        "style_score": signal_scores["stylometry"],
        "lexical_score": signal_scores["lexical"],
        "status": "classified",
        "created_at": _utcnow(),
    })
    audit.log_classification(content_id, creator_id, result, signal_scores)

    return jsonify({
        "content_id": content_id,
        "attribution": result["attribution"],
        "confidence": result["confidence"],
        "label": label,
        "signals": {
            "llm": {"ai_likelihood": llm["ai_likelihood"], **llm["detail"]},
            "stylometry": {"ai_likelihood": style["ai_likelihood"], **style["detail"]},
            "lexical": {"ai_likelihood": lexical["ai_likelihood"], **lexical["detail"]},
        },
        "p_ai": result["p_ai"],
        "status": "classified",
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


if __name__ == "__main__":
    # use_reloader=False -> single process (the debug reloader otherwise spawns a
    # child, which complicates clean restarts). Port is overridable; note macOS
    # may run AirPlay Receiver on *:5000, but 127.0.0.1:5000 still resolves here.
    import os
    port = int(os.getenv("PORT", "5000"))
    app.run(host="127.0.0.1", port=port, debug=True, use_reloader=False)
