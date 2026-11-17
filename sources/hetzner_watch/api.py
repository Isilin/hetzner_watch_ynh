"""Client minimal de l'API Hetzner Cloud : liste paginée des server types.

Disponibilité : champ server_types[].locations[].available (l'ancien
GET /v1/datacenters renvoie 410 Gone depuis le 2026-10-01).
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from email.message import Message
from typing import Any, Callable, Protocol

from hetzner_watch import USER_AGENT

log = logging.getLogger(__name__)

API_BASE = "https://api.hetzner.cloud/v1"
PER_PAGE = 50  # maximum autorisé par l'API
MAX_PAGES = 20  # garde-fou contre une pagination qui boucle
RATE_LIMIT_WAIT = 60.0  # le quota se recharge de 1 requête/s : 60 s suffisent à repartir

JsonObject = dict[str, Any]


class Response(Protocol):
    headers: Message

    def read(self) -> bytes: ...

    def __enter__(self) -> Response: ...

    def __exit__(self, *exc: object) -> bool | None: ...


Opener = Callable[..., Response]


class ApiError(Exception):
    """Erreur d'appel à l'API Hetzner."""


class AuthError(ApiError):
    """Token absent, invalide ou sans droit : inutile de réessayer."""


class TransientError(ApiError):
    """Erreur passagère (réseau, 5xx, maintenance, réponse illisible) : on réessaiera."""


class RateLimited(ApiError):
    """HTTP 429 : quota de requêtes dépassé."""

    def __init__(self, retry_after: float) -> None:
        super().__init__(f"quota API dépassé (HTTP 429), nouvel essai dans {retry_after:.0f} s")
        self.retry_after = retry_after


class HetznerClient:
    def __init__(
        self,
        token: str,
        *,
        base_url: str = API_BASE,
        opener: Opener | None = None,
        timeout: float = 15.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._opener: Opener = opener or urllib.request.urlopen
        self._timeout = timeout
        self._clock = clock

    def __repr__(self) -> str:  # ne jamais exposer le token
        return f"HetznerClient(base_url={self._base_url!r})"

    def fetch_server_types(self) -> list[JsonObject]:
        """Tous les server types, toutes pages confondues."""
        results: list[JsonObject] = []
        page = 1
        for _ in range(MAX_PAGES):
            data = self._get("/server_types", {"page": page, "per_page": PER_PAGE})
            items = data.get("server_types")
            if not isinstance(items, list):
                raise TransientError("réponse inattendue : champ server_types absent")
            results.extend(item for item in items if isinstance(item, dict))
            next_page = ((data.get("meta") or {}).get("pagination") or {}).get("next_page")
            if not next_page:
                return results
            if not isinstance(next_page, int) or next_page <= page:
                raise TransientError(f"pagination incohérente (page {page} -> {next_page!r})")
            page = next_page
        raise TransientError(f"pagination interrompue après {MAX_PAGES} pages")

    def _get(self, path: str, params: dict[str, Any]) -> JsonObject:
        url = f"{self._base_url}{path}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with self._opener(request, timeout=self._timeout) as response:
                self._log_quota(response.headers)
                body = response.read()
        except urllib.error.HTTPError as e:
            raise self._http_error(e) from None
        except (urllib.error.URLError, OSError) as e:  # DNS, connexion refusée, timeout...
            reason = getattr(e, "reason", e)
            raise TransientError(f"erreur réseau : {reason}") from None
        try:
            data = json.loads(body)
        except ValueError:
            raise TransientError("réponse JSON invalide") from None
        if not isinstance(data, dict):
            raise TransientError("réponse JSON inattendue (objet attendu)")
        return data

    def _http_error(self, e: urllib.error.HTTPError) -> ApiError:
        code, message = _error_details(e)
        detail = f"HTTP {e.code}" + (f" {code}" if code else "") + (f" : {message}" if message else "")
        if e.code == 401:
            return AuthError(f"token refusé ({detail})")
        if e.code == 403:
            if code == "maintenance":
                return TransientError(f"API en maintenance ({detail})")
            return AuthError(f"accès refusé ({detail})")
        if e.code == 429:
            return RateLimited(self._retry_after(e.headers))
        return TransientError(f"erreur API ({detail})")

    def _retry_after(self, headers: Message | None) -> float:
        """60 s par défaut ; moins si le quota est entièrement rechargé avant (RateLimit-Reset)."""
        reset = _int_header(headers, "RateLimit-Reset")
        if reset is not None:
            until = reset - self._clock()
            if 0 < until < RATE_LIMIT_WAIT:
                return max(until, 1.0)
        return RATE_LIMIT_WAIT

    @staticmethod
    def _log_quota(headers: Message | None) -> None:
        limit = _int_header(headers, "RateLimit-Limit")
        remaining = _int_header(headers, "RateLimit-Remaining")
        if limit and remaining is not None:
            if remaining < limit * 0.1:
                log.warning("Quota API presque épuisé : %s requêtes restantes sur %s", remaining, limit)
            else:
                log.debug("Quota API : %s/%s", remaining, limit)


def _int_header(headers: Message | None, name: str) -> int | None:
    if headers is None:
        return None
    value = headers.get(name)
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _error_details(e: urllib.error.HTTPError) -> tuple[str, str]:
    """(error.code, error.message) du corps JSON d'erreur Hetzner, ou ('', '')."""
    try:
        payload = json.loads(e.read() or b"{}")
        error = payload.get("error") or {}
        return str(error.get("code") or ""), str(error.get("message") or "")
    except Exception:  # corps absent ou illisible
        return "", ""
