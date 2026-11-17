### Réglages

Admin web > Applications > Hetzner Watch > **Configuration**, ou en ligne de commande :

```sh
sudo yunohost app config get __APP__
sudo yunohost app config set __APP__ main.watch.watch_types -v cx43,cx33
sudo yunohost app config set __APP__ main.watch.watch_locations -v fsn1,nbg1,hel1
sudo yunohost app config set __APP__ main.heartbeat.heartbeat_url -v https://hc-ping.com/<uuid>
```

Champs secrets (token Hetzner, token ntfy, webhook Discord) : laisser vide garde la valeur actuelle,
`-` l'efface.

### Commandes

```sh
sudo hetzner_watch --list          # disponibilité de tous les types et locations (* = surveillé)
sudo hetzner_watch --test-notify   # notification de test
sudo journalctl -u __APP__ -f      # journal du service
sudo systemctl restart __APP__
```

### Codes de sortie du service

- arrêt sur **token refusé** (HTTP 401/403) ou configuration invalide : code 2, systemd ne relance pas.
  Une notification « token refusé » est envoyée et le heartbeat reçoit `/fail`. Corriger le token
  dans la configuration : le service redémarre.
- erreurs réseau, 5xx, maintenance Hetzner, quota dépassé (429) : nouvel essai avec délai croissant
  (5 min max, 15 min pour le quota) ; le heartbeat n'est plus pingué tant que ça dure.
