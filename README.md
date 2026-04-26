# Cyrano de Bergerac A2A System (Secure)

A two-agent system demonstrating Agent-to-Agent (A2A) communication with a full Infrastructure Trust Plane. Chris (CLI client, no LLM) talks to Cyrano (A2A server, LLM) over HTTPS, but only after verifying through the Agent Registry that Cyrano is an authorized agent.

The system mirrors the central dynamic of Rostand's *Cyrano de Bergerac* (1897).

In the play, Chris (Christian) speaks with Roxanne while Cyrano composes Chris's words from the shadows. In this two-agent system, Chris is a CLI agent that speaks with the user, who stands in for Roxanne. When Chris receives a message, Chris passes it to Cyrano for a response.

With this basic dynamic in place, this repo adds trust infrastructure: TLS for transport security, and an Agent Registry for agent verification.

## Trust planes

When a user sends a message through an agent, and that agent accesses infrastructure services to produce a response, three independent trust concerns are active simultaneously. Each concern defines a trust plane. Each plane asks two questions: one about identity (who or what is this?) and one about authority (what is it allowed to do?).

| Plane | Identity | Authority |
|-------|----------|-----------|
| **Infrastructure** | Is this service genuine? (TLS, Registry) | Does this agent have access to this resource? |
| **Agent** | Is this agent who it claims to be? (Registry verification, pairing) | Does this user have permission to use this agent? |
| **User** | Is this human who they claim to be? (Identity provider) | What actions can this user perform? |

Each plane actively produces the trust context that gives adjacent planes their meaning. The Infrastructure Plane produces verified service identity (TLS, Registry assertions) that the Agent Plane consumes. The Agent Plane produces authorization decisions that give user identity its operational effect. Governance follows from context production: the authority question at each plane governs not only peer access within the plane but access from the plane above.

The planes are independent in failure: a request can fail on any plane regardless of the others. A valid TLS connection says nothing about whether the organization authorized the agent. An authorized agent says nothing about whether the user has permission. All three planes are evaluated for every request; they do not form a sequential pipeline.

We use "planes" (not "layers") for consistency, just as we use "pairing" (not "handshaking") for agent identity verification. For the full Trust Planes reference, including boundary questions and the autonomy distinction between infrastructure and agents, see `Architecture/trust-planes.md`.

**This repo implements the Infrastructure Trust Plane.** The User and Agent Planes are documented as architectural context; they are not implemented.

## Why the Agent Registry exists alongside TLS

TLS certificate authorities are external to any single organization. Any server operator can obtain a valid TLS certificate. TLS answers "am I talking to the server at this endpoint?" It does not answer "did this organization authorize this agent?"

The Agent Registry fills this gap. It performs the same structural function for agent service identity that a TLS CA performs for transport identity: it is the authority the organization controls that decides which agents are authorized, records that decision, and issues short-lived assertions that clients can verify. Chris requires both a valid TLS connection and a valid Registry assertion before routing any user messages.

## Distance to production

This is a teaching repository and a proof of concept for the Infrastructure Trust Plane. It implements a production trust architecture for agent pairing, running locally on one machine so that every mechanism is visible, testable, and understandable.

**What is production-grade:**

- **The Agent Registry and its role.** The Registry is a standalone service that stores agent records, mediates pairing challenges, and issues signed assertions. The API surface, the data model, and the pairing protocol are production mechanisms. In production, this service runs behind a load balancer; here it runs on localhost:8003.

- **The pairing protocol.** The challenge-response sequence, the Trust Badge verification, the signed assertion, and the client-side verification are all production mechanisms. The three-party protocol (Chris initiates, Cyrano proves to Registry, Registry vouches to Chris) exists to keep the Trust Badge out of Chris's hands. That constraint applies identically in production.

- **The trust model.** Two independent authority structures operate in parallel: a TLS CA for transport identity, and the Agent Registry for agent service identity. Chris requires both. This separation exists because TLS CAs are shared global infrastructure that no single organization controls.

- **HMAC-SHA256 assertion signing.** The proof of concept uses symmetric HMAC, where the Registry and Chris share the same key. Production would use asymmetric signatures (RS256 or Ed25519) so the verification key can be distributed publicly. The assertion format, the fields signed, and the verification logic are otherwise the same. Swapping HMAC for asymmetric signatures is a key management change, not an architectural one.

- **Failure behavior.** Chris refuses to proceed when the agent is unknown, unapproved, when the Trust Badge is wrong, or when the assertion is invalid or expired. These are production failure modes.

**What differs from production:**

- **The Mock TLS CA.** In production, TLS certificates come from commercial certificate authorities (Let's Encrypt, DigiCert, Google Trust Services). The Mock TLS CA stands in for that infrastructure. It generates a local root certificate and issues server certs signed by it, so that every TLS connection follows the correct verification path rather than skipping verification. The Mock TLS CA teaches the right trust model; it anchors trust in a local root instead of a public one.

- **Localhost instead of DNS.** All services run on localhost with different ports. Production would use separate hosts with real domain names.

- **JSON file instead of a database.** The Registry stores agent records in a JSON file. Production would use a database with CRUD operations, audit logging, and access controls. The data model (agent ID, endpoint, status, Trust Badge hash) is the same.

- **Single Cyrano instance.** A production deployment would support many agents, each owned by a different organizational unit. This repo has one.

The distance from this repo to production is infrastructure, not architecture.

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

## Setup and running

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

- `GEMINI_API_KEY`: your Gemini API key (get one at https://aistudio.google.com/apikey)
- `CYRANO_TRUST_BADGE`: copy the value from `certs/cyrano_trust_badge.txt`
- `CHRIS_CREDENTIAL`: copy the value from `certs/chris_credential.txt`

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

- **Unknown agent:** `python3 main.py chat fake-agent` prints "Agent not found" and exits.
- **Wrong Trust Badge:** Change `CYRANO_TRUST_BADGE` in `.env` to a wrong value, restart Cyrano, run `python3 main.py chat`. Prints "pairing verification failed" and exits.

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

- `Architecture/How-Pairing-Works/`: per-entity pairing documentation (overview, registry builders, chris builders, cyrano builders, and a welcome package for external teams)
- `Architecture/z-archive/`: original pre-implementation specification (archived; current system documented in How-Pairing-Works/)
- `Architecture/system-architecture.md`: system topology, module structure, credential provenance, key abstractions
- `Architecture/ORIGINS.md`: the literary metaphor and why Chris is the interesting design element
- `Architecture/llm-voice-and-context.md`: voice service and context compaction design
- `a2a_trust_pairing/README.md`: API reference for the portable pairing module

## Upstream

Forked from [Cyrano-de-Bergerac-A2A](https://github.com/jsweet8258/Cyrano-de-Bergerac-A2A). The upstream repo implements the same two-agent system without the trust infrastructure.
