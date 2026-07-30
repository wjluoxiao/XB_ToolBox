import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// ============================================================
// XB_ModelLoaderV2 — 模型加载大全V2 (高噪+低噪 双模型)
// ============================================================

app.registerExtension({
    name: "XB_ToolBox.ModelLoaderV2",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "XB_ModelLoaderV2") return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            if (onNodeCreated) onNodeCreated.apply(this, arguments);
            const node = this;

            const wType = node.widgets.find(w => w.name === "model_type");
            const wModelH = node.widgets.find(w => w.name === "model_high");
            const wModelL = node.widgets.find(w => w.name === "model_low");
            const wClip = node.widgets.find(w => w.name === "clip");
            const wVae = node.widgets.find(w => w.name === "vae");

            // 高噪 LoRA 槽
            node._lora_high_slots = [];
            for (let i = 1; i <= 4; i++) {
                const wL = node.widgets.find(w => w.name === `lora_high_${i}`);
                const wOn = node.widgets.find(w => w.name === `lora_high_${i}_on`);
                const wStr = node.widgets.find(w => w.name === `lora_high_${i}_strength`);
                if (wL && wOn && wStr) {
                    if (i > 1) {
                        wL.type = "hidden"; wL.computeSize = () => [0, -4];
                        wOn.type = "hidden"; wOn.computeSize = () => [0, -4];
                        wStr.type = "hidden"; wStr.computeSize = () => [0, -4];
                    }
                    node._lora_high_slots.push({ idx: i, lora: wL, on: wOn, str: wStr, visible: i === 1 });
                }
            }

            // 低噪 LoRA 槽
            node._lora_low_slots = [];
            for (let i = 1; i <= 4; i++) {
                const wL = node.widgets.find(w => w.name === `lora_low_${i}`);
                const wOn = node.widgets.find(w => w.name === `lora_low_${i}_on`);
                const wStr = node.widgets.find(w => w.name === `lora_low_${i}_strength`);
                if (wL && wOn && wStr) {
                    if (i > 1) {
                        wL.type = "hidden"; wL.computeSize = () => [0, -4];
                        wOn.type = "hidden"; wOn.computeSize = () => [0, -4];
                        wStr.type = "hidden"; wStr.computeSize = () => [0, -4];
                    }
                    node._lora_low_slots.push({ idx: i, lora: wL, on: wOn, str: wStr, visible: i === 1 });
                }
            }

            const refreshLists = async (keyword) => {
                if (!keyword || !keyword.trim()) return;
                try {
                    const resp = await api.fetchApi("/xb_toolbox/model_list", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ keyword: keyword.trim() })
                    });
                    if (resp.ok) {
                        const data = await resp.json();
                        if (data.models) {
                            wModelH.options.values = data.models;
                            if (!data.models.includes(wModelH.value)) wModelH.value = data.models[0];
                            wModelL.options.values = data.models;
                            if (!data.models.includes(wModelL.value)) wModelL.value = data.models[0];
                        }
                        if (data.clips) { wClip.options.values = data.clips; if (!data.clips.includes(wClip.value)) wClip.value = data.clips[0]; }
                        if (data.vaes) { wVae.options.values = data.vaes; if (!data.vaes.includes(wVae.value)) wVae.value = data.vaes[0]; }
                        if (data.loras) {
                            const loraOpts = ["无", ...data.loras];
                            node._lora_high_slots.forEach(s => { s.lora.options.values = loraOpts; });
                            node._lora_low_slots.forEach(s => { s.lora.options.values = loraOpts; });
                        }
                        if (wModelH.callback) wModelH.callback(wModelH.value);
                        if (wModelL.callback) wModelL.callback(wModelL.value);
                    }
                } catch (e) { console.error("[XB_ModelLoaderV2] 刷新失败:", e); }
            };

            if (wType) {
                const orig = wType.callback;
                wType.callback = function (v) { if (orig) orig.apply(this, arguments); refreshLists(v); };
            }

            // 高噪 LoRA 按钮
            const btnAddH = node.addWidget("button", "➕ 高噪LoRA", "add_hlora", () => {
                const h = node._lora_high_slots.filter(s => !s.visible);
                if (h.length > 0) { h[0].visible = true; h[0].lora.type = "combo"; h[0].lora.computeSize = () => [node.size[0] - 16, 26]; h[0].on.type = "toggle"; h[0].on.computeSize = () => [node.size[0] - 16, 26]; h[0].str.type = "number"; h[0].str.computeSize = () => [node.size[0] - 16, 26]; node.setDirtyCanvas(true, true); }
            });
            btnAddH.options.serialize = false;

            const btnDelH = node.addWidget("button", "➖ 高噪LoRA", "del_hlora", () => {
                const v = node._lora_high_slots.filter(s => s.visible);
                if (v.length > 1) { const s = v[v.length - 1]; s.visible = false; s.lora.type = "hidden"; s.lora.computeSize = () => [0, -4]; s.on.type = "hidden"; s.on.computeSize = () => [0, -4]; s.str.type = "hidden"; s.str.computeSize = () => [0, -4]; s.lora.value = "无"; s.on.value = false; s.str.value = 1.0; node.setDirtyCanvas(true, true); }
            });
            btnDelH.options.serialize = false;

            // 低噪 LoRA 按钮
            const btnAddL = node.addWidget("button", "➕ 低噪LoRA", "add_llora", () => {
                const h = node._lora_low_slots.filter(s => !s.visible);
                if (h.length > 0) { h[0].visible = true; h[0].lora.type = "combo"; h[0].lora.computeSize = () => [node.size[0] - 16, 26]; h[0].on.type = "toggle"; h[0].on.computeSize = () => [node.size[0] - 16, 26]; h[0].str.type = "number"; h[0].str.computeSize = () => [node.size[0] - 16, 26]; node.setDirtyCanvas(true, true); }
            });
            btnAddL.options.serialize = false;

            const btnDelL = node.addWidget("button", "➖ 低噪LoRA", "del_llora", () => {
                const v = node._lora_low_slots.filter(s => s.visible);
                if (v.length > 1) { const s = v[v.length - 1]; s.visible = false; s.lora.type = "hidden"; s.lora.computeSize = () => [0, -4]; s.on.type = "hidden"; s.on.computeSize = () => [0, -4]; s.str.type = "hidden"; s.str.computeSize = () => [0, -4]; s.lora.value = "无"; s.on.value = false; s.str.value = 1.0; node.setDirtyCanvas(true, true); }
            });
            btnDelL.options.serialize = false;

            setTimeout(() => { if (wType && wType.value && wType.value.trim()) refreshLists(wType.value); }, 300);
            if (node.size[1] < 640) node.size[1] = 640;
        };
    }
});
