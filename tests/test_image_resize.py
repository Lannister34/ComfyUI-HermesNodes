import pytest

from hermes_nodes.nodes.image_resize.image_resize import ImageResize


@pytest.mark.parametrize("w, h, size, mode, multiple, expected", [
    (744, 720, 720, "smallest", 8, (744, 720)),  # a float ratio once widened this to 752x720
    (1000, 1500, 1500, "largest", 16, (992, 1488)),
    (1920, 1080, 1280, "largest", 16, (1280, 720)),
    (1920, 1080, 720, "smallest", 16, (1280, 720)),
    (1080, 1920, 720, "smallest", 16, (720, 1280)),
    (100, 100, 64, "largest", 16, (64, 64)),
])
def test_target_size(w, h, size, mode, multiple, expected):
    assert ImageResize._target_size(w, h, size, mode, multiple) == expected


@pytest.mark.parametrize("mode", ["smallest", "largest"])
@pytest.mark.parametrize("multiple", [8, 16])
def test_sides_snap_to_the_multiple_and_stay_within_one_multiple_of_the_aspect(mode, multiple):
    for size in (720, 1024):
        for w in range(256, 2049, 8):
            for h in (720, 1080, 1500):
                new_w, new_h = ImageResize._target_size(w, h, size, mode, multiple)
                assert new_w % multiple == 0 and new_h % multiple == 0, (w, h)
                if mode == "smallest":
                    assert min(new_w, new_h) >= size, (w, h)
                else:
                    assert max(new_w, new_h) <= size, (w, h)
                width_leads = (w <= h) if mode == "smallest" else (w >= h)
                exact_follow = new_w * h / w if width_leads else new_h * w / h
                got_follow = new_h if width_leads else new_w
                assert abs(got_follow - exact_follow) < multiple, (w, h)
