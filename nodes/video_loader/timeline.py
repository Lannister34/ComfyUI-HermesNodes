from collections.abc import Iterable, Iterator
from typing import TypeVar

import torch

T = TypeVar("T")

TIE_TOLERANCE = 1e-6
SILENCE_SAMPLE_RATE = 44100
SILENCE_CHANNELS = 2


def resample_frames(frames: Iterable[tuple[float, T]], first_time: float, fps: float, limit: int,
                    frame_span: float) -> Iterator[tuple[float, T]]:
    emitted = 0
    previous = None
    for time, frame in frames:
        if previous is not None:
            boundary = (previous[0] + time) / 2
            while emitted < limit and first_time + emitted / fps <= boundary + TIE_TOLERANCE:
                yield previous
                emitted += 1
        if emitted >= limit:
            return
        previous = (time, frame)
    if previous is None:
        return
    end_time = previous[0] + frame_span
    while emitted < limit and first_time + emitted / fps < end_time - TIE_TOLERANCE:
        yield previous
        emitted += 1


def frames_from(frames: Iterable[tuple[float, T]], first_time: float, limit: int) -> Iterator[tuple[float, T]]:
    emitted = 0
    for time, frame in frames:
        if emitted >= limit:
            return
        if time + TIE_TOLERANCE < first_time:
            continue
        yield time, frame
        emitted += 1


def overlaps(sample_count: int, sample_rate: int, samples_start: float, window_start: float,
             duration: float) -> bool:
    samples_end = samples_start + sample_count / sample_rate
    return sample_count > 0 and samples_start < window_start + duration and samples_end > window_start


def audio_window(samples: torch.Tensor, sample_rate: int, samples_start: float, window_start: float,
                 duration: float) -> torch.Tensor:
    length = round(duration * sample_rate)
    offset = round((window_start - samples_start) * sample_rate)
    out = torch.zeros(samples.shape[0], length, dtype=torch.float32)
    src_from, dst_from = max(offset, 0), max(-offset, 0)
    count = min(samples.shape[1] - src_from, length - dst_from)
    if count > 0:
        out[:, dst_from:dst_from + count] = samples[:, src_from:src_from + count]
    return out


def silence(duration: float) -> dict:
    waveform = torch.zeros(1, SILENCE_CHANNELS, round(duration * SILENCE_SAMPLE_RATE), dtype=torch.float32)
    return {"waveform": waveform, "sample_rate": SILENCE_SAMPLE_RATE}
