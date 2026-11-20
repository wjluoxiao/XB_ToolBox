/**
 * XB 编码分块节点 — 动态图片输入槽位
 * =====================================
 * 只声明第一个图片口，接上一个自动长出下一个：
 *   XB_MiniMaxH3ImageConditioningTiled → image_0、image_1…
 *   XB_TextEncodeQwenImage21Tiled       → image_1、image_2…
 * 保证任何时刻只有一个「末尾空槽」；中间空槽会被清掉（链接自动重排）。
 */

import { app } from "../../scripts/app.js";

const SLOT_RE = /^image_(\d+)$/;

const NODE_BASE_INDEX = {
    XB_MiniMaxH3ImageConditioningTiled: 0,
    XB_TextEncodeQwenImage21Tiled: 1,
};

function slotIndexOf(name) {
    const m = SLOT_RE.exec(name || "");
    return m ? parseInt(m[1], 10) : -1;
}

function imageSlots(node) {
    return (node.inputs || []).filter((inp) => inp && slotIndexOf(inp.name) >= 0);
}

function isFilled(slot) {
    return !!slot && slot.link != null;
}

function syncSlots(node) {
    const base = NODE_BASE_INDEX[node?.type];
    if (base === undefined || !node.graph) return;

    let changed = false;

    // 1) 只留末尾一个空槽：多余空槽（含中间空槽）一律移除
    for (let guard = 0; guard < 64; guard++) {
        const slots = imageSlots(node);
        if (slots.length === 0) break;

        let dirty = false;
        for (let i = slots.length - 1; i >= 1; i--) {
            if (!isFilled(slots[i]) && !isFilled(slots[i - 1])) {
                const idx = node.inputs.indexOf(slots[i]);
                if (idx >= 0) { node.removeInput(idx); dirty = changed = true; }
            }
        }
        for (let i = slots.length - 2; i >= 0; i--) {
            if (!isFilled(slots[i])) {
                const idx = node.inputs.indexOf(slots[i]);
                if (idx >= 0) { node.removeInput(idx); dirty = changed = true; }
            }
        }
        if (!dirty) break;
    }

    // 2) 序号压实：从 base 起连续编号（保持顺序、不动链接）
    let slots = imageSlots(node);
    for (let i = 0; i < slots.length; i++) {
        const wanted = `image_${base + i}`;
        if (slots[i].name !== wanted) {
            slots[i].name = wanted;
            changed = true;
        }
    }

    // 3) 至少留一个图片槽
    if (slots.length === 0) {
        node.addInput(`image_${base}`, "IMAGE");
        changed = true;
        slots = imageSlots(node);
    }

    // 4) 末尾槽已接上 → 追加下一个序号
    if (slots.length > 0 && isFilled(slots[slots.length - 1])) {
        node.addInput(`image_${base + slots.length}`, "IMAGE");
        changed = true;
    }

    if (changed && node.graph) node.graph.setDirtyCanvas(true, true);
}

app.registerExtension({
    name: "XB_ToolBox.EncodeTiledDynamicImages",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (!(nodeData?.name in NODE_BASE_INDEX)) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            this.__xbSyncImageSlots = () => syncSlots(this);
            syncSlots(this);
            return result;
        };

        const onConnectionsChange = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function () {
            const result = onConnectionsChange?.apply(this, arguments);
            syncSlots(this);
            return result;
        };

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const result = onConfigure?.apply(this, arguments);
            setTimeout(() => syncSlots(this), 0);
            return result;
        };
    },

    async loadedGraphNode(node) {
        if (!(node?.type in NODE_BASE_INDEX)) return;
        setTimeout(() => syncSlots(node), 0);
    },
});
