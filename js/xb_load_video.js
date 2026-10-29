import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import { setupVideoPreview, collectVideos } from "./xb_video_preview.js";

// ============================================================
// XB-BOX - 🎬 加载视频 —— 预览/上传行为
//   1. 参数（跳过帧数 / 间隔取帧 / 强制帧率 / 分辨率 / 帧数上限 / 文件）一改，
//      预览窗口立刻换成「按当前参数转码」的版本（后端 /xb/videopreview 实时流式转码）；
//      参数从别的节点连线进来时也会跟着上游变化（200ms 轮询）。
//   2. 自动播放开关、鼠标悬停才出声由 xb_video_preview.js 统一处理。
//   3. 经典模式的「上传」按钮改名为「选择上传视频」。
// ============================================================

const NODE_TYPE = "XB_LoadVideo";
const UPLOAD_LABEL = "选择上传视频";
const PREVIEW_INPUTS = [
    "file", "force_rate", "custom_width", "custom_height",
    "frame_load_cap", "skip_first_frames", "select_every_nth",
];
const DEBOUNCE_MS = 220;
const LINKED_POLL_MS = 200;     // 上游连线参数变化的轮询间隔

function widgetNum(node, name, fallback = 0) {
    const w = (node.widgets || []).find((x) => x && x.name === name);
    const n = Number(w?.value);
    return Number.isFinite(n) ? n : fallback;
}

// 输出名 → 上游部件名/标签的别名（不同节点的输出名和部件名并不一致，
// 例如 XB_VideoParamsMaster 的 Frames 输出对应的是 length 部件，标签叫「帧数」）
const OUTPUT_ALIASES = {
    frames: ["length", "frame_count", "frames", "num_frames", "帧数", "总帧数"],
    fps: ["fps", "frame_rate", "framerate", "帧率"],
    fps_float: ["fps_float", "fpsfloat", "帧率(小数)", "帧率（小数）"],
    width: ["width", "宽度"],
    height: ["height", "高度"],
};

const normKey = (s) => String(s || "").toLowerCase().replace(/[\s_\-]/g, "");

/** 按「输出名 / 别名」去找上游对应的部件（名字或中文标签都算） */
function matchWidgetByOutput(ws, outName, ok, raw) {
    if (!outName) return null;
    const names = new Set([normKey(outName)]);
    for (const [key, list] of Object.entries(OUTPUT_ALIASES)) {
        if (normKey(key) === normKey(outName)) list.forEach((a) => names.add(normKey(a)));
    }
    for (const w of ws) {
        if (w && names.has(normKey(w.name)) && ok(raw(w))) return w;
    }
    for (const w of ws) {
        if (w && names.has(normKey(w.label)) && ok(raw(w))) return w;
    }
    return null;
}

/** 从上游节点里挑出「能代表该输出的值」（兼容各种整数/Primitive/参数面板节点） */
function pickUpstreamValue(src, slot, outName, numeric) {
    const ws = src.widgets || [];
    const raw = (w) => (w && w.value != null && w.value !== "" ? w.value : null);
    const ok = (v) => {
        if (v == null || v === "") return false;
        if (!numeric) return true;
        return Number.isFinite(Number(v));
    };

    // 1) 输出名 / 别名 对应的部件（名称或中文标签）
    const byName = matchWidgetByOutput(ws, outName, ok, raw);
    if (byName) return raw(byName);
    // 2) 名字像数值的部件（rgthree「数量多功能工具」的 value#1 / 中文「数值」等）
    const numericName = /value|val$|数值|值|number|num|int|float|count/i;
    for (const w of ws) {
        if (w && numericName.test(`${w.name || ""}${w.label || ""}`) && ok(raw(w))) return raw(w);
    }
    // 3) 与输出槽位对齐的部件（跳过 type 这类选择器）
    const direct = ws[slot];
    if (direct && !/^(type|类型)$/i.test(direct.name || "") && ok(raw(direct))) return raw(direct);
    // 4) 存档值里第一个合适的
    const arr = src.widgets_values;
    if (Array.isArray(arr)) {
        for (const v of arr) {
            if (ok(v) && (numeric ? typeof v !== "string" || Number.isFinite(Number(v)) : true)) return v;
        }
    }
    return null;
}

/** 取输入端口上「连着的上游值」 */
function linkedValue(node, name, { numeric = true } = {}) {
    const inp = (node.inputs || []).find((i) => i && i.name === name);
    if (!inp || inp.link == null || inp.link < 0) return null;
    const graph = app.graph;
    const link = graph?.getLink?.(inp.link) || graph?.links?.[inp.link];
    if (!link) return null;
    const src = graph.getNodeById?.(link.origin_id);
    if (!src) return null;
    return pickUpstreamValue(src, link.origin_slot ?? 0,
        (src.outputs?.[link.origin_slot ?? 0]?.name || "").toLowerCase(), numeric);
}

/** 端口连着线时以连线上的值为准，否则用本节点的部件值 */
function effectiveNum(node, name, fallback = 0) {
    const linked = linkedValue(node, name);
    if (linked != null) {
        const n = Number(linked);
        if (Number.isFinite(n)) return n;
    }
    return widgetNum(node, name, fallback);
}

function currentFile(node) {
    const linked = linkedValue(node, "file", { numeric: false });
    if (typeof linked === "string" && linked.trim()) return linked;
    return (node.widgets || []).find((x) => x && x.name === "file")?.value || "";
}

function normalize(url) {
    try { return new URL(url, window.location.href).href; } catch (_) { return String(url || ""); }
}

/** 当前参数快照（预览地址只由这些值决定） */
function previewParams(node) {
    return {
        force_rate: effectiveNum(node, "force_rate"),
        select_every_nth: Math.max(1, effectiveNum(node, "select_every_nth", 1)),
        skip_first_frames: effectiveNum(node, "skip_first_frames"),
        frame_load_cap: effectiveNum(node, "frame_load_cap"),
        custom_width: effectiveNum(node, "custom_width"),
        custom_height: effectiveNum(node, "custom_height"),
    };
}

/** 按当前参数生成预览地址（只在参数变化时才换新地址，否则会不断重启播放） */
function makePreviewUrlBuilder(node) {
    let lastKey = null;
    let lastUrl = null;
    const build = (file, params) => {
        const q = new URLSearchParams({
            filename: file,
            type: "input",
            ...Object.fromEntries(Object.entries(params).map(([k, v]) => [k, String(v)])),
            v: String(Date.now()),
        });
        return api.apiURL("/xb/videopreview?" + q.toString());
    };
    return {
        /** force=true：失败重试时换一个带新 v= 的地址，绕开坏掉的那一份流 */
        get(force = false) {
            const file = currentFile(node);
            if (!file) { lastKey = null; lastUrl = null; return null; }
            const params = previewParams(node);
            const key = JSON.stringify([file, params]);
            if (force || !lastUrl || key !== lastKey) {
                lastKey = key;
                lastUrl = build(file, params);
            }
            return lastUrl;
        },
    };
}

/** 文件不在下拉列表里（工作流里的文件已被删/改名）时不要劫持预览，交给官方原片预览 */
function fileIsSelectable(node, file) {
    const w = (node.widgets || []).find((x) => x && x.name === "file");
    const values = w?.options?.values;
    if (!Array.isArray(values) || !values.length) return true;
    return values.includes(file);
}

/** 官方原片预览地址（转码预览失败时退回它，保证播放器不变成错误框） */
function officialUrl(file) {
    const name = String(file || "");
    if (!name) return null;
    const cut = Math.max(name.lastIndexOf("/"), name.lastIndexOf("\\"));
    const subfolder = cut >= 0 ? name.slice(0, cut) : "";
    const filename = cut >= 0 ? name.slice(cut + 1) : name;
    const q = new URLSearchParams({ filename, type: "input", rand: String(Date.now()) });
    if (subfolder) q.set("subfolder", subfolder);
    return api.apiURL("/view?" + q.toString());
}

/** 经典模式的「上传」按钮默认沿用输入框的名字，这里改成更直白的文案 */
function labelUploadButton(node) {
    const w = (node.widgets || []).find((x) => x && x.name === "upload");
    if (!w || w.label === UPLOAD_LABEL) return;
    w.label = UPLOAD_LABEL;
    node.setDirtyCanvas?.(true, false);
}

function setupLoadVideoUi(node) {
    let timer = null;
    let lastUrl = null;
    let lastSetAt = 0;         // 上次给播放器换地址的时刻（用来识别「自己打断自己」）
    let earlyErrors = 0;
    let failures = 0;          // 连续失败次数 → 退避重试，绝不永久放弃
    let retryAt = 0;
    let needFreshUrl = false;  // 失败后重试要换一个带新 v= 的地址
    const previewUrl = makePreviewUrlBuilder(node);

    // 转码预览失败时的退避表（毫秒）：1.5s → 3s → 6s → 12s → 30s 封顶
    const BACKOFF = [1500, 3000, 6000, 12000, 30000];

    const noteFailure = () => {
        failures = Math.min(failures + 1, BACKOFF.length);
        retryAt = Date.now() + BACKOFF[failures - 1];
        needFreshUrl = true;          // 可能只是这一份流坏了，重试时换新地址
    };
    const noteSuccess = () => {
        failures = 0;
        retryAt = 0;
        earlyErrors = 0;
    };

    const setPreviewSrc = (url) => {
        lastUrl = url;
        lastSetAt = Date.now();
        const target = normalize(url);
        for (const v of collectVideos(node)) {
            if (!v.__xbParamBound) {
                v.__xbParamBound = true;
                // 只有「本脚本设置的地址」出错才算失败，官方预览的报错不参与
                v.addEventListener("error", () => {
                    if (!lastUrl || normalize(v.currentSrc || v.src) !== normalize(lastUrl)) return;
                    // 刚换地址就报错，多半是我们自己打断上一份流：换个新地址快速重试一次，先别退回原片
                    if (Date.now() - lastSetAt < 700 && earlyErrors < 2) {
                        earlyErrors += 1;
                        needFreshUrl = true;
                        retryAt = Date.now() + 500;
                        return;
                    }
                    earlyErrors = 0;
                    noteFailure();
                    // 退回原片预览：宁可先看到未抽帧的原片，也不要留一个「视频加载失败」的错误框
                    const fb = officialUrl(currentFile(node));
                    if (fb) {
                        lastUrl = null;
                        try { v.src = fb; } catch (_) { /* ignore */ }
                    }
                });
                v.addEventListener("loadeddata", () => {
                    if (lastUrl && normalize(v.currentSrc || v.src) === normalize(lastUrl)) {
                        earlyErrors = 0;
                        noteSuccess();
                    }
                });
            }
            if (normalize(v.src) !== target) {
                try { v.src = url; } catch (_) { /* ignore */ }
            }
        }
    };

    // 官方预览会在执行完成 / 重渲染时把 src 换回原片，这里每轮都拉回「按参数转码」的地址。
    // 参数没变就沿用缓存地址（绝不重新加载，避免播放被打断）；失败后退避期内不打扰。
    const pin = () => {
        if (!node.graph) return;
        if (Date.now() < retryAt) return;
        const file = currentFile(node);
        if (!file || !fileIsSelectable(node, file)) return;   // 文件不见了 → 保留官方预览
        const fresh = needFreshUrl;
        needFreshUrl = false;
        const url = previewUrl.get(fresh);
        if (url) setPreviewSrc(url);
    };

    // 参数一改就重置失败计数：新参数值得立刻试一次（上次失败可能只是那一份流坏了）
    const schedule = () => {
        clearTimeout(timer);
        noteSuccess();
        timer = setTimeout(() => pin(), DEBOUNCE_MS);
    };

    // 参数是从别的节点连进来时，本节点部件不会触发回调 → 轻量轮询兜住上游变化
    const linkedTimer = setInterval(pin, LINKED_POLL_MS);

    for (const name of PREVIEW_INPUTS) {
        const w = (node.widgets || []).find((x) => x && x.name === name);
        if (!w) continue;
        const orig = w.callback;
        w.callback = function (...args) {
            const r = orig?.apply?.(this, args);
            schedule();
            return r;
        };
    }

    // 执行完成后官方预览会重渲染并抢回 src：第一时间拉回按参数转码的版本
    const onExecuted = () => { noteSuccess(); pin(); };
    try { api.addEventListener("executed", onExecuted); } catch (_) { /* ignore */ }

    // 载入工作流（onConfigure）时也一样
    const origConfigure = node.onConfigure;
    node.onConfigure = function (...args) {
        const r = origConfigure?.apply?.(this, args);
        noteSuccess();
        pin();
        return r;
    };

    const origRemoved = node.onRemoved;
    node.onRemoved = function (...args) {
        clearTimeout(timer);
        clearInterval(linkedTimer);
        try { api.removeEventListener("executed", onExecuted); } catch (_) { /* ignore */ }
        return origRemoved?.apply?.(this, args);
    };

    setupVideoPreview(node, {
        onApply: (n) => {
            labelUploadButton(n);
            pin();
        },
    });
}

app.registerExtension({
    name: "XB_ToolBox.LoadVideo",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData?.name !== NODE_TYPE) return;
        const origCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = origCreated?.apply(this, arguments);
            try {
                setupLoadVideoUi(this);
            } catch (e) {
                console.warn("[XB-BOX 加载视频] 预览控制初始化失败", e);
            }
            return r;
        };
    },
});
