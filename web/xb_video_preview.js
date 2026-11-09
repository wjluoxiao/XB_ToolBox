// ============================================================
// XB-BOX 视频预览共用逻辑（保存视频 / 加载视频 共用）
//   1. 「自动播放」开关：开 = 视频就绪后自动开始（静音，浏览器允许自动播放）；
//      关 = 保持暂停，等用户点播放。只在「新视频 / 开关变化」时动作，不打断用户手动暂停。
//   2. 鼠标悬停在画面上才出声，移出立刻静音。
//   3. 节点尺寸只由用户决定：预览永远不许改变节点宽高。
//      · 经典模式把部件的 computeLayoutSize 最小宽高压到负值（抵消排版的 8px），
//        并在赋值那一刻用属性拦截（前端是「先 addDOMWidget、返回后才赋值」，事后补丁会晚一帧）。
//      · 两个模式都额外「钉住尺寸」：记住基准尺寸（用户工作流里的 / 用户手动拖过的），
//        发现被自动改动就拉回；用户正在拖拽时则以新尺寸为基准。这样刷新页面也不会变矮。
// ============================================================

export const MIN_PREVIEW = 80;     // Nodes 2.0：.video-preview 的 CSS 最小高度
// 经典模式下预览部件不允许向节点「要」任何额外高度：
// 一旦要了，节点就会被 setSize 撑高（且高度随视频分辨率变化）。
// 这里用一个很小的负值 (-8) 抵消经典排版给「弹性部件」固定加的 8px 内边距，
// 让预览只吃节点里现有的空余高度、节点尺寸完全不变（和 Nodes 2.0 一致）。
const CLASSIC_PREVIEW_MIN = -8;
// 基准尺寸存在 properties 里，跟着工作流一起保存（刷新后仍按它固定）
const PIN_KEY = "xbPinnedSize";

/** 读取「钉住」的尺寸（Nodes 2.0 里 size 可能是类数组代理，不能用 Array.isArray 判） */
function readPin(node) {
    const p = node?.properties?.[PIN_KEY];
    const w = Math.round(Number(p?.[0]));
    const h = Math.round(Number(p?.[1]));
    return w > 0 && h > 0 ? [w, h] : null;
}

/** 写入「钉住」的尺寸 */
function writePin(node, size) {
    const w = Math.round(Number(size?.[0]));
    const h = Math.round(Number(size?.[1]));
    if (!(w > 0 && h > 0)) return;
    node.properties = node.properties || {};
    const cur = node.properties[PIN_KEY];
    if (Number(cur?.[0]) === w && Number(cur?.[1]) === h) return;
    node.properties[PIN_KEY] = [w, h];
}

/** 用户是否正在手动拖拽改尺寸（按住鼠标 + 2.0 的缩放手柄） */
function userIsResizing(node) {
    return pointerHeld || !!node.__xbUserResizing;
}

// 全局记录「鼠标是否按下」：只有按住鼠标拖拽才会改变尺寸，其余变化一律是自动的。
let pointerHeld = false;
const pinWatchers = new Set();

function hookGlobalPointer() {
    if (window.__xbPinPointerHooked) return;
    window.__xbPinPointerHooked = true;
    window.addEventListener("pointerdown", () => { pointerHeld = true; }, true);
    const release = () => {
        pointerHeld = false;
        // 松手那一刻把当前尺寸认作用户设定（拖拽可能比轮询更快结束）
        for (const node of pinWatchers) {
            if (!node.graph) { pinWatchers.delete(node); continue; }
            writePin(node, node.size);
        }
    };
    window.addEventListener("pointerup", release, true);
    window.addEventListener("pointercancel", release, true);
}

/**
 * 把节点尺寸钉回基准值。
 * 用户正在拖拽 → 把当前尺寸当成新的基准（这就是「手动调整」的唯一合法来源）。
 */
function enforcePinnedSize(node) {
    const pin = readPin(node);
    if (!pin || node.flags?.collapsed) return false;
    const w = Math.round(Number(node.size?.[0]));
    const h = Math.round(Number(node.size?.[1]));
    if (!(w > 0 && h > 0)) return false;
    if (w === pin[0] && h === pin[1]) return false;
    if (userIsResizing(node)) {
        writePin(node, node.size);
        return false;
    }
    node.setSize([pin[0], pin[1]]);
    node.graph?.setDirtyCanvas?.(true, true);
    return true;
}

/** 读取布尔开关部件；缺失时返回 fallback（老工作流没保存该项时按默认走） */
export function readToggle(node, name, fallback = true) {
    const w = (node.widgets || []).find((x) => x && (x.name === name || x.label === name));
    if (!w) return fallback;
    const v = w.value;
    if (v === false || v === 0 || v === "false" || v === "0") return false;
    return !!v;
}

/** 收集本节点上的所有 <video>：2.0 在节点 DOM 里，经典模式在 node.videoContainer 里 */
export function collectVideos(node) {
    const found = new Set();
    try {
        const root = node.domElement?.closest?.("[data-node-id]") ||
            document.querySelector(`[data-node-id="${node.id}"]`);
        if (root) for (const v of root.querySelectorAll("video")) found.add(v);
    } catch (_) { /* ignore */ }
    try {
        const box = node.videoContainer;
        if (box) {
            if (box.tagName === "VIDEO") found.add(box);
            for (const v of box.querySelectorAll?.("video") || []) found.add(v);
        }
    } catch (_) { /* ignore */ }
    return found;
}

/** 经典模式：预览部件默认按视频分辨率给最小宽高，导致节点无法缩小。这里放开下限。 */
export function relaxPreviewMinSize(node) {
    const w = previewWidget(node);
    if (!w || w.__xbMinRelaxed) return;
    // 重新赋值一次以触发属性 setter：把前端当前的实现包成 clamp 版本
    const cur = w.computeLayoutSize;
    if (typeof cur === "function") w.computeLayoutSize = cur;
    w.__xbMinRelaxed = true;
}

/** 找到视频预览部件（前端 addVideoDomWidget 用 "video-preview"；旧版是 "videopreview"） */
function previewWidget(node) {
    return (node.widgets || []).find(
        (x) => x && (x.name === "video-preview" || x.name === "videopreview"),
    );
}

/** 视频元素（经典模式在 node.videoContainer 里） */
function previewVideo(node) {
    try {
        const box = node.videoContainer;
        return box?.tagName === "VIDEO" ? box : box?.querySelector?.("video") || null;
    } catch (_) {
        return null;
    }
}

/** 把前端给的 computeLayoutSize 包一层：最小宽高归零，预览只吃节点里现有的空余高度，绝不撑大节点 */
function clampLayoutFn(fn) {
    return function (...args) {
        let r;
        try { r = fn.apply(this, args); } catch (_) { r = undefined; }
        return { ...(r || {}), minHeight: CLASSIC_PREVIEW_MIN, minWidth: CLASSIC_PREVIEW_MIN };
    };
}

/**
 * 用属性拦截把「video-preview」部件的 computeLayoutSize 永久套上 clamp。
 * 必须这样做的原因：前端的 addVideoDomWidget 是「先 addDOMWidget、返回后才赋值
 * computeLayoutSize」，所以事后补丁会晚一帧，部件第一次参与排版时仍按视频尺寸
 * 把节点撑高（经典模式下 l > t 就 setSize）。
 */
function hookPreviewWidgetCreation(node) {
    if (node.__xbPreviewHooked) return;
    node.__xbPreviewHooked = true;
    const orig = node.addDOMWidget;
    if (typeof orig !== "function") return;
    node.addDOMWidget = function (name, type, element, options) {
        const w = orig.apply(this, arguments);
        if (w && (name === "video-preview" || name === "videopreview")) {
            let inner = null;
            try {
                Object.defineProperty(w, "computeLayoutSize", {
                    configurable: true,
                    get() { return inner; },
                    set(fn) { inner = typeof fn === "function" ? clampLayoutFn(fn) : fn; },
                });
                w.__xbMinRelaxed = true;
            } catch (_) { /* ignore */ }
        }
        return w;
    };
}

/** Nodes 2.0：预览组件自带 220px 最小高度（min-h-55），会把节点撑住缩不下去，这里收到 80px。 */
function relaxNodes2PreviewMinSize(node) {
    let root = null;
    try {
        root = node.domElement?.closest?.("[data-node-id]") ||
            document.querySelector(`[data-node-id="${node.id}"]`);
    } catch (_) { return; }
    if (!root) return;
    const minH = `${MIN_PREVIEW}px`;
    for (const el of root.querySelectorAll(".video-preview")) {
        if (el.style.minHeight !== minH) el.style.minHeight = minH;
        if (el.style.minWidth !== "0px") el.style.minWidth = "0px";
    }
}

/**
 * 给节点上的视频预览绑定 自动播放 / 悬停出声，并固定节点尺寸。
 * @param {object} node LiteGraph 节点
 * @param {{autoplayWidget?: string, onApply?: (node: object) => void}} options
 */
export function setupVideoPreview(node, options = {}) {
    const { autoplayWidget = "autoplay", onApply } = options;

    const tryPlay = (v) => {
        try {
            const p = v.play?.();
            if (p && typeof p.catch === "function") p.catch(() => { /* 自动播放被拦截时保持暂停 */ });
        } catch (_) { /* ignore */ }
    };

    // ── 尺寸固定：记录基准，之后只由用户拖拽改写 ──────────────────────
    const installSizePin = () => {
        // 载入工作流时先把「工作流里保存的尺寸」定为基准
        const origConfigure = node.onConfigure;
        node.onConfigure = function (info) {
            const r = origConfigure?.apply(this, arguments);
            if (!readPin(this)) writePin(this, info?.size || this.size);
            else enforcePinnedSize(this);
            return r;
        };
        if (!readPin(node)) writePin(node, node.size);
        pinWatchers.add(node);
        hookGlobalPointer();

        // Nodes 2.0：拖拽右下角等手柄时标记「用户正在调整」
        const watchDomHandle = () => {
            const root = node.domElement?.closest?.(".lg-node")
                || document.querySelector(`.lg-node[data-node-id="${node.id}"]`);
            if (!root || root.__xbPinWatched) return;
            root.__xbPinWatched = true;
            root.addEventListener("pointerdown", (e) => {
                const el = e.target?.closest?.("[aria-label]");
                if (!el) return;
                const label = el.getAttribute("aria-label") || "";
                if (!/调整大小|resize/i.test(label)) return;
                node.__xbUserResizing = true;
                setTimeout(() => { node.__xbUserResizing = false; }, 1500);
            }, true);
        };
        watchDomHandle();
    };

    const apply = () => {
        try {
            if (!node.graph) return;
            onApply?.(node);
            relaxPreviewMinSize(node);
            relaxNodes2PreviewMinSize(node);
            enforcePinnedSize(node);     // 预览/视频绝不允许改变节点尺寸
            const autoplay = readToggle(node, autoplayWidget);
            for (const v of collectVideos(node)) {
                let st = v.__xbVideoPreview;
                if (!st) {
                    st = v.__xbVideoPreview = { src: "", autoplay: null };
                    v.autoplay = false;        // 由本脚本控制，避免前端/浏览器自行播放
                    v.playsInline = true;
                    v.muted = true;            // 先静音：浏览器才允许自动播放
                    v.addEventListener("mouseenter", () => { v.muted = false; });
                    v.addEventListener("mouseleave", () => { v.muted = true; });
                }
                const src = v.currentSrc || v.src || "";
                if (src && src !== st.src) {
                    st.src = src;
                    st.autoplay = autoplay;
                    v.muted = true;            // 新视频重新从静音开始
                    if (autoplay) tryPlay(v);
                } else if (st.autoplay !== autoplay) {
                    st.autoplay = autoplay;
                    if (autoplay) tryPlay(v);
                    else v.pause?.();
                }
            }
        } catch (_) { /* ignore */ }
    };

    apply();
    hookPreviewWidgetCreation(node);
    installSizePin();
    relaxPreviewMinSize(node);
    const timer = setInterval(apply, 400);

    // 开关一改立刻生效（不等下一次轮询）
    const w = (node.widgets || []).find((x) => x && x.name === autoplayWidget);
    if (w) {
        const origCb = w.callback;
        w.callback = function (...args) {
            const r = origCb?.apply?.(this, args);
            apply();
            return r;
        };
    }

    const origRemoved = node.onRemoved;
    node.onRemoved = function (...args) {
        clearInterval(timer);
        return origRemoved?.apply?.(this, args);
    };
}
