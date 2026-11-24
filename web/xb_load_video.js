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
//   4. 播放器出错时自愈：转码流 → 原片 → 换新流；官方组件已经进入错误态（<video>
//      被移除）时自动重建这一个节点的预览，不用再刷新整个页面。
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
// 例如 XB_VideoParamsMaster 的 Frames 输出对应的是 length 部件，标签叫「长度」）
const OUTPUT_ALIASES = {
    frames: ["length", "frame_count", "frames", "num_frames", "长度", "帧数", "总帧数"],
    fps: ["fps", "frame_rate", "framerate", "帧率"],
    fps_float: ["fps_float", "fpsfloat", "帧率（浮点）", "帧率(小数)", "帧率（小数）"],
    width: ["width", "宽度"],
    height: ["height", "高度"],
};

const normKey = (s) => String(s || "").toLowerCase().replace(/[\s_\-]/g, "");

// ── 海螺系列参数节点（同时输出 Width / Height / Frames）──
// 这类节点上**没有** width / height / frames 部件，只有 aspect_ratio / megapixels / duration…
// 必须用与后端 process() 完全相同的公式现场算，否则会掉进下面的兜底逻辑按槽位瞎猜：
//   · Height(槽位1) 撞上 megapixels → 1.0 → 2×2 的畸形预览
//   · Frames(槽位2) 撞上 multiple   → 永远 32 帧 → 帧数上限「不受控制」
const PARAM_NODE_TYPES = new Set([
    "JZL_HailuoH3VideoParams",
    "JZL_HailuoH3VideoParamsPro",
    "XB_HailuoH3VideoParams",
]);

/** Python round() 是「四舍六入五取偶」，JS Math.round 是五入 —— 必须一致，否则预览与实际输出差一档 */
function roundHalfEven(x) {
    const f = Math.floor(x);
    const diff = x - f;
    if (diff > 0.5) return f + 1;
    if (diff < 0.5) return f;
    return f % 2 === 0 ? f : f + 1;
}

function aspectRatioText(node) {
    const w = (node.widgets || []).find((x) => x && x.name === "aspect_ratio");
    return String((w && w.value) || "16:9 (Widescreen)");
}

function ratioOf(text) {
    const m = String(text || "").match(/(\d+(?:\.\d+)?)\s*[:：]\s*(\d+(?:\.\d+)?)/);
    if (!m) return [16, 9];
    const a = Number(m[1]);
    const b = Number(m[2]);
    return a > 0 && b > 0 ? [a, b] : [16, 9];
}

/** 与节点 process() 完全一致：MP×1024² → 按比例开方 → 对齐 multiple */
function computeResolution(node) {
    const [wr, hr] = ratioOf(aspectRatioText(node));
    const mp = widgetNum(node, "megapixels", 1.0) || 1.0;
    const mult = Math.max(1, Math.round(widgetNum(node, "multiple", 32) || 32));
    const total = mp * 1024 * 1024;
    const scale = Math.sqrt(total / (wr * hr));
    return {
        width: Math.max(mult, roundHalfEven((wr * scale) / mult) * mult),
        height: Math.max(mult, roundHalfEven((hr * scale) / mult) * mult),
    };
}

/** 与节点 process() 完全一致：时长(秒) × 24fps → 吸附 17k+5 网格 */
function computeFrameCount(node) {
    const dur = widgetNum(node, "duration", 8) || 8;
    const base = Math.max(5, roundHalfEven(dur * 24));
    // JS 的 % 会保留负号（Python 不会），必须再归一化成正数
    return base + (((5 - (base % 17)) % 17) + 17) % 17;
}

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
    const key = normKey(outName);
    const isDim = key === "width" || key === "height" || key === "宽度" || key === "高度";
    const isFrames = key === "frames" || key === "framecount" || key === "numframes"
        || key === "帧数" || key === "总帧数";
    const raw = (w) => (w && w.value != null && w.value !== "" ? w.value : null);
    const ok = (v) => {
        if (v == null || v === "") return false;
        if (!numeric) return true;
        const n = Number(v);
        if (!Number.isFinite(n)) return false;
        // 分辨率不可能小于 16：拦住 megapixels / scale_factor 这类小数被误当成宽高
        if (isDim && n < 16) return false;
        return true;
    };

    // 0) 海螺参数节点：节点上没有 width / height / frames 部件，只能按公式现场算
    if (PARAM_NODE_TYPES.has(src.type)) {
        if (isDim) {
            const r = computeResolution(src);
            return key === "width" || key === "宽度" ? r.width : r.height;
        }
        if (isFrames) return computeFrameCount(src);
    }

    // 1) 输出名 / 别名 对应的部件（名称或中文标签）
    const byName = matchWidgetByOutput(ws, outName, ok, raw);
    if (byName) return raw(byName);

    // 2) 宽高：部件名/标签以 width|height|宽度|高度 结尾也算（如 image_width、出图宽度）
    if (isDim) {
        const tails = (key === "width" || key === "宽度") ? ["width", "宽度"] : ["height", "高度"];
        for (const w of ws) {
            const nk = normKey(w && w.name);
            const lk = normKey(w && w.label);
            if ((tails.some((t) => nk.endsWith(t)) || tails.some((t) => lk.endsWith(t)))
                && ok(raw(w))) return raw(w);
        }
        // 单部件节点（Primitive / rgthree 数值）直接按它取值
        if (ws.length === 1 && ok(raw(ws[0]))) return raw(ws[0]);
        // 再往下猜就会把 megapixels(1.0)、multiple(32) 当成分辨率 → 预览变成 2×2 畸形条。
        // 返回 null 只退回「保持源尺寸」，永远不会错得离谱。
        return null;
    }

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

/** 当前「文件 + 参数」快照：预览地址只由它决定（也是「这套参数走不通」的判定键） */
function previewKey(node) {
    const file = currentFile(node);
    if (!file) return null;
    return JSON.stringify([file, previewParams(node)]);
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

/** 节点 DOM 根（Nodes 2.0）；经典模式返回 null */
function nodeRootEl(node) {
    try {
        const own = node.domElement?.closest?.(".lg-node") || node.domElement;
        if (own) return own;
    } catch (_) { /* ignore */ }
    return document.querySelector(`.lg-node[data-node-id="${node.id}"]`);
}

/**
 * 让官方 VideoPreview 重建 <video>。
 * 它判定失败后会 v-if 移除 <video>（只剩错误框），之后任何脚本都改不回来，只能刷新页面。
 * 做法：先把节点输出摘掉（组件卸载、错误态清零），再挂一份新的 outputs
 * （预览地址会带新的 rand，组件按新地址从头建播放器）——等价于只刷新这一个节点。
 */
function remountPreview(node) {
    const outs = app.nodeOutputs?.[node.id];
    if (!outs?.images?.length) return false;
    const fresh = { ...outs, images: outs.images.map((i) => (i ? { ...i } : i)) };
    try { delete app.nodeOutputs[node.id]; } catch (_) { /* ignore */ }
    setTimeout(() => {
        if (!node.graph || !app.nodeOutputs) return;
        app.nodeOutputs[node.id] = fresh;
    }, 80);
    return true;
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
    let needFreshUrl = false;  // 失败后重试要换一个带新 v= 的地址
    let retryAt = 0;           // 短暂延后下一次 pin（换新地址前给播放器一点时间）
    let remountFails = 0;      // 「重建预览」连续没救回来的次数（拉长重试间隔）
    let lastRemountAt = 0;
    const previewUrl = makePreviewUrlBuilder(node);

    const noteSuccess = () => {
        retryAt = 0;
    };

    const assignSrc = (v, url) => {
        try { v.src = url; } catch (_) { /* ignore */ }
    };

    /**
     * 失败记忆：某个「文件+参数」的转码流坏过一次就记住（只给它一次换新地址的机会）。
     * 没有这个记忆的话，退回原片后 200ms 轮询又会把地址换成坏掉的转码流 → 反复报错，
     * 表现就是「频繁提示视频加载失败」。参数/文件一变（key 变化）自动重新尝试。
     */
    const retried = new Set();     // 已经换过一次新地址的 key
    const failed = new Set();      // 确认走不通的 key → 这套参数只用原片
    const key = () => previewKey(node);

    /** 让播放器回到官方原片预览（原片走 /view，支持 Range/拖动，最稳） */
    const useOfficial = () => {
        lastUrl = null;
        const fb = officialUrl(currentFile(node));
        if (!fb) return false;
        for (const v of collectVideos(node)) {
            if (normalize(v.currentSrc || v.src) === normalize(fb)) continue;
            assignSrc(v, fb);
        }
        return true;
    };

    /**
     * 播放器报错时的兜底：转码流坏 → 换一次新地址；再坏 → 这套参数永久用原片。
     * 返回 true 表示已经处理（调用方要拦下这次 error，别让官方组件移除 <video>）。
     */
    const healVideo = (v) => {
        const src = normalize(v.currentSrc || v.src || v.getAttribute?.("src") || "");
        if (!src) return false;
        const k = key();
        if (!k) return false;

        // 原片都放不出来 → 文件本身有问题，交给官方显示错误（换什么都不管用）
        const fb = officialUrl(currentFile(node));
        if (fb && src === normalize(fb)) return false;

        // 1) 转码流第一次失败：换一个带新 v= 的地址再试一次（可能只是这一份流坏了）
        if (!retried.has(k)) {
            retried.add(k);
            needFreshUrl = true;
            retryAt = Date.now() + 400;
            return true;
        }

        // 2) 还是失败：这套参数不再用转码流，永久退回原片
        failed.add(k);
        needFreshUrl = false;
        retryAt = 0;
        useOfficial();
        return true;
    };

    const setPreviewSrc = (url) => {
        lastUrl = url;
        const target = normalize(url);
        for (const v of collectVideos(node)) {
            if (!v.__xbParamBound) {
                v.__xbParamBound = true;
                // 经典模式没有 DOM 根可挂捕获监听，只能靠元素自身的 error 自愈
                v.addEventListener("error", () => { healVideo(v); });
                v.addEventListener("loadeddata", () => {
                    remountFails = 0;
                    // 只有「我们的转码流」放出来了才算这套参数可用；
                    // 原片（兜底）成功不能清掉失败记忆，否则会再次切回坏掉的转码流 → 反复报错
                    if (!lastUrl || normalize(v.currentSrc || v.src) !== normalize(lastUrl)) return;
                    const k = key();
                    if (k) { retried.delete(k); failed.delete(k); }
                    noteSuccess();
                });
            }
            if (normalize(v.src) !== target) assignSrc(v, url);
        }
    };

    // ── 错误态守卫 ─────────────────────────────────────────────────
    // 官方 VideoPreview 一旦报错就 v-if 移除 <video>，之后谁也改不回画面（只能刷新页面）。
    // 所以在捕获阶段拦下 <video> 的 error：只要我们还兜得住，就不让它进入错误态。
    let guardRoot = null;
    const onErrorCapture = (e) => {
        const el = e.target;
        if (!el || el.tagName !== "VIDEO") return;
        let healed = false;
        try { healed = healVideo(el); } catch (_) { healed = false; }
        if (healed) {
            e.stopImmediatePropagation();
            e.stopPropagation();
        }
    };
    const attachGuard = (root) => {
        if (!root || root === guardRoot) return;
        if (guardRoot) {
            try { guardRoot.removeEventListener("error", onErrorCapture, true); } catch (_) { /* ignore */ }
        }
        guardRoot = root;
        root.addEventListener("error", onErrorCapture, true);
    };

    // 万一还是进了错误态（没有 <video> 只剩错误框）→ 自动重建预览，等价于「刷新页面」。
    // 重建后仍失败就逐步拉长间隔，避免对真坏的文件死循环重试。
    const REMOUNT_BACKOFF = [1500, 3000, 6000, 15000, 30000];
    const healTimer = setInterval(() => {
        if (!node.graph) return;
        const root = nodeRootEl(node);
        if (!root) return;
        attachGuard(root);
        if (root.querySelector("video")) return;                 // 画面在，正常
        const errorBox = root.querySelector('[role="alert"]');
        if (!errorBox) return;                                   // 还没渲染预览
        const wait = REMOUNT_BACKOFF[Math.min(remountFails, REMOUNT_BACKOFF.length - 1)];
        if (Date.now() - lastRemountAt < wait) return;
        if (!remountPreview(node)) return;
        lastRemountAt = Date.now();
        remountFails = Math.min(remountFails + 1, REMOUNT_BACKOFF.length);
        noteSuccess();
        setTimeout(pin, 150);
    }, 600);

    // 官方预览会在执行完成 / 重渲染时把 src 换回原片，这里每轮都拉回「按参数转码」的地址。
    // 参数没变就沿用缓存地址（绝不重新加载，避免播放被打断）；失败后不再纠缠这套参数。
    const pin = () => {
        if (!node.graph) return;
        if (Date.now() < retryAt) return;
        const file = currentFile(node);
        if (!file || !fileIsSelectable(node, file)) return;   // 文件不见了 → 保留官方预览
        const k = key();
        // 这套参数已确认走不通 → 只用原片（参数/文件一变，key 也变，会自动重新尝试）
        if (k && failed.has(k)) { useOfficial(); return; }
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
        clearInterval(healTimer);
        if (guardRoot) {
            try { guardRoot.removeEventListener("error", onErrorCapture, true); } catch (_) { /* ignore */ }
            guardRoot = null;
        }
        try { api.removeEventListener("executed", onExecuted); } catch (_) { /* ignore */ }
        return origRemoved?.apply?.(this, args);
    };

    setupVideoPreview(node, {
        onApply: (n) => {
            labelUploadButton(n);
            // 尽早挂上错误守卫（比 600ms 的看护定时器更早介入，减少进错误态的机会）
            attachGuard(nodeRootEl(n));
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
