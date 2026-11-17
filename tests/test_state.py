import json
import os

import pytest

from hetzner_watch import state as state_mod
from hetzner_watch.state import State, load_state, save_state


def test_missing_file_gives_empty_state(tmp_path):
    assert load_state(tmp_path / "absent.json") == State()


def test_round_trip_and_directory_creation(tmp_path):
    path = tmp_path / "sub" / "dir" / "state.json"
    st = State(available={"cx43@fsn1": True, "cx33@nbg1": False}, last_notified={"cx43@fsn1": 123.5})
    save_state(path, st)
    assert load_state(path) == st
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 1


def test_no_temporary_file_left(tmp_path):
    path = tmp_path / "state.json"
    save_state(path, State(available={"a@b": True}))
    save_state(path, State(available={"a@b": False}))
    assert sorted(p.name for p in tmp_path.iterdir()) == ["state.json"]


def test_failed_write_keeps_previous_state(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    save_state(path, State(available={"a@b": True}))

    def boom(*args, **kwargs):
        raise OSError("disque plein")

    monkeypatch.setattr(state_mod.os, "replace", boom)
    with pytest.raises(OSError):
        save_state(path, State(available={"a@b": False}))
    monkeypatch.undo()
    assert load_state(path).available == {"a@b": True}
    assert sorted(p.name for p in tmp_path.iterdir()) == ["state.json"]


def test_corrupt_file_is_set_aside(tmp_path, caplog):
    path = tmp_path / "state.json"
    path.write_text("{pas du json", encoding="utf-8")
    assert load_state(path) == State()
    assert (tmp_path / "state.json.corrupt").exists()
    assert not path.exists()
    assert "illisible" in caplog.text


def test_wrong_shape_is_corrupt(tmp_path):
    path = tmp_path / "state.json"
    path.write_text('{"version": 1, "available": [1, 2]}', encoding="utf-8")
    assert load_state(path) == State()


def test_prototype_format_is_migrated(tmp_path):
    path = tmp_path / "state.json"
    path.write_text('{"cx43@fsn1": true, "cx33@nbg1": false}', encoding="utf-8")
    assert load_state(path).available == {"cx43@fsn1": True, "cx33@nbg1": False}


def test_bad_entries_are_dropped():
    st = State.from_json(
        {"version": 1, "available": {"a@b": True, "c@d": "yes"}, "last_notified": {"a@b": 1, "c@d": True, "e@f": "x"}}
    )
    assert st == State(available={"a@b": True}, last_notified={"a@b": 1.0})


@pytest.mark.skipif(os.name == "nt", reason="permissions POSIX")
def test_unreadable_file_gives_empty_state(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{}", encoding="utf-8")
    path.chmod(0)
    try:
        if os.access(path, os.R_OK):  # root lit tout
            pytest.skip("exécuté en root")
        assert load_state(path) == State()
    finally:
        path.chmod(0o600)
