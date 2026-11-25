import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import { setupVideoPreview, collectVideos } from "./xb_video_preview.js";

// ============================================================
// XB-BOX - 🎬 加载视频 —— 预览/上传
//   预览行为与官方 Load Video 对齐：
//     · 参数全默认 → 后端 /xb/videopreview 直接返回原片，和官方一模一样
//       （尺寸、时长、进度条都由原片决定）；
//     · 改了 帧率 / 帧数上限 / 宽 / 高 / 跳过帧 / 间隔取帧 → 预览按新参数重新转码，
//       实时显示调节后的样子（尺寸 = 实际输出尺寸，不缩放）。
//   另外：上传按钮改名「选择上传视频」；自动播放 / 悬停出声 / 尺寸固定走 xb_video_preview.js。
// ============================================================

const NODE_TYPE = "XB_LoadVideo";
const UPLOAD_LABEL = "选择上传视频";
const PARAM_INPUTS = [
    "file", "force_rate", "custom_width", "custom_height",
    "frame_load_cap", "skip_first_frames", "select_every_nth",
];
const DEBOUNCE_MS = 220;    // 拖数值时合并成一次请求

function widgetValue(node, name) {
    const w = (node.widgets || []).find((x) => x && x.name === name);
    return w ? w.value : undefined;
}

/** 当前参数快照：预览地址只由它决定 */
function paramsKey(node) {
    const file = widgetValue(node, "file");
    if (!file) return null;
    return JSON.stringify([
        file,
        Number(widgetValue(node, "force_rate")) || 0,
        Number(widgetValue(node, "custom_width")) || 0,
        Number(widgetValue(node, "custom_height")) || 0,
        Number(widgetValue(node, "frame_load_cap")) || 0,
        Number(widgetValue(node, "skip_first_frames")) || 0,
        Math.max(1, Number(widgetValue(node, "select_every_nth")) || 1),
    ]);
}

function previewUrl(node) {
    const file = widgetValue(node, "file");
    if (!file) return null;
    const q = new URLSearchParams({
        filename: file,
        type: "input",
        force_rate: String(Number(widgetValue(node, "force_rate")) || 0),
        custom_width: String(Number(widgetValue(node, "custom_width")) || 0),
        custom_height: String(Number(widgetValue(node, "custom_height")) || 0),
        frame_load_cap: String(Number(widgetValue(node, "frame_load_cap")) || 0),
        skip_first_frames: String(Number(widgetValue(node, "skip_first_frames")) || 0),
        select_every_nth: String(Math.max(1, Number(widgetValue(node, "select_every_nth")) || 1)),
        v: String(Date.now()),
    });
    return api.apiURL("/xb/videopreview?" + q.toString());
}

function normalize(url) {
    try { return new URL(url, window.location.href).href; } catch (_) { return String(url || ""); }
}

/** 经典模式的「上传」按钮默认沿用输入框的名字，这里改成更直白的文案 */
function labelUploadButton(node) {
    const w = (node.widgets || []).find((x) => x && x.name === "upload");
    if (!w || w.label === UPLOAD_LABEL) return;
    w.label = UPLOAD_LABEL;
    node.setDirtyCanvas?.(true, false);
}

function setupPreviewSync(node) {
    let lastKey = null;
    let lastUrl = null;
    let failedKey = null;      // 这套参数转码失败 → 不再反复请求，直到参数/文件变化
    let timer = null;

    const apply = () => {
        if (!node.graph) return;
        const key = paramsKey(node);
        if (!key) return;
        if (failedKey && failedKey === key) return;
        if (key !== lastKey || !lastUrl) {
            lastKey = key;
            lastUrl = previewUrl(node);
        }
        if (!lastUrl) return;
        const target = normalize(lastUrl);
        for (const v of collectVideos(node)) {
            if (normalize(v.currentSrc || v.src) === target) continue;
            try { v.src = lastUrl; } catch (_) { /* ignore */ }
        }
    };

    /** 我们的转码地址出错 → 记下这套参数别再试，并退回官方原片（不弹错误框） */
    const bindError = (v) => {
        if (!v || v.__xbPreviewErrorBound) return;
        v.__xbPreviewErrorBound = true;
        v.addEventListener("error", () => {
            const src = normalize(v.currentSrc || v.src);
            if (!lastUrl || src !== normalize(lastUrl)) return;
            failedKey = lastKey;
            lastKey = null;
            lastUrl = null;
            const q = new URLSearchParams({
                filename: widgetValue(node, "file") || "",
                type: "input",
                rand: String(Date.now()),
            });
            try { v.src = api.apiURL("/view?" + q.toString()); } catch (_) { /* ignore */ }
        });
    };

    const schedule = () => {
        clearTimeout(timer);
        timer = setTimeout(apply, DEBOUNCE_MS);
    };

    // 部件回调：改参数立刻同步（拖数值时用 debounce 合并）
    for (const name of PARAM_INPUTS) {
        const w = (node.widgets || []).find((x) => x && x.name === name);
        if (!w) continue;
        const orig = w.callback;
        w.callback = function (...args) {
            const r = orig?.apply?.(this, args);
            schedule();
            return r;
        };
    }

    // 参数从上游连线进来时部件不会触发回调：由 setupVideoPreview 的 400ms onApply 兜住

    // 执行完成后官方预览会把 src 换回原片：新一轮同步把它拉回按参数转码的版本
    const onExecuted = () => { lastKey = null; apply(); };
    try { api.addEventListener("executed", onExecuted); } catch (_) { /* ignore */ }

    const origConfigure = node.onConfigure;
    node.onConfigure = function (...args) {
        const r = origConfigure?.apply?.(this, args);
        failedKey = null;
        lastKey = null;
        schedule();
        return r;
    };

    const origRemoved = node.onRemoved;
    node.onRemoved = function (...args) {
        clearTimeout(timer);
        try { api.removeEventListener("executed", onExecuted); } catch (_) { /* ignore */ }
        return origRemoved?.apply?.(this, args);
    };

    return { apply, bindError, hasSynced: () => !!lastUrl || !!failedKey };
}

app.registerExtension({
    name: "XB_ToolBox.LoadVideo",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData?.name !== NODE_TYPE) return;
        const origCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = origCreated?.apply(this, arguments);
            try {
                const sync = setupPreviewSync(this);
                setupVideoPreview(this, {
                    onApply: (n) => {
                        labelUploadButton(n);
                        for (const v of collectVideos(n)) sync.bindError(v);
                        sync.apply();      // 参数快照变了才换地址；没变就只做「src 拉回」
                    },
                });
            } catch (e) {
                console.warn("[XB-BOX 加载视频] 预览初始化失败", e);
            }
            return r;
        };
    },
});
