import math

from PIL import Image

from hermes_nodes.nodes.random_image_loader.random_image_loader import RandomImageLoader


def test_is_changed_tracks_the_folder_contents(tmp_path):
    Image.new("RGB", (4, 4), "red").save(tmp_path / "a.png")
    before = RandomImageLoader.IS_CHANGED(str(tmp_path), 0, False)

    assert RandomImageLoader.IS_CHANGED(str(tmp_path), 0, False) == before
    Image.new("RGB", (4, 4), "blue").save(tmp_path / "b.png")
    assert RandomImageLoader.IS_CHANGED(str(tmp_path), 0, False) != before


def test_is_changed_never_trusts_the_cache_when_an_input_is_linked():
    # ComfyUI evaluates IS_CHANGED before links resolve, so a wired input arrives as None
    assert math.isnan(RandomImageLoader.IS_CHANGED(None, 0, False))
    assert math.isnan(RandomImageLoader.IS_CHANGED("x", 0, None))
