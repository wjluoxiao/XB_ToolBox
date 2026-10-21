import { app } from "../../scripts/app.js";
import { setupVideoPreview } from "./xb_video_preview.js";
import { allNodes } from "./xb_compat.js";

// ============================================================
// XB-BOX - 🎬 保存视频 —— 预览播放行为
//   自动播放 / 悬停出声 / 经典模式放开预览尺寸下限 由 xb_video_preview.js 统一处理；
//   本文件额外把动态下拉子项的英文名补成中文（codec → 编解码器）。
//   另外补上「文件名前缀」的标记展开（核心 SaveImage/SaveVideo 是在前端
//   Comfy.SaveImageExtraOutput 里做的，自定义保存节点不在那个白名单里，
//   不展开就会生成 output/…/%date:yyyy-MM-dd%/ 这种非法目录名）。
// ============================================================

const NODE_TYPE = "XB_SaveVideo";
// 同类的自定义保存节点也一起补上
const SAVE_NODES = new Set([NODE_TYPE, "XB_VideoCombine"]);

// 与核心前端一致的日期标记规则：d / dd / M / MM / h / hh / m / mm / s / ss / yy / yyyy
// 额外支持 H / HH（24 小时制），写 yyyy-MM-dd_HH-mm-ss 也能得到预期结果
const DATE_PARTS = {
    d: (t) => t.getDate(),
    M: (t) => t.getMonth() + 1,
    H: (t) => t.getHours(),
    h: (t) => t.getHours(),
    m: (t) => t.getMinutes(),
    s: (t) => t.getSeconds(),
};

function formatDate(fmt, when = new Date()) {
    return String(fmt).replace(/dd?|MM?|HH?|hh?|mm?|ss?|yyy?y?/g, (tok) => {
        if (tok === "yy") return String(when.getFullYear()).slice(-2);
        if (tok === "yyyy") return String(when.getFullYear());
        const f = DATE_PARTS[tok[0]];
        if (!f) return tok;
        return String(f(when)).padStart(tok.length, "0");
    });
}

/** %date:yyyy-MM-dd% → 日期；%节点名.控件名% → 该控件的值（与核心 applyTextReplacements 一致） */
function applyTextReplacements(text) {
    if (typeof text !== "string" || !text.includes("%")) return text;
    const nodes = allNodes();
    return text.replace(/%([^%]+)%/g, (full, token) => {
        const seg = token.split(".");
        if (seg.length !== 2) {
            return seg[0].startsWith("date:") ? formatDate(seg[0].slice(5)) : full;
        }
        const [nodeName, widgetName] = seg;
        let hits = nodes.filter((n) => n.properties?.["Node name for S&R"] === nodeName);
        if (!hits.length) hits = nodes.filter((n) => n.title === nodeName);
        if (!hits.length) return full;
        const w = (hits[0].widgets || []).find((x) => x.name === widgetName);
        if (!w) return full;
        return String(w.value ?? "").replace(/[/?<>\\:*|"\u0000-\u001F\u007F]/g, "_");
    });
}

// 动态下拉（如 format 下面的 codec）的子项在界面上取不到后端 display_name，
// 前端会退回成英文名，这里补上中文显示。
const WIDGET_LABELS = [
    [/\.codec$/, "编解码器"],
    [/\.encoding$/, "编码模式"],
    [/\.crf$/, "CRF"],
];

/** 修正嵌套下拉部件的显示名（format 一改动部件可能重建，所以轮询里反复校正） */
function localizeWidgetLabels(node) {
    let changed = false;
    for (const w of node.widgets || []) {
        if (!w || !w.name) continue;
        for (const [re, label] of WIDGET_LABELS) {
            if (re.test(w.name) && w.label !== label) {
                w.label = label;
                changed = true;
            }
        }
    }
    if (changed) node.setDirtyCanvas?.(true, false);
}

/** 给 filename_prefix 挂上标记展开（核心保存节点用 serializeValue 达到同样效果） */
function installPrefixExpansion(node) {
    const w = (node.widgets || []).find((x) => x.name === "filename_prefix");
    if (!w || w.__xbPrefixHook) return;
    w.__xbPrefixHook = true;
    w.serializeValue = () => applyTextReplacements(w.value);
}

// ── 刷新后继续显示上一次生成的视频 ─────────────────────────────────────
// 前端的执行结果只存在内存里（撤销记录里带一份），刷新就丢了；
// 所以跑完把结果记进 node.properties（随工作流保存），载入时再塞回 app.nodeOutputs，
// 前端就会照常建出预览。文件被删掉的情况用一次 HEAD 请求挡掉。

const LAST_OUTPUT_PROP = "xbLastOutput";

function rememberOutput(node, output) {
    const first = output?.images?.[0];
    if (!first?.filename) return;
    node.properties = node.properties || {};
    node.properties[LAST_OUTPUT_PROP] = {
        filename: first.filename,
        subfolder: first.subfolder || "",
        type: first.type || "output",
    };
}

function viewUrl(entry) {
    const q = new URLSearchParams({
        filename: entry.filename,
        subfolder: entry.subfolder || "",
        type: entry.type || "output",
    });
    return `/view?${q}`;
}

async function stillExists(entry) {
    try {
        const r = await fetch(viewUrl(entry), { method: "HEAD" });
        return r.ok;
    } catch (_) {
        return false;
    }
}

/** 把历史结果塞回前端的结果仓库，预览就会像刚跑完一样出现 */
function applyPreview(node, entry) {
    if (!app.nodeOutputs) return;
    app.nodeOutputs[node.id] = {
        images: [{ filename: entry.filename, subfolder: entry.subfolder || "", type: entry.type || "output" }],
        animated: [true],
    };
    // 经典模式：预览部件是在 onDrawBackground（updatePreviews）里惰性创建的，
    // 刚载入工作流时画布往往已经画完了，这里直接踢一脚，并补几次重绘兜底。
    const kick = () => {
        if (!node.graph) return;
        try { node.onDrawBackground?.({}); } catch (_) { /* ignore */ }
        node.graph.setDirtyCanvas?.(true, true);
    };
    kick();
    for (const ms of [120, 500, 1200, 2500]) setTimeout(kick, ms);
}

/** 老工作流里没有记录时，去 /history 找这个节点最后一次的输出 */
async function findInHistory(node) {
    try {
        const res = await fetch("/history?max_items=64");
        const data = await res.json();
        const startTime = (h) => {
            for (const [name, payload] of h?.status?.messages || []) {
                if (name === "execution_start") return Number(payload?.timestamp) || 0;
            }
            return 0;
        };
        const hits = [];
        for (const h of Object.values(data || {})) {
            const img = h?.outputs?.[node.id]?.images?.[0];
            if (!img?.filename) continue;
            const meta = Array.isArray(h.prompt) ? h.prompt[2]?.[node.id] : null;
            if (meta && meta.class_type && meta.class_type !== node.type) continue;
            hits.push({ entry: { filename: img.filename, subfolder: img.subfolder || "", type: img.type || "output" }, ts: startTime(h) });
        }
        hits.sort((a, b) => b.ts - a.ts);
        for (const hit of hits) {
            if (await stillExists(hit.entry)) return hit.entry;
        }
    } catch (_) { /* ignore */ }
    return null;
}

async function restoreLastVideo(node) {
    if (!app.nodeOutputs || app.nodeOutputs[node.id]?.images?.length) return;
    const saved = node.properties?.[LAST_OUTPUT_PROP];
    if (saved?.filename) {
        if (await stillExists(saved)) {
            applyPreview(node, saved);
            return;
        }
        delete node.properties[LAST_OUTPUT_PROP];
    }
    const fromHistory = await findInHistory(node);
    if (fromHistory) {
        node.properties = node.properties || {};
        node.properties[LAST_OUTPUT_PROP] = fromHistory;
        applyPreview(node, fromHistory);
    }
}

app.registerExtension({
    name: "XB_ToolBox.SaveVideo",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (!SAVE_NODES.has(nodeData?.name)) return;
        const origCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = origCreated?.apply(this, arguments);
            installPrefixExpansion(this);
            if (nodeData?.name !== NODE_TYPE) return r;
            const origExec = this.onExecuted;
            this.onExecuted = function (output) {
                rememberOutput(this, output);
                return origExec?.apply(this, arguments);
            };
            try {
                setupVideoPreview(this, { onApply: localizeWidgetLabels });
            } catch (e) {
                console.warn("[XB-BOX 保存视频] 预览控制初始化失败", e);
            }
            return r;
        };
    },

    async loadedGraphNode(node) {
        if (node?.type !== NODE_TYPE) return;
        setTimeout(() => { restoreLastVideo(node); }, 600);
    },
});
