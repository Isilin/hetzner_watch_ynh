La surveillance tourne. Pour vérifier :

- `sudo hetzner_watch --test-notify` : notification de test sur le téléphone ;
- `sudo hetzner_watch --list` : disponibilité de tous les types et locations, à comparer avec la console Hetzner ;
- `sudo journalctl -u __APP__ -f` : journal du service.

Réglages (types, locations, intervalle, ntfy, Discord, heartbeat, token) : admin web > Applications >
Hetzner Watch > Configuration. Le service redémarre après chaque modification.
