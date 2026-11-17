import json

import pytest

from conftest import FailingNotifier, FakeOpener, RecordingNotifier
from hetzner_watch.config import Config, ConfigError
from hetzner_watch.notify import (
    CONSOLE_URL,
    DiscordNotifier,
    Message,
    NtfyNotifier,
    build_notifiers,
    dispatch,
    split_ntfy_url,
)


def payload(request):
    return json.loads(request.data.decode("utf-8"))


def test_split_ntfy_url():
    assert split_ntfy_url("https://ntfy.sh/mon-topic") == ("https://ntfy.sh/", "mon-topic")
    assert split_ntfy_url("https://exemple.org/ntfy/alertes/") == ("https://exemple.org/ntfy/", "alertes")
    with pytest.raises(ValueError):
        split_ntfy_url("https://ntfy.sh/")


def test_ntfy_urgent_message():
    opener = FakeOpener({})
    NtfyNotifier("https://ntfy.sh/hw-secret", "tk_abc", opener=opener).send(
        Message("Hetzner : CX43 disponible", "CX43 à fsn1 : 9,49 € HT/mois", urgent=True, tags=("rotating_light",))
    )
    request = opener.requests[0]
    assert request.full_url == "https://ntfy.sh/"
    assert request.get_method() == "POST"
    assert request.get_header("Authorization") == "Bearer tk_abc"
    assert request.get_header("Content-type") == "application/json"
    assert payload(request) == {
        "topic": "hw-secret",
        "title": "Hetzner : CX43 disponible",
        "message": "CX43 à fsn1 : 9,49 € HT/mois",
        "priority": 5,
        "tags": ["rotating_light"],
        "click": CONSOLE_URL,
    }


def test_ntfy_without_token_or_click():
    opener = FakeOpener({})
    NtfyNotifier("https://ntfy.sh/topic", opener=opener).send(Message("titre", "corps", click_url=None))
    request = opener.requests[0]
    assert request.get_header("Authorization") is None
    body = payload(request)
    assert body["priority"] == 3
    assert "click" not in body and "tags" not in body


def test_discord_payload_is_truncated_and_mentions_disabled():
    opener = FakeOpener({})
    DiscordNotifier("https://discord.com/api/webhooks/1/abc", opener=opener).send(Message("T", "x" * 3000))
    body = payload(opener.requests[0])
    assert len(body["content"]) == 2000
    assert body["content"].startswith("**T**\n")
    assert body["allowed_mentions"] == {"parse": []}


def test_build_notifiers():
    assert build_notifiers(Config()) == []
    notifiers = build_notifiers(
        Config(ntfy_url="https://ntfy.sh/t", discord_webhook="https://discord.com/api/webhooks/x")
    )
    assert [n.name for n in notifiers] == ["ntfy", "discord"]
    with pytest.raises(ConfigError):
        build_notifiers(Config(ntfy_url="https://ntfy.sh/"))


def test_dispatch_isolates_failing_channel(caplog):
    good, bad = RecordingNotifier(), FailingNotifier()
    sleeps = []
    delivered = dispatch([bad, good], Message("t", "b"), sleep=sleeps.append, retry_delays=(1, 2))
    assert delivered == 1
    assert len(good.messages) == 1
    assert bad.calls == 3
    assert sleeps == [1, 2]
    assert "Échec de la notification broken après 3 essais" in caplog.text


def test_dispatch_retries_then_succeeds():
    flaky = FailingNotifier(failures=1)
    assert dispatch([flaky], Message("t", "b"), sleep=lambda s: None) == 1
    assert len(flaky.messages) == 1


def test_dispatch_without_channel_logs_warning(caplog):
    assert dispatch([], Message("t", "b")) == 0
    assert "Aucun canal" in caplog.text
