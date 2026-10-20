/**
 * XB 引用任意 (Reference Any)
 * =============================
 * 融合 rgthree Fast Muter + Any Switch：
 *   - 动态输入槽：接线自动扩展，端口名显示上游节点名
 *   - 面板上一个下拉框「选择」：选中哪个上游节点就只激活它，其余静音；
 *     选「全部关闭」= 上游全部静音，本节点输出空
 *   - 「选择」端口还能接 STRING 上游来外部驱动选择（Python 端 defaultInput）
 *
 * ⚠️ 为什么下拉不用 LiteGraph 的 combo widget：
 *    Nodes 2.0（Vue）在节点创建时就把 widget.options 快照进 store，之后 JS 改
 *    options.values 不会同步过去，下拉里会一直显示「未找到结果」，并且一点就把
 *    值回退成第一项「全部关闭」。所以改为 DOM widget + 原生 <select>，
 *    两种渲染器下都可靠，也不受上游全静音影响（选项只认连线，不认 mode）。
 */

import { app } from "../../scripts/app.js";
import { setWidgetHidden } from "./xb_compat.js";

const NODE_TYPE = "XB_ReferenceAny";
const WNAME = "选择";
const ALL_OFF = "全部关闭";
const MODE_ACTIVE = 0;
const MODE_MUTE = 2;
const PANEL_H = 32;

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

/** 「选择」是控制端口（可以是隐藏 widget 自己占的槽位） */
function isValuePort(self, inp) {
    if (!inp) return true;
    if (inp.widget) return inp.name === WNAME;
    return inp.name === WNAME;
}

/** 所有已连线的上游节点：[{ index, node, title }] */
function getLinkedNodes(self) {
    const list = [];
    for (let i = 0; i < (self.inputs?.length || 0); i++) {
        const inp = self.inputs[i];
        if (!inp || inp.link == null || isValuePort(self, inp)) continue;
        const up = getUpstreamNode(self, i);
        if (up) list.push({ index: i, node: up, title: up.title || up.type || `输入${i + 1}` });
    }
    return list;
}

/** 数据槽（排除「选择」控制槽与 widget 槽） */
function dataSlots(self) {
    return (self.inputs || [])
        .map((inp, i) => ({ inp, i }))
        .filter((x) => x.inp && !isValuePort(self, x.inp));
}

/**
 * 反向嗅探：顺「选择」端口找到上游节点，读取它第一个 string 类型 widget 的值。
 * 支持 String/Text 原语节点在编辑期间实时嗅探。
 */
function sniffControlString(self) {
    const input = (self.inputs || []).find((inp) => inp && inp.name === WNAME && inp.link != null);
    if (!input?.link) return null;
    const graph = self.graph;
    if (!graph) return null;
    const link = graph.links?.[input.link];
    if (!link) return null;
    const src = graph.getNodeById?.(link.origin_id);
    if (!src) return null;
    for (const w of (src.widgets || [])) {
        if (typeof w.value === "string" && w.value !== "") return w.value;
    }
    return null;
}

/** 用嗅探到的字符串匹配一个选项（包含匹配，取最长命中） */
function matchOption(text, values) {
    if (typeof text !== "string" || !text) return ALL_OFF;
    const lower = text.toLowerCase();
    let best = null;
    for (const v of values) {
        if (v === ALL_OFF) continue;
        if (lower.includes(String(v).toLowerCase())) {
            if (!best || String(v).length > best.length) best = String(v);
        }
    }
    return best || ALL_OFF;
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
        if (node?.type === NODE_TYPE) setTimeout(() => patchInstance(node), 200);
    },
});

// ── instance patching ──────────────────────────────────────────────────

function patchInstance(self) {
    if (self.__xbRefReady) return;
    self.__xbRefReady = true;

    const valueWidget = () => (self.widgets || []).find((w) => w.name === WNAME);

    // 「选择」的原生 STRING widget 只作为取值 / 端口载体，界面上藏掉，用下面的下拉代替
    const hideValueWidget = () => {
        const w = valueWidget();
        if (!w || w.__xbHidden) return;
        w.__xbHidden = true;
        try { setWidgetHidden(self, w, true); } catch (_) { /* ignore */ }
    };
    hideValueWidget();

    // 至少留一个空数据槽
    if (!dataSlots(self).length) self.addInput("", "*");

    // ── 面板：一个原生 <select> ───────────────────────────────────────
    const container = document.createElement("div");
    container.style.cssText = "width:100%;height:100%;box-sizing:border-box;display:flex;align-items:center;gap:6px;"
        + "padding:0 6px;background:#2b2b2b;border-radius:6px;";

    const label = document.createElement("span");
    label.textContent = WNAME;
    label.style.cssText = "flex:0 0 auto;color:#c8c8c8;font-size:12px;";

    const sel = document.createElement("select");
    sel.style.cssText = "flex:1 1 auto;min-width:0;height:24px;background:#1e1e1e;color:#e6e6e6;"
        + "border:1px solid #444;border-radius:5px;font-size:12px;font-family:inherit;padding:0 4px;cursor:pointer;";
    const stop = (e) => { e.stopPropagation(); };
    sel.addEventListener("pointerdown", stop);
    sel.addEventListener("mousedown", stop);
    sel.addEventListener("click", stop);
    sel.addEventListener("change", () => {
        const v = sel.value;
        const w = valueWidget();
        if (w && w.value !== v) w.value = v;
        self.__xbAppliedValue = v;
        self.__xbUserPick = true;
        self.applySelection?.(v);
        self.graph?.setDirtyCanvas?.(true, true);
    });
    container.append(label, sel);
    self.__xbSelectEl = sel;

    const domWidget = self.addDOMWidget?.("xb_ref_select", "XB_REF_SELECT", container, {
        serialize: false,
        hideOnZoom: false,
    });
    if (domWidget) {
        domWidget.options = domWidget.options || {};
        domWidget.options.serialize = false;
        domWidget.options.getMinHeight = () => PANEL_H;
        domWidget.computeSize = () => [Math.max(160, Math.round(self.size?.[0] || 200)), PANEL_H];
        domWidget.computeLayoutSize = () => ({ minHeight: PANEL_H, maxHeight: undefined, minWidth: 160 });
    }
    try { self.size = [Math.max(200, self.size?.[0] || 200), Math.max(PANEL_H + 40, self.size?.[1] || 70)]; } catch (_) { /* ignore */ }

    // ── 端口维护：接线扩展 / 收空槽 / 端口名跟随上游 ──────────────────
    self.stabilizeInputsOutputs = function () {
        let changed = false;
        let slots = dataSlots(this);
        if (!slots.length) {
            this.addInput("", "*");
            return true;
        }
        // 末尾已接线 → 追加一个空槽
        const last = slots[slots.length - 1];
        if (last.inp.link != null) {
            this.addInput("", "*");
            changed = true;
            slots = dataSlots(this);
        }
        // 中间的空槽收掉（只留末尾一个空槽）
        for (let k = slots.length - 2; k >= 0; k--) {
            const { inp, i } = slots[k];
            if (inp && inp.link == null) {
                this.removeInput(i);
                changed = true;
            }
        }
        // 端口名 = 上游节点名
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

    // ── 下拉选项同步（只认连线，不看 mode，所以全静音时也照常显示）──────
    self.syncSelectOptions = function () {
        const el = this.__xbSelectEl;
        if (!el) return false;
        const linked = getLinkedNodes(this);
        const titles = [];
        for (const { title } of linked) {
            if (title && !titles.includes(title)) titles.push(title);
        }
        const values = [ALL_OFF, ...titles];
        const w = valueWidget();
        let current = String(w?.value ?? el.value ?? ALL_OFF);
        if (!values.includes(current)) {
            // 选中的上游确实不在了（被删 / 断开 / 改名）→ 只有当它连 id 都找不到时才回退
            const stillLinked = linked.some((x) => x.node?.id === this.__xbSelectedId);
            const keep = stillLinked ? (linked.find((x) => x.node?.id === this.__xbSelectedId)?.title || ALL_OFF) : ALL_OFF;
            current = keep;
            if (w && w.value !== current) w.value = current;
        }
        const same = el.options.length === values.length
            && values.every((v, i) => el.options[i]?.value === v);
        if (!same) {
            el.replaceChildren(...values.map((v) => {
                const o = document.createElement("option");
                o.value = v;
                o.textContent = v;
                return o;
            }));
        }
        if (el.value !== current) el.value = current;
        return !same;
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
        if (changed) this.graph?.setDirtyCanvas?.(true, true);
        return changed;
    };

    // ── 周期稳定 ──────────────────────────────────────────────────────
    self.doStablization = function () {
        if (!this.graph || this.__xbRefRemoved) return;
        let dirty = false;
        try {
            dirty = this.stabilizeInputsOutputs() || dirty;
            dirty = this.syncSelectOptions() || dirty;

            const el = this.__xbSelectEl;
            const w = valueWidget();
            const ctrl = (this.inputs || []).find((inp) => inp && inp.name === WNAME);

            if (ctrl?.link != null) {
                // 外部 STRING 驱动选择：嗅探值 → 匹配选项
                const sniffed = sniffControlString(this);
                if (sniffed !== this.__xbLastSniffed) {
                    this.__xbLastSniffed = sniffed;
                    const target = sniffed == null ? ALL_OFF : matchOption(sniffed, (el ? Array.from(el.options).map((o) => o.value) : []));
                    if (w && w.value !== target) w.value = target;
                    if (el && el.value !== target) el.value = target;
                    this.__xbAppliedValue = target;
                    dirty = this.applySelection(target) || dirty;
                }
            } else {
                this.__xbLastSniffed = null;
                // 手动下拉：值变了才应用（避免每轮都改上游 mode）
                const cur = String(el?.value ?? w?.value ?? ALL_OFF);
                if (cur !== this.__xbAppliedValue) {
                    this.__xbAppliedValue = cur;
                    dirty = this.applySelection(cur) || dirty;
                }
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
        hideValueWidget();
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
        const w = valueWidget();
        const cur = String(w?.value || ALL_OFF);
        if (self.__xbSelectEl) self.__xbSelectEl.value = cur;
        self.__xbAppliedValue = cur;
        self.doStablization?.();
    }, 250);
}
