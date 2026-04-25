# OpenBeavs Agent Pairing: Infrastructure Trust Plane Engineering Requirements

Version 2026-0423

## Purpose

This document defines the engineering requirements for a working proof of concept of the OpenBeavs Infrastructure Trust Plane: the mechanism by which a dumb A2A client (Chris) verifies that it is talking to an authorized A2A server (Cyrano), not an impostor.

Chris has no LLM. It is a thin protocol client. Cyrano has the LLM and the domain expertise. The entire challenge is authentication at pairing time: Chris must know, before routing any user messages, that the Cyrano it is about to connect to is authorized by OSU.

This document both teaches the core concepts and specifies the system that must be built. It follows the Feynman Standard for systems knowledge: the how and the why, captured in a form that enables the next person to maintain, extend, or replicate the system without the builder's presence.

## Core concept: why the Agent Registry exists alongside TLS

The A2A specification requires HTTPS for all production communication (Section 7.1). TLS certificates prove domain identity: the server at `cyrano.example.com` holds a certificate issued for that domain, and the connection is confidential and authenticated at the transport level.

But TLS certificate authorities are external to OSU. Let's Encrypt, DigiCert, Google Trust Services: any of them will issue a valid certificate to any server operator who proves domain control. OSU does not decide who gets a TLS certificate. OSU has no veto. Any A2A server operator can get one.

This means TLS alone cannot express OSU authorization. A server with a valid TLS certificate, a well-formed agent card, and a working LLM is indistinguishable from an OSU-authorized agent at the transport level. TLS answers "am I talking to the server at this endpoint?" It does not answer "did OSU authorize this agent?"

**The Agent Registry performs the same structural function for agent service identity that a TLS certificate authority performs for transport identity.** It is the authority OSU controls that decides which agents are authorized, records that decision, and issues short-lived assertions that Chris can verify.

Two independent authority structures operate in parallel:

- **TLS CA** (external to OSU): asserts "this server controls this domain"
- **Agent Registry** (controlled by OSU): asserts "this agent is authorized by OSU"

Chris requires both assertions to proceed. The first comes from the TLS handshake. The second comes from the pairing protocol mediated by the Registry.

Both operate within the Infrastructure Trust Plane. TLS handles transport-level identity. The Registry handles service-level identity. They answer independent questions. A connection can pass TLS and fail registry verification (unauthorized agent with a valid cert). A connection can pass registry verification and fail TLS (authorized agent with an expired cert). Both checks must pass.

## Trust planes context

The OpenBeavs trust architecture organizes trust into three independent planes. Each plane addresses a different question, and a request can fail on any plane independently of the others:

- **Infrastructure Trust Plane** -- Are these services genuine? Transport identity (TLS), agent service identity (Agent Registry), and the pairing protocol that binds them.
- **User Trust Plane** -- Is this human who they claim to be? Authentication via identity providers (e.g., ONID at OSU).
- **Agent Trust Plane** -- Is this agent authorized to serve this user? Access control, business rules, and per-user authorization decisions.

The planes are not a stack where one sits on top of another. They are orthogonal concerns that intersect: a single message might need to satisfy all three simultaneously. The word "plane" (not "layer") reflects this. Layers imply vertical dependency. Planes imply independent dimensions.

This proof of concept builds the Infrastructure Trust Plane. The User Trust Plane and Agent Trust Plane are absent from the hello world: there is no human authentication and no per-user authorization. Those planes are where production OpenBeavs adds the rest of the trust model.

## System entities

The proof of concept comprises four entities. All network communication uses TLS.

### 1. Mock TLS CA

A local TLS certificate authority that issues TLS certificates for the Registry and Cyrano, and whose root certificate all parties trust.

**What it is:** A setup-time artifact, not a running service. You run it once before any service starts. It produces a root certificate, server certificates, and private keys.

**Why it exists:** The A2A specification requires HTTPS and recommends that clients verify server certificates against trusted CAs (Section 7.2). In local development, there is no public DNS and no public CA will issue certificates for localhost or private addresses. The Mock TLS CA satisfies the A2A TLS requirement for development and testing while keeping the certificate verification path honest: Chris validates certs against a known root, not by skipping validation.

**What it produces:**

- Root CA certificate (trusted by Chris, Cyrano, and the Registry)
- Server certificate and private key for the Agent Registry
- Server certificate and private key for Cyrano

**Why not self-signed certificates on each server:** Self-signed certificates require each client to trust each individual server cert. The Mock TLS CA provides a single root of trust, which mirrors how TLS works in production: clients trust a CA, the CA vouches for servers. This means the development setup teaches the correct trust model rather than a shortcut.

### 2. Agent Registry

An HTTPS API server that stores agent records and mediates the pairing handshake. It performs the same structural function for agent service identity that a TLS certificate authority performs for transport identity: it is the authority OSU controls that decides which agents are authorized, records that decision, and issues short-lived assertions that clients can verify.

**What it is:** A single-process HTTPS server backed by a configuration file (JSON). It holds the authoritative list of agents and their trust status.

**What it stores per agent:**

- Agent ID (unique identifier)
- Display name
- Endpoint URL (the HTTPS address where the agent listens)
- Trust status: `approved`, `provisional`, or `unapproved`
- Trust Badge hash (a salted hash of the agent's shared secret; the Registry never stores the raw secret)

**What it holds for itself:**

- A signing key used to issue short-lived pairing assertions
- A verification key shared with Chris so Chris can verify those assertions

**API surface (minimum viable):**

```
┌──────────────────────┬────────┬───────────┬──────────────────────────────────────────────────────┐
│ Endpoint             │ Method │ Called by │ Purpose                                              │
├──────────────────────┼────────┼───────────┼──────────────────────────────────────────────────────┤
│ /agents/{agent_id}   │ GET    │ Chris     │ Look up agent record: endpoint, status.               │
│                      │        │           │ Does not return the Trust Badge hash.                 │
├──────────────────────┼────────┼───────────┼──────────────────────────────────────────────────────┤
│ /pairing/challenge   │ POST   │ Chris     │ Initiate a pairing challenge for a given agent ID.   │
│                      │        │           │ Returns a challenge token.                           │
├──────────────────────┼────────┼───────────┼──────────────────────────────────────────────────────┤
│ /pairing/verify      │ POST   │ Cyrano    │ Cyrano proves identity by presenting its Trust Badge │
│                      │        │           │ along with the challenge token. If valid, the        │
│                      │        │           │ Registry returns a signed, short-lived pairing       │
│                      │        │           │ assertion.                                           │
└──────────────────────┴────────┴───────────┴──────────────────────────────────────────────────────┘
```

**What it does not do:** The Registry does not proxy messages between Chris and Cyrano. After pairing, Chris talks directly to Cyrano. The Registry is involved only at pairing time.

### 3. Cyrano (A2A server)

An HTTPS A2A-compliant server with an LLM behind it. It serves domain-specific expertise and proves its identity to the Registry during the pairing handshake.

**What it holds:**

- Its Trust Badge: a shared secret between Cyrano and the Agent Registry, used to prove identity during pairing. Cyrano never reveals the Trust Badge to Chris.
- Its A2A agent card, served at the well-known endpoint per the A2A specification.
- Access to an LLM for generating responses.

**A2A compliance:** Cyrano serves the standard A2A endpoints. For the proof of concept, the minimum is:

- `/.well-known/agent-card.json` -- agent card discovery
- A2A message endpoint for receiving tasks and returning responses

**Pairing behavior:** When Chris initiates pairing, Cyrano receives a challenge token (relayed by Chris or fetched directly). Cyrano proves its identity to the Registry by presenting its Trust Badge and the challenge token to the Registry's `/pairing/verify` endpoint. If the Registry validates both, it returns a signed pairing assertion. Cyrano passes this assertion to Chris.

### 4. Chris CLI

A command-line A2A client with no LLM. It takes user input from stdin, routes it to a verified Cyrano, and prints responses to stdout.

**What it does:**

1. Accepts an agent ID as a command-line argument
2. Queries the Agent Registry for the agent's record and endpoint
3. Executes the pairing protocol (described below) to verify the agent is authorized
4. If pairing succeeds, opens an A2A session and routes user messages to Cyrano
5. Prints Cyrano's responses to stdout
6. If pairing fails, prints a clear explanation and exits

**What it holds:**

- The Agent Registry's URL
- The Mock TLS CA root certificate (for TLS verification)
- The Registry's verification key or the ability to call a Registry introspection endpoint (for checking pairing assertions)

**What it does not hold:** Chris has no LLM, no Trust Badge, and no secrets belonging to Cyrano or the Registry's signing key.

## Pairing protocol

The pairing protocol is the sequence by which Chris verifies that a Cyrano agent is authorized by OSU before routing any user messages. It involves all three running entities: Chris, the Agent Registry, and Cyrano.

### Why this design and not simpler alternatives

**Alternative considered: Chris asks the Registry directly, "is agent X legitimate?"**

In this design, Chris queries the Registry and gets back a yes/no answer. The problem: this proves the Registry has a record for agent X, but it does not prove that the server at the endpoint *is* agent X. An attacker who compromises DNS or the endpoint URL could serve a different agent at the registered address. The Registry said "agent X is approved," but nothing proved the server Chris is about to talk to is actually agent X.

**Alternative considered: Cyrano presents its Trust Badge directly to Chris.**

This would require Chris to know the Trust Badge (or its hash) and Cyrano to reveal the secret on the wire between them. The Trust Badge becomes a shared secret between three parties (Cyrano, Registry, Chris), increasing the attack surface. If Chris is compromised, the Trust Badge leaks. The Registry-mediated design keeps the Trust Badge as a two-party secret between Cyrano and the Registry only.

**Chosen design: Registry-mediated pairing with a challenge-response and signed assertion.**

Chris initiates. Cyrano proves identity to the Registry. The Registry vouches for Cyrano by issuing a signed assertion that Chris can verify. The Trust Badge never leaves the Cyrano-Registry relationship. Chris trusts the Registry's signature, not Cyrano's secret.

### Sequence

```
Chris                          Registry                         Cyrano
  |                               |                               |
  |  1. GET /agents/{agent_id}    |                               |
  |------------------------------>|                               |
  |  agent record (endpoint, status)                              |
  |<------------------------------|                               |
  |                               |                               |
  |  [Chris checks: status is approved or provisional]            |
  |                               |                               |
  |  2. POST /pairing/challenge   |                               |
  |     {agent_id}                |                               |
  |------------------------------>|                               |
  |  challenge_token              |                               |
  |<------------------------------|                               |
  |                               |                               |
  |  3. Send challenge_token to Cyrano                            |
  |-------------------------------------------------------------->|
  |                               |                               |
  |                               |  4. POST /pairing/verify      |
  |                               |     {agent_id,                |
  |                               |      challenge_token,         |
  |                               |      trust_badge}             |
  |                               |<------------------------------|
  |                               |                               |
  |                               |  [Registry validates:         |
  |                               |   - trust_badge matches       |
  |                               |   - challenge_token is valid  |
  |                               |   - agent status is approved  |
  |                               |     or provisional]           |
  |                               |                               |
  |                               |  signed pairing_assertion     |
  |                               |----------------------------->|
  |                               |                               |
  |  5. Cyrano returns pairing_assertion to Chris                 |
  |<--------------------------------------------------------------|
  |                               |                               |
  |  [Chris verifies:                                             |
  |   - assertion signature is valid (Registry's key)             |
  |   - assertion is not expired                                  |
  |   - assertion names the correct agent_id]                     |
  |                               |                               |
  |  6. Pairing complete. A2A session begins.                     |
  |<------------------------------------------------------------->|
```

### Pairing assertion contents

The pairing assertion is a short-lived, signed token issued by the Registry. It contains:

- `agent_id` -- the agent this assertion vouches for
- `issued_at` -- timestamp of issuance
- `expires_at` -- expiration (short-lived; minutes, not hours)
- `registry_signature` -- HMAC or digital signature using the Registry's signing key

### Failure modes

```
┌─────────────────────────────────┬────────────────────┬──────────────────────────────────────────────┐
│ Failure                         │ Who detects        │ What happens                                 │
├─────────────────────────────────┼────────────────────┼──────────────────────────────────────────────┤
│ Agent ID not in Registry        │ Chris (step 1)     │ Chris prints "agent not found" and exits     │
├─────────────────────────────────┼────────────────────┼──────────────────────────────────────────────┤
│ Agent status is unapproved      │ Chris (step 1)     │ Chris prints "agent is not approved" and     │
│                                 │                    │ exits                                        │
├─────────────────────────────────┼────────────────────┼──────────────────────────────────────────────┤
│ Challenge token expired or      │ Registry (step 4)  │ Registry rejects; Cyrano cannot obtain       │
│ invalid                         │                    │ assertion; Chris times out or receives error  │
├─────────────────────────────────┼────────────────────┼──────────────────────────────────────────────┤
│ Trust Badge mismatch            │ Registry (step 4)  │ Registry rejects; same as above. Registry    │
│                                 │                    │ logs the event.                              │
├─────────────────────────────────┼────────────────────┼──────────────────────────────────────────────┤
│ Assertion signature invalid     │ Chris (step 5)     │ Chris prints "pairing verification failed"   │
│                                 │                    │ and exits                                    │
├─────────────────────────────────┼────────────────────┼──────────────────────────────────────────────┤
│ Assertion expired               │ Chris (step 5)     │ Chris prints "pairing assertion expired"     │
│                                 │                    │ and exits                                    │
├─────────────────────────────────┼────────────────────┼──────────────────────────────────────────────┤
│ Assertion names wrong agent_id  │ Chris (step 5)     │ Chris prints "pairing assertion mismatch"    │
│                                 │                    │ and exits                                    │
└─────────────────────────────────┴────────────────────┴──────────────────────────────────────────────┘
```

Every failure produces a clear, specific message. Chris never falls through to routing messages without a verified assertion.

## Credential provenance

The Infrastructure Trust Plane uses three independent credentials. They serve different trust relationships, are issued by different authorities, and have no cryptographic relationship to each other. The proof of concept generates all three in a single setup script (`scripts/mock_ca.py`) for convenience. Production systems would issue each credential through a different process. This section documents what each credential is, what issues it in the demo, and what would issue it in production.

### TLS certificates (transport identity)

**What they are:** X.509 server certificates for the Registry and Cyrano, signed by a root certificate that all parties trust.

**Trust relationship:** Client verifies server. Chris trusts that the server at a given endpoint is the server it claims to be. The TLS handshake verifies this before any application data flows.

**Demo:** `scripts/mock_ca.py` generates a local root certificate (`ca.crt`) and signs server certificates for the Registry and Cyrano. All parties trust the local root. This is the one component that does not exist in production.

**Production:** A commercial TLS certificate authority (Let's Encrypt, DigiCert, Google Trust Services) verifies domain ownership and issues certificates that clients already trust through the global TLS CA ecosystem. OSU does not control which TLS certificates exist. Anyone who controls a domain can get one. This is precisely why TLS certificates alone cannot express OSU authorization.

**What changes:** The root of trust moves from a local file to the global TLS CA ecosystem. The certificate verification logic does not change.

### Trust Badge (agent service identity — agent to Registry)

**What it is:** A shared secret (64 hex characters) known only to Cyrano and the Agent Registry. The Registry stores a SHA-256 hash; Cyrano holds the raw value.

**Trust relationship:** Agent proves identity to Registry. During pairing, Cyrano presents the raw badge; the Registry hashes it and compares against the stored hash.

**Demo:** `scripts/mock_ca.py` generates a random hex string (`secrets.token_hex(32)`) and writes the raw badge to `certs/cyrano_trust_badge.txt` and the hash to `registry/agents.json`. The demo generates this alongside TLS certificates for convenience, but the Trust Badge has no cryptographic relationship to TLS.

**Production:** An administrative provisioning process controlled by OSU. When a new agent is registered, an administrator generates (or the Registry generates) a Trust Badge and securely delivers it to the agent operator. The Registry stores the hash. Agent provisioning is separate from TLS certificate issuance: different authority, different channel, different lifecycle.

**What changes:** The generation and distribution mechanism. The verification logic (hash comparison at `/pairing/verify`) does not change.

### HMAC signing key (assertion verification — Registry to Chris)

**What it is:** A symmetric HMAC-SHA256 key (64 hex characters) shared between the Registry and Chris.

**Trust relationship:** Chris trusts assertions from the Registry. The Registry signs pairing assertions with this key; Chris verifies the signature.

**Demo:** `scripts/mock_ca.py` generates a random hex string (`secrets.token_hex(32)`) and writes it to `certs/registry_signing.key`. Both the Registry and Chris read this file. The demo generates this alongside TLS certificates for convenience, but the HMAC key has no cryptographic relationship to TLS or to the Trust Badge.

**Production:** Production would replace symmetric HMAC with asymmetric signatures (RS256 or Ed25519). The Registry holds a private signing key; Chris (and any other client) holds the corresponding public verification key. The public key can be distributed openly: compromising it does not allow forging signatures. This is a key management change, not an architectural one. The assertion format, the fields signed, and the verification logic are otherwise the same.

**What changes:** The signature scheme (symmetric to asymmetric) and key distribution. The assertion format and verification logic do not change.

### Why the three credentials are independent

A valid TLS certificate does not imply a valid Trust Badge. A valid Trust Badge does not imply a valid HMAC key. Each credential answers a different question: "Is this connection secure?" (TLS), "Is this agent authorized?" (Trust Badge), "Did the Registry vouch for this agent?" (HMAC assertion). Each is issued by a different authority, distributed through a different channel, and can fail independently of the others.

## A2A compliance requirements

The proof of concept must comply with the A2A specification where the specification applies:

- **HTTPS required** for all server endpoints (Registry and Cyrano). Chris validates TLS certificates against the Mock TLS CA root.
- **Agent card** served by Cyrano at `/.well-known/agent-card.json` per the A2A discovery specification.
- **TLS 1.2 minimum**, TLS 1.3 preferred, per the A2A security recommendations.
- **Deprecated protocol versions disabled** (SSLv3, TLS 1.0, TLS 1.1).

The Agent Registry is not an A2A agent. It is an HTTPS API server that supports the trust infrastructure. It does not serve an agent card and does not implement the A2A message protocol.

## Technology constraints

For the proof of concept:

- **Language:** Python. The existing codebase is Python.
- **Mock TLS CA:** OpenSSL CLI or a Python script using the `cryptography` library. Must produce PEM files.
- **Agent Registry:** A lightweight HTTPS server (e.g., Flask or FastAPI) with a JSON file as data store.
- **Cyrano:** The existing Cyrano A2A server, extended with Trust Badge handling and pairing protocol support.
- **Chris CLI:** A new Python command-line program. No web UI. Stdin/stdout for human interaction. Uses `httpx` or `requests` for HTTPS calls with certificate verification.
- **Signing mechanism for pairing assertions:** HMAC-SHA256 with a shared key between Registry and Chris is sufficient for the proof of concept. The key is pre-shared at setup time (generated alongside the Mock TLS CA artifacts). A production system would use asymmetric signatures (e.g., RS256 or Ed25519) so the verification key can be public.

## What is in scope

- Mock TLS CA setup: generate root cert, server certs for Registry and Cyrano
- Agent Registry: HTTPS server with agent lookup, pairing challenge, and pairing verify endpoints
- Cyrano: Trust Badge storage, pairing verify call to Registry, pairing assertion relay to Chris
- Chris CLI: agent lookup, pairing challenge initiation, assertion verification, A2A session routing
- A working end-to-end demo: Chris pairs with Cyrano through the Registry and conducts a conversation
- Documentation of the setup, the protocol, and the design rationale

## What is out of scope

- User authentication (User Trust Plane)
- Per-user authorization and business rules (Agent Trust Plane)
- Web UI for Chris (production OpenBeavs uses a browser; this proof of concept uses a CLI)
- Agent catalog or discovery beyond direct agent ID lookup
- Persistent storage for the Registry (JSON file is sufficient)
- Trust Shields and Trust Dots (UI concerns; Chris CLI reports trust status as text)
- Multiple simultaneous agents or agent switching mid-session

## Success criteria

The proof of concept succeeds when:

1. Chris CLI can pair with Cyrano through the Agent Registry using the full three-step protocol
2. The pairing uses TLS throughout, with certificates issued by the Mock TLS CA
3. Chris correctly refuses to pair with an unauthorized agent (one not in the Registry or with `unapproved` status)
4. Chris correctly refuses to pair when the pairing assertion is invalid, expired, or names the wrong agent
5. After successful pairing, Chris routes user messages to Cyrano and prints responses
6. The system can be set up from scratch by someone reading the documentation, without the builder's presence

Criterion 6 is the Feynman Standard applied to the project: the knowledge architecture must be complete enough to enable replication.

## File placement

This document lives in `Architecture/` alongside the existing system architecture documents. It governs the implementation work for the Infrastructure Trust Plane proof of concept. Implementation plans, once written, belong in `Control/`.
