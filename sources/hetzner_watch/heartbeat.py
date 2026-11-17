"""Ping de vie vers un service de type healthchecks.io : il alerte quand les pings cessent."""

from __future__ import annotations

import logging
import time
import urllib.request
from typing import Any, Callable

from hetzner_watch import USER_AGENT

log = logging.getLogger(__name__)

Opener = Callable[..., Any]


class Heartbeat:
    def __init__(
        self,
        url: str,
        interval: float,
        *,
        opener: Opener | None = None,
        clock: Callable[[], float] = time.monotonic,
        timeout: float = 10.0,
    ) -> None:
        self._url = url.rstrip("/")
        self._interval = interval
        self._opener: Opener = opener or urllib.request.urlopen
        self._clock = clock
        self._timeout = timeout
        self._last: float | None = None

    @property
    def enabled(self) -> bool:
        return bool(self._url)

    def success(self) -> None:
        """Après une vérification réussie : ping, au plus une fois par intervalle."""
        if not self._url:
            return
        now = self._clock()
        if self._last is not None and now - self._last < self._interval:
            return
        if self._ping(self._url):
            self._last = now

    def fail(self) -> None:
        """Erreur fatale : signale l'échec tout de suite (convention healthchecks : /fail)."""
        if self._url:
            self._ping(self._url + "/fail")

    def _ping(self, url: str) -> bool:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with self._opener(request, timeout=self._timeout) as response:
                response.read()
            return True
        except Exception as e:
            log.warning("Ping heartbeat en échec : %s", e)
            return False
