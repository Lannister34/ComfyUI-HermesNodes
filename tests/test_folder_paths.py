import sys

import pytest

from hermes_nodes.nodes.random_image_loader.random_image_loader import normalize_folder


def test_folder_paths_are_stripped():
    assert normalize_folder("  /tmp/x ") == "/tmp/x"


@pytest.mark.skipif(sys.platform != "win32", reason="bare drive letters are a Windows path form")
def test_a_bare_drive_letter_is_the_drive_root_not_its_current_directory():
    assert normalize_folder("D:") == "D:\\"
    assert normalize_folder("D:\\Work") == "D:\\Work"
