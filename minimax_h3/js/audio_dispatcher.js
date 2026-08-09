/**
 * XB MiniMax 音频调度器 — 照抄SceneDispatcher模式
 */
import { app } from "../../scripts/app.js";

const NODE_TYPE = "XB_MiniMax_AudioDispatcher";

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

app.registerExtension({
    name: "XB_ToolBox.MiniMaxAudioDispatcher",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData?.name !== NODE_TYPE) return;
        const orig = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = orig?.apply(this, arguments);
            setTimeout(() => patchInstance(this), 50);
            return r;
        };
    },
    async loadedGraphNode(node) {
        if (node.type === NODE_TYPE) setTimeout(() => patchInstance(node), 200);
    },
});

function patchInstance(self) {
    if (self.__xb_amd) return;
    self.__xb_amd = true;

    const hasDynamic = (self.inputs || []).some(inp => inp.type === "AUDIO");
    if (!hasDynamic) self.addInput("*", "AUDIO");

    self.stabilizeInputsOutputs = function () {
        const inputs = this.inputs || [];
        const dynIndices = [];
        for (let i = 0; i < inputs.length; i++) {
            if (inputs[i].type === "AUDIO") dynIndices.push(i);
        }

        if (dynIndices.length === 0) {
            this.addInput("*", "AUDIO");
            return true;
        }

        const lastDyn = inputs[dynIndices[dynIndices.length - 1]];
        if (lastDyn?.link != null) {
            this.addInput("*", "AUDIO");
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
