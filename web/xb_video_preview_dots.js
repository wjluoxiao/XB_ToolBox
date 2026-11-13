/**
 * XB-BOX 视频预览分页点（还原官方样式）
 * =====================================
 * 官方 VideoPreview 的分页小圆点是 `absolute bottom-2`（叠在视频进度条上，挡住点击）。
 * 本扩展只做两件事，圆的样式完全沿用官方：
 *   1. 把这排小圆点从视频框里"抬"到视频框下面（进度条下方），不再压住进度条；
 *   2. 拼接出来的完整视频，其圆点染成橙色，便于和分段区分。
 *
 * 只作用于 XB 的多段视频预览节点（批量拼接 / 批量保存 / 长视频放大保存）。
 * 手动重跑：window.xbVideoDots.reapply()
 */

import { app } from "../../scripts/app.js";

const NODE_TYPES = new Set([
    "XB_BatchVideoMerge",
    "XB_BatchSaveVideo",
    "XB_LongVideoVSRUpscale",
]);

const MERGED_COLOR = "#f59e0b";
const LEGACY_PAGER = "data-xb-pager";

/* ── 基础工具 ─────────────────────────────────────────────── */

function outputFilenames(nodeId) {
    try {
        const out = app?.nodeOutputs?.[nodeId];
        const images = out?.images || out?.video || [];
        return images.map((i) => i?.filename).filter(Boolean);
    } catch (_) {
        return [];
    }
}

function isMergedName(name) {
    return typeof name === "string" && (name.includes("_merged_") || name.includes("_merged."));
}

/** 拼接结果在输出列表中的下标（找不到返回 -1） */
function mergedIndexOf(names) {
    const last = names[names.length - 1];
    if (names.length > 1 && isMergedName(last)) return names.length - 1;
    for (let i = 0; i < names.length; i++) {
        if (isMergedName(names[i])) return i;
    }
    return -1;
}

function matchesName(video, names) {
    let src = video.currentSrc || video.src || "";
    if (!src) src = video.querySelector?.("source")?.src || "";
    if (!src) return false;
    let decoded = src;
    try { decoded = decodeURIComponent(src); } catch (_) { /* ignore */ }
    return names.some((n) => src.includes(n) || decoded.includes(n));
}

function domRoot(node) {
    try {
        const own = node.domElement?.closest?.(".lg-node") || node.domElement;
        if (own && own.getAttribute?.("data-node-id") != null) return own;
    } catch (_) { /* ignore */ }
    for (const el of document.querySelectorAll(".lg-node")) {
        if (el.getAttribute("data-node-id") === String(node.id)) return el;
    }
    return null;
}

/* ── 找官方分页点容器 ─────────────────────────────────────── */

function isDotButton(el) {
    return el?.tagName === "BUTTON" && String(el.className || "").includes("rounded-full");
}

function dotsBoxIn(container, skip) {
    for (const el of container.children) {
        if (el === skip) continue;
        if (el.hasAttribute?.(LEGACY_PAGER)) continue;
        const kids = Array.from(el.children || []);
        if (kids.length < 2) continue;
        if (kids.every(isDotButton)) return el;
    }
    return null;
}

function findDotsBox(video, wrapper) {
    // 视频框内（官方原位）→ 已被我们抬到视频框外面 → 两者都找
    return dotsBoxIn(wrapper, video) || (wrapper.parentElement ? dotsBoxIn(wrapper.parentElement, wrapper) : null);
}

/* ── 把分页点移到视频框下方（进度条下面）──────────────────── */

function liftBelowProgress(box, wrapper) {
    const host = wrapper.parentElement;
    if (!host) return;

    // Vue 有可能把容器重新塞回视频框里，发现就再移出来一次
    if (box.parentElement === wrapper) {
        host.insertBefore(box, wrapper.nextSibling);
    }
    if (box.style.position !== "static") {
        box.style.position = "static";
        box.style.left = "auto";
        box.style.right = "auto";
        box.style.bottom = "auto";
        box.style.marginTop = "5px";
        box.style.flex = "0 0 auto";
    }
}

/* ── 给拼接结果上橙色 ─────────────────────────────────────── */

function paintDots(box, mergedIndex) {
    const dots = Array.from(box.children);
    dots.forEach((dot, i) => {
        const isMerged = i === mergedIndex;
        const title = isMerged ? "拼接后的完整视频" : `第 ${i + 1} 段`;
        if (dot.title !== title) dot.title = title;
        if (isMerged) {
            const active = dot.classList.contains("bg-foreground");
            if (dot.style.backgroundColor !== "rgb(245, 158, 11)") {
                dot.style.backgroundColor = MERGED_COLOR;
            }
            dot.style.transform = active ? "scale(1.45)" : "";
        } else if (dot.style.backgroundColor) {
            dot.style.backgroundColor = "";
            dot.style.transform = "";
        }
    });
}

/* ── 主流程 ───────────────────────────────────────────────── */

function processNode(node) {
    const names = outputFilenames(node.id);
    if (!names.length) return;
    const mergedIndex = mergedIndexOf(names);

    let videos = Array.from(document.querySelectorAll("video")).filter((v) => matchesName(v, names));
    if (!videos.length) {
        const root = domRoot(node);
        videos = root ? Array.from(root.querySelectorAll("video")) : [];
    }

    for (const video of videos) {
        const wrapper = video.parentElement;
        if (!wrapper) continue;

        const legacy = wrapper.parentElement?.querySelector(`[${LEGACY_PAGER}]`) || wrapper.querySelector(`[${LEGACY_PAGER}]`);
        if (legacy) legacy.remove();

        const box = findDotsBox(video, wrapper);
        if (!box) continue;

        liftBelowProgress(box, wrapper);
        paintDots(box, mergedIndex);
    }
}

let running = false;
function reapply() {
    if (running) return;
    running = true;
    try {
        const walk = (g) => {
            for (const node of g?._nodes || []) {
                if (NODE_TYPES.has(node?.type)) {
                    try { processNode(node); } catch (e) { console.warn("[xb dots]", e); }
                }
                if (node?.subgraph) walk(node.subgraph);
            }
        };
        walk(app.graph);
    } catch (_) { /* ignore */ }
    running = false;
}

export const XB_VIDEO_PREVIEW_DOTS = { version: 3 };

app.registerExtension({
    name: "XB_ToolBox.VideoPreviewDots",

    setup() {
        window.xbVideoDots = { reapply, version: 3 };
        setInterval(reapply, 500);
    },

    async loadedGraphNode() {
        setTimeout(reapply, 300);
    },
});
