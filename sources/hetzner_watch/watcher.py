"""Boucle de surveillance : détection des transitions, notifications, backoff, arrêt propre."""

from __future__ import annotations

import logging
import random
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Callable

from hetzner_watch.api import AuthError, RateLimited, TransientError
from hetzner_watch.availability import Offer, describe, extract, missing_types
from hetzner_watch.config import Config
from hetzner_watch.heartbeat import Heartbeat
from hetzner_watch.notify import Message, Notifier, dispatch
from hetzner_watch.state import State, load_state, save_state

log = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_CONFIG = 2  # token refusé / configuration invalide : systemd ne relance pas (RestartPreventExitStatus)

MAX_RATE_LIMIT_WAIT = 900.0  # 15 min
MAX_ERROR_WAIT = 300.0  # 5 min

Source = Callable[[], list[dict[str, Any]]]


@dataclass(frozen=True)
class Transitions:
    up: list[str]
    down: list[str]


def diff(previous: Mapping[str, bool], current: Mapping[str, bool]) -> Transitions:
    """Montées : jamais vu ou indisponible -> disponible. Descentes : disponible -> indisponible."""
    up = sorted(k for k, ok in current.items() if ok and previous.get(k) is not True)
    down = sorted(k for k, ok in current.items() if not ok and previous.get(k) is True)
    return Transitions(up=up, down=down)


def available_message(offers: Sequence[Offer]) -> Message:
    if len(offers) == 1:
        title = f"Hetzner : {offers[0].server_type.upper()} disponible"
    else:
        title = f"Hetzner : {len(offers)} serveurs disponibles"
    return Message(
        title=title,
        body="\n".join(describe(o) for o in offers),
        urgent=True,
        tags=("rotating_light",),
    )


def unavailable_message(offers: Sequence[Offer]) -> Message:
    return Message(
        title="Hetzner : plus disponible",
        body="\n".join(f"{o.server_type.upper()} à {o.location}" for o in offers),
        tags=("zzz",),
    )


class Watcher:
    def __init__(
        self,
        cfg: Config,
        source: Source,
        notifiers: Sequence[Notifier],
        heartbeat: Heartbeat | None = None,
        *,
        stop_event: threading.Event | None = None,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.cfg = cfg
        self._source = source
        self._notifiers = notifiers
        self._heartbeat = heartbeat or Heartbeat("", cfg.heartbeat_interval)
        self._stop = stop_event or threading.Event()
        self._clock = clock
        self._sleep = sleep  # délai entre deux essais de notification
        self.state: State = load_state(cfg.state_file)
        self._warned_missing: tuple[str, ...] = ()
        self._first_check = True

    def _notify(self, message: Message) -> None:
        dispatch(self._notifiers, message, sleep=self._sleep)

    def check(self) -> Transitions:
        """Une vérification : lit l'API, notifie les transitions, enregistre l'état."""
        server_types = self._source()
        offers = extract(server_types, self.cfg.watch_types, self.cfg.watch_locations)

        missing = tuple(missing_types(server_types, self.cfg.watch_types))
        if missing and missing != self._warned_missing:
            log.warning("Types introuvables dans l'API (faute de frappe ou type retiré) : %s", ", ".join(missing))
        self._warned_missing = missing
        if not offers:
            log.warning(
                "Aucun couple type/location surveillé (types=%s, locations=%s)",
                ",".join(self.cfg.watch_types),
                ",".join(self.cfg.watch_locations) or "toutes",
            )

        current = {key: offer.available for key, offer in offers.items()}
        transitions = diff(self.state.available, current)
        now = self._clock()

        to_notify = []
        for key in transitions.up:
            last = self.state.last_notified.get(key)
            if last is not None and now - last < self.cfg.notify_cooldown:
                log.info("%s de nouveau disponible, déjà notifié il y a %.0f s : pas d'alerte", key, now - last)
                continue
            to_notify.append(key)
        if to_notify:
            self._notify(available_message([offers[k] for k in to_notify]))
            for key in to_notify:
                self.state.last_notified[key] = now
        if transitions.down:
            log.info("Plus disponible : %s", ", ".join(transitions.down))
            if self.cfg.notify_unavailable:
                self._notify(unavailable_message([offers[k] for k in transitions.down]))

        self.state.available = current
        self.state.last_notified = {k: v for k, v in self.state.last_notified.items() if k in current}
        try:
            save_state(self.cfg.state_file, self.state)
        except OSError as e:
            log.warning("Impossible d'enregistrer l'état (%s) : %s", self.cfg.state_file, e)

        up_now = sorted(k for k, ok in current.items() if ok)
        if self._first_check or transitions.up or transitions.down:
            log.info("Disponibles : %s", ", ".join(up_now) or "aucun")
        else:
            log.debug("Rien de nouveau ; disponibles : %s", ", ".join(up_now) or "aucun")
        self._first_check = False
        return transitions

    def run(self, *, once: bool = False) -> int:
        """Boucle jusqu'à SIGTERM/SIGINT (stop_event). Retourne le code de sortie."""
        log.info(
            "Surveillance de %s sur %s, toutes les %s s",
            ", ".join(self.cfg.watch_types),
            ", ".join(self.cfg.watch_locations) or "toutes les locations",
            self.cfg.interval,
        )
        errors = 0
        rate_limited = 0
        while not self._stop.is_set():
            ok = False
            try:
                self.check()
                ok = True
                errors = rate_limited = 0
                self._heartbeat.success()
                delay = float(self.cfg.interval)
            except AuthError as e:
                log.error("%s. Vérifie HCLOUD_TOKEN (token en lecture seule du projet Hetzner).", e)
                self._notify(
                    Message(
                        title="Hetzner watch : token refusé",
                        body=f"{e}. La surveillance est arrêtée : corrige le token dans la configuration de l'app.",
                        tags=("warning",),
                    )
                )
                self._heartbeat.fail()
                return EXIT_CONFIG
            except RateLimited as e:
                rate_limited += 1
                delay = min(e.retry_after * (1 << min(rate_limited - 1, 10)), MAX_RATE_LIMIT_WAIT)
                log.warning("Quota API dépassé (HTTP 429), nouvel essai dans %.0f s", delay)
            except TransientError as e:
                errors += 1
                delay = self._error_delay(errors)
                log.warning("Vérification impossible (%s), nouvel essai dans %.0f s", e, delay)
            except Exception:
                errors += 1
                delay = self._error_delay(errors)
                log.exception("Erreur inattendue, nouvel essai dans %.0f s", delay)
            if once:
                return EXIT_OK if ok else EXIT_ERROR
            self._stop.wait(delay)
        log.info("Arrêt demandé : fin de la surveillance")
        return EXIT_OK

    def _error_delay(self, errors: int) -> float:
        base = min(float(self.cfg.interval * (1 << min(errors, 10))), MAX_ERROR_WAIT)
        return base + random.uniform(0, base * 0.1)
