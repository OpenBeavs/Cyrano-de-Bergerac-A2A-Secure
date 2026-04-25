#---------------------------------------------------------------------#
#
# responder.py -- Pairing responder for A2A agents
#
#   Adds pairing capability to any A2A FastAPI app. The agent
#   (e.g., Cyrano) calls mount_pairing_responder() at startup.
#   This registers a POST /pairing/respond endpoint on the app.
#
#   When Chris initiates pairing, Chris sends a challenge token
#   to this endpoint. The responder proves the agent's identity
#   to the Registry by sending a pairing-verify skill message
#   to the Registry's A2A service. The Registry returns a signed
#   pairing assertion, which the responder relays back to Chris.
#   The agent never reveals its Trust Badge to Chris.
#
#   All config is passed as function parameters. The module never
#   reads environment variables directly.
#
#---------------------------------------------------------------------#

import json
import logging
import uuid
import warnings

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

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

logger = logging.getLogger(__name__)


class _PairingRespondRequest(BaseModel):
    challenge_token: str


def mount_pairing_responder(
    app: FastAPI,
    agent_id: str,
    trust_badge: str,
    registry_url: str,
    ca_cert_path: str,
) -> None:
    """Register the /pairing/respond endpoint on the app.

    Args:
        app: The FastAPI app to mount the endpoint on.
        agent_id: This agent's ID in the Registry.
        trust_badge: This agent's Trust Badge (shared secret
            with the Registry; never revealed to Chris).
        registry_url: Base URL of the Agent Registry.
        ca_cert_path: Path to the CA cert for TLS verification.
    """

    @app.post("/pairing/respond")
    async def pairing_respond(req: _PairingRespondRequest) -> dict:
        if not trust_badge:
            logger.error("trust_badge is not configured")
            raise HTTPException(
                status_code=500,
                detail="agent trust credentials not configured",
            )

        # Send pairing-verify as an A2A skill message
        payload = {
            "skill": "pairing-verify",
            "agent_id": agent_id,
            "challenge_token": req.challenge_token,
            "trust_badge": trust_badge,
        }

        request = SendMessageRequest(
            id=uuid.uuid4().hex,
            params=MessageSendParams(
                message=Message(
                    role="user",
                    messageId=uuid.uuid4().hex,
                    parts=[
                        Part(root=TextPart(
                            text=json.dumps(payload)
                        ))
                    ],
                ),
            ),
        )

        async with httpx.AsyncClient(
            verify=ca_cert_path, timeout=10.0
        ) as httpx_client:
            try:
                registry_client = A2AClient(
                    httpx_client=httpx_client,
                    url=registry_url + "/",
                )
                response = await registry_client.send_message(
                    request
                )
            except httpx.ConnectError:
                logger.error(
                    "cannot reach Agent Registry at %s",
                    registry_url,
                )
                raise HTTPException(
                    status_code=502,
                    detail="cannot reach Agent Registry",
                )

        inner = response.root
        if hasattr(inner, "error") and inner.error:
            logger.warning(
                "Registry rejected pairing verify: %s",
                inner.error.message,
            )
            raise HTTPException(
                status_code=403,
                detail=inner.error.message,
            )

        result_msg = inner.result
        if result_msg is None:
            raise HTTPException(
                status_code=502,
                detail="registry returned no result",
            )

        # Extract JSON from the response message
        parts = getattr(result_msg, "parts", [])
        for part in parts:
            p = part.root if hasattr(part, "root") else part
            if hasattr(p, "text"):
                data = json.loads(p.text)
                if "error" in data:
                    logger.warning(
                        "Registry rejected pairing verify: %s",
                        data["error"],
                    )
                    raise HTTPException(
                        status_code=403,
                        detail=data["error"],
                    )
                return data

        raise HTTPException(
            status_code=502,
            detail="registry returned empty response",
        )


#---------------------------------------------------------------------#
#eof#
