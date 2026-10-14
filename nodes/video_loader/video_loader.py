import logging
import os

import folder_paths

from .decode import load_video

logger = logging.getLogger(__name__)


def _input_videos():
    input_dir = folder_paths.get_input_directory()
    files = [f for f in os.listdir(input_dir) if os.path.isfile(os.path.join(input_dir, f))]
    return sorted(folder_paths.filter_files_content_types(files, ["video"]))


class LoadVideo:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video": (_input_videos(), {"video_upload": True}),
                "fps": ("FLOAT", {"default": 24.0, "min": 0.0, "max": 120.0, "step": 0.5,
                                  "tooltip": "Resample to this frame rate (nearest frame by timestamp). "
                                             "0 keeps the source rate."}),
                "start_time": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 1e6, "step": 0.01,
                                         "tooltip": "Seconds to skip from the start of the video."}),
                "max_frames": ("INT", {"default": 0, "min": 0, "max": 100000,
                                       "tooltip": "Frames to load at the output rate. 0 loads to the end."}),
            },
        }

    RETURN_TYPES = ("IMAGE", "AUDIO", "FLOAT", "INT", "BOOLEAN")
    RETURN_NAMES = ("images", "audio", "fps", "frame_count", "has_audio")
    OUTPUT_TOOLTIPS = (
        "Frames at the output rate.",
        "The soundtrack under exactly these frames; silence when the file has no audio track.",
        "Frame rate of the frames.",
        "Number of frames loaded.",
        "False when the file has no audio track and the audio output is silence.",
    )
    FUNCTION = "load"
    CATEGORY = "hermes/video"
    DESCRIPTION = ("Loads a video resampled to a fixed frame rate, with its soundtrack cut to the same span. "
                   "Files without sound give silence instead of failing.")

    def load(self, video, fps, start_time, max_frames):
        path = folder_paths.get_annotated_filepath(video)
        loaded = load_video(path, float(fps), float(start_time), int(max_frames))
        if not loaded.has_audio:
            logger.info("[Hermes] Load Video: %s has no audio track; using silence", video)
        return (loaded.frames, loaded.audio, loaded.fps, loaded.frames.shape[0], loaded.has_audio)

    @classmethod
    def IS_CHANGED(cls, video, **_kwargs):
        return os.path.getmtime(folder_paths.get_annotated_filepath(video))

    @classmethod
    def VALIDATE_INPUTS(cls, video, **_kwargs):
        if not folder_paths.exists_annotated_filepath(video):
            return f"Invalid video file: {video}"
        return True
