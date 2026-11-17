# Hetzner Watch pour YunoHost

Les petits VPS Hetzner Cloud (CX, CAX…) sont souvent en rupture et les remises en stock partent vite.
Hetzner Watch interroge l'API Hetzner toutes les 30 s et envoie une **notification push** dès qu'un type
surveillé redevient commandable dans une location surveillée, avec le prix HT mensuel et un lien vers
la console.

- disponibilité lue dans `GET /v1/server_types` (`locations[].available`) ; l'ancien `GET /v1/datacenters`
  renvoie 410 Gone depuis le 2026-10-01 ;
- alerte uniquement sur transition « indisponible → disponible » (option : l'inverse aussi), état
  persisté : pas de nouvelle alerte au redémarrage ;
- ntfy (priorité urgente, clic vers https://console.hetzner.cloud/) et webhook Discord ;
- heartbeat vers healthchecks.io (ou équivalent) : alerte si la surveillance s'arrête ;
- réglages dans l'admin web YunoHost (config panel), derrière le SSO ;
- **aucune commande de serveur** : un token API en lecture seule suffit.

Dépendances : `python3` (≥ 3.9, déjà présent avec YunoHost), rien d'autre. Environ 15 Mo de RAM.

## Installation

Prérequis : un token API Hetzner **en lecture seule** (console > projet > Sécurité > Tokens API, de
préférence dans un projet dédié : le quota de 3600 requêtes/h est partagé par projet) et l'URL d'un
topic ntfy.

```sh
sudo yunohost app install https://github.com/Isilin/hetzner_watch_ynh
```

YunoHost demande le token, les types à surveiller (défaut `cx43,cx33,cax31,cax21`), les locations
(vide = toutes) et l'URL ntfy. Mise à jour :

```sh
sudo yunohost app upgrade hetzner_watch -u https://github.com/Isilin/hetzner_watch_ynh
```

## Utilisation

```sh
sudo hetzner_watch --test-notify   # notification de test
sudo hetzner_watch --list          # disponibilité de tous les types et locations (* = surveillé)
sudo journalctl -u hetzner_watch -f
```

Exemple d'alerte :

> **Hetzner : CX43 disponible**
> CX43 à nbg1 (8 vCPU, 16 Go, x86) : 9,49 € HT/mois

## Réglages

Admin web > Applications > Hetzner Watch > **Configuration** (le service redémarre à l'enregistrement),
ou `sudo yunohost app config set hetzner_watch <panel.section.option> -v <valeur>`.

| Réglage | Variable | Défaut | Rôle |
|---|---|---|---|
| `watch_types` | `WATCH_TYPES` | `cx43,cx33,cax31,cax21` | types surveillés |
| `watch_locations` | `WATCH_LOCATIONS` | vide = toutes | fsn1, nbg1, hel1, ash, hil, sin |
| `interval` | `INTERVAL` | 30 | secondes entre deux vérifications (minimum 10) |
| `notify_unavailable` | `NOTIFY_UNAVAILABLE` | 0 | notifier aussi le retour à « indisponible » |
| `notify_cooldown` | `NOTIFY_COOLDOWN` | 300 | délai minimum entre deux alertes pour un même couple type/location |
| `ntfy_url` | `NTFY_URL` | | URL complète du topic ntfy |
| `ntfy_token` | `NTFY_TOKEN` | | token ntfy (instance protégée) |
| `discord_webhook` | `DISCORD_WEBHOOK` | | webhook Discord |
| `heartbeat_url` | `HEARTBEAT_URL` | | URL de ping healthchecks (`/fail` ajouté sur erreur fatale) |
| `heartbeat_interval` | `HEARTBEAT_INTERVAL` | 300 | délai minimum entre deux pings |
| `hcloud_token` | `HCLOUD_TOKEN` | | token API Hetzner en lecture seule |
| | `STATE_FILE` | `state.json` | fichier d'état (YunoHost : `/home/yunohost.app/hetzner_watch/state.json`) |
| | `LOG_LEVEL` | `INFO` | DEBUG, INFO, WARNING, ERROR |

Champs secrets du config panel : laisser vide garde la valeur, `-` l'efface.

## Comportement

- **Premier démarrage** (état vide) : ce qui est déjà disponible est notifié.
- **Transitions** : une alerte par passage « indisponible → disponible » ; rien tant que ça reste
  disponible. Les couples type/location dépréciés (`locations[].deprecation` non nul) sont ignorés.
  Un type configuré introuvable dans l'API (faute de frappe, type retiré comme `cx42`) est signalé
  dans le journal.
- **Erreurs** :
  - 401/403 (token refusé) : notification, ping `/fail`, arrêt avec le code 2 (systemd ne relance pas).
  - 403 `maintenance`, 5xx, réseau : nouvel essai, délai doublé à chaque échec (5 min max).
  - 429 (quota) : attente de 60 s puis doublement (15 min max).
- **Arrêt** : SIGTERM interrompt immédiatement l'attente entre deux vérifications.
- Le token n'est jamais écrit dans les logs (les secrets connus sont masqués par `***`).

## Développement

```
sources/hetzner_watch/   code Python (bibliothèque standard uniquement)
  api.py                 client API Hetzner (pagination, erreurs, rate limit)
  availability.py        couples type@location, prix, descriptions
  watcher.py             boucle, transitions, backoff, heartbeat
  notify.py              canaux ntfy et Discord (ajouter un canal = une classe)
  state.py               état JSON à écriture atomique
  config.py              variables d'environnement
  cli.py                 ligne de commande
manifest.toml            paquet YunoHost (format v2, helpers 2.1)
config_panel.toml        formulaire de réglages de l'admin web
scripts/, conf/          scripts d'installation et modèles de configuration
doc/                     description, notes d'admin, logo (tools/make_logo.py)
tests/                   pytest (aucun accès réseau), fixtures JSON de l'API
```

```sh
pip install -e ".[dev]"          # ou : pip install pytest ruff mypy
pytest
ruff check sources tests tools && ruff format --check sources tests tools
mypy
```

Lancer en local sans YunoHost ni token, à partir d'une réponse API enregistrée :

```sh
PYTHONPATH=sources python -m hetzner_watch --fixture tests/fixtures/server_types_mixed.json --list
PYTHONPATH=sources STATE_FILE=/tmp/hw.json python -m hetzner_watch --fixture tests/fixtures/server_types_mixed.json --once
```

Avec `--fixture` sans `--once`, le fichier est relu à chaque vérification : le modifier simule une
remise en stock. `--env-file fichier.env` charge des variables `KEY=VALUE`.

## Licence

MIT.
