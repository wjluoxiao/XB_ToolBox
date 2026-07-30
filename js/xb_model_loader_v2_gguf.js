import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

app.registerExtension({
    name: "XB_ToolBox.ModelLoaderV2_GGUF",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "XB_ModelLoaderV2_GGUF") return;
        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            if (onNodeCreated) onNodeCreated.apply(this, arguments);
            const node = this;
            const wType = node.widgets.find(w => w.name === "model_type");
            const wModelH = node.widgets.find(w => w.name === "model_high");
            const wModelL = node.widgets.find(w => w.name === "model_low");
            const wClip = node.widgets.find(w => w.name === "clip");
            const wVae = node.widgets.find(w => w.name === "vae");
            node._lora_high_slots = []; node._lora_low_slots = [];
            for (let i = 1; i <= 4; i++) {
                const wLh = node.widgets.find(w => w.name === `lora_high_${i}`);
                const wOnh = node.widgets.find(w => w.name === `lora_high_${i}_on`);
                const wStrh = node.widgets.find(w => w.name === `lora_high_${i}_strength`);
                if (wLh && wOnh && wStrh) { if (i > 1) { wLh.type = "hidden"; wLh.computeSize = () => [0, -4]; wOnh.type = "hidden"; wOnh.computeSize = () => [0, -4]; wStrh.type = "hidden"; wStrh.computeSize = () => [0, -4]; } node._lora_high_slots.push({ idx: i, lora: wLh, on: wOnh, str: wStrh, visible: i === 1 }); }
                const wLl = node.widgets.find(w => w.name === `lora_low_${i}`);
                const wOnl = node.widgets.find(w => w.name === `lora_low_${i}_on`);
                const wStrl = node.widgets.find(w => w.name === `lora_low_${i}_strength`);
                if (wLl && wOnl && wStrl) { if (i > 1) { wLl.type = "hidden"; wLl.computeSize = () => [0, -4]; wOnl.type = "hidden"; wOnl.computeSize = () => [0, -4]; wStrl.type = "hidden"; wStrl.computeSize = () => [0, -4]; } node._lora_low_slots.push({ idx: i, lora: wLl, on: wOnl, str: wStrl, visible: i === 1 }); }
            }
            const refreshLists = async (keyword) => {
                if (!keyword || !keyword.trim()) return;
                try {
                    const resp = await api.fetchApi("/xb_toolbox/model_list", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ keyword: keyword.trim() }) });
                    if (resp.ok) {
                        const data = await resp.json();
                        if (data.models) { wModelH.options.values = data.models; wModelL.options.values = data.models; if (!data.models.includes(wModelH.value)) wModelH.value = data.models[0]; if (!data.models.includes(wModelL.value)) wModelL.value = data.models[0]; }
                        if (data.clips) { wClip.options.values = data.clips; if (!data.clips.includes(wClip.value)) wClip.value = data.clips[0]; }
                        if (data.vaes) { wVae.options.values = data.vaes; if (!data.vaes.includes(wVae.value)) wVae.value = data.vaes[0]; }
                        if (data.loras) { const lo = ["无", ...data.loras]; node._lora_high_slots.forEach(s => { s.lora.options.values = lo; }); node._lora_low_slots.forEach(s => { s.lora.options.values = lo; }); }
                        if (wModelH.callback) wModelH.callback(wModelH.value);
                    }
                } catch (e) {}
            };
            if (wType) { const orig = wType.callback; wType.callback = function (v) { if (orig) orig.apply(this, arguments); refreshLists(v); }; }
            const mkBtn = (label, slots) => {
                const btn = node.addWidget("button", label, "btn", () => { const h = slots.filter(s => !s.visible); if (h.length > 0) { h[0].visible = true; h[0].lora.type = "combo"; h[0].lora.computeSize = () => [node.size[0] - 16, 26]; h[0].on.type = "toggle"; h[0].on.computeSize = () => [node.size[0] - 16, 26]; h[0].str.type = "number"; h[0].str.computeSize = () => [node.size[0] - 16, 26]; node.setDirtyCanvas(true, true); } }); btn.options.serialize = false;
                const btnD = node.addWidget("button", label.replace("➕","➖"), "btn2", () => { const v = slots.filter(s => s.visible); if (v.length > 1) { const s = v[v.length - 1]; s.visible = false; s.lora.type = "hidden"; s.lora.computeSize = () => [0, -4]; s.on.type = "hidden"; s.on.computeSize = () => [0, -4]; s.str.type = "hidden"; s.str.computeSize = () => [0, -4]; s.lora.value = "无"; s.on.value = false; s.str.value = 1.0; node.setDirtyCanvas(true, true); } }); btnD.options.serialize = false;
            };
            mkBtn("➕ 高噪LoRA", node._lora_high_slots);
            mkBtn("➕ 低噪LoRA", node._lora_low_slots);
            setTimeout(() => { if (wType && wType.value && wType.value.trim()) refreshLists(wType.value); }, 300);
            if (node.size[1] < 640) node.size[1] = 640;
        };
    }
});
