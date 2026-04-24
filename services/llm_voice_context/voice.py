#---------------------------------------------------------------------#
#
# voice.py — LLM call with audit logging
#
#   This module does one thing: send a prompt to an LLM and return
#   the reply, while recording exactly what happened to a log file.
#
#   The interface is deliberately simple. An agent provides:
#     - who it is (agent_name)
#     - which conversation this belongs to (session_id)
#     - the system message (character / role instructions)
#     - the user message (what to respond to)
#     - the conversation history (prior turns, managed by the
#       context service)
#     - which model to use (model_id)
#     - optionally, a temperature
#
#   The function returns the LLM's response text and token usage.
#   The agent decides what to do with the response — send it via
#   A2A, return it to the user, or discard it. The voice service
#   doesn't care; it just speaks and logs.
#
#   The google.genai SDK (v1.x) is the underlying transport. The
#   SDK is initialized once, lazily, using the same GEMINI_API_KEY
#   that the rest of the system uses.
#
#---------------------------------------------------------------------#

import os
import json
import logging
from datetime import datetime, timezone

from google import genai
from google.genai import types


# ── Logging setup ──────────────────────────────────────────────────
#
#   Each agent gets its own log file: tmp/{agent_name}-voice.log.
#   We keep a dict of loggers so we create each one only once.
#   The log directory is the same tmp/ the rest of CDB uses.

LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "tmp")
_loggers: dict[str, logging.Logger] = {}


def _get_logger(agent_name: str) -> logging.Logger:
    """Return (or create) a file logger for the given agent."""
    if agent_name in _loggers:
        return _loggers[agent_name]

    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, f"{agent_name}-voice.log")

    logger = logging.getLogger(f"voice.{agent_name}")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)

    _loggers[agent_name] = logger
    return logger


# ── Genai client ───────────────────────────────────────────────────
#
#   Lazy singleton. The first call to llm_call() creates it using
#   GEMINI_API_KEY from the environment. This avoids import-time
#   side effects — the .env is already loaded by the time any
#   agent calls voice.llm_call().

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Cannot make LLM calls."
            )
        _client = genai.Client(api_key=api_key)
    return _client


# ── Turn counter ───────────────────────────────────────────────────
#
#   Simple per-session counter so log entries show the conversation
#   turn number. Resets when a new session starts.

_turn_counters: dict[str, int] = {}


def _next_turn(session_id: str) -> int:
    count = _turn_counters.get(session_id, 0) + 1
    _turn_counters[session_id] = count
    return count


# ── The main function ──────────────────────────────────────────────

def llm_call(
    agent_name: str,
    session_id: str,
    system_message: str,
    user_message: str,
    conversation_history: list[dict] | None = None,
    model_id: str | None = None,
    temperature: float = 1.0,
) -> dict:
    """Make an LLM call and log the exchange.

    Parameters
    ----------
    agent_name : str
        Who is speaking (e.g. "cyrano", "context-manager").
    session_id : str
        Conversation identifier. Ties log entries together across
        agents.
    system_message : str
        The agent's system prompt — character, role, instructions.
    user_message : str
        The message to respond to.
    conversation_history : list[dict], optional
        Prior turns as [{"role": "user"|"model", "content": "..."}].
        Managed by the context service. The voice service passes
        this through to the LLM but never logs it (only the delta).
    model_id : str, optional
        Gemini model ID. Falls back to the agent's env var
        ({AGENT_NAME}_MODEL) if not provided.
    temperature : float
        Sampling temperature. Default 1.0.

    Returns
    -------
    dict
        {
            "response": str,       # The LLM's reply text
            "input_tokens": int,   # Tokens in the prompt
            "output_tokens": int,  # Tokens in the reply
            "total_tokens": int,   # Sum of the above
        }
    """

    # ── Resolve model ──────────────────────────────────────────
    #
    #   Three ways to specify the model, in priority order:
    #   1. Explicit model_id argument
    #   2. {AGENT_NAME}_MODEL environment variable
    #   3. Fail — no guessing, no silent defaults

    if not model_id:
        env_var = f"{agent_name.upper()}_MODEL"
        model_id = os.environ.get(env_var)
        if not model_id:
            raise RuntimeError(
                f"No model_id provided and {env_var} is not set."
            )

    # ── Build the contents list ────────────────────────────────
    #
    #   The genai SDK takes a list of Content objects. The system
    #   message goes into the config (system_instruction), not
    #   into the contents. The conversation history and the new
    #   user message are the contents.

    contents = []

    if conversation_history:
        for turn in conversation_history:
            contents.append(
                types.Content(
                    role=turn["role"],
                    parts=[types.Part.from_text(text=turn["content"])],
                )
            )

    contents.append(
        types.Content(
            role="user",
            parts=[types.Part.from_text(text=user_message)],
        )
    )

    # ── Make the call ──────────────────────────────────────────

    client = _get_client()
    response = client.models.generate_content(
        model=model_id,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system_message,
            temperature=temperature,
        ),
    )

    response_text = response.text or ""

    # ── Extract token usage ────────────────────────────────────

    usage = response.usage_metadata
    input_tokens = usage.prompt_token_count or 0 if usage else 0
    output_tokens = usage.candidates_token_count or 0 if usage else 0
    total_tokens = usage.total_token_count or 0 if usage else 0

    # ── Log the exchange ───────────────────────────────────────
    #
    #   Each log entry is a single JSON line — easy to parse, easy
    #   to grep, easy to feed into analysis tools. We log only the
    #   new user message and the new response (the delta), never
    #   the full conversation history. An auditor reconstructs the
    #   full conversation by reading the log in order.

    turn = _next_turn(session_id)
    logger = _get_logger(agent_name)

    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "turn": turn,
        "agent": agent_name,
        "model": model_id,
        "input": user_message,
        "output": response_text,
        "tokens": {
            "input": input_tokens,
            "output": output_tokens,
            "total": total_tokens,
        },
    }
    logger.info(json.dumps(log_entry, ensure_ascii=False))

    return {
        "response": response_text,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


#---------------------------------------------------------------------#
#eof#
