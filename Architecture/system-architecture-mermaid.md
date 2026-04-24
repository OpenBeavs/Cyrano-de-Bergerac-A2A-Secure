# System Architecture -- Mermaid Diagrams

Mermaid renderings of the diagrams in
[system-architecture.md](system-architecture.md).

## 1. System Topology

Three processes plus a setup-time artifact (Mock TLS CA). All connections use TLS with certificates issued by the Mock TLS CA. The Agent Registry performs the same structural function for agent service identity that a TLS certificate authority performs for transport identity: it decides which agents are authorized and issues short-lived pairing assertions that Chris can verify.

```mermaid
graph TD
    subgraph Setup["Setup Time -- python3 scripts/mock_ca.py"]
        MockCA["Mock TLS CA<br/>ca.crt, ca.key<br/>registry.crt, cyrano.crt<br/>cyrano_trust_badge.txt<br/>registry_signing.key"]
    end

    subgraph P1["Process 1 -- python3 main.py chat"]
        Chris["Chris (CLI chat client)<br/>No LLM · Pure A2A relay<br/>Verifies TLS certs against Mock TLS CA root<br/>Runs full pairing protocol before chat<br/>Verifies pairing assertions with HMAC key<br/>Maintains context_id"]
    end

    subgraph P2["Process 2 -- python3 main.py serve registry"]
        Registry["Agent Registry (HTTPS :8003)<br/>Authorizes agents (agent service identity)<br/>Agent records (JSON)<br/>Challenge tokens · Trust Badge validation<br/>Signs pairing assertions (HMAC-SHA256)"]
    end

    subgraph P3["Process 3 -- python3 main.py serve cyrano"]
        Cyrano["Cyrano (A2A HTTPS :8002)<br/>AgentExecutor · $CYRANO_MODEL<br/>voice.llm_call() + ConversationContext"]
        Services["Shared Services<br/>llm_voice_context/ · env_validator"]
    end

    Chris -->|"TLS :8003 (pairing)"| Registry
    Chris -->|"TLS :8002 (pairing + A2A)"| Cyrano
    Cyrano -->|"TLS :8003 (verify)"| Registry
    Cyrano -.->|imports| Services
```

## 2. Pairing Flow

Before any user messages flow, Chris executes the pairing protocol. The Agent Registry mediates: Chris never sees Cyrano's Trust Badge, and Cyrano never sees the Registry's signing key.

```mermaid
sequenceDiagram
    participant Chris as Chris<br/>(CLI client)
    participant Registry as Agent Registry<br/>(:8003)
    participant Cyrano as Cyrano<br/>(:8002)

    Chris->>Registry: 1. GET /agents/{agent_id}
    Registry-->>Chris: agent record (endpoint, status)

    Note over Chris: Check: status is approved<br/>or provisional

    Chris->>Registry: 2. POST /pairing/challenge {agent_id}
    Registry-->>Chris: challenge_token

    Chris->>Cyrano: 3. POST /pairing/respond {challenge_token}

    Cyrano->>Registry: 4. POST /pairing/verify {agent_id, challenge_token, trust_badge}

    Note over Registry: Validate badge, token,<br/>agent status

    Registry-->>Cyrano: signed pairing_assertion

    Cyrano-->>Chris: 5. pairing_assertion

    Note over Chris: Verify HMAC signature,<br/>agent_id, expiration

    Note over Chris,Cyrano: 6. Pairing complete. A2A session begins.
```

## 3. Request Flow (after pairing)

Every user message follows the same path. Chris sends to Cyrano over the already-established TLS connection, Cyrano crafts a reply, Chris prints it.

```mermaid
sequenceDiagram
    actor User
    participant Chris as Chris<br/>(CLI client)
    participant Cyrano as Cyrano<br/>(:8002)
    participant Voice as voice service
    participant Gemini as Gemini API

    User->>Chris: "Venus is bright tonight"

    Chris->>Cyrano: A2A SendMessage (context_id)

    Cyrano->>Voice: voice.llm_call()
    Voice->>Gemini: generate_content()
    Gemini-->>Voice: Eloquent reply + tokens
    Voice-->>Cyrano: Response (logged to tmp/cyrano-voice.log)
    Note over Cyrano: ConversationContext tracks the exchange<br/>Returns A2A Message with reply text

    Cyrano-->>Chris: A2A response (Message with text)
    Chris-->>User: "Cyrano: ..."
```

## 4. Module Structure

```mermaid
graph TD
    subgraph "scripts/mock_ca.py"
        SetupCA["generate_ca()<br/>→ ca.crt, ca.key"]
        SetupCerts["generate_server_cert()<br/>→ registry/cyrano .crt/.key"]
        SetupTrust["generate_trust_credentials()<br/>→ trust_badge, signing_key<br/>→ updates agents.json"]
    end

    subgraph "registry/agent_registry.py"
        RegApp["FastAPI HTTPS :8003"]
        RegAgents["GET /agents/{id}"]
        RegChallenge["POST /pairing/challenge"]
        RegVerify["POST /pairing/verify"]
        RegJSON["agents.json"]
    end

    subgraph "agents/chris.py"
        ChrisPairing["_run_pairing()<br/>query → challenge → send → verify"]
        ChrisVerify["_verify_assertion()<br/>HMAC signature, agent_id, expiration"]
        ChrisSend["_send_message()<br/>SendMessageRequest + context_id"]
        ChrisLoop["run_chat()<br/>pairing then CLI input loop"]
    end

    subgraph "agents/cyrano.py"
        CyranoExec["CyranoExecutor<br/>(AgentExecutor)"]
        CyranoPairing["POST /pairing/respond<br/>challenge → prove → relay"]
        CyranoCard["AgentCard<br/>name, capabilities, skills, https URL"]
        CyranoApp["a2a_app<br/>A2AFastAPIApplication"]
    end

    subgraph "services/"
        VoiceService["llm_voice_context/voice.py<br/>llm_call() + audit log"]
        ContextService["llm_voice_context/context.py<br/>ConversationContext<br/>Three-tier compaction"]
        EnvValidator["env_validator.py<br/>validate_env()"]
    end

    subgraph "main.py"
        MainReg["serve registry → uvicorn TLS :8003"]
        MainCyr["serve cyrano → uvicorn TLS :8002"]
        MainChat["chat → Chris CLI with pairing"]
    end

    ChrisPairing -->|"TLS"| RegChallenge
    ChrisPairing -->|"TLS"| CyranoPairing
    CyranoPairing -->|"TLS"| RegVerify
    ChrisSend ==>|"A2A HTTPS"| CyranoApp
    CyranoExec -.->|uses| VoiceService
    CyranoExec -.->|uses| ContextService
```

## 5. The Play Metaphor

```mermaid
graph LR
    User((User / Roxane))
    Chris["Christian<br/><i>The front man</i><br/>CLI relay"]
    Registry["The Church<br/><i>Agent Registry</i><br/>Verifies identities"]
    Cyrano["Cyrano<br/><i>The wordsmith</i><br/>Hidden talent<br/>behind the curtain"]

    User <-->|types at CLI| Chris
    Chris <-->|pairing via| Registry
    Cyrano <-->|proves identity to| Registry
    Chris <-->|A2A (after pairing)| Cyrano

    style Cyrano fill:#f0f0f0,stroke:#888,stroke-dasharray: 5 5
    style Registry fill:#e8f4e8,stroke:#4a4
```

## 6. Voice + Context Data Flow

```mermaid
flowchart TD
    subgraph "CyranoExecutor.execute()"
        A[Extract user text<br/>from A2A message] --> B[ConversationContext<br/>add_message]
        B --> C{needs_compaction?}
        C -->|yes| D[compact via<br/>CONTEXT_MANAGER_LLM]
        C -->|no| E[voice.llm_call<br/>with get_history]
        D --> E
        E --> F[Log to tmp/cyrano-voice.log]
        F --> G[add_message for response]
        G --> H[Return A2A Message]
    end
```
