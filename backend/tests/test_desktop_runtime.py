from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import DESKTOP_AUTH_TOKEN_ENV, desktop_auth_token
from app.database import DB_PATH, REPOSITORY_DB_DIR, resolved_database_path
from app.desktop_entry import MAX_STARTUP_MESSAGE_BYTES, parse_startup_message, startup_message
from app.main import _authorized_api_request, app


TOKEN = "a" * 64


async def asgi_request(
    method: str,
    path: str,
    headers: list[tuple[bytes, bytes]] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    messages: list[dict[str, object]] = []
    request_sent = False

    async def receive() -> dict[str, object]:
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message: dict[str, object]) -> None:
        messages.append(message)

    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "root_path": "",
            "headers": headers or [],
            "client": ("127.0.0.1", 40000),
            "server": ("127.0.0.1", 8000),
        },
        receive,
        send,
    )
    start = next(message for message in messages if message["type"] == "http.response.start")
    response_headers = {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in start["headers"]
    }
    body = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )
    return int(start["status"]), response_headers, body


class DesktopDataDirectoryTests(unittest.TestCase):
    def test_repository_fallback_is_unchanged_when_override_is_absent(self) -> None:
        self.assertEqual(
            resolved_database_path(None, environment_present=False),
            REPOSITORY_DB_DIR / "glacial.db",
        )
        self.assertEqual(DB_PATH.name, "glacial.db")

    def test_absolute_desktop_override_uses_a_dedicated_database(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "data"
            self.assertEqual(
                resolved_database_path(str(data_dir), environment_present=True),
                data_dir.resolve() / "glacial.db",
            )

    def test_invalid_desktop_overrides_are_rejected(self) -> None:
        invalid_values = (None, "", "relative\\data", "C:\\temp\\..\\escape", "bad\0path")
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    resolved_database_path(value, environment_present=True)


class DesktopAuthenticationTests(unittest.TestCase):
    def test_authentication_is_disabled_only_when_environment_variable_is_absent(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(desktop_auth_token())
        self.assertIsNone(desktop_auth_token(None, environment=False))

    def test_token_configuration_is_exact(self) -> None:
        self.assertEqual(desktop_auth_token(TOKEN, environment=False), TOKEN)
        for value in ("", "a" * 63, "A" * 64, "g" * 64):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    desktop_auth_token(value, environment=False)

    def test_api_authentication_accepts_only_the_exact_bearer_value(self) -> None:
        self.assertTrue(_authorized_api_request("/api/health", "GET", f"Bearer {TOKEN}", TOKEN))
        for value in (None, "", TOKEN, f"bearer {TOKEN}", f"Bearer {TOKEN[:-1]}b"):
            with self.subTest(value=value):
                self.assertFalse(_authorized_api_request("/api/health", "GET", value, TOKEN))

    def test_missing_malformed_and_incorrect_tokens_return_401(self) -> None:
        with patch.dict(os.environ, {DESKTOP_AUTH_TOKEN_ENV: TOKEN}, clear=False):
            for authorization in (None, b"Basic abc", f"Bearer {'b' * 64}".encode("ascii")):
                headers = [] if authorization is None else [(b"authorization", authorization)]
                status, _, body = asyncio.run(asgi_request("GET", "/api/health", headers))
                self.assertEqual(status, 401)
                self.assertEqual(json.loads(body), {"detail": "Desktop API authentication is required."})

    def test_authentication_disabled_and_enabled_health_requests(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            status, _, body = asyncio.run(asgi_request("GET", "/api/health"))
            self.assertEqual((status, json.loads(body)), (200, {"status": "ok"}))
        with patch.dict(os.environ, {DESKTOP_AUTH_TOKEN_ENV: TOKEN}, clear=False):
            status, _, body = asyncio.run(
                asgi_request("GET", "/api/health", [(b"authorization", f"Bearer {TOKEN}".encode("ascii"))])
            )
            self.assertEqual((status, json.loads(body)), (200, {"status": "ok"}))

    def test_cors_preflight_remains_available_with_desktop_authentication(self) -> None:
        headers = [
            (b"origin", b"http://127.0.0.1:5173"),
            (b"access-control-request-method", b"GET"),
            (b"access-control-request-headers", b"authorization"),
        ]
        with patch.dict(os.environ, {DESKTOP_AUTH_TOKEN_ENV: TOKEN}, clear=False):
            status, response_headers, _ = asyncio.run(asgi_request("OPTIONS", "/api/health", headers))
        self.assertEqual(status, 200)
        self.assertEqual(response_headers["access-control-allow-origin"], "http://127.0.0.1:5173")
        self.assertIn("Authorization", response_headers["access-control-allow-headers"])


class DesktopStartupMessageTests(unittest.TestCase):
    def test_startup_message_is_exact_bounded_and_round_trips(self) -> None:
        message = startup_message(49152)
        self.assertEqual(message, 'GLACIAL_BACKEND_READY {"port":49152}')
        self.assertLessEqual(len(message.encode("ascii")), MAX_STARTUP_MESSAGE_BYTES)
        self.assertEqual(parse_startup_message(message), 49152)

    def test_malformed_duplicate_and_oversized_messages_are_rejected(self) -> None:
        invalid = (
            "",
            'GLACIAL_BACKEND_READY {"port":0}',
            'GLACIAL_BACKEND_READY {"port":8000,"port":8001}',
            'GLACIAL_BACKEND_READY {"port":8000,"token":"secret"}',
            'GLACIAL_BACKEND_READY {"port":8000}\nextra',
            "x" * (MAX_STARTUP_MESSAGE_BYTES + 1),
        )
        for message in invalid:
            with self.subTest(message=message):
                with self.assertRaises(ValueError):
                    parse_startup_message(message)


if __name__ == "__main__":
    unittest.main()
