from pathlib import Path

import pytest

from hetzner_watch.config import DEFAULT_TYPES, Config, ConfigError, load_config, parse_csv, read_env_file


def test_defaults():
    cfg = load_config({})
    assert cfg == Config()
    assert cfg.watch_types == DEFAULT_TYPES
    assert cfg.watch_locations == ()
    assert cfg.interval == 30
    assert cfg.notify_unavailable is False
    assert cfg.state_file == Path("state.json")


def test_full_config():
    cfg = load_config(
        {
            "HCLOUD_TOKEN": " secret ",
            "WATCH_TYPES": "CX43, cax21,,cx43",
            "WATCH_LOCATIONS": "fsn1,NBG1",
            "INTERVAL": "45",
            "NOTIFY_UNAVAILABLE": "yes",
            "NOTIFY_COOLDOWN": "0",
            "NTFY_URL": "https://ntfy.sh/t",
            "NTFY_TOKEN": "tk",
            "DISCORD_WEBHOOK": "https://discord.com/api/webhooks/x",
            "HEARTBEAT_URL": "https://hc-ping.com/uuid",
            "HEARTBEAT_INTERVAL": "120",
            "STATE_FILE": "/var/lib/hw/state.json",
            "LOG_LEVEL": "debug",
        }
    )
    assert cfg.token == "secret"
    assert cfg.watch_types == ("cx43", "cax21")
    assert cfg.watch_locations == ("fsn1", "nbg1")
    assert cfg.interval == 45
    assert cfg.notify_unavailable is True
    assert cfg.notify_cooldown == 0
    assert cfg.heartbeat_interval == 120
    assert cfg.state_file == Path("/var/lib/hw/state.json")
    assert cfg.log_level == "DEBUG"


def test_interval_floor(caplog):
    assert load_config({"INTERVAL": "3"}).interval == 10
    assert "trop court" in caplog.text


@pytest.mark.parametrize(
    "env",
    [
        {"INTERVAL": "abc"},
        {"INTERVAL": "0"},
        {"NOTIFY_UNAVAILABLE": "peut-être"},
        {"NOTIFY_COOLDOWN": "-1"},
        {"WATCH_TYPES": " , "},
        {"NTFY_URL": "ntfy.sh/topic"},
        {"HEARTBEAT_URL": "file:///etc/passwd"},
        {"LOG_LEVEL": "VERBOSE"},
    ],
)
def test_invalid_values(env):
    with pytest.raises(ConfigError):
        load_config(env)


@pytest.mark.parametrize("raw,expected", [("1", True), ("true", True), ("ON", True), ("0", False), ("", False)])
def test_booleans(raw, expected):
    assert load_config({"NOTIFY_UNAVAILABLE": raw}).notify_unavailable is expected


def test_secrets_not_in_repr():
    cfg = Config(
        token="tok-123456",
        ntfy_url="https://ntfy.sh/secret-topic",
        discord_webhook="https://d/x",
        heartbeat_url="https://hc",
    )
    text = repr(cfg)
    for secret in cfg.secrets():
        assert secret not in text
    assert set(cfg.secrets()) == {"tok-123456", "https://ntfy.sh/secret-topic", "https://d/x", "https://hc"}


def test_parse_csv():
    assert parse_csv(" a, B ,a,, c ") == ("a", "b", "c")


def test_read_env_file(tmp_path):
    path = tmp_path / "hw.env"
    path.write_text(
        "# commentaire\n\nHCLOUD_TOKEN=abc\nexport WATCH_TYPES=\"cx43,cx33\"\nNTFY_URL='https://ntfy.sh/t'\nEMPTY=\n",
        encoding="utf-8",
    )
    assert read_env_file(path) == {
        "HCLOUD_TOKEN": "abc",
        "WATCH_TYPES": "cx43,cx33",
        "NTFY_URL": "https://ntfy.sh/t",
        "EMPTY": "",
    }
    path.write_text("PAS_DE_EGAL\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        read_env_file(path)
