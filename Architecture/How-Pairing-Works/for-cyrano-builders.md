# For Cyrano Builders

How to build a Cyrano-type A2A server (responder) that proves its identity through the Agent Registry when challenged.

## What Cyrano is

Cyrano is an A2A server with an LLM. Chris sends messages; Cyrano crafts replies. Cyrano's primary function is domain expertise (in the demo, eloquent writing). Pairing is a secondary obligation: when Chris initiates a pairing challenge, Cyrano must prove its identity to the Agent Registry.

Cyrano never speaks to the user directly. Chris is the user-facing interface. Cyrano is the hidden talent.

## The pairing flow from Cyrano's perspective

Cyrano's role in pairing is narrow. Cyrano does not initiate pairing, does not generate challenges, and does not verify assertions. Cyrano responds.

1. Chris sends a challenge token to Cyrano's `/pairing/respond` endpoint.
2. Cyrano sends the challenge token and its Trust Badge to the AR's `pairing-verify` skill.
3. The AR validates the badge and challenge, then returns a signed assertion.
4. Cyrano relays the assertion back to Chris.

Cyrano acts as a pass-through between Chris and the AR. The critical step is Step 2: Cyrano proves it holds the Trust Badge that the AR has on file for this agent ID. Everything else is relay.

## Using the pairing module

The `a2a_trust_pairing` module provides `mount_pairing_responder()`, which adds the pairing endpoint to any FastAPI-based A2A app.

```python
from a2a_trust_pairing import mount_pairing_responder

mount_pairing_responder(
    app=a2a_app,
    agent_id=CYRANO_AGENT_ID,
    trust_badge=CYRANO_TRUST_BADGE,
    registry_url=REGISTRY_URL,
    ca_cert_path=CA_CERT_PATH,
)
```

This registers `POST /pairing/respond` on the app. When Chris sends a challenge, the endpoint handles Steps 2--4 automatically: it contacts the AR, presents the Trust Badge, and relays the result.

**Parameters:**

| Parameter | Source | Purpose |
|---|---|---|
| `app` | Your A2A FastAPI app | The app to mount the endpoint on |
| `agent_id` | Environment (`CYRANO_AGENT_ID`) | This agent's ID in the AR |
| `trust_badge` | Environment (`CYRANO_TRUST_BADGE`) | Shared secret with the AR; proves identity |
| `registry_url` | Environment (`REGISTRY_URL`) | Where the AR listens |
| `ca_cert_path` | Environment (`CA_CERT_PATH`) | TLS CA root cert for verifying the AR's server cert |

Call `mount_pairing_responder()` after building the A2A app but before the server starts accepting connections.

## The Trust Badge

The Trust Badge is a shared secret between Cyrano and the Agent Registry. The AR stores a SHA-256 hash of the badge in `agents.json`. Cyrano holds the raw value.

During pairing-verify, Cyrano sends the raw badge to the AR. The AR hashes it and compares against the stored hash. If they match, the AR knows this Cyrano holds the correct badge for this agent ID.

**Where it comes from:** The admin team provisions the Trust Badge when registering the agent. In the demo, `mock_ca.py` generates it. In production, the admin team's provisioning process generates it and delivers it to the Cyrano operator through a secure channel.

**How to load it:** From the environment (`CYRANO_TRUST_BADGE`). The operator copies the raw badge value from the provisioned file into `.env` or their secrets management system.

**Why it must never be revealed to Chris:** If Chris held the badge, Chris could impersonate Cyrano to the AR. The entire point of mediated pairing is that Chris verifies the AR's assertion, not Cyrano's credential. The Trust Badge stays on the Cyrano-AR channel.

## Agent card

Cyrano's agent card advertises its capabilities to Chris. The pairing protocol does not impose specific requirements on the agent card's skills or capabilities. The agent card describes what Cyrano does (compose replies, translate, analyze); the pairing protocol describes whether Cyrano is authorized to do it.

The current Cyrano agent card:

```python
AgentCard(
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
```

The `url` field must match the `endpoint` in the AR's agent record. If they differ, Chris will pair successfully (the AR returns the endpoint from its record) but then connect to a different URL than the agent card advertises.

## What Cyrano does not care about

**Chris's credential.** Cyrano has no knowledge of how Chris authenticates to the AR. Chris's credential exists on the Chris-AR channel only. Cyrano never sees it, never validates it, and has no code path that references it.

**The HMAC signing key.** The AR signs pairing assertions; Chris verifies them. Cyrano relays the assertion but does not inspect it. Cyrano does not hold the signing key or the verify key. From Cyrano's perspective, the assertion is an opaque blob that Chris asked for and Cyrano delivers.

**The AR's judgment process.** Cyrano does not know why it was approved, provisional, or rejected. The admin team makes that decision based on their vetting process. Cyrano's code does not change based on trust status.

## Cyrano is stateless for pairing

Cyrano does not store pairing state. Each challenge-response is a self-contained exchange: Chris sends a challenge, Cyrano proves its identity to the AR, and the result goes back. If Chris disconnects and reconnects, a new pairing runs from scratch. Cyrano has no memory of previous pairings.

Cyrano does maintain conversation context for chat messages (tracked by `context_id`). But this is unrelated to pairing. When Chris sends `/exit`, Cyrano clears the conversation context for that session and continues listening for the next connection.

## Integration pattern

A typical Cyrano implementation has this structure:

```python
# 1. Build the A2A app with your executor
a2a_app = A2AFastAPIApplication(
    agent_card=agent_card,
    http_handler=handler,
).build()

# 2. Mount the pairing responder
from a2a_trust_pairing import mount_pairing_responder

mount_pairing_responder(
    app=a2a_app,
    agent_id=AGENT_ID,
    trust_badge=TRUST_BADGE,
    registry_url=REGISTRY_URL,
    ca_cert_path=CA_CERT_PATH,
)

# 3. Run with uvicorn (TLS required)
```

The pairing responder is additive. It adds one endpoint to your existing app. It does not modify your executor, your agent card, or your domain logic.
