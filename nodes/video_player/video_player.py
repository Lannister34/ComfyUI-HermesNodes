"""
Video Player - same encoding and saving as Video Preview, different front end.

Preview is built for glancing at a result: it autoplays, unmutes on hover and pauses on
click, with no controls in the way. Player is built for inspecting one: the browser's own
transport bar, so a clip can be scrubbed, paused on a frame and muted deliberately.
"""

from ..video_preview.video_preview import VideoPreview


class VideoPlayer(VideoPreview):
    TEMP_PREFIX = "hermes_video_player"
    DESCRIPTION = "Encodes frames to mp4 and plays them in the node with native player controls for scrubbing."

    @classmethod
    def INPUT_TYPES(cls):
        spec = VideoPreview.INPUT_TYPES()
        spec["required"] = dict(spec["required"])
        base = spec["required"]["filename_prefix"][1]
        spec["required"]["filename_prefix"] = ("STRING", {**base, "default": "VideoPlayer"})
        return spec
