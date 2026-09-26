/**
 * WAN Dual LoRA Loader - Frontend Widget
 * Creates a two-column dynamic LoRA loader for HIGH and LOW WAN models
 * With preset save/load functionality
 */

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// Widget row height
const ROW_HEIGHT = 26;
const HEADER_HEIGHT = 24;
const BUTTON_HEIGHT = 24;
const PRESET_SECTION_HEIGHT = 94;

// ---- Shared state: one server listener and one fetch per session, not one per node ----

// Loader nodes currently in a graph. Nodes cloned for copy/paste run onNodeCreated but are
// never added, so registering here (onAdded/onRemoved) cannot leak them.
const liveNodes = new Set();

let loraListsPromise = null;
function getLoraLists(force = false) {
    if (force || !loraListsPromise) {
        loraListsPromise = Promise.all([fetchLoraList("high"), fetchLoraList("low")]);
    }
    return loraListsPromise;
}

let presetsPromise = null;
function getPresetLists(force = false) {
    if (force || !presetsPromise) {
        presetsPromise = api.fetchApi("/hermes/presets/init", { method: "POST", body: "{}" })
            .then(resp => (resp.ok ? resp.json() : Promise.reject(new Error(`HTTP ${resp.status}`))))
            .then(data => data.lists)
            .catch(e => {
                console.warn("Failed to fetch presets:", e);
                presetsPromise = null;
                return null;
            });
    }
    return presetsPromise;
}

api.addEventListener("hermes-presets-update", (event) => {
    const lists = event.detail?.lists;
    if (!lists) return;
    presetsPromise = Promise.resolve(lists);
    for (const node of liveNodes) node.applyPresetLists(lists);
});

// Changes made from menus, prompts or async responses happen after the change tracker took its
// mouseup/keydown snapshot; record them explicitly so undo and the "modified" marker see them.
function markWorkflowChanged() {
    const tracker = app.extensionManager?.workflow?.activeWorkflow?.changeTracker;
    (tracker?.captureCanvasState ?? tracker?.checkState)?.call(tracker);
}

// Rows come from saved workflows and presets that may be hand-edited: never trust their shape
function normalizeLora(row) {
    const strength = Number(row?.strength);
    return {
        on: row?.on !== false,
        lora: typeof row?.lora === "string" && row.lora ? row.lora : null,
        strength: Number.isFinite(strength) ? strength : 1.0,
    };
}

async function errorText(resp) {
    try {
        return (await resp.json()).error || `HTTP ${resp.status}`;
    } catch {
        return `HTTP ${resp.status}`;
    }
}

// Fetch LoRA list from server
async function fetchLoraList(type) {
    try {
        const resp = await api.fetchApi(`/hermes/wan_loras/${type}`);
        if (resp.ok) {
            return await resp.json();
        }
    } catch (e) {
        console.warn(`Failed to fetch ${type} LoRAs:`, e);
    }
    return [];
}

// Get display name without I2V/T2V prefix and file extension
function getLoraDisplayName(loraPath) {
    let name = loraPath;
    if (name.startsWith("I2V/")) name = name.slice(4);
    else if (name.startsWith("T2V/")) name = name.slice(4);
    // Remove common extensions
    name = name.replace(/\.(safetensors|ckpt|pt|bin)$/i, "");
    return name;
}

// Show LoRA selection menu with filter input + I2V/T2V grouped
function showLoraMenu(event, loras, callback) {
    // Close any existing picker
    document.querySelectorAll(".hermes-lora-picker").forEach(el => el.remove());

    // Build sorted list with subfolder grouping: {display, value, group, subfolder}
    // Group = I2V/T2V/other, subfolder = top-level folder under group (or "" for root)
    const buildItems = (filtered, group) => {
        const entries = filtered.map(l => {
            const stripped = getLoraDisplayName(l).replace(/\\/g, "/");
            const slashIdx = stripped.indexOf("/");
            const subfolder = slashIdx > -1 ? stripped.slice(0, slashIdx) : "";
            const leaf = slashIdx > -1 ? stripped.slice(slashIdx + 1) : stripped;
            return { display: leaf, full: stripped, value: l, group, subfolder };
        });
        // Sort: items with subfolder first (alphabetically by subfolder, then leaf),
        // then root-level items (without subfolder) alphabetically.
        entries.sort((a, b) => {
            const aHas = a.subfolder ? 0 : 1;
            const bHas = b.subfolder ? 0 : 1;
            if (aHas !== bHas) return aHas - bHas;
            const aKey = (a.subfolder + "/" + a.display).toLowerCase();
            const bKey = (b.subfolder + "/" + b.display).toLowerCase();
            return aKey.localeCompare(bKey);
        });
        return entries;
    };

    const items = [{ display: "None", full: "None", value: null, group: null, subfolder: "" }];
    if (loras && loras.length > 0) {
        const i2v = loras.filter(l => l.startsWith("I2V/"));
        const t2v = loras.filter(l => l.startsWith("T2V/"));
        const other = loras.filter(l => !l.startsWith("I2V/") && !l.startsWith("T2V/"));
        items.push(...buildItems(i2v, "I2V"));
        items.push(...buildItems(t2v, "T2V"));
        items.push(...buildItems(other, null));
    }

    // Root overlay (captures outside clicks)
    const overlay = document.createElement("div");
    overlay.className = "hermes-lora-picker";
    overlay.style.cssText = `
        position: fixed; inset: 0; z-index: 10000;
        background: transparent;
    `;

    // Picker panel
    const panel = document.createElement("div");
    panel.style.cssText = `
        position: absolute; min-width: 280px; max-width: 480px;
        background: #1f1f1f; border: 1px solid #555; border-radius: 4px;
        box-shadow: 0 6px 24px rgba(0,0,0,0.5); overflow: hidden;
        display: flex; flex-direction: column;
        font-family: sans-serif; font-size: 13px; color: #ddd;
    `;
    // Position at click point, clamped to viewport
    const maxH = Math.min(500, window.innerHeight - 40);
    let x = event.clientX;
    let y = event.clientY;
    if (x + 300 > window.innerWidth) x = window.innerWidth - 310;
    if (y + maxH > window.innerHeight) y = window.innerHeight - maxH - 10;
    panel.style.left = `${Math.max(10, x)}px`;
    panel.style.top = `${Math.max(10, y)}px`;
    panel.style.maxHeight = `${maxH}px`;

    // Filter input
    const input = document.createElement("input");
    input.type = "text";
    input.placeholder = "Filter list...";
    input.style.cssText = `
        width: 100%; padding: 8px 10px; box-sizing: border-box;
        background: #2a2a2a; color: #fff; border: none;
        border-bottom: 1px solid #444; outline: none; font-size: 13px;
    `;
    panel.appendChild(input);

    // Scrollable list
    const list = document.createElement("div");
    list.style.cssText = `
        overflow-y: auto; flex: 1 1 auto; min-height: 0;
    `;
    panel.appendChild(list);

    let selectedIdx = 0;
    let visibleItems = [];

    const close = () => overlay.remove();

    const choose = (value) => {
        close();
        callback(value);
    };

    const render = (filter) => {
        list.innerHTML = "";
        const f = (filter || "").toLowerCase().trim();
        let lastGroup = undefined;
        let lastSubfolder = undefined;
        visibleItems = [];
        for (const item of items) {
            const hay = `${item.group || ""} ${item.subfolder || ""} ${item.full} ${item.value || ""}`.toLowerCase();
            if (f && !hay.includes(f)) continue;

            // Group header (I2V / T2V)
            if (item.group !== lastGroup && item.group) {
                const header = document.createElement("div");
                header.textContent = `── ${item.group} ──`;
                header.style.cssText = "padding: 4px 10px; color: #888; font-size: 11px; background:#262626;";
                list.appendChild(header);
                lastGroup = item.group;
                lastSubfolder = undefined;
            } else if (!item.group) {
                lastGroup = undefined;
                lastSubfolder = undefined;
            }

            // Subfolder sub-header (only when grouped under I2V/T2V)
            if (item.group && item.subfolder && item.subfolder !== lastSubfolder) {
                const sub = document.createElement("div");
                sub.textContent = `📁 ${item.subfolder}`;
                sub.style.cssText = "padding: 3px 10px 3px 18px; color: #aaa; font-size: 11px; background:#222;";
                list.appendChild(sub);
                lastSubfolder = item.subfolder;
            } else if (item.group && !item.subfolder) {
                lastSubfolder = "";
            }

            const row = document.createElement("div");
            row.textContent = item.display;
            row.title = item.value || "None";
            row.dataset.idx = visibleItems.length;
            const pad = item.subfolder ? "6px 12px 6px 28px" : "6px 12px";
            row.style.cssText = `padding: ${pad}; cursor: pointer; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;`;
            row.addEventListener("mouseenter", () => {
                selectedIdx = parseInt(row.dataset.idx);
                updateHighlight();
            });
            row.addEventListener("click", () => choose(item.value));
            list.appendChild(row);
            visibleItems.push({ item, el: row });
        }
        if (visibleItems.length === 0) {
            const empty = document.createElement("div");
            empty.textContent = "(no matches)";
            empty.style.cssText = "padding: 10px; color: #888; font-style: italic;";
            list.appendChild(empty);
        }
        selectedIdx = Math.min(selectedIdx, Math.max(0, visibleItems.length - 1));
        updateHighlight();
    };

    const updateHighlight = () => {
        visibleItems.forEach((vi, i) => {
            vi.el.style.background = i === selectedIdx ? "#3a5a8a" : "transparent";
        });
        if (visibleItems[selectedIdx]) {
            visibleItems[selectedIdx].el.scrollIntoView({ block: "nearest" });
        }
    };

    input.addEventListener("input", () => render(input.value));
    input.addEventListener("keydown", (e) => {
        if (e.key === "ArrowDown") {
            e.preventDefault();
            selectedIdx = Math.min(selectedIdx + 1, visibleItems.length - 1);
            updateHighlight();
        } else if (e.key === "ArrowUp") {
            e.preventDefault();
            selectedIdx = Math.max(selectedIdx - 1, 0);
            updateHighlight();
        } else if (e.key === "Enter") {
            e.preventDefault();
            if (visibleItems[selectedIdx]) choose(visibleItems[selectedIdx].item.value);
        } else if (e.key === "Escape") {
            e.preventDefault();
            close();
        }
    });

    overlay.addEventListener("mousedown", (e) => {
        if (!panel.contains(e.target)) close();
    });

    overlay.appendChild(panel);
    document.body.appendChild(overlay);
    render("");
    // Defer focus until after the triggering click event finishes to avoid focus steal
    requestAnimationFrame(() => {
        input.focus();
        input.select();
    });
}

// Find matching LoRA in the opposite HIGH/LOW folder
async function findMatchingLora(loraName, sourceType) {
    try {
        const resp = await api.fetchApi("/hermes/wan_loras/find_match", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                lora_name: loraName,
                source_type: sourceType
            })
        });
        if (resp.ok) {
            const data = await resp.json();
            return data.match;
        }
    } catch (e) {
        console.warn("Failed to find matching LoRA:", e);
    }
    return null;
}

// Show dropdown menu for preset selection
function showDropdownMenu(event, items, title, callback) {
    const menu = items.map(item => ({
        content: item,
        callback: () => callback(item)
    }));

    if (menu.length === 0) {
        menu.push({
            content: "(empty)",
            disabled: true
        });
    }

    new LiteGraph.ContextMenu(menu, {
        event: event,
        title: title
    });
}

app.registerExtension({
    name: "hermes.WANDualLoraLoader",

    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (nodeData.name !== "WANDualLoraLoader") {
            return;
        }

        // Store original methods
        const origOnNodeCreated = nodeType.prototype.onNodeCreated;
        const origOnConfigure = nodeType.prototype.onConfigure;

        nodeType.prototype.onNodeCreated = function() {
            if (origOnNodeCreated) {
                origOnNodeCreated.apply(this, arguments);
            }

            // Enable widget serialization
            this.serialize_widgets = true;

            // Initialize LoRA data
            this.highLoras = [];
            this.lowLoras = [];
            this.loraListsHigh = [];
            this.loraListsLow = [];
            this.loraWidgetCounter = 0;

            // Initialize preset data
            this.presetLists = { "Default": {} };
            this.currentList = "Default";
            this.currentPreset = "None";
            this.saveAsName = "";

            // Create the dual LoRA panel as a custom widget
            this.createDualLoraWidget();
        };

        const origOnAdded = nodeType.prototype.onAdded;
        nodeType.prototype.onAdded = function() {
            origOnAdded?.apply(this, arguments);
            liveNodes.add(this);
            this.refreshLoraLists();
            this.fetchPresets();
        };

        const origOnRemoved = nodeType.prototype.onRemoved;
        nodeType.prototype.onRemoved = function() {
            liveNodes.delete(this);
            return origOnRemoved?.apply(this, arguments);
        };

        // Take a fresh copy of the preset lists (from the server or a broadcast)
        nodeType.prototype.applyPresetLists = function(lists) {
            this.presetLists = lists && Object.keys(lists).length ? lists : { "Default": {} };
            if (!this.presetLists[this.currentList]) {
                this.currentList = Object.keys(this.presetLists)[0];
            }
            // the selected preset may have been deleted by another client
            if (this.currentPreset !== "None" && !this.presetLists[this.currentList]?.[this.currentPreset]) {
                this.currentPreset = "None";
            }
            this.setDirtyCanvas(true);
        };

        nodeType.prototype.fetchPresets = async function(force = false) {
            const lists = await getPresetLists(force);
            if (lists) this.applyPresetLists(lists);
        };

        // Create custom widget for the dual LoRA panel
        nodeType.prototype.createDualLoraWidget = function() {
            const node = this;

            const widget = {
                name: "wan_dual_lora_panel",
                type: "custom",
                serialize: false,
                options: { serialize: false },
                value: null,

                draw: function(ctx, node, width, y, height) {
                    node.drawDualLoraPanel(ctx, width, y);
                },

                computeSize: function() {
                    const highRows = node.highLoras ? node.highLoras.length : 0;
                    const lowRows = node.lowLoras ? node.lowLoras.length : 0;
                    const maxRows = Math.max(highRows, lowRows, 0);
                    // LoRA panel + preset section
                    return [340, HEADER_HEIGHT + (maxRows * ROW_HEIGHT) + ROW_HEIGHT + PRESET_SECTION_HEIGHT + 16];
                },

                mouse: function(event, pos, node) {
                    return node.handleLoraWidgetMouse(event, pos);
                }
            };

            this.addCustomWidget(widget);
        };

        // Grow node size if needed (never shrink)
        nodeType.prototype.growSizeIfNeeded = function() {
            const computed = this.computeSize();
            const newWidth = Math.max(this.size[0], computed[0]);
            const newHeight = Math.max(this.size[1], computed[1]);
            if (newWidth !== this.size[0] || newHeight !== this.size[1]) {
                this.setSize([newWidth, newHeight]);
            }
        };

        // Refresh LoRA file lists from server
        nodeType.prototype.refreshLoraLists = async function(force = false) {
            [this.loraListsHigh, this.loraListsLow] = await getLoraLists(force);
            this.setDirtyCanvas(true);
        };

        // Draw the dual LoRA panel
        nodeType.prototype.drawDualLoraPanel = function(ctx, width, startY) {
            const margin = 10;
            const colWidth = (width - margin * 3) / 2;
            const leftX = margin;
            const rightX = margin * 2 + colWidth;

            let y = startY;

            // Draw headers
            ctx.save();
            ctx.fillStyle = "#2d2d2d";
            ctx.fillRect(leftX, y, colWidth, HEADER_HEIGHT);
            ctx.fillRect(rightX, y, colWidth, HEADER_HEIGHT);

            ctx.fillStyle = "#ccc";
            ctx.font = "bold 11px Arial";
            ctx.textAlign = "center";
            ctx.textBaseline = "middle";
            ctx.fillText("HIGH LoRAs", leftX + colWidth/2, y + HEADER_HEIGHT/2);
            ctx.fillText("LOW LoRAs", rightX + colWidth/2, y + HEADER_HEIGHT/2);
            ctx.restore();

            y += HEADER_HEIGHT + 2;

            // Store hit areas
            this.loraHitAreas = {};
            this.addButtonAreas = {};
            this.presetHitAreas = {};

            // Draw HIGH column
            for (let i = 0; i < this.highLoras.length; i++) {
                this.drawLoraRow(ctx, leftX, y + i * ROW_HEIGHT, colWidth, this.highLoras[i], 'high', i);
            }

            // Draw LOW column
            for (let i = 0; i < this.lowLoras.length; i++) {
                this.drawLoraRow(ctx, rightX, y + i * ROW_HEIGHT, colWidth, this.lowLoras[i], 'low', i);
            }

            // Draw add buttons
            const maxRows = Math.max(this.highLoras.length, this.lowLoras.length);
            const addY = y + maxRows * ROW_HEIGHT + 2;

            this.drawAddButton(ctx, leftX, addY, colWidth, 'high');
            this.drawAddButton(ctx, rightX, addY, colWidth, 'low');

            // Draw preset section
            const presetY = addY + ROW_HEIGHT + 8;
            this.drawPresetSection(ctx, margin, presetY, width - margin * 2);
        };

        // Draw preset section with List, Load, Save controls
        nodeType.prototype.drawPresetSection = function(ctx, x, y, width) {
            const rowHeight = 22;
            const labelWidth = 42;
            const buttonWidth = 50;
            const gap = 4;
            const padding = 8;

            ctx.save();

            // Background
            ctx.fillStyle = "#252525";
            ctx.beginPath();
            ctx.roundRect(x, y, width, PRESET_SECTION_HEIGHT - 8, 4);
            ctx.fill();

            let currentY = y + 6;

            // Row 1: List dropdown
            ctx.fillStyle = "#888";
            ctx.font = "10px Arial";
            ctx.textAlign = "left";
            ctx.textBaseline = "middle";
            ctx.fillText("List:", x + padding, currentY + rowHeight/2);

            const listBoxX = x + padding + labelWidth;
            const listBoxWidth = width - padding * 2 - labelWidth;
            this.drawDropdownBox(ctx, listBoxX, currentY, listBoxWidth, rowHeight, this.currentList);
            this.presetHitAreas.listDropdown = { x: listBoxX, y: currentY, w: listBoxWidth, h: rowHeight };

            currentY += rowHeight + gap;

            // Row 2: Load dropdown + Load button + Delete button
            ctx.fillStyle = "#888";
            ctx.fillText("Load:", x + padding, currentY + rowHeight/2);

            const loadBoxX = x + padding + labelWidth;
            const loadBoxWidth = width - padding * 2 - labelWidth - buttonWidth * 2 - gap * 2;
            this.drawDropdownBox(ctx, loadBoxX, currentY, loadBoxWidth, rowHeight, this.currentPreset || "None");
            this.presetHitAreas.loadDropdown = { x: loadBoxX, y: currentY, w: loadBoxWidth, h: rowHeight };

            // Load button
            const loadBtnX = loadBoxX + loadBoxWidth + gap;
            this.drawButton(ctx, loadBtnX, currentY, buttonWidth, rowHeight, "Load", "#4a6");
            this.presetHitAreas.loadButton = { x: loadBtnX, y: currentY, w: buttonWidth, h: rowHeight };

            // Delete button
            const deleteBtnX = loadBtnX + buttonWidth + gap;
            this.drawButton(ctx, deleteBtnX, currentY, buttonWidth, rowHeight, "Delete", "#a44");
            this.presetHitAreas.deleteButton = { x: deleteBtnX, y: currentY, w: buttonWidth, h: rowHeight };

            currentY += rowHeight + gap;

            // Row 3: Save name input + Save button (aligned with dropdowns above)
            const saveBoxX = x + padding + labelWidth;
            const saveBoxWidth = width - padding * 2 - labelWidth - buttonWidth - gap;
            this.drawTextBox(ctx, saveBoxX, currentY, saveBoxWidth, rowHeight, this.saveAsName || "(click to enter name)");
            this.presetHitAreas.saveNameBox = { x: saveBoxX, y: currentY, w: saveBoxWidth, h: rowHeight };

            // Save button
            const saveBtnX = saveBoxX + saveBoxWidth + gap;
            this.drawButton(ctx, saveBtnX, currentY, buttonWidth, rowHeight, "Save", "#46a");
            this.presetHitAreas.saveButton = { x: saveBtnX, y: currentY, w: buttonWidth, h: rowHeight };

            ctx.restore();
        };

        // Draw a dropdown box
        nodeType.prototype.drawDropdownBox = function(ctx, x, y, width, height, text) {
            ctx.fillStyle = "#1a1a1a";
            ctx.beginPath();
            ctx.roundRect(x, y, width, height, 3);
            ctx.fill();

            ctx.strokeStyle = "#444";
            ctx.stroke();

            ctx.fillStyle = "#ccc";
            ctx.font = "11px Arial";
            ctx.textAlign = "left";
            ctx.textBaseline = "middle";

            // Truncate text
            let displayText = text || "";
            while (ctx.measureText(displayText).width > width - 20 && displayText.length > 3) {
                displayText = displayText.slice(0, -4) + "...";
            }
            ctx.fillText(displayText, x + 6, y + height/2);

            // Draw dropdown arrow
            ctx.fillStyle = "#888";
            ctx.beginPath();
            ctx.moveTo(x + width - 14, y + height/2 - 3);
            ctx.lineTo(x + width - 6, y + height/2 - 3);
            ctx.lineTo(x + width - 10, y + height/2 + 3);
            ctx.closePath();
            ctx.fill();
        };

        // Draw a text input box
        nodeType.prototype.drawTextBox = function(ctx, x, y, width, height, text) {
            ctx.fillStyle = "#1a1a1a";
            ctx.beginPath();
            ctx.roundRect(x, y, width, height, 3);
            ctx.fill();

            ctx.strokeStyle = "#444";
            ctx.stroke();

            const isPlaceholder = !this.saveAsName;
            ctx.fillStyle = isPlaceholder ? "#666" : "#ccc";
            ctx.font = "11px Arial";
            ctx.textAlign = "left";
            ctx.textBaseline = "middle";

            let displayText = text || "";
            while (ctx.measureText(displayText).width > width - 12 && displayText.length > 3) {
                displayText = displayText.slice(0, -4) + "...";
            }
            ctx.fillText(displayText, x + 6, y + height/2);
        };

        // Draw a button
        nodeType.prototype.drawButton = function(ctx, x, y, width, height, text, color) {
            ctx.fillStyle = color || "#444";
            ctx.beginPath();
            ctx.roundRect(x, y, width, height, 3);
            ctx.fill();

            ctx.fillStyle = "#fff";
            ctx.font = "bold 10px Arial";
            ctx.textAlign = "center";
            ctx.textBaseline = "middle";
            ctx.fillText(text, x + width/2, y + height/2);
        };

        // Draw a single LoRA row
        nodeType.prototype.drawLoraRow = function(ctx, x, y, width, lora, type, index) {
            const height = ROW_HEIGHT - 2;
            const toggleSize = 14;
            const strengthWidth = 42;
            const margin = 4;

            ctx.save();

            // Background
            ctx.fillStyle = lora.on ? "#353535" : "#252525";
            ctx.beginPath();
            ctx.roundRect(x, y, width, height, 3);
            ctx.fill();

            let posX = x + margin;

            // Toggle checkbox
            ctx.fillStyle = lora.on ? "#5a5" : "#444";
            ctx.beginPath();
            ctx.roundRect(posX, y + (height - toggleSize)/2, toggleSize, toggleSize, 2);
            ctx.fill();

            if (lora.on) {
                ctx.fillStyle = "#fff";
                ctx.font = "bold 10px Arial";
                ctx.textAlign = "center";
                ctx.textBaseline = "middle";
                ctx.fillText("✓", posX + toggleSize/2, y + height/2);
            }

            // Store toggle hit area
            const toggleArea = { x: posX, y: y + (height - toggleSize)/2, w: toggleSize, h: toggleSize };

            posX += toggleSize + margin;

            // LoRA name (display without I2V/T2V prefix)
            const nameWidth = width - toggleSize - strengthWidth - margin * 5;
            ctx.fillStyle = lora.on ? "#ddd" : "#777";
            ctx.font = "11px Arial";
            ctx.textAlign = "left";
            ctx.textBaseline = "middle";

            let displayName = lora.lora ? getLoraDisplayName(lora.lora) : "(click to select)";
            // Truncate if too long
            while (ctx.measureText(displayName).width > nameWidth && displayName.length > 3) {
                displayName = displayName.slice(0, -4) + "...";
            }
            ctx.fillText(displayName, posX, y + height/2);

            const nameArea = { x: posX, y: y, w: nameWidth, h: height };

            posX = x + width - strengthWidth - margin;

            // Strength box
            ctx.fillStyle = "#2a2a2a";
            ctx.beginPath();
            ctx.roundRect(posX, y + 2, strengthWidth, height - 4, 2);
            ctx.fill();

            ctx.fillStyle = lora.on ? "#fff" : "#888";
            ctx.textAlign = "center";
            ctx.fillText(Number(lora.strength).toFixed(2), posX + strengthWidth/2, y + height/2);

            const strengthArea = { x: posX, y: y + 2, w: strengthWidth, h: height - 4 };

            ctx.restore();

            // Store hit areas
            this.loraHitAreas[`${type}_${index}`] = {
                toggle: toggleArea,
                name: nameArea,
                strength: strengthArea,
                row: { x: x, y: y, w: width, h: height, type: type, index: index }
            };
        };

        // Draw add button
        nodeType.prototype.drawAddButton = function(ctx, x, y, width, type) {
            const height = ROW_HEIGHT - 4;

            ctx.save();
            ctx.fillStyle = "#303030";
            ctx.strokeStyle = "#484848";
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.roundRect(x, y, width, height, 3);
            ctx.fill();
            ctx.stroke();

            ctx.fillStyle = "#888";
            ctx.font = "11px Arial";
            ctx.textAlign = "center";
            ctx.textBaseline = "middle";
            ctx.fillText("+ Add LoRA", x + width/2, y + height/2);
            ctx.restore();

            this.addButtonAreas[type] = { x: x, y: y, w: width, h: height };
        };

        // Handle mouse events on the LoRA widget
        nodeType.prototype.handleLoraWidgetMouse = function(event, pos) {
            if (event.type !== "pointerdown") return false;

            // Check preset controls
            if (this.presetHitAreas) {
                // List dropdown
                if (this.isInArea(pos, this.presetHitAreas.listDropdown)) {
                    const lists = Object.keys(this.presetLists);
                    showDropdownMenu(event, lists, "Select List", (selected) => {
                        this.currentList = selected;
                        this.currentPreset = "None";
                        this.setDirtyCanvas(true);
                    });
                    return true;
                }

                // Load dropdown
                if (this.isInArea(pos, this.presetHitAreas.loadDropdown)) {
                    const presets = ["None", ...Object.keys(this.presetLists[this.currentList] || {})];
                    showDropdownMenu(event, presets, "Select Preset", (selected) => {
                        this.currentPreset = selected;
                        // Pre-fill the save name so the preset is easy to overwrite
                        if (selected && selected !== "None") {
                            this.saveAsName = selected;
                        }
                        this.setDirtyCanvas(true);
                    });
                    return true;
                }

                // Load button
                if (this.isInArea(pos, this.presetHitAreas.loadButton)) {
                    this.loadPreset();
                    return true;
                }

                // Delete button
                if (this.isInArea(pos, this.presetHitAreas.deleteButton)) {
                    this.deletePreset();
                    return true;
                }

                // Save name box - use canvas.prompt for input
                if (this.isInArea(pos, this.presetHitAreas.saveNameBox)) {
                    app.canvas.prompt("Preset Name", this.saveAsName || "", (value) => {
                        this.saveAsName = value;
                        this.setDirtyCanvas(true);
                    }, event);
                    return true;
                }

                // Save button
                if (this.isInArea(pos, this.presetHitAreas.saveButton)) {
                    this.savePreset();
                    return true;
                }
            }

            // Check add buttons
            for (const [type, area] of Object.entries(this.addButtonAreas || {})) {
                if (this.isInArea(pos, area)) {
                    this.addLora(type, event);
                    return true;
                }
            }

            // Check LoRA rows
            for (const [key, areas] of Object.entries(this.loraHitAreas || {})) {
                const [type, indexStr] = key.split('_');
                const index = parseInt(indexStr);
                const list = type === 'high' ? this.highLoras : this.lowLoras;

                // Toggle
                if (this.isInArea(pos, areas.toggle)) {
                    if (list[index]) {
                        list[index].on = !list[index].on;
                        this.commitLoras();
                    }
                    return true;
                }

                // Name (show dropdown)
                if (this.isInArea(pos, areas.name)) {
                    this.showLoraSelector(type, index, event);
                    return true;
                }

                // Strength
                if (this.isInArea(pos, areas.strength)) {
                    this.editStrength(type, index, event);
                    return true;
                }
            }

            return false;
        };

        // Save current state as preset
        nodeType.prototype.savePreset = async function() {
            if (!this.saveAsName || !this.saveAsName.trim()) {
                alert("Please enter a preset name");
                return;
            }

            // Get prompt widget value
            const promptWidget = this.widgets.find(w => w.name === "prompt");
            const prompt = promptWidget ? promptWidget.value : "";

            const presetData = {
                prompt: prompt,
                highLoras: this.highLoras.map(l => ({...l})),
                lowLoras: this.lowLoras.map(l => ({...l}))
            };

            try {
                const resp = await api.fetchApi("/hermes/presets/save", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        list_name: this.currentList,
                        preset_name: this.saveAsName.trim(),
                        preset_data: presetData
                    })
                });

                if (!resp.ok) throw new Error(await errorText(resp));
                this.currentPreset = this.saveAsName.trim();
                this.setDirtyCanvas(true);
            } catch (e) {
                console.error("Failed to save preset:", e);
                alert(`Failed to save preset: ${e.message}`);
            }
        };

        // Load selected preset
        nodeType.prototype.loadPreset = async function() {
            // "None" clears everything
            if (!this.currentPreset || this.currentPreset === "None") {
                const promptWidget = this.widgets.find(w => w.name === "prompt");
                const hasContent = this.highLoras.length || this.lowLoras.length || promptWidget?.value;
                if (hasContent && !confirm("Clear the prompt and all LoRAs?")) {
                    return;
                }
                if (promptWidget) {
                    promptWidget.value = "";
                }
                this.highLoras = [];
                this.lowLoras = [];
                this.commitLoras();
                return;
            }

            try {
                const resp = await api.fetchApi("/hermes/presets/load", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        list_name: this.currentList,
                        preset_name: this.currentPreset
                    })
                });

                if (!resp.ok) throw new Error(await errorText(resp));
                const { preset } = await resp.json();

                const promptWidget = this.widgets.find(w => w.name === "prompt");
                if (promptWidget && preset.prompt !== undefined) {
                    promptWidget.value = preset.prompt;
                }
                this.highLoras = (preset.highLoras || []).map(normalizeLora);
                this.lowLoras = (preset.lowLoras || []).map(normalizeLora);

                // Pre-fill the save name so the loaded preset is easy to re-save
                this.saveAsName = this.currentPreset;

                this.commitLoras();
                this.growSizeIfNeeded();
            } catch (e) {
                console.error("Failed to load preset:", e);
                alert(`Failed to load preset: ${e.message}`);
            }
        };

        // Delete selected preset
        nodeType.prototype.deletePreset = async function() {
            if (!this.currentPreset || this.currentPreset === "None") {
                return;
            }

            if (!confirm(`Delete preset "${this.currentPreset}"?`)) {
                return;
            }

            try {
                const resp = await api.fetchApi("/hermes/presets/delete", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        list_name: this.currentList,
                        preset_name: this.currentPreset
                    })
                });

                if (!resp.ok) throw new Error(await errorText(resp));
                this.currentPreset = "None";
                this.setDirtyCanvas(true);
            } catch (e) {
                console.error("Failed to delete preset:", e);
                alert(`Failed to delete preset: ${e.message}`);
            }
        };

        // Check if point is in area
        nodeType.prototype.isInArea = function(pos, area) {
            if (!area) return false;
            return pos[0] >= area.x && pos[0] <= area.x + area.w &&
                   pos[1] >= area.y && pos[1] <= area.y + area.h;
        };

        // Add a new LoRA entry with auto-match for opposite column
        nodeType.prototype.addLora = function(type, event) {
            const loras = type === 'high' ? this.loraListsHigh : this.loraListsLow;
            const list = type === 'high' ? this.highLoras : this.lowLoras;
            const otherList = type === 'high' ? this.lowLoras : this.highLoras;
            const otherType = type === 'high' ? 'low' : 'high';

            showLoraMenu(event, loras, async (selected) => {
                if (selected) {
                    // Check if already exists in this list
                    const alreadyInList = list.some(l => l.lora === selected);
                    if (alreadyInList) {
                        console.debug(`LoRA already in ${type.toUpperCase()} list: ${selected}`);
                        return;
                    }

                    // Add to the selected column
                    list.push({
                        on: true,
                        lora: selected,
                        strength: 1.0
                    });

                    // Try to find and add matching LoRA in the other column
                    const matchingLora = await findMatchingLora(selected, type);
                    if (matchingLora) {
                        // Check if already exists in other list
                        const alreadyExists = otherList.some(l => l.lora === matchingLora);
                        if (!alreadyExists) {
                            otherList.push({
                                on: true,
                                lora: matchingLora,
                                strength: 1.0
                            });
                            console.debug(`Auto-added matching ${otherType.toUpperCase()} LoRA: ${matchingLora}`);
                        }
                    }

                    this.commitLoras();
                    this.growSizeIfNeeded();
                    this.setDirtyCanvas(true);
                }
            });
        };

        // Show LoRA selector
        nodeType.prototype.showLoraSelector = function(type, index, event) {
            const loras = type === 'high' ? this.loraListsHigh : this.loraListsLow;
            const list = type === 'high' ? this.highLoras : this.lowLoras;

            showLoraMenu(event, loras, (selected) => {
                if (selected === null) {
                    // "None" selected - remove this LoRA from the list
                    list.splice(index, 1);
                    this.commitLoras();
                } else if (selected && list[index]) {
                    list[index].lora = selected;
                    this.commitLoras();
                }
            });
        };

        // Edit strength value - use canvas.prompt like Power Lora Loader
        nodeType.prototype.editStrength = function(type, index, event) {
            const row = (type === 'high' ? this.highLoras : this.lowLoras)[index];
            if (!row) return;

            // the prompt is not modal: rows may be removed or replaced before Enter
            app.canvas.prompt("Strength", String(row.strength), (value) => {
                const parsed = parseFloat(value);
                const stillThere = this.highLoras.includes(row) || this.lowLoras.includes(row);
                if (!isNaN(parsed) && stillThere) {
                    row.strength = parsed;
                    this.commitLoras();
                }
            }, event);
        };

        // Sync LoRA data to widgets for Python backend
        nodeType.prototype.syncLoraWidgets = function() {
            // Remove old dynamic lora widgets
            const toRemove = [];
            for (let i = this.widgets.length - 1; i >= 0; i--) {
                const w = this.widgets[i];
                if (w.name && (w.name.startsWith('HIGH_LORA_') || w.name.startsWith('LOW_LORA_'))) {
                    toRemove.push(i);
                }
            }
            for (const i of toRemove) {
                this.widgets.splice(i, 1);
            }

            // Add widgets for each HIGH LoRA
            for (let i = 0; i < this.highLoras.length; i++) {
                const lora = this.highLoras[i];
                this.addLoraWidget(`HIGH_LORA_${i}`, lora, 'high');
            }

            // Add widgets for each LOW LoRA
            for (let i = 0; i < this.lowLoras.length; i++) {
                const lora = this.lowLoras[i];
                this.addLoraWidget(`LOW_LORA_${i}`, lora, 'low');
            }
        };

        // Apply a user edit: rebuild the backend widgets, redraw, record for undo
        nodeType.prototype.commitLoras = function() {
            this.syncLoraWidgets();
            this.setDirtyCanvas(true);
            markWorkflowChanged();
        };

        // Add a hidden widget for a LoRA entry
        nodeType.prototype.addLoraWidget = function(name, loraData, loraType) {
            const widget = {
                name: name,
                type: "hidden",
                options: { serialize: true },
                value: { ...loraData, _type: loraType },
                computeSize: () => [0, -4],
                // Serialize method for saving to workflow
                serializeValue: function() {
                    return { ...this.value };
                }
            };
            this.widgets.push(widget);
        };

        // Right-click context menu
        const origGetExtraMenuOptions = nodeType.prototype.getExtraMenuOptions;
        nodeType.prototype.getExtraMenuOptions = function(canvas, options) {
            origGetExtraMenuOptions?.apply(this, arguments);
            // hit areas are node-relative, graph_mouse is in graph space
            const pos = [canvas.graph_mouse[0] - this.pos[0], canvas.graph_mouse[1] - this.pos[1]];

            // Check if over a LoRA row
            for (const [key, areas] of Object.entries(this.loraHitAreas || {})) {
                if (this.isInArea(pos, areas.row)) {
                    const [type, indexStr] = key.split('_');
                    const index = parseInt(indexStr);
                    const list = type === 'high' ? this.highLoras : this.lowLoras;

                    options.push(null); // separator

                    if (index > 0) {
                        options.push({
                            content: "Move Up",
                            callback: () => {
                                [list[index-1], list[index]] = [list[index], list[index-1]];
                                this.commitLoras();
                            }
                        });
                    }

                    if (index < list.length - 1) {
                        options.push({
                            content: "Move Down",
                            callback: () => {
                                [list[index], list[index+1]] = [list[index+1], list[index]];
                                this.commitLoras();
                            }
                        });
                    }

                    options.push({
                        content: "Remove LoRA",
                        callback: () => {
                            list.splice(index, 1);
                            this.commitLoras();
                            this.setSize(this.computeSize());
                            this.setDirtyCanvas(true);
                        }
                    });

                    break;
                }
            }

            options.push(null);
            options.push({
                content: "Refresh LoRA Lists",
                callback: async () => {
                    await getLoraLists(true);
                    for (const node of liveNodes) node.refreshLoraLists();
                }
            });
            options.push({
                content: "Refresh Presets",
                callback: async () => {
                    const lists = await getPresetLists(true);
                    if (lists) for (const node of liveNodes) node.applyPresetLists(lists);
                }
            });
        };

        // Handle configure for loading saved workflows
        nodeType.prototype.onConfigure = function(info) {
            if (origOnConfigure) {
                origOnConfigure.apply(this, arguments);
            }

            // Restore LoRA data from saved widget values
            this.highLoras = [];
            this.lowLoras = [];

            // Read from widgets_values array (how ComfyUI stores serialized data)
            if (info.widgets_values && Array.isArray(info.widgets_values)) {
                for (const value of info.widgets_values) {
                    if (value && typeof value === 'object' && value.lora !== undefined) {
                        // Check if it's a HIGH or LOW LoRA based on stored type
                        if (value._type === 'high') {
                            this.highLoras.push(normalizeLora(value));
                        } else if (value._type === 'low') {
                            this.lowLoras.push(normalizeLora(value));
                        }
                    }
                }
            }

            // Sync widgets after restoring
            this.syncLoraWidgets();

            // Preserve saved size from workflow, or use computed minimum
            const minSize = this.computeSize();
            if (info.size) {
                // Use saved size but ensure it's at least the minimum needed
                this.setSize([
                    Math.max(info.size[0], minSize[0]),
                    Math.max(info.size[1], minSize[1])
                ]);
            } else {
                this.setSize(minSize);
            }
        };

        // Override computeSize
        const origComputeSize = nodeType.prototype.computeSize;
        nodeType.prototype.computeSize = function() {
            const size = origComputeSize ? origComputeSize.apply(this, arguments) : [340, 100];
            size[0] = Math.max(size[0], 340);
            return size;
        };
    }
});
