/**
 * XB-llama 分镜词处理器 — ComfyUI 前端扩展
 * ============================================
 * 1. 抽卡开启 → mute 上游节点 (text_input / list_input 源头)
 * 2. 穿透 OFF → 恢复所有上游节点
 * 3. text_input 文本显示 → 完全复刻 Show Text (ComfyUI-Custom-Scripts)
 */

import { app } from "../../scripts/app.js";
import { ComfyWidgets } from "../../scripts/widgets.js";

const NODE_TYPE = "XB_llamaStoryboardProcessor";
const MODE_ACTIVE = 0;
const MODE_MUTE   = 2;

// ── 上游节点收集 & mute/恢复 ──

function collectUpstreamNodes(node) {
    const graph = node.graph ?? app.graph;
    if (!graph) return [];
    const allNodes = graph._nodes ?? graph.nodes ?? [];
    const links    = graph.links ?? graph._links;
    const seen     = new Set();

    for (const input of (node.inputs || [])) {
        if (input.link == null) continue;
        const link = links?.[input.link] ?? links?.get?.(input.link);
        if (!link || link.origin_id == null) continue;
        const src = allNodes.find((n) => n.id === link.origin_id);
        if (src && !seen.has(src.id)) seen.add(src.id);
    }
    return [...seen].map((id) => allNodes.find((n) => n.id === id)).filter(Boolean);
}

function applyUpstreamMode(node, drawMode) {
    const upstream = collectUpstreamNodes(node);
    const targetMode = drawMode ? MODE_MUTE : MODE_ACTIVE;
    let changed = false;
    for (const u of upstream) {
        if (u.mode !== targetMode) { u.mode = targetMode; changed = true; }
    }
    if (changed) (node.graph ?? app.graph)?.setDirtyCanvas?.(true, true);
}

// ── Show Text  文本显示 (完全复刻 ComfyUI-Custom-Scripts showText.js) ──

function populateShowText(node, text) {
    if (node.widgets) {
        // 清理旧的 text_ 前缀 widget
        for (let i = node.widgets.length - 1; i >= 0; i--) {
            if (node.widgets[i].name?.startsWith?.("text_")) {
                node.widgets[i].onRemove?.();
                node.widgets.splice(i, 1);
            }
        }
    }

    const v = [...text];
    if (!v[0]) v.shift();

    for (let list of v) {
        if (!(list instanceof Array)) list = [list];
        for (const l of list) {
            const w = ComfyWidgets["STRING"](
                node, "text_" + (node.widgets?.length ?? 0),
                ["STRING", { multiline: true }], app
            ).widget;
            w.inputEl.readOnly = true;
            w.inputEl.style.opacity = 0.6;
            w.value = l;
        }
    }

    requestAnimationFrame(() => {
        const sz = node.computeSize();
        if (sz[0] < node.size[0]) sz[0] = node.size[0];
        if (sz[1] < node.size[1]) sz[1] = node.size[1];
        node.onResize?.(sz);
        app.graph.setDirtyCanvas(true, false);
    });
}

// ── 注册 ──

app.registerExtension({
    name: "XB_ToolBox.StoryboardProcessor",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_TYPE) return;

        const origCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            origCreated?.apply(this, arguments);
            const self = this;

            // draw_mode 切换 → mute / 恢复上游
            const wMode = (self.widgets || []).find((w) => w.name === "draw_mode");
            if (wMode) {
                const origCb = wMode.callback;
                wMode.callback = function (value) {
                    origCb?.apply?.(this, arguments);
                    applyUpstreamMode(self, value);
                };
            }

            // 连线变化时重新评估
            const origConn = self.onConnectionsChange;
            self.onConnectionsChange = function (type, index, slot, connected, link_info, ...rest) {
                origConn?.apply?.(this, [type, index, slot, connected, link_info, ...rest]);
                if (wMode) applyUpstreamMode(self, wMode.value);
            };
        };

        // ── Show Text : onExecuted 接收 ui.text 并渲染 widget ──
        const origExec = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            origExec?.apply?.(this, arguments);
            populateShowText(this, message.text);
        };
    },
});
