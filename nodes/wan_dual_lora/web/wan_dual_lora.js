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

// Fetch LoRA list from server
async function fetchLoraList(type) {
    try {
        const resp = await api.fetchApi(`/wan_loras/${type}`);
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

// Show LoRA selection menu with I2V/T2V grouped
function showLoraMenu(event, loras, callback) {
    const menu = [];

    menu.push({
        content: "None",
        callback: () => callback(null)
    });

    if (!loras || loras.length === 0) {
        menu.push({
            content: "(No LoRAs in folder)",
            disabled: true
        });
    } else {
        // Group by I2V/T2V
        const i2vLoras = loras.filter(l => l.startsWith("I2V/"));
        const t2vLoras = loras.filter(l => l.startsWith("T2V/"));
        const otherLoras = loras.filter(l => !l.startsWith("I2V/") && !l.startsWith("T2V/"));

        if (i2vLoras.length > 0) {
            menu.push({ content: "── I2V ──", disabled: true });
            for (const lora of i2vLoras) {
                menu.push({
                    content: getLoraDisplayName(lora),
                    callback: () => callback(lora)
                });
            }
        }

        if (t2vLoras.length > 0) {
            menu.push({ content: "── T2V ──", disabled: true });
            for (const lora of t2vLoras) {
                menu.push({
                    content: getLoraDisplayName(lora),
                    callback: () => callback(lora)
                });
            }
        }

        if (otherLoras.length > 0) {
            for (const lora of otherLoras) {
                menu.push({
                    content: lora,
                    callback: () => callback(lora)
                });
            }
        }
    }

    new LiteGraph.ContextMenu(menu, {
        event: event,
        title: "Select LoRA"
    });
}

// Find matching LoRA in the opposite HIGH/LOW folder
async function findMatchingLora(loraName, sourceType) {
    try {
        const resp = await api.fetchApi("/wan_loras/find_match", {
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
    name: "comfy.WANDualLoraLoader",

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

            // Fetch available LoRAs
            this.refreshLoraLists();

            // Fetch preset data
            this.fetchPresets();

            // Create the dual LoRA panel as a custom widget
            this.createDualLoraWidget();

            // Listen for preset updates from server
            this.setupPresetListener();
        };

        // Setup listener for preset updates
        nodeType.prototype.setupPresetListener = function() {
            const node = this;
            api.addEventListener("hermes-presets-update", (event) => {
                if (event.detail && event.detail.lists) {
                    node.presetLists = event.detail.lists;
                    node.setDirtyCanvas(true);
                }
            });
        };

        // Fetch presets from server
        nodeType.prototype.fetchPresets = async function() {
            try {
                const resp = await api.fetchApi("/hermes/presets/init", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({})
                });
                if (resp.ok) {
                    const data = await resp.json();
                    this.presetLists = data.lists || { "Default": {} };
                    if (!this.presetLists[this.currentList]) {
                        this.currentList = Object.keys(this.presetLists)[0] || "Default";
                    }
                    this.setDirtyCanvas(true);
                }
            } catch (e) {
                console.warn("Failed to fetch presets:", e);
            }
        };

        // Create custom widget for the dual LoRA panel
        nodeType.prototype.createDualLoraWidget = function() {
            const node = this;

            const widget = {
                name: "wan_dual_lora_panel",
                type: "custom",
                options: { serialize: false },
                _value: { high: [], low: [] },

                get value() {
                    return this._value;
                },

                set value(v) {
                    this._value = v || { high: [], low: [] };
                },

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
            this.dualLoraWidget = widget;
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
        nodeType.prototype.refreshLoraLists = async function() {
            this.loraListsHigh = await fetchLoraList('high');
            this.loraListsLow = await fetchLoraList('low');
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
            ctx.fillText(lora.strength.toFixed(2), posX + strengthWidth/2, y + height/2);

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
                        this.syncLoraWidgets();
                        this.setDirtyCanvas(true);
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

                if (resp.ok) {
                    this.currentPreset = this.saveAsName.trim();
                    this.setDirtyCanvas(true);
                }
            } catch (e) {
                console.error("Failed to save preset:", e);
                alert("Failed to save preset");
            }
        };

        // Load selected preset
        nodeType.prototype.loadPreset = async function() {
            // "None" clears everything
            if (!this.currentPreset || this.currentPreset === "None") {
                const promptWidget = this.widgets.find(w => w.name === "prompt");
                if (promptWidget) {
                    promptWidget.value = "";
                }
                this.highLoras = [];
                this.lowLoras = [];
                this.syncLoraWidgets();
                this.setDirtyCanvas(true);
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

                if (resp.ok) {
                    const data = await resp.json();
                    const preset = data.preset;

                    if (preset) {
                        // Set prompt
                        const promptWidget = this.widgets.find(w => w.name === "prompt");
                        if (promptWidget && preset.prompt !== undefined) {
                            promptWidget.value = preset.prompt;
                        }

                        // Set LoRAs
                        this.highLoras = (preset.highLoras || []).map(l => ({...l}));
                        this.lowLoras = (preset.lowLoras || []).map(l => ({...l}));

                        this.syncLoraWidgets();
                        this.growSizeIfNeeded();
                        this.setDirtyCanvas(true);
                    }
                }
            } catch (e) {
                console.error("Failed to load preset:", e);
                alert("Failed to load preset");
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

                if (resp.ok) {
                    this.currentPreset = "None";
                    this.setDirtyCanvas(true);
                }
            } catch (e) {
                console.error("Failed to delete preset:", e);
                alert("Failed to delete preset");
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
                        console.log(`LoRA already in ${type.toUpperCase()} list: ${selected}`);
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
                            console.log(`Auto-added matching ${otherType.toUpperCase()} LoRA: ${matchingLora}`);
                        }
                    }

                    this.syncLoraWidgets();
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
                    this.syncLoraWidgets();
                    this.setDirtyCanvas(true);
                } else if (selected && list[index]) {
                    list[index].lora = selected;
                    this.syncLoraWidgets();
                    this.setDirtyCanvas(true);
                }
            });
        };

        // Edit strength value - use canvas.prompt like Power Lora Loader
        nodeType.prototype.editStrength = function(type, index, event) {
            const list = type === 'high' ? this.highLoras : this.lowLoras;
            if (!list[index]) return;

            app.canvas.prompt("Strength", list[index].strength.toString(), (value) => {
                const parsed = parseFloat(value);
                if (!isNaN(parsed)) {
                    list[index].strength = parsed;
                    this.syncLoraWidgets();
                    this.setDirtyCanvas(true);
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
        nodeType.prototype.getExtraMenuOptions = function(canvas, options) {
            const pos = canvas.graph_mouse;

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
                                this.syncLoraWidgets();
                                this.setDirtyCanvas(true);
                            }
                        });
                    }

                    if (index < list.length - 1) {
                        options.push({
                            content: "Move Down",
                            callback: () => {
                                [list[index], list[index+1]] = [list[index+1], list[index]];
                                this.syncLoraWidgets();
                                this.setDirtyCanvas(true);
                            }
                        });
                    }

                    options.push({
                        content: "Remove LoRA",
                        callback: () => {
                            list.splice(index, 1);
                            this.syncLoraWidgets();
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
                callback: () => {
                    this.refreshLoraLists();
                }
            });
            options.push({
                content: "Refresh Presets",
                callback: () => {
                    this.fetchPresets();
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
                            this.highLoras.push({ on: value.on, lora: value.lora, strength: value.strength });
                        } else if (value._type === 'low') {
                            this.lowLoras.push({ on: value.on, lora: value.lora, strength: value.strength });
                        }
                    }
                }
            }

            // Also check widgets directly (for compatibility)
            if (this.highLoras.length === 0 && this.lowLoras.length === 0 && this.widgets) {
                for (const w of this.widgets) {
                    if (w.name && w.value && typeof w.value === 'object' && w.value.lora !== undefined) {
                        if (w.name.startsWith('HIGH_LORA_')) {
                            this.highLoras.push({ ...w.value });
                        } else if (w.name.startsWith('LOW_LORA_')) {
                            this.lowLoras.push({ ...w.value });
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

        // Override serialize to save LoRA data
        const origSerialize = nodeType.prototype.serialize;
        nodeType.prototype.serialize = function() {
            // Ensure widgets are synced before serialization
            this.syncLoraWidgets();

            const data = origSerialize ? origSerialize.apply(this, arguments) : {};
            return data;
        };

        // Override computeSize
        const origComputeSize = nodeType.prototype.computeSize;
        nodeType.prototype.computeSize = function() {
            let size = origComputeSize ? origComputeSize.apply(this, arguments) : [200, 100];

            const highRows = this.highLoras ? this.highLoras.length : 0;
            const lowRows = this.lowLoras ? this.lowLoras.length : 0;
            const maxRows = Math.max(highRows, lowRows, 0);

            // Calculate needed height: base + lora panel + preset section
            const baseHeight = 130; // model inputs, prompt, seed
            const loraHeight = HEADER_HEIGHT + (maxRows * ROW_HEIGHT) + ROW_HEIGHT + 12;
            const presetHeight = PRESET_SECTION_HEIGHT + 8;

            size[1] = Math.max(size[1], baseHeight + loraHeight + presetHeight);
            size[0] = Math.max(size[0], 340);

            return size;
        };
    }
});
