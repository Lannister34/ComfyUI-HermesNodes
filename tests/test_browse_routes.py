import asyncio
import json
import os

import pytest

from hermes_nodes.nodes.random_image_loader import routes

DRIVE = os.path.splitdrive(os.getcwd())[0]  # "D:" on Windows, "" elsewhere


class FakeRequest:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


def browse(path):
    response = asyncio.run(routes.browse_folder(FakeRequest({"path": path})))
    return response.status, json.loads(response.text)


def test_a_missing_path_is_rejected(tmp_path):
    status, body = browse(str(tmp_path / "missing"))
    assert status == 400
    assert "error" in body


def test_a_folder_lists_its_subfolders_only(tmp_path):
    (tmp_path / "b").mkdir()
    (tmp_path / "a").mkdir()
    (tmp_path / "file.png").write_bytes(b"")
    status, body = browse(str(tmp_path))
    assert status == 200
    assert body["folders"] == ["a", "b"]


@pytest.mark.skipif(not DRIVE, reason="bare drive letters are a Windows path form")
def test_a_bare_drive_letter_lists_the_drive_root_not_its_current_directory():
    status, body = browse(DRIVE)
    assert status == 200
    assert body["path"] == DRIVE + "\\"
