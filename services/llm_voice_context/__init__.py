#---------------------------------------------------------------------#
#
# services/llm_voice_context/ — Voice and Context Services
#
#   Two services that work together to give agents memory and speech.
#
#   The voice service wraps a single operation: send a prompt to an
#   LLM, get a reply, and log exactly what happened. An agent calls
#   llm_call() to think, reads the response, then decides what to do
#   with it. The LLM call is visible and auditable.
#
#   Each agent writes to its own log file (tmp/{agent}-voice.log).
#   Every entry is timestamped in UTC with a session ID and turn
#   number. Logs record only the delta (new message in, new message
#   out), never the full history.
#
#   The context service manages conversation history with three-tier
#   compaction (distant summary, recent summary, verbatim recent).
#   When the total approaches 90% of CONTEXT_MAX, compaction fires.
#   After compaction, the total is at most 30% of CONTEXT_MAX.
#
#   Each conversation session gets its own ConversationContext
#   instance, keyed by context_id. Instances never share state.
#
#---------------------------------------------------------------------#

from services.llm_voice_context.voice import llm_call
from services.llm_voice_context.context import ConversationContext

__all__ = ["llm_call", "ConversationContext"]
