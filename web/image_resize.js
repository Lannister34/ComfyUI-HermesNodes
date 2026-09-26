import { app } from "../../scripts/app.js";

// Shows "<in> -> <out>" size after each run.
app.registerExtension({
    name: "hermes.ImageResize",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "HermesImageResize") return;

        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (data) {
            onExecuted?.apply(this, arguments);
            if (!data?.text) return;

            let widget = this.widgets?.find((w) => w.name === "output_size");
            if (!widget) {
                widget = this.addWidget("text", "output_size", "", () => {}, { serialize: false });
                widget.serialize = false; // display only, keep it out of widgets_values
            }
            widget.value = data.text[0];
            this.setSize(this.computeSize());
        };
    },
});
