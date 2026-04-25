#---------------------------------------------------------------------#
#
# verification.py -- Pairing assertion verification
#
#   Verifies HMAC-SHA256 pairing assertions issued by the Agent
#   Registry. Pure function, no I/O. The caller (typically an
#   initiator like Chris) passes the assertion dict and the HMAC
#   key; this module says whether it checks out.
#
#   Three checks:
#     1. Signature: recompute HMAC over the signed fields and
#        compare. Catches tampering and wrong keys.
#     2. Agent ID: the assertion must name the agent we asked for.
#        Catches assertion replay across agents.
#     3. Expiration: the assertion must not have expired. Catches
#        stale assertions presented after their TTL.
#
#   The signature format (pipe-delimited fields) matches what the
#   Registry produces in sign_assertion(). If the Registry changes
#   its format, this must change too.
#
#---------------------------------------------------------------------#

import hashlib
import hmac

from datetime import datetime, timezone


def verify_assertion(
    assertion: dict,
    expected_agent_id: str,
    verify_key: str,
) -> tuple[bool, str | None]:
    """Check signature, agent_id, and expiration.

    Returns (True, None) on success or (False, error_message).
    """
    agent_id = assertion.get("agent_id", "")
    issued_at = assertion.get("issued_at", "")
    expires_at = assertion.get("expires_at", "")
    signature = assertion.get("signature", "")

    # -- signature check --
    message = f"{agent_id}|{issued_at}|{expires_at}"
    expected_sig = hmac.new(
        verify_key.encode(), message.encode(), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(signature, expected_sig):
        return False, "pairing verification failed"

    # -- agent_id check --
    if agent_id != expected_agent_id:
        return False, "pairing assertion mismatch"

    # -- expiration check --
    try:
        exp = datetime.fromisoformat(expires_at)
        if datetime.now(timezone.utc) > exp:
            return False, "pairing assertion expired"
    except (ValueError, TypeError):
        return False, "pairing assertion has invalid expiration"

    return True, None


#---------------------------------------------------------------------#
#eof#
