# a2a_trust_pairing

Portable pairing module for the Infrastructure Trust Plane.

This module handles the mechanics of agent pairing: how an initiator (Chris) verifies a responder (Cyrano) through the Agent Registry, and how a responder proves its identity when challenged. It implements the full challenge-response protocol with HMAC-SHA256 assertion verification.

## What this module does

Two pairing flows, matching the two tiers of trust:

**Mediated pairing** (Chris to Cyrano, via the Agent Registry): The initiator looks up the agent, gets a challenge token, sends it to the responder, and verifies the signed assertion that comes back. This is earned trust, proven every time.

**Bootstrap authentication** (Chris to AR): The initiator presents a pre-shared credential (`chris_credential`) to the Registry. This is organizational trust; no third party mediates because Chris and the AR are the root of trust.

## Dependencies

- `a2a-sdk` (A2A protocol client and message types)
- `httpx` (HTTPS client)
- `fastapi` and `pydantic` (for the responder endpoint)
- Python 3.12+ standard library (`hashlib`, `hmac`, `datetime`)

## Usage

### For initiators (Chris-type agents)

```python
from a2a_trust_pairing import initiate_pairing, PairingError

try:
    endpoint, status = await initiate_pairing(
        agent_id="cyrano-001",
        registry_url="https://localhost:8003",
        ca_cert_path="certs/ca.crt",
        verify_key=verify_key,  # HMAC key, loaded from file
    )
except PairingError as e:
    print(f"Pairing failed: {e}")
```

### For responders (Cyrano-type agents)

```python
from a2a_trust_pairing import mount_pairing_responder

mount_pairing_responder(
    app=a2a_app,           # Your FastAPI app
    agent_id="cyrano-001",
    trust_badge=trust_badge,  # Shared secret with the Registry
    registry_url="https://localhost:8003",
    ca_cert_path="certs/ca.crt",
)
```

This registers a `POST /pairing/respond` endpoint on your app.

### For assertion verification only

```python
from a2a_trust_pairing import verify_assertion

success, error = verify_assertion(
    assertion=assertion_dict,
    expected_agent_id="cyrano-001",
    verify_key=verify_key,
)
```

## What stays in your agent

This module owns "how to pair." Your agent owns "when and whether to pair."

- **Initiator decisions** (yours): When to pair (before chat? on every request?), what to show the user, what to do on failure (exit, retry, degrade).
- **Responder decisions** (yours): Your Trust Badge value, your agent_id, your agent card, your domain logic.

## Credentials

The module needs credentials that the admin team provisions:

| Credential | Who holds it | What it does |
|---|---|---|
| Trust Badge | Responder + Registry | Proves responder identity. Shared secret; Registry stores the hash. |
| Chris credential | Initiator + Registry | Authenticates the initiator to the Registry on every request. Registry stores the hash. |
| HMAC verify key | Initiator + Registry | Verifies assertion signatures. Symmetric in demo; asymmetric in production. |
| CA certificate | Everyone | Verifies TLS server certificates. |

## Distribution

This module is distributed as source. Copy the `a2a_trust_pairing/` directory into your project. Config is passed as function parameters, not environment variables, so it works in any project without inheriting naming conventions.

## Welcome package for builders

This folder is the core functional element: copy it into your project, import the functions, and supply your credentials. Everything you need to integrate pairing is here.

Additional documentation is available separately upon request under `How-Pairing-Works/`, which covers:

- **Cyrano Builder Welcome Package** -- step-by-step quick-start for external teams: what to build, what to import, how to register with the admin team, and what credentials you receive.
- **For Cyrano Builders** -- deeper reference on Trust Badge mechanics, the pairing flow from the responder's perspective, and what your agent does and does not need to know about the rest of the trust system.
- **For Chris Builders** -- the initiator's perspective: assertion verification, failure handling, and the two trust tiers.
- **For Registry Builders** -- Agent Registry architecture, record schemas, skill handlers, credential provisioning, and attack surfaces.

Contact the admin team to request these documents along with your Trust Badge and agent registration.
