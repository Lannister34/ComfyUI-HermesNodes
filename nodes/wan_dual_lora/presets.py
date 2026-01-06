"""
Preset storage for WAN Dual LoRA Loader.
Stores prompt + LoRA configurations as named presets organized into lists.
"""

import os
import json
import folder_paths

# Storage location
def get_presets_path():
    """Get path to presets JSON file in ComfyUI user directory."""
    user_dir = folder_paths.get_user_directory()
    presets_dir = os.path.join(user_dir, "hermes_presets")
    os.makedirs(presets_dir, exist_ok=True)
    return os.path.join(presets_dir, "wan_lora_presets.json")


def get_default_data():
    """Return default empty data structure."""
    return {
        "version": "1.0",
        "lists": {
            "Default": {},
            "I2V": {},
            "T2V": {}
        }
    }


class PresetManager:
    """Manages preset storage and retrieval."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.data = None
        self.load_data()

    def load_data(self):
        """Load presets from JSON file."""
        path = get_presets_path()
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    self.data = json.load(f)
                # Ensure structure is valid
                if "lists" not in self.data:
                    self.data = get_default_data()
                else:
                    # Ensure default lists exist (migration for existing users)
                    changed = False
                    for list_name in ["Default", "I2V", "T2V"]:
                        if list_name not in self.data["lists"]:
                            self.data["lists"][list_name] = {}
                            changed = True
                    if changed:
                        self.save_data()
            except (json.JSONDecodeError, IOError):
                self.data = get_default_data()
        else:
            self.data = get_default_data()
            self.save_data()

    def save_data(self):
        """Save presets to JSON file."""
        path = get_presets_path()
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
        except IOError as e:
            print(f"[Hermes] Failed to save presets: {e}")

    def get_lists(self):
        """Get all list names."""
        return list(self.data["lists"].keys())

    def get_presets_in_list(self, list_name):
        """Get all preset names in a list."""
        if list_name in self.data["lists"]:
            return list(self.data["lists"][list_name].keys())
        return []

    def get_preset(self, list_name, preset_name):
        """Get a specific preset."""
        if list_name in self.data["lists"]:
            return self.data["lists"][list_name].get(preset_name)
        return None

    def save_preset(self, list_name, preset_name, preset_data):
        """Save a preset to a list."""
        if list_name not in self.data["lists"]:
            self.data["lists"][list_name] = {}
        self.data["lists"][list_name][preset_name] = preset_data
        self.save_data()

    def delete_preset(self, list_name, preset_name):
        """Delete a preset from a list."""
        if list_name in self.data["lists"]:
            if preset_name in self.data["lists"][list_name]:
                del self.data["lists"][list_name][preset_name]
                self.save_data()
                return True
        return False

    def add_list(self, list_name):
        """Add a new list."""
        if list_name not in self.data["lists"]:
            self.data["lists"][list_name] = {}
            self.save_data()
            return True
        return False

    def delete_list(self, list_name):
        """Delete a list (if not the last one)."""
        if list_name in self.data["lists"] and len(self.data["lists"]) > 1:
            del self.data["lists"][list_name]
            self.save_data()
            return True
        return False

    def get_all_data(self):
        """Get all data for UI sync."""
        return self.data["lists"]


# Singleton instance
preset_manager = PresetManager()
