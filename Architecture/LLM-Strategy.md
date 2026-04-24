# LLM Strategy -- Who Uses What, and Why

## Cyrano -- The Generative Engine

**Model:** `gemini-3.1-pro-preview` (configured via `CYRANO_MODEL`)

Cyrano is the only agent in the system that *generates* the user-visible response. His entire job is language production: take a message and craft an eloquent, expressive reply. The quality of his output *is* the quality of the system's output.

This is why Cyrano gets the most capable model. The difference between a good language model and a great one shows up exactly here -- in fluency, nuance, and the ability to sustain a voice across turns. Cyrano's model is the one place where spending more buys a directly better user experience.

Chris, the other agent, makes no LLM calls at all. He is a CLI chat client that relays messages to Cyrano via the A2A protocol.

## Context Manager -- The Infrastructure Model

**Model:** `gemini-3.1-flash-lite-preview` (configured via `CONTEXT_MANAGER_LLM`, defaults to `CYRANO_MODEL`)

The context manager isn't an agent -- it's the LLM that the context service uses to summarize conversation history during compaction. When a conversation approaches the context window limit (90% of `CONTEXT_MAX`), the context service compresses older messages into summaries. This compression requires an LLM call, and that call uses `CONTEXT_MANAGER_LLM`.

The model choice is straightforward: summarization is a fast, low-token task that doesn't need creativity. A lightweight model handles it with low latency and low cost. Unlike Cyrano's output, the summaries are never user-visible -- they're internal context that the model reads for coherence, not prose that the user judges for quality.

The default-to-`CYRANO_MODEL` behavior means the system works with zero extra configuration. Separating the variable lets you override it if needed -- for example, using a cheaper model for summarization to reduce cost in long conversations.

See [llm-voice-and-context.md](llm-voice-and-context.md) for the three-tier compaction algorithm that drives these LLM calls.

## The Model Configuration Pattern

All models are assigned through environment variables in `.env`:

```
# Agent model
CYRANO_MODEL="gemini-3.1-pro-preview"

# Infrastructure model (defaults to CYRANO_MODEL if not set)
CONTEXT_MANAGER_LLM="gemini-3.1-flash-lite-preview"
```

This keeps model selection out of the code and allows experimentation without code changes. You can swap Cyrano to a different model, compare outputs, and swap back -- all by editing one line in `.env`. This matters because model capabilities shift with every release. The model that's best for generation today may not be tomorrow's best, and the configuration pattern lets you track that evolution without touching agent logic.

The `-preview` suffix on the model names means these are early-access releases from Google -- available for development but subject to change before the stable versions ship.

The startup validator (`services/env_validator.py`) checks all model variables at boot time. `CYRANO_MODEL` causes a hard failure if missing. `CONTEXT_MANAGER_LLM` is optional -- it falls back to `CYRANO_MODEL` with a warning. `CONTEXT_MAX` defaults to 131072 (128K tokens) if not set.
