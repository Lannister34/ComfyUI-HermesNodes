/**
 * In-node mp4 player shared by Video Preview, Video Player and Video Compare.
 *
 * The backend returns {videos: [{filename, subfolder, type, format, fps}]} in the node's UI
 * output; this attaches a <video> DOM widget that plays it through ComfyUI's /view route and
 * restores the last clip when a saved workflow is reopened.
 */

import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

function buildVideoUrl(meta) {
    const params = new URLSearchParams({
        filename: meta.filename,
        subfolder: meta.subfolder || "",
        type: meta.type || "temp",
        t: Date.now().toString(),
    });
    return api.apiURL(`/view?${params}`);
}

function fitHeight(node) {
    node.setSize([node.size[0], node.computeSize([node.size[0], node.size[1]])[1]]);
    node?.graph?.setDirtyCanvas(true);
}

function removeWidget(node, widgetName) {
    if (!node.widgets) return;
    for (let i = node.widgets.length - 1; i >= 0; i--) {
        const w = node.widgets[i];
        if (w.name !== widgetName) continue;
        // stop playback and release the stream before dropping the element
        w.element?.querySelectorAll?.("video").forEach((v) => {
            try {
                v.pause();
                v.removeAttribute("src");
                v.load();
            } catch (e) { /* element already detached */ }
        });
        w.element?.remove();
        w.onRemove?.();
        node.widgets.splice(i, 1);
    }
}

/**
 * The canvas normally owns pointer events over a widget so the graph can still be panned and
 * zoomed. A press that lands on the video itself belongs to the video (click to pause, or
 * dragging the native scrub bar) until the gesture ends; everything else goes to the canvas.
 */
function forwardCanvasEvents(parentEl, video) {
    let onVideo = false;
    const release = () => { onVideo = false; };
    const toCanvas = (handler) => (e) => {
        e.preventDefault();
        return handler?.call(app.canvas, e);
    };

    parentEl.addEventListener("contextmenu", toCanvas(app.canvas._mousedown_callback), true);
    parentEl.addEventListener("pointerdown", (e) => {
        if (e.button === 0 && e.target === video) { onVideo = true; return; }
        return toCanvas(app.canvas._mousedown_callback)(e);
    }, true);
    parentEl.addEventListener("pointermove", (e) => {
        if (onVideo) return;
        return toCanvas(app.canvas._mousemove_callback)(e);
    }, true);
    parentEl.addEventListener("pointerup", (e) => {
        if (onVideo) { release(); return; }
        return toCanvas(app.canvas._mouseup_callback)(e);
    }, true);
    parentEl.addEventListener("pointercancel", release, true);
    parentEl.addEventListener("pointerleave", release, true);
    // cancelling "wheel" also suppresses the legacy "mousewheel" event, so one handler is enough
    parentEl.addEventListener("wheel", toCanvas(app.canvas._mousewheel_callback), true);
}

function attachVideo(node, meta, opts) {
    node._hermesVideo = { ...node._hermesVideo, meta };
    removeWidget(node, opts.widgetName);

    const parentEl = document.createElement("div");
    parentEl.style.width = "100%";

    const video = document.createElement("video");
    Object.assign(video, {
        src: buildVideoUrl(meta),
        loop: true,
        autoplay: true,
        muted: true, // browsers only allow autoplay while muted
        playsInline: true,
        controls: opts.controls,
    });
    Object.assign(video.style, { width: "100%", display: "block", borderRadius: "4px" });

    if (opts.hoverUnmute) {
        video.addEventListener("mouseenter", () => { video.muted = false; });
        video.addEventListener("mouseleave", () => { video.muted = true; });
    }
    if (opts.clickToPause) {
        video.style.cursor = "pointer";
        video.addEventListener("click", (e) => {
            e.stopPropagation();
            if (video.paused) video.play();
            else video.pause();
        });
    }

    forwardCanvasEvents(parentEl, video);
    parentEl.appendChild(video);

    const widget = node.addDOMWidget(opts.widgetName, opts.widgetType, parentEl, {
        serialize: false,
        hideOnZoom: false,
    });
    widget.serialize = false; // display only: keep it out of widgets_values
    widget.aspectRatio = node._hermesVideo.aspect || null;
    widget.computeSize = function (width) {
        if (!widget.aspectRatio) return [width, -4]; // collapsed until the clip reports its size
        const height = Math.max(0, (node.size[0] - 20) / widget.aspectRatio + 10);
        widget.computedHeight = height + 10;
        return [width, height];
    };

    video.addEventListener("loadedmetadata", () => {
        widget.aspectRatio = video.videoWidth / video.videoHeight;
        node._hermesVideo.aspect = widget.aspectRatio;
        fitHeight(node);
    });
    video.addEventListener("error", () => {
        parentEl.hidden = true;
        fitHeight(node);
    });
}

/**
 * Register the in-node player for one node type.
 *
 * @param {object} opts
 * @param {string} opts.extensionName frontend extension name, e.g. "hermes.VideoPreview"
 * @param {string} opts.nodeName      backend node id, e.g. "HermesVideoPreview"
 * @param {string} opts.widgetName    DOM widget name
 * @param {string} opts.widgetType    DOM widget type
 * @param {object} opts.storageKeys   {meta, aspect, width}: keys saved in the workflow JSON
 * @param {boolean} opts.controls     show the browser's native transport bar
 * @param {boolean} opts.hoverUnmute  sound only while the cursor is over the video
 * @param {boolean} opts.clickToPause click toggles play/pause
 */
export function registerVideoNode(opts) {
    const keys = opts.storageKeys;

    app.registerExtension({
        name: opts.extensionName,
        async beforeRegisterNodeDef(nodeType, nodeData) {
            if (nodeData.name !== opts.nodeName) return;

            const onExecuted = nodeType.prototype.onExecuted;
            nodeType.prototype.onExecuted = function (message) {
                onExecuted?.apply(this, arguments);
                const videos = message?.videos;
                if (!Array.isArray(videos) || videos.length === 0) return;
                this._hermesVideo = { aspect: null }; // new clip: re-measure on loadedmetadata
                attachVideo(this, videos[0], opts);
            };

            const onSerialize = nodeType.prototype.onSerialize;
            nodeType.prototype.onSerialize = function (o) {
                onSerialize?.apply(this, arguments);
                if (this._hermesVideo?.meta) o[keys.meta] = this._hermesVideo.meta;
                if (this._hermesVideo?.aspect) o[keys.aspect] = this._hermesVideo.aspect;
                o[keys.width] = this.size[0];
            };

            const onConfigure = nodeType.prototype.onConfigure;
            nodeType.prototype.onConfigure = function (o) {
                onConfigure?.apply(this, arguments);
                this._hermesVideo = { aspect: o?.[keys.aspect] || null };
                if (!o?.[keys.meta]) return;
                // widgets are not ready until configure finishes
                setTimeout(() => {
                    attachVideo(this, o[keys.meta], opts);
                    if (o[keys.width]) this.size[0] = o[keys.width];
                    fitHeight(this);
                }, 0);
            };

            const onRemoved = nodeType.prototype.onRemoved;
            nodeType.prototype.onRemoved = function () {
                removeWidget(this, opts.widgetName);
                return onRemoved?.apply(this, arguments);
            };
        },
    });
}
