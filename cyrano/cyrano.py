#---------------------------------------------------------------------#
#
# cyrano.py — Cyrano de Bergerac (The Hidden Wordsmith)
#
#   Cyrano is the creative engine of the CDB system. He receives a
#   message (always from Chris, never from the user directly) and
#   crafts an eloquent reply. He is the leaf agent — no sub-agents,
#   no routing, just words.
#
#   This module implements a pure A2A server using the a2a-sdk. No
#   ADK dependency. The server exposes an AgentCard at the standard
#   well-known URL and handles SendMessage requests via JSON-RPC.
#
#   Infrastructure Trust Plane: Cyrano participates in the pairing
#   protocol by exposing a /pairing/respond endpoint. When Chris
#   initiates pairing, Chris sends a challenge token to this
#   endpoint. Cyrano proves its identity to the Agent Registry by
#   presenting its Trust Badge and the challenge token to the
#   Registry's /pairing/verify endpoint. The Registry returns a
#   signed pairing assertion, which Cyrano relays back to Chris.
#   Cyrano never reveals its Trust Badge to Chris.
#
#   The LLM call routes through the voice service, which makes a
#   Gemini API call and logs every exchange with UTC timestamps,
#   session IDs, and token counts.
#
#   Conversation history is managed by the context service. Each
#   message (inbound and outbound) is added to a ConversationContext
#   instance. When the history approaches 90% of CONTEXT_MAX, the
#   context service compacts it into three tiers (distant summary,
#   recent summary, verbatim recent) before the next LLM call.
#
#---------------------------------------------------------------------#

import logging
import os
import uuid

from dotenv import load_dotenv

from a2a.server.agent_execution.agent_executor import AgentExecutor
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.server.request_handlers.default_request_handler import DefaultRequestHandler
from a2a.server.tasks.inmemory_task_store import InMemoryTaskStore
from a2a.server.apps.jsonrpc.fastapi_app import A2AFastAPIApplication
from a2a.types import (
    AgentCard,
    AgentCapabilities,
    AgentSkill,
    Message,
    Part,
    TextPart,
)

from services.llm_voice_context import llm_call, ConversationContext
from a2a_trust_pairing import mount_pairing_responder


load_dotenv()

logger = logging.getLogger(__name__)


# ── Conversation context ──────────────────────────────────────────
#
#   One instance per context_id. Cyrano has a single conversation
#   channel — messages from Chris. The context_id groups turns
#   within a logical conversation.

_contexts: dict[str, ConversationContext] = {}


def _get_context(context_id: str) -> ConversationContext:
    """Return (or create) the conversation context for this context."""
    if context_id not in _contexts:
        _contexts[context_id] = ConversationContext(
            channel_name="cyrano-chris",
            session_id=context_id,
        )
    return _contexts[context_id]


# ── System instruction ────────────────────────────────────────────

CYRANO_INSTRUCTION = (
    "You are Cyrano de Bergerac, a brilliant wordsmith hidden from "
    "the audience. You receive a message and craft an eloquent, "
    "expressive reply. Your words will be delivered by another -- "
    "you never speak to the user directly."
)

CYRANO_FAREWELL_INSTRUCTION = (
    "You are Cyrano de Bergerac. The conversation is ending. "
    "Compose a brief, poignant farewell to your beloved Roxane, "
    "in character. This is your final speech -- make it worthy "
    "of the name Cyrano de Bergerac."
)


# ── Agent executor ────────────────────────────────────────────────
#
#   The a2a-sdk calls execute() for each incoming SendMessage
#   request. We extract the user's text, run it through voice +
#   context, and publish the response as an A2A Message.

class CyranoExecutor(AgentExecutor):

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        user_message = self._extract_text(context)
        if not user_message:
            await event_queue.enqueue_event(
                self._make_message(context, "(empty message received)")
            )
            return

        is_exit = user_message.strip().lower() == "/exit"
        context_id = context.context_id or "default"
        ctx = _get_context(context_id)
        ctx.add_message("user", user_message)

        if ctx.needs_compaction():
            ctx.compact()

        result = llm_call(
            agent_name="cyrano",
            session_id=context_id,
            system_message=CYRANO_FAREWELL_INSTRUCTION if is_exit else CYRANO_INSTRUCTION,
            user_message=user_message,
            conversation_history=ctx.get_history(),
            model_id=os.environ.get("CYRANO_MODEL"),
        )

        response_text = result["response"]
        ctx.add_message("model", response_text)

        await event_queue.enqueue_event(
            self._make_message(context, response_text)
        )

        if is_exit:
            del _contexts[context_id]

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        pass

    def _extract_text(self, context: RequestContext) -> str:
        """Pull the user's text from the incoming A2A message."""
        text = context.get_user_input()
        if text:
            return text
        msg = context.message
        if not msg:
            return ""
        for part in msg.parts:
            inner = part.root if hasattr(part, "root") else part
            if hasattr(inner, "text"):
                return inner.text
        return ""

    def _make_message(self, context: RequestContext, text: str) -> Message:
        return Message(
            role="agent",
            messageId=uuid.uuid4().hex,
            parts=[Part(root=TextPart(text=text))],
            contextId=context.context_id,
        )


# ── Agent card ────────────────────────────────────────────────────

agent_card = AgentCard(
    name="cyrano",
    description="A brilliant wordsmith who crafts eloquent replies.",
    url="https://localhost:8002/",
    version="1.0.0",
    capabilities=AgentCapabilities(streaming=False),
    defaultInputModes=["text"],
    defaultOutputModes=["text"],
    skills=[
        AgentSkill(
            id="compose",
            name="Compose eloquent reply",
            description="Receives a message and crafts an eloquent, expressive reply.",
            tags=["writing", "creative"],
        )
    ],
)


# ── Trust credentials ────────────────────────────────────────────
#
#   CYRANO_TRUST_BADGE is the shared secret between Cyrano and the
#   Agent Registry. Cyrano presents it to the Registry during
#   pairing to prove identity. It is never revealed to Chris.
#
#   CYRANO_AGENT_ID identifies this agent in the Registry.
#
#   REGISTRY_URL is where the Agent Registry listens.
#
#   CA_CERT_PATH is the Mock CA root certificate. Cyrano uses it
#   to verify the Registry's TLS certificate when calling
#   /pairing/verify.

CYRANO_AGENT_ID = os.environ.get("CYRANO_AGENT_ID", "cyrano-001")
CYRANO_TRUST_BADGE = os.environ.get("CYRANO_TRUST_BADGE", "")
REGISTRY_URL = os.environ.get("REGISTRY_URL", "https://localhost:8003")
CA_CERT_PATH = os.environ.get(
    "CA_CERT_PATH",
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "certs", "ca.crt",
    ),
)


# ── Build the ASGI app ───────────────────────────────────────────

_handler = DefaultRequestHandler(
    agent_executor=CyranoExecutor(),
    task_store=InMemoryTaskStore(),
)

a2a_app = A2AFastAPIApplication(
    agent_card=agent_card,
    http_handler=_handler,
).build()


# ── Pairing ──────────────────────────────────────────────────────
#
#   The pairing endpoint lets Chris verify Cyrano's identity
#   through the Agent Registry. The a2a_trust_pairing module
#   owns the mechanics; Cyrano supplies its credentials.

mount_pairing_responder(
    app=a2a_app,
    agent_id=CYRANO_AGENT_ID,
    trust_badge=CYRANO_TRUST_BADGE,
    registry_url=REGISTRY_URL,
    ca_cert_path=CA_CERT_PATH,
)


#---------------------------------------------------------------------#
#eof#
