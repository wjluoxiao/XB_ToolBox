import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import { hideWidget, showWidgetAs, slotSize } from "./xb_compat.js";

app.registerExtension({
    name: "XB_ToolBox.ModelLoaderV1_GGUF",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "XB_ModelLoaderV1_GGUF") return;
        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            if (onNodeCreated) onNodeCreated.apply(this, arguments);
            const node = this;
            const wType = node.widgets.find(w => w.name === "model_type");
            const wModel = node.widgets.find(w => w.name === "model");
            const wClip = node.widgets.find(w => w.name === "clip");
            const wVae = node.widgets.find(w => w.name === "vae");
            node._lora_slots = [];
            for (let i = 1; i <= 8; i++) {
                const wL = node.widgets.find(w => w.name === `lora_${i}`);
                const wOn = node.widgets.find(w => w.name === `lora_${i}_on`);
                const wStr = node.widgets.find(w => w.name === `lora_${i}_strength`);
                if (wL && wOn && wStr) {
                    // 隐藏槽位：经典模式靠 type="hidden"，Nodes 2.0 还需 hidden / options.hidden
                    if (i > 1) { hideWidget(node, wL); hideWidget(node, wOn); hideWidget(node, wStr); }
                    node._lora_slots.push({ idx: i, lora: wL, on: wOn, str: wStr, visible: i === 1 });
                }
            }
            const refreshLists = async (keyword) => {
                if (!keyword || !keyword.trim()) return;
                try {
                    const resp = await api.fetchApi("/xb_toolbox/model_list", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ keyword: keyword.trim() }) });
                    if (resp.ok) {
                        const data = await resp.json();
                        if (data.models) { wModel.options.values = data.models; if (!data.models.includes(wModel.value)) wModel.value = data.models[0]; }
                        if (data.clips) { wClip.options.values = data.clips; if (!data.clips.includes(wClip.value)) wClip.value = data.clips[0]; }
                        if (data.vaes) { wVae.options.values = data.vaes; if (!data.vaes.includes(wVae.value)) wVae.value = data.vaes[0]; }
                        if (data.loras) { const loraOpts = ["无", ...data.loras]; node._lora_slots.forEach(s => { s.lora.options.values = loraOpts; }); }
                        if (wModel.callback) wModel.callback(wModel.value);
                    }
                } catch (e) {}
            };
            if (wType) { const orig = wType.callback; wType.callback = function (v) { if (orig) orig.apply(this, arguments); refreshLists(v); }; }
            const btnAdd = node.addWidget("button", "➕ 添加LoRA", "add_lora", () => {
                const h = node._lora_slots.filter(s => !s.visible);
                if (h.length > 0) { const s = h[0]; s.visible = true; showWidgetAs(node, s.lora, { type: "combo", computeSize: slotSize(node, 26) }); showWidgetAs(node, s.on, { type: "toggle", computeSize: slotSize(node, 26) }); showWidgetAs(node, s.str, { type: "number", computeSize: slotSize(node, 26) }); node.setDirtyCanvas(true, true); }
            }); btnAdd.options.serialize = false;
            const btnDel = node.addWidget("button", "➖ 移除LoRA", "del_lora", () => {
                const v = node._lora_slots.filter(s => s.visible);
                if (v.length > 1) { const s = v[v.length - 1]; s.visible = false; hideWidget(node, s.lora); hideWidget(node, s.on); hideWidget(node, s.str); s.lora.value = "无"; s.on.value = false; s.str.value = 1.0; node.setDirtyCanvas(true, true); }
            }); btnDel.options.serialize = false;
            setTimeout(() => { if (wType && wType.value && wType.value.trim()) refreshLists(wType.value); }, 300);
            if (node.size[1] < 480) node.size[1] = 480;
        };
    }
});
