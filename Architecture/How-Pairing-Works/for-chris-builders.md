# For Chris Builders

How to build a Chris-type A2A client (initiator) that verifies agent identity before routing user messages.

## What Chris is

Chris is a CLI chat client. A pure relay with no LLM. Chris sends user messages to Cyrano via A2A and prints the replies. The entire value of Chris is the trust verification that happens before any user message flows: Chris proves that the Cyrano at the endpoint is the agent the Agent Registry authorized.

Chris never routes user messages without a verified pairing assertion.

## Two tiers of trust from Chris's perspective

Chris participates in both trust tiers, but the tiers feel different.

**Tier 1: Bootstrap trust (Chris to AR).** Chris holds a pre-shared credential (`chris_credential`). Chris includes it in every message to the AR. The AR verifies it. This is infrastructure authentication: if the credential is wrong or missing, the AR rejects every request. Chris does not negotiate this trust; Chris holds a credential and uses it. The organizational trust decision behind it (the admin team controls both Chris and the AR) is the admin team's concern, not Chris's code.

**Tier 2: Mediated trust (Chris to Cyrano).** Chris does not trust Cyrano directly. Chris trusts the AR's judgment about Cyrano. The pairing protocol gives Chris cryptographic proof that the Cyrano at a given endpoint is the one the AR authorized. Chris verifies the AR's signed assertion; Chris never handles Cyrano's Trust Badge.

## Using the pairing module

The `a2a_trust_pairing` module handles the pairing mechanics. Chris provides the config; the module runs the protocol.

### initiate_pairing()

The main entry point. Runs the full mediated pairing flow: agent lookup, challenge request, challenge delivery to Cyrano, and assertion verification.

```python
from a2a_trust_pairing import initiate_pairing, PairingError

try:
    endpoint, status = await initiate_pairing(
        agent_id="cyrano-001",
        registry_url=REGISTRY_URL,
        ca_cert_path=CA_CERT_PATH,
        verify_key=verify_key,
        chris_credential=CHRIS_CREDENTIAL or None,
    )
except PairingError as e:
    print(f"Pairing failed: {e}")
    sys.exit(1)
```

**Parameters:**

| Parameter | Source | Purpose |
|---|---|---|
| `agent_id` | Command line or config | Which agent to pair with |
| `registry_url` | Environment (`REGISTRY_URL`) | Where the AR listens |
| `ca_cert_path` | Environment (`CA_CERT_PATH`) | TLS CA root certificate for verifying server certs |
| `verify_key` | File (`certs/registry_signing.key`) | HMAC key for verifying the AR's pairing assertions |
| `chris_credential` | Environment (`CHRIS_CREDENTIAL`) | Chris's credential for AR authentication |

**Returns:** `(endpoint_url, trust_status)` on success.

**Raises:** `PairingError` with a descriptive message on any failure.

### bootstrap_authenticate()

Optional. Tests whether Chris's credential is accepted by the AR. Useful for fail-fast validation at startup before attempting the full pairing flow.

```python
from a2a_trust_pairing import bootstrap_authenticate

is_valid = await bootstrap_authenticate(
    chris_credential=CHRIS_CREDENTIAL,
    registry_url=REGISTRY_URL,
    ca_cert_path=CA_CERT_PATH,
)
```

Returns `True` if the AR accepts the credential, `False` otherwise.

## Chris's credential

Chris loads `CHRIS_CREDENTIAL` from the environment. The admin team provisions it (in the demo, `mock_ca.py` generates it into `certs/chris_credential.txt`; the operator copies the value into `.env`).

The credential is included in every A2A message to the AR. The module handles this: when `chris_credential` is passed to `initiate_pairing()`, the module adds it to the `agent-lookup` and `pairing-challenge` skill payloads.

The credential is not sent to Cyrano. Cyrano has no knowledge of Chris's credential and no way to verify it. The credential exists on the Chris-AR channel only.

## Assertion verification

When the pairing flow completes, Chris receives a signed assertion from Cyrano (who relayed it from the AR). The `initiate_pairing()` function verifies it internally, but understanding the checks matters for debugging.

Three checks:

1. **HMAC signature.** Chris recomputes the signature over `agent_id|issued_at|expires_at` using the verify key and compares. If the signature does not match, either the assertion was tampered with or the verify key is wrong.

2. **Agent ID match.** The assertion must name the agent Chris asked for. This prevents replay across agents: an assertion for `cyrano-001` cannot be used for `cyrano-002`.

3. **Expiration.** The assertion has a 300-second TTL. If it has expired, the pairing is stale and Chris must re-pair. This limits the window for assertion replay.

## Trust status display

After successful pairing, Chris displays the trust status to the user:

- **APPROVED** (green badge): The admin team has fully vetted this agent.
- **PROVISIONAL** (red badge): The agent is registered but carries a caution flag. The user should know they are interacting with a provisionally trusted agent.

What Chris displays is a UX decision that belongs to Chris, not to the pairing module. The module returns the status string; Chris decides how to present it.

## Failure handling

Every failure during pairing raises `PairingError` with a message that identifies the problem. Chris's job is to present the error clearly and exit. Chris does not retry pairing automatically; the user restarts.

| Error message | What happened | What it means |
|---|---|---|
| `cannot reach Agent Registry at ...` | Network failure or AR not running | Infrastructure problem. Check that the AR is running and the URL is correct. |
| `agent not found: ...` | Agent ID not in `agents.json` | The agent is not registered. Check the agent ID. |
| `agent is not approved (status: ...)` | Agent exists but status is `unapproved` | The admin team has not authorized this agent. |
| `cannot reach agent at ...` | Cyrano's endpoint is unreachable | Cyrano is not running or the endpoint in the agent record is wrong. |
| `pairing failed: Trust Badge mismatch` | Cyrano presented the wrong Trust Badge | The Cyrano at this endpoint is not the one the AR authorized. This is the attack the system is designed to catch. |
| `pairing verification failed` | HMAC signature check failed | The assertion was tampered with, or the verify key does not match the AR's signing key. |
| `pairing assertion expired` | Assertion TTL exceeded | The assertion is stale. This can happen if there is significant clock skew or network delay. Re-pair. |
| `chris authentication failed` | AR rejected the `chris_credential` | The credential is wrong or missing. Check `.env` configuration. |

## What Chris does not care about

Chris does not know or handle Cyrano's Trust Badge. The Trust Badge exists on the Cyrano-AR channel; Chris never sees it. Chris verifies the AR's assertion about Cyrano, not Cyrano's credential directly. This is by design: the AR mediates so that neither party discloses credentials to the other.

Chris does not decide whether an agent should be approved. That is the admin team's judgment, recorded in the AR. Chris reads the verdict and displays it.
