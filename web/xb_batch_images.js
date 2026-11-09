/**
 * XB 批量图像 — 动态图片输入槽位
 * =================================
 * 图片1 默认显示，接入后自动新增 图片2...图片50。
 * 断开后自动重编号，第一个永远是"图片1"。
 */

import { app } from "../../scripts/app.js";

const NODE_TYPE = "XB_BatchImages";
const MAX_IMAGES = 50;

function isImageSlot(inp) {
    return inp.name && /^(图片|image)\d+$/.test(inp.name);
}

app.registerExtension({
    name: "XB_ToolBox.BatchImages",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData?.name !== NODE_TYPE) return;
        const orig = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = orig?.apply(this, arguments);
            const self = this;

            if (!(self.inputs || []).some(inp => isImageSlot(inp))) {
                // 清理旧版 "image1" 端口
                const oldIdx = (self.inputs || []).findIndex(inp => inp.name === "image1");
                if (oldIdx >= 0) {
                    self.inputs[oldIdx].name = "图片1";
                } else {
                    self.addInput("图片1", "IMAGE");
                }
            }

            const renumber = () => {
                const slots = [];
                for (let i = 0; i < (self.inputs || []).length; i++) {
                    if (isImageSlot(self.inputs[i])) slots.push(i);
                }
                for (let n = 0; n < slots.length; n++) {
                    self.inputs[slots[n]].name = `图片${n + 1}`;
                }
            };

            const stabilize = () => {
                if (!self.graph || self.__xb_removed) return;
                let dirty = false;
                const inputs = self.inputs;
                const dynIndices = [];
                for (let i = 0; i < (inputs || []).length; i++) {
                    if (isImageSlot(inputs[i])) dynIndices.push(i);
                }
                const count = dynIndices.length;
                if (count > 0 && count < MAX_IMAGES) {
                    if (inputs[dynIndices[count - 1]]?.link != null) {
                        self.addInput("图片" + (count + 1), "IMAGE");
                        dirty = true;
                    }
                }
                for (let di = count - 2; di >= 0; di--) {
                    if (inputs[dynIndices[di]].link == null) {
                        self.removeInput(dynIndices[di]);
                        dirty = true;
                    }
                }
                if (dirty) {
                    renumber();
                    self.graph.setDirtyCanvas(true, true);
                }
                if (!self.__xb_removed) self.__xb_timer = setTimeout(stabilize, 300);
            };

            const oc = self.onConnectionsChange;
            self.onConnectionsChange = function () {
                if (oc) oc.apply(this, arguments);
                if (self.__xb_timer) clearTimeout(self.__xb_timer);
                self.__xb_timer = setTimeout(stabilize, 80);
            };

            const or_ = self.onRemoved;
            self.onRemoved = function () {
                self.__xb_removed = true;
                if (self.__xb_timer) { clearTimeout(self.__xb_timer); }
                if (or_) or_.apply(this, arguments);
            };

            stabilize();
            return r;
        };
    },

    async loadedGraphNode(node) {
        if (node.type !== NODE_TYPE) return;
        if (!(node.inputs || []).some(inp => isImageSlot(inp))) {
            node.addInput("图片1", "IMAGE");
        }
    },
});
