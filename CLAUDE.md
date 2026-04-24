# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Cyrano de Bergerac is a two-agent system demonstrating Agent-to-Agent (A2A) communication with a full Infrastructure Trust Plane. Two agents mirror the play: Chris (CLI chat client, the user's interface) and Cyrano (hidden wordsmith, A2A server). Chris sends messages to Cyrano via the A2A protocol over HTTPS; Cyrano crafts eloquent replies. Chris makes no LLM calls; all creative work happens in Cyrano.

Before routing any user messages, Chris verifies that Cyrano is an OSU-authorized agent through the Agent Registry. The Registry performs the same structural function for agent service identity that a TLS certificate authority performs for transport identity. TLS proves domain identity (the server is who it claims to be); the Registry proves agent service identity (the agent is authorized by OSU). Both checks are required.

## Setup & Running

### First-time setup

```bash
# 0. Generate certificates and trust credentials
python3 scripts/mock_ca.py

# 1. Install dependencies
pip install -r requirements.txt

# 2. Create .env from example and fill in values
cp .env.example .env
```

Requires a `.env` file with `GEMINI_API_KEY`, `CYRANO_MODEL`, and `CYRANO_TRUST_BADGE` (see `.env.example`). Copy the Trust Badge value from `certs/cyrano_trust_badge.txt` into `.env`. The setup script also updates `registry/agents.json` with the Trust Badge hash.

### Run the system (three terminals)

```bash
# Terminal 1: Start the Agent Registry
python3 main.py serve registry

# Terminal 2: Start Cyrano's A2A server
python3 main.py serve cyrano

# Terminal 3: Start the chat client (runs pairing, then chat)
python3 main.py chat
```

## Architecture

Four entities, all communicating over TLS:

```
User (CLI) → Chris → [pairing via Registry] → [A2A :8002 HTTPS] → Cyrano → reply back
```

| Path | Role |
|------|------|
| `agents/chris.py` | CLI chat client. Pure relay, no LLM. Runs full pairing protocol before chat: queries Registry, sends challenge to Cyrano, verifies signed assertion. Then routes user messages to Cyrano via `A2AClient` over HTTPS. |
| `agents/cyrano.py` | A2A HTTPS server. Implements `AgentExecutor` from the `a2a-sdk`. Crafts eloquent replies via the voice service. Exposes `/pairing/respond` endpoint: receives challenge from Chris, proves identity to Registry, relays signed assertion back. |
| `registry/agent_registry.py` | Agent Registry HTTPS server. Authorizes agents (agent service identity). Stores agent records in `registry/agents.json`. Exposes `/agents/{id}`, `/pairing/challenge`, `/pairing/verify`. Signs pairing assertions with HMAC-SHA256. |
| `scripts/mock_ca.py` | Mock TLS CA. Generates server certs, Trust Badge, and HMAC signing key. Run once before starting any service. |
| `main.py` | Entry point. `serve registry` starts the Registry on :8003; `serve cyrano` starts Cyrano on :8002; `chat [agent_id]` starts Chris. |
| `services/llm_voice_context/` | Voice and context services. `llm_call()` makes audited Gemini API calls; `ConversationContext` manages history with three-tier compaction (90% trigger, post-compaction <=30%). |
| `services/env_validator.py` | Environment validator. Checks required vars, warns on missing optional vars with defaults, fails fast. |

### Key files and directories

- `Architecture/` -- System diagrams, literary origins, design principles, Infrastructure Trust Plane ERD
- `registry/` -- Agent Registry: `agent_registry.py` (FastAPI HTTPS server), `agents.json` (agent records)
- `scripts/` -- `mock_ca.py` (Mock TLS CA, certs, trust credentials)
- `certs/` -- Generated TLS certificates and trust credentials (gitignored)
- `services/` -- Shared services: `llm_voice_context/` (voice + context), `env_validator.py`. Portable between projects.
- `tmp/` -- Runtime logs (gitignored): `a2a-backend.log`, `{agent}-voice.log`
- `API-Key/` -- API key storage (gitignored)
- `.env` -- Runtime config (gitignored), created from `.env.example`

### Key Dependencies

- `a2a-sdk` -- A2A protocol support (server: `AgentExecutor`, `A2AFastAPIApplication`, `DefaultRequestHandler`; client: `A2AClient`)
- `google-genai` (v1.x) -- Gemini API SDK, used by the voice service for LLM calls
- `fastapi` + `uvicorn` -- HTTPS server for Cyrano's A2A endpoint and the Agent Registry
- `httpx` -- HTTPS client used by Chris and Cyrano (for Registry calls)
- `cryptography` -- TLS certificate generation in `scripts/mock_ca.py`
- Cyrano uses a Gemini model via `CYRANO_MODEL` env var. See `Architecture/LLM-Strategy.md` for model rationale.
- Infrastructure vars: `CONTEXT_MANAGER_LLM` (defaults to `CYRANO_MODEL`), `CONTEXT_MAX` (defaults to 131072). See `.env.example`.
- Trust Plane vars: `CYRANO_TRUST_BADGE`, `CYRANO_AGENT_ID`, `REGISTRY_URL`, `CA_CERT_PATH`, `PAIRING_VERIFY_KEY`. See `.env.example`.

### Voice + Context Architecture

The voice service wraps every LLM call with audit logging. Cyrano calls `voice.llm_call()` to generate a response; the voice service makes the Gemini API call and logs the exchange (timestamp, session ID, turn number, model, input, output, token usage) to `tmp/cyrano-voice.log`.

The context service manages conversation history. Each message (inbound and outbound) is tracked in a `ConversationContext` instance. When history approaches 90% of `CONTEXT_MAX`, the context service compacts it into three tiers (distant summary, recent summary, verbatim recent) before the next LLM call.

**Audit logs:** Per-agent JSON-line files in `tmp/{agent}-voice.log`. Each entry: UTC timestamp, session_id, turn number, model, input, output, token usage. Logs only the delta, never full history.

### A2A protocol details

Cyrano's A2A server is built with the `a2a-sdk` directly (no ADK). The server exposes an `AgentCard` at `/.well-known/agent-card.json` and handles `SendMessage` requests via JSON-RPC over HTTPS. Chris uses `A2AClient` (from `a2a-sdk`) to send messages and receive replies. Conversation continuity is maintained via a `contextId` that Chris generates at startup and includes in every message.

### Infrastructure Trust Plane

The Agent Registry performs for agent service identity the same structural function that a TLS certificate authority performs for transport identity. TLS certificate authorities are external to OSU and cannot express OSU authorization. The Registry fills this gap: it is the authority OSU controls that decides which agents are authorized, records that decision, and issues short-lived pairing assertions that Chris can verify.

Pairing protocol (runs before every chat session):
1. Chris queries Registry for agent record and status
2. Chris requests a challenge token from Registry
3. Chris sends the challenge to Cyrano's `/pairing/respond`
4. Cyrano proves identity to Registry with its Trust Badge
5. Registry issues a signed pairing assertion
6. Cyrano relays the assertion to Chris
7. Chris verifies the assertion (HMAC signature, agent_id, expiration)

See `Architecture/OpenBeavs - Infrastructure Trust Plane - Engineering Requirements - v2026-0423.md` for the full design rationale.

## Current status

- Infrastructure Trust Plane implemented and tested end-to-end (2026-04-23).
- Four-entity architecture: Mock TLS CA, Agent Registry, Cyrano (HTTPS), Chris CLI.
- All communication over TLS. Certificates issued by Mock TLS CA.
- Full pairing protocol: challenge-response with Registry-mediated verification.
- Failure modes verified: unknown agent, unapproved agent, tampered assertion, expired assertion.
- Cyrano runs as a pure a2a-sdk server (no ADK dependency). Voice + context services wired in. Audit logs verified working.
- Chris runs as a CLI chat client with pairing-before-chat. Maintains conversation continuity via context_id.
- API key is configured and verified working. Model: Gemini 3.1 Pro (Cyrano).
- Forked from https://github.com/jsweet8258/Cyrano-de-Bergerac-A2A (upstream).

## Design principles

- **Working System Principle** -- always go from working system to working system. Never write code that "doesn't work yet." See `Architecture/working-system-principle.md`.
- **UX Design Principles** -- announce before you act, errors must be unmissable, surface results not machinery. See `Architecture/ux-design-principles.md`.
- **The Play Metaphor** -- the system mirrors Cyrano de Bergerac: Chris is the front man who faces the audience, Cyrano is the hidden talent. See `Architecture/ORIGINS.md`.

## Standing directive

Claude acts as an expert software architect. When writing or reviewing code, Claude applies the Feynman Standard as a quality lens: explain why, not just what; teach without announcing you are teaching. The Feynman Standard governs all project writing, not just code: READMEs, documentation, and commit messages. When a design has a structural weakness, a maintenance risk, or an unnecessary complexity, Claude flags it directly. Claude does not merely present options; Claude recommends, explains why, and flags where the recommendation requires author judgment. The author values honest technical judgment over agreement.

Documentation is load-bearing infrastructure, not a supplement. Document the *why*, not just the *what* or *how*: design rationale, dependency order, tradeoffs, and the constraints that shaped the architecture. The project is not done when the system works; it is done when someone who has never seen it can read the documentation and understand it well enough to maintain it, extend it, or replicate it from scratch.

Key principles:

1. **Orient before you explain.** A reader should know within thirty seconds what a system is, whether it works, and where to look for depth.
2. **Document for replication.** If the documentation does not teach someone to rebuild the subsystem from scratch, it teaches operation, not understanding.
3. **State the why.** Knowing how enables operation. Knowing why enables understanding. Both are required.
4. **Name what you chose against.** For every non-trivial design choice, name the alternatives considered and rejected, with reasoning.
5. **Layer insights at multiple depths.** The same decision appears in code comments (while working), architecture docs (while studying), and strategy docs (while deciding). Each layer cites the others.
6. **The written requirement.** The builder owes a duty to externalize what they learned. A system that ships without teaching what the builder understood is incomplete.
7. **First-principles reflection.** Before acting on a directive, verify that its reasoning holds. If it does not, say so directly.
