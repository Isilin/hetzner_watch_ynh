"""Cohérence du paquet YunoHost : manifest, config panel, modèles de configuration, scripts."""

import re
import struct
import sys
from pathlib import Path

import pytest

import hetzner_watch
from hetzner_watch.config import ENV_KEYS

ROOT = Path(__file__).resolve().parent.parent
SETTINGS = {
    "hcloud_token",
    "watch_types",
    "watch_locations",
    "interval",
    "notify_unavailable",
    "notify_cooldown",
    "ntfy_url",
    "ntfy_token",
    "discord_webhook",
    "heartbeat_url",
    "heartbeat_interval",
}
# Variables disponibles au moment de ynh_config_add : réglages de l'app + variables du cœur
KNOWN_VARS = SETTINGS | {"app", "install_dir", "data_dir"}

needs_tomllib = pytest.mark.skipif(sys.version_info < (3, 11), reason="tomllib")


def load_toml(name):
    import tomllib

    with open(ROOT / name, "rb") as f:
        return tomllib.load(f)


def panel_options(panel):
    for panel_value in panel.values():
        if not isinstance(panel_value, dict):
            continue
        for section in panel_value.values():
            if not isinstance(section, dict):
                continue
            for option_id, option in section.items():
                if isinstance(option, dict) and "type" in option:
                    yield option_id, option


def env_template():
    """{KEY: placeholder} de conf/hetzner_watch.env."""
    pairs = {}
    for line in (ROOT / "conf" / "hetzner_watch.env").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            key, _, value = line.partition("=")
            pairs[key] = value
    return pairs


@needs_tomllib
def test_manifest_version_matches_code():
    manifest = load_toml("manifest.toml")
    assert manifest["version"].split("~ynh")[0] == hetzner_watch.__version__
    assert manifest["id"] == "hetzner_watch"


@needs_tomllib
def test_manifest_has_no_web_questions():
    install = load_toml("manifest.toml")["install"]
    assert "domain" not in install and "path" not in install
    assert set(install) <= SETTINGS


@needs_tomllib
def test_config_panel_options_are_settings():
    options = dict(panel_options(load_toml("config_panel.toml")))
    assert set(options) == SETTINGS
    for option_id, option in options.items():
        assert "bind" not in option, f"{option_id} : stocké dans les réglages, .env régénéré par scripts/config"


@needs_tomllib
def test_tag_choices_are_identical_in_manifest_and_panel():
    install = load_toml("manifest.toml")["install"]
    options = dict(panel_options(load_toml("config_panel.toml")))
    for key in ("watch_types", "watch_locations"):
        assert install[key]["choices"] == options[key]["choices"]
    assert set(install["watch_types"]["default"].split(",")) <= set(install["watch_types"]["choices"])


def test_env_template_matches_config_keys():
    template = env_template()
    assert set(template) == set(ENV_KEYS)
    for key, value in template.items():
        if key.lower() in SETTINGS:
            assert value == f"__{key}__", key


def test_every_setting_has_a_default():
    common = (ROOT / "scripts" / "_common.sh").read_text(encoding="utf-8")
    defaults = set(re.findall(r"ynh_app_setting_set_default --key=(\w+)", common))
    read_back = set(re.findall(r"ynh_app_setting_get --key=(\w+)", common))
    assert defaults == SETTINGS
    assert read_back == SETTINGS


def test_secret_setters_exist():
    config = (ROOT / "scripts" / "config").read_text(encoding="utf-8")
    for key in ("hcloud_token", "ntfy_token", "discord_webhook"):
        assert f"set__{key}()" in config


@pytest.mark.parametrize("name", sorted(p.name for p in (ROOT / "conf").iterdir()))
def test_conf_templates_use_known_vars(name):
    text = (ROOT / "conf" / name).read_text(encoding="utf-8")
    used = {m.lower() for m in re.findall(r"__([A-Z0-9_]+?)__", text)}
    assert used <= KNOWN_VARS


def test_install_waits_for_startup_line():
    for script in ("install", "upgrade", "restore"):
        text = (ROOT / "scripts" / script).read_text(encoding="utf-8")
        assert '--wait_until="Surveillance de"' in text, script


def test_logo_is_a_square_png():
    """YunoHost n'accepte que du PNG pour le logo d'une app (yunohost user permission update --logo)."""
    head = (ROOT / "doc" / "logo.png").read_bytes()[:24]
    assert head[:8] == bytes.fromhex("89504e470d0a1a0a")
    width, height = struct.unpack(">II", head[16:24])
    assert width == height >= 256


def test_scripts_use_lf():
    for folder in ("scripts", "conf"):
        for path in (ROOT / folder).iterdir():
            assert b"\r\n" not in path.read_bytes(), f"{folder}/{path.name}"
