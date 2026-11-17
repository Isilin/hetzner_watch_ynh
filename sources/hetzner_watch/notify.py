"""Canaux de notification. Ajouter un canal (Telegram...) = une classe avec name/send + build_notifiers."""

from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from hetzner_watch import USER_AGENT
from hetzner_watch.config import Config, ConfigError

log = logging.getLogger(__name__)

CONSOLE_URL = "https://console.hetzner.cloud/"
DISCORD_MAX = 2000  # longueur maximale du champ content
RETRY_DELAYS = (2.0, 5.0)  # une alerte de dispo perdue serait le pire des cas : on insiste un peu

Opener = Callable[..., Any]


@dataclass(frozen=True)
class Message:
    title: str
    body: str
    urgent: bool = False
    click_url: str | None = CONSOLE_URL
    tags: tuple[str, ...] = ()


class Notifier(Protocol):
    name: str

    def send(self, message: Message) -> None: ...


def _post_json(opener: Opener, url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float) -> None:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT, **headers},
        method="POST",
    )
    with opener(request, timeout=timeout) as response:
        response.read()


def split_ntfy_url(url: str) -> tuple[str, str]:
    """'https://ntfy.sh/mon-topic' -> ('https://ntfy.sh/', 'mon-topic') pour la publication JSON."""
    parts = urllib.parse.urlsplit(url)
    base_path, _, topic = parts.path.rstrip("/").rpartition("/")
    if not topic:
        raise ValueError("NTFY_URL doit se terminer par le topic, ex. https://ntfy.sh/mon-topic")
    base = urllib.parse.urlunsplit((parts.scheme, parts.netloc, base_path + "/", parts.query, ""))
    return base, topic


class NtfyNotifier:
    """Publication JSON (titres UTF-8 sans souci d'en-têtes), priorité max si urgent."""

    name = "ntfy"

    def __init__(self, url: str, token: str = "", *, opener: Opener | None = None, timeout: float = 10.0) -> None:
        self._base, self._topic = split_ntfy_url(url)
        self._token = token
        self._opener: Opener = opener or urllib.request.urlopen
        self._timeout = timeout

    def send(self, message: Message) -> None:
        payload: dict[str, Any] = {
            "topic": self._topic,
            "title": message.title,
            "message": message.body,
            "priority": 5 if message.urgent else 3,  # 5 = urgent (max), 3 = default
        }
        if message.tags:
            payload["tags"] = list(message.tags)
        if message.click_url:
            payload["click"] = message.click_url
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        _post_json(self._opener, self._base, payload, headers, self._timeout)


class DiscordNotifier:
    name = "discord"

    def __init__(self, webhook: str, *, opener: Opener | None = None, timeout: float = 10.0) -> None:
        self._webhook = webhook
        self._opener: Opener = opener or urllib.request.urlopen
        self._timeout = timeout

    def send(self, message: Message) -> None:
        content = f"**{message.title}**\n{message.body}"
        if message.click_url:
            content += f"\n{message.click_url}"
        if len(content) > DISCORD_MAX:
            content = content[: DISCORD_MAX - 1] + "…"
        payload = {"content": content, "allowed_mentions": {"parse": []}}
        _post_json(self._opener, self._webhook, payload, {}, self._timeout)


def build_notifiers(cfg: Config, *, opener: Opener | None = None) -> list[Notifier]:
    """Canaux configurés (ceux dont l'URL est renseignée)."""
    notifiers: list[Notifier] = []
    if cfg.ntfy_url:
        try:
            notifiers.append(NtfyNotifier(cfg.ntfy_url, cfg.ntfy_token, opener=opener))
        except ValueError as e:
            raise ConfigError(str(e)) from None
    if cfg.discord_webhook:
        notifiers.append(DiscordNotifier(cfg.discord_webhook, opener=opener))
    return notifiers


def dispatch(
    notifiers: Sequence[Notifier],
    message: Message,
    *,
    sleep: Callable[[float], None] = time.sleep,
    retry_delays: Sequence[float] = RETRY_DELAYS,
) -> int:
    """Envoie sur chaque canal (avec nouveaux essais) ; un canal en échec ne bloque pas les autres.

    Retourne le nombre de canaux qui ont accepté le message.
    """
    log.info("Notification : %s | %s", message.title, message.body.replace("\n", " | "))
    if not notifiers:
        log.warning("Aucun canal de notification configuré (NTFY_URL, DISCORD_WEBHOOK)")
        return 0
    delivered = 0
    for notifier in notifiers:
        for attempt, delay in enumerate((*retry_delays, None), start=1):
            try:
                notifier.send(message)
                delivered += 1
                break
            except Exception as e:  # réseau, HTTP 4xx/5xx...
                if delay is None:
                    log.error("Échec de la notification %s après %s essais : %s", notifier.name, attempt, e)
                else:
                    log.warning("Échec de la notification %s (essai %s) : %s", notifier.name, attempt, e)
                    sleep(delay)
    return delivered
