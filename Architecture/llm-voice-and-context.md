# Voice and Context Services -- Design Rationale

The voice and context services are the audit and memory layers of the CDB system. They exist to make every LLM call visible and to manage conversation history within finite context windows. This document explains the problem, the solution, and the mechanism.

## The Voice Service

**Location:** `services/llm_voice_context/voice.py`

The voice service wraps a single operation: send a prompt to an LLM, get a reply, log exactly what happened.

**`llm_call()`** makes a Gemini API call via the `google.genai` SDK and logs the exchange. Parameters: agent name, session ID, system message, user message, conversation history, model ID, temperature. Returns the response text and token usage.

Cyrano's `AgentExecutor.execute()` calls `voice.llm_call()` directly. The voice service makes the Gemini API call, records the exchange, and returns the response. Cyrano then wraps the response text in an A2A `Message` and publishes it to the event queue.

### Audit log format

Each agent writes to `tmp/{agent_name}-voice.log`. Entries are JSON lines -- one JSON object per line, no surrounding array. Each entry records:

```json
{
  "timestamp": "2026-04-01T15:30:42.123456+00:00",
  "session_id": "a1b2c3d4e5f6",
  "turn": 3,
  "agent": "cyrano",
  "model": "gemini-3.1-pro-preview",
  "input": "Venus is bright tonight",
  "output": "Indeed, my love -- she burns with...",
  "tokens": {
    "input": 847,
    "output": 156,
    "total": 1003
  }
}
```

Deliberate constraint: the log records only the delta -- the new message in and the new message out. It never dumps the full conversation history. If it did, logs would grow quadratically with conversation length (each entry would include every previous message). The full conversation can always be reassembled from the sequence of deltas by reading the log in order.

Turn numbers are per-session, per-process. UTC timestamps are the authoritative ordering for audit reconstruction.

### Genai client

The `google.genai` SDK is used directly for LLM calls. The client is a lazy singleton -- created on first use with `GEMINI_API_KEY` from the environment. This avoids import-time side effects.

## The Context Service

**Location:** `services/llm_voice_context/context.py`

The context service solves a fundamental problem: context windows are finite, but conversations aren't. Left unchecked, conversation history grows until it exceeds the model's context window and the call fails.

### Three-tier compaction

The solution is three-tier compaction. Instead of summarizing everything (which destroys the verbatim recent exchanges the model needs for coherent dialogue) or keeping everything (which eventually overflows), we maintain three tiers with different fidelity:

```
 distant_history      Compressed narrative of the deep past.
                      "We discussed X, then Y, then Z."
                      Budget: <=10% of CONTEXT_MAX.

 summarized_recent    Compressed summary of the near past.
                      Bridges deep history and verbatim messages.
                      Budget: <=10% of CONTEXT_MAX.

 verbatim_recent      Exact recent messages, word for word.
                      What the model reads for coherent replies.
                      Budget: <=10% of CONTEXT_MAX.
```

Total post-compaction: at most 30% of CONTEXT_MAX, leaving 70% headroom for new conversation.

### When compaction fires

Compaction triggers when total token usage across all three tiers reaches 90% of CONTEXT_MAX. The 10% gap between trigger (90%) and window limit (100%) is the safety margin -- it absorbs the next few messages while compaction runs.

### How compaction works

1. **Split verbatim in half.** The newest messages stay verbatim (they're what the model needs). The oldest messages become candidates for summarization.

2. **Fill the verbatim tier.** Take as many newest messages as fit within 10% of CONTEXT_MAX. Anything that doesn't fit overflows into the summarization candidates.

3. **Summarize into summarized_recent.** Combine any existing summarized_recent with the overflow messages. Send to the context manager LLM with instructions to compress. Truncate to the 10% budget.

4. **Compress distant_history if over budget.** If distant_history has grown past 10%, compress it further via another LLM call.

5. **Update the verbatim tier.** Replace with only the messages that fit.

The context manager LLM is configured via `CONTEXT_MANAGER_LLM` (defaults to `CYRANO_MODEL`). It should be fast and cheap -- summarization doesn't need creativity, and compaction sits on the critical path when it fires. See [LLM-Strategy.md](LLM-Strategy.md) for model rationale.

### Token estimation

Token counting uses a 4-characters-per-token heuristic: `max(1, len(text) // 4)`. This avoids the latency of calling a real tokenizer on every `add_message()` call. The 90% trigger provides enough margin that the ~20% variance of the heuristic doesn't matter -- we compact a little early or a little late, but never overflow.

### Per-agent context instances

Each `ConversationContext` instance manages one conversation channel. Cyrano has one context instance per `context_id` (each `context_id` represents a distinct conversation session initiated by Chris).

### History assembly

`get_history()` assembles the three tiers into a flat message list ready for `voice.llm_call()`:

1. If compressed history exists, inject a context preamble: a "user" message containing the distant and summarized tiers, followed by a "model" acknowledgment. This gives the LLM background without polluting the verbatim conversation.

2. Append the verbatim recent messages exactly as recorded.

The result is a `list[dict]` of `{"role": "user"|"model", "content": "..."}` entries that the voice service passes directly to the Gemini API as the conversation contents.

## The Startup Validator

**Location:** `services/env_validator.py`

`validate_env(scope)` runs before any heavy imports or server startup. It loads `.env`, checks required variables, warns on missing optional variables with fallback defaults, and fails fast with actionable guidance if anything required is missing.

Required variables: `GEMINI_API_KEY`, `CYRANO_MODEL`. Optional variables (`CONTEXT_MANAGER_LLM`, `CONTEXT_MAX`) get defaults and warnings, not failures. The operator sees exactly what's falling back and can decide whether to configure explicitly.

## Cross-References

- **Code:** `agents/cyrano.py` -- the `CyranoExecutor` that wires into these services; `agents/chris.py` -- the CLI client
- **Architecture:** [system-architecture.md](system-architecture.md) -- where the services sit in the system topology
- **Strategy:** [LLM-Strategy.md](LLM-Strategy.md) -- model selection for Cyrano and for the context manager
- **Standards:** The Feynman Standard governs the teaching commentary in the service code (see CLAUDE.md)
