import json

import pytest

from conftest import Clock, FakeOpener, FakeStop, RecordingNotifier, set_available
from hetzner_watch.api import AuthError, RateLimited, TransientError
from hetzner_watch.config import Config
from hetzner_watch.heartbeat import Heartbeat
from hetzner_watch.state import load_state
from hetzner_watch.watcher import EXIT_CONFIG, EXIT_ERROR, EXIT_OK, Watcher, diff


def make_watcher(tmp_path, source, *, notifier=None, heartbeat=None, stop=None, clock=None, **cfg_kwargs):
    cfg = Config(state_file=tmp_path / "state.json", **cfg_kwargs)
    return Watcher(
        cfg,
        source,
        [notifier if notifier is not None else RecordingNotifier()],
        heartbeat,
        stop_event=stop or FakeStop(),
        clock=clock or Clock(),
        sleep=lambda s: None,
    )


def test_diff():
    t = diff({"a": True, "b": False, "c": True}, {"a": True, "b": True, "c": False, "d": True, "e": False})
    assert t.up == ["b", "d"]  # d jamais vu -> disponible : compte comme une montée
    assert t.down == ["c"]


def test_first_run_notifies_already_available(tmp_path, mixed):
    notifier = RecordingNotifier()
    w = make_watcher(tmp_path, lambda: mixed, notifier=notifier)
    assert w.check().up == ["cax21@hel1", "cx33@fsn1", "cx43@nbg1"]
    [message] = notifier.messages
    assert message.urgent is True
    assert message.title == "Hetzner : 3 serveurs disponibles"
    assert message.body.splitlines() == [
        "CAX21 à hel1 (4 vCPU, 8 Go, arm) : 6,49 € HT/mois",
        "CX33 à fsn1 (4 vCPU, 8 Go, x86) : 5,49 € HT/mois",
        "CX43 à nbg1 (8 vCPU, 16 Go, x86) : 9,49 € HT/mois",
    ]
    assert message.click_url == "https://console.hetzner.cloud/"


def test_first_run_with_nothing_available_is_silent(tmp_path, mixed):
    notifier = RecordingNotifier()
    w = make_watcher(tmp_path, lambda: mixed, notifier=notifier, watch_types=("cax31",))
    w.check()
    assert notifier.messages == []
    assert load_state(tmp_path / "state.json").available == {
        "cax31@fsn1": False,
        "cax31@hel1": False,
        "cax31@nbg1": False,
    }


def test_no_duplicate_notification(tmp_path, mixed):
    notifier = RecordingNotifier()
    w = make_watcher(tmp_path, lambda: mixed, notifier=notifier)
    w.check()
    w.check()
    w.check()
    assert len(notifier.messages) == 1


def test_unavailable_to_available(tmp_path, mixed):
    notifier = RecordingNotifier()
    w = make_watcher(tmp_path, lambda: mixed, notifier=notifier)
    w.check()
    set_available(mixed, "cx43", "fsn1", True)
    assert w.check().up == ["cx43@fsn1"]
    message = notifier.messages[-1]
    assert message.title == "Hetzner : CX43 disponible"
    assert message.body == "CX43 à fsn1 (8 vCPU, 16 Go, x86) : 9,49 € HT/mois"


def test_back_to_unavailable_is_silent_by_default(tmp_path, mixed):
    notifier = RecordingNotifier()
    w = make_watcher(tmp_path, lambda: mixed, notifier=notifier)
    w.check()
    set_available(mixed, "cx43", "nbg1", False)
    assert w.check().down == ["cx43@nbg1"]
    assert len(notifier.messages) == 1


def test_back_to_unavailable_notified_when_enabled(tmp_path, mixed):
    notifier = RecordingNotifier()
    w = make_watcher(tmp_path, lambda: mixed, notifier=notifier, notify_unavailable=True)
    w.check()
    set_available(mixed, "cx43", "nbg1", False)
    w.check()
    message = notifier.messages[-1]
    assert message.title == "Hetzner : plus disponible"
    assert message.body == "CX43 à nbg1"
    assert message.urgent is False


def test_cooldown_suppresses_flapping(tmp_path, mixed):
    notifier = RecordingNotifier()
    clock = Clock()
    w = make_watcher(tmp_path, lambda: mixed, notifier=notifier, clock=clock, notify_cooldown=300)
    w.check()  # 1 message (3 dispos)
    set_available(mixed, "cx43", "nbg1", False)
    clock.now += 30
    w.check()
    set_available(mixed, "cx43", "nbg1", True)
    clock.now += 30
    w.check()  # 60 s après la première alerte : rien
    assert len(notifier.messages) == 1
    set_available(mixed, "cx43", "nbg1", False)
    clock.now += 300
    w.check()
    set_available(mixed, "cx43", "nbg1", True)
    w.check()  # 360 s après : nouvelle alerte
    assert len(notifier.messages) == 2
    assert notifier.messages[-1].title == "Hetzner : CX43 disponible"


def test_restart_with_persisted_state_does_not_renotify(tmp_path, mixed):
    first = RecordingNotifier()
    make_watcher(tmp_path, lambda: mixed, notifier=first).check()
    assert len(first.messages) == 1
    second = RecordingNotifier()
    make_watcher(tmp_path, lambda: mixed, notifier=second).check()
    assert second.messages == []


def test_state_is_saved(tmp_path, mixed):
    clock = Clock(5000.0)
    make_watcher(tmp_path, lambda: mixed, clock=clock, watch_types=("cx43",)).check()
    data = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert data == {
        "version": 1,
        "available": {"cx43@fsn1": False, "cx43@nbg1": True},
        "last_notified": {"cx43@nbg1": 5000.0},
    }


def test_state_write_failure_does_not_crash(tmp_path, mixed, caplog):
    notifier = RecordingNotifier()
    cfg = Config(state_file=tmp_path)  # un dossier : l'écriture échoue
    w = Watcher(cfg, lambda: mixed, [notifier], stop_event=FakeStop(), sleep=lambda s: None)
    w.check()
    assert len(notifier.messages) == 1
    assert "Impossible d'enregistrer l'état" in caplog.text


def test_missing_type_warned_once(tmp_path, mixed, caplog):
    w = make_watcher(tmp_path, lambda: mixed, watch_types=("cx43", "cx42"))
    w.check()
    w.check()
    assert caplog.text.count("Types introuvables") == 1
    assert "cx42" in caplog.text


def test_auth_error_notifies_and_exits_2(tmp_path):
    notifier = RecordingNotifier()
    hb_opener = FakeOpener({})
    heartbeat = Heartbeat("https://hc-ping.com/uuid", 300, opener=hb_opener)

    def source():
        raise AuthError("token refusé (HTTP 401 unauthorized)")

    w = make_watcher(tmp_path, source, notifier=notifier, heartbeat=heartbeat)
    assert w.run() == EXIT_CONFIG
    assert notifier.messages[0].title == "Hetzner watch : token refusé"
    assert [r.full_url for r in hb_opener.requests] == ["https://hc-ping.com/uuid/fail"]


def test_heartbeat_only_on_success_and_throttled(tmp_path, mixed):
    hb_opener = FakeOpener({}, {})
    hb_clock = Clock(0.0)
    heartbeat = Heartbeat("https://hc-ping.com/uuid/", 300, opener=hb_opener, clock=hb_clock)
    results = iter([mixed, TransientError("boom"), mixed, mixed])

    def source():
        item = next(results)
        if isinstance(item, Exception):
            raise item
        return item

    stop = FakeStop(max_waits=4)
    w = make_watcher(tmp_path, source, heartbeat=heartbeat, stop=stop)

    original_wait = stop.wait

    def wait(timeout=None):
        hb_clock.now += 200  # 200 s entre deux vérifications
        return original_wait(timeout)

    stop.wait = wait
    assert w.run() == EXIT_OK
    # ping à t=0 (succès), erreur à t=200, succès à t=400 (ping), succès à t=600 (< 300 s : pas de ping)
    assert [r.full_url for r in hb_opener.requests] == ["https://hc-ping.com/uuid", "https://hc-ping.com/uuid"]


def test_backoff_on_transient_errors_then_reset(tmp_path, mixed):
    outcomes = iter([TransientError("a"), TransientError("b"), TransientError("c"), mixed, TransientError("d")])

    def source():
        item = next(outcomes)
        if isinstance(item, Exception):
            raise item
        return item

    stop = FakeStop(max_waits=5)
    make_watcher(tmp_path, source, stop=stop, interval=30).run()
    delays = stop.waits
    assert 60 <= delays[0] <= 66  # 30 * 2, plus 10 % de jitter au plus
    assert 120 <= delays[1] <= 132
    assert 240 <= delays[2] <= 264
    assert delays[3] == 30  # succès : retour à l'intervalle
    assert 60 <= delays[4] <= 66  # compteur remis à zéro


def test_error_backoff_is_capped(tmp_path):
    def source():
        raise TransientError("panne")

    stop = FakeStop(max_waits=8)
    make_watcher(tmp_path, source, stop=stop, interval=30).run()
    assert max(stop.waits) <= 330
    assert stop.waits[-1] >= 300


def test_rate_limit_backoff(tmp_path, mixed):
    outcomes = iter([RateLimited(60), RateLimited(60), mixed])

    def source():
        item = next(outcomes)
        if isinstance(item, Exception):
            raise item
        return item

    stop = FakeStop(max_waits=3)
    make_watcher(tmp_path, source, stop=stop, interval=30).run()
    assert stop.waits == [60, 120, 30]


def test_unexpected_exception_is_logged_and_retried(tmp_path, mixed, caplog):
    outcomes = iter([KeyError("x"), mixed])

    def source():
        item = next(outcomes)
        if isinstance(item, Exception):
            raise item
        return item

    stop = FakeStop(max_waits=2)
    assert make_watcher(tmp_path, source, stop=stop).run() == EXIT_OK
    assert "Erreur inattendue" in caplog.text


@pytest.mark.parametrize("outcome,expected", [("ok", EXIT_OK), ("error", EXIT_ERROR)])
def test_once_exit_codes(tmp_path, mixed, outcome, expected):
    def source():
        if outcome == "error":
            raise TransientError("panne")
        return mixed

    stop = FakeStop()
    assert make_watcher(tmp_path, source, stop=stop).run(once=True) == expected
    assert stop.waits == []


def test_stop_event_ends_loop(tmp_path, mixed, caplog):
    stop = FakeStop()
    stop.set()
    assert make_watcher(tmp_path, lambda: mixed, stop=stop).run() == EXIT_OK
    assert "Arrêt demandé" in caplog.text


def test_startup_log_line_for_yunohost(tmp_path, mixed, caplog):
    # scripts/install attend cette chaîne dans le journal (ynh_systemctl --wait_until)
    make_watcher(tmp_path, lambda: mixed, stop=FakeStop()).run(once=True)
    assert "Surveillance de cx43, cx33, cax31, cax21 sur toutes les locations, toutes les 30 s" in caplog.text
