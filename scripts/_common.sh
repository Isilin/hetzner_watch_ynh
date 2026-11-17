#!/bin/bash

# Réglages et valeurs par défaut (modifiables ensuite dans le config panel)
_hw_default_settings() {
    ynh_app_setting_set_default --key=hcloud_token --value=""
    ynh_app_setting_set_default --key=watch_types --value="cx43,cx33,cax31,cax21"
    ynh_app_setting_set_default --key=watch_locations --value=""
    ynh_app_setting_set_default --key=interval --value=30
    ynh_app_setting_set_default --key=notify_unavailable --value=0
    ynh_app_setting_set_default --key=notify_cooldown --value=300
    ynh_app_setting_set_default --key=ntfy_url --value=""
    ynh_app_setting_set_default --key=ntfy_token --value=""
    ynh_app_setting_set_default --key=discord_webhook --value=""
    ynh_app_setting_set_default --key=heartbeat_url --value=""
    ynh_app_setting_set_default --key=heartbeat_interval --value=300
}

# Le code est versionné dans ce dépôt (sources/) : pas de téléchargement, on le copie.
_hw_setup_source() {
    ynh_safe_rm "$install_dir/hetzner_watch"
    cp -r "$YNH_APP_BASEDIR/sources/hetzner_watch" "$install_dir/hetzner_watch"
    python3 -m compileall -q "$install_dir/hetzner_watch"
    chmod -R u=rwX,g=rX,o= "$install_dir"
    chown -R "$app:$app" "$install_dir"
}

# hetzner_watch.env (lu par le service) + commande /usr/local/bin/hetzner_watch
# shellcheck disable=SC2034  # les variables locales sont lues par ynh_config_add (__HCLOUD_TOKEN__...)
_hw_add_config() {
    # Relit chaque réglage : dans le config panel, les champs password laissés vides
    # arrivent vides alors que la valeur enregistrée doit être conservée.
    local hcloud_token watch_types watch_locations interval notify_unavailable notify_cooldown \
        ntfy_url ntfy_token discord_webhook heartbeat_url heartbeat_interval
    hcloud_token=$(ynh_app_setting_get --key=hcloud_token)
    watch_types=$(ynh_app_setting_get --key=watch_types)
    watch_locations=$(ynh_app_setting_get --key=watch_locations)
    interval=$(ynh_app_setting_get --key=interval)
    notify_unavailable=$(ynh_app_setting_get --key=notify_unavailable)
    notify_cooldown=$(ynh_app_setting_get --key=notify_cooldown)
    ntfy_url=$(ynh_app_setting_get --key=ntfy_url)
    ntfy_token=$(ynh_app_setting_get --key=ntfy_token)
    discord_webhook=$(ynh_app_setting_get --key=discord_webhook)
    heartbeat_url=$(ynh_app_setting_get --key=heartbeat_url)
    heartbeat_interval=$(ynh_app_setting_get --key=heartbeat_interval)

    ynh_config_add --template="hetzner_watch.env" --destination="$install_dir/hetzner_watch.env"
    chmod 600 "$install_dir/hetzner_watch.env"
    chown "$app:$app" "$install_dir/hetzner_watch.env"

    ynh_config_add --template="hetzner_watch.sh" --destination="/usr/local/bin/$app"
    chmod 755 "/usr/local/bin/$app"
    chown root:root "/usr/local/bin/$app"
}

# Logo dans la liste des apps (option --logo : YunoHost >= 12.1)
_hw_set_logo() {
    local logo="$YNH_APP_BASEDIR/doc/logo.png"
    if [ -f "$logo" ] && yunohost user permission update --help 2>/dev/null | grep -q -- "--logo"; then
        yunohost user permission update "$app.main" --logo "$logo" >/dev/null || true
    fi
}

_hw_service_add() {
    yunohost service add "$app" --description="Surveillance des serveurs Hetzner Cloud (hetzner_watch)"
}
