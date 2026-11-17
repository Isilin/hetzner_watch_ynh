import json
import logging

import pytest

from conftest import FIXTURES, RecordingNotifier
from hetzner_watch import cli
from hetzner_watch.api import AuthError
from hetzner_watch.cli import RedactingFormatter, format_table, load_fixture, main
from hetzner_watch.config import Config

TOKEN = "hc-token-0123456789abcdef"
MIXED = str(FIXTURES / "server_types_mixed.json")


@pytest.fixture
def notifier(monkeypatch):
    recorder = RecordingNotifier("ntfy")
    monkeypatch.setattr(cli, "build_notifiers", lambda cfg: [recorder])
    return recorder


@pytest.fixture
def env(tmp_path):
    return {"STATE_FILE": str(tmp_path / "state.json"), "NTFY_URL": "https://ntfy.sh/topic-secret"}


@pytest.fixture(autouse=True)
def restore_logging():
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


def test_fixture_once_end_to_end(env, notifier, tmp_path):
    assert main(["--fixture", MIXED, "--once"], env) == 0
    assert notifier.messages[0].title == "Hetzner : 3 serveurs disponibles"
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert state["available"]["cx43@nbg1"] is True
    # second passage : pas de doublon
    assert main(["--fixture", MIXED, "--once"], env) == 0
    assert len(notifier.messages) == 1


def test_fixture_does_not_need_token(env, notifier):
    assert "HCLOUD_TOKEN" not in env
    assert main(["--fixture", MIXED, "--once"], env) == 0


def test_missing_token_exits_2(env, notifier, caplog):
    assert main(["--once"], env) == 2
    assert "HCLOUD_TOKEN manquant" in caplog.text


def test_invalid_config_exits_2(env, notifier, caplog):
    env["INTERVAL"] = "souvent"
    assert main(["--once", "--fixture", MIXED], env) == 2
    assert "Configuration invalide" in caplog.text


def test_test_notify(env, notifier):
    assert main(["--test-notify"], env) == 0
    assert notifier.messages[0].title == "Hetzner watch : test"


def test_test_notify_without_channel(tmp_path, caplog):
    assert main(["--test-notify"], {"STATE_FILE": str(tmp_path / "s.json")}) == 2
    assert "Aucun canal" in caplog.text


def test_list(env, notifier, capsys):
    env["WATCH_TYPES"] = "cx43"
    env["WATCH_LOCATIONS"] = "nbg1"
    assert main(["--list", "--fixture", MIXED], env) == 0
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert lines[0].split() == ["type", "location", "dispo", "prix", "HT/mois", "vCPU", "RAM", "arch"]
    assert any(line.startswith("*") and "cx43" in line and "nbg1" in line and "oui" in line for line in lines)
    assert not any("cx43" in line and "hel1" in line for line in lines)  # déprécié
    assert "ccx13" not in out
    assert notifier.messages == []


def test_auth_error_never_logs_token(env, notifier, monkeypatch, caplog, capsys):
    class FakeClient:
        def __init__(self, token):
            assert token == TOKEN

        def fetch_server_types(self):
            raise AuthError("token refusé (HTTP 401 unauthorized : unable to authenticate)")

    monkeypatch.setattr(cli, "HetznerClient", FakeClient)
    env["HCLOUD_TOKEN"] = TOKEN
    env["LOG_LEVEL"] = "DEBUG"
    caplog.set_level(logging.DEBUG)
    assert main(["--once"], env) == 2
    assert main(["--list"], env) == 2
    assert "token refusé" in caplog.text
    captured = capsys.readouterr()
    for text in (caplog.text, captured.err, captured.out):
        assert TOKEN not in text
    assert all(TOKEN not in str(m.body) for m in notifier.messages)


def test_env_file(tmp_path, notifier):
    env_file = tmp_path / "hw.env"
    env_file.write_text(f"STATE_FILE={tmp_path / 'from-file.json'}\nWATCH_TYPES=cx43\n", encoding="utf-8")
    assert main(["--env-file", str(env_file), "--fixture", MIXED, "--once"], {"WATCH_TYPES": "cx33"}) == 0
    state = json.loads((tmp_path / "from-file.json").read_text(encoding="utf-8"))
    assert sorted(state["available"]) == ["cx33@fsn1", "cx33@hel1", "cx33@nbg1"]  # l'environnement prime


def test_redacting_formatter():
    formatter = RedactingFormatter("%(message)s", [TOKEN, "", "https://ntfy.sh/topic-secret"])
    record = logging.LogRecord(
        "x", logging.ERROR, __file__, 1, "échec %s via %s", (TOKEN, "https://ntfy.sh/topic-secret"), None
    )
    assert formatter.format(record) == "échec *** via ***"


def test_journald_format_has_no_timestamp(tmp_path, capsys, notifier):
    env = {"STATE_FILE": str(tmp_path / "s.json"), "JOURNAL_STREAM": "8:1234"}
    main(["--fixture", MIXED, "--once"], env)
    first = capsys.readouterr().err.splitlines()[0]
    assert first.startswith("INFO Surveillance de")


def test_load_fixture_accepts_plain_list(tmp_path):
    path = tmp_path / "list.json"
    path.write_text('[{"name": "cx43"}, 3]', encoding="utf-8")
    assert load_fixture(path) == [{"name": "cx43"}]
    path.write_text('{"nope": 1}', encoding="utf-8")
    with pytest.raises(ValueError):
        load_fixture(path)


def test_format_table_empty():
    assert format_table([], Config()) == "Aucun type de serveur dans la réponse."


def test_version(capsys):
    with pytest.raises(SystemExit) as info:
        main(["--version"], {})
    assert info.value.code == 0
    assert "hetzner_watch 1." in capsys.readouterr().out
