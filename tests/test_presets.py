import json

import pytest

from hermes_nodes.nodes.wan_dual_lora import presets


@pytest.fixture
def manager(tmp_path, monkeypatch):
    path = tmp_path / "wan_lora_presets.json"
    monkeypatch.setattr(presets, "get_presets_path", lambda: str(path))
    return presets.PresetManager(), path


def on_disk(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)["lists"]


def test_save_and_delete_round_trip(manager):
    pm, path = manager
    pm.save_preset("Default", "a", {"prompt": "x"})
    assert pm.get_preset("Default", "a") == {"prompt": "x"}
    assert on_disk(path)["Default"] == {"a": {"prompt": "x"}}
    assert pm.delete_preset("Default", "a") is True
    assert pm.delete_preset("Default", "a") is False
    assert on_disk(path)["Default"] == {}


def test_a_failed_write_changes_nothing_in_memory_or_on_disk(manager, monkeypatch):
    pm, path = manager
    pm.save_preset("Default", "kept", {"prompt": "x"})

    def disk_full(data):
        raise OSError("disk full")

    monkeypatch.setattr(presets.PresetManager, "_write", staticmethod(disk_full))

    with pytest.raises(OSError):
        pm.save_preset("Default", "lost", {"prompt": "y"})
    with pytest.raises(OSError):
        pm.delete_preset("Default", "kept")
    assert pm.delete_preset("Default", "absent") is False  # nothing to delete, so the disk is not touched

    assert pm.get_preset("Default", "lost") is None
    assert pm.get_preset("Default", "kept") == {"prompt": "x"}
    assert on_disk(path)["Default"] == {"kept": {"prompt": "x"}}
