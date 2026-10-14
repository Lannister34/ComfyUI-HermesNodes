"""Runs the package against a ComfyUI checkout: the one it lives in (custom_nodes/<this>/) or the
one COMFYUI_ROOT points at.

The HTTP server is stubbed so the route modules import without a running PromptServer, and the
user, temp and output folders point at a scratch directory so nothing touches the real install.
"""

import importlib.util
import os
import sys
import tempfile
import types
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parents[1]
COMFY_ROOT = Path(os.environ.get("COMFYUI_ROOT", PACKAGE_DIR.parents[1]))
PACKAGE_NAME = "hermes_nodes"  # the folder name carries a hyphen; ComfyUI itself imports it by path
_SCRATCH = tempfile.TemporaryDirectory(prefix="hermes-tests-")
SCRATCH = Path(_SCRATCH.name)


def _stub_server():
    class Routes:
        def get(self, *_args, **_kwargs):
            return lambda handler: handler

        post = get

    class Instance:
        routes = Routes()

        def __init__(self):
            self.sent = []

        def send_sync(self, event, data, sid=None):
            self.sent.append((event, data))

    server = types.ModuleType("server")
    server.PromptServer = types.SimpleNamespace(instance=Instance())
    sys.modules["server"] = server


def _import_package():
    if str(COMFY_ROOT) not in sys.path:
        sys.path.insert(0, str(COMFY_ROOT))
    import folder_paths

    folder_paths.set_user_directory(str(SCRATCH / "user"))
    folder_paths.set_temp_directory(str(SCRATCH / "temp"))
    folder_paths.set_output_directory(str(SCRATCH / "output"))
    _stub_server()

    spec = importlib.util.spec_from_file_location(
        PACKAGE_NAME, PACKAGE_DIR / "__init__.py", submodule_search_locations=[str(PACKAGE_DIR)]
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE_NAME] = module
    spec.loader.exec_module(module)
    return module


hermes = _import_package()
