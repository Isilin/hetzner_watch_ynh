"""Configuration par variables d'environnement (fichier env sous systemd)."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_TYPES = ("cx43", "cx33", "cax31", "cax21")
MIN_INTERVAL = 10
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")

# Toutes les clés lues : sert aussi au test de cohérence avec le paquet YunoHost
ENV_KEYS = (
    "HCLOUD_TOKEN",
    "WATCH_TYPES",
    "WATCH_LOCATIONS",
    "INTERVAL",
    "NOTIFY_UNAVAILABLE",
    "NOTIFY_COOLDOWN",
    "NTFY_URL",
    "NTFY_TOKEN",
    "DISCORD_WEBHOOK",
    "HEARTBEAT_URL",
    "HEARTBEAT_INTERVAL",
    "STATE_FILE",
    "LOG_LEVEL",
)

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off", ""}


class ConfigError(Exception):
    """Configuration invalide : le programme s'arrête avec le code 2."""


@dataclass(frozen=True)
class Config:
    token: str = field(default="", repr=False)
    watch_types: tuple[str, ...] = DEFAULT_TYPES
    watch_locations: tuple[str, ...] = ()  # vide = toutes
    interval: int = 30
    notify_unavailable: bool = False
    notify_cooldown: int = 300
    ntfy_url: str = field(default="", repr=False)
    ntfy_token: str = field(default="", repr=False)
    discord_webhook: str = field(default="", repr=False)
    heartbeat_url: str = field(default="", repr=False)
    heartbeat_interval: int = 300
    state_file: Path = Path("state.json")
    log_level: str = "INFO"

    def secrets(self) -> list[str]:
        """Valeurs à masquer dans les logs (les URL ntfy, Discord et heartbeat valent un secret)."""
        values = (self.token, self.ntfy_url, self.ntfy_token, self.discord_webhook, self.heartbeat_url)
        return [v for v in values if len(v) >= 4]


def parse_csv(raw: str) -> tuple[str, ...]:
    """'CX43, cx33,,cx43' -> ('cx43', 'cx33') : minuscules, sans vide ni doublon, ordre conservé."""
    out: list[str] = []
    for part in raw.split(","):
        item = part.strip().lower()
        if item and item not in out:
            out.append(item)
    return tuple(out)


def parse_bool(raw: str, key: str) -> bool:
    value = raw.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ConfigError(f"{key} : booléen attendu (1/0, true/false, yes/no), reçu {raw!r}")


def parse_int(raw: str, key: str, minimum: int) -> int:
    try:
        value = int(raw.strip())
    except ValueError:
        raise ConfigError(f"{key} : entier attendu, reçu {raw!r}") from None
    if value < minimum:
        raise ConfigError(f"{key} : minimum {minimum}, reçu {value}")
    return value


def parse_url(raw: str, key: str) -> str:
    value = raw.strip()
    if value and not value.startswith(("https://", "http://")):
        raise ConfigError(f"{key} : URL http(s) attendue")
    return value


def load_config(env: Mapping[str, str]) -> Config:
    """Construit la configuration ; lève ConfigError si une valeur est invalide."""

    defaults = Config()

    def get(key: str) -> str:
        return (env.get(key) or "").strip()

    types = defaults.watch_types
    if "WATCH_TYPES" in env:
        types = parse_csv(get("WATCH_TYPES"))
        if not types:
            raise ConfigError("WATCH_TYPES est vide : indiquer au moins un type (ex. cx43)")

    interval = defaults.interval
    if get("INTERVAL"):
        interval = parse_int(get("INTERVAL"), "INTERVAL", minimum=1)
        if interval < MIN_INTERVAL:
            log.warning("INTERVAL=%s trop court, ramené à %s s", interval, MIN_INTERVAL)
            interval = MIN_INTERVAL

    cooldown = defaults.notify_cooldown
    if get("NOTIFY_COOLDOWN"):
        cooldown = parse_int(get("NOTIFY_COOLDOWN"), "NOTIFY_COOLDOWN", minimum=0)

    heartbeat_interval = defaults.heartbeat_interval
    if get("HEARTBEAT_INTERVAL"):
        heartbeat_interval = parse_int(get("HEARTBEAT_INTERVAL"), "HEARTBEAT_INTERVAL", minimum=10)

    level = (get("LOG_LEVEL") or defaults.log_level).upper()
    if level not in LOG_LEVELS:
        raise ConfigError(f"LOG_LEVEL : une valeur parmi {', '.join(LOG_LEVELS)}")

    return Config(
        token=get("HCLOUD_TOKEN"),
        watch_types=types,
        watch_locations=parse_csv(get("WATCH_LOCATIONS")),
        interval=interval,
        notify_unavailable=parse_bool(get("NOTIFY_UNAVAILABLE"), "NOTIFY_UNAVAILABLE"),
        notify_cooldown=cooldown,
        ntfy_url=parse_url(get("NTFY_URL"), "NTFY_URL"),
        ntfy_token=get("NTFY_TOKEN"),
        discord_webhook=parse_url(get("DISCORD_WEBHOOK"), "DISCORD_WEBHOOK"),
        heartbeat_url=parse_url(get("HEARTBEAT_URL"), "HEARTBEAT_URL"),
        heartbeat_interval=heartbeat_interval,
        state_file=Path(get("STATE_FILE")) if get("STATE_FILE") else defaults.state_file,
        log_level=level,
    )


def read_env_file(path: Path) -> dict[str, str]:
    """Lit un fichier KEY=VALUE (format EnvironmentFile de systemd, sans les cas exotiques)."""
    values: dict[str, str] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, sep, value = line.partition("=")
        if not sep or not key.strip():
            raise ConfigError(f"{path}:{number} : ligne KEY=VALUE attendue")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values
