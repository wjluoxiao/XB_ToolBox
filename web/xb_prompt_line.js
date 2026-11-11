/**
 * XB 提示词多行（XB_PromptLine）
 * ===========================================
 * 独立实现：给节点加一个「⬇ 取下游 COMBO 下拉值」按钮。
 * 连线到下游节点的 combo 输入后，点击即可把该下拉的所有选项按行填入提示词框，
 * 便于直接按行编辑/筛选（等价于 Easy-Use 提示词行的 get values from COMBO link）。
 */

import { app } from "../../scripts/app.js";

const NODE_TYPE = "XB_PromptLine";
const BTN_LABEL = "⬇ 取下游 COMBO 下拉值";

function notify(msg, type = "info") {
    try {
        if (app?.extensionManager?.toast?.add) {
            app.extensionManager.toast.add({ severity: type, summary: "📝 提示词多行", detail: msg, life: 3000 });
            return;
        }
    } catch (_) { /* ignore */ }
    console.log(`[XB 提示词多行] ${msg}`);
}

function widgetValue(w) {
    if (!w) return undefined;
    return w.value !== undefined ? w.value : w._state?.value;
}

function setWidgetValue(w, value) {
    if (!w) return;
    try { w.value = value; } catch (_) { /* ignore */ }
    try { if (w._state) w._state.value = value; } catch (_) { /* ignore */ }
    try { w.callback?.(value); } catch (_) { /* ignore */ }
    try { w._node?.setDirtyCanvas?.(true, true); } catch (_) { /* ignore */ }
}

/** 从本节点 COMBO 输出（端口 1）顺着连线找到下游节点里对应的 combo 控件 */
function findComboWidgetFromLink(node) {
    const graph = node.graph || app.graph;
    const out = node.outputs?.[1];
    const linkId = Array.isArray(out?.links) ? out.links[0] : null;
    if (linkId == null) return null;

    const link = graph?.links?.[linkId];
    if (!link) return null;

    const target = graph.getNodeById?.(link.target_id) || graph._nodes?.find((n) => n.id === link.target_id);
    if (!target) return null;

    const idx = link.target_slot;
    const input = target.inputs?.[idx];
    const names = [];
    if (input?.widget?.name) names.push(input.widget.name);
    if (input?.name) names.push(input.name);

    const widgets = target.widgets || [];
    for (const name of names) {
        const w = widgets.find((cate) => cate?.name === name);
        if (w) return w;
    }
    return null;
}

function comboValues(w) {
    const values = w?.options?.values;
    if (Array.isArray(values)) return values;
    if (typeof values === "function") {
        try {
            const r = values(w);
            if (Array.isArray(r)) return r;
        } catch (_) { /* ignore */ }
    }
    return null;
}

app.registerExtension({
    name: "XB_ToolBox.PromptLine",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData?.name !== NODE_TYPE) return;

        const origOnNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = origOnNodeCreated?.apply(this, arguments);
            const self = this;

            this.addWidget("button", BTN_LABEL, null, () => {
                const widget = findComboWidgetFromLink(self);
                if (!widget) {
                    notify("COMBO 输出未连接到带下拉控件的节点", "warn");
                    return;
                }
                const values = comboValues(widget);
                if (!values || !values.length) {
                    notify(`上游控件「${widget.name}」没有可选下拉值`, "warn");
                    return;
                }
                const promptWidget = (self.widgets || []).find((w) => w?.name === "prompt");
                if (!promptWidget) {
                    notify("未找到提示词输入框", "error");
                    return;
                }
                setWidgetValue(promptWidget, values.join("\n"));
                notify(`已写入 ${values.length} 行（来自「${widget.name}」）`, "success");
            }, { serialize: false });

            return r;
        };
    },
});
