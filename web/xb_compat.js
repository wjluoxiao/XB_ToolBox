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
 * 灰化（禁用）一组 widget：仍可见但不可操作
 * Nodes 2.0：widget.disabled = true → Vue 组件拿到 options.disabled 后渲染成 disabled（实测生效）
 * 经典模式：同步写 options.disabled（部分前端版本不绘制灰态，但不影响数值使用）
 * @param {object} node 节点
 * @param {string[]} names widget 名
 * @param {boolean} disabled 是否禁用
 * @returns {boolean} 是否有变化
 */
export function setWidgetsDisabled(node, names, disabled) {
    const list = findWidgets(node, names);
    let changed = false;
    for (const w of list) {
        const t = liveWidget(node, w);
        if (!t) continue;
        if (!!t.disabled === !!disabled) {
            if (t.options && !!t.options.disabled !== !!disabled) t.options.disabled = !!disabled;
            continue;
        }
        t.disabled = !!disabled;
        try { if (t.options) t.options.disabled = !!disabled; } catch (_) { /* ignore */ }
        changed = true;
    }
    if (changed) refreshWidgets(node);
    return changed;
}

/** LATENT 输出端口是否已连线（空latent 一组参数是否生效的前提） */
export function latentOutputLinked(node) {
    try {
        const outs = node?.outputs || [];
        const slot = outs.find((o) => String(o?.type || "").toUpperCase() === "LATENT")
            || outs.find((o) => o?.name === "空latent");
        if (!slot) return false;
        return Array.isArray(slot.links) ? slot.links.length > 0 : slot.link != null;
    } catch (_) {
        return false;
    }
}

/**
 * 「空latent 未连线 → 相关参数变灰不可操作」的守卫
 * 生效时把 names 里的 widget 设为 disabled；接上「空latent」输出连线后自动恢复。
 * @param {object} node 节点
 * @param {string[]} [names] 默认 latent_kind / aspect_ratio / width / height / batch_size
 * @returns {Function} 手动刷新函数（工作流加载后调用一次）
 */
export function installLatentGuard(node, names) {
    if (!node) return () => {};
    const list = names || ["latent_kind", "aspect_ratio", "width", "height", "batch_size"];
    const apply = () => {
        if (!node.widgets) return;
        const locked = !latentOutputLinked(node);
        setWidgetsDisabled(node, list, locked);
        try { node.__xbLatentLocked = locked; } catch (_) { /* ignore */ }
    };
    node.__xbLatentGuardApply = apply;
    if (!node.__xbLatentGuardHooked) {
        node.__xbLatentGuardHooked = true;
        const prev = node.onConnectionsChange;
        node.onConnectionsChange = function (...args) {
            const r = prev?.apply(this, args);
            setTimeout(apply, 0);
            return r;
        };
    }
    setTimeout(apply, 0);
    setTimeout(apply, 350);
    return apply;
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
        "padding:6px 8px;border-radius:6px;background:var(--xb-bg-raise);color:var(--xb-text);" +
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

/**
 * 结构变化（切换 Nodes 2.0 时前端会整块卸载/重建 `.lg-node`）的统一监听。
 * MutationObserver 的回调在**绘制前**执行 ⇒ 在它里面同步重算高度，用户看不到中间态
 * （否则容器会先按"无上限"铺开一帧，再被压回，表现为节点像弹簧一样变长再缩回）。
 */
const XB_NODES2_APPLIERS = new Set();
let XB_NODES2_OBSERVER = null;
function watchNodes2Mount(apply) {
    if (typeof MutationObserver !== "function") return;
    XB_NODES2_APPLIERS.add(apply);
    if (XB_NODES2_OBSERVER) return;
    try {
        XB_NODES2_OBSERVER = new MutationObserver(() => {
            for (const fn of XB_NODES2_APPLIERS) { try { fn(); } catch (_) { /* ignore */ } }
        });
        XB_NODES2_OBSERVER.observe(document.body, { childList: true, subtree: true });
    } catch (_) { XB_NODES2_OBSERVER = null; }
}

/**
 * ============================================================
 * Nodes 2.0：让一个「面板显示框」始终填满节点剩余空间（随节点高度自由伸缩）
 * ============================================================
 * 与 installNodes2BoxResize（按指针位移改固定 px）不同，这里把框高绑到前端自带的
 * CSS 变量 `--node-height`（= 节点高度 + 固定余量），减去一次性标定出的 chrome：
 *   · 纯 CSS 跟随 ⇒ 拖大拖小都跟手，不会「只能变大不能变小」（写 px 会写回 node.size 自锁）；
 *   · 与 JZL 导演台/查看器同一套做法，多节点共用一个实现。
 *
 * @param {object} node LiteGraph 节点
 * @param {HTMLElement} box 要伸缩的显示框
 * @param {object} [opts] { min }
 * @returns {() => void} 卸载函数
 */
export function bindNodes2BoxFill(node, box, opts = {}) {
    if (!node || !box) return () => {};
    const MIN = Number(opts.min) || 120;
    const PROBE = 3000;
    const orig = { height: box.style.height, maxHeight: box.style.maxHeight, minHeight: box.style.minHeight, flex: box.style.flex };
    let K = 0, applied = false, timer = 0;

    const rootEl = () => (box.closest ? box.closest(".lg-node") : null);
    // chrome = 节点根部高度 − 显示框高度：用固定 3000px 撑开量，与框内内容无关
    const calibrate = () => {
        const root = rootEl();
        if (!root) return false;
        const keep = { max: box.style.maxHeight, min: box.style.minHeight, flex: box.style.flex, h: box.style.height };
        try {
            box.style.maxHeight = "";
            box.style.minHeight = "0px";
            box.style.flex = "0 0 auto";
            box.style.height = PROBE + "px";
            const rh = root.clientHeight, bh = box.clientHeight;
            if (!bh || rh <= bh) return false;
            K = Math.max(40, Math.round(rh - bh));
            return true;
        } finally {
            box.style.maxHeight = keep.max;
            box.style.minHeight = keep.min;
            box.style.flex = keep.flex;
            box.style.height = keep.h;
        }
    };
    const apply = () => {
        const root = box.closest ? box.closest(".lg-node") : null;
        if (!root) { restore(); return; }
        // `--node-height` 是 2.0 渲染器写在 .lg-node 上的；拿不到就不写 calc（否则回落兜底值 → 弹簧闪动）
        let vh = "";
        try { vh = getComputedStyle(root).getPropertyValue("--node-height").trim(); } catch (_) { /* ignore */ }
        if (!vh) return;
        if (!K && !calibrate()) return;
        const h = `calc(var(--node-height) - ${K}px)`;
        applied = true;
        box.style.flex = "0 0 auto";
        if (box.style.height !== h) box.style.height = h;
        if (box.style.maxHeight !== h) box.style.maxHeight = h;
        if (box.style.minHeight !== MIN + "px") box.style.minHeight = MIN + "px";
    };
    const restore = () => {
        if (!applied) return;
        applied = false;
        try {
            box.style.height = orig.height;
            box.style.maxHeight = orig.maxHeight;
            box.style.minHeight = orig.minHeight;
            box.style.flex = orig.flex;
        } catch (_) { /* ignore */ }
    };
    const tick = () => {
        try {
            if (isNodes2()) apply();
            else restore();
        } catch (_) { /* ignore */ }
    };
    [0, 120, 400, 1000].forEach((d) => setTimeout(tick, d));
    timer = setInterval(tick, 1000);
    watchNodes2Mount(tick);   // 切 2.0 时在绘制前同步重算，避免一帧的"无上限"铺开

    const uninstall = () => {
        try { clearInterval(timer); } catch (_) { /* ignore */ }
        XB_NODES2_APPLIERS.delete(tick);
        restore();
    };
    try {
        const origRemoved = node.onRemoved;
        node.onRemoved = function () { uninstall(); return origRemoved?.apply(this, arguments); };
    } catch (_) { /* ignore */ }
    return uninstall;
}

/**
 * ============================================================
 * Nodes 2.0：让「面板容器」始终填满节点剩余高度（贴住节点下边缘）
 * ============================================================
 * 与 installNodes2BoxResize（按指针位移写固定 px）不同：这里每拍按**当前实际可用高度**重算。
 *   · 可用高度 = 节点根部 clientHeight − 容器顶部偏移（标题 + 原生输入行） − 底部留白
 *   · 容器写死 height/maxHeight ⇒ 内部 `flex:1` 的输入框/显示窗自然吃掉剩余空间
 *     ⇒ 节点拉高时不会再在底部留一片空白，也不会出现"内容撑出面板"的滚动条。
 *   · 不写 node.setSize（节点尺寸完全由用户/前端决定）⇒ 没有自激抖动。
 *   · 经典模式（无 .lg-node）→ 立即还原行内原样。
 *
 * @param {object} node  LiteGraph 节点
 * @param {HTMLElement} box 要撑满的容器（DOM widget 内容根）
 * @param {object} [opts] { min, bottomPad }
 * @returns {() => void} 卸载函数
 */
export function bindNodes2NodeFill(node, box, opts = {}) {
    if (!node || !box) return () => {};
    const MIN = Number(opts.min) || 120;
    const PAD = Number.isFinite(opts.bottomPad) ? Number(opts.bottomPad) : 12;
    const orig = { height: box.style.height, maxHeight: box.style.maxHeight, minHeight: box.style.minHeight, flex: box.style.flex };
    let applied = false, timer = 0, rafId = 0;
    // ⚠️ Nodes 2.0 刚挂载时，上方原生 widget 行还在逐行铺开，量到的 top 会先小后大。
    //    用偏小的 top 算出的容器高度比可用空间大 → 把整个节点撑高，
    //    下一拍 top 变大再缩回 ⇒ 用户看到「进界面时节点长高一下又恢复」。
    //    所以挂载后的 SETTLE_MS 内只测量、不写入，等布局稳定后再贴合。
    const SETTLE_MS = 300;
    let mountedAt = 0;
    // 已确认的「容器顶部相对节点根部」偏移（布局像素）与待确认候选值
    let stableTop = -1, candTop = -1, candCount = 0;

    // ⚠️ 必须用 offsetTop 累加取偏移，不能用 getBoundingClientRect 相减再除以缩放比：
    //    滚轮缩放时 `app.canvas.ds.scale` 立刻变成新值，而 DOM 的 transform 要下一帧才跟上，
    //    两者不同步 ⇒ 量到的 chrome 比实际小（实测 234 vs 256）⇒ 容器被算高 22px、
    //    节点被内容撑高 13px，下一拍又校正回来 = 用户看到的「跟弹簧一样变一下」。
    //    offsetTop/offsetParent 是布局像素，与画布缩放完全无关，可彻底避开这个不同步。
    const layoutTop = (el, root) => {
        let y = 0;
        let cur = el;
        while (cur && cur !== root) {
            y += cur.offsetTop || 0;
            cur = cur.offsetParent;
        }
        return cur === root ? y : null;
    };

    const restore = () => {
        if (applied) {
            try {
                box.style.height = orig.height;
                box.style.maxHeight = orig.maxHeight;
                box.style.minHeight = orig.minHeight;
                box.style.flex = orig.flex;
            } catch (_) { /* ignore */ }
        }
        applied = false;
        mountedAt = 0;
        stableTop = -1; candTop = -1; candCount = 0;
    };

    const apply = () => {
        const root = box.closest ? box.closest(".lg-node") : null;
        if (!root) { restore(); return; }         // 经典模式 / 还没挂到 DOM
        try {
            // `--node-height` 是 2.0 渲染器写在 .lg-node 上的；拿不到就不写 calc，
            // 否则 calc 会回落到兜底值（3000px）⇒ 切换 2.0 的瞬间节点像弹簧一样变长再缩回。
            let vh = "";
            try { vh = getComputedStyle(root).getPropertyValue("--node-height").trim(); } catch (_) { /* ignore */ }
            if (!vh) { restore(); return; }
            if (!mountedAt) mountedAt = performance.now();
            if (performance.now() - mountedAt < SETTLE_MS) return;   // 布局还在长，写入会撑高节点
            const rb = root.getBoundingClientRect();
            const bb = box.getBoundingClientRect();
            if (!(bb.width > 0 && bb.height > 0 && rb.height > 0)) return;   // 还没真正布局
            const rawTop = layoutTop(box, root);
            if (rawTop == null) return;                                      // 还不在节点 DOM 里
            // 收缩方向（top 变小 ⇒ 容器会被撑高）必须连续两拍一致才采纳，
            // 避免前端重排的中间帧把节点顶高一下再缩回。
            if (stableTop < 0 || rawTop >= stableTop) {
                stableTop = rawTop; candTop = -1; candCount = 0;
            } else if (rawTop === candTop) {
                if (++candCount >= 1) { stableTop = rawTop; candTop = -1; candCount = 0; }
            } else {
                candTop = rawTop; candCount = 0;
            }
            const top = Math.max(0, Math.round(stableTop));
            const css = `calc(var(--node-height) - ${top + PAD}px)`;
            applied = true;
            if (box.style.flex !== "0 0 auto") box.style.flex = "0 0 auto";
            if (box.style.minHeight !== MIN + "px") box.style.minHeight = MIN + "px";
            if (box.style.maxHeight !== css) box.style.maxHeight = css;
            if (box.style.height !== css) box.style.height = css;
        } catch (_) { /* ignore */ }
    };

    const tick = () => { try { apply(); } catch (_) { /* ignore */ } };
    // 首帧 + 之后 500ms 轮询（切 2.0 开关、面板重建、前端重排都能兜住）
    [0, 60, 200, 600].forEach((d) => setTimeout(tick, d));
    // 布局稳定后立刻贴合，不必等下一个 500ms 轮询
    setTimeout(tick, SETTLE_MS + 20);
    timer = setInterval(tick, 500);
    // 结构变化（切 2.0 时 .lg-node 重建）→ MutationObserver 在**绘制前**同步重算，避免看到中间态
    watchNodes2Mount(tick);
    // 挂载初期用 rAF 连续测量，保证 SETTLE_MS 一到就能用最新的 top
    let burst = 40;
    const rafTick = () => { tick(); if (--burst > 0) rafId = requestAnimationFrame(rafTick); };
    rafId = requestAnimationFrame(rafTick);

    const uninstall = () => {
        try { clearInterval(timer); } catch (_) { /* ignore */ }
        try { cancelAnimationFrame(rafId); } catch (_) { /* ignore */ }
        restore();
    };
    try {
        const origRemoved = node.onRemoved;
        node.onRemoved = function () { uninstall(); return origRemoved?.apply(this, arguments); };
    } catch (_) { /* ignore */ }
    return uninstall;
}

/**
 * ============================================================
 * 稳定的节点高度管理（Nodes 2.0 / Vue 节点）
 * ============================================================
 * 实测得到的两条硬事实（这是所有尺寸问题的根源）：
 *   ① **DOM 渲染高度 = max(node.size[1], 内容真实需求) + 标题栏(30)**，
 *      与画布缩放无关（offsetHeight 在 0.5x / 1x / 1.5x 下完全一致）。
 *      正常（不溢出）时恒有 `offsetHeight == size[1] + 30`。
 *   ② 一旦 `size[1] < 内容需求`，DOM 就会**撑破**节点盒子：视觉底边跑到 size 之外，
 *      于是「拖拽弹跳」「底边压不上网格」全部来自这一个错位。
 *
 * 因此本实现只做两件事，且只在就绪后 / 松手后各跑一次：
 *   · **喂饱**：`size[1]` 不允许小于 DOM 实测需求（`offsetHeight - 30`），
 *     且必须连续两次读到同样的溢出量才采纳 —— 布局中间帧的瞬时大值不会被永久固化
 *     （这是「偶发自动变高」的根因）；
 *   · **压线**：`视觉底边 = pos.y + size[1] + 30`，把它补到网格线（δ 最多 9px）。
 *     因为标题栏 30 本身是网格整数倍，只要 size 与 pos 都是网格倍数就自然对齐。
 *   · 不劫持 `onResize`：拖拽完全交给 LiteGraph 原生处理，避免和原生吸附互相打架。
 *
 * @param {object} node LiteGraph 节点
 * @param {object} opts
 *   · minWidth    最小宽度（默认 420）
 *   · rows        节点表面「可见参数行数」（数字或函数）
 *   · domFixedH   兜底常量估算用：DOM 区固定高度
 *   · presetH     新建节点的**预置高度**（默认宽度下的实测最终高度）。
 *                新建时直接就按它布局，不会先以 LiteGraph 默认小尺寸出现再被「拉长」。
 *   · textMinH    兜底常量估算用：提示词框最小高度
 * @returns {{ apply:Function, align:Function, markReady:Function, measure:Function, rows:Function,
 *             destroy:Function, chrome:Function, domHeight:Function, grid:Function, isReady:Function }}
 */
/**
 * ============================================================
 * DOM 容器填满节点（无反馈回路的高度适配）
 * ============================================================
 * 目标：节点高度只由用户 / 工作流决定，DOM 内容适配节点（而不是反过来）。
 *
 * 做法（实测校准，不猜任何常量）：
 *   ① **探测 chrome**：临时把容器高度撑到 3000px，
 *      `chrome = 节点根元素 clientHeight − 容器 clientHeight`。
 *      这个差值只取决于节点壳（标题栏/插槽/footer），**与内容无关**，
 *      所以在任何内容状态下都能量准（旧写法用「实测 top」会随内容漂 ⇒ 越写越长）。
 *   ② 把容器 `maxHeight`（可选同时 `height`）设为 `calc(var(--node-height) - chrome px)`。
 *      `--node-height` 是前端写在 `.lg-node` 上的实时节点高度（Nodes 2.0）。
 *      拿不到就什么都不写（避免 calc 落到兜底值导致「先变长再缩回」）。
 *   ③ 内部用 flex 压缩（提示词框 `flex:1 1 0; min-height:小值`），
 *      所以节点拖矮时内容自己让位（出现滚动条）而不会把节点撑高。
 *
 * ⚠️ 不写 node.size，因此不存在任何反馈回路：不会弹性、不会偶发变高、不可能无限变长。
 *
 * @param {object} node LiteGraph 节点
 * @param {HTMLElement} el 容器（DOM widget 内容）
 * @param {object} opts
 *   · minHeight  容器最小高度（防被压成 0）
 *   · definite   同时写 height（让内部 flex 真正压缩，甲滞留滚动条）
 * @returns {Function} 干净撤销
 */
export function bindDomWidgetFill(node, el, opts = {}) {
    if (!node || !el) return () => {};
    const minH = Number(opts.minHeight) || 0;
    const TITLE_H = 30;   // Vue 节点标题栏（实测恒定：DOM 高 = size + 30）
    const rootEl = () => (el.closest ? el.closest(".lg-node") : null);
    const orig = { max: el.style.maxHeight, min: el.style.minHeight, flex: el.style.flex, h: el.style.height };
    let applied = false;
    let timer = null;
    let ro = null;
    let lastMinKey = "";   // 「内容自然高度」的缓存键（宽度或 K 变了才重量）
    let lastMinAt = 0;
    let fixingH = false;

    const restore = () => {
        if (!applied) return;
        applied = false;
        try {
            el.style.maxHeight = orig.max;
            el.style.minHeight = orig.min;
            el.style.flex = orig.flex;
            el.style.height = orig.h;
        } catch (_) { /* ignore */ }
    };

    /**
     * 量「内容自然高度」= 固定件（按钮区/标签/信息区…）+ 提示词框最小高度。
     *   临时把容器高度放开成 auto，读 offsetHeight 得到内容真实需求高，然后原样恢复。
     *   同一拍内不会有任何绘制，用户看不到。值只取决于宽度（换行）与 K（上方 widget 行数）。
     */
    const measureNatural = () => {
        const ph = el.style.height, pm = el.style.maxHeight, pn = el.style.minHeight;
        let nat = 0;
        try {
            el.style.height = "auto";
            el.style.maxHeight = "none";
            el.style.minHeight = "0px";
            nat = el.offsetHeight;
        } catch (_) { nat = 0; }
        try {
            el.style.height = ph;
            el.style.maxHeight = pm;
            el.style.minHeight = pn;
        } catch (_) { /* ignore */ }
        return nat;
    };

    /**
     * 每次重新实测「容器可用高度」——不缓存任何常量：
     *   可用高 = 小部件区高度(实时) − 容器在该区内的顶部偏移(实时)。
     *
     * ⎠ 旧写法把 chrome（容器上方的高度）用 3000px 探针测一次就永久缓存，
     *    但它并不是常量：节点上方的原生 widget 行数会变（内部字段显隐、输入查位变化、
     *    工作流加载后 widget 重建），一旦它变小，容器就会比可用区短 ⇒ 底部留一大片空白（用户报障）。
     *    现在每次都用实时布局量一次，不依赖任何缓存值。
     *
     * ⎡ 不写 node.size，因此不存在反馈回路（不会弹性 / 偶发变高）。
     */
    /**
     * 把容器高度写成 **CSS calc(var(--node-height) - K)**。
     *
     * ⎠ 为什么必须用 CSS而不是 JS 量一次写一次：
     *    JS 写法要等下一拍（onResize 防抖 / ResizeObserver 回调）才能改容器高度，
     *    拖拽时就会出现「节点先变高、提示词框迟一拍才跟着变」的延迟。
     *    calc() 直接表达式依赖前端每帧更新的 --node-height ⇒ 节点和框**同一帧**变化（0 延迟）。
     *
     * ⎡ K 是不依赖节点高度的常量，每次用实时布局重量：
     *    K = 容器顶部到节点顶部的偏移 + 小部件区下方的固定件高度（footer + 内边距）。
     *    两项都是两个元素 rect 相减，与是否溢出无关、与节点高度无关 ⇒ **不存在反馈回路**。
     *    只在上方 widget 行数变化（内部字段显隐、输入查位）时才会变，那种时候我们会重量并改写 calc 里的 K。
     */
    const apply = () => {
        try {
            const root = rootEl();
            if (!root) { restore(); return; }                       // 经典渲染器 → 交回原生
            const wa = el.closest ? el.closest(".lg-node-widgets") : null;
            if (!wa) { restore(); return; }                          // 没有 2.0 小部件区 → 交回原生
            const nodeW = Number(node.size?.[0]) || 0;
            const nodeH = Number(node.size?.[1]) || 0;
            if (!(nodeW > 0) || !(nodeH > 0)) return;
            const rr = root.getBoundingClientRect();
            const wr = wa.getBoundingClientRect();
            const er = el.getBoundingClientRect();
            if (!(rr.width > 0) || !(rr.height > 0)) return;         // 还没真正布局
            const scale = rr.width / nodeW;                          // 画布缩放 / UI 缩放
            if (!(scale > 0.05) || !(scale < 20)) return;
            const topInRoot = (er.top - rr.top) / scale;             // 容器顶部 到 节点顶部
            const bottomChrome = (rr.bottom - wr.bottom) / scale;    // 小部件区下方的固定件（footer + 内边距）
            if (!(topInRoot >= -2) || !(bottomChrome >= 0)) return;  // 动画 / 未就绪
            const K = Math.round(topInRoot + bottomChrome);
            if (!(K >= 40) || K > 4000) return;                      // 非常识 → 本拍不写
            let vh = "";
            try { vh = getComputedStyle(root).getPropertyValue("--node-height").trim(); } catch (_) { /* ignore */ }
            // 拿不到 --node-height 的环境（很老的前端 / 异常态）退化为固定 px
            const h = vh ? `calc(var(--node-height) - ${K}px)` : `${Math.max(60, Math.round(nodeH + TITLE_H - K))}px`;
            applied = true;
            if (el.style.flex !== "0 0 auto") el.style.flex = "0 0 auto";
            if (opts.definite && el.style.height !== h) el.style.height = h;
            if (el.style.maxHeight !== h) el.style.maxHeight = h;
            if (minH > 0 && el.style.minHeight !== minH + "px") el.style.minHeight = minH + "px";
            // 节点「最小高度」：保证最小时按钮区 + 提示词框全部同屏显示，
            // 不裁掉任何一部分，也不产生滚动条（容器 overflow:hidden）。
            //   内容自然高 nat = 固定件 + 提示词框最小高；可用高 = nodeH + 30 − K
            //   ⇒ 最小 nodeH = nat + K − 30
            try {
                if (opts.autoMinHeight !== false) {
                    const key = Math.round(nodeW) + "@" + K;
                    const now = Date.now();
                    // 2 秒兜底重量一次：万一某一拍在布局过渡中量到偏大的值，
                    // 之后会自己修正回去（否则那个偏大的下限会一直卡着）。
                    if (key !== lastMinKey || now - lastMinAt > 2000) {
                        lastMinKey = key;
                        lastMinAt = now;
                        const nat = measureNatural();
                        if (nat > 20 && nat < 6000) {
                            const need = Math.round(nat + K - TITLE_H);
                            if (need > 0 && Math.abs((Number(node._xbMinNodeH) || 0) - need) > 1) {
                                node._xbMinNodeH = need;
                            }
                        }
                    }
                    const need2 = Number(node._xbMinNodeH) || 0;
                    if (need2 > 0 && nodeH < need2 - 0.5 && !fixingH) {
                        fixingH = true;
                        try { node.setSize([nodeW, need2]); } catch (_) { /* ignore */ }
                        fixingH = false;
                    }
                }
            } catch (_) { /* ignore */ }
        } catch (_) { /* ignore */ }
    };

    const tick = () => { try { apply(); } catch (_) { /* ignore */ } };

    // 首帧 + 几个时序点（DOM 挂载 / 工作流加载都能兜住）
    try { requestAnimationFrame(() => { tick(); setTimeout(tick, 120); setTimeout(tick, 400); setTimeout(tick, 1000); }); }
    catch (_) { tick(); }

    // 小部件区 / 根元素尺寸变化（节点拖拽、widget 重建、显隐变化）→ 立即重量
    try {
        if (typeof ResizeObserver === "function") {
            ro = new ResizeObserver(tick);
            const root = rootEl();
            const wa = el.closest ? el.closest(".lg-node-widgets") : null;
            if (root) ro.observe(root);
            if (wa) ro.observe(wa);
        }
    } catch (_) { ro = null; }

    // 低频兜底：节点被删 / 切模式 → 还原；否则每次都重量一下（仅写差异，不抖）
    timer = setInterval(() => {
        if (!el.isConnected || !node.graph) {
            clearInterval(timer);
            timer = null;
            if (ro) { try { ro.disconnect(); } catch (_) { /* ignore */ } ro = null; }
            restore();
            return;
        }
        tick();
    }, 400);

    const cleanup = () => {
        if (timer) { clearInterval(timer); timer = null; }
        if (ro) { try { ro.disconnect(); } catch (_) { /* ignore */ } ro = null; }
        restore();
    };
    // 调用方可以随时重新应用 / 还原（如节点 resize 后重算）
    cleanup.apply = () => { try { apply(); } catch (_) { /* ignore */ } };
    cleanup.restore = () => { try { restore(); } catch (_) { /* ignore */ } };
    return cleanup;
}

/**
 * 让节点尺寸**只由自己决定**（用户拖拽 / presetH / 我们自己的下限钳制）。
 *
 * ⎠ 为什么要劫持 computeSize：
 *   前端在「加载 / 打开工作流」的收尾会跑一段 grow-only 的尺寸修正
 *   （app.js：`t = e.computeSize(); t[0] = max(e.size[0], t[0]); …; e.setSize(t)`），
 *   而 `computeSize()` 会把 DOM 部件的 `computeLayoutSize().minWidth` 再加上「值区宽度」：
 *   我们的 DOM 部件 minWidth = 560 → 560 + 110 = **670**。
 *   于是任何宽度小于 670 的预设节点，刷新页面后都会被顶回 670，而且永远缩不小
 *   （它只增不减）。高度同理会被撑到 `minHeight` 之和，造成「刷新后变高 / 底部空白」。
 *
 *   把 computeSize 换成就地返回当前尺寸后，那一段修正对我们是空操作；
 *   节点尺寸完全由 `installStableNodeHeight`（预置高度 + 宽度锁）与用户拖拽决定。
 *
 * @param {object} node 节点
 * @param {number} [minW] 宽度兜底（节点尺寸异常为 0 时用）
 */
export function lockNodeComputeSize(node, minW = 0) {
    if (!node || node.__xbComputeLocked) return;
    node.__xbComputeLocked = true;
    try {
        node.computeSize = function () {
            const w = Number(this.size?.[0]);
            const h = Number(this.size?.[1]);
            return [w > 0 ? w : (minW > 0 ? minW : 200), h > 0 ? h : 240];
        };
    } catch (_) { /* ignore */ }
}

export function installStableNodeHeight(node, opts = {}) {
    const MIN_W = Number(opts.minWidth) || 420;
    const TITLE_H = 30;     // Vue 节点标题栏高度（实测恒定）
    const ROW_H = 26;       // 原生 widget 单行高度
    const DOM_FIXED_H = Number.isFinite(opts.domFixedH) ? opts.domFixedH : 116;
    const TEXT_MIN_H = Number.isFinite(opts.textMinH) ? opts.textMinH : 300;
    const HARD_MIN = 420;
    const PRESET_H = Number.isFinite(opts.presetH) && opts.presetH > 0 ? Math.round(opts.presetH) : 0;
    const rowsOf = typeof opts.rows === "function" ? opts.rows : () => (Number(opts.rows) || 0);

    /** 画布网格步长（ComfyUI 设置 → LiteGraph.CANVAS_GRID_SIZE → 10） */
    const gridOf = () => {
        try {
            const v = app?.ui?.settings?.getSettingValue?.("Comfy.SnapToGrid.GridSize");
            if (Number.isFinite(v) && v > 0) return v;
        } catch (_) { /* ignore */ }
        const lg = Number(window.LiteGraph?.CANVAS_GRID_SIZE);
        return Number.isFinite(lg) && lg > 0 ? lg : 10;
    };

    /** 默认宽度下的内容最小高度（仅供下限/调试） */
    const measure = () => Math.max(HARD_MIN, Math.round(TITLE_H + rowsOf() * ROW_H + DOM_FIXED_H + TEXT_MIN_H));

    const domHeight = () => {
        try {
            const list = document.querySelectorAll(`[data-node-id="${node.id}"]`);
            for (const el of list) {
                if (String(el.className || "").includes("lg-node")) return el.offsetHeight || 0;
            }
        } catch (_) { /* ignore */ }
        return 0;
    };

    /** 宽度下限锁（唯一会写尺寸的地方之一，且只管宽度） */
    const lockWidth = () => {
        try {
            const w = Number.isFinite(node.size?.[0]) ? node.size[0] : 0;
            if (w >= MIN_W) return 0;
            node.setSize?.([MIN_W, Math.max(Number(node.size?.[1]) || HARD_MIN, HARD_MIN)]);
            return 1;
        } catch (_) { return 0; }
    };

    /**
     * 对齐：**不再写高度**。
     *
     * ⎠ 这是本次彻底修复的关键：
     *    旧实现用「DOM 实测高度」反推 node.size，形成了 **DOM → size → DOM 的反馈回路**：
     *      · 内容被拖矮 ⇒ 溢出 ⇒ 长高 ⇒ 移动/重排时又重算 ⇒ 弹性、偶发变高、无限变长；
     *      · 「底边压网格」的 0~9px 补偿就是「拖到最小反弹 10px」的直接原因。
     *    现在完全交给原生 + CSS（见 bindDomWidgetFill）：节点高度只由用户/工作流决定，
     *    DOM 内容用 CSS 去适配节点（而不是节点去适配内容）⇒ 彻底无回路、无弹性、不可能自动变高。
     */
    const align = () => {
        const c = lockWidth();
        if (c) node.setDirtyCanvas?.(true, true);
        return c;
    };

    /** DOM 挂载完成后调一次（保留 API 兼容；不再做任何尺寸自适应） */
    const markReady = () => { try { align(); } catch (_) { /* ignore */ } };

    const destroy = () => { try { node.__xbStableHeight = null; } catch (_) { /* ignore */ } };

    /**
     * 预置高度：本函数在 addDOMWidget 之前调用，此刻 DOM 还没挂载。
     * 直接把 size 设到「默认宽度下的实测最终高度」，节点从第一帧就是最终尺寸。
     * 工作流加载时 configure 会用保存的尺寸覆盖它，不影响老工作流。
     */
    if (PRESET_H) {
        try {
            const curW = Number(node.size?.[0]) || MIN_W;
            node.setSize?.([Math.max(curW, MIN_W), PRESET_H]);
        } catch (_) { /* ignore */ }
    }

    const api = {
        apply: align, align, markReady, measure, rows: rowsOf, destroy,
        chrome: () => 0, domHeight, grid: gridOf,
        isReady: () => true,
    };
    try { node.__xbStableHeight = api; } catch (_) { /* ignore */ }
    return api;
}

/**
 * 遍历「根图 + 所有子图（含嵌套）」，返回全部节点。
 * 放在子图里的节点不在 app.graph._nodes 里，轮询时必须用这个。
 */
export function allNodes() {    const out = [];
    const seenGraphs = new Set();
    const seenNodes = new Set();
    const visit = (g) => {
        if (!g || seenGraphs.has(g)) return;
        seenGraphs.add(g);
        for (const n of g._nodes || []) {
            if (!seenNodes.has(n)) { seenNodes.add(n); out.push(n); }
            if (n.subgraph) visit(n.subgraph);
        }
    };
    visit(app?.graph?.rootGraph || app?.graph);
    return out;
}

/**
 * 找外层子图节点上对应同名的 widget。
 * 节点被打包进子图且该输入被提升为子图输入时，外层子图节点上会有一个同名 widget，
 * 但内外两边不会自动互相同步（运行时靠连线传值，widget.value 保持旧值）。
 */
export function ownerWidgets(node, name) {
    const inner = node?.graph;
    const root = inner?.rootGraph || app?.graph?.rootGraph;
    const out = [];
    if (!inner || !root || root === inner) return out;
    const seen = new Set();
    const visit = (g) => {
        if (!g || seen.has(g)) return;
        seen.add(g);
        for (const n of g._nodes || []) {
            const sub = n.subgraph;
            if (!sub) continue;
            if (sub === inner) {
                const w = (n.widgets || []).find((x) => x.name === name);
                if (w) out.push(w);
            }
            visit(sub);
        }
    };
    visit(root);
    return out;
}

/** 按 widget 类型把值规整一下；不合法返回 null */
function promoNormalize(w, v) {
    const vals = w?.options?.values;
    if (Array.isArray(vals) && vals.length) {
        if (vals.includes(v)) return v;
        if (vals.includes(String(v))) return String(v);
        return null;
    }
    const numeric = typeof w?.value === "number" || /INT|FLOAT|number/i.test(String(w?.type || ""));
    if (numeric) {
        const n = Number(v);
        return Number.isFinite(n) ? n : null;
    }
    if (typeof v === "string") return v;
    if (typeof v === "number" || typeof v === "boolean") return v;
    return null;
}

/**
 * 内外两侧哪个变了就同步到另一边：
 *   · 用户改了外层子图节点上的 widget → 拉回内层（ComfyUI 不会自动回写）
 *   · 用户改了内层 widget / 内层联动算出新值 → 推到外层（否则执行时用的还是外层旧值）
 * 通过记住上一次两边的值来判定方向，避免互相覆盖。
 */
export function syncPromotedValues(node) {
    let pulled = false;
    for (const w of node?.widgets || []) {
        const ext = ownerWidgets(node, w.name);
        if (!ext.length) continue;
        const ow = ext[0];
        const st = w.__xbPromo || (w.__xbPromo = { i: w.value, o: ow.value });
        const innerChanged = st.i !== w.value;
        const outerChanged = st.o !== ow.value;
        if (outerChanged && !innerChanged) {
            const nv = promoNormalize(w, ow.value);
            if (nv !== null && nv !== w.value) { w.value = nv; pulled = true; }
        } else if (innerChanged && !outerChanged) {
            const nv = promoNormalize(ow, w.value);
            if (nv !== null && nv !== ow.value) ow.value = nv;
        }
        w.__xbPromo = { i: w.value, o: ow.value };
    }
    return pulled;
}

/** 把内层 widget 的值推到外层子图节点上（否则执行时用的还是外层的旧值） */
export function pushPromotedValue(node, name, val) {
    let changed = false;
    for (const w of ownerWidgets(node, name)) {
        if (w.value !== val) { w.value = val; changed = true; }
    }
    return changed;
}

/** 供自动化/排查使用 */
export const XB_COMPAT = { version: 1 };
