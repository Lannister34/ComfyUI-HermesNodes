"""
Folder picker API for the Random Image Loader.

Lists directory names only - never file names or contents. Image previews go through
ComfyUI's own /view route (see save_preview), so no file is served from here.
"""

import os
import string
import sys

from aiohttp import web
from server import PromptServer

from .random_image_loader import normalize_folder


def _roots():
    if sys.platform == "win32":
        return [f"{letter}:\\" for letter in string.ascii_uppercase if os.path.exists(f"{letter}:\\")]
    return ["/"]


@PromptServer.instance.routes.post("/hermes/browse_folder")
async def browse_folder(request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    path = str(data.get("path") or "")
    if not path:
        if sys.platform == "win32":
            return web.json_response({"folders": _roots(), "path": ""})
        path = "/"

    path = normalize_folder(path)
    if not os.path.isdir(path):
        return web.json_response({"error": "Not a directory"}, status=400)

    try:
        folders = sorted(
            (entry.name for entry in os.scandir(path)
             if not entry.name.startswith(".") and entry.is_dir()),
            key=str.lower,
        )
    except OSError:  # permission denied, drive not ready, ...
        folders = []

    return web.json_response({"folders": folders, "path": os.path.abspath(path)})
