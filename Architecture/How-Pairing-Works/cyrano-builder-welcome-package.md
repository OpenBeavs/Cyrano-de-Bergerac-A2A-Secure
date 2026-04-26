# Cyrano Builder Welcome Package

A quick-start guide for external teams building a Cyrano-type agent for the CDB system.

## What you are building

You are building an A2A server with an LLM (or other domain expertise) that registers with the Agent Registry and proves its identity when challenged by Chris, the user-facing client.

Your agent needs two capabilities:

1. **Domain expertise.** Your A2A executor handles messages from Chris: answer questions, compose text, translate, analyze, or whatever your agent specializes in.
2. **Pairing support.** When Chris initiates a pairing challenge, your agent proves its identity to the Agent Registry. You do not write this code yourself; you import the `a2a_trust_pairing` module.

## What you import

The `a2a_trust_pairing` module is a source directory distributed as part of your onboarding materials. Copy it into your project root.

You need one function from it:

```python
from a2a_trust_pairing import mount_pairing_responder
```

This function adds a `POST /pairing/respond` endpoint to your A2A FastAPI app. When Chris sends a challenge, the endpoint handles the exchange with the Agent Registry automatically.

## What you write yourself

Everything else is yours:

- **Your A2A executor.** This is your domain logic. Implement `AgentExecutor` from the `a2a-sdk`. Your executor receives messages from Chris and returns replies. The executor has nothing to do with pairing.
- **Your agent card.** Advertise your capabilities, skills, and endpoint. See "Agent card requirements" below.
- **Your LLM integration.** Choose your model, manage context, handle streaming if needed.

## Step by step

### 1. Build your A2A server

Use the `a2a-sdk` to create a server with your executor:

```python
from a2a.server.agent_execution.agent_executor import AgentExecutor
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.server.request_handlers.default_request_handler import DefaultRequestHandler
from a2a.server.tasks.inmemory_task_store import InMemoryTaskStore
from a2a.server.apps.jsonrpc.fastapi_app import A2AFastAPIApplication
from a2a.types import (
    AgentCard, AgentCapabilities, AgentSkill,
    Message, Part, TextPart,
)

class YourExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        user_message = context.get_user_input()
        # ... your domain logic ...
        response = Message(
            role="agent",
            messageId="...",
            parts=[Part(root=TextPart(text=reply_text))],
            contextId=context.context_id,
        )
        await event_queue.enqueue_event(response)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        pass
```

### 2. Define your agent card

```python
agent_card = AgentCard(
    name="your-agent-name",
    description="What your agent does.",
    url="https://your-endpoint:port/",
    version="1.0.0",
    capabilities=AgentCapabilities(streaming=False),
    defaultInputModes=["text"],
    defaultOutputModes=["text"],
    skills=[
        AgentSkill(
            id="your-skill",
            name="Your skill name",
            description="What this skill does.",
            tags=["your", "tags"],
        )
    ],
)
```

The `url` field must match the endpoint you provide to the admin team during registration (see Step 4). The `tags` field on `AgentSkill` is required by the `a2a-sdk`.

### 3. Mount the pairing responder

```python
from a2a_trust_pairing import mount_pairing_responder

handler = DefaultRequestHandler(
    agent_executor=YourExecutor(),
    task_store=InMemoryTaskStore(),
)

a2a_app = A2AFastAPIApplication(
    agent_card=agent_card,
    http_handler=handler,
).build()

mount_pairing_responder(
    app=a2a_app,
    agent_id="your-agent-id",       # From the admin team
    trust_badge="your-trust-badge",  # From the admin team
    registry_url="https://registry-host:8003",
    ca_cert_path="path/to/ca.crt",
)
```

### 4. Register with the admin team

Contact the admin team with:

- Your agent's name and description
- Your agent's endpoint URL (the HTTPS address where your server will listen)
- A brief description of what your agent does

The admin team will:

1. Vet your agent according to their assessment process.
2. Create a record for your agent in the Agent Registry.
3. Assign a trust status (`approved` or `provisional`).
4. Generate a Trust Badge and deliver it to you through a secure channel.
5. Provide you with your agent ID, the Registry's URL, and the CA certificate.

### 5. Configure and deploy

Set these in your environment or secrets management:

| Variable | Value | Source |
|---|---|---|
| Agent ID | e.g., `your-agent-001` | Provided by admin team |
| Trust Badge | 64-character hex string | Provided by admin team |
| Registry URL | e.g., `https://registry.example:8003` | Provided by admin team |
| CA cert path | Path to the TLS CA root certificate | Provided by admin team |

Run your server with TLS. In development:

```bash
uvicorn your_module:a2a_app --host 0.0.0.0 --port 8002 \
    --ssl-keyfile certs/your-server.key \
    --ssl-certfile certs/your-server.crt
```

## What the admin team provides

| Credential | What it is | What you do with it |
|---|---|---|
| Trust Badge | A shared secret between your agent and the Agent Registry | Load it from your environment; pass it to `mount_pairing_responder()` |
| Agent ID | Your agent's unique identifier in the Registry | Pass it to `mount_pairing_responder()` |
| Registry URL | Where the Agent Registry listens | Pass it to `mount_pairing_responder()` |
| CA certificate | The TLS root cert for verifying the Registry's server cert | Pass its file path to `mount_pairing_responder()` |

## What the admin team does not provide

- **Chris's credential.** Chris authenticates to the AR independently. Your agent has no role in that relationship and no access to Chris's credential.
- **The HMAC signing key.** The AR signs pairing assertions; Chris verifies them. Your agent relays the assertion but never inspects or validates it.
- **Chris's source code or configuration.** Your agent interacts with Chris through the A2A protocol. The protocol is the interface; you do not need Chris's internals.

## Trust status

The admin team assigns one of two active statuses:

- **Approved** (green badge): The admin team has fully vetted your agent and is satisfied with its behavior, security, and purpose.
- **Provisional** (red badge, user-caution-advised): Your agent is registered and can pair, but the admin team has flagged it for caution. Chris displays this to the user so they know they are interacting with a provisionally trusted agent.

Agents with `unapproved` status cannot pair. The AR rejects the pairing-verify request.

The trust status is the admin team's judgment. Your agent's code does not change based on its status. The status affects how Chris presents your agent to the user, not how your agent operates.

## Dependencies

Your project needs:

- `a2a-sdk` (A2A protocol support)
- `fastapi` + `uvicorn` (HTTPS server)
- `httpx` (used internally by `a2a_trust_pairing` for Registry communication)
- `pydantic` (used internally by `a2a_trust_pairing`)
- Your LLM SDK (Gemini, OpenAI, Anthropic, or whatever you use)
- The `a2a_trust_pairing/` source directory, copied into your project

## Questions

| Question | Answer |
|---|---|
| Do I need to understand the pairing protocol to build an agent? | No. Call `mount_pairing_responder()` with the credentials the admin team gives you. The module handles the protocol. |
| Can I use a different LLM? | Yes. The pairing protocol is independent of your LLM choice. Use whatever model serves your domain. |
| Can I add skills beyond what Chris expects? | Yes. Your agent card advertises your skills. Chris discovers them via the agent card. The pairing protocol does not constrain what skills you offer. |
| What if pairing fails? | Chris handles pairing failures. Your agent logs the error (the module logs to the standard Python logger) but does not need to take corrective action. Chris will either retry or inform the user. |
| Do I need to run the Agent Registry myself? | No. The admin team runs the Registry. Your agent contacts it during pairing at the URL they provide. |
