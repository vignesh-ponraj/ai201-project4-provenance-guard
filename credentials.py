"""Provenance certificate (stretch: verified-human credential).

A creator earns a "Verified Human Creator" credential through a two-step
challenge: the platform issues a phrase, the creator types it back verbatim, and
on success an HMAC-signed credential is issued and stored.

This is deliberately a *lightweight* check — a presence/attention step that
deters trivial scripted sign-ups, not strong identity proofing (a production
system would use captcha, OAuth, or government ID). Crucially, the credential is
about the *creator's identity*, NOT a claim about any single piece of content:
verified creators' submissions are still classified normally. The badge gives a
reader extra trust context; it never overrides detection. A verified human whose
work is flagged AI is, however, a strong candidate for appeal.
"""
from __future__ import annotations

import hashlib
import hmac
import uuid

import db
from config import VERIFY_PHRASE, VERIFY_SECRET


def _sign(creator_id: str, credential_id: str) -> str:
    msg = f"{creator_id}:{credential_id}".encode()
    return hmac.new(VERIFY_SECRET.encode(), msg, hashlib.sha256).hexdigest()


def start_verification(creator_id: str) -> dict:
    """Create a pending challenge; return the phrase the creator must type back."""
    challenge_id = str(uuid.uuid4())
    db.save_challenge(challenge_id, creator_id, VERIFY_PHRASE)
    return {
        "challenge_id": challenge_id,
        "instructions": "Type the phrase below back exactly to verify you're a human creator.",
        "phrase": VERIFY_PHRASE,
    }


def complete_verification(challenge_id: str, typed_phrase: str) -> dict:
    """Validate the typed phrase and, on success, issue a credential.

    Returns {ok: bool, ...}. ok=False carries an `error` and `status` code hint.
    """
    challenge = db.get_challenge(challenge_id)
    if not challenge:
        return {"ok": False, "status": 404, "error": "unknown challenge_id"}
    if challenge["used"]:
        return {"ok": False, "status": 409, "error": "challenge already used"}

    if (typed_phrase or "").strip().lower() != challenge["phrase"].strip().lower():
        return {"ok": False, "status": 422, "error": "phrase did not match"}

    creator_id = challenge["creator_id"]
    credential_id = str(uuid.uuid4())
    token = _sign(creator_id, credential_id)
    issued_at = db.save_credential(creator_id, credential_id, token)
    db.mark_challenge_used(challenge_id)

    return {
        "ok": True,
        "creator_id": creator_id,
        "credential_id": credential_id,
        "token": token,
        "issued_at": issued_at,
        "badge": badge_for(creator_id),
    }


def badge_for(creator_id: str) -> dict | None:
    """The verified-human badge to surface on a creator's content, or None."""
    cred = db.get_credential(creator_id)
    if not cred:
        return None
    # Verify the stored token really was signed by us (tamper check).
    expected = _sign(creator_id, cred["credential_id"])
    if not hmac.compare_digest(expected, cred["token"]):
        return None
    return {
        "verified_human": True,
        "label": "✓ Verified Human Creator",
        "credential_id": cred["credential_id"],
        "verified_at": cred["issued_at"],
    }
