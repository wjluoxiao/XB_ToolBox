/**
 * XB FLUX多图编码 — 动态图片输入槽位管理
 * ==========================================
 * 默认1个图片输入，接入后自动新增，最多9个。
 */

import { app } from "../../scripts/app.js";

const NODE_TYPE = "XB_FluxMultiImageEncode";
const MAX_IMAGES = 9;
const FIXED_INPUT_NAMES = new Set(["positive", "negative", "vae", "image1", "longer_edge"]);

function isImageInput(inp) {
    return !FIXED_INPUT_NAMES.has(inp.name) && (inp.type === "IMAGE" || inp.type === "*");
}

app.registerExtension({
    name: "XB_ToolBox.FluxMultiImageEncode",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData?.name !== NODE_TYPE) return;

        const orig = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = orig?.apply(this, arguments);
            const self = this;

            // Ensure one dynamic image slot exists initially
            const hasDyn = (self.inputs || []).some(inp => isImageInput(inp));
            if (!hasDyn) self.addInput("image2", "IMAGE");

            // ---- stabilize ----
            const stabilize = () => {
                if (!self.graph || self.__xb_removed) return;
                let dirty = false;
                const inputs = self.inputs;

                // Count dynamic image inputs
                const dynIndices = [];
                for (let i = 0; i < inputs.length; i++) {
                    if (isImageInput(inputs[i])) dynIndices.push(i);
                }

                const count = dynIndices.length;

                // If last dynamic input is connected and we're under max, add new
                if (count > 0 && count < MAX_IMAGES) {
                    const lastDyn = inputs[dynIndices[count - 1]];
                    if (lastDyn?.link != null) {
                        self.addInput(`image${count + 2}`, "IMAGE");
                        dirty = true;
                    }
                }

                // Remove empty dynamic inputs from middle (keep exactly one empty at end, not exceeding max)
                const newDynIndices = [];
                for (let i = 0; i < inputs.length; i++) {
                    if (isImageInput(inputs[i])) newDynIndices.push(i);
                }
                for (let di = newDynIndices.length - 2; di >= 0; di--) {
                    const idx = newDynIndices[di];
                    if (inputs[idx].link == null) {
                        self.removeInput(idx);
                        dirty = true;
                    }
                }

                if (dirty) self.graph.setDirtyCanvas(true, true);

                if (!self.__xb_removed) {
                    self.__xb_timer = setTimeout(stabilize, 300);
                }
            };

            // ---- hooks ----
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
        // Ensure at least one dynamic slot on reload
        const hasDyn = (node.inputs || []).some(inp => isImageInput(inp));
        if (!hasDyn) node.addInput("image2", "IMAGE");
    },
});
