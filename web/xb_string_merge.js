import { app } from "../../scripts/app.js";

// ─── 动态输入槽管理（源自 ComfyUI-KJNodes） ───
// 添加 "Update inputs" 按钮，根据 inputcount 重建 string_1..string_N 插槽
function setupDynamicInputs(node, { type, prefix, countWidget = "inputcount", slotOptions } = {}) {
    const rebuild = () => {
        if (!node.inputs) node.inputs = [];
        const countW = node.widgets?.find(w => w.name === countWidget);
        if (!countW) return;
        const target = countW.value;
        const current = node.inputs.filter(i => i.name?.startsWith(prefix)).length;
        if (target === current) return;
        if (target < current) {
            for (let i = 0; i < current - target; i++) node.removeInput(node.inputs.length - 1);
        } else {
            for (let i = current + 1; i <= target; i++) node.addInput(`${prefix}${i}`, type, slotOptions);
        }
    };
    node.addWidget("button", "Update inputs", null, rebuild);
    const countW = node.widgets?.find(w => w.name === countWidget);
    if (countW) {
        const origCb = countW.callback;
        countW.callback = function (value, canvas) {
            const r = origCb ? origCb.apply(this, arguments) : undefined;
            if (!canvas) rebuild();  // bare = API reload; skip interactive scrub
            return r;
        };
    }
    return rebuild;
}

app.registerExtension({
    name: "XB_ToolBox.StringMerge",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "XB_StringMerge") return;

        const origOnNodeCreated = nodeType.prototype.onNodeCreated || function () { };
        nodeType.prototype.onNodeCreated = function () {
            origOnNodeCreated.apply(this, arguments);
            setupDynamicInputs(this, { type: "STRING", prefix: "string_", slotOptions: { shape: 7 } });
        };
    },
});
