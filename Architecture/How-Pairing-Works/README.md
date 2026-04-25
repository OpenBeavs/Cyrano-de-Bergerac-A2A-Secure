# How Pairing Works

This directory documents the Infrastructure Trust Plane pairing protocol: how Chris verifies that Cyrano is authorized by OSU before routing any user messages. Each document addresses a different entity type and a different audience.

## The problem

TLS certificate authorities are external to OSU. Any server operator can get a valid TLS certificate, stand up an A2A server with a well-formed agent card, and accept connections. TLS proves transport identity (this server controls this endpoint) but cannot express agent service identity (OSU authorized this agent). The pairing protocol fills that gap.

## Two tiers of trust

The system has two tiers of trust, proven differently.

**Tier 1: Bootstrap trust (Chris to Agent Registry).** The admin team controls both Chris and the Agent Registry. They own the servers, write the code, deploy it. The trust is organizational and exists before any protocol runs. Chris authenticates to the AR with a pre-shared credential (`chris_credential`) to guard against a Fake Chris exploiting the network boundary. No mediator is needed because this is the root of trust.

**Tier 2: Mediated trust (Chris to Cyrano).** Cyrano comes from external teams. The admin team vets each Cyrano implementation and makes a judgment: decline, issue a red badge (user-caution-advised), or issue a green badge (clear). The Agent Registry records that judgment. Every time Chris connects to a Cyrano, the AR mediates a challenge-response protocol to prove the Cyrano at the endpoint is the one the AR authorized.

## Three entity types

| Entity | Role | Trust relationship |
|---|---|---|
| Agent Registry (AR) | Authority that records which agents are authorized. Issues signed pairing assertions. | Root of trust. Chris and the AR trust each other organizationally. |
| Chris (initiator) | CLI chat client. Verifies Cyrano's identity before routing user messages. | Holds `chris_credential` for AR authentication. Holds HMAC verify key for assertion checking. |
| Cyrano (responder) | A2A server with LLM. Proves identity to the AR when challenged. | Holds `trust_badge` shared with the AR. Never reveals it to Chris. |

## The protocol in seven steps

1. Chris queries the AR for the agent record (A2A: `agent-lookup` skill).
2. Chris requests a challenge token from the AR (A2A: `pairing-challenge` skill).
3. Chris sends the challenge token to Cyrano (`POST /pairing/respond`).
4. Cyrano sends the challenge token and its Trust Badge to the AR (A2A: `pairing-verify` skill).
5. The AR validates the Trust Badge, the challenge token, and the agent's status. If all pass, it signs a pairing assertion.
6. Cyrano relays the signed assertion back to Chris.
7. Chris verifies the assertion: HMAC signature, agent ID match, expiration.

If all checks pass, Chris has proof that the endpoint is the agent the AR authorized. Chat begins.

## Why this design and not simpler alternatives

**Alternative considered: Chris asks the Registry directly, "is agent X legitimate?"** Chris queries the Registry and gets back a yes/no answer. The problem: this proves the Registry has a record for agent X, but it does not prove that the server at the endpoint *is* agent X. An attacker who compromises DNS or the endpoint URL could serve a different agent at the registered address. The Registry said "agent X is approved," but nothing proved the server Chris is about to talk to is actually agent X.

**Alternative considered: Cyrano presents its Trust Badge directly to Chris.** This would require Chris to know the Trust Badge (or its hash) and Cyrano to reveal the secret on the wire between them. The Trust Badge becomes a shared secret between three parties (Cyrano, Registry, Chris), increasing the attack surface. If Chris is compromised, the Trust Badge leaks.

**Chosen design: Registry-mediated challenge-response with signed assertion.** Chris initiates. Cyrano proves identity to the Registry. The Registry vouches for Cyrano by issuing a signed assertion that Chris can verify. The Trust Badge never leaves the Cyrano-Registry relationship. Chris trusts the Registry's signature, not Cyrano's secret.

## Protocol uniformity

All entities speak A2A. The AR is a full A2A service with an `AgentCard` and three skills. Chris communicates with the AR and with Cyrano using the same protocol. The one exception is Step 3: Chris sends the challenge to Cyrano via a REST endpoint (`POST /pairing/respond`) mounted on Cyrano's A2A app. This is a pragmatic choice; the challenge delivery is a single request-response exchange that does not benefit from A2A framing.

## Documents in this directory

| Document | Audience | What it covers |
|---|---|---|
| [for-registry-builders.md](for-registry-builders.md) | Someone building or maintaining an Agent Registry | AR architecture, record schemas, skill handlers, credential provisioning, signing, attack surfaces |
| [for-chris-builders.md](for-chris-builders.md) | Someone building a Chris-type initiator | How to use `a2a_trust_pairing`, the two trust tiers from Chris's perspective, assertion verification, failure handling |
| [for-cyrano-builders.md](for-cyrano-builders.md) | Someone building a Cyrano-type responder | How to use `mount_pairing_responder`, Trust Badge mechanics, what Cyrano does and does not know |
| [cyrano-builder-welcome-package.md](cyrano-builder-welcome-package.md) | External team registering a new Cyrano-type agent | Quick-start: what to build, what to import, what to configure, how to register |

## A2A compliance

The system complies with the A2A specification where it applies:

- HTTPS required for all server endpoints (Registry and Cyrano). Chris validates TLS certificates against the CA root.
- Agent card served by Cyrano at `/.well-known/agent-card.json` per A2A discovery (Section 7.1).
- TLS 1.2 minimum, TLS 1.3 preferred, per A2A security recommendations (Section 7.2).

The Agent Registry is an A2A service (it serves an agent card and handles A2A messages). Chris communicates with the Registry and with Cyrano using the same A2A protocol.

## Related documents

- [a2a_trust_pairing/README.md](../../a2a_trust_pairing/README.md): API reference for the portable pairing module.
- [Engineering Requirements (archived)](../z-archive/OpenBeavs%20-%20Infrastructure%20Trust%20Plane%20-%20Engineering%20Requirements%20-%20v2026-0423.md): Original pre-implementation specification. Describes the REST-based design that was later converted to pure A2A. Retained as a historical artifact; the current system is documented in this directory.
