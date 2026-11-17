"""Outils de test : opener HTTP factice (aucun accès réseau), notifiers d'enregistrement, fixtures JSON."""

from __future__ import annotations

import copy
import io
import json
import urllib.error
from email.message import Message
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def load_json(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def make_headers(values: dict[str, str] | None = None) -> Message:
    headers = Message()
    for key, value in (values or {}).items():
        headers[key] = value
    return headers


class FakeResponse:
    def __init__(self, body: Any = b"{}", headers: dict[str, str] | None = None) -> None:
        if not isinstance(body, bytes):
            body = json.dumps(body).encode("utf-8")
        self._body = body
        self.headers = make_headers(headers)

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def http_error(code: int, body: Any = None, headers: dict[str, str] | None = None) -> urllib.error.HTTPError:
    raw = json.dumps(body).encode("utf-8") if body is not None else b""
    return urllib.error.HTTPError(
        "https://api.hetzner.cloud/v1/server_types", code, "error", make_headers(headers), io.BytesIO(raw)
    )


def api_error(code: int, error_code: str, message: str = "", headers: dict[str, str] | None = None):
    return http_error(code, {"error": {"code": error_code, "message": message}}, headers)


class FakeOpener:
    """Remplace urllib.request.urlopen : rejoue des réponses (ou lève des exceptions) dans l'ordre."""

    def __init__(self, *responses: Any) -> None:
        self.responses = list(responses)
        self.requests: list[Any] = []
        self.timeouts: list[Any] = []

    def __call__(self, request: Any, timeout: Any = None) -> FakeResponse:
        self.requests.append(request)
        self.timeouts.append(timeout)
        if not self.responses:
            raise AssertionError(f"requête inattendue : {request.full_url}")
        item = self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, FakeResponse):
            return item
        return FakeResponse(item)


class RecordingNotifier:
    def __init__(self, name: str = "test") -> None:
        self.name = name
        self.messages: list[Any] = []

    def send(self, message: Any) -> None:
        self.messages.append(message)


class FailingNotifier:
    def __init__(self, name: str = "broken", failures: int = 99) -> None:
        self.name = name
        self.failures = failures
        self.calls = 0
        self.messages: list[Any] = []

    def send(self, message: Any) -> None:
        self.calls += 1
        if self.calls <= self.failures:
            raise OSError("connexion refusée")
        self.messages.append(message)


class FakeStop:
    """threading.Event factice : wait() enregistre le délai et arrête la boucle après N attentes."""

    def __init__(self, max_waits: int = 1) -> None:
        self.max_waits = max_waits
        self.waits: list[float] = []
        self._set = False

    def is_set(self) -> bool:
        return self._set

    def set(self) -> None:
        self._set = True

    def wait(self, timeout: float | None = None) -> bool:
        self.waits.append(float(timeout or 0))
        if len(self.waits) >= self.max_waits:
            self._set = True
        return self._set


class Clock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def set_available(server_types: list[dict[str, Any]], name: str, location: str, available: bool) -> None:
    for st in server_types:
        if st["name"] == name:
            for loc in st["locations"]:
                if loc["name"] == location:
                    loc["available"] = available
                    return
    raise KeyError(f"{name}@{location}")


@pytest.fixture
def mixed() -> list[dict[str, Any]]:
    """server_types_mixed.json : disponibles = cx23 partout, cx33@fsn1, cx43@nbg1, cax21@hel1, cpx22@ash.

    cx43@hel1 est disponible mais déprécié (ignoré) ; ccx13 est déprécié partout.
    """
    return copy.deepcopy(load_json("server_types_mixed.json")["server_types"])
