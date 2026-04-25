# Cyrano de Bergerac A2A System (Secure)

A two-agent system demonstrating Agent-to-Agent (A2A) communication with a full Infrastructure Trust Plane. Chris (CLI client, no LLM) talks to Cyrano (A2A server, LLM) over HTTPS, but only after verifying through the Agent Registry that Cyrano is an authorized agent.

The system mirrors the play's central dynamic: Chris faces the audience, Cyrano composes the words from the shadows. What this fork adds is the trust infrastructure that makes the connection verifiable.

## Trust planes

The OpenBeavs security architecture organizes trust into three independent planes. Each plane addresses a different question, and a request can fail on any plane independently of the others:

- **Infrastructure Trust Plane** -- Are these services genuine? Covers transport identity (TLS: is this connection going to the right server?) and agent service identity (Agent Registry: is this agent authorized by OSU?). This is what this repo builds.
- **User Trust Plane** -- Is this human who they claim to be? Covers authentication via identity providers (e.g., ONID/Microsoft at OSU). Not implemented in this repo.
- **Agent Trust Plane** -- Is this user allowed to use this agent? Covers per-user authorization, access control, and business rules enforced by individual agents. Not implemented in this repo.

The planes are not a stack where one sits on top of another. They are orthogonal concerns that intersect: a single message might need to satisfy all three simultaneously. The word "plane" (not "layer") reflects this. Layers imply vertical dependency. Planes imply independent dimensions.

This repo is a proof of concept for the Infrastructure Trust Plane. The other two planes are where production OpenBeavs adds human authentication and per-user authorization.

## What this repo is and how it relates to production

This is a teaching repository. It implements the production security architecture for OpenBeavs agent pairing, running locally on one machine. The design is not a simulation or a simplified sketch. It is the real protocol, the real trust model, and the real separation of concerns, built to run on localhost so that every mechanism is visible, testable, and understandable.

**What is identical to production:**

- **The Agent Registry and its role.** The Registry is a standalone service that stores agent records, mediates pairing challenges, and issues signed assertions. In production, this service runs in Google Cloud behind a load balancer. Here it runs on localhost:8003. The API surface, the data model, and the pairing protocol are the same.

- **The pairing protocol.** The challenge-response sequence, the Trust Badge verification, the signed assertion, and the client-side verification are all production mechanisms. The three-party handshake (Chris initiates, Cyrano proves to Registry, Registry vouches to Chris) exists to keep the Trust Badge out of Chris's hands. That constraint applies identically in production.

- **The trust model.** Two independent authority structures operate in parallel: a TLS CA for transport identity, and the Agent Registry for agent service identity. Chris requires both. This separation exists because TLS CAs are shared global infrastructure that OSU does not control. That fact does not change between development and production.

- **HMAC-SHA256 assertion signing.** The proof of concept uses symmetric HMAC, where the Registry and Chris share the same key. Production would use asymmetric signatures (RS256 or Ed25519) so the verification key can be distributed publicly. The assertion format, the fields signed, and the verification logic are otherwise the same. Swapping HMAC for asymmetric signatures is a key management change, not an architectural one.

- **Failure behavior.** Chris refuses to proceed when the agent is unknown, unapproved, when the Trust Badge is wrong, or when the assertion is invalid or expired. These are production failure modes. The error messages and exit behavior are what a production client would do.

**What differs from production:**

- **The Mock TLS CA.** This is the one component that does not exist in production. In production, TLS certificates come from commercial TLS certificate authorities: Let's Encrypt, DigiCert, Google Trust Services, or whatever TLS CA the organization uses. Those CAs verify domain ownership and issue certificates that browsers and clients already trust. The Mock TLS CA stands in for that infrastructure. It generates a local root certificate and issues server certs signed by it, so that every TLS connection in the system follows the correct verification path (client checks cert, cert chains to trusted root) rather than skipping verification. The Mock TLS CA teaches the right trust model; it just anchors it in a local root instead of a public one.

- **Localhost instead of DNS.** All services run on localhost with different ports. In production, the Registry, Cyrano, and Chris would be separate hosts with real domain names. The certificates would have SANs matching those domains instead of `localhost` and `127.0.0.1`.

- **JSON file instead of a database.** The Registry stores agent records in a JSON file loaded at startup. Production would use a database with CRUD operations, audit logging, and access controls. The data model (agent ID, endpoint, status, Trust Badge hash) is the same.

- **Single Cyrano instance.** Production OpenBeavs supports many Cyrano agents, each owned by a different OSU unit. This repo has one.

The distance from this repo to production is infrastructure, not architecture. The security model, the protocol, the separation of trust planes, and the pairing mechanism do not change. What changes is where the services run, who issues the TLS certificates, and how the Registry stores its data.

## Why the Agent Registry exists alongside TLS

TLS certificate authorities are external to OSU. Any server operator can obtain a valid TLS certificate. A server with a valid cert, a well-formed agent card, and a working LLM is indistinguishable from an OSU-authorized agent at the transport level. TLS answers "am I talking to the server at this endpoint?" It does not answer "did OSU authorize this agent?"

The Agent Registry performs the same structural function for agent service identity that a TLS certificate authority performs for transport identity, but one level up: it is the authority OSU controls that decides which agents are authorized, records that decision, and issues short-lived assertions that Chris can verify. Chris requires both a valid TLS connection and a valid Registry assertion before routing any user messages.

## Architecture

Four entities, all communicating over TLS:

```
┌───────────────┐         ┌──────────────────┐         ┌───────────────┐
│   Chris CLI   │──TLS───▶│  Agent Registry   │◀──TLS──│    Cyrano     │
│  (no LLM)     │         │  (HTTPS :8003)    │         │ (HTTPS :8002) │
│               │──TLS────────────────────────────TLS──▶│               │
└───────────────┘         └──────────────────┘         └───────────────┘
        ▲
        │
   Mock TLS CA root cert
   (trusted by all)
```

**Pairing protocol** (runs before every chat session):

1. Chris queries the Registry for the agent record and status
2. Chris requests a challenge token from the Registry
3. Chris sends the challenge to Cyrano's `/pairing/respond` endpoint
4. Cyrano proves its identity to the Registry using its Trust Badge
5. The Registry validates the badge, issues a signed pairing assertion
6. Cyrano relays the assertion to Chris
7. Chris verifies the assertion (HMAC signature, agent_id, expiration)
8. Only then does Chris open the A2A session and route user messages

If any step fails, Chris prints a specific error and exits.

## Setup and Running

### Step 0: Generate certificates and trust credentials

```bash
python3 scripts/mock_ca.py
```

This creates the `certs/` directory containing:

- Mock TLS CA root certificate and key
- Server certificates for the Registry and Cyrano
- A Trust Badge for Cyrano (shared secret with the Registry)
- An HMAC signing key (shared between the Registry and Chris)
- A Chris credential (shared secret between Chris and the Registry)

The script also updates `registry/agents.json` with the Trust Badge hash and Chris credential hash.

### Step 1: Create your environment file

```bash
cp .env.example .env
```

Edit `.env` and fill in:

- `GEMINI_API_KEY` -- your Gemini API key (get one at https://aistudio.google.com/apikey)
- `CYRANO_TRUST_BADGE` -- copy the value from `certs/cyrano_trust_badge.txt`
- `CHRIS_CREDENTIAL` -- copy the value from `certs/chris_credential.txt`

The remaining values have sensible defaults. See `.env.example` for the full list.

### Step 2: Install dependencies

```bash
pip install -r requirements.txt
```

### Step 3: Run the system (three terminals)

**Terminal 1: Agent Registry**

```bash
python3 main.py serve registry
```

You should see: `Agent Registry running on https://localhost:8003`

**Terminal 2: Cyrano**

```bash
python3 main.py serve cyrano
```

You should see: `Cyrano A2A server running on https://localhost:8002`

**Terminal 3: Chris**

```bash
python3 main.py chat
```

You should see the pairing sequence print step by step, ending with `Trust Status: [APPROVED]`, then the chat prompt. Type a message and press Enter. Type `/exit` or press Ctrl+C to quit.

To connect to a specific agent (default is `cyrano-001`):

```bash
python3 main.py chat cyrano-001
```

### Testing failure modes

With the Registry and Cyrano running:

- **Unknown agent:** `python3 main.py chat fake-agent` -- prints "Agent not found" and exits.
- **Wrong Trust Badge:** Change `CYRANO_TRUST_BADGE` in `.env` to a wrong value, restart Cyrano, run `python3 main.py chat` -- prints "pairing verification failed" and exits.

## Key files

```
chris/chris.py                  Chris CLI client with pairing protocol
cyrano/cyrano.py                Cyrano A2A HTTPS server with /pairing/respond
registry/agent_registry.py      Agent Registry (pure A2A service, three skills)
registry/agents.json            Agent and client records (type, status, credential hashes)
a2a_trust_pairing/              Portable pairing module (shared by Chris and Cyrano)
scripts/mock_ca.py              Mock TLS CA: generates certs and trust credentials
main.py                         Entry point for all three services
services/llm_voice_context/     Voice (audited LLM calls) and context (compaction)
services/env_validator.py       Environment validation (fail fast)
Architecture/How-Pairing-Works/ Per-entity pairing documentation and builder welcome package
Architecture/                   Design rationale and system documentation
```

## Design documents

- `Architecture/How-Pairing-Works/` -- per-entity pairing documentation: overview, registry builders, chris builders, cyrano builders, and a welcome package for external teams
- `Architecture/z-archive/OpenBeavs - Infrastructure Trust Plane - Engineering Requirements - v2026-0423.md` -- original pre-implementation specification (archived; current system documented in How-Pairing-Works/)
- `Architecture/system-architecture.md` -- system topology, module structure, credential provenance, key abstractions
- `Architecture/ORIGINS.md` -- the literary metaphor and why Chris is the interesting design element
- `Architecture/llm-voice-and-context.md` -- voice service and context compaction design
- `a2a_trust_pairing/README.md` -- API reference for the portable pairing module

## Upstream

Forked from [Cyrano-de-Bergerac-A2A](https://github.com/jsweet8258/Cyrano-de-Bergerac-A2A). The upstream repo implements the same two-agent system without the trust infrastructure.

James was here
