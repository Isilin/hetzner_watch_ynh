"""Ligne de commande : python -m hetzner_watch [--once | --list | --test-notify] [--fixture JSON]."""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import signal
import sys
import threading
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path
from typing import Any

from hetzner_watch import __version__
from hetzner_watch.api import ApiError, AuthError, HetznerClient
from hetzner_watch.availability import format_memory, format_price, iter_offers
from hetzner_watch.config import Config, ConfigError, load_config, read_env_file
from hetzner_watch.heartbeat import Heartbeat
from hetzner_watch.notify import Message, build_notifiers, dispatch
from hetzner_watch.watcher import EXIT_CONFIG, EXIT_ERROR, EXIT_OK, Source, Watcher

log = logging.getLogger("hetzner_watch")

_HANDLER_FLAG = "_hetzner_watch_handler"


class RedactingFormatter(logging.Formatter):
    """Remplace les secrets connus par *** dans tout ce qui est écrit (messages et tracebacks)."""

    def __init__(self, fmt: str, secrets: Iterable[str]) -> None:
        super().__init__(fmt)
        self._secrets = sorted({s for s in secrets if s}, key=len, reverse=True)

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        for secret in self._secrets:
            text = text.replace(secret, "***")
        return text


def setup_logging(level: str, secrets: Iterable[str], journald: bool) -> None:
    """Logs sur stderr ; sans horodatage sous journald, qui horodate déjà."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, _HANDLER_FLAG, False):
            root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stderr)
    fmt = "%(levelname)s %(message)s" if journald else "%(asctime)s %(levelname)s %(message)s"
    handler.setFormatter(RedactingFormatter(fmt, secrets))
    setattr(handler, _HANDLER_FLAG, True)
    root.addHandler(handler)
    root.setLevel(level)


def load_fixture(path: Path) -> list[dict[str, Any]]:
    """Réponse API enregistrée : {"server_types": [...]} ou directement la liste."""
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("server_types") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ValueError(f"{path} : liste server_types attendue")
    return [item for item in items if isinstance(item, dict)]


def format_table(server_types: Iterable[dict[str, Any]], cfg: Config) -> str:
    """Tableau de tous les couples type/location ; * = surveillé par la configuration actuelle."""
    offers = sorted(iter_offers(server_types), key=lambda o: (o.server_type, o.location))
    if not offers:
        return "Aucun type de serveur dans la réponse."
    rows = [["", "type", "location", "dispo", "prix HT/mois", "vCPU", "RAM", "arch"]]
    for o in offers:
        watched = o.server_type in cfg.watch_types and (not cfg.watch_locations or o.location in cfg.watch_locations)
        rows.append(
            [
                "*" if watched else "",
                o.server_type,
                o.location,
                "oui" if o.available else "non",
                format_price(o.price_net).replace(" HT/mois", ""),
                "" if o.cores is None else str(o.cores),
                format_memory(o.memory),
                o.architecture,
            ]
        )
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    lines = ["  ".join(cell.ljust(w) for cell, w in zip(row, widths)).rstrip() for row in rows]
    lines.append("")
    lines.append("* = surveillé par la configuration actuelle")
    return "\n".join(lines)


@contextlib.contextmanager
def stop_on_signals(stop: threading.Event) -> Iterator[None]:
    """SIGTERM/SIGINT -> stop.set() : la boucle s'arrête sans attendre la fin de l'intervalle."""

    def handler(signum: int, frame: Any) -> None:  # pas de log ici (verrous de logging)
        stop.set()

    previous: dict[signal.Signals, Any] = {}
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(ValueError, OSError):  # hors du thread principal
            previous[sig] = signal.signal(sig, handler)
    try:
        yield
    finally:
        for sig, old in previous.items():
            signal.signal(sig, old)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hetzner_watch",
        description="Notifie dès qu'un type de serveur Hetzner Cloud redevient commandable.",
        epilog="Configuration par variables d'environnement (HCLOUD_TOKEN, WATCH_TYPES, NTFY_URL...) : voir README.",
    )
    parser.add_argument("--once", action="store_true", help="une seule vérification puis sortie (0 = OK)")
    parser.add_argument("--list", action="store_true", help="disponibilité de tous les types et locations, puis sortie")
    parser.add_argument("--test-notify", action="store_true", help="notification de test sur chaque canal configuré")
    parser.add_argument("--fixture", type=Path, metavar="JSON", help="lit la réponse API dans un fichier (test)")
    parser.add_argument(
        "--env-file", type=Path, metavar="FICHIER", help="charge un fichier KEY=VALUE (l'environnement est prioritaire)"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: Sequence[str] | None = None, env: dict[str, str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    environ = dict(os.environ if env is None else env)
    journald = "JOURNAL_STREAM" in environ
    setup_logging("INFO", (), journald)

    try:
        if args.env_file:
            for key, value in read_env_file(args.env_file).items():
                environ.setdefault(key, value)
        cfg = load_config(environ)
        setup_logging(cfg.log_level, cfg.secrets(), journald)
        notifiers = build_notifiers(cfg)
    except (ConfigError, OSError) as e:
        log.error("Configuration invalide : %s", e)
        return EXIT_CONFIG

    if args.test_notify:
        if not notifiers:
            log.error("Aucun canal de notification configuré : renseigner NTFY_URL (ou DISCORD_WEBHOOK)")
            return EXIT_CONFIG
        message = Message(
            title="Hetzner watch : test",
            body=f"Les notifications fonctionnent (hetzner-watch {__version__}). "
            f"Types surveillés : {', '.join(cfg.watch_types)}.",
            tags=("white_check_mark",),
        )
        return EXIT_OK if dispatch(notifiers, message) == len(notifiers) else EXIT_ERROR

    source: Source
    if args.fixture:
        fixture: Path = args.fixture

        def source() -> list[dict[str, Any]]:
            return load_fixture(fixture)

    else:
        if not cfg.token:
            log.error(
                "HCLOUD_TOKEN manquant : créer un token API en lecture seule "
                "(console Hetzner > projet > Sécurité > Tokens API)"
            )
            return EXIT_CONFIG
        source = HetznerClient(cfg.token).fetch_server_types

    if args.list:
        try:
            server_types = source()
        except AuthError as e:
            log.error("%s. Vérifie HCLOUD_TOKEN.", e)
            return EXIT_CONFIG
        except (ApiError, OSError, ValueError) as e:
            log.error("Lecture impossible : %s", e)
            return EXIT_ERROR
        print(format_table(server_types, cfg))
        return EXIT_OK

    stop = threading.Event()
    heartbeat = Heartbeat(cfg.heartbeat_url, cfg.heartbeat_interval)
    watcher = Watcher(cfg, source, notifiers, heartbeat, stop_event=stop)
    with stop_on_signals(stop):
        return watcher.run(once=args.once)
