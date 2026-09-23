/**
 * XB_ToolBox — ComfyUI “Nodes 2.0”（DOM/Vue 节点渲染）兼容工具
 * ============================================================
 * 背景（前端 1.5x 实测源码结论）：
 *   · 开启 `Comfy.VueNodes.Enabled` 后，节点由 DOM 渲染，`LGraphCanvas.drawNode()` 直接 early-return
 *     ⇒ 节点级 onDrawForeground / onDrawBackground / node.draw 一律不执行。
 *   · 节点级 onMouseDown / onDblClick（画布坐标命中）不再触发。
 *   · 画布 widget 仍会画（WidgetLegacy 把 widget.draw 画进独立 canvas）。
 *   · 可见性判定：经典模式看 `type === "hidden"`；Nodes 2.0 看 `widget.hidden` / `widget.options.hidden`。
 *   · DOM widget 高度：Nodes 2.0 走 `computeLayoutSize()`（= options.getMinHeight 或 CSS 变量
 *     `--comfy-widget-min-height`），经典模式走 `computeSize()`。
 *
 * 本文件被 WEB_DIRECTORY 当作扩展一起加载，但只导出工具函数、不注册扩展。
 */
import { app } from "../../scripts/app.js";

/** 当前是否运行在 Nodes 2.0（DOM 节点渲染）模式 */
export function isNodes2() {
    try {
        return app?.ui?.settings?.getSettingValue?.("Comfy.VueNodes.Enabled") === true;
    } catch (_) {
        return false;
    }
}

/** 取“当前活动的”widget 对象：按名字重新查找，确保拿到 Nodes 2.0 的响应式代理 */
export function liveWidget(node, w) {
    try {
        const list = node?.widgets;
        if (!list || !w) return w;
        return list.find((x) => x === w) || list.find((x) => x.name === w.name) || w;
    } catch (_) {
        return w;
    }
}

/** 按名字收集 widget（含 type === "button" 的通配） */
export function findWidgets(node, names, opts = {}) {
    const set = new Set(names);
    const wantButtons = !!opts.buttons;
    return (node?.widgets || []).filter((w) => w && (set.has(w.name) || (wantButtons && w.type === "button")));
}

/**
 * 让 Nodes 2.0 的 widget 列表刷新一次。
 * 前端把 node.widgets 包成 reactive 数组并监听长度/元素变化，重新赋值同内容数组即触发重新映射。
 */
export function refreshWidgets(node) {
    try {
        if (Array.isArray(node?.widgets)) node.widgets = node.widgets.slice();
    } catch (_) { /* ignore */ }
    // ⚠️ 实测（前端 1.52.7）：只改 type/hidden/options.hidden 时，Nodes 2.0 的 DOM 不会立刻重渲染；
    //    触发这个内部事件会让 Vue 侧重新抽取节点数据，可见性立即生效（其他图形事件同理）。
    try {
        node?.graph?.trigger?.("node:slot-label:changed", { nodeId: node.id, slotType: 2 });
    } catch (_) { /* ignore */ }
    try { node?.setDirtyCanvas?.(true, true); } catch (_) { /* ignore */ }
    try { node?.graph?.setDirtyCanvas?.(true, true); } catch (_) { /* ignore */ }
}

/**
 * 隐藏 / 恢复一个 widget（经典 + Nodes 2.0 双兼容，幂等）
 * 经典模式：type="hidden" + computeSize=[0,-4]
 * Nodes 2.0：hidden=true + options.hidden=true（官方 core 的 setWidgetHidden 同款）
 */
export function setWidgetHidden(node, w, hidden) {
    const t = liveWidget(node, w);
    if (!t) return;
    if (hidden) {
        if (!t.__xbHide) {
            t.__xbHide = {
                type: t.type,
                hidden: t.hidden,
                optHidden: t.options ? t.options.hidden : undefined,
                computeSize: t.computeSize,
                hadComputeSize: Object.prototype.hasOwnProperty.call(t, "computeSize"),
            };
        }
        try { t.type = "hidden"; } catch (_) { /* ignore */ }
        try { t.hidden = true; } catch (_) { /* ignore */ }
        try { if (t.options) t.options.hidden = true; } catch (_) { /* ignore */ }
        try { t.computeSize = () => [0, -4]; } catch (_) { /* ignore */ }
        try { if (t.inputEl) t.inputEl.style.display = "none"; } catch (_) { /* ignore */ }
    } else {
        const s = t.__xbHide;
        if (!s) return;
        try { t.type = s.type; } catch (_) { /* ignore */ }
        try { t.hidden = s.hidden; } catch (_) { /* ignore */ }
        try { if (t.options) t.options.hidden = s.optHidden; } catch (_) { /* ignore */ }
        try {
            if (s.hadComputeSize) t.computeSize = s.computeSize;
            else delete t.computeSize;
        } catch (_) { /* ignore */ }
        try { if (t.inputEl) t.inputEl.style.display = ""; } catch (_) { /* ignore */ }
        try { delete t.__xbHide; } catch (_) { /* ignore */ }
    }
    // ⚠️ 关键：onNodeCreated 阶段前端还没把 widgets 包成响应式代理，改完必须刷一次才重渲染
    refreshWidgets(node);
}

export const hideWidget = (node, w) => setWidgetHidden(node, w, true);
export const showWidget = (node, w) => setWidgetHidden(node, w, false);

/**
 * 显示部件并按需覆盖类型 / 高度（模型加载器这类“槽位”场景使用）
 * @param {object} opts.type 恢复后要设置的 widget 类型（combo / toggle / number …）
 * @param {Function} opts.computeSize 恢复后要设置的 computeSize
 */
export function showWidgetAs(node, w, opts = {}) {
    setWidgetHidden(node, w, false);
    const t = liveWidget(node, w);
    if (!t) return;
    try { if (opts.type) t.type = opts.type; } catch (_) { /* ignore */ }
    try { if (typeof opts.computeSize === "function") t.computeSize = opts.computeSize; } catch (_) { /* ignore */ }
}

/** 节点内“一行部件”的经典模式尺寸（Nodes 2.0 会按 DOM 内容自适应，不受影响） */
export const slotSize = (node, h = 26) => () => [Math.max(1, (node?.size?.[0] || 360) - 16), h];

/** 批量锁定一组 widget：names 为名字数组；opts.buttons=true 时把 button 型 widget 一并锁定 */
export function lockWidgets(node, names, locked, opts = {}) {
    const list = findWidgets(node, names, opts);
    for (const w of list) setWidgetHidden(node, w, locked);
    refreshWidgets(node);
    return list.length;
}

/**
 * DOM widget 尺寸（Nodes 2.0 用 computeLayoutSize/options.getMinHeight，经典模式用 computeSize）
 * @param {number} minH 期望高度（px）
 */
export function sizeDomWidget(node, w, minH) {
    if (!w) return w;
    const h = Math.max(1, Math.round(Number(minH) || 50));
    try {
        w.options = w.options || {};
        w.options.getMinHeight = () => h;
    } catch (_) { /* ignore */ }
    try {
        w.computeLayoutSize = () => ({ minHeight: h, maxHeight: undefined, minWidth: 0 });
    } catch (_) { /* ignore */ }
    try {
        w.computeSize = () => [Math.max(1, (node?.size?.[0] || 400) - 16), h];
    } catch (_) { /* ignore */ }
    try {
        w.element?.style?.setProperty?.("--comfy-widget-min-height", h + "px");
    } catch (_) { /* ignore */ }
    return w;
}

/** 统一样式设置：DOM widget（element）/ 经典 widget（inputEl）都能吃到，不存在则静默跳过 */
export function styleWidgetInput(w, css) {
    try {
        for (const el of [w?.inputEl, w?.element]) {
            if (!el || !el.style) continue;
            if (typeof css === "string") el.style.cssText += ";" + css;
            else Object.assign(el.style, css);
        }
    } catch (_) { /* ignore */ }
}

/**
 * 统一写 widget 值：DOM 面板 / Vue 部件 / 回调 三条通道都兜住
 * （Nodes 2.0 里数字/下拉是 Vue 组件，没有 inputEl/element，只能靠 value + callback）
 */
export function setWidgetValue(w, val) {
    if (!w) return;
    const el = w.inputEl || w.element;
    let handled = false;
    try {
        if (el && "value" in el) {
            el.value = val;
            el.dispatchEvent(new Event("input", { bubbles: true }));
            handled = true;
        }
    } catch (_) { /* ignore */ }
    try {
        if (w.value !== val) w.value = val;
    } catch (_) { /* ignore */ }
    if (!handled) {
        try { if (typeof w.callback === "function") w.callback(val); } catch (_) { /* ignore */ }
    }
}

/**
 * 生成/复用“被接管”提示条（DOM widget，经典模式与 Nodes 2.0 都能显示）
 * 用一个 DOM widget 替代原来画在画布上的 🔒 蒙版文案。
 */
export function ensureBanner(node, name, text, minH = 30) {
    let w = (node?.widgets || []).find((x) => x.name === name);
    if (w) {
        try {
            const el = w.element?.querySelector?.("[data-xb-banner]");
            if (el && el.textContent !== text) el.textContent = text;
        } catch (_) { /* ignore */ }
        return w;
    }
    const el = document.createElement("div");
    el.dataset.xbBanner = "1";
    el.textContent = text;
    el.style.cssText =
        "padding:6px 8px;border-radius:6px;background:#2b3138;color:#cfd6dd;" +
        "font-size:12px;line-height:1.4;text-align:center;user-select:none;";
    w = node.addDOMWidget(name, name, el, { serialize: false, hideOnZoom: false, getMinHeight: () => minH });
    sizeDomWidget(node, w, minH);
    setWidgetHidden(node, w, true); // 默认收起
    return w;
}

/**
 * 接力点“端口被连线接管 → 锁住本地部件”的通用实现（替代原来画在画布上的蒙版 + onMouseDown 拦截）
 * @param {object} node
 * @param {object} opts
 *   opts.locked(node) -> boolean   是否处于锁定态
 *   opts.names  string[]           需要锁定的 widget 名
 *   opts.text   string             提示条文案
 *   opts.watch  string[]           触发重新评估的 widget 名（开关型）
 */
export function installRelayLock(node, opts = {}) {
    if (!node || node._xbRelayLock) return;
    node._xbRelayLock = true;

    const names = opts.names || ["image_upload", "upload"];
    const watch = opts.watch || [];
    const bannerName = opts.bannerName || "xb_relay_banner";
    const text = opts.text || "🔒 已由连线接管";
    const isLocked = () => {
        try { return !!opts.locked?.(node); } catch (_) { return false; }
    };
    const targets = () =>
        (node.widgets || []).filter(
            (w) =>
                w &&
                w.name !== bannerName &&
                (names.includes(w.name) || (w.type === "button" && !/randomize/i.test(w.name || "")))
        );

    const apply = () => {
        if (!node.widgets) return;
        const lock = isLocked();
        for (const w of targets()) setWidgetHidden(node, w, lock);
        setWidgetHidden(node, ensureBanner(node, bannerName, text), !lock);
        if (opts.hideImgs) syncImgs(lock);
        refreshWidgets(node);
    };

    // 预览图收走/归还（取代原先在 onDrawBackground 里临时置空 this.imgs 的写法）
    const syncImgs = (lock) => {
        try {
            if (lock) {
                if (node.imgs && !node.__xbImgs) {
                    node.__xbImgs = node.imgs;
                    node.imgs = undefined;
                }
            } else if (node.__xbImgs) {
                node.imgs = node.__xbImgs;
                delete node.__xbImgs;
            }
        } catch (_) { /* ignore */ }
    };
    if (opts.hideImgs) {
        const origExec = node.onExecuted;
        node.onExecuted = function () {
            const r = origExec?.apply(this, arguments);
            try { if (isLocked()) syncImgs(true); } catch (_) { /* ignore */ }
            return r;
        };
    }

    // 1) 连线变化 → 重新评估
    const origConn = node.onConnectionsChange;
    node.onConnectionsChange = function () {
        const r = origConn?.apply(this, arguments);
        setTimeout(apply, 0);
        return r;
    };

    // 2) 开关型 widget 的值变化 → 重新评估
    const bindWatch = () => {
        for (const nm of watch) {
            const w = (node.widgets || []).find((x) => x.name === nm);
            if (!w || w._xbLockBound) continue;
            w._xbLockBound = true;
            const oc = w.callback;
            w.callback = function (v, ...rest) {
                const r = oc?.apply(this, [v, ...rest]);
                setTimeout(apply, 0);
                return r;
            };
        }
    };
    const boot = () => { bindWatch(); apply(); };
    setTimeout(boot, 50);
    setTimeout(boot, 300);
    setTimeout(apply, 1200);
    apply();
}

/**
 * Nodes 2.0：让「面板内某个输入框」跟随节点拉伸而变高（经典模式下还原原样、零副作用）
 * ============================================================
 * 背景（实测）：2.0 下节点高度由 DOM 内容决定，面板里 `flex:1 1 auto` 的框在容器
 * 高度不确定时会一直停在 min-height（用户在节点上拖高，框不跟着变）。
 * 而「按节点高度反推框高」会自激（写框高 → 撑高节点 → 又被当成拖拽增量），
 * 所以这里采用已验证的做法：
 *   · 首次直接给默认高度（deflt）；
 *   · 用户拖节点尺寸手柄时，按**指针位移 / 画布缩放**同步改框高（两个方向都跟手，
 *     且不会因为"节点不允许小于内容"而拖不回去）；
 *   · 切回经典模式 → 还原原样行内值，交回原有 flex 布局。
 *
 * @param {object} node  LiteGraph 节点
 * @param {HTMLElement} box 要被改高度的元素（面板里的输入框）
 * @param {object} [opts] { min, max, deflt }
 * @returns {() => void} 卸载函数
 */
export function installNodes2BoxResize(node, box, opts = {}) {
    const MIN = Number(opts.min) || 120;
    const MAX = Number(opts.max) || 4000;
    const DEFLT = Number(opts.deflt) || 300;
    const orig = {
        height: box.style.height, minHeight: box.style.minHeight,
        maxHeight: box.style.maxHeight, flex: box.style.flex,
    };
    let applied = false, drag = null, timer = 0;

    const apply = (h) => {
        applied = true;
        box.style.flex = "0 0 auto";
        box.style.height = h + "px";
        box.style.minHeight = h + "px";
        box.style.maxHeight = h + "px";
    };
    const restore = () => {
        if (!applied) return;
        applied = false;
        try {
            box.style.height = orig.height;
            box.style.minHeight = orig.minHeight;
            box.style.maxHeight = orig.maxHeight;
            box.style.flex = orig.flex;
        } catch (_) { /* ignore */ }
    };
    const sync = () => {
        if (!isNodes2()) { restore(); return; }
        if (drag) return;                       // 拖拽中由指针接管
        if (!applied) apply(Math.max(MIN, Math.min(MAX, DEFLT)));
    };
    const onMove = (e) => {
        if (!drag) return;
        try {
            const scale = Number(app?.canvas?.ds?.scale) || 1;
            const d = ((e.clientY - drag.y) / scale) * drag.sign;
            const h = Math.max(MIN, Math.min(MAX, Math.round(drag.box + d)));
            if (Math.abs(box.offsetHeight - h) > 1) apply(h);
        } catch (_) { /* ignore */ }
    };
    const onEnd = () => {
        drag = null;
        try {
            window.removeEventListener("pointermove", onMove, true);
            window.removeEventListener("pointerup", onEnd, true);
            window.removeEventListener("pointercancel", onEnd, true);
        } catch (_) { /* ignore */ }
    };
    const hookHandles = () => {
        try {
            const el = document.querySelector(`[data-node-id="${node.id}"]`);
            if (!el || el.__xbBoxResizeHooked) return;
            el.__xbBoxResizeHooked = true;
            el.addEventListener("pointerdown", (e) => {
                const hd = (e.target && e.target.closest) ? e.target.closest('[aria-label*="调整大小"]') : null;
                if (!hd) return;
                const corner = (hd.getAttribute("data-corner") || "").toUpperCase();
                if (corner.indexOf("N") < 0 && corner.indexOf("S") < 0) return;   // 只处理能改高度的角
                drag = {
                    y: e.clientY,
                    box: box.offsetHeight || DEFLT,
                    sign: corner.indexOf("N") >= 0 ? -1 : 1,          // 拖上边时指针向上 = 节点变高
                };
                window.addEventListener("pointermove", onMove, true);
                window.addEventListener("pointerup", onEnd, true);
                window.addEventListener("pointercancel", onEnd, true);
            }, true);
        } catch (_) { /* ignore */ }
    };

    // 初始化：几次延时兜住「DOM 挂载/工作流加载」时序；之后 1s 轮询应对运行时切换 2.0 开关
    const boot = () => { hookHandles(); sync(); };
    [0, 120, 400, 1000].forEach((d) => setTimeout(boot, d));
    timer = setInterval(boot, 1000);

    const uninstall = () => {
        try { clearInterval(timer); } catch (_) { /* ignore */ }
        onEnd();
        restore();
    };
    try {
        const origRemoved = node.onRemoved;
        node.onRemoved = function () { uninstall(); return origRemoved?.apply(this, arguments); };
    } catch (_) { /* ignore */ }
    return uninstall;
}

/** 供自动化/排查使用 */
export const XB_COMPAT = { version: 1 };
