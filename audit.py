"""Structured audit logging — every classification and every appeal becomes an
immutable event in the audit_log table (planning.md §4).

Each event records enough to diagnose a decision later: the combined confidence,
all three individual signal scores, and (for appeals) the creator's reasoning
beside a snapshot of the original decision.
"""
import db


def log_classification(content_id: str, creator_id: str, result: dict,
                       signals: dict) -> None:
    payload = {
        "creator_id": creator_id,
        "attribution": result["attribution"],
        "confidence": result["confidence"],
        "p_ai": result["p_ai"],
        "llm_score": signals.get("llm"),
        "style_score": signals.get("stylometry"),
        "lexical_score": signals.get("lexical"),
        "used_signals": result.get("used_signals"),
        "status": "classified",
    }
    db.append_audit(content_id, "classified", payload)
    print(f'[CLASSIFIED] {content_id[:8]} → {result["attribution"]} '
          f'(conf {result["confidence"]}, p_ai {result["p_ai"]})')


def log_appeal(content_id: str, creator_reasoning: str, original: dict) -> None:
    """Log an appeal next to a snapshot of the original decision."""
    payload = {
        "status": "under_review",
        "appeal_reasoning": creator_reasoning,
        # Snapshot of what is being contested, so a reviewer sees both sides.
        "original_decision": {
            "attribution": original.get("attribution"),
            "confidence": original.get("confidence"),
            "p_ai": original.get("p_ai"),
            "llm_score": original.get("llm_score"),
            "style_score": original.get("style_score"),
            "lexical_score": original.get("lexical_score"),
        },
    }
    db.append_audit(content_id, "appeal", payload)
    print(f'[APPEAL] {content_id[:8]} → under_review')
