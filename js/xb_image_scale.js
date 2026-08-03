/**
 * XB 批量缩放图像 — 动态输入/输出槽位管理
 * ===========================================
 * N进N出，输入接入后自动新增（最多9个），输出槽位同步匹配。
 */

import { app } from "../../scripts/app.js";

const NODE_TYPE = "XB_ImageScale";
const MAX_IMAGES = 9;
const FIXED_INPUT_NAMES = new Set(["upscale_method", "width", "height", "crop", "image1"]);

function isImageInput(inp) {
    return !FIXED_INPUT_NAMES.has(inp.name) && (inp.type === "IMAGE" || inp.type === "*");
}

app.registerExtension({
    name: "XB_ToolBox.ImageScale",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData?.name !== NODE_TYPE) return;

        const orig = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = orig?.apply(this, arguments);
            const self = this;

            // Ensure one dynamic image slot exists
            const hasDyn = (self.inputs || []).some(inp => isImageInput(inp));
            if (!hasDyn) {
                self.addInput("image2", "IMAGE");
                // Also ensure output slots: image1 is fixed, add image2
                manageOutputs(self);
            }

            const stabilize = () => {
                if (!self.graph || self.__xb_removed) return;
                let dirty = false;
                const inputs = self.inputs;

                // ---- manage dynamic inputs ----
                const dynIndices = [];
                for (let i = 0; i < inputs.length; i++) {
                    if (isImageInput(inputs[i])) dynIndices.push(i);
                }

                const inCount = dynIndices.length;
                if (inCount > 0 && inCount < MAX_IMAGES) {
                    const lastDyn = inputs[dynIndices[inCount - 1]];
                    if (lastDyn?.link != null) {
                        self.addInput(`image${inCount + 2}`, "IMAGE");
                        dirty = true;
                    }
                }
                for (let di = dynIndices.length - 2; di >= 0; di--) {
                    if (inputs[dynIndices[di]].link == null) {
                        self.removeInput(dynIndices[di]);
                        dirty = true;
                    }
                }

                // ---- manage dynamic outputs (match input count) ----
                dirty = manageOutputs(self) || dirty;

                if (dirty) self.graph.setDirtyCanvas(true, true);
                if (!self.__xb_removed) {
                    self.__xb_timer = setTimeout(stabilize, 300);
                }
            };

            const origConn = self.onConnectionsChange;
            self.onConnectionsChange = function () {
                if (origConn) origConn.apply(this, arguments);
                if (self.__xb_timer) clearTimeout(self.__xb_timer);
                self.__xb_timer = setTimeout(stabilize, 80);
            };

            const origRem = self.onRemoved;
            self.onRemoved = function () {
                self.__xb_removed = true;
                if (self.__xb_timer) { clearTimeout(self.__xb_timer); self.__xb_timer = null; }
                if (origRem) origRem.apply(this, arguments);
            };

            stabilize();
            return r;
        };
    },

    async loadedGraphNode(node) {
        if (node.type !== NODE_TYPE) return;
        const hasDyn = (node.inputs || []).some(inp => isImageInput(inp));
        if (!hasDyn) node.addInput("image2", "IMAGE");
        manageOutputs(node);
    },
});

/** Count connected image inputs (image1 + dynamic). */
function countImageInputs(node) {
    let n = 0;
    for (const inp of (node.inputs || [])) {
        if (inp.type === "IMAGE" || inp.type === "*") n++;
    }
    return n;
}

/** Sync output slots to match connected input count (min 1, max 9). */
function manageOutputs(node) {
    let changed = false;
    const totalIns = countImageInputs(node);
    const targetOuts = Math.min(totalIns, MAX_IMAGES);
    const currentOuts = (node.outputs || []).length;

    // Remove trailing unconnected outputs if too many
    while ((node.outputs || []).length > targetOuts) {
        const last = node.outputs[node.outputs.length - 1];
        if (!last.links || last.links.length === 0) {
            node.removeOutput(node.outputs.length - 1);
            changed = true;
        } else {
            break; // don't remove connected outputs
        }
    }

    // Add outputs if needed
    while ((node.outputs || []).length < targetOuts && (node.outputs || []).length < MAX_IMAGES) {
        const idx = node.outputs.length + 1;
        node.addOutput(`图像${idx}`, "IMAGE");
        changed = true;
    }

    return changed;
}
