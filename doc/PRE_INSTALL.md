Avant l'installation :

1. **Token API Hetzner en lecture seule** : console Hetzner > projet > Sécurité > Tokens API > Générer,
   droits « Lecture ». De préférence dans un projet dédié : le quota de 3600 requêtes/h est partagé
   par tous les outils qui utilisent le même projet.
2. **Topic ntfy** : l'URL complète du topic (ex. `https://ntfy.sh/hetzner-watch-xxxxxxxx`), abonné
   dans l'appli ntfy du téléphone. Sur ntfy.sh, choisir un nom long et aléatoire.
3. Facultatif : un check healthchecks.io (période 5 min, délai de grâce 10 min) dont l'URL de ping
   se renseigne ensuite dans la configuration de l'app.
