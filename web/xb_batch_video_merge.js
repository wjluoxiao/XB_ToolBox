import { app } from "../../scripts/app.js";
import { setupVideoPreview } from "./xb_video_preview.js";

// ============================================================
// XB-BOX - 🎬 视频批量拼接 —— 预览播放行为
//   1. 播放行为与「XB-BOX - 🎬 保存视频」一致：新视频静音自动播放，
//      鼠标指上才出声，移出立刻静音（统一走 xb_video_preview.js）。
//   2. 刷新后继续显示上一次的预览：前端的执行结果只存在内存里，刷新就丢，
//      所以跑完把预览列表（各分段 + 拼接结果）记进 node.properties（随工作流保存），
//      载入时确认文件还在再塞回 app.nodeOutputs，前端就会照常重建预览；
//      老工作流没有记录时再去 /history 里找一次。
// ============================================================

const NODE_TYPE = "XB_BatchVideoMerge";

const LAST_OUTPUT_PROP = "xbLastOutput";

/** [{filename, subfolder, type}] —— 只保留能定位到文件的项 */
function toEntries(items) {
    return (items || [])
        .filter((i) => i?.filename)
        .map((i) => ({ filename: i.filename, subfolder: i.subfolder || "", type: i.type || "output" }));
}

function rememberOutput(node, output) {
    const list = toEntries(output?.images || output?.video);
    if (!list.length) return;
    node.properties = node.properties || {};
    // 内容没变就不碰 properties，免得工作流一直显示"已修改"
    if (JSON.stringify(node.properties[LAST_OUTPUT_PROP]) === JSON.stringify(list)) return;
    node.properties[LAST_OUTPUT_PROP] = list;
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

/** 过滤掉已经被删掉的文件（例如关掉「保留分段」后分段文件不存在了）；限流避免一次打爆服务端 */
const CHECK_CONCURRENCY = 6;

async function existingEntries(list) {
    const flags = new Array(list.length).fill(false);
    let next = 0;
    const worker = async () => {
        while (next < list.length) {
            const i = next++;
            flags[i] = await stillExists(list[i]);
        }
    };
    await Promise.all(Array.from({ length: Math.min(CHECK_CONCURRENCY, list.length) }, worker));
    return list.filter((_, i) => flags[i]);
}

/** 把历史结果塞回前端的结果仓库，预览就会像刚跑完一样出现 */
function applyPreview(node, list) {
    if (!app.nodeOutputs) return;
    app.nodeOutputs[node.id] = {
        images: list.map((e) => ({ filename: e.filename, subfolder: e.subfolder || "", type: e.type || "output" })),
        animated: list.map(() => true),
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
            const list = toEntries(h?.outputs?.[node.id]?.images);
            if (!list.length) continue;
            const meta = Array.isArray(h.prompt) ? h.prompt[2]?.[node.id] : null;
            if (meta && meta.class_type && meta.class_type !== node.type) continue;
            hits.push({ list, ts: startTime(h) });
        }
        hits.sort((a, b) => b.ts - a.ts);
        for (const hit of hits) {
            const ok = await existingEntries(hit.list);
            if (ok.length) return ok;
        }
    } catch (_) { /* ignore */ }
    return null;
}

async function restoreLastOutput(node) {
    if (!node?.graph || !app.nodeOutputs) return;
    const cur = app.nodeOutputs[node.id];
    if (cur && (cur.images?.length || cur.video?.length)) return;

    const saved = node.properties?.[LAST_OUTPUT_PROP];
    if (Array.isArray(saved) && saved.length) {
        const ok = await existingEntries(toEntries(saved));
        if (ok.length) {
            if (ok.length !== saved.length) node.properties[LAST_OUTPUT_PROP] = ok;
            applyPreview(node, ok);
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
    name: "XB_ToolBox.BatchVideoMerge",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData?.name !== NODE_TYPE) return;
        const origCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = origCreated?.apply(this, arguments);
            const origExec = this.onExecuted;
            this.onExecuted = function (output) {
                try { rememberOutput(this, output); } catch (e) { console.warn("[XB-BOX 视频批量拼接]", e); }
                return origExec?.apply(this, arguments);
            };
            try {
                setupVideoPreview(this);
            } catch (e) {
                console.warn("[XB-BOX 视频批量拼接] 预览控制初始化失败", e);
            }
            return r;
        };
    },

    async loadedGraphNode(node) {
        if (node?.type !== NODE_TYPE) return;
        setTimeout(() => { restoreLastOutput(node); }, 600);
    },
});
