// Video Player: built for inspecting a result - the browser's own transport bar, so a clip
// can be scrubbed, paused on a frame and muted deliberately.
import { registerVideoNode } from "./common/video_widget.js";

registerVideoNode({
    extensionName: "hermes.VideoPlayer",
    nodeName: "HermesVideoPlayer",
    widgetName: "$hermes_video_player",
    widgetType: "player",
    storageKeys: { meta: "_hermes_player", aspect: "_hermes_player_aspect", width: "_hermes_player_width" },
    controls: true,
    hoverUnmute: false,
    clickToPause: false,
});
