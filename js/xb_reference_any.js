/**
 * XB 引用任意 (Reference Any)
 * =============================
 * 融合 rgthree Fast Muter + Any Switch：
 *   - 动态输入槽，连接后自动扩展
 *   - 输入端口显示上游节点名称 (input.name)
 *   - 下拉菜单选择活跃的上游节点，选项 = 上游节点名
 *   - Python 端 "选择" 下拉框 defaultInput: True → 可直接接受上游 STRING 控制
 *   - 选中 → mode=0（活跃），其余 → mode=2（静音），即时生效无延迟
 *
 * 参照 rgthree-comfy 的 BaseNodeModeChanger + BaseAnyInputConnectedNode 模式。
 */

import { app } from "../../scripts/app.js";

const NODE_TYPE = "XB_ReferenceAny";
const COMBO_WIDGET_NAME = "选择";
const MODE_ACTIVE = 0;
const MODE_MUTE = 2;

// ── helpers ────────────────────────────────────────────────────────────

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

/** Check if an input is the control input (not a dynamic data input). */
function isControlInput(inp) {
    return inp.name === COMBO_WIDGET_NAME;
}

/** Collect all connected upstream node info (skips control input). */
function getLinkedNodes(self) {
    const list = [];
    for (let i = 0; i < (self.inputs?.length || 0); i++) {
        const inp = self.inputs[i];
        if (!inp.link || isControlInput(inp)) continue;
        const up = getUpstreamNode(self, i);
        if (up) list.push({ index: i, node: up, title: up.title || `输入${i + 1}` });
    }
    return list;
}

/**
 * 反向嗅探：顺 "选择" 端口连接找到上游节点，读取其第一个 string 类型 widget 的值。
 * 支持 String/Text 原语节点在编辑期间实时嗅探。
 */
function sniffControlString(self) {
    const input = (self.inputs || []).find(inp => inp.name === COMBO_WIDGET_NAME);
    if (!input?.link) return null;
    const graph = self.graph;
    if (!graph) return null;
    const link = graph.links?.[input.link];
    if (!link) return null;
    const src = graph.getNodeById?.(link.origin_id);
    if (!src) return null;
    // Read widget values from source (works for String/Text primitives)
    for (const w of (src.widgets || [])) {
        if (w.value != null && typeof w.value === 'string' && w.value !== '') return w.value;
    }
    return null;
}

// ── extension ──────────────────────────────────────────────────────────

app.registerExtension({
    name: "XB_ToolBox.ReferenceAny",

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

// ── instance patching ──────────────────────────────────────────────────

function patchInstance(self) {
    if (self.__xb_patched) return;
    self.__xb_patched = true;

    // Replace the Python-created STRING widget with a combo widget (same name, keeps defaultInput port working)
    const strIdx = (self.widgets || []).findIndex(w => w.name === COMBO_WIDGET_NAME && w.type !== "combo");
    if (strIdx >= 0) {
        const oldW = self.widgets[strIdx];
        const savedValue = oldW.value || "";
        self.widgets.splice(strIdx, 1);
        const combo = self.addWidget("combo", COMBO_WIDGET_NAME, savedValue, () => {}, { values: [] });
        // Move it to the same position
        const newIdx = self.widgets.indexOf(combo);
        if (newIdx > strIdx) {
            self.widgets.splice(newIdx, 1);
            self.widgets.splice(strIdx, 0, combo);
        }
    }

    // Ensure at least one dynamic input slot exists (in case FlexibleOptionalInputType starts empty)
    const hasDynamicInput = (self.inputs || []).some(inp => !isControlInput(inp));
    if (!hasDynamicInput) self.addInput("", "*");

    // ---- stabilizeInputsOutputs ----
    self.stabilizeInputsOutputs = function () {
        let ch = false;
        const inputs = this.inputs;

        // Find indices of dynamic inputs (skip control inputs)
        const dynIndices = [];
        for (let i = 0; i < inputs.length; i++) {
            if (!isControlInput(inputs[i])) dynIndices.push(i);
        }

        // If no dynamic inputs at all, add one
        if (dynIndices.length === 0) {
            this.addInput("", "*");
            return true;
        }

        // Last dynamic input connected → add new empty slot
        const lastDyn = inputs[dynIndices[dynIndices.length - 1]];
        if (lastDyn?.link != null) {
            this.addInput("", "*");
            dynIndices.push(inputs.length - 1);
            ch = true;
        }

        // Remove empty dynamic inputs (keep exactly one empty at the end)
        for (let di = dynIndices.length - 2; di >= 0; di--) {
            const idx = dynIndices[di];
            if (inputs[idx].link == null) {
                this.removeInput(idx);
                ch = true;
            } else {
                const up = getUpstreamNode(this, idx);
                const nm = up?.title || "";
                if (inputs[idx].name !== nm) { inputs[idx].name = nm; ch = true; }
            }
        }
        return ch;
    };

    // ---- syncComboOptions (only updates dropdown list, no mode changes) ----
    self.syncComboOptions = function () {
        const combo = (this.widgets || []).find(w => w.name === COMBO_WIDGET_NAME);
        if (!combo) return false;

        const linked = getLinkedNodes(this);
        const newVals = ["全部关闭", ...linked.map(n => n.title)];
        const curVals = combo.options?.values || [];

        // Compare (ignore first "全部关闭" if it was already there)
        const cmp = (a, b) => a.length === b.length && a.every((v, i) => v === b[i]);
        if (!cmp(curVals, newVals)) {
            this.__xb_syncing = true;
            combo.options.values = newVals;
            // Preserve current selection; never auto-override "全部关闭"
            if (!newVals.includes(combo.value)) {
                combo.value = newVals[0];
            }
            this.__xb_syncing = false;
            return true;
        }
        return false;
    };

    // ---- applySelection: set modes based on combo value, returns true if changed ----
    self.applySelection = function (value) {
        if (value === this.__xb_lastSelection) return false;
        this.__xb_lastSelection = value;
        const linked = getLinkedNodes(this);
        let changed = false;
        if (value === "全部关闭") {
            // Mute all upstream nodes, output nothing
            for (const { node } of linked) {
                if (node && node.mode !== MODE_MUTE) { node.mode = MODE_MUTE; changed = true; }
            }
        } else {
            for (const { node } of linked) {
                if (!node) continue;
                const targetMode = (node.title === value) ? MODE_ACTIVE : MODE_MUTE;
                if (node.mode !== targetMode) { node.mode = targetMode; changed = true; }
            }
        }
        if (changed) this.graph?.setDirtyCanvas?.(true, true);
        return changed;
    };

    // ---- setupComboCallback (fires instantly on user click) ----
    function setupComboCallback() {
        const combo = (self.widgets || []).find(w => w.name === COMBO_WIDGET_NAME);
        if (!combo || combo.__xb_cb_set) return;
        combo.__xb_cb_set = true;

        combo.callback = function (value) {
            if (self.__xb_syncing) return;  // skip if programmatic update
            self.applySelection(value);
        };
    }

    // ---- doStablization (rgthree pattern) ----
    self.doStablization = function () {
        if (!this.graph || this.__xb_removed) return;
        let dirty = false;
        try {
            dirty = this.stabilizeInputsOutputs() || dirty;
            dirty = this.syncComboOptions() || dirty;

            const combo = (this.widgets || []).find(w => w.name === COMBO_WIDGET_NAME);
            if (!combo) return;

            // 检查 "选择" 端口是否被接入
            const selectInput = (this.inputs || []).find(inp => inp.name === COMBO_WIDGET_NAME);
            const isConnected = selectInput?.link != null;

            if (isConnected) {
                // 有上游接入 → 反向嗅探，匹配则激活，不匹配则"全部关闭"
                const sniffed = sniffControlString(this);
                if (sniffed !== this.__xb_lastSniffed) {
                    this.__xb_lastSniffed = sniffed;
                    if (sniffed != null) {
                        const options = combo.options?.values || [];
                        let bestMatch = null;
                        const lowerInput = sniffed.toLowerCase();
                        for (const opt of options) {
                            if (lowerInput.includes(opt.toLowerCase())) {
                                if (!bestMatch || opt.length > bestMatch.length) {
                                    bestMatch = opt;
                                }
                            }
                        }
                        // 匹配成功 → 激活对应选项；匹配失败 → 回退到"全部关闭"
                        const target = bestMatch || "全部关闭";
                        this.__xb_syncing = true;
                        combo.value = target;
                        this.__xb_syncing = false;
                        dirty = this.applySelection(target) || dirty;
                    } else {
                        // 嗅探不到值 → 默认"全部关闭"
                        dirty = this.applySelection("全部关闭") || dirty;
                    }
                }
            } else {
                // 无上游接入 → 用下拉菜单手动选择的值
                if (combo.value !== this.__xb_lastSelection) {
                    dirty = this.applySelection(combo.value) || dirty;
                }
                // 清除嗅探缓存
                this.__xb_lastSniffed = null;
            }
        } catch (e) { /* ignore */ }
        if (dirty) this.graph.setDirtyCanvas(true, true);
        if (!this.__xb_removed) {
            this._xbTimer = setTimeout(() => {
                this._xbTimer = null;
                this.doStablization?.();
            }, 300);
        }
    };

    // ---- scheduleStabilizeWidgets ----
    self.scheduleStabilizeWidgets = function (ms = 80) {
        if (this._xbScheduled) return;
        this._xbScheduled = true;
        if (this._xbTimer) clearTimeout(this._xbTimer);
        this._xbTimer = setTimeout(() => {
            this._xbScheduled = false;
            this._xbTimer = null;
            this.doStablization?.();
        }, ms);
    };

    // ---- hooks ----
    const origConn = self.onConnectionsChange;
    self.onConnectionsChange = function () {
        if (origConn) origConn.apply(this, arguments);
        this.scheduleStabilizeWidgets?.(64);
    };

    const origRem = self.onRemoved;
    self.onRemoved = function () {
        this.__xb_removed = true;
        if (this._xbTimer) { clearTimeout(this._xbTimer); this._xbTimer = null; }
        if (origRem) origRem.apply(this, arguments);
    };

    // ---- kick off ----
    setTimeout(() => {
        setupComboCallback();
        // Apply initial selection (defaults to "全部关闭" → all muted)
        const combo = (self.widgets || []).find(w => w.name === COMBO_WIDGET_NAME);
        if (combo) self.applySelection(combo.value || "全部关闭");
        self.doStablization?.();
    }, 300);
}
