import math
import sys
from fractions import Fraction

import av
import folder_paths
import numpy as np
import pytest
import torch

from hermes_nodes.nodes.video_loader import LoadVideo
from hermes_nodes.nodes.video_loader.timeline import audio_window, frames_from, overlaps, resample_frames

SIZE = 32


def solid_levels(count):
    return [int(10 + i * 230 / max(count - 1, 1)) for i in range(count)]


def write_clip(path, fps, levels, audio_rate=None, tone_hz=440.0):
    with av.open(str(path), mode="w") as container:
        video = container.add_stream("libx264", rate=Fraction(fps).limit_denominator(1000))
        video.width = video.height = SIZE
        video.pix_fmt = "yuv420p"
        video.options = {"crf": "0", "preset": "ultrafast"}
        audio = container.add_stream("aac", rate=audio_rate, layout="stereo") if audio_rate else None
        for level in levels:
            frame = np.full((SIZE, SIZE, 3), level, np.uint8)
            for packet in video.encode(av.VideoFrame.from_ndarray(frame, format="rgb24")):
                container.mux(packet)
        for packet in video.encode():
            container.mux(packet)
        if audio is not None:
            seconds = len(levels) / fps
            t = np.arange(int(seconds * audio_rate)) / audio_rate
            tone = (0.5 * np.sin(2 * np.pi * tone_hz * t)).astype(np.float32)
            samples = np.stack([tone, tone])
            for pos in range(0, samples.shape[1], 1024):
                chunk = av.AudioFrame.from_ndarray(np.ascontiguousarray(samples[:, pos:pos + 1024]),
                                                   format="fltp", layout="stereo")
                chunk.sample_rate = audio_rate
                chunk.pts = pos
                for packet in audio.encode(chunk):
                    container.mux(packet)
            for packet in audio.encode(None):
                container.mux(packet)


def levels_of(images):
    return [round(float(frame.mean()) * 255) for frame in images]


@pytest.fixture
def input_dir(tmp_path):
    previous = folder_paths.get_input_directory()
    folder_paths.set_input_directory(str(tmp_path))
    yield tmp_path
    folder_paths.set_input_directory(previous)


def picked(frames):
    return [frame for _, frame in frames]


def test_30fps_resampled_to_24_picks_the_nearest_source_frame_and_the_earlier_one_on_a_tie():
    source = [(i / 30, i) for i in range(30)]

    got = picked(resample_frames(source, 0.0, 24.0, 1000, 1 / 30))

    assert got == [min(29, math.ceil(i * 30 / 24 - 0.5)) for i in range(24)]


def test_resampling_stops_at_the_frame_limit():
    source = [(i / 30, i) for i in range(300)]

    assert len(picked(resample_frames(source, 0.0, 24.0, 107, 1 / 30))) == 107


def test_upsampling_repeats_frames_until_the_last_frame_has_been_shown():
    source = [(i / 12, i) for i in range(12)]

    got = picked(resample_frames(source, 0.0, 24.0, 1000, 1 / 12))

    assert len(got) == 24
    assert got[:4] == [0, 0, 1, 1] and got[-2:] == [11, 11]


def test_without_a_frame_limit_the_output_ends_with_the_last_source_frame():
    source = [(i / 30, i) for i in range(60)]

    got = picked(resample_frames(source, 0.0, 24.0, sys.maxsize, 1 / 30))

    assert len(got) == 48


def test_start_offset_skips_earlier_frames():
    source = [(i / 24, i) for i in range(48)]

    assert picked(resample_frames(source, 1.0, 24.0, 3, 1 / 24)) == [24, 25, 26]
    assert picked(frames_from(source, 1.0, 3)) == [24, 25, 26]


def test_a_track_that_ends_before_the_window_does_not_overlap_it():
    assert overlaps(100, 100, samples_start=0.0, window_start=0.5, duration=1.0)
    assert not overlaps(100, 100, samples_start=0.0, window_start=2.0, duration=1.0)
    assert not overlaps(0, 100, samples_start=0.0, window_start=0.0, duration=1.0)


def test_audio_window_pads_with_silence_where_the_track_is_shorter_than_the_frames():
    samples = torch.ones(2, 100)

    window = audio_window(samples, 100, samples_start=0.0, window_start=0.5, duration=1.0)

    assert window.shape == (2, 100)
    assert window[:, :50].eq(1).all() and window[:, 50:].eq(0).all()


def test_audio_window_aligns_a_track_that_starts_after_the_video():
    samples = torch.ones(1, 100)

    window = audio_window(samples, 100, samples_start=0.25, window_start=0.0, duration=0.5)

    assert window[:, :25].eq(0).all() and window[:, 25:].eq(1).all()


def test_a_30fps_file_loads_at_24fps_in_order(input_dir):
    levels = solid_levels(30)
    write_clip(input_dir / "clip30.mp4", 30, levels)

    images, _, fps, count, _ = LoadVideo().load("clip30.mp4", 24.0, 0.0, 0)

    assert fps == 24.0 and count == 24 == images.shape[0]
    assert images.shape[1:] == (SIZE, SIZE, 3)
    got = levels_of(images)
    assert got == sorted(got)
    assert abs(got[0] - levels[0]) <= 3 and abs(got[-1] - levels[-1]) <= 3


def test_a_file_without_sound_gives_silence_as_long_as_the_frames(input_dir):
    write_clip(input_dir / "mute.mp4", 24, solid_levels(48))

    _, audio, _, count, has_audio = LoadVideo().load("mute.mp4", 24.0, 0.0, 0)

    assert has_audio is False
    waveform = audio["waveform"]
    assert waveform.abs().max() == 0
    assert waveform.shape[-1] == round(count / 24 * audio["sample_rate"])


def test_the_soundtrack_is_cut_to_exactly_the_loaded_frames(input_dir):
    write_clip(input_dir / "tone.mp4", 30, solid_levels(90), audio_rate=48000)

    _, audio, _, count, has_audio = LoadVideo().load("tone.mp4", 24.0, 0.5, 40)

    assert has_audio is True and count == 40
    assert audio["sample_rate"] == 48000
    assert audio["waveform"].shape == (1, 2, round(40 / 24 * 48000))
    assert audio["waveform"].abs().max() > 0.3


def test_a_missing_file_is_rejected_before_running(input_dir):
    assert LoadVideo.VALIDATE_INPUTS("absent.mp4") is not True
