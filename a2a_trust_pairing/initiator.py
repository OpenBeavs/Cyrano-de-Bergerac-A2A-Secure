#---------------------------------------------------------------------#
#
# initiator.py -- Pairing initiation flows
#
#   Two flows for the two tiers of trust:
#
#   initiate_pairing() -- Mediated trust (Chris-to-Cyrano via AR).
#     Full challenge-response: look up the agent, get a challenge
#     token, send it to Cyrano, verify the signed assertion that
#     comes back. Returns the verified endpoint and trust status.
#
#   bootstrap_authenticate() -- Bootstrap trust (Chris-to-AR).
#     Organizational trust, pre-provisioned. Chris presents a
#     credential; the AR verifies it. No third-party mediator
#     because this IS the root of trust. Stub until Phase 5
#     when Chris authentication is added.
#
#   All config is passed as function parameters. The module never
#   reads environment variables directly. This makes it portable:
#   any project can import it and supply its own config.
#
#   Steps 1--2 (agent-lookup, pairing-challenge) and the responder's
#   verify call all speak A2A to the Registry. Step 3 (challenge to
#   Cyrano) uses REST because Cyrano's /pairing/respond is a direct
#   FastAPI endpoint on the A2A app, not an A2A skill.
#
#---------------------------------------------------------------------#

import json
import uuid
import warnings

import httpx

warnings.filterwarnings(
    "ignore", category=DeprecationWarning, module="a2a"
)
from a2a.client import A2AClient
from a2a.types import (
    Message,
    MessageSendParams,
    Part,
    SendMessageRequest,
    TextPart,
)

from .verification import verify_assertion


# ── A2A helpers ──────────────────────────────────────────────────

async def _send_a2a_skill(
    client: A2AClient,
    payload: dict,
) -> dict:
    """Send a JSON skill payload to an A2A service.

    Wraps the payload as a TextPart in a SendMessage request,
    sends it, and parses the JSON response. Raises PairingError
    if the service returns an error.
    """
    request = SendMessageRequest(
        id=uuid.uuid4().hex,
        params=MessageSendParams(
            message=Message(
                role="user",
                messageId=uuid.uuid4().hex,
                parts=[
                    Part(root=TextPart(text=json.dumps(payload)))
                ],
            ),
        ),
    )

    response = await client.send_message(request)
    inner = response.root

    if hasattr(inner, "error") and inner.error:
        raise PairingError(
            f"registry error: {inner.error.message}"
        )

    result_msg = inner.result
    if result_msg is None:
        raise PairingError("registry returned no result")

    # Extract text from the response message
    if hasattr(result_msg, "parts"):
        parts = result_msg.parts
    elif hasattr(result_msg, "artifacts"):
        parts = []
        for a in (result_msg.artifacts or []):
            parts.extend(a.parts or [])
    else:
        raise PairingError("unexpected response structure")

    for part in parts:
        p = part.root if hasattr(part, "root") else part
        if hasattr(p, "text"):
            data = json.loads(p.text)
            if "error" in data:
                raise PairingError(data["error"])
            return data

    raise PairingError("registry returned empty response")


# ── Mediated pairing (Chris to Cyrano via AR) ────────────────────

async def initiate_pairing(
    agent_id: str,
    registry_url: str,
    ca_cert_path: str,
    verify_key: str,
    chris_credential: str | None = None,
) -> tuple[str, str]:
    """Run the full mediated pairing flow.

    Steps:
      1. Look up the agent record in the Registry (A2A).
      2. Request a challenge token from the Registry (A2A).
      3. Send the challenge to the agent's pairing endpoint (REST).
      4. Verify the signed assertion that comes back.

    Args:
        agent_id: The agent to pair with.
        registry_url: Base URL of the Agent Registry.
        ca_cert_path: Path to the CA certificate for TLS.
        verify_key: HMAC key for assertion verification.
        chris_credential: Chris's credential for AR authentication.

    Returns:
        (endpoint_url, trust_status) on success.

    Raises:
        PairingError on any failure.
    """
    async with httpx.AsyncClient(
        verify=ca_cert_path, timeout=15.0
    ) as httpx_client:

        # A2A client for Registry communication
        try:
            registry_client = A2AClient(
                httpx_client=httpx_client,
                url=registry_url + "/",
            )
        except Exception:
            raise PairingError(
                f"cannot reach Agent Registry at {registry_url}"
            )

        # Step 1: look up the agent
        lookup_payload = {
            "skill": "agent-lookup",
            "agent_id": agent_id,
        }
        if chris_credential:
            lookup_payload["chris_credential"] = chris_credential

        try:
            agent_record = await _send_a2a_skill(
                registry_client, lookup_payload,
            )
        except httpx.ConnectError:
            raise PairingError(
                f"cannot reach Agent Registry at {registry_url}"
            )

        status = agent_record["status"]
        endpoint = agent_record["endpoint"]

        if status not in ("approved", "provisional"):
            raise PairingError(
                f"agent is not approved (status: {status})"
            )

        # Step 2: request a challenge token
        challenge_payload = {
            "skill": "pairing-challenge",
            "agent_id": agent_id,
        }
        if chris_credential:
            challenge_payload["chris_credential"] = (
                chris_credential
            )

        try:
            challenge_resp = await _send_a2a_skill(
                registry_client, challenge_payload,
            )
        except httpx.ConnectError:
            raise PairingError(
                f"cannot reach Agent Registry at {registry_url}"
            )

        challenge_token = challenge_resp["challenge_token"]

        # Step 3: send challenge to the agent (REST endpoint)
        try:
            resp = await httpx_client.post(
                f"{endpoint}/pairing/respond",
                json={"challenge_token": challenge_token},
            )
        except httpx.ConnectError:
            raise PairingError(
                f"cannot reach agent at {endpoint}"
            )

        if resp.status_code != 200:
            detail = resp.json().get("detail", resp.text)
            raise PairingError(f"pairing failed: {detail}")

        assertion = resp.json()

        # Step 4: verify the assertion
        success, error = verify_assertion(
            assertion, agent_id, verify_key
        )
        if not success:
            raise PairingError(error)

    return endpoint, status


# ── Bootstrap authentication (Chris to AR) ───────────────────────

async def bootstrap_authenticate(
    chris_credential: str,
    registry_url: str,
    ca_cert_path: str,
) -> bool:
    """Verify that Chris can authenticate with the AR.

    The AR enforces chris_credential on every skill request
    (agent-lookup, pairing-challenge). This function confirms
    the credential works by sending a no-op lookup. If the AR
    rejects it, the credential is wrong.

    Returns True if the credential is accepted, False otherwise.
    """
    if not chris_credential:
        return False

    # Any skill call will test the credential. Use agent-lookup
    # with a known-missing ID; we only care whether the AR
    # rejects the credential (auth failure) vs. processes the
    # request (agent not found is fine -- it means auth passed).
    async with httpx.AsyncClient(
        verify=ca_cert_path, timeout=10.0
    ) as httpx_client:
        try:
            registry_client = A2AClient(
                httpx_client=httpx_client,
                url=registry_url + "/",
            )
            await _send_a2a_skill(
                registry_client,
                {
                    "skill": "agent-lookup",
                    "agent_id": "__auth_test__",
                    "chris_credential": chris_credential,
                },
            )
        except PairingError as e:
            if "authentication failed" in str(e):
                return False
            # "agent not found" means auth succeeded
            return True
        except httpx.ConnectError:
            return False

    return True


# ── Errors ───────────────────────────────────────────────────────

class PairingError(Exception):
    """Any failure during the pairing protocol."""
    pass


#---------------------------------------------------------------------#
#eof#
