from __future__ import annotations

import json
import socket
import sys

import uvicorn

from app.config import desktop_auth_token
from app.database import prepare_database_directory
from app.main import app


LOOPBACK_HOST = "127.0.0.1"
STARTUP_PREFIX = "GLACIAL_BACKEND_READY "
MAX_STARTUP_MESSAGE_BYTES = 96


def startup_message(port: int) -> str:
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise ValueError("startup port must be a valid TCP port")
    message = STARTUP_PREFIX + json.dumps({"port": port}, separators=(",", ":"))
    if len(message.encode("ascii")) > MAX_STARTUP_MESSAGE_BYTES:
        raise ValueError("startup message is too large")
    return message


def parse_startup_message(message: str) -> int:
    if not message or "\n" in message or "\r" in message:
        raise ValueError("startup message must contain exactly one line")
    if len(message.encode("utf-8")) > MAX_STARTUP_MESSAGE_BYTES or not message.startswith(STARTUP_PREFIX):
        raise ValueError("startup message is invalid")
    try:
        payload = json.loads(
            message[len(STARTUP_PREFIX) :],
            object_pairs_hook=_unique_object,
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError("startup message is invalid") from exc
    if not isinstance(payload, dict) or set(payload) != {"port"}:
        raise ValueError("startup message is invalid")
    port = payload["port"]
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise ValueError("startup message is invalid")
    return port


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate startup message key")
        result[key] = value
    return result


def run() -> int:
    listener: socket.socket | None = None
    try:
        desktop_auth_token()
        prepare_database_directory()
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind((LOOPBACK_HOST, 0))
        port = listener.getsockname()[1]
        print(startup_message(port), flush=True)

        config = uvicorn.Config(
            app,
            host=LOOPBACK_HOST,
            port=0,
            access_log=False,
            log_level="warning",
            proxy_headers=False,
            server_header=False,
        )
        server = uvicorn.Server(config)
        server.run(sockets=[listener])
        return 0 if server.started else 1
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) and exc.code != 0 else 1
    except Exception:
        print("Glacial backend startup failed.", file=sys.stderr, flush=True)
        return 1
    finally:
        if listener is not None:
            listener.close()


if __name__ == "__main__":
    raise SystemExit(run())
