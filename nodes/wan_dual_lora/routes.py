"""HTTP API used by the WAN Dual LoRA Loader front end (web/wan_dual_lora.js)."""

from aiohttp import web
from server import PromptServer

from .lora_paths import MODEL_TYPES, find_matching_lora, list_loras
from .presets import preset_manager

routes = PromptServer.instance.routes


def _error(message, status=400):
    return web.json_response({"error": message}, status=status)


async def _json_body(request):
    try:
        data = await request.json()
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _invalid_name(name):
    """Names are shown in menus on every connected client: plain text of sane length only."""
    return not isinstance(name, str) or not name.strip() or len(name) > 100 or any(c in name for c in "<>")


def _broadcast_presets():
    PromptServer.instance.send_sync("hermes-presets-update", {"lists": preset_manager.lists})


# ---------- LoRA lists ----------

@routes.get("/hermes/wan_loras/{lora_type}")
async def get_wan_loras(request):
    """Prefixed LoRA names ("I2V/...", "T2V/...") for the HIGH or LOW column."""
    lora_type = request.match_info.get("lora_type", "").lower()
    if lora_type not in MODEL_TYPES:
        return _error("lora_type must be 'high' or 'low'")
    return web.json_response(list_loras(lora_type))


@routes.post("/hermes/wan_loras/find_match")
async def find_match(request):
    """Twin of a LoRA in the opposite column, e.g. x_HIGH -> x_LOW."""
    data = await _json_body(request)
    if data is None:
        return _error("Invalid JSON body")
    lora_name = data.get("lora_name")
    source_type = str(data.get("source_type", "")).lower()
    if not lora_name or source_type not in MODEL_TYPES:
        return _error("lora_name and source_type ('high' or 'low') are required")
    target_type = "low" if source_type == "high" else "high"
    return web.json_response({"match": find_matching_lora(lora_name, target_type)})


# ---------- Presets ----------

@routes.post("/hermes/presets/init")
async def presets_init(request):
    return web.json_response({"lists": preset_manager.lists})


@routes.post("/hermes/presets/load")
async def presets_load(request):
    data = await _json_body(request)
    if data is None or not data.get("preset_name"):
        return _error("preset_name is required")
    preset = preset_manager.get_preset(data.get("list_name", "Default"), data["preset_name"])
    if preset is None:
        return _error("Preset not found", status=404)
    return web.json_response({"preset": preset})


@routes.post("/hermes/presets/save")
async def presets_save(request):
    data = await _json_body(request)
    if data is None or not isinstance(data.get("preset_data"), dict):
        return _error("preset_name and preset_data are required")
    list_name, preset_name = data.get("list_name", "Default"), data.get("preset_name")
    if _invalid_name(list_name) or _invalid_name(preset_name):
        return _error("Preset and list names must be 1-100 characters without < or >")
    try:
        preset_manager.save_preset(list_name, preset_name.strip(), data["preset_data"])
    except OSError as e:
        return _error(f"Could not write presets file: {e}", status=500)
    _broadcast_presets()
    return web.json_response({"success": True})


@routes.post("/hermes/presets/delete")
async def presets_delete(request):
    data = await _json_body(request)
    if data is None or not data.get("preset_name"):
        return _error("preset_name is required")
    try:
        success = preset_manager.delete_preset(data.get("list_name", "Default"), data["preset_name"])
    except OSError as e:
        return _error(f"Could not write presets file: {e}", status=500)
    _broadcast_presets()
    return web.json_response({"success": success})

