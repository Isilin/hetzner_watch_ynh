#!/bin/sh
# Commande hetzner_watch - installée par le paquet YunoHost __APP__
#   sudo hetzner_watch --list          disponibilité de tous les types et locations
#   sudo hetzner_watch --test-notify   notification de test
#   sudo hetzner_watch --version
set -eu
[ "$(id -u)" -eq 0 ] || { echo "à lancer avec sudo" >&2; exit 1; }
cd __INSTALL_DIR__
exec runuser -u __APP__ -- /usr/bin/python3 -m hetzner_watch --env-file __INSTALL_DIR__/hetzner_watch.env "$@"
