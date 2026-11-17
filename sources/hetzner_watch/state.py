"""État persistant (JSON) : dernière disponibilité connue et dernière notification par couple."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

STATE_VERSION = 1


@dataclass
class State:
    # couple absent = jamais vu (premier démarrage) : différent de False (vu indisponible)
    available: dict[str, bool] = field(default_factory=dict)
    last_notified: dict[str, float] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {"version": STATE_VERSION, "available": self.available, "last_notified": self.last_notified}

    @classmethod
    def from_json(cls, data: Any) -> State:
        if not isinstance(data, dict):
            raise ValueError("objet JSON attendu")
        if "version" not in data:
            # format du prototype : {"cx43@fsn1": true, ...}
            return cls(available={str(k): v for k, v in data.items() if isinstance(v, bool)})
        available = data.get("available") or {}
        last = data.get("last_notified") or {}
        if not isinstance(available, dict) or not isinstance(last, dict):
            raise ValueError("champs available / last_notified invalides")
        return cls(
            available={str(k): v for k, v in available.items() if isinstance(v, bool)},
            last_notified={
                str(k): float(v) for k, v in last.items() if isinstance(v, (int, float)) and not isinstance(v, bool)
            },
        )


def load_state(path: Path) -> State:
    """État enregistré ; état vide si le fichier manque. Un fichier corrompu est mis de côté."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return State()
    except OSError as e:
        log.warning("Lecture de l'état impossible (%s) : %s ; on repart d'un état vide", path, e)
        return State()
    try:
        return State.from_json(json.loads(text))
    except ValueError as e:
        corrupt = path.with_name(path.name + ".corrupt")
        log.warning("État illisible (%s : %s), mis de côté dans %s ; on repart d'un état vide", path, e, corrupt)
        with contextlib.suppress(OSError):
            os.replace(path, corrupt)
        return State()


def save_state(path: Path, state: State) -> None:
    """Écriture atomique : fichier temporaire dans le même dossier, fsync, puis rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state.to_json(), f, indent=2, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
