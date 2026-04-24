#---------------------------------------------------------------------#
#
# env_validator.py — Environment Validation
#
#   Called at the top of main.py before any heavy imports or server
#   startup. Its job: fail fast with a clear message if the
#   environment is misconfigured.
#
#---------------------------------------------------------------------#

import os
import sys
from dotenv import load_dotenv


def validate_env(scope: str = "cyrano"):
    """Validate environment variables and fail fast on errors.

    Parameters
    ----------
    scope : str
        Which set of variables to check:
        - "cyrano" — check API key + Cyrano model (default)

    Loads .env before checking. Safe to call multiple times.
    """
    load_dotenv()

    errors = []
    warnings = []

    if not os.environ.get("GEMINI_API_KEY"):
        errors.append(
            "GEMINI_API_KEY is not set.\n"
            "    Get an API key at https://aistudio.google.com/apikey\n"
            "    Then add it to your .env file."
        )

    if not os.environ.get("CYRANO_MODEL"):
        errors.append(
            "CYRANO_MODEL is not set.\n"
            '    Example: CYRANO_MODEL="gemini-3.1-pro-preview"'
        )

    if not os.environ.get("CONTEXT_MANAGER_LLM"):
        fallback = os.environ.get("CYRANO_MODEL")
        if fallback:
            warnings.append(
                f"CONTEXT_MANAGER_LLM is not set. "
                f"Defaulting to CYRANO_MODEL ({fallback})."
            )
            os.environ["CONTEXT_MANAGER_LLM"] = fallback
        else:
            warnings.append(
                "CONTEXT_MANAGER_LLM is not set and CYRANO_MODEL is "
                "unavailable for fallback. Context compaction will "
                "fail until one of these is configured."
            )

    if not os.environ.get("CONTEXT_MAX"):
        warnings.append(
            "CONTEXT_MAX is not set. Defaulting to 131072 (128K tokens)."
        )

    if warnings:
        for w in warnings:
            print(f"  [warn] {w}")
        print()

    if errors:
        print()
        print("  *** CONFIGURATION ERROR ***")
        print()
        for e in errors:
            for line in e.split("\n"):
                print(f"  {line}")
            print()
        print("  Copy .env.example to .env and fill in the values.")
        print()
        sys.exit(1)


#---------------------------------------------------------------------#
#eof#
