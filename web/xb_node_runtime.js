/**
 * XB-BOX 节点耗时显示 / 节点编号显示
 * ===================================
 * 设置：设置 → XB_ToolBox → 节点相关
 *   · 开启节点耗时显示（默认开）
 *   · 开启节点编号显示（默认开）—— 在节点右上角画出节点编号（#id）
 *
 * 记录每个节点在最近一次执行里的耗时，并显示在节点上：
 *   · 经典模式（画布渲染）：标题栏上方画一个小胶囊（实例级 onDrawForeground）。
 *   · Nodes 2.0（DOM 渲染）：onDrawForeground 根本不执行，所以改成往节点 DOM 里插胶囊，
 *     位置与经典模式一致——**节点左上角外侧**。入口不依赖节点自身结构：新版前端只有部分
 *     节点有「#id | 包名」徽标行（KSampler / VAEDecode 都没有），所以自己画一个同款胶囊。
 *
 * 计时来源是前后端都会发的 `executing` 事件：它表示「某个节点开始执行」，
 * 所以「上一个节点的结束 → 当前节点的开始」就是上一个节点的耗时。
 * 一轮开始（execution_start）清空旧耗时；成功 / 报错 / 中断时补齐最后一个节点。
 */

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import { allNodes, isNodes2 } from "./xb_compat.js";

const SETTING_ID = "xb_toolbox.node_runtime.enabled";
const ID_SETTING_ID = "xb_toolbox.node_id.enabled";
const SEC_KEY = "__xbRuntimeSec";     // 节点上累计的秒数
const CACHED_KEY = "__xbRuntimeCached"; // 本轮直接命中缓存（没真正执行）
const CHIP_ATTR = "data-xb-runtime";  // Nodes 2.0 里那个 DOM 胶囊的标记
const ID_CHIP_ATTR = "data-xb-nodeid"; // Nodes 2.0 里「编号」胶囊的标记
const CACHED_TEXT = "缓存";

let enabled = true;
let showId = true;         // 是否在节点上显示编号

let currentId = null;      // 正在执行的节点执行 id（字符串，如 "3:1"）
let currentStart = 0;      // 开始时刻（performance.now）
let currentLeaf = null;    // 正在执行的那个节点对象
let currentAncestors = []; // 它所在的子图节点（由内到外）
let currentAncestorIds = new Set();
const dirty = new Set();       // 需要立刻刷新显示的节点 id
const ranIds = new Set();      // 有过耗时的节点 id（Vue 重渲染后补回胶囊）

// ── 计时 ───────────────────────────────────────────────────────────────

function rootGraphOf() {
    try {
        return app.graph?.rootGraph || app.rootGraph || app.graph || null;
    } catch (_) {
        return null;
    }
}

/**
 * 把执行 id 解析成节点（与前端 resolveExecutionNode 同逻辑）：
 * 子图里的节点执行 id 是 "3:1" 这种「子图节点id : 内部节点id」的形式，
 * 逐段拆开、遇到子图节点就往下钻。
 */
function resolveExecutionNode(graph, execId) {
    if (!graph || execId == null) return null;
    const id = String(execId);
    for (let i = id.indexOf(":"); i !== -1; i = id.indexOf(":", i + 1)) {
        const parent = graph.getNodeById?.(id.slice(0, i));
        if (!parent?.subgraph) continue;
        const hit = resolveExecutionNode(parent.subgraph, id.slice(i + 1));
        if (hit) return hit;
    }
    const node = graph.getNodeById?.(id);
    return node ? { graph, node } : null;
}

function nodeById(id) {
    if (id == null) return null;
    const hit = resolveExecutionNode(rootGraphOf(), id)?.node;
    if (hit) return hit;
    try {
        return allNodes().find((n) => String(n.id) === String(id)) || null;
    } catch (_) {
        return null;
    }
}

/** 执行 id 的所有祖先子图节点（"3:4:1" → ["3", "3:4"]） */
function ancestorNodes(execId) {
    const out = [];
    const id = String(execId);
    for (let i = id.indexOf(":"); i !== -1; i = id.indexOf(":", i + 1)) {
        const node = resolveExecutionNode(rootGraphOf(), id.slice(0, i))?.node;
        if (node?.subgraph) out.push(node);
    }
    return out;
}

/** executing 事件的 detail：旧版本是 id 字符串，新版本是 {node, display_node} */
function eventNodeId(event) {
    const d = event?.detail ?? event;
    if (d == null) return null;
    if (typeof d === "string" || typeof d === "number") return String(d);
    const id = d.node ?? d.display_node ?? null;
    return id == null ? null : String(id);
}

function addTime(node, sec) {
    if (!node || !(sec > 0)) return;
    node[SEC_KEY] = (Number(node[SEC_KEY]) || 0) + sec;
    delete node[CACHED_KEY];
    ranIds.add(String(node.id));
    dirty.add(String(node.id));
}

/** 把「上一个节点」的耗时结算掉；子图内的节点同时累加到它的祖先子图节点上 */
function flush(now = performance.now()) {
    if (currentId == null) return;
    const sec = (now - currentStart) / 1000;
    addTime(currentLeaf, sec);
    for (const ancestor of currentAncestors) addTime(ancestor, sec);
    currentId = null;
    currentStart = 0;
    currentLeaf = null;
    currentAncestors = [];
    currentAncestorIds = new Set();
}

function clearAll() {
    currentId = null;
    currentStart = 0;
    currentLeaf = null;
    currentAncestors = [];
    currentAncestorIds = new Set();
    dirty.clear();
    ranIds.clear();
    for (const node of allNodes()) {
        if (node[SEC_KEY] !== undefined) delete node[SEC_KEY];
        if (node[CACHED_KEY] !== undefined) delete node[CACHED_KEY];
    }
    for (const el of document.querySelectorAll(`[${CHIP_ATTR}]`)) el.remove();
}

/** 节点当前显示用的秒数（正在执行的节点、以及它所在的子图节点都是实时增长的） */
function liveSeconds(node) {
    const sec = Number(node?.[SEC_KEY]) || 0;
    if (currentId == null || !currentStart || !node) return sec;
    const id = String(node.id);
    if (currentLeaf && id === String(currentLeaf.id)) {
        return sec + (performance.now() - currentStart) / 1000;
    }
    if (currentAncestorIds.has(id)) {
        return sec + (performance.now() - currentStart) / 1000;
    }
    return sec;
}

/** 节点上要显示的文字（空字符串 = 不显示） */
function labelFor(node) {
    if (!enabled) return "";
    const text = fmtDuration(liveSeconds(node));
    if (text) return text;
    return node?.[CACHED_KEY] ? CACHED_TEXT : "";
}

/** 一律用「秒 + 3 位小数」显示（例如 0.012s / 12.345s / 3725.400s） */
function fmtDuration(sec) {
    if (!(sec > 0)) return "";
    return `${sec.toFixed(3)}s`;
}

// ── 经典模式：画在标题栏上方 ────────────────────────────────────────────

function roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.arcTo(x + w, y, x + w, y + r, r);
    ctx.lineTo(x + w, y + h - r);
    ctx.arcTo(x + w, y + h, x + w - r, y + h, r);
    ctx.lineTo(x + r, y + h);
    ctx.arcTo(x, y + h, x, y + h - r, r);
    ctx.lineTo(x, y + r);
    ctx.arcTo(x, y, x + r, y, r);
    ctx.closePath();
}

function drawClassicBadge(ctx, node) {
    const text = labelFor(node);
    if (!text || !ctx) return;
    const th = (typeof LiteGraph !== "undefined" && LiteGraph.NODE_TITLE_HEIGHT) || 30;
    ctx.save();
    ctx.font = "12px Inter, system-ui, segoe-ui, sans-serif";
    const w = ctx.measureText(text).width + 12;
    const h = Math.max(14, th - 14);
    const x = 0;
    const y = -th - h - 5;
    roundRect(ctx, x, y, w, h, 4);
    ctx.fillStyle = "rgba(58, 58, 58, 0.95)";
    ctx.fill();
    ctx.strokeStyle = "rgba(255, 255, 255, 0.12)";
    ctx.lineWidth = 1;
    ctx.stroke();
    ctx.fillStyle = "#e6e6e6";
    ctx.textBaseline = "middle";
    ctx.fillText(text, x + 6, y + h / 2 + 0.5);
    ctx.restore();
}

// ── 节点编号（#id）────────────────────────────────────────────────────

// 这些节点本身是「纯显示」用途（画布文字标签等），画编号会很难看 → 不显示编号
const ID_HIDDEN_TYPES = new Set(["XB_CanvasLabel"]);

function nodeTypeName(node) {
    return String(node?.type || node?.comfyClass || node?.constructor?.comfyClass || "");
}

/** 节点上要显示的编号文字（空字符串 = 不显示） */
function idLabelFor(node) {
    if (!showId || !node || node.id == null) return "";
    if (ID_HIDDEN_TYPES.has(nodeTypeName(node))) return "";
    return `#${node.id}`;
}

/** 经典模式：画在标题栏上方右侧，与左侧耗时胶囊错开 */
function drawIdBadge(ctx, node) {
    const text = idLabelFor(node);
    if (!text || !ctx) return;
    const th = (typeof LiteGraph !== "undefined" && LiteGraph.NODE_TITLE_HEIGHT) || 30;
    ctx.save();
    ctx.font = "12px Inter, system-ui, segoe-ui, sans-serif";
    const w = ctx.measureText(text).width + 12;
    const h = Math.max(14, th - 14);
    const x = Math.max(0, (node.size?.[0] || 0) - w - 2);
    const y = -th - h - 5;
    roundRect(ctx, x, y, w, h, 4);
    ctx.fillStyle = "rgba(58, 58, 58, 0.95)";
    ctx.fill();
    ctx.strokeStyle = "rgba(255, 255, 255, 0.12)";
    ctx.lineWidth = 1;
    ctx.stroke();
    ctx.fillStyle = "#9ad7ff";
    ctx.textBaseline = "middle";
    ctx.fillText(text, x + 6, y + h / 2 + 0.5);
    ctx.restore();
}

// ── Nodes 2.0：节点底部信息条里的胶囊 ──────────────────────────────────

function domRoot(node) {
    try {
        // 优先用节点自己的 DOM（子图视图里内外层可能出现相同数字 id，按属性查会认错）
        const own = node.domElement?.closest?.(".lg-node") || node.domElement;
        if (own && own.getAttribute?.("data-node-id") != null) return own;
    } catch (_) { /* ignore */ }
    for (const el of document.querySelectorAll(".lg-node")) {
        if (el.getAttribute("data-node-id") === String(node.id)) return el;
    }
    return null;
}

/**
 * Nodes 2.0 胶囊样式：统一挂在节点**左上角外侧**，与经典模式（画在标题栏上方）位置一致。
 * 不依赖节点内部结构：新版前端只有部分节点有「#id | 包名」徽标行，KSampler / VAEDecode 都没有。
 */
const CHIP_CSS = [
    "position:absolute",
    "left:2px",
    "bottom:100%",
    "margin-bottom:3px",
    "height:16px",
    "display:flex",
    "align-items:center",
    "padding:0 6px",
    "border-radius:5px",
    "font-size:11px",
    "line-height:1",
    "white-space:nowrap",
    "color:#e6e6e6",
    "background:rgba(58,58,58,.95)",
    "border:1px solid rgba(255,255,255,.12)",
    "pointer-events:none",
    "z-index:20",
].join(";");

const ID_CHIP_CSS = CHIP_CSS.replace("left:2px", "right:2px");


/**
 * 统一维护一个胶囊：text 为空就移除，有就补上并同步文字。
 * 耗时胶囊（左）与编号胶囊（右）都走这里，互不干扰。
 */
function syncChip(root, attr, side, text, title, color, node) {
    const existing = root.querySelector(`[${attr}]`);
    if (!text) {
        existing?.remove();
        return;
    }
    if (existing) {
        if (existing.textContent !== text) existing.textContent = text;
        return;
    }
    const chip = document.createElement("div");
    chip.setAttribute(attr, "1");
    if (node?.id != null) chip.setAttribute("data-node-id", String(node.id));
    chip.title = title;
    chip.style.cssText = side === "right" ? ID_CHIP_CSS : CHIP_CSS;
    chip.style.color = color;
    chip.textContent = text;
    root.appendChild(chip);
}

/** Nodes 2.0：一次同步「耗时（左上）」和「编号（右上）」两个胶囊 */
function updateBadges(node) {
    const root = domRoot(node);
    if (!root) return;
    try {
        syncChip(root, CHIP_ATTR, "left",
            enabled ? labelFor(node) : "", "本节点耗时", "#e6e6e6", node);
    } catch (_) { /* ignore */ }
    try {
        syncChip(root, ID_CHIP_ATTR, "right",
            idLabelFor(node), "节点编号", "#9ad7ff", node);
    } catch (_) { /* ignore */ }
}

/** 兼容旧调用点 */
function updateChip2(node) { updateBadges(node); }

function removeAllIdChips() {
    for (const el of document.querySelectorAll(`[${ID_CHIP_ATTR}]`)) el.remove();
}

// ── 刷新循环 ───────────────────────────────────────────────────────────

let needsRepaint = false;
let idSweep = 0;

function tick() {
    const nodes2 = isNodes2();
    readSetting();                 // 每轮读一次设置，避免缓存值让某个开关"失效"
    try {
        if (!nodes2) hookAllNodes();   // 经典模式：补上新出现的节点（含子图节点）
        if (nodes2) {
            // 两个胶囊（耗时 / 编号）一起维护：Vue 重渲染会整块丢掉 DOM，每轮补一次最稳
            for (const node of allNodes()) updateBadges(node);
            if (++idSweep % 4 === 0) {
                // 节点被删除后 DOM 没了但胶囊可能残留：清理孤儿
                const live = new Set(allNodes().map((n) => String(n.id)));
                for (const el of document.querySelectorAll(`[${CHIP_ATTR}],[${ID_CHIP_ATTR}]`)) {
                    const nid = el.getAttribute("data-node-id");
                    if (nid == null || !live.has(nid)) el.remove();
                }
            }
        } else if (needsRepaint) {
            app.graph?.setDirtyCanvas?.(true, true);
        }
    } catch (_) { /* ignore */ }
    dirty.clear();
    needsRepaint = false;

    if (enabled && currentId != null) {
        if (nodes2) {
            if (currentLeaf) updateChip2(currentLeaf);
            for (const a of currentAncestors) updateChip2(a);
        } else {
            app.graph?.setDirtyCanvas?.(true, false);
        }
    }
    setTimeout(tick, currentId != null ? 200 : 600);
}

// ── 事件 ───────────────────────────────────────────────────────────────

function wireEvents() {
    api.addEventListener("execution_start", () => {
        clearAll();
        needsRepaint = true;
    });
    api.addEventListener("executing", (event) => {
        const id = eventNodeId(event);
        flush();                     // 上一个节点到此结束
        if (id == null) return;
        const leaf = nodeById(id);
        if (leaf) delete leaf[CACHED_KEY];
        currentId = id;
        currentStart = performance.now();
        currentLeaf = leaf;
        currentAncestors = ancestorNodes(id);
        currentAncestorIds = new Set(currentAncestors.map((n) => String(n.id)));
        dirty.add(id);
        for (const a of currentAncestors) dirty.add(String(a.id));
    });
    api.addEventListener("execution_cached", (event) => {
        // 命中缓存的节点没有 executing，标成「缓存」而不是留空
        const ids = event?.detail?.nodes ?? event?.nodes ?? [];
        for (const id of ids || []) {
            const node = nodeById(id);
            if (node) {
                node[CACHED_KEY] = true;
                ranIds.add(String(node.id));
                dirty.add(String(node.id));
            }
            // 子图里全命中缓存 → 子图节点也标缓存
            for (const ancestor of ancestorNodes(id)) {
                ancestor[CACHED_KEY] = true;
                ranIds.add(String(ancestor.id));
                dirty.add(String(ancestor.id));
            }
        }
        needsRepaint = true;
    });
    for (const name of ["execution_success", "execution_error", "execution_interrupted"]) {
        api.addEventListener(name, () => {
            flush();
            needsRepaint = true;
        });
    }
}

function readSetting() {
    try {
        const v = app.ui?.settings?.getSettingValue?.(SETTING_ID);
        if (v !== undefined) enabled = v !== false;
    } catch (_) { /* 设置系统还没就绪时保持默认 */ }
    try {
        const v2 = app.ui?.settings?.getSettingValue?.(ID_SETTING_ID);
        if (v2 !== undefined) showId = v2 !== false;
    } catch (_) { /* 同上 */ }
}

// ── 经典模式绘制入口 ───────────────────────────────────────────────────

/**
 * 给单个节点挂上 onDrawForeground（实例级）。
 * 不用 beforeRegisterNodeDef 包原型：子图（子工作流）节点的类型是运行时动态注册的，
 * 拿不到那个钩子，结果子图节点永远不显示耗时。
 */
function ensureNodeDrawHook(node) {
    if (!node || node.__xbDrawHooked) return;
    node.__xbDrawHooked = true;
    const orig = node.onDrawForeground;
    node.onDrawForeground = function (ctx) {
        const r = orig ? orig.apply(this, arguments) : undefined;
        if (enabled && ctx && !isNodes2()) {
            try {
                if ((Number(this[SEC_KEY]) || 0) > 0 || this[CACHED_KEY]) drawClassicBadge(ctx, this);
            } catch (_) { /* ignore */ }
        }
        if (showId && ctx && !isNodes2()) {
            try { drawIdBadge(ctx, this); } catch (_) { /* ignore */ }
        }
        return r;
    };
}

function hookAllNodes() {
    try {
        for (const node of allNodes()) ensureNodeDrawHook(node);
    } catch (_) { /* ignore */ }
}

/** 注册一个开关；任何一个失败都不影响另一个（避免两个设置互相拖累）
 *
 * ⚠️ 前端设置面板用「category 路径」建树，**同一路径下只会显示最后注册的一个**。
 * 所以同一个分组里的多个开关必须带上不同的第三段（第三段只做唯一键，标题仍显示第二段）。
 */
function addToggleSetting(id, name, tooltip, defaultValue, category, sortOrder, onChange) {
    try {
        app.ui.settings.addSetting({
            id,
            name,
            tooltip,
            type: "boolean",
            defaultValue,
            category,
            sortOrder,
            onChange,
        });
        return true;
    } catch (e) {
        console.warn(`[XB 节点显示] 设置「${name}」注册失败：`, e);
        return false;
    }
}

app.registerExtension({
    name: "XB_ToolBox.NodeRuntime",

    async setup() {
        if (app.ui?.settings?.addSetting) {
            addToggleSetting(SETTING_ID, "开启节点耗时显示",
                "在节点上显示该节点最近一次执行的耗时（Nodes 2.0 下显示在节点左上角）",
                true, ["XB_ToolBox", "节点相关", "耗时"], 2, (value) => {
                    enabled = value !== false;
                    if (!enabled) clearAll();
                    refreshSoon();
                });
            addToggleSetting(ID_SETTING_ID, "开启节点编号显示",
                "在节点右上角显示节点编号（#id）；文字标签等纯显示节点不显示",
                true, ["XB_ToolBox", "节点相关", "编号"], 1, (value) => {
                    showId = value !== false;
                    if (!showId) removeAllIdChips();
                    refreshSoon();
                });
        }
        readSetting();
        wireEvents();
        tick();
    },
});

/** 设置变化后尽快重建胶囊并重绘画布 */
let refreshTimer = null;
function refreshSoon() {
    if (refreshTimer) return;
    refreshTimer = setTimeout(() => {
        refreshTimer = null;
        try {
            for (const node of allNodes()) updateBadges(node);
        } catch (_) { /* ignore */ }
        app.graph?.setDirtyCanvas?.(true, true);
    }, 30);
}
