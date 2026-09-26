import av
import numpy as np
import pytest

from hermes_nodes.nodes.common import video


def decode(path):
    with av.open(str(path)) as container:
        return [frame.to_ndarray(format="rgb24") for frame in container.decode(container.streams.video[0])]


@pytest.mark.parametrize("channels", [3, 4, 1])
def test_encode_accepts_rgb_rgba_and_grey_frames(tmp_path, channels):
    # 4-channel IMAGE batches reach Video Preview straight from RGBA loaders; the encoder is rgb24
    frames = np.random.default_rng(0).integers(0, 256, size=(4, 17, 33, channels), dtype=np.uint8)
    out = tmp_path / "clip.mp4"

    video.encode_mp4(frames, 8.0, str(out), codec="libx264")

    decoded = decode(out)
    assert len(decoded) == 4
    # yuv420p needs even sides, so 33x17 frames are trimmed to 32x16
    assert decoded[0].shape == (16, 32, 3)


def test_colour_survives_the_round_trip_without_the_alpha_channel(tmp_path):
    rgba = np.zeros((2, 16, 16, 4), np.uint8)
    rgba[...] = (200, 40, 90, 255)
    out = tmp_path / "solid.mp4"

    video.encode_mp4(rgba, 8.0, str(out), codec="libx264")

    mean_rgb = decode(out)[0].astype(int).mean(axis=(0, 1))
    assert np.abs(mean_rgb - (200, 40, 90)).max() <= 4
