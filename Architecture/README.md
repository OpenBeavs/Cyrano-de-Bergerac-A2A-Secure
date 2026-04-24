# Architecture

Design rationale, system structure, and guiding principles for the Cyrano de Bergerac A2A system (Secure). This is the teaching layer of the project: the place where the *why* behind the system is documented at a depth that code comments cannot carry.

## How to read this directory

The documents here serve different purposes but overlap deliberately. A design decision often touches architecture, strategy, and philosophy at the same time. Rather than force each document into a single category, we keep them flat and let the reader navigate by topic. The descriptions below name both the primary purpose and the secondary concerns each document touches.

### System architecture

- [system-architecture.md](system-architecture.md) -- ASCII diagram of the four-entity system: Mock TLS CA, Agent Registry, Cyrano, and Chris. Shows the system topology with TLS connections, the pairing flow sequence, the post-pairing request flow, module structure, port allocation, the play metaphor, and key abstractions (A2A SDK, Infrastructure Trust Plane, CDB Services).
- [system-architecture-mermaid.md](system-architecture-mermaid.md) -- The same architecture as Mermaid diagrams, for contexts that render them (GitHub, IDE preview).

### Infrastructure Trust Plane

- [OpenBeavs - Infrastructure Trust Plane - Engineering Requirements - v2026-0423.md](OpenBeavs%20-%20Infrastructure%20Trust%20Plane%20-%20Engineering%20Requirements%20-%20v2026-0423.md) -- Full engineering requirements for the Infrastructure Trust Plane proof of concept. Teaches the core concept (the Agent Registry performs for agent service identity the same structural function that a TLS certificate authority performs for transport identity), defines the four system entities, specifies the pairing protocol with sequence diagram, documents failure modes, and states success criteria.
- [How-the-Handshake-Works.md](How-the-Handshake-Works.md) -- Step-by-step walkthrough of the pairing handshake between Chris, the Agent Registry, and Cyrano. Explains what happens at each step, what each party validates, and why the Trust Badge never leaves the Cyrano-Registry channel.

### Services

- [llm-voice-and-context.md](llm-voice-and-context.md) -- The voice and context services: how Cyrano's `AgentExecutor` routes LLM calls through the voice service, the three-tier compaction algorithm, audit log format, and the startup validator. The primary design document for `services/`.

### Strategy

- [LLM-Strategy.md](LLM-Strategy.md) -- Which model Cyrano uses and why. Covers the generative model for Cyrano, the infrastructure model for context compaction, the model configuration pattern, and the startup validator.

### Design principles

- [working-system-principle.md](working-system-principle.md) -- The development philosophy: always go from working system to working system. Every change leaves the system functional.
- [ux-design-principles.md](ux-design-principles.md) -- Announce before you act, errors must be unmissable, surface results not machinery. Governs how agents communicate with users.

### Philosophy and origins

- [ORIGINS.md](ORIGINS.md) -- The literary metaphor: how Rostand's play maps onto the two-agent architecture. Explains why Chris is the interesting design element (the relay positioned for future evolution) and why CDB exists as a scaffold.

## Cross-references

These documents form a citation graph. Code comments in `agents/cyrano.py` cite llm-voice-and-context.md. Code comments in `registry/agent_registry.py` cite the Engineering Requirements ERD. LLM-Strategy.md cites llm-voice-and-context.md for the context manager model. ORIGINS.md provides the conceptual foundation that the other documents assume. The README.md at the project root provides the operational orientation.

A reader can enter at any level:
- **From the code** -- follow the citation in a file header to the relevant architecture doc.
- **From this README** -- pick a topic and read the document.
- **From CLAUDE.md** -- the Architecture section points here for depth.

## Governing standards

Documentation in this directory follows the Feynman Standard: explain why, not just what; teach without announcing you are teaching. The voice is that of a colleague sharing working knowledge. The structure is layered: code comments for the developer at work, these documents for the reader studying the design, CLAUDE.md for the agent or newcomer orienting to the project.
