"""
Hermes Nodes - ComfyUI Custom Nodes
WAN Dual LoRA Loader with preset management.
"""

import os
import re
import folder_paths
from aiohttp import web
from server import PromptServer

# Register custom WAN LoRA folder paths for I2V and T2V
models_dir = folder_paths.models_dir

# Define all folder paths (HIGH/LOW specific + shared root folders)
WAN_LORA_PATHS = {
    # HIGH/LOW specific folders
    "i2v_high": os.path.join(models_dir, "loras", "wan", "I2V", "HIGH"),
    "i2v_low": os.path.join(models_dir, "loras", "wan", "I2V", "LOW"),
    "t2v_high": os.path.join(models_dir, "loras", "wan", "T2V", "HIGH"),
    "t2v_low": os.path.join(models_dir, "loras", "wan", "T2V", "LOW"),
    # Shared folders (LoRAs that work with both HIGH and LOW)
    "i2v_shared": os.path.join(models_dir, "loras", "wan", "I2V"),
    "t2v_shared": os.path.join(models_dir, "loras", "wan", "T2V"),
}

# Create directories if they don't exist and register with ComfyUI
for folder_name, folder_path in WAN_LORA_PATHS.items():
    os.makedirs(folder_path, exist_ok=True)
    folder_paths.add_model_folder_path(f"wan_loras_{folder_name}", folder_path)


def normalize_lora_name(name):
    """
    Normalize LoRA name by removing high/low variants for matching.
    Removes: high, _high_, _high, high_, low, _low_, _low, low_ (case insensitive)
    Examples:
        SVI_HIGH.safetensors -> svi
        SVI_LOW.safetensors -> svi
        character_high_v2.safetensors -> character_v2
    """
    # Remove file extension for comparison
    base_name = os.path.splitext(name)[0]
    normalized = base_name.lower()

    # Remove high/low with various separators (order matters - longer patterns first)
    patterns = [
        r'[_\-]high[_\-]',  # _high_ or -high-
        r'[_\-]low[_\-]',   # _low_ or -low-
        r'[_\-]high$',      # _high or -high at end
        r'[_\-]low$',       # _low or -low at end
        r'^high[_\-]',      # high_ or high- at start
        r'^low[_\-]',       # low_ or low- at start
    ]

    for pattern in patterns:
        normalized = re.sub(pattern, '_', normalized)

    # Clean up any double underscores or leading/trailing underscores
    normalized = re.sub(r'_+', '_', normalized).strip('_')
    return normalized


def find_matching_lora(lora_name, source_type, target_type):
    """
    Find a matching LoRA in the target folder based on normalized name.
    source_type: 'high' or 'low' (the type we're searching FROM)
    target_type: 'high' or 'low' (the type we're searching FOR)
    """
    # Extract variant (i2v/t2v) from source
    if lora_name.startswith("I2V/"):
        variant = "i2v"
        actual_name = lora_name[4:]  # Remove "I2V/" prefix
    elif lora_name.startswith("T2V/"):
        variant = "t2v"
        actual_name = lora_name[4:]  # Remove "T2V/" prefix
    else:
        # Try to find in both variants
        variant = None
        actual_name = lora_name

    source_normalized = normalize_lora_name(actual_name)

    # Search in target folders (HIGH/LOW specific first, then shared)
    variants_to_search = [variant] if variant else ["i2v", "t2v"]

    for v in variants_to_search:
        # First try the specific HIGH/LOW folder
        target_folder = f"wan_loras_{v}_{target_type}"
        try:
            target_loras = folder_paths.get_filename_list(target_folder)
            for target_lora in target_loras:
                if normalize_lora_name(target_lora) == source_normalized:
                    prefix = "I2V" if v == "i2v" else "T2V"
                    return f"{prefix}/{target_lora}"
        except Exception:
            pass

        # Then try the shared folder
        shared_folder = f"wan_loras_{v}_shared"
        try:
            shared_loras = folder_paths.get_filename_list(shared_folder)
            for shared_lora in shared_loras:
                # Skip files in HIGH/LOW subfolders
                if shared_lora.startswith(("HIGH/", "LOW/", "HIGH\\", "LOW\\")):
                    continue
                if normalize_lora_name(shared_lora) == source_normalized:
                    prefix = "I2V" if v == "i2v" else "T2V"
                    return f"{prefix}/{shared_lora}"
        except Exception:
            pass

    return None


# ============== LoRA API Routes ==============

@PromptServer.instance.routes.get("/wan_loras/{lora_type}")
async def get_wan_loras(request):
    """Get list of available WAN LoRAs for HIGH or LOW with I2V/T2V prefixes"""
    lora_type = request.match_info.get("lora_type", "").lower()

    if lora_type not in ("high", "low"):
        return web.json_response({"error": "Invalid lora type"}, status=400)

    try:
        result = []

        # Get I2V LoRAs from specific HIGH/LOW folder
        i2v_folder = f"wan_loras_i2v_{lora_type}"
        try:
            i2v_loras = folder_paths.get_filename_list(i2v_folder)
            for lora in i2v_loras:
                result.append(f"I2V/{lora}")
        except Exception:
            pass

        # Get T2V LoRAs from specific HIGH/LOW folder
        t2v_folder = f"wan_loras_t2v_{lora_type}"
        try:
            t2v_loras = folder_paths.get_filename_list(t2v_folder)
            for lora in t2v_loras:
                result.append(f"T2V/{lora}")
        except Exception:
            pass

        # Get shared I2V LoRAs (files directly in I2V folder, not in HIGH/LOW subfolders)
        try:
            i2v_shared_loras = folder_paths.get_filename_list("wan_loras_i2v_shared")
            for lora in i2v_shared_loras:
                # Skip files in HIGH or LOW subfolders
                if not lora.startswith(("HIGH/", "LOW/", "HIGH\\", "LOW\\")):
                    prefixed = f"I2V/{lora}"
                    if prefixed not in result:
                        result.append(prefixed)
        except Exception:
            pass

        # Get shared T2V LoRAs (files directly in T2V folder, not in HIGH/LOW subfolders)
        try:
            t2v_shared_loras = folder_paths.get_filename_list("wan_loras_t2v_shared")
            for lora in t2v_shared_loras:
                # Skip files in HIGH or LOW subfolders
                if not lora.startswith(("HIGH/", "LOW/", "HIGH\\", "LOW\\")):
                    prefixed = f"T2V/{lora}"
                    if prefixed not in result:
                        result.append(prefixed)
        except Exception:
            pass

        return web.json_response(result)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


@PromptServer.instance.routes.post("/wan_loras/find_match")
async def find_matching_lora_route(request):
    """Find matching LoRA in the opposite HIGH/LOW folder"""
    try:
        data = await request.json()
        lora_name = data.get("lora_name")
        source_type = data.get("source_type", "").lower()  # 'high' or 'low'

        if not lora_name or source_type not in ("high", "low"):
            return web.json_response({"error": "Invalid parameters"}, status=400)

        target_type = "low" if source_type == "high" else "high"
        match = find_matching_lora(lora_name, source_type, target_type)

        return web.json_response({"match": match})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


# ============== Preset API Routes ==============

from .nodes.wan_dual_lora.presets import preset_manager

@PromptServer.instance.routes.post("/hermes/presets/init")
async def presets_init(request):
    """Get initial preset data for UI."""
    return web.json_response({
        "lists": preset_manager.get_all_data()
    })

@PromptServer.instance.routes.post("/hermes/presets/save")
async def presets_save(request):
    """Save a preset."""
    try:
        data = await request.json()
        list_name = data.get("list_name", "Default")
        preset_name = data.get("preset_name")
        preset_data = data.get("preset_data")

        if not preset_name or not preset_data:
            return web.json_response({"error": "Missing preset_name or preset_data"}, status=400)

        preset_manager.save_preset(list_name, preset_name, preset_data)

        # Broadcast update to all clients
        PromptServer.instance.send_sync("hermes-presets-update", {
            "lists": preset_manager.get_all_data()
        })

        return web.json_response({"success": True})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

@PromptServer.instance.routes.post("/hermes/presets/load")
async def presets_load(request):
    """Load a preset."""
    try:
        data = await request.json()
        list_name = data.get("list_name", "Default")
        preset_name = data.get("preset_name")

        if not preset_name:
            return web.json_response({"error": "Missing preset_name"}, status=400)

        preset_data = preset_manager.get_preset(list_name, preset_name)
        if preset_data is None:
            return web.json_response({"error": "Preset not found"}, status=404)

        return web.json_response({"preset": preset_data})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

@PromptServer.instance.routes.post("/hermes/presets/delete")
async def presets_delete(request):
    """Delete a preset."""
    try:
        data = await request.json()
        list_name = data.get("list_name", "Default")
        preset_name = data.get("preset_name")

        if not preset_name:
            return web.json_response({"error": "Missing preset_name"}, status=400)

        success = preset_manager.delete_preset(list_name, preset_name)

        # Broadcast update to all clients
        PromptServer.instance.send_sync("hermes-presets-update", {
            "lists": preset_manager.get_all_data()
        })

        return web.json_response({"success": success})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

@PromptServer.instance.routes.post("/hermes/presets/add_list")
async def presets_add_list(request):
    """Add a new preset list."""
    try:
        data = await request.json()
        list_name = data.get("list_name")

        if not list_name:
            return web.json_response({"error": "Missing list_name"}, status=400)

        success = preset_manager.add_list(list_name)

        # Broadcast update
        PromptServer.instance.send_sync("hermes-presets-update", {
            "lists": preset_manager.get_all_data()
        })

        return web.json_response({"success": success})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

@PromptServer.instance.routes.post("/hermes/presets/delete_list")
async def presets_delete_list(request):
    """Delete a preset list."""
    try:
        data = await request.json()
        list_name = data.get("list_name")

        if not list_name:
            return web.json_response({"error": "Missing list_name"}, status=400)

        success = preset_manager.delete_list(list_name)

        # Broadcast update
        PromptServer.instance.send_sync("hermes-presets-update", {
            "lists": preset_manager.get_all_data()
        })

        return web.json_response({"success": success})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


# Import nodes
from .nodes.wan_dual_lora import WANDualLoraLoader

NODE_CLASS_MAPPINGS = {
    "WANDualLoraLoader": WANDualLoraLoader,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "WANDualLoraLoader": "WAN Dual LoRA Loader",
}

WEB_DIRECTORY = "./nodes/wan_dual_lora/web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
