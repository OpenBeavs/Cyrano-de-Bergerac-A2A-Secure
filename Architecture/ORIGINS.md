# Origins -- Literary Context and Design Philosophy

## The Play

Edmond Rostand's *Cyrano de Bergerac* (1897) is a comedic drama built on a single elegant deception. Cyrano -- brilliant, eloquent, and convinced he is unlovable -- secretly composes love letters and speeches for Christian de Neuvillette, a handsome soldier who lacks the words to woo Roxane. Christian delivers Cyrano's words as his own. Roxane falls in love with the eloquence, never knowing its true author.

The arrangement has three clearly defined roles and two handoff boundaries:

- **Roxane** receives the words. She interacts with Christian and has no knowledge of Cyrano's involvement.
- **Christian** is the intermediary. He faces Roxane, but the substance comes from behind him.
- **Cyrano** is the hidden talent. He never speaks to Roxane directly. His output flows through Christian, who gets the credit.

The comedy -- and the tragedy -- comes from the fact that this indirection works flawlessly. The system produces results that no single participant could achieve alone.

## How the Play Maps to the System

The system mirrors the play with two agents:

- **The user** plays Roxane. They type at the CLI prompt and receive eloquent replies without knowing their true author.
- **Chris** plays Christian. He is the front man -- the CLI chat client that faces the user and delivers Cyrano's words. Today he is a pure relay: every message passes through to Cyrano, and every reply passes back. He makes no LLM calls and adds no judgment of his own.
- **Cyrano** is the hidden wordsmith. He receives messages from Chris via the A2A protocol, crafts eloquent replies using a Gemini LLM, and returns them. Only Chris knows he exists.

The user sees a conversation with Chris. They never see Cyrano, never interact with the A2A protocol, never know that an entirely separate agent is composing their replies.

## Why This Structure Exists

This project exists as a **scaffold** -- a minimal, working demonstration of Agent-to-Agent communication using the A2A protocol. The two agents are intentionally simple so the architecture is visible. The point is not what any individual agent does; the point is how they communicate across an A2A boundary.

Chris is the interesting design element. Today he is a thin client, but the architecture positions him to become more. A richer system could have Chris analyze messages before forwarding, choose among multiple Cyranos, transform requests, or add his own judgment. The A2A plumbing is already in place; the evolution happens in Chris's code.

That extensibility is the reason the scaffold exists. A team starting a real agent system can fork this structure, replace the agent logic with domain-specific behavior, and have the A2A communication already working.

## The Working System Principle

See [working-system-principle.md](working-system-principle.md) -- the development philosophy that governs how this project (and any agentic system) should evolve: working system to working system, every single day.
