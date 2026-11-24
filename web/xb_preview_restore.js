import { app } from "../../scripts/app.js";

// ============================================================
// XB-BOX 视频预览「记忆」——保存视频 / 视频批量拼接 共用
//   前端的执行结果（app.nodeOutputs）只存在内存里，而且是按「节点 id」存的：
//   · 刷新页面就丢；
//   · 复制粘贴节点时新节点换了 id，同样看不到画面。
//   所以跑完把结果记进 node.properties（随工作流/剪贴板一起走），
//   之后在「载入工作流」和「粘贴/克隆」时再塞回 app.nodeOutputs，预览就会重新出现。
//   文件被删掉的情况用一次 HEAD 请求挡掉，避免出现「视频加载失败」错误框。
// ============================================================

export const LAST_OUTPUT_PROP = "xbLastOutput";

/** 统一成 [{filename, subfolder, type}]：兼容单对象（保存视频旧格式）与数组（批量拼接） */
export function toEntries(value) {
    const list = Array.isArray(value) ? value : (value ? [value] : []);
    return list
        .filter((i) => i && typeof i === "object" && i.filename)
        .map((i) => ({ filename: i.filename, subfolder: i.subfolder || "", type: i.type || "output" }));
}

/** 从 onExecuted 的 output 里取出可预览的文件列表 */
export function entriesFromOutput(output) {
    return toEntries(output?.images || output?.video);
}

/** 跑完后把结果记进 properties（随工作流保存、随复制粘贴一起走） */
export function rememberOutput(node, output) {
    const list = entriesFromOutput(output);
    if (!list.length) return;
    node.properties = node.properties || {};
    // 内容没变就不碰 properties，免得工作流一直显示「已修改」
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

// 限流检查，避免一次打爆服务端（拼接节点可能有很多分段）
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
    if (!app.nodeOutputs || !list.length) return;
    app.nodeOutputs[node.id] = {
        images: list.map((e) => ({ filename: e.filename, subfolder: e.subfolder || "", type: e.type || "output" })),
        animated: list.map(() => true),
    };
    // 经典模式：预览部件是在 onDrawBackground（updatePreviews）里惰性创建的，
    // 刚载入工作流 / 刚粘贴时画布往往已经画完了，这里直接踢一脚，并补几次重绘兜底。
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

const restoring = new Set();

/**
 * 把 properties 里记住的预览还原到 app.nodeOutputs。
 * 已经在显示的不动；文件都被删了就清掉记录（不当成错误框）。
 */
export async function restorePreview(node, { fromHistory = true } = {}) {
    if (!node?.graph || !app.nodeOutputs) return;
    if (restoring.has(node)) return;
    const cur = app.nodeOutputs[node.id];
    if (cur && (cur.images?.length || cur.video?.length)) return;

    restoring.add(node);
    try {
        const saved = toEntries(node.properties?.[LAST_OUTPUT_PROP]);
        if (saved.length) {
            const ok = await existingEntries(saved);
            if (ok.length) {
                if (ok.length !== saved.length) node.properties[LAST_OUTPUT_PROP] = ok;
                applyPreview(node, ok);
                return;
            }
            delete node.properties[LAST_OUTPUT_PROP];
        }
        if (!fromHistory) return;
        const fromHist = await findInHistory(node);
        if (fromHist) {
            node.properties = node.properties || {};
            node.properties[LAST_OUTPUT_PROP] = fromHist;
            applyPreview(node, fromHist);
        }
    } finally {
        restoring.delete(node);
    }
}

/**
 * 让节点自动还原预览：载入工作流、粘贴/克隆（都会走 onConfigure）、撤销重做都覆盖。
 * 统一延迟一拍：粘贴时节点 id 是在 configure 之后才定下来的，必须等它定好再写 outputs。
 */
export function installAutoRestore(node) {
    const orig = node.onConfigure;
    node.onConfigure = function (info) {
        const r = orig?.apply(this, arguments);
        setTimeout(() => { restorePreview(this); }, 200);
        return r;
    };
    return orig;
}
