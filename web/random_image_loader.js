import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// Random Image Loader: folder picker button + preview of the picked image with its name/size.

app.registerExtension({
    name: "hermes.RandomImageLoader",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "HermesRandomImageLoader") return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);

            const folderWidget = this.widgets.find(w => w.name === "folder_path");

            // Hide the raw folder_path text input
            if (folderWidget) {
                folderWidget.draw = function() {};
                folderWidget.computeSize = function() { return [0, -4]; };
            }

            // Add "Choose Folder" button
            const browseBtn = this.addWidget("button", "Choose Folder", "Choose Folder", () => {
                openFolderPicker(this, folderWidget);
            });
            browseBtn.serialize = false;

            // State
            this._imgEl = null;
            this._previewInfo = "";
            this._folderWidget = folderWidget;
        };

        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (data) {
            onExecuted?.apply(this, arguments);

            if (data?.info) {
                this._previewInfo = data.info[0];
            }

            const preview = data?.preview?.[0];
            if (preview) {
                // the backend writes a downscaled copy to temp/, served by ComfyUI's /view
                const params = new URLSearchParams({
                    filename: preview.filename,
                    subfolder: preview.subfolder || "",
                    type: preview.type || "temp",
                    t: Date.now().toString(),
                });
                const url = api.apiURL(`/view?${params}`);

                if (!this._imgEl) {
                    this._imgEl = new Image();
                }
                this._imgEl.onload = () => {
                    this.setSize(this.computeSize());
                    this.setDirtyCanvas(true);
                };
                this._imgEl.src = url;
            }
        };

        // Draw folder path label + preview image + info overlay
        const onDrawForeground = nodeType.prototype.onDrawForeground;
        nodeType.prototype.onDrawForeground = function (ctx) {
            onDrawForeground?.apply(this, arguments);

            // Find bottom of last visible widget
            let yOffset = 0;
            if (this.widgets?.length) {
                for (const w of this.widgets) {
                    if (w.computeSize && w.computeSize()[1] < 0) continue;
                    const bottom = (w.last_y || 0) + (w.computedHeight || 22);
                    if (bottom > yOffset) yOffset = bottom;
                }
            }

            const pad = 10;

            // Draw folder path label
            const folderPath = this._folderWidget?.value;
            if (folderPath) {
                yOffset += 4;
                ctx.save();
                ctx.font = "11px sans-serif";
                ctx.fillStyle = "#aaa";
                // Truncate long paths from the left
                const maxTextW = this.size[0] - pad * 2;
                let displayPath = folderPath;
                let textW = ctx.measureText(displayPath).width;
                if (textW > maxTextW) {
                    while (textW > maxTextW - 10 && displayPath.length > 10) {
                        displayPath = displayPath.substring(1);
                        textW = ctx.measureText("..." + displayPath).width;
                    }
                    displayPath = "..." + displayPath;
                }
                ctx.fillText(displayPath, pad, yOffset + 10);
                ctx.restore();
                yOffset += 16;
            }

            // Draw preview image
            if (this._imgEl && this._imgEl.naturalWidth) {
                yOffset += 4;
                const maxW = this.size[0] - pad * 2;
                const aspect = this._imgEl.naturalHeight / this._imgEl.naturalWidth;
                const drawW = maxW;
                const drawH = drawW * aspect;

                ctx.drawImage(this._imgEl, pad, yOffset, drawW, drawH);

                // Info overlay at bottom of image
                if (this._previewInfo) {
                    ctx.save();
                    ctx.font = "11px sans-serif";
                    const infoW = ctx.measureText(this._previewInfo).width;
                    ctx.fillStyle = "rgba(0,0,0,0.6)";
                    ctx.fillRect(pad, yOffset + drawH - 20, infoW + 12, 20);
                    ctx.fillStyle = "#fff";
                    ctx.fillText(this._previewInfo, pad + 6, yOffset + drawH - 6);
                    ctx.restore();
                }

                yOffset += drawH + 6;
            }

            if (this.size[1] < yOffset + 4) {
                this.size[1] = yOffset + 4;
            }
        };

        // Compute size to accommodate folder label + preview
        const origComputeSize = nodeType.prototype.computeSize;
        nodeType.prototype.computeSize = function () {
            const size = origComputeSize?.apply(this, arguments) || [200, 100];
            if (this._folderWidget?.value) {
                size[1] += 20;
            }
            if (this._imgEl && this._imgEl.naturalWidth) {
                const maxW = Math.max(size[0], 200);
                const aspect = this._imgEl.naturalHeight / this._imgEl.naturalWidth;
                const drawH = (maxW - 20) * aspect;
                size[1] += drawH + 14;
            }
            return size;
        };
    },
});


function textSpan(text) {
    const span = document.createElement("span");
    span.textContent = text;
    return span;
}

function messageDiv(text, color) {
    const div = document.createElement("div");
    div.style.cssText = `padding: 12px; color: ${color}; text-align: center;`;
    div.textContent = text;
    return div;
}

function showMessage(container, text, color) {
    container.replaceChildren(messageDiv(text, color));
}

async function openFolderPicker(node, folderWidget) {
    const currentPath = folderWidget?.value || "";

    const dialog = document.createElement("div");
    dialog.style.cssText = `
        position: fixed; top: 0; left: 0; right: 0; bottom: 0;
        background: rgba(0,0,0,0.7); z-index: 10000;
        display: flex; align-items: center; justify-content: center;
    `;

    const panel = document.createElement("div");
    panel.style.cssText = `
        background: #2a2a2a; border-radius: 8px; padding: 16px;
        min-width: 420px; max-width: 600px; max-height: 70vh;
        display: flex; flex-direction: column; color: #eee; font-family: sans-serif;
    `;

    const header = document.createElement("div");
    header.style.cssText = "display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;";
    const title = textSpan("Select Folder");
    title.style.cssText = "font-size: 14px; font-weight: bold;";
    header.appendChild(title);

    const closeBtn = document.createElement("button");
    closeBtn.textContent = "\u2715";
    closeBtn.style.cssText = "background: none; border: none; color: #eee; font-size: 18px; cursor: pointer;";
    closeBtn.onclick = () => dialog.remove();
    header.appendChild(closeBtn);

    const pathBar = document.createElement("div");
    pathBar.style.cssText = `
        display: flex; align-items: center; gap: 4px; margin-bottom: 8px;
        background: #1a1a1a; padding: 6px 8px; border-radius: 4px;
        font-size: 12px; overflow-x: auto; white-space: nowrap;
    `;

    const listContainer = document.createElement("div");
    listContainer.style.cssText = `
        flex: 1; overflow-y: auto; max-height: 400px;
        border: 1px solid #444; border-radius: 4px;
    `;

    const btnRow = document.createElement("div");
    btnRow.style.cssText = "display: flex; justify-content: flex-end; gap: 8px; margin-top: 12px;";

    const selectBtn = document.createElement("button");
    selectBtn.textContent = "Select This Folder";
    selectBtn.style.cssText = `
        background: #4a7; color: #fff; border: none; padding: 8px 16px;
        border-radius: 4px; cursor: pointer; font-size: 13px;
    `;

    const cancelBtn = document.createElement("button");
    cancelBtn.textContent = "Cancel";
    cancelBtn.style.cssText = `
        background: #555; color: #fff; border: none; padding: 8px 16px;
        border-radius: 4px; cursor: pointer; font-size: 13px;
    `;
    cancelBtn.onclick = () => dialog.remove();

    btnRow.appendChild(cancelBtn);
    btnRow.appendChild(selectBtn);

    panel.appendChild(header);
    panel.appendChild(pathBar);
    panel.appendChild(listContainer);
    panel.appendChild(btnRow);
    dialog.appendChild(panel);

    dialog.addEventListener("click", (e) => {
        if (e.target === dialog) dialog.remove();
    });

    let activePath = currentPath;

    async function loadFolder(path) {
        try {
            const resp = await api.fetchApi("/hermes/browse_folder", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ path }),
            });
            const data = await resp.json();
            if (data.error) {
                showMessage(listContainer, data.error, "#f88");
                return;
            }

            activePath = data.path;

            // Breadcrumb
            pathBar.replaceChildren();
            if (activePath) {
                const rootBtn = document.createElement("span");
                rootBtn.textContent = "\uD83D\uDCBB";
                rootBtn.style.cssText = "cursor:pointer; padding: 2px 4px;";
                rootBtn.onclick = () => loadFolder("");
                pathBar.appendChild(rootBtn);

                const parts = activePath.split(/[/\\]/).filter(Boolean);
                let built = "";
                const sep = activePath.includes("/") ? "/" : "\\";
                for (const part of parts) {
                    built += part + sep;
                    const arrow = document.createElement("span");
                    arrow.textContent = " \u203A ";
                    arrow.style.color = "#888";
                    pathBar.appendChild(arrow);

                    const seg = document.createElement("span");
                    seg.textContent = part;
                    seg.style.cssText = "cursor:pointer; padding: 2px 4px; border-radius: 3px;";
                    seg.onmouseenter = () => seg.style.background = "#444";
                    seg.onmouseleave = () => seg.style.background = "none";
                    const target = built;
                    seg.onclick = () => loadFolder(target);
                    pathBar.appendChild(seg);
                }
            } else {
                pathBar.textContent = "\uD83D\uDCBB Drives";
            }

            // Folder list
            listContainer.replaceChildren();

            if (activePath) {
                const parentItem = document.createElement("div");
                parentItem.style.cssText = `
                    padding: 8px 12px; cursor: pointer; border-bottom: 1px solid #333;
                    display: flex; align-items: center; gap: 8px;
                `;
                parentItem.append(textSpan("\uD83D\uDCC1"), textSpan(".."));
                parentItem.onmouseenter = () => parentItem.style.background = "#333";
                parentItem.onmouseleave = () => parentItem.style.background = "none";
                parentItem.onclick = () => {
                    const parent = activePath.replace(/[/\\][^/\\]*$/, "") || "";
                    loadFolder(parent);
                };
                listContainer.appendChild(parentItem);
            }

            for (const folder of data.folders) {
                const item = document.createElement("div");
                item.style.cssText = `
                    padding: 8px 12px; cursor: pointer; border-bottom: 1px solid #333;
                    display: flex; align-items: center; gap: 8px;
                `;
                item.append(textSpan("\uD83D\uDCC2"), textSpan(folder));
                item.onmouseenter = () => item.style.background = "#333";
                item.onmouseleave = () => item.style.background = "none";
                item.onclick = () => {
                    const newPath = activePath ? activePath.replace(/[/\\]?$/, `/${folder}`) : folder;
                    loadFolder(newPath);
                };
                listContainer.appendChild(item);
            }

            if (data.folders.length === 0 && activePath) {
                listContainer.appendChild(messageDiv("No subfolders", "#888"));
            }

        } catch (err) {
            showMessage(listContainer, err.message, "#f88");
        }
    }

    selectBtn.onclick = () => {
        if (activePath) {
            folderWidget.value = activePath;
            node.setDirtyCanvas(true);
        }
        dialog.remove();
    };

    document.body.appendChild(dialog);
    await loadFolder(currentPath);
}
