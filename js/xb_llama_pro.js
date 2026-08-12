import { app } from "../../scripts/app.js";

// ============================================================
// XB_LlamaModelLoaderPro — 高级选项折叠 UI
//   完全参照 MiniMax H3 Easy 的 widget.type="hidden" 模式
// ============================================================

const NODE_TYPE = "XB_LlamaModelLoaderPro";

const ADVANCED_NAMES = new Set([
    "n_ctx", "vram_limit", "image_min_tokens", "image_max_tokens",
    "max_tokens", "top_k", "top_p", "min_p", "typical_p",
    "temperature", "repeat_penalty", "frequency_penalty", "present_penalty",
    "mirostat_mode", "mirostat_eta", "mirostat_tau", "state_uid",
]);

// ── 工具 ──

function asBoolean(v) { return v === true || v === "true" || Number(v) === 1; }

function getWidget(node, name) { return node.widgets?.find(w => w.name === name); }

function setWidgetOption(w, key, val) {
    if (!w.options) w.options = {};
    w.options[key] = val;
}

// ── 测量单个 widget 高度 ──

function getWidgetRowHeight(node, widget) {
    if (!widget) return 26;
    if (widget.__xbRowHeight > 0) return widget.__xbRowHeight;
    const fn = widget.computeSize;
    try {
        const w = Math.max(80, Number(node?.size?.[0]) || 220);
        const sz = fn?.call(widget, w);
        const h = Number(sz?.[1]);
        if (h > 0) { widget.__xbRowHeight = h; return h; }
    } catch (_) {}
    const h = Number(widget.computedHeight) > 0 ? Number(widget.computedHeight) : 26;
    widget.__xbRowHeight = h;
    return h;
}

// ── 隐藏 / 显示 ──

function hideConditionalWidget(widget) {
    if (!widget) return false;
    if (widget.type === "hidden" && widget.hidden === true) return false;
    if (!Object.prototype.hasOwnProperty.call(widget, "__xbOrigType")) {
        widget.__xbOrigType = widget.type;
        widget.__xbOrigComputeSize = widget.computeSize;
        widget.__xbOrigHidden = widget.hidden;
        widget.__xbOrigComputedHeight = widget.computedHeight;
        widget.__xbOrigOptionsHidden = widget.options?.hidden;
        widget.__xbOrigOptionsCanvasOnly = widget.options?.canvasOnly;
    }
    widget.hidden = true;
    if (widget.inputEl) widget.inputEl.style.display = "none";
    if (widget.element) widget.element.style.display = "none";
    widget.type = "hidden";
    widget.computeSize = () => [0, -4];
    widget.computedHeight = 0;
    setWidgetOption(widget, "hidden", true);
    setWidgetOption(widget, "canvasOnly", true);
    if (widget._state) {
        widget._state.hidden = true;
        widget._state.type = "hidden";
        widget._state.computedHeight = 0;
    }
    return true;
}

function showConditionalWidget(widget) {
    if (!widget) return false;
    if (widget.type !== "hidden") return false;
    if (!Object.prototype.hasOwnProperty.call(widget, "__xbOrigType")) return false;

    widget.hidden = widget.__xbOrigHidden ?? false;
    if (widget.inputEl) widget.inputEl.style.display = "";
    if (widget.element) widget.element.style.display = "";
    widget.type = widget.__xbOrigType || "INT";
    if (widget.__xbOrigComputeSize) widget.computeSize = widget.__xbOrigComputeSize;
    else delete widget.computeSize;
    widget.computedHeight = widget.__xbOrigComputedHeight;
    setWidgetOption(widget, "hidden", widget.__xbOrigOptionsHidden ?? false);
    setWidgetOption(widget, "canvasOnly", widget.__xbOrigOptionsCanvasOnly ?? false);
    if (widget._state) {
        widget._state.hidden = widget.hidden;
        widget._state.type = widget.type;
        if (widget.__xbOrigComputedHeight !== undefined) widget._state.computedHeight = widget.__xbOrigComputedHeight;
        else delete widget._state.computedHeight;
    }

    delete widget.__xbOrigType;
    delete widget.__xbOrigComputeSize;
    delete widget.__xbOrigHidden;
    delete widget.__xbOrigComputedHeight;
    delete widget.__xbOrigOptionsHidden;
    delete widget.__xbOrigOptionsCanvasOnly;
    return true;
}

// ── 调整节点高度 (像素偏移) ──

function adjustNodeHeight(node, delta) {
    if (!node?.size || !delta) return;
    const w = Number(node.size[0]) || 0;
    const h = Math.max(0, Number(node.size[1]) + delta);
    node.setSize?.([w, h]);
    if (Array.isArray(node.size)) { node.size[0] = w; node.size[1] = h; }
}

// ── 批量切换可见性 ──

function syncAdvancedWidgets(node, { adjustHeight = true } = {}) {
    const show = asBoolean(getWidget(node, "advanced_settings")?.value);
    let delta = 0;

    for (const w of node.widgets || []) {
        if (!ADVANCED_NAMES.has(w.name)) continue;
        const rowH = getWidgetRowHeight(node, w);
        if (show) {
            if (showConditionalWidget(w)) delta += rowH + 4;
        } else {
            if (hideConditionalWidget(w)) delta -= rowH + 4;
        }
    }

    if (adjustHeight && delta !== 0) {
        adjustNodeHeight(node, delta);
    }

    node._widgetSlotsDirty = true;
    node.setDirtyCanvas?.(true, true);
    node.graph?.setDirtyCanvas?.(true, true);
}

// ── 注册扩展 ──

app.registerExtension({
    name: "XB_ToolBox.LlamaModelLoaderPro",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData?.name !== NODE_TYPE) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            const self = this;

            const wToggle = getWidget(self, "advanced_settings");
            if (!wToggle) return result;

            // 等 ComfyUI 设置好 node.size 后再做首次折叠 (adjustHeight=true)
            requestAnimationFrame(() => {
                syncAdvancedWidgets(self, { adjustHeight: true });
            });

            // 用户点击 toggle
            const origCb = wToggle.callback;
            wToggle.callback = function (v) {
                if (origCb) origCb.apply(this, arguments);
                syncAdvancedWidgets(self, { adjustHeight: true });
            };

            // 加载工作流: ComfyUI 的 configure 已恢复 node.size，只需同步可见性
            const onConfigure = self.onConfigure;
            self.onConfigure = function (info) {
                const resultCfg = onConfigure?.apply(this, arguments);
                // ComfyUI 的 configure 已根据 workflow 恢复了 node.size
                // 这里只需同步 widget 可见性，不再动高度
                requestAnimationFrame(() => {
                    syncAdvancedWidgets(self, { adjustHeight: false });
                });
                return resultCfg;
            };

            return result;
        };
    },
});



