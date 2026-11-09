import { app } from "../../scripts/app.js";

// ============================================================
// XB_MSR — 多图合成帧序列 UI
// ============================================================

app.registerExtension({
    name: "xiaobai.msr",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "XB_MSR") return;
        // MSR 节点使用默认 ComfyUI 样式，无需额外定制
    },
});
