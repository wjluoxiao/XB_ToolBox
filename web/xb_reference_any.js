/**
 * XB 引用任意 (Reference Any)
 * =============================
 *   - 动态输入槽：接线自动扩展，端口名显示上游节点名
 *   - 节点上一个正常的下拉框「选择」（原生 combo widget），列出当前已接入的上游节点，
 *     选中哪个就只激活它，其余静音；选「全部关闭」= 上游全部静音，本节点输出空
 *   - 下拉框左侧自带输入端口（widget input），类型放宽成 * 所以可以随便接线
 *   - 打包进子图（子工作流）后，把「选择」提升为子图输入，子图节点表面就是这个下拉框；
 *     在子图节点上换选哪一项，内部就切到哪一个（外层值是准，内层同步）
 *   - 上游接进来的字符串不会再改写下拉框的选中项（不是字符串控制）
 *
 * 实现要点（Nodes 2.0 / 经典模式通用）：
 *   (1) 在 beforeRegisterNodeDef 里把「选择」从 STRING 改成 COMBO，
 *       这样前端会直接建出原生下拉框（不是文本框），左侧也自带可接线端口。
 *   (2) Nodes 2.0 的节点组件在创建时就把 widget.options 快照进 store，
 *       之后改 options.values 不会重渲染。所以候选值必须是 Vue 的响应式数组，
 *       并在节点创建（onNodeCreated）时挂上去，后续用 splice 原地更新才会实时刷新。
 *       响应式函数从已加载的 vendor-vue-core 模块里按行为探测取得（不写死哈希文件名）。
 */

import { app } from "../../scripts/app.js";

const NODE_TYPE = "XB_ReferenceAny";
const WNAME = "选择";
const ALL_OFF = "全部关闭";
const MODE_ACTIVE = 0;
const MODE_MUTE = 2;

// ── Vue 响应式数组（拿不到就退化成普通数组：只是不会实时刷新，功能不受影响）──
let xbReactive = null;
let xbReactiveReady = null;

function loadReactive() {
    if (xbReactiveReady) return xbReactiveReady;
    xbReactiveReady = (async () => {
        try {
            const urls = performance.getEntriesByType("resource").map((e) => e.name);
            const url = urls.find((n) => /vendor-vue-core-.*\.js$/.test(n));
            if (!url) return null;
            const mod = await import(url);
            for (const k of Object.keys(mod)) {
                const f = mod[k];
                if (typeof f !== "function") continue;
                try {
                    const probe = { __xbProbe: 1 };
                    const r = f(probe);
                    if (r && r.__v_isReactive === true && r.__v_raw === probe && r.__v_isShallow !== true) {
                        xbReactive = f;
                        break;
                    }
                } catch (_) { /* 不是响应式函数 */ }
            }
        } catch (_) { /* ignore */ }
        return xbReactive;
    })();
    return xbReactiveReady;
}
loadReactive();

const makeReactive = (arr) => (xbReactive ? xbReactive(arr) : arr);

// ── helpers ────────────────────────────────────────────────────────────

/** 顺着连线（含 Reroute）找真正的上游节点 */
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
        if (String(src.type || "").includes("Reroute") && !seen.has(src.id)) {
            seen.add(src.id);
            node = src;
            slot = 0;
            continue;
        }
        return src;
    }
    return null;
}

/** 「选择」是控制端口（widget 自己占的槽位） */
function isValuePort(inp) {
    return !inp || inp.widget || inp.name === WNAME;
}

/** 所有已连线的上游节点：[{ index, node, title }] */
function getLinkedNodes(self) {
    const list = [];
    for (let i = 0; i < (self.inputs?.length || 0); i++) {
        const inp = self.inputs[i];
        if (!inp || inp.link == null || isValuePort(inp)) continue;
        const up = getUpstreamNode(self, i);
        if (up) list.push({ index: i, node: up, title: up.title || up.type || `输入${i + 1}` });
    }
    return list;
}

/** 数据槽（排除「选择」控制槽与 widget 槽） */
function dataSlots(self) {
    return (self.inputs || [])
        .map((inp, i) => ({ inp, i }))
        .filter((x) => x.inp && !isValuePort(x.inp));
}

/** 把「选择」声明成下拉框（必须在节点类型注册时就改，否则前端建出来的是文本框） */
function forceComboDef(nodeData) {
    const spec = nodeData?.input?.required?.[WNAME] || nodeData?.input?.optional?.[WNAME];
    if (!Array.isArray(spec)) return;
    spec[0] = [ALL_OFF];
    const opts = spec[1] && typeof spec[1] === "object" ? spec[1] : {};
    opts.default = ALL_OFF;
    spec[1] = opts;
}

/** 打包进子图后，外层子图节点上的「选择」是候选值的副本，这里把它们同步过去 */
function propagateToSubgraphNodes(self, names) {
    const inner = self.graph;
    if (!inner) return;
    const root = inner.rootGraph || app.rootGraph;
    if (!root || root === inner) return;
    const visit = (graph) => {
        for (const n of graph._nodes || []) {
            const sub = n.subgraph;
            if (!sub) continue;
            if (sub === inner) {
                const w = (n.widgets || []).find((x) => x.name === WNAME);
                const arr = w?.options?.values;
                if (arr) {
                    const same = arr.length === names.length && names.every((v, i) => arr[i] === v);
                    if (!same) arr.splice(0, arr.length, ...names);
                    if (!names.includes(String(w.value ?? ALL_OFF))) w.value = ALL_OFF;
                }
            }
            visit(sub);
        }
    };
    visit(root);
}

/** 节点刚创建时把候选值换成响应式数组（Nodes 2.0 的 store 会快照它） */
function initWidgetValues(node) {
    if (node.__xbValues) return;
    const w = (node.widgets || []).find((x) => x.name === WNAME);
    if (!w) return;
    const arr = makeReactive([ALL_OFF]);
    w.options = w.options || {};
    w.options.values = arr;
    node.__xbValues = arr;
    if (!arr.includes(w.value)) w.value = ALL_OFF;
}

// ── extension ──────────────────────────────────────────────────────────

app.registerExtension({
    name: "XB_ToolBox.ReferenceAny",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData?.name !== NODE_TYPE) return;
        await loadReactive();          // 必须在建节点前拿到响应式函数
        forceComboDef(nodeData);
        const orig = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = orig?.apply(this, arguments);
            initWidgetValues(this);
            setTimeout(() => patchInstance(this), 0);
            return r;
        };
    },

    async loadedGraphNode(node) {
        if (node?.type === NODE_TYPE) setTimeout(() => patchInstance(node), 150);
    },
});

// ── instance patching ──────────────────────────────────────────────────

function patchInstance(self) {
    if (self.__xbRefReady) return;
    self.__xbRefReady = true;

    const valueWidget = () => (self.widgets || []).find((w) => w.name === WNAME);
    initWidgetValues(self);

    // combo 的端口默认类型是 COMBO，别的类型接不进来；
    // 改成 * 才能像普通输入端口那样随便接线（是否生效只看下拉框的手动选择）
    const widenValueSlot = () => {
        const inp = (this?.inputs || self.inputs || []).find((i) => i?.widget && i.name === WNAME);
        if (inp && inp.type !== "*") { inp.type = "*"; return true; }
        return false;
    };
    widenValueSlot();

    if (!dataSlots(self).length) self.addInput("", "*");

    // ── 端口维护：接线扩展 / 收空槽 / 端口名跟随上游 ──────────────────
    self.stabilizeInputsOutputs = function () {
        let changed = false;
        let slots = dataSlots(this);
        if (!slots.length) {
            this.addInput("", "*");
            return true;
        }
        const last = slots[slots.length - 1];
        if (last.inp.link != null) {
            this.addInput("", "*");
            changed = true;
            slots = dataSlots(this);
        }
        for (let k = slots.length - 2; k >= 0; k--) {
            const { inp, i } = slots[k];
            if (inp && inp.link == null) {
                this.removeInput(i);
                changed = true;
            }
        }
        for (const { inp, i } of dataSlots(this)) {
            if (inp.link == null) {
                if (inp.name !== "") { inp.name = ""; inp.label = ""; changed = true; }
                continue;
            }
            const up = getUpstreamNode(this, i);
            const nm = up?.title || up?.type || "";
            if (inp.name !== nm) { inp.name = nm; changed = true; }
            if ((inp.label || "") !== nm) { inp.label = nm; changed = true; }
        }
        return changed;
    };

    // ── 候选值：只认连线（不看 mode，全静音时也照常列出）───────────────
    self.syncOptions = function () {
        const w = valueWidget();
        const arr = this.__xbValues;
        if (!w || !arr) return false;
        const linked = getLinkedNodes(this);
        const names = [ALL_OFF];
        for (const { title } of linked) {
            if (title && !names.includes(title)) names.push(title);
        }
        const same = arr.length === names.length && names.every((v, i) => arr[i] === v);
        if (!same) arr.splice(0, arr.length, ...names);

        const key = names.join("\u0001");
        if (this.__xbPropKey !== key) {
            this.__xbPropKey = key;
            propagateToSubgraphNodes(this, names);
        }

        const cur = String(w.value ?? ALL_OFF);
        if (!names.includes(cur)) {
            const still = linked.find((x) => x.node?.id === this.__xbSelectedId);
            const keep = still ? still.title : ALL_OFF;
            if (w.value !== keep) { w.value = keep; w.callback?.(keep); }
        }
        return !same;
    };

    // ── 子图：外层子图节点上的「选择」就是这个节点的选择 ────────────────
    const ownerWidgets = () => {
        const inner = self.graph;
        const root = inner?.rootGraph || app.rootGraph;
        const out = [];
        if (!inner || !root || root === inner) return out;
        const visit = (g) => {
            for (const n of g._nodes || []) {
                const sub = n.subgraph;
                if (!sub) continue;
                if (sub === inner) {
                    const w = (n.widgets || []).find((x) => x.name === WNAME);
                    if (w) out.push(w);
                }
                visit(sub);
            }
        };
        visit(root);
        return out;
    };

    // 被打包进子图时以外层的值为准；外层值不合法（比如刚删了上游）才用自己的
    const effectiveValue = () => {
        const own = String(valueWidget()?.value ?? ALL_OFF);
        const names = Array.from(self.__xbValues || []);
        for (const w of ownerWidgets()) {
            const v = String(w.value ?? ALL_OFF);
            if (names.includes(v)) return v;
        }
        return own;
    };

    // ── 应用选择：选中的激活，其余静音；「全部关闭」= 全静音 ────────────
    self.applySelection = function (value) {
        const linked = getLinkedNodes(this);
        let targetId = null;
        if (value && value !== ALL_OFF) {
            const hit = linked.find((x) => x.title === value);
            if (hit) targetId = hit.node.id;
        }
        this.__xbSelectedId = targetId;
        let changed = false;
        for (const { node } of linked) {
            if (!node) continue;
            const want = (node.id === targetId) ? MODE_ACTIVE : MODE_MUTE;
            if (node.mode !== want) { node.mode = want; changed = true; }
        }
        return changed;
    };

    // 手动改下拉框 → 立即生效（在子图里也要把外层子图节点的值同步过去）
    const w0 = valueWidget();
    if (w0 && !w0.__xbComboHooked) {
        w0.__xbComboHooked = true;
        const orig = w0.callback;
        w0.callback = function (v) {
            const r = orig?.apply(this, arguments);
            const val = String(v ?? ALL_OFF);
            self.__xbAppliedValue = val;
            self.applySelection?.(val);
            for (const w of ownerWidgets()) {
                if (String(w.value) !== val) w.value = val;
            }
            self.graph?.setDirtyCanvas?.(true, true);
            return r;
        };
    }

    // ── 周期稳定 ──────────────────────────────────────────────────────
    self.doStablization = function () {
        if (!this.graph || this.__xbRefRemoved) return;
        let dirty = false;
        try {
            dirty = widenValueSlot.call(this) || dirty;
            dirty = this.stabilizeInputsOutputs() || dirty;
            dirty = this.syncOptions() || dirty;
            const cur = effectiveValue();
            if (cur !== this.__xbAppliedValue) {
                this.__xbAppliedValue = cur;
                dirty = this.applySelection(cur) || dirty;
            }
        } catch (_) { /* ignore */ }
        if (dirty) this.graph.setDirtyCanvas(true, true);
        if (!this.__xbRefRemoved) {
            this._xbTimer = setTimeout(() => {
                this._xbTimer = null;
                this.doStablization?.();
            }, 300);
        }
    };

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

    // ── hooks ─────────────────────────────────────────────────────────
    const origConn = self.onConnectionsChange;
    self.onConnectionsChange = function () {
        if (origConn) origConn.apply(this, arguments);
        this.scheduleStabilizeWidgets?.(64);
    };

    const origConfigure = self.onConfigure;
    self.onConfigure = function () {
        const r = origConfigure?.apply(this, arguments);
        this.scheduleStabilizeWidgets?.(64);
        return r;
    };

    const origRem = self.onRemoved;
    self.onRemoved = function () {
        this.__xbRefRemoved = true;
        if (this._xbTimer) { clearTimeout(this._xbTimer); this._xbTimer = null; }
        if (origRem) origRem.apply(this, arguments);
    };

    // ── 启动 ──────────────────────────────────────────────────────────
    setTimeout(() => {
        // 首次不预设已应用值，让第一轮稳定逻辑把选中状态强制落一次
        self.doStablization?.();
    }, 200);
}
