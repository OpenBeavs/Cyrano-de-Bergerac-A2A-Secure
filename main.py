import sys
import os
import warnings

warnings.filterwarnings("ignore")

from services.env_validator import validate_env

LOG_DIR = os.path.join(os.path.dirname(__file__) or ".", "tmp")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "a2a-backend.log")

USAGE = """Usage: python main.py <command>

Commands:
  serve registry   Start the Agent Registry (port 8003, HTTPS)
  serve cyrano     Start Cyrano's A2A server (port 8002, HTTPS)
  chat [agent_id]  Start the Chris chat client (default: cyrano-001)
"""


def _make_log_config():
    """Build a uvicorn log config that sends output to the log file."""
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "handlers": {
            "file": {
                "class": "logging.FileHandler",
                "filename": LOG_FILE,
                "formatter": "default",
            },
        },
        "formatters": {
            "default": {
                "fmt": "%(asctime)s %(levelname)s %(name)s: %(message)s",
            },
        },
        "loggers": {
            "uvicorn":        {"handlers": ["file"], "level": "INFO", "propagate": False},
            "uvicorn.error":  {"handlers": ["file"], "level": "INFO", "propagate": False},
            "uvicorn.access": {"handlers": ["file"], "level": "INFO", "propagate": False},
        },
    }


def serve_registry():
    """Run the Agent Registry as an HTTPS server."""
    import logging
    import uvicorn

    cert_dir = os.path.join(os.path.dirname(__file__) or ".", "certs")
    ssl_cert = os.path.join(cert_dir, "registry.crt")
    ssl_key = os.path.join(cert_dir, "registry.key")

    if not os.path.exists(ssl_cert):
        print("  *** certs/ not found. Run: python3 scripts/mock_ca.py")
        sys.exit(1)

    print("  Loading Agent Registry ...", end=" ", flush=True)
    from registry.agent_registry import app as registry_app
    print("done.")
    print()

    logging.basicConfig(
        filename=LOG_FILE, level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    print("  Agent Registry running on https://localhost:8003")
    print("  Logs: tmp/a2a-backend.log")
    print()
    sys.stdout.flush()
    uvicorn.run(
        registry_app,
        host="127.0.0.1",
        port=8003,
        ssl_keyfile=ssl_key,
        ssl_certfile=ssl_cert,
        log_config=_make_log_config(),
    )


def serve_cyrano():
    """Run Cyrano as a uvicorn A2A HTTPS server."""
    import logging
    import uvicorn

    validate_env(scope="cyrano")

    cert_dir = os.path.join(os.path.dirname(__file__) or ".", "certs")
    ssl_cert = os.path.join(cert_dir, "cyrano.crt")
    ssl_key = os.path.join(cert_dir, "cyrano.key")

    if not os.path.exists(ssl_cert):
        print("  *** certs/ not found. Run: python3 scripts/mock_ca.py")
        sys.exit(1)

    print("  Loading Cyrano ...", end=" ", flush=True)
    from agents.cyrano import a2a_app
    print("done.")
    print()

    logging.basicConfig(
        filename=LOG_FILE, level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    print("  Cyrano A2A server running on https://localhost:8002")
    print("  Logs: tmp/a2a-backend.log")
    print()
    print("  To chat, open another terminal and run:")
    print("      python main.py chat")
    print()
    sys.stdout.flush()
    uvicorn.run(
        a2a_app,
        host="127.0.0.1",
        port=8002,
        ssl_keyfile=ssl_key,
        ssl_certfile=ssl_cert,
        log_config=_make_log_config(),
    )


def run_chat():
    """Run Chris as a CLI chat client."""
    print()
    print("  ─────────────────────────────────────────────────────────────────────")
    print("  Make sure Cyrano is running first. If not, open another terminal:")
    print()
    print("      python main.py serve cyrano")
    print("  ─────────────────────────────────────────────────────────────────────")
    print()

    from agents.chris import main as chris_main
    chris_main()


def main():
    if len(sys.argv) < 2:
        print(USAGE)
        sys.exit(1)

    command = sys.argv[1]

    if command == "serve":
        if len(sys.argv) < 3:
            print("Usage: python main.py serve <registry|cyrano>")
            sys.exit(1)
        target = sys.argv[2]
        if target == "registry":
            serve_registry()
        elif target == "cyrano":
            serve_cyrano()
        else:
            print(f"Unknown serve target: {target}")
            sys.exit(1)

    elif command == "chat":
        run_chat()

    else:
        print(f"Unknown command: {command}")
        print(USAGE)
        sys.exit(1)


if __name__ == "__main__":
    main()
