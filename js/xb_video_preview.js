// ============================================================
// XB-BOX 视频预览共用逻辑（保存视频 / 加载视频 共用）
//   1. 「自动播放」开关：开 = 视频就绪后自动开始（静音，浏览器允许自动播放）；
//      关 = 保持暂停，等用户点播放。只在「新视频 / 开关变化」时动作，不打断用户手动暂停。
//   2. 鼠标悬停在画面上才出声，移出立刻静音。
//   3. 视频预览不允许反过来撑大节点：
//      经典模式放开部件的 computeLayoutSize 下限；Nodes 2.0 放开 .video-preview 的 220px 最小高度。
// ============================================================

export const MIN_PREVIEW = 80;     // 经典模式：视频预览部件允许的最小宽/高

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
    const w = (node.widgets || []).find(
        (x) => x && (x.name === "video-preview" || x.name === "videopreview"),
    );
    if (!w || w.__xbMinRelaxed) return;
    const orig = w.computeLayoutSize;
    if (typeof orig !== "function") return;
    w.computeLayoutSize = function (...args) {
        let r;
        try { r = orig.apply(this, args); } catch (_) { r = undefined; }
        const minHeight = Math.min(Number(r && r.minHeight) || MIN_PREVIEW, MIN_PREVIEW);
        const minWidth = Math.min(Number(r && r.minWidth) || MIN_PREVIEW, MIN_PREVIEW);
        return { ...(r || {}), minHeight, minWidth };
    };
    w.__xbMinRelaxed = true;
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
                } else if (st.autoplay !== autoplay) {
                    st.autoplay = autoplay;
                    if (autoplay) tryPlay(v);
                    else v.pause?.();
                }
            }
        } catch (_) { /* ignore */ }
    };

    apply();
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
