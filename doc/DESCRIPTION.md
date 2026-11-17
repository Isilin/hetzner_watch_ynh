Surveille la disponibilité des types de serveurs Hetzner Cloud (CX, CPX, CAX, CCX) et envoie une
notification push dès qu'un type surveillé redevient commandable dans une location surveillée.

- interroge l'API Hetzner (`GET /v1/server_types`, champ `locations[].available`) toutes les 30 s par défaut ;
- alerte uniquement sur transition « indisponible → disponible », avec le type, la location et le prix HT ;
- notifications ntfy (priorité urgente, clic vers la console Hetzner) et/ou webhook Discord ;
- ping heartbeat (healthchecks.io ou équivalent) pour être prévenu si la surveillance s'arrête ;
- réglages modifiables dans l'admin web (types, locations, intervalle, canaux) ;
- aucune commande de serveur : l'app ne fait que lire l'API (un token en lecture seule suffit).
