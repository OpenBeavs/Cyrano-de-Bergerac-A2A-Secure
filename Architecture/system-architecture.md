# System Architecture -- Cyrano de Bergerac A2A (Secure)

The system mirrors the play: Chris faces the audience, Cyrano composes the words from the shadows. What this fork adds is the Infrastructure Trust Plane: before Chris routes any user messages, he verifies through the Agent Registry that Cyrano is an OSU-authorized agent.

Four entities communicate over TLS. The Agent Registry performs the same structural function for agent service identity that a TLS certificate authority performs for transport identity: it is the authority OSU controls that decides which agents are authorized. TLS certificate authorities are external to OSU and cannot express OSU authorization; the Registry fills that gap.

Two shared services support Cyrano: the **voice service** (audited LLM calls) and the **context service** (conversation history with three-tier compaction). See [llm-voice-and-context.md](llm-voice-and-context.md) for the full design rationale.

## 1. System Topology

Three processes plus a setup-time artifact (Mock TLS CA). Chris runs as a CLI process. The Registry and Cyrano each run as HTTPS servers via `main.py` + uvicorn. All connections use TLS with certificates issued by the Mock TLS CA.

```
┌─────────────────────────────────────────────────────────────────┐
│  SETUP TIME -- python3 scripts/mock_ca.py                   │
│                                                                 │
│  Mock TLS CA generates:                                          │
│    ca.crt / ca.key          Root certificate (trusted by all)   │
│    registry.crt / .key      Registry server certificate         │
│    cyrano.crt / .key        Cyrano server certificate           │
│    cyrano_trust_badge.txt   Shared secret (Cyrano ↔ Registry)  │
│    registry_signing.key     HMAC key (Registry ↔ Chris)        │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  PROCESS 1 -- python3 main.py chat [agent_id]                   │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Chris (CLI chat client)                                  │  │
│  │  No LLM. Pure relay over A2A protocol.                    │  │
│  │  Verifies TLS certs against Mock TLS CA root.             │  │
│  │  Runs full pairing protocol before chat.                  │  │
│  │  Verifies pairing assertions with HMAC key.               │  │
│  │  A2AClient → https://localhost:8002/                      │  │
│  │  Maintains context_id for conversation continuity.        │  │
│  └──────────┬───────────────────────────┬────────────────────┘  │
│              │                           │                      │
└──────────────┼───────────────────────────┼──────────────────────┘
               │                           │
       TLS :8003                   TLS :8002
     (pairing)               (pairing + A2A)
               │                           │
┌──────────────┼───────────────────────────┼──────────────────────┐
│              │                           │                      │
│  ┌───────────▼───────────────────────┐   │                      │
│  │  PROCESS 2 -- serve registry      │   │                      │
│  │                                   │   │                      │
│  │  Agent Registry (HTTPS :8003)     │   │                      │
│  │  Authorizes agents (agent service identity). │   │                      │
│  │  Stores agent records (JSON).     │   │                      │
│  │  Issues challenge tokens.         │   │                      │
│  │  Validates Trust Badges.          │   │                      │
│  │  Signs pairing assertions.        │   │                      │
│  └───────────▲───────────────────────┘   │                      │
│              │                           │                      │
│          TLS :8003                       │                      │
│        (verify)                          │                      │
│              │                           │                      │
│  ┌───────────┴───────────────────────────▼───────────────────┐  │
│  │  PROCESS 3 -- serve cyrano                                │  │
│  │                                                           │  │
│  │  Cyrano (A2A HTTPS server, uvicorn :8002)                 │  │
│  │  AgentExecutor (a2a-sdk)                                  │  │
│  │  $CYRANO_MODEL (gemini-3.1-pro-preview)                   │  │
│  │                                                           │  │
│  │  The hidden wordsmith. Crafts eloquent replies.           │  │
│  │  voice.llm_call() → Gemini API (audited)                  │  │
│  │  ConversationContext → three-tier compaction               │  │
│  │                                                           │  │
│  │  /pairing/respond: receives challenge from Chris,         │  │
│  │  proves identity to Registry, relays assertion back.      │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Shared Services (imported by Cyrano)                     │  │
│  │                                                           │  │
│  │  services/llm_voice_context/                               │  │
│  │    voice.py    LLM calls with audit logging               │  │
│  │                → tmp/cyrano-voice.log                     │  │
│  │    context.py  Conversation history management            │  │
│  │                Three-tier compaction (90% trigger)         │  │
│  │                                                           │  │
│  │  services/env_validator.py                                │  │
│  │                Environment validation (fail fast)          │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## 2. Pairing Flow

Before any user messages flow, Chris executes the pairing protocol. The Agent Registry mediates: Chris never sees Cyrano's Trust Badge, and Cyrano never sees the Registry's signing key.

```
 Chris (CLI)                    Registry (:8003)               Cyrano (:8002)
  │                                │                               │
  │  1. GET /agents/{agent_id}     │                               │
  │───────────────────────────────▶│                               │
  │  agent record (endpoint,       │                               │
  │  status)                       │                               │
  │◀───────────────────────────────│                               │
  │                                │                               │
  │  [Check: status is approved    │                               │
  │   or provisional]              │                               │
  │                                │                               │
  │  2. POST /pairing/challenge    │                               │
  │     {agent_id}                 │                               │
  │───────────────────────────────▶│                               │
  │  challenge_token               │                               │
  │◀───────────────────────────────│                               │
  │                                │                               │
  │  3. POST /pairing/respond      │                               │
  │     {challenge_token}          │                               │
  │───────────────────────────────────────────────────────────────▶│
  │                                │                               │
  │                                │  4. POST /pairing/verify      │
  │                                │     {agent_id,                │
  │                                │      challenge_token,         │
  │                                │      trust_badge}             │
  │                                │◀──────────────────────────────│
  │                                │                               │
  │                                │  [Validate badge, token,      │
  │                                │   agent status]               │
  │                                │                               │
  │                                │  signed pairing_assertion     │
  │                                │──────────────────────────────▶│
  │                                │                               │
  │  5. pairing_assertion          │                               │
  │◀──────────────────────────────────────────────────────────────│
  │                                │                               │
  │  [Verify HMAC signature,       │                               │
  │   agent_id, expiration]        │                               │
  │                                │                               │
  │  6. Pairing complete. A2A session begins.                      │
  │◀══════════════════════════════════════════════════════════════▶│
```

## 3. Request Flow (after pairing)

Every user message follows the same path. Chris sends to Cyrano over the already-established TLS connection, Cyrano crafts a reply, Chris prints it.

```
 User (CLI)
  │
  │  "Venus is bright tonight"
  │
  ▼
 Chris (CLI chat client)
  │  Wraps text in A2A SendMessage with context_id
  │  Sends via A2AClient (httpx, TLS verified)
  │
  │  A2A HTTPS POST :8002
  │
  ▼
 Cyrano (A2A server, uvicorn :8002)
  │  AgentExecutor.execute() receives the request
  │  Extracts user text from A2A message
  │  Adds to ConversationContext
  │  Checks compaction (90% of CONTEXT_MAX)
  │  voice.llm_call() crafts the eloquent reply (logged for audit)
  │  Adds response to ConversationContext
  │  Returns A2A Message with reply text
  │
  │  A2A response
  │
  ▼
 Chris prints: "Cyrano: ..."
```

## 4. Module Structure

```
 scripts/mock_ca.py
  ├── generate_ca()           → ca.crt, ca.key
  ├── generate_server_cert()  → {registry,cyrano}.{crt,key}
  └── generate_trust_credentials()
       → cyrano_trust_badge.txt, registry_signing.key
       → updates registry/agents.json

 registry/agent_registry.py
  ├── FastAPI HTTPS app (uvicorn :8003)
  ├── GET /agents/{agent_id}      → agent record
  ├── POST /pairing/challenge     → challenge token
  ├── POST /pairing/verify        → signed pairing assertion
  └── agents.json                 → agent records (JSON file)

 agents/chris.py
  ├── _run_pairing()       → full pairing protocol
  │     query registry → challenge → send to cyrano → verify assertion
  ├── _verify_assertion()  → HMAC signature, agent_id, expiration
  ├── _send_message()      → A2A SendMessageRequest with context_id
  ├── run_chat()           → pairing then CLI input loop
  └── main()               → asyncio.run(run_chat())

 agents/cyrano.py
  ├── CyranoExecutor(AgentExecutor)
  │     execute() → voice.llm_call() + ConversationContext
  ├── POST /pairing/respond
  │     receives challenge → proves to registry → returns assertion
  ├── AgentCard (name, capabilities, skills, https URL)
  ├── DefaultRequestHandler + InMemoryTaskStore
  └── a2a_app = A2AFastAPIApplication(...).build()

 services/llm_voice_context/
  ├── voice.py
  │     └── llm_call()       — Gemini API call + audit log
  └── context.py
        └── ConversationContext  — Three-tier compaction
              ├── add_message()
              ├── needs_compaction() → compact()
              └── get_history() → list[dict]

 services/env_validator.py
  └── validate_env(scope)  — Fail-fast environment check

 main.py
  ├── serve registry  → uvicorn.run(registry, TLS :8003)
  ├── serve cyrano    → validate_env + uvicorn.run(a2a_app, TLS :8002)
  └── chat [agent_id] → Chris CLI client with pairing
```

## 5. Port Allocation

```
┌──────┬──────────┬──────────────────────────────────────┐
│ Port │ Service  │ Started by                            │
├──────┼──────────┼──────────────────────────────────────┤
│ 8002 │ Cyrano   │ python3 main.py serve cyrano (HTTPS) │
├──────┼──────────┼──────────────────────────────────────┤
│ 8003 │ Registry │ python3 main.py serve registry (HTTPS)│
└──────┴──────────┴──────────────────────────────────────┘

Chris runs as a CLI process (no port).
```

## 6. The Play Metaphor

```
┌────────────┬──────────────────────────────────────────────┐
│ Play       │ System                                        │
├────────────┼──────────────────────────────────────────────┤
│ Roxane     │ The user. Types messages at the CLI prompt.   │
│            │ Receives eloquence without knowing its        │
│            │ true author.                                  │
├────────────┼──────────────────────────────────────────────┤
│ Christian  │ Chris. The front man. Faces the audience      │
│            │ and delivers Cyrano's words. Verifies         │
│            │ Cyrano's identity through the Registry        │
│            │ before trusting him.                          │
├────────────┼──────────────────────────────────────────────┤
│ Cyrano     │ The hidden wordsmith. Crafts the reply.       │
│            │ Proves his identity to the Registry.          │
│            │ Only Chris knows he exists.                   │
├────────────┼──────────────────────────────────────────────┤
│ The Church │ The Agent Registry. The institution that      │
│            │ verifies identities and vouches for those     │
│            │ it trusts.                                    │
└────────────┴──────────────────────────────────────────────┘
```

## 7. Credential Provenance

The Infrastructure Trust Plane uses three independent credentials. They serve different trust relationships, are issued by different authorities, and have no cryptographic relationship to each other. This section documents where each credential comes from in this teaching demo and what issues it in production.

### TLS certificates (transport identity)

```
┌─────────────────────────────────────────────────────────────────┐
│ Credential:  X.509 server certificates (registry.crt,          │
│              cyrano.crt) signed by a root CA (ca.crt)           │
│                                                                 │
│ Trust relationship:  Client ↔ Server                            │
│   Chris trusts that the server at a given endpoint is the       │
│   server it claims to be. The TLS handshake verifies this.      │
│                                                                 │
│ Demo issuer:  scripts/mock_ca.py — generate_ca() and            │
│   generate_server_cert(). A local root CA signs server certs    │
│   for localhost. All parties trust the local root.              │
│                                                                 │
│ Production issuer:  A commercial TLS certificate authority       │
│   (Let's Encrypt, DigiCert, Google Trust Services, or           │
│   whichever TLS CA the organization uses). These authorities    │
│   verify domain ownership and issue certificates that clients   │
│   already trust. OSU does not control which TLS certificates    │
│   exist in the world. Anyone can get one.                       │
│                                                                 │
│ What changes from demo to production:  The root of trust        │
│   moves from a local file (ca.crt) to the global TLS CA        │
│   ecosystem. The certificate verification logic in Chris and    │
│   Cyrano does not change — only the trusted root changes.       │
│                                                                 │
│ Key point:  TLS certificates prove transport identity (this     │
│   server controls this domain). They cannot prove service       │
│   identity (OSU authorized this agent). That gap is why the     │
│   Agent Registry exists.                                        │
└─────────────────────────────────────────────────────────────────┘
```

### Trust Badge (agent service identity — agent to Registry)

```
┌─────────────────────────────────────────────────────────────────┐
│ Credential:  A shared secret (64 hex characters) known only     │
│              to Cyrano and the Agent Registry                   │
│                                                                 │
│ Trust relationship:  Agent ↔ Registry                           │
│   Cyrano proves to the Registry that it is the agent the        │
│   Registry authorized. The Registry stores a SHA-256 hash;      │
│   Cyrano holds the raw secret. During pairing, Cyrano presents  │
│   the raw badge; the Registry hashes it and compares.           │
│                                                                 │
│ Demo issuer:  scripts/mock_ca.py — generate_trust_credentials() │
│   Generates a random hex string via secrets.token_hex(32).      │
│   Writes the raw badge to certs/cyrano_trust_badge.txt and      │
│   the hash to registry/agents.json. The demo script generates   │
│   this alongside TLS certificates for convenience, but the      │
│   Trust Badge has no cryptographic relationship to TLS.         │
│                                                                 │
│ Production issuer:  An administrative provisioning process      │
│   controlled by OSU. When a new agent is registered, an         │
│   administrator generates (or the Registry generates) a Trust   │
│   Badge and securely delivers it to the agent operator. The     │
│   Registry stores the hash. The provisioning process is         │
│   separate from TLS certificate issuance — different            │
│   authority, different channel, different lifecycle.             │
│                                                                 │
│ What changes from demo to production:  The generation and       │
│   distribution mechanism. The demo generates everything in      │
│   one script; production separates agent provisioning from      │
│   TLS certificate management. The verification logic (hash      │
│   comparison at /pairing/verify) does not change.               │
│                                                                 │
│ Key point:  The Trust Badge is unrelated to TLS. A valid TLS    │
│   certificate does not imply a valid Trust Badge. An agent      │
│   with a valid cert but no badge fails pairing.                 │
└─────────────────────────────────────────────────────────────────┘
```

### HMAC signing key (assertion verification — Registry to Chris)

```
┌─────────────────────────────────────────────────────────────────┐
│ Credential:  A symmetric HMAC-SHA256 key (64 hex characters)    │
│              shared between the Registry and Chris              │
│                                                                 │
│ Trust relationship:  Registry → Chris                           │
│   Chris trusts that a pairing assertion was issued by the       │
│   Registry and has not been tampered with. The Registry signs   │
│   assertions with this key; Chris verifies the signature.       │
│                                                                 │
│ Demo issuer:  scripts/mock_ca.py — generate_trust_credentials() │
│   Generates a random hex string via secrets.token_hex(32).      │
│   Writes it to certs/registry_signing.key. Both the Registry    │
│   and Chris read this file. The demo generates this alongside   │
│   TLS certificates for convenience, but the HMAC key has no     │
│   cryptographic relationship to TLS or to the Trust Badge.      │
│                                                                 │
│ Production issuer:  Production would replace HMAC (symmetric)   │
│   with asymmetric signatures (RS256 or Ed25519). The Registry   │
│   holds a private signing key; Chris (and any other client)     │
│   holds the corresponding public verification key. The public   │
│   key can be distributed openly — compromising it does not      │
│   allow forging signatures. Key management becomes a Registry   │
│   administration concern, not a shared-secret distribution      │
│   problem.                                                      │
│                                                                 │
│ What changes from demo to production:  The signature scheme     │
│   (symmetric → asymmetric) and key distribution. The assertion  │
│   format, the fields signed, and the verification logic are     │
│   otherwise the same. Swapping HMAC for asymmetric signatures   │
│   is a key management change, not an architectural one.         │
│                                                                 │
│ Key point:  The signing key is unrelated to TLS certificates    │
│   and unrelated to Trust Badges. All three credentials serve    │
│   different trust relationships and are issued independently.   │
└─────────────────────────────────────────────────────────────────┘
```

## 8. Key Abstractions

### A2A SDK (Server Side)

```
┌─────────────────────────────────────────────────────────────────┐
│ a2a.server.agent_execution.AgentExecutor                        │
│   Abstract base class. Implement execute() to handle requests.  │
│   Receives RequestContext and EventQueue.                        │
├─────────────────────────────────────────────────────────────────┤
│ a2a.server.request_handlers.DefaultRequestHandler               │
│   Wires AgentExecutor to A2A protocol (task store, queues).     │
├─────────────────────────────────────────────────────────────────┤
│ a2a.server.apps.jsonrpc.fastapi_app.A2AFastAPIApplication       │
│   Builds a FastAPI app that speaks A2A JSON-RPC. Exposes the    │
│   AgentCard at /.well-known/agent-card.json.                    │
├─────────────────────────────────────────────────────────────────┤
│ a2a.types.AgentCard                                             │
│   Service discovery: name, capabilities, skills, URL.           │
└─────────────────────────────────────────────────────────────────┘
```

### A2A SDK (Client Side)

```
┌─────────────────────────────────────────────────────────────────┐
│ a2a.client.A2AClient                                            │
│   Sends SendMessageRequest to an A2A server via JSON-RPC.       │
│   Returns SendMessageResponse containing the agent's reply.     │
│   Configured with httpx client using TLS cert verification.     │
└─────────────────────────────────────────────────────────────────┘
```

### Infrastructure Trust Plane

```
┌─────────────────────────────────────────────────────────────────┐
│ registry.agent_registry (FastAPI HTTPS :8003)                           │
│   Agent Registry. For agent service identity, performs the same        │
│   structural function that a TLS certificate authority performs  │
│   for transport identity. Stores agent records, mediates         │
│   pairing, signs assertions with HMAC-SHA256.                   │
├─────────────────────────────────────────────────────────────────┤
│ scripts.mock_ca                                                 │
│   Setup-time script. Generates three independent artifacts:     │
│                                                                 │
│   1. TLS certificates (ca.crt, server certs for Registry and    │
│      Cyrano). These handle transport identity. In production,   │
│      a commercial CA issues these instead.                      │
│                                                                 │
│   2. Trust Badge (cyrano_trust_badge.txt). A shared secret      │
│      between Cyrano and the Registry, used during pairing to    │
│      prove agent service identity. Unrelated to TLS.                  │
│                                                                 │
│   3. HMAC signing key (registry_signing.key). Shared between    │
│      the Registry and Chris. The Registry signs pairing         │
│      assertions with it; Chris verifies them. Unrelated to      │
│      TLS or the Trust Badge.                                    │
├─────────────────────────────────────────────────────────────────┤
│ Pairing assertion (JSON, HMAC-signed)                           │
│   Short-lived token: agent_id, issued_at, expires_at,           │
│   signature. Issued by Registry, verified by Chris.             │
└─────────────────────────────────────────────────────────────────┘
```

### CDB Services

```
┌─────────────────────────────────────────────────────────────────┐
│ services.llm_voice_context.llm_call()                            │
│   Gemini API call via google.genai + JSON-line audit logging.   │
│   Used by Cyrano's AgentExecutor.                               │
├─────────────────────────────────────────────────────────────────┤
│ services.llm_voice_context.ConversationContext                   │
│   Per-channel conversation history with three-tier compaction.  │
│   90% trigger, <=30% post-compaction. Uses CONTEXT_MANAGER_LLM. │
├─────────────────────────────────────────────────────────────────┤
│ services.env_validator.validate_env(scope)                       │
│   Environment validation. Fail-fast on missing required vars,   │
│   warn on missing optional vars with defaults.                  │
└─────────────────────────────────────────────────────────────────┘
```
