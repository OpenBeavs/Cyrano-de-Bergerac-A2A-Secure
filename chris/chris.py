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
import os
import sys
import uuid
import warnings

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

from a2a_trust_pairing import initiate_pairing, PairingError


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
CHRIS_CREDENTIAL = os.environ.get("CHRIS_CREDENTIAL", "")

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
#---------------------------------------------------------------------#

def _load_verify_key() -> str:
    with open(PAIRING_VERIFY_KEY_PATH, "r") as f:
        return f.read().strip()


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

    print(f"  Querying Registry for agent '{agent_id}' ...")
    try:
        endpoint, status = await initiate_pairing(
            agent_id=agent_id,
            registry_url=REGISTRY_URL,
            ca_cert_path=CA_CERT_PATH,
            verify_key=verify_key,
            chris_credential=CHRIS_CREDENTIAL or None,
        )
    except PairingError as e:
        print(f"  [Error] {e}")
        sys.exit(1)

    print("  Pairing verified.")
    print()

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
