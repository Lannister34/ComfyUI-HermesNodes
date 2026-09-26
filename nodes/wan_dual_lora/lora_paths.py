"""
WAN LoRA folder layout, listing, resolution and HIGH<->LOW matching.

    models/loras/wan/
    ├── I2V/          <- "shared": LoRAs here show up in both HIGH and LOW lists
    │   ├── HIGH/
    │   └── LOW/
    └── T2V/
        ├── HIGH/
        └── LOW/

LoRA names travel between UI and backend as "<VARIANT>/<path inside folder>",
e.g. "I2V/character_high.safetensors".
"""

import os
import re

import folder_paths

VARIANTS = ("I2V", "T2V")
MODEL_TYPES = ("high", "low")
_SUBFOLDER_PREFIXES = ("HIGH/", "LOW/", "HIGH\\", "LOW\\")


def _folder_key(variant, kind):
    """kind: 'high', 'low' or 'shared'."""
    return f"wan_loras_{variant.lower()}_{kind}"


def register_folders():
    """Create the WAN LoRA folders and register them with ComfyUI (idempotent)."""
    wan_root = os.path.join(folder_paths.models_dir, "loras", "wan")
    for variant in VARIANTS:
        paths = {
            "high": os.path.join(wan_root, variant, "HIGH"),
            "low": os.path.join(wan_root, variant, "LOW"),
            "shared": os.path.join(wan_root, variant),
        }
        for kind, path in paths.items():
            os.makedirs(path, exist_ok=True)
            key = _folder_key(variant, kind)
            folder_paths.add_model_folder_path(key, path)
            # a freshly added key gets an empty extension filter (= every file); list model files only
            dirs, extensions = folder_paths.folder_names_and_paths[key]
            if not extensions:
                folder_paths.folder_names_and_paths[key] = (dirs, folder_paths.supported_pt_extensions)


def _files(key):
    try:
        return folder_paths.get_filename_list(key)
    except KeyError:
        return []


def _shared_files(variant):
    """Files directly in the variant folder, excluding its HIGH/ and LOW/ subfolders."""
    return [f for f in _files(_folder_key(variant, "shared")) if not f.startswith(_SUBFOLDER_PREFIXES)]


def _split(lora_name):
    """'I2V/x.safetensors' -> (['I2V'], 'x.safetensors'); unprefixed names search both variants."""
    for variant in VARIANTS:
        if lora_name.startswith(variant + "/"):
            return [variant], lora_name[len(variant) + 1:]
    return list(VARIANTS), lora_name


def list_loras(model_type):
    """All LoRAs for a HIGH or LOW column, as prefixed names: specific folders first, then shared."""
    result = [f"{v}/{f}" for v in VARIANTS for f in _files(_folder_key(v, model_type))]
    seen = set(result)
    for variant in VARIANTS:
        for f in _shared_files(variant):
            name = f"{variant}/{f}"
            if name not in seen:
                seen.add(name)
                result.append(name)
    return result


def resolve_lora_path(lora_name, model_type):
    """Absolute path of a LoRA for the given column, or None. Specific folders win over shared ones."""
    variants, actual_name = _split(lora_name)
    for kind in (model_type, "shared"):
        for variant in variants:
            path = folder_paths.get_full_path(_folder_key(variant, kind), actual_name)
            if path:
                return path
    return None


def normalize_lora_name(name):
    """
    Strip the extension and any high/low marker so HIGH and LOW twins compare equal:
        SVI_HIGH.safetensors -> svi
        character_high_v2.safetensors -> character_v2
    """
    normalized = os.path.splitext(name)[0].lower()
    for pattern in (r"[_\-]high[_\-]", r"[_\-]low[_\-]", r"[_\-]high$", r"[_\-]low$", r"^high[_\-]", r"^low[_\-]"):
        normalized = re.sub(pattern, "_", normalized)
    return re.sub(r"_+", "_", normalized).strip("_")


def find_matching_lora(lora_name, target_type):
    """Find the twin of `lora_name` in the other column (target_type 'high' or 'low'), or None."""
    variants, actual_name = _split(lora_name)
    wanted = normalize_lora_name(actual_name)
    for variant in variants:
        candidates = _files(_folder_key(variant, target_type)) + _shared_files(variant)
        for candidate in candidates:
            if normalize_lora_name(candidate) == wanted:
                return f"{variant}/{candidate}"
    return None
