# For Registry Builders

How to build and operate an Agent Registry for the Infrastructure Trust Plane.

## What the Agent Registry is

The Agent Registry performs the same structural function for agent service identity that a TLS certificate authority performs for transport identity. TLS CAs are external to OSU: any server operator can obtain a valid TLS certificate. OSU cannot use TLS alone to express agent authorization. The Registry fills this gap. It is the authority OSU controls that decides which agents are authorized, records that decision, and issues short-lived pairing assertions that Chris can verify.

Two independent authority structures operate in parallel:

- **TLS CA** (external to OSU): asserts "this server controls this domain"
- **Agent Registry** (controlled by OSU): asserts "this agent is authorized by OSU"

Chris requires both assertions to proceed. The Registry does not replace TLS; it answers a question TLS cannot.

## Architecture

The AR is a pure A2A service. It implements `AgentExecutor` from the `a2a-sdk`, advertises an `AgentCard` with three skills, and handles all requests as A2A `SendMessage` JSON-RPC calls. No REST endpoints.

Every incoming message is a JSON object in the first `TextPart` with a `"skill"` field that names the operation. The executor dispatches to the corresponding handler.

This replaced earlier REST endpoints (`GET /agents/{id}`, `POST /pairing/challenge`, `POST /pairing/verify`) with a uniform A2A interface. The benefit is protocol uniformity: Chris uses A2A to talk to the Registry and to Cyrano. The cost is JSON-RPC wrapping around simple request-response operations. One protocol is easier to follow than two.

## Record schema

The Registry stores records in `agents.json`. A single flat namespace with a `type` field distinguishes agents from clients.

### Agent records

```json
{
  "cyrano-001": {
    "type": "agent",
    "name": "Cyrano de Bergerac",
    "endpoint": "https://localhost:8002",
    "status": "approved",
    "trust_badge_hash": "0470f0...957c"
  }
}
```

| Field | Purpose |
|---|---|
| `type` | Always `"agent"`. Distinguishes agent records from client records in the same namespace. |
| `name` | Display name. Human-readable; not used for authentication. |
| `endpoint` | The HTTPS URL where the agent listens. Returned to Chris during agent-lookup. |
| `status` | One of `approved`, `provisional`, or `unapproved`. The AR checks this during pairing-verify; only `approved` and `provisional` agents can pair. |
| `trust_badge_hash` | SHA-256 hex digest of the agent's Trust Badge. The AR never stores the raw badge. During pairing-verify, the AR hashes the presented badge and compares. |

**Why store the hash, not the raw badge:** If the agents.json file is compromised, the attacker gets hashes, not credentials. The attacker cannot present a valid badge to the AR using only its hash. This is the same principle behind storing password hashes instead of passwords.

### Client records

```json
{
  "chris-001": {
    "type": "client",
    "name": "Chris (CLI)",
    "chris_credential_hash": "dd76ac...fb99"
  }
}
```

| Field | Purpose |
|---|---|
| `type` | Always `"client"`. |
| `name` | Display name. |
| `chris_credential_hash` | SHA-256 hex digest of Chris's credential. The AR hashes the presented credential on every request and compares. |

**Why `chris_credential`, not `client_credential`:** In A2A, every caller is a "client." The generic term is ambiguous. `chris_credential` is self-documenting: when you see it anywhere in the code, you know it is Chris authenticating to the AR.

**Why a single flat namespace instead of separate agent/client sections:** The Registry already looks up by ID. Adding a type field is one extra check. Separate sections would require the Registry to know which section to query, adding routing logic for no security benefit. The type field also accommodates entity types that do not exist yet.

## The three A2A skills

### agent-lookup

**Caller:** Chris. **Authentication:** `chris_credential` required.

Chris sends:
```json
{"skill": "agent-lookup", "agent_id": "cyrano-001", "chris_credential": "..."}
```

The AR returns the public portion of the agent record: name, endpoint, and trust status. Does not return `trust_badge_hash`. Chris uses this to discover the agent's endpoint and confirm its status before initiating pairing.

### pairing-challenge

**Caller:** Chris. **Authentication:** `chris_credential` required.

Chris sends:
```json
{"skill": "pairing-challenge", "agent_id": "cyrano-001", "chris_credential": "..."}
```

The AR generates a random challenge token (64 hex characters via `secrets.token_hex(32)`), stores it in memory with a 60-second TTL bound to the agent ID, and returns it. The token is single-use: consumed by pairing-verify, or it expires.

### pairing-verify

**Caller:** Cyrano. **Authentication:** Trust Badge (validated within the handler; no `chris_credential`).

Cyrano sends:
```json
{
  "skill": "pairing-verify",
  "agent_id": "cyrano-001",
  "challenge_token": "...",
  "trust_badge": "..."
}
```

The AR validates four conditions:

1. The challenge token exists and has not expired.
2. The challenge token was issued for this agent ID.
3. The SHA-256 hash of the presented Trust Badge matches the stored hash.
4. The agent's status is `approved` or `provisional`.

If all pass, the AR signs a pairing assertion (HMAC-SHA256) and returns it. The challenge token is consumed (deleted) regardless of outcome to prevent replay.

**Why pairing-verify does not require `chris_credential`:** Cyrano calls this skill, not Chris. Cyrano authenticates via its Trust Badge, which the handler validates directly. Requiring Chris's credential here would mean sharing Chris's credential with Cyrano, which breaks the trust boundary.

## Client authentication

Skills called by Chris (`agent-lookup`, `pairing-challenge`) require `chris_credential` in the payload. The AR hashes it and compares against the stored hash for Chris's record. Per-request, stateless: no sessions, no tokens.

The authentication check runs in the executor before dispatch. If the credential is missing or wrong, the request is rejected before the handler runs. This guards against a Fake Chris probing the AR for agent records or generating challenge tokens.

## Credential provisioning

Four independent credentials serve four independent trust relationships. In the demo, `scripts/mock_ca.py` generates all of them for convenience. In production, each comes from a different issuing authority.

| Credential | Demo generation | Production equivalent |
|---|---|---|
| TLS certificates | Mock CA (`mock_ca.py`) | Commercial CA (Let's Encrypt, DigiCert) |
| Trust Badge | Random hex string (`mock_ca.py`) | Admin provisioning process at agent registration |
| HMAC signing key | Random hex string (`mock_ca.py`) | Asymmetric key pair (RS256 or Ed25519); public key distributed to Chris |
| Chris credential | Random hex string (`mock_ca.py`) | Admin internal provisioning process |

The `mock_ca.py` script also updates `agents.json` with the Trust Badge hash and Chris credential hash, keeping the generated credentials and the Registry's stored hashes in sync.

## The HMAC signing key

The signing key signs pairing assertions. The Registry holds it; Chris holds the same key to verify. The signature covers `agent_id|issued_at|expires_at` with pipe delimiters.

**Why symmetric (HMAC-SHA256) in the demo:** Simpler to set up. One key, shared via file.

**What production replaces it with:** An asymmetric key pair. The Registry holds the private signing key; Chris holds the public verification key. The public key can be distributed openly. This is a key management change, not an architectural change: the assertion format and verification logic stay the same.

## The root of trust

The Chris-AR relationship is bootstrap trust: organizational, pre-provisioned, and not mediated by any third party. The admin team controls both Chris and the AR, runs both services, and provisions the credential. The `chris_credential` makes that organizational trust verifiable at the protocol level.

"Organizational" means: the same team that deploys Chris also deploys the AR. They share credentials through their internal provisioning process, not through the pairing protocol. The pairing protocol mediates trust between entities controlled by different teams (Chris and Cyrano). It does not mediate trust that already exists.

## Attack surfaces

**Fake Chris.** An attacker who can reach the AR's network endpoint could probe for agent records or generate challenge tokens. The `chris_credential` blocks this: every skill request is authenticated before dispatch. Without the credential, the AR returns "chris authentication failed" and logs the attempt.

**Replay attacks.** Challenge tokens are single-use (consumed after pairing-verify) and have a 60-second TTL. A captured token cannot be reused. Pairing assertions have a 300-second TTL and are signed, so a captured assertion expires quickly and cannot be modified.

**Challenge token exhaustion.** An attacker with a valid `chris_credential` could request many challenge tokens. The AR purges expired tokens opportunistically during challenge creation. In production, rate limiting on the AR's endpoint would address this.

**Compromised agents.json.** Contains hashes, not raw credentials. An attacker who reads the file learns which agents are registered and their endpoints (which are public information via agent cards anyway) but cannot impersonate an agent without the raw Trust Badge.
