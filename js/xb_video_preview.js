// ============================================================
// XB-BOX 视频预览共用逻辑（保存视频 / 加载视频 共用）
//   1. 「自动播放」开关：开 = 视频就绪后自动开始（静音，浏览器允许自动播放）；
//      关 = 保持暂停，等用户点播放。只在「新视频 / 开关变化」时动作，不打断用户手动暂停。
//   2. 鼠标悬停在画面上才出声，移出立刻静音。
//   3. 视频预览不允许反过来撑大节点：
//      经典模式用属性拦截把部件的 computeLayoutSize 最小宽高收到 MIN_PREVIEW
//      （前端是「先 addDOMWidget、返回后才赋值 computeLayoutSize」，所以必须在赋值那一刻收），
//      Nodes 2.0 放开 .video-preview 的 220px 最小高度。
// ============================================================

export const MIN_PREVIEW = 80;     // Nodes 2.0：.video-preview 的 CSS 最小高度
// 经典模式下预览部件不允许向节点「要」任何额外高度：
// 一旦要了，节点就会被 setSize 撑高（且高度随视频分辨率变化）。
// 这里用一个很小的负值 (-8) 抵消经典排版给「弹性部件」固定加的 8px 内边距，
// 让预览只吃节点里现有的空余高度、节点尺寸完全不变（和 Nodes 2.0 一致）。
const CLASSIC_PREVIEW_MIN = -8;

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
        const before = Array.isArray(this.size) ? this.size.slice() : null;
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
            // 挂上预览会让经典模式的排版多出 8px 左右（widget 行的固定间距）；
            // 这一丁点补偿也回退掉，节点尺寸才真正保持不变（和 Nodes 2.0 一致）。
            if (before) {
                setTimeout(() => {
                    if (!this.graph || !Array.isArray(this.size)) return;
                    const grew = this.size[1] - before[1];
                    if (grew > 0 && grew <= 16) this.setSize([this.size[0], before[1]]);
                }, 500);
            }
        }
        return w;
    };
}

/**
 * 修掉已经被撑高的节点：只有当「多出来的高度」正好等于按视频尺寸算出来的需求时才回收，
 * 这样用户自己手动拉高的节点不会被误改。
 */
function repairAutoGrown(node) {
    const v = previewVideo(node);
    const natural = node.computeSize?.();
    if (!v || !natural || !v.videoWidth || !v.videoHeight) return false;
    const target = Number(natural[1]) || 0;
    const excess = (node.size?.[1] || 0) - target;
    if (target <= 0 || excess < 40) return false;
    // 老版本会把 minHeight 直接设成「按视频比例算出来的高度」
    const demand = Math.max((node.size?.[0] || 256) / (v.videoWidth / v.videoHeight), 64) - CLASSIC_PREVIEW_MIN;
    if (demand <= 0 || Math.abs(excess - demand) > Math.max(20, demand * 0.2)) return false;
    node.setSize([node.size[0], target]);
    node.graph?.setDirtyCanvas?.(true, true);
    return true;
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
 * 给节点上的视频预览绑定 自动播放 / 悬停出声。
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

    const apply = () => {
        try {
            if (!node.graph) return;
            onApply?.(node);
            relaxPreviewMinSize(node);
            relaxNodes2PreviewMinSize(node);
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
                    repairAutoGrown(node);     // 经典模式：回收被「按视频尺寸撑高」的节点高度
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
