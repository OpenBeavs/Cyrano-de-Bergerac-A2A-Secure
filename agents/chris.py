#---------------------------------------------------------------------#
#
# chris.py — Christian de Neuvillette (CLI Chat Client)
#
#   Chris is the user-facing interface to the CDB system. He runs
#   as a CLI chat loop: you type a message, Chris sends it to Cyrano
#   via A2A, and prints Cyrano's reply.
#
#   Chris makes no LLM calls. He is a pure relay — a thin client
#   over the A2A protocol. All creative work happens in Cyrano.
#
#   Infrastructure Trust Plane: before entering the chat loop,
#   Chris executes the full pairing protocol to verify that the
#   Cyrano he is about to talk to is authorized by OSU. The
#   sequence:
#
#     1. Query the Agent Registry for the agent record.
#     2. Request a challenge token from the Registry.
#     3. Send the challenge to Cyrano's /pairing/respond endpoint.
#     4. Verify the signed pairing assertion that comes back.
#
#   If any step fails, Chris prints a specific error and exits.
#   Chris never routes user messages without a verified assertion.
#
#   TLS is required on every connection. Chris verifies server
#   certificates against the Mock CA root certificate.
#
#   Conversation continuity: Chris generates a context_id at startup
#   and includes it in every message. Cyrano uses this to maintain
#   a single conversation thread with full history.
#
#---------------------------------------------------------------------#

import asyncio
import hashlib
import hmac
import os
import sys
import uuid
import warnings

from datetime import datetime, timezone
from dotenv import load_dotenv

import httpx

warnings.filterwarnings("ignore", category=DeprecationWarning, module="a2a")
from a2a.client import A2AClient
from a2a.types import (
    Message,
    MessageSendParams,
    Part,
    SendMessageRequest,
    TextPart,
)


load_dotenv()

#---------------------------------------------------------------------#

REGISTRY_URL = os.environ.get("REGISTRY_URL", "https://localhost:8003")
CA_CERT_PATH = os.environ.get(
    "CA_CERT_PATH",
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "certs", "ca.crt",
    ),
)
PAIRING_VERIFY_KEY_PATH = os.environ.get(
    "PAIRING_VERIFY_KEY",
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "certs", "registry_signing.key",
    ),
)

DEFAULT_AGENT_ID = "cyrano-001"

BANNER = """
╔═════════════════════════════════════════════════════════════════════╗
║                                                                     ║
║             Cyrano de Bergerac — Secure Chat                       ║
║                                                                     ║
╚═════════════════════════════════════════════════════════════════════╝

  Type a message and press Enter. Cyrano will compose a reply.
  Type /exit to end the session, or press Ctrl+C to quit.
"""


#---------------------------------------------------------------------#
#
# _load_verify_key()
#   Read the HMAC key that the Registry uses to sign pairing
#   assertions. Chris uses the same key to verify them. This is
#   a symmetric (HMAC-SHA256) arrangement sufficient for the
#   proof of concept. Production would use asymmetric signatures.
#
#   Returns:
#       str: The hex-encoded HMAC key.
#
#---------------------------------------------------------------------#

def _load_verify_key() -> str:
    with open(PAIRING_VERIFY_KEY_PATH, "r") as f:
        return f.read().strip()


#---------------------------------------------------------------------#
#
# _verify_assertion()
#   Verify a pairing assertion signed by the Agent Registry.
#   Checks:
#     1. The HMAC-SHA256 signature is valid.
#     2. The assertion names the expected agent_id.
#     3. The assertion has not expired.
#
#   Args:
#       assertion (dict): The pairing assertion from Cyrano.
#       expected_agent_id (str): The agent ID Chris requested.
#       verify_key (str): The HMAC key.
#
#   Returns:
#       tuple: (success: bool, error_message: str or None)
#
#---------------------------------------------------------------------#

def _verify_assertion(
    assertion: dict, expected_agent_id: str, verify_key: str
) -> tuple[bool, str | None]:
    agent_id = assertion.get("agent_id", "")
    issued_at = assertion.get("issued_at", "")
    expires_at = assertion.get("expires_at", "")
    signature = assertion.get("signature", "")

    message = f"{agent_id}|{issued_at}|{expires_at}"
    expected_sig = hmac.new(
        verify_key.encode(), message.encode(), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(signature, expected_sig):
        return False, "pairing verification failed"

    if agent_id != expected_agent_id:
        return False, "pairing assertion mismatch"

    try:
        exp = datetime.fromisoformat(expires_at)
        if datetime.now(timezone.utc) > exp:
            return False, "pairing assertion expired"
    except (ValueError, TypeError):
        return False, "pairing assertion has invalid expiration"

    return True, None


#---------------------------------------------------------------------#
#
# _run_pairing()
#   Execute the full pairing protocol before entering the chat.
#
#   Steps:
#     1. GET /agents/{agent_id} — look up the agent in the
#        Registry. Confirm status is approved or provisional.
#     2. POST /pairing/challenge — get a challenge token.
#     3. POST {cyrano_endpoint}/pairing/respond — send the
#        challenge to Cyrano. Cyrano proves itself to the Registry
#        and returns the signed pairing assertion.
#     4. Verify the assertion locally using the HMAC key.
#
#   Returns the Cyrano endpoint URL and trust status on success.
#   Prints a specific error and exits on failure.
#
#   Args:
#       agent_id (str): The agent ID to pair with.
#       verify_key (str): The HMAC key for assertion verification.
#
#   Returns:
#       tuple: (endpoint_url: str, trust_status: str)
#
#---------------------------------------------------------------------#

async def _run_pairing(
    agent_id: str, verify_key: str
) -> tuple[str, str]:
    async with httpx.AsyncClient(
        verify=CA_CERT_PATH, timeout=15.0
    ) as client:

        # Step 1: look up the agent
        print(f"  Querying Registry for agent '{agent_id}' ...")
        try:
            resp = await client.get(
                f"{REGISTRY_URL}/agents/{agent_id}"
            )
        except httpx.ConnectError:
            print(
                "  [Error] Cannot reach Agent Registry at",
                REGISTRY_URL,
            )
            sys.exit(1)

        if resp.status_code == 404:
            print(f"  [Error] Agent not found: {agent_id}")
            sys.exit(1)
        if resp.status_code != 200:
            print(f"  [Error] Registry error: {resp.text}")
            sys.exit(1)

        agent_record = resp.json()
        status = agent_record["status"]
        endpoint = agent_record["endpoint"]

        if status not in ("approved", "provisional"):
            print(f"  [Error] Agent is not approved (status: {status})")
            sys.exit(1)

        print(f"  Agent found: {agent_record['name']}")
        print(f"  Status: {status}")
        print(f"  Endpoint: {endpoint}")

        # Step 2: request a challenge token
        print("  Requesting pairing challenge ...")
        resp = await client.post(
            f"{REGISTRY_URL}/pairing/challenge",
            json={"agent_id": agent_id},
        )
        if resp.status_code != 200:
            print(f"  [Error] Challenge request failed: {resp.text}")
            sys.exit(1)

        challenge_token = resp.json()["challenge_token"]

        # Step 3: send challenge to Cyrano
        print("  Sending challenge to Cyrano ...")
        try:
            resp = await client.post(
                f"{endpoint}/pairing/respond",
                json={"challenge_token": challenge_token},
            )
        except httpx.ConnectError:
            print(f"  [Error] Cannot reach Cyrano at {endpoint}")
            sys.exit(1)

        if resp.status_code != 200:
            detail = resp.json().get("detail", resp.text)
            print(f"  [Error] Pairing failed: {detail}")
            sys.exit(1)

        assertion = resp.json()

        # Step 4: verify the assertion
        print("  Verifying pairing assertion ...")
        success, error = _verify_assertion(
            assertion, agent_id, verify_key
        )
        if not success:
            print(f"  [Error] {error}")
            sys.exit(1)

        print("  Pairing verified.")
        print()

    return endpoint, status


#---------------------------------------------------------------------#
#
# _send_message()
#   Send a message to Cyrano via A2A and return the reply text.
#
#---------------------------------------------------------------------#

async def _send_message(
    client: A2AClient, context_id: str, text: str
) -> str:
    request = SendMessageRequest(
        id=uuid.uuid4().hex,
        params=MessageSendParams(
            message=Message(
                role="user",
                messageId=uuid.uuid4().hex,
                parts=[Part(root=TextPart(text=text))],
                contextId=context_id,
            ),
        ),
    )

    response = await client.send_message(request)

    inner = response.root
    if hasattr(inner, "error") and inner.error:
        return f"[Error from Cyrano: {inner.error.message}]"

    msg = inner.result
    if msg is None:
        return "(No result from Cyrano)"

    texts = []
    for part in msg.parts:
        p = part.root if hasattr(part, "root") else part
        if hasattr(p, "text"):
            texts.append(p.text)
    return "\n".join(texts) if texts else "(Empty reply from Cyrano)"


#---------------------------------------------------------------------#
#
# run_chat()
#   Main entry point. Runs pairing, then enters the chat loop.
#
#---------------------------------------------------------------------#

async def run_chat() -> None:
    agent_id = (
        sys.argv[2] if len(sys.argv) > 2 else DEFAULT_AGENT_ID
    )

    verify_key = _load_verify_key()

    print()
    print("  ─────────────────────────────────────────────────────")
    print("  Infrastructure Trust Plane: Pairing")
    print("  ─────────────────────────────────────────────────────")
    print()

    endpoint, status = await _run_pairing(agent_id, verify_key)

    status_label = (
        "APPROVED" if status == "approved" else "PROVISIONAL"
    )
    print(f"  ─────────────────────────────────────────────────────")
    print(f"  Trust Status: [{status_label}]")
    print(f"  Connected to: {agent_id} at {endpoint}")
    print(f"  ─────────────────────────────────────────────────────")

    context_id = uuid.uuid4().hex
    cyrano_url = endpoint + "/"

    async with httpx.AsyncClient(
        verify=CA_CERT_PATH, timeout=120.0
    ) as httpx_client:
        client = A2AClient(
            httpx_client=httpx_client, url=cyrano_url
        )

        print(BANNER)

        while True:
            try:
                user_input = input("  You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not user_input:
                continue

            print()
            try:
                reply = await _send_message(
                    client, context_id, user_input
                )
                print(f"  Cyrano: {reply}")
            except httpx.ConnectError:
                print(
                    "  [Error] Cannot reach Cyrano at", cyrano_url
                )
                print("  Is the Cyrano server running?")
            except Exception as e:
                print(f"  [Error] {e}")
            print()

            if user_input.strip().lower() == "/exit":
                break


def main() -> None:
    asyncio.run(run_chat())


#---------------------------------------------------------------------#
#eof#
