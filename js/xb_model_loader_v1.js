import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import { hideWidget, showWidgetAs, slotSize } from "./xb_compat.js";

// ============================================================
// XB_ModelLoaderV1 — 模型加载大全V1
// 关键字过滤 + LoRA多槽管理 + 折叠UI
// ============================================================

app.registerExtension({
    name: "XB_ToolBox.ModelLoaderV1",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "XB_ModelLoaderV1") return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            if (onNodeCreated) onNodeCreated.apply(this, arguments);
            const node = this;

            // ── Widget 引用 ──
            const wType = node.widgets.find(w => w.name === "model_type");
            const wModel = node.widgets.find(w => w.name === "model");
            const wClip = node.widgets.find(w => w.name === "clip");
            const wVae = node.widgets.find(w => w.name === "vae");

            // 隐藏LoRA开关和强度的label（通过后续CSS）
            node._lora_slots = [];
            for (let i = 1; i <= 8; i++) {
                const wL = node.widgets.find(w => w.name === `lora_${i}`);
                const wOn = node.widgets.find(w => w.name === `lora_${i}_on`);
                const wStr = node.widgets.find(w => w.name === `lora_${i}_strength`);
                if (wL && wOn && wStr) {
                    // 默认只有第一个lora可见
                    if (i > 1) {
                        // 隐藏槽位：经典模式靠 type="hidden"，Nodes 2.0 还需 hidden / options.hidden
                        hideWidget(node, wL);
                        hideWidget(node, wOn);
                        hideWidget(node, wStr);
                    }
                    node._lora_slots.push({ idx: i, lora: wL, on: wOn, str: wStr, visible: i === 1 });
                }
            }

            // ── 模型类型变化 → 刷新所有下拉列表 ──
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
                        if (data.models) { wModel.options.values = data.models; if (!data.models.includes(wModel.value)) wModel.value = data.models[0]; }
                        if (data.clips) { wClip.options.values = data.clips; if (!data.clips.includes(wClip.value)) wClip.value = data.clips[0]; }
                        if (data.vaes) { wVae.options.values = data.vaes; if (!data.vaes.includes(wVae.value)) wVae.value = data.vaes[0]; }
                        if (data.loras) {
                            const loraOpts = ["无", ...data.loras];
                            node._lora_slots.forEach(s => {
                                s.lora.options.values = loraOpts;
                            });
                        }
                        // 触发回调
                        if (wModel.callback) wModel.callback(wModel.value);
                    }
                } catch (e) { console.error("[XB_ModelLoaderV1] 刷新列表失败:", e); }
            };

            if (wType) {
                const orig = wType.callback;
                wType.callback = function (v) {
                    if (orig) orig.apply(this, arguments);
                    refreshLists(v);
                };
            }

            // ── 添加 LoRA 按钮 ──
            const btnAddLora = node.addWidget("button", "➕ 添加LoRA槽", "add_lora", () => {
                const hidden = node._lora_slots.filter(s => !s.visible);
                if (hidden.length > 0) {
                    const s = hidden[0];
                    s.visible = true;
                    // 恢复显示：经典模式还原 type/computeSize，Nodes 2.0 同时还原 hidden/options.hidden
                    showWidgetAs(node, s.lora, { type: "combo", computeSize: slotSize(node, 26) });
                    showWidgetAs(node, s.on, { type: "toggle", computeSize: slotSize(node, 26) });
                    showWidgetAs(node, s.str, { type: "number", computeSize: slotSize(node, 26) });
                    node.setDirtyCanvas(true, true);
                }
            });
            btnAddLora.options.serialize = false;

            // ── 移除最后一个 LoRA 按钮 ──
            const btnDelLora = node.addWidget("button", "➖ 移除LoRA槽", "del_lora", () => {
                const visible = node._lora_slots.filter(s => s.visible);
                if (visible.length > 1) {
                    const s = visible[visible.length - 1];
                    s.visible = false;
                    hideWidget(node, s.lora);
                    hideWidget(node, s.on);
                    hideWidget(node, s.str);
                    s.lora.value = "无";
                    s.on.value = false;
                    s.str.value = 1.0;
                    node.setDirtyCanvas(true, true);
                }
            });
            btnDelLora.options.serialize = false;

            // ── 初始刷新 ──
            setTimeout(() => {
                if (wType && wType.value && wType.value.trim()) {
                    refreshLists(wType.value);
                }
            }, 300);

            // ── 最小尺寸 ──
            if (node.size[1] < 480) node.size[1] = 480;
        };
    }
});
