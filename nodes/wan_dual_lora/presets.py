"""
Preset storage for WAN Dual LoRA Loader.
Stores prompt + LoRA configurations as named presets organized into lists,
in <ComfyUI user dir>/hermes_presets/wan_lora_presets.json.
"""

import copy
import json
import logging
import os
import threading

import folder_paths

logger = logging.getLogger(__name__)

DEFAULT_LISTS = ("Default", "I2V", "T2V")


def get_presets_path():
    presets_dir = os.path.join(folder_paths.get_user_directory(), "hermes_presets")
    os.makedirs(presets_dir, exist_ok=True)
    return os.path.join(presets_dir, "wan_lora_presets.json")


def _default_data():
    return {"version": "1.0", "lists": {name: {} for name in DEFAULT_LISTS}}


class PresetManager:
    """Loads presets once and writes the whole file back after every change."""

    def __init__(self):
        self._lock = threading.Lock()
        self.data = self._load()

    def _load(self):
        path = get_presets_path()
        if not os.path.exists(path):
            data = _default_data()
            try:
                self._write(data)
            except OSError:
                pass  # already logged; presets still work in memory
            return data
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            backup = path + ".broken"
            try:
                os.replace(path, backup)  # keep the unreadable file instead of overwriting it on next save
            except OSError:
                backup = "(backup failed)"
            logger.error("[Hermes] Could not read presets from %s (%s); moved it to %s and started fresh",
                         path, e, backup)
            return _default_data()
        if not isinstance(data, dict) or not isinstance(data.get("lists"), dict) or not data["lists"]:
            return _default_data()
        return data

    @staticmethod
    def _write(data):
        """Raises OSError so callers (and the UI) learn that a change was not persisted."""
        path = get_presets_path()
        tmp_path = path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, path)  # atomic: a crash mid-write never truncates the presets
        except OSError as e:
            logger.error("[Hermes] Failed to save presets to %s: %s", path, e)
            raise

    @property
    def lists(self):
        return self.data["lists"]

    def get_preset(self, list_name, preset_name):
        return self.lists.get(list_name, {}).get(preset_name)

    def _commit(self, mutate):
        """Apply `mutate(lists)` to a copy; when it reports a change, persist that copy, then publish it.

        A failed write changes nothing, and a no-op never touches the disk."""
        with self._lock:
            candidate = copy.deepcopy(self.data)
            changed = mutate(candidate["lists"])
            if changed:
                self._write(candidate)
                self.data = candidate
            return changed

    def save_preset(self, list_name, preset_name, preset_data):
        def mutate(lists):
            lists.setdefault(list_name, {})[preset_name] = preset_data
            return True

        self._commit(mutate)

    def delete_preset(self, list_name, preset_name):
        def mutate(lists):
            return lists.get(list_name, {}).pop(preset_name, None) is not None

        return self._commit(mutate)


preset_manager = PresetManager()
