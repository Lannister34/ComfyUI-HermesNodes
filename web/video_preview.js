// Video Preview: built for glancing at a result - autoplay, sound on hover, click to pause.
import { registerVideoNode } from "./common/video_widget.js";

registerVideoNode({
    extensionName: "hermes.VideoPreview",
    nodeName: "HermesVideoPreview",
    widgetName: "$hermes_video_preview",
    widgetType: "preview",
    storageKeys: { meta: "_hermes_video", aspect: "_hermes_aspect", width: "_hermes_width" },
    controls: false,
    hoverUnmute: true,
    clickToPause: true,
});
