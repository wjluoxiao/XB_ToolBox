/**
 * XB 角色场景调度器 — ComfyUI 前端扩展
 * ============================================
 * 动态输入槽管理: 接入图片后自动扩展空槽位
 *   背景A → 新增空槽 "背景B"
 *   角色A → 新增空槽 "角色B"
 */

import { app } from "../../scripts/app.js";
import { ComfyWidgets } from "../../scripts/widgets.js";

const NODE_TYPE = "XB_RoleSceneDispatcher";
const MODE_ACTIVE = 0;
const MODE_MUTE   = 2;

// mute 仅 text_input 的上游节点, 图片输入不受影响
function muteTextUpstream(node, drawMode) {
    const inp = (node.inputs || []).find(i => i.type !== "IMAGE" && i.name !== "draw_mode");
    if (!inp?.link) return;
    const graph = node.graph ?? app.graph;
    if (!graph) return;
    const link = graph.links?.[inp.link] ?? graph._links?.get?.(inp.link);
    if (!link) return;
    const src = graph.getNodeById?.(link.origin_id);
    if (!src) return;
    const target = drawMode ? MODE_MUTE : MODE_ACTIVE;
    if (src.mode !== target) {
        src.mode = target;
        graph.setDirtyCanvas?.(true, true);
    }
}

app.registerExtension({
    name: "XB_ToolBox.RoleSceneDispatcher",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData?.name !== NODE_TYPE) return;

        const orig = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = orig?.apply(this, arguments);
            setTimeout(() => patchInstance(this), 50);
            return r;
        };

        // Show Text 显示
        const origExec = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            origExec?.apply?.(this, arguments);
            if (message.text) {
                if (this.widgets) {
                    for (let i = this.widgets.length - 1; i >= 0; i--) {
                        if (this.widgets[i].name?.startsWith?.("text_")) {
                            this.widgets[i].onRemove?.();
                            this.widgets.splice(i, 1);
                        }
                    }
                }
                const v = [...message.text];
                if (!v[0]) v.shift();
                for (let list of v) {
                    if (!(list instanceof Array)) list = [list];
                    for (const l of list) {
                        const w = ComfyWidgets["STRING"](this, "text_" + (this.widgets?.length ?? 0), ["STRING", { multiline: true }], app).widget;
                        w.inputEl.readOnly = true;
                        w.inputEl.style.opacity = 0.6;
                        w.value = l;
                    }
                }
                requestAnimationFrame(() => {
                    const sz = this.computeSize();
                    if (sz[0] < this.size[0]) sz[0] = this.size[0];
                    if (sz[1] < this.size[1]) sz[1] = this.size[1];
                    this.onResize?.(sz);
                    app.graph.setDirtyCanvas(true, false);
                });
            }
        };
    },
    async loadedGraphNode(node) {
        if (node.type === NODE_TYPE) {
            setTimeout(() => {
                patchInstance(node);
                const wMode = (node.widgets || []).find(w => w.name === "draw_mode");
                if (wMode) muteTextUpstream(node, wMode.value);
            }, 300);
        }
    },
});

function patchInstance(self) {
    if (self.__xb_disp) return;
    self.__xb_disp = true;

    // 【修复1】按 type==="IMAGE" 过滤，免疫汉化插件改 name
    const hasDynamic = (self.inputs || []).some(inp => inp.type === "IMAGE");

    // 【修复2】用 "*" 替代 ""，新版 LiteGraph 不隐藏非空名槽
    if (!hasDynamic) self.addInput("*", "IMAGE");

    // draw_mode → mute text_input upstream only
    const wMode = (self.widgets || []).find(w => w.name === "draw_mode");
    if (wMode) {
        const origCb = wMode.callback;
        wMode.callback = function (value) {
            origCb?.apply?.(this, arguments);
            muteTextUpstream(self, value);
        };
    }

    self.stabilizeInputsOutputs = function () {
        const inputs = this.inputs || [];
        const dynIndices = [];
        for (let i = 0; i < inputs.length; i++) {
            if (inputs[i].type === "IMAGE") dynIndices.push(i);
        }

        if (dynIndices.length === 0) {
            this.addInput("*", "IMAGE");
            return true;
        }

        const lastDyn = inputs[dynIndices[dynIndices.length - 1]];
        if (lastDyn?.link != null) {
            this.addInput("*", "IMAGE");
            dynIndices.push(inputs.length - 1);
        }

        let ch = false;
        for (let di = dynIndices.length - 1; di >= 0; di--) {
            const idx = dynIndices[di];
            const inp = inputs[idx];
            if (inp.link == null && di < dynIndices.length - 1) {
                this.removeInput(idx);
                ch = true;
            } else if (inp.link != null) {
                const src = getUpstreamNode(this, idx);
                const nm = src?.title || "*";
                if (inp.name !== nm) { inp.name = nm; ch = true; }
            }
        }
        return ch;
    };

    const origConn = self.onConnectionsChange;
    self.onConnectionsChange = function (type, index, slot, connected, link_info, ...rest) {
        origConn?.apply?.(this, [type, index, slot, connected, link_info, ...rest]);
        const w = (this.widgets || []).find(wd => wd.name === "draw_mode");
        if (w) muteTextUpstream(this, w.value);
        this.scheduleStabilize?.();
    };

    self.scheduleStabilize = function (ms = 80) {
        if (this._xbSched) return;
        this._xbSched = true;
        if (this._xbTimer) clearTimeout(this._xbTimer);
        this._xbTimer = setTimeout(() => {
            this._xbSched = false;
            this._xbTimer = null;
            this.stabilizeInputsOutputs?.();
            this.graph?.setDirtyCanvas?.(true, true);
        }, ms);
    };
}

function getUpstreamNode(self, inputIndex) {
    const graph = self.graph;
    if (!graph) return null;
    let node = self;
    let slot = inputIndex;
    const seen = new Set();
    for (let i = 0; i < 20; i++) {
        const inp = node.inputs?.[slot];
        if (inp?.link == null) return null;
        const link = graph.links?.[inp.link];
        if (!link) return null;
        const src = graph.getNodeById?.(link.origin_id);
        if (!src) return null;
        if (src.type?.includes?.("Reroute") && !seen.has(src.id)) {
            seen.add(src.id);
            node = src;
            slot = 0;
            continue;
        }
        return src;
    }
    return null;
}
