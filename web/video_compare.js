// Video Compare: the stitched grid clip, with click to pause (the grid has no audio track).
import { registerVideoNode } from "./common/video_widget.js";

registerVideoNode({
    extensionName: "hermes.VideoCompare",
    nodeName: "HermesVideoCompare",
    widgetName: "$hermes_video_preview",
    widgetType: "preview",
    storageKeys: { meta: "_hermes_video", aspect: "_hermes_aspect", width: "_hermes_width" },
    controls: false,
    hoverUnmute: false,
    clickToPause: true,
});
