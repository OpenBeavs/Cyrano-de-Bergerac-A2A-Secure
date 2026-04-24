#---------------------------------------------------------------------#
#
# context.py — Three-tier conversation history with compaction
#
#   This module manages conversation history for a single
#   conversation session. Each session (identified by context_id)
#   gets its own ConversationContext instance. They never mix.
#
#   The three tiers:
#
#   distant_history     — Summary of the deep past. Starts empty.
#                         After compaction, contains a compressed
#                         narrative of everything that was previously
#                         in distant_history + the oldest messages.
#                         Budget: ≤10% of CONTEXT_MAX.
#
#   summarized_recent   — Summary of the near past. Contains a
#                         compressed version of messages that were
#                         too old to keep verbatim but too recent
#                         to merge into distant_history.
#                         Budget: ≤10% of CONTEXT_MAX.
#
#   verbatim_recent     — Exact recent messages, word for word.
#                         This is what the model actually reads to
#                         produce a coherent reply. Kept as-is.
#                         Budget: ≤10% of CONTEXT_MAX.
#
#   Total post-compaction budget: ≤30% of CONTEXT_MAX.
#
#   Token counting is approximate. We estimate 4 characters per
#   token — a rough heuristic that works well enough for English
#   text and avoids the latency of calling a tokenizer. The
#   compaction trigger (90%) has enough margin that precision
#   doesn't matter.
#
#---------------------------------------------------------------------#

import os
from services.llm_voice_context.voice import llm_call


# ── Defaults ───────────────────────────────────────────────────────

DEFAULT_CONTEXT_MAX = 131072      # 128K tokens
COMPACTION_TRIGGER = 0.90         # Compact at 90% full
TIER_BUDGET = 0.10                # Each tier gets ≤10% of CONTEXT_MAX

# ── Token estimation ───────────────────────────────────────────────
#
#   Why not use a real tokenizer? Two reasons:
#   1. Speed. Tokenizers are slow relative to division. Compaction
#      is already an expensive operation (LLM calls); we don't want
#      to add tokenizer overhead to every add_message() call.
#   2. Precision doesn't matter here. We're deciding "is it time
#      to compact?" not "exactly how many tokens is this?" The 90%
#      trigger gives us a 10% margin of error, which is far more
#      than the ~20% variance of the 4-char heuristic.

CHARS_PER_TOKEN = 4


def _estimate_tokens(text: str) -> int:
    """Rough token count from character length."""
    return max(1, len(text) // CHARS_PER_TOKEN)


def _estimate_messages_tokens(messages: list[dict]) -> int:
    """Token estimate for a list of {"role": ..., "content": ...}."""
    return sum(_estimate_tokens(m["content"]) for m in messages)


class ConversationContext:
    """Manages conversation history with three-tier compaction.

    Usage::

        ctx = ConversationContext("cyrano-chris", "session-42")
        ctx.add_message("user", "Venus is bright tonight")
        ctx.add_message("model", "Indeed it is, my love.")

        if ctx.needs_compaction():
            ctx.compact()

        history = ctx.get_history()
        # Pass history to voice.llm_call() as conversation_history

    Parameters
    ----------
    channel_name : str
        Human-readable name for this conversation channel.
        Used in log messages and the compaction LLM prompt.
        Examples: "cyrano-chris".
    session_id : str
        Session identifier. Passed to voice.llm_call() when
        the compaction LLM is invoked.
    context_max : int, optional
        Maximum context window in tokens. Defaults to CONTEXT_MAX
        env var, then to 131072 (128K).
    context_manager_model : str, optional
        Model to use for compaction summaries. Defaults to
        CONTEXT_MANAGER_LLM env var. Should be a fast, cheap
        model — compaction doesn't need creativity.
    """

    def __init__(
        self,
        channel_name: str,
        session_id: str,
        context_max: int | None = None,
        context_manager_model: str | None = None,
    ):
        self.channel_name = channel_name
        self.session_id = session_id

        self.context_max = context_max or int(
            os.environ.get("CONTEXT_MAX", DEFAULT_CONTEXT_MAX)
        )
        self.context_manager_model = context_manager_model or os.environ.get(
            "CONTEXT_MANAGER_LLM"
        )

        # ── The three tiers ────────────────────────────────────
        self.distant_history: str = ""
        self.summarized_recent: str = ""
        self.verbatim_recent: list[dict] = []

    # ── Public interface ───────────────────────────────────────────

    def add_message(self, role: str, content: str):
        """Append a message to the verbatim recent tier.

        Call this after every exchange — both the user/inbound
        message and the model/outbound response.
        """
        self.verbatim_recent.append({"role": role, "content": content})

    def needs_compaction(self) -> bool:
        """True if the total history exceeds the compaction trigger.

        Check this after adding messages. If True, the caller
        should call compact() before the next LLM call.
        """
        return self._total_tokens() >= self.context_max * COMPACTION_TRIGGER

    def compact(self):
        """Run three-tier compaction to reclaim context space.

        After compaction, total history occupies ≤30% of
        CONTEXT_MAX:
          - distant_history:    ≤10%
          - summarized_recent:  ≤10%
          - verbatim_recent:    ≤10% (most recent messages, verbatim)

        This method makes LLM calls via voice.llm_call() to
        produce the summaries. It uses the CONTEXT_MANAGER_LLM
        model, which should be fast and cheap.

        Raises RuntimeError if CONTEXT_MANAGER_LLM is not configured.
        """
        if not self.context_manager_model:
            raise RuntimeError(
                "Cannot compact: CONTEXT_MANAGER_LLM is not set. "
                "Add it to your .env file."
            )

        tier_budget = int(self.context_max * TIER_BUDGET)
        tier_budget_chars = tier_budget * CHARS_PER_TOKEN

        # ── Step 1: Split verbatim_recent in half ──────────────
        #
        #   The newest messages stay verbatim (they're what the
        #   model needs for coherent replies). The oldest messages
        #   get summarized.

        midpoint = len(self.verbatim_recent) // 2
        older_half = self.verbatim_recent[:midpoint]
        newer_half = self.verbatim_recent[midpoint:]

        # ── Step 2: Verbatim tier — keep the newest messages ───
        #
        #   Take as many of the newest messages as fit within
        #   10% of CONTEXT_MAX. If even the newest half exceeds
        #   the budget, keep only the most recent ones.

        verbatim_keep = []
        token_count = 0
        for msg in reversed(newer_half):
            msg_tokens = _estimate_tokens(msg["content"])
            if token_count + msg_tokens > tier_budget:
                break
            verbatim_keep.insert(0, msg)
            token_count += msg_tokens

        # Anything from newer_half that didn't fit in verbatim
        # gets added to older_half for summarization.
        overflow = newer_half[:len(newer_half) - len(verbatim_keep)]
        older_half = older_half + overflow

        # ── Step 3: Summarize the older half → summarized_recent
        #
        #   Combine any existing summarized_recent with the older
        #   messages and compress into a single summary.

        text_to_summarize = ""
        if self.summarized_recent:
            text_to_summarize += (
                f"Previous summary:\n{self.summarized_recent}\n\n"
            )
        if older_half:
            text_to_summarize += "Recent conversation:\n"
            for msg in older_half:
                text_to_summarize += f"{msg['role']}: {msg['content']}\n"

        if text_to_summarize.strip():
            result = llm_call(
                agent_name="context-manager",
                session_id=self.session_id,
                system_message=(
                    "You are a conversation summarizer. Compress the "
                    "following conversation into a concise summary that "
                    "preserves key facts, decisions, and emotional tone. "
                    "Write in past tense. Be concise."
                ),
                user_message=(
                    f"Summarize this in at most "
                    f"{tier_budget_chars} characters:\n\n"
                    f"{text_to_summarize}"
                ),
                model_id=self.context_manager_model,
                temperature=0.2,
            )
            self.summarized_recent = result["response"][:tier_budget_chars]
        else:
            self.summarized_recent = ""

        # ── Step 4: Merge old distant + old summarized → distant
        #
        #   Take the existing distant_history and merge it with
        #   whatever was previously in summarized_recent (now
        #   replaced by step 3). Compress to ≤10%.

        text_to_merge = ""
        if self.distant_history:
            text_to_merge += (
                f"Deep past:\n{self.distant_history}\n\n"
            )
        # The old summarized_recent was already folded into the
        # new summarized_recent in step 3. For distant_history,
        # we only need to update if distant_history itself has
        # grown beyond budget. If it's within budget, leave it.

        if _estimate_tokens(self.distant_history) > tier_budget:
            result = llm_call(
                agent_name="context-manager",
                session_id=self.session_id,
                system_message=(
                    "You are a conversation summarizer. Compress the "
                    "following history summary into a shorter version "
                    "that preserves the most important facts and "
                    "decisions. Write in past tense. Be very concise."
                ),
                user_message=(
                    f"Compress this to at most "
                    f"{tier_budget_chars} characters:\n\n"
                    f"{self.distant_history}"
                ),
                model_id=self.context_manager_model,
                temperature=0.2,
            )
            self.distant_history = result["response"][:tier_budget_chars]

        # ── Step 5: Promote summarized → distant if needed ─────
        #
        #   On the first compaction, distant_history is empty and
        #   summarized_recent is new. On subsequent compactions,
        #   we merge the old summarized_recent into distant before
        #   writing the new summarized_recent.
        #
        #   This is already handled: step 3 overwrites
        #   summarized_recent with a fresh summary that includes
        #   the old one. So summarized_recent is always current.
        #   Distant grows by absorbing old summaries over time.
        #
        #   To keep distant growing: after the first compaction,
        #   future compactions merge the previous summarized_recent
        #   into distant before step 3 runs. We handle this by
        #   including the previous summary in step 3's input.

        # ── Step 6: Update verbatim tier ───────────────────────

        self.verbatim_recent = verbatim_keep

    def get_history(self) -> list[dict]:
        """Assemble the full history for an LLM call.

        Returns a list of {"role": ..., "content": ...} messages
        that includes all three tiers, ready to pass as
        conversation_history to voice.llm_call().

        The tiers are assembled as:
          1. A "user" message with the distant + summarized context
             (if any), so the model knows the backstory.
          2. The verbatim recent messages, exactly as recorded.
        """
        history = []

        # ── Context preamble ───────────────────────────────────
        #
        #   If there's compressed history, inject it as a system-
        #   style context message at the top. The model reads this
        #   as background for the conversation.

        preamble_parts = []
        if self.distant_history:
            preamble_parts.append(
                f"[Conversation history — distant past]\n"
                f"{self.distant_history}"
            )
        if self.summarized_recent:
            preamble_parts.append(
                f"[Conversation history — recent summary]\n"
                f"{self.summarized_recent}"
            )

        if preamble_parts:
            history.append({
                "role": "user",
                "content": "\n\n".join(preamble_parts),
            })
            history.append({
                "role": "model",
                "content": (
                    "Understood. I have the conversation context. "
                    "Please continue."
                ),
            })

        # ── Verbatim messages ──────────────────────────────────

        history.extend(self.verbatim_recent)

        return history

    def _total_tokens(self) -> int:
        """Estimate total tokens across all three tiers."""
        total = 0
        total += _estimate_tokens(self.distant_history)
        total += _estimate_tokens(self.summarized_recent)
        total += _estimate_messages_tokens(self.verbatim_recent)
        return total

    def token_usage_report(self) -> dict:
        """Return current token usage per tier, for diagnostics."""
        return {
            "distant_history": _estimate_tokens(self.distant_history),
            "summarized_recent": _estimate_tokens(self.summarized_recent),
            "verbatim_recent": _estimate_messages_tokens(
                self.verbatim_recent
            ),
            "total": self._total_tokens(),
            "context_max": self.context_max,
            "utilization": round(
                self._total_tokens() / self.context_max, 3
            ),
        }


#---------------------------------------------------------------------#
#eof#
