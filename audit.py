"""Structured audit logging — every classification and every appeal becomes an
immutable event in the audit_log table (planning.md §4).

Each event records enough to diagnose a decision later: the combined confidence
and every individual signal score (stored as a dict so it works for any
modality — text or image_metadata). Appeals additionally record the creator's
reasoning beside a snapshot of the original decision.
"""
import db


def log_classification(content_id: str, creator_id: str, content_type: str,
                       result: dict, signals: dict) -> None:
    payload = {
        "creator_id": creator_id,
        "content_type": content_type,
        "attribution": result["attribution"],
        "confidence": result["confidence"],
        "p_ai": result["p_ai"],
        "signals": signals,                 # {signal_name: score, ...}
        "used_signals": result.get("used_signals"),
        "status": "classified",
    }
    db.append_audit(content_id, "classified", payload)
    print(f'[CLASSIFIED] {content_id[:8]} ({content_type}) → {result["attribution"]} '
          f'(conf {result["confidence"]}, p_ai {result["p_ai"]})')


def log_appeal(content_id: str, creator_reasoning: str, original: dict) -> None:
    """Log an appeal next to a snapshot of the original decision."""
    payload = {
        "status": "under_review",
        "appeal_reasoning": creator_reasoning,
        # Snapshot of what is being contested, so a reviewer sees both sides.
        "original_decision": {
            "content_type": original.get("content_type"),
            "attribution": original.get("attribution"),
            "confidence": original.get("confidence"),
            "p_ai": original.get("p_ai"),
            "signals": original.get("signals"),
        },
    }
    db.append_audit(content_id, "appeal", payload)
    print(f'[APPEAL] {content_id[:8]} → under_review')
