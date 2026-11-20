/**
 * XB-BOX - 🖼️ 外补画板（Outpaint Board）— 前端可视化窗口
 * ============================================================================
 * 参数由后端负责，这里只管「图怎么摆」：
 *   · 预览窗把节点剩下的空间**全部用满**；「画幅比例 + 长边尺寸」的边界方框在预览里
 *     等比放大到贴边（长边方向严丝合缝），方框不可拖动（只作参考边界）。
 *   · 图片只从「图像」端口的连线读，不做全图嗅探（多张 Load Image 时不会认错图）：
 *       「刷新图片」= 手动读取上游图片（PNG 带透明通道时同时还原遮罩）；
 *       跑过一次之后，后端通过 ui 预览把「原图 + 最终遮罩」推回来，自动显示。
 *   · 四角拖拽 = 等比缩放（对角锚定，相对位移，不会跳）；中间拖拽 = 平移（小手）；
 *     悬停图片滚轮 = 按「对齐倍数」步进缩放。四个调节点始终贴在**图片的真实四角**上。
 *   · 「居中填满」= 整图等比缩放并居中，**完整落在画幅框内**（不裁切、可放大）。
 *   · 图片可以拖出画布（= 裁剪），但位置夹取保证**始终至少有一个真实的角在画布内**
 *     （离边至少一个对齐倍数），所以贴角的调节点永远抓得到、图也永远拖不丢。
 *   · 摆放结果存成归一化值写回隐藏部件 layout：
 *         {"v":1,"s":图宽/画布宽,"cx":中心x/画布宽,"cy":中心y/画布高}
 *     改画幅比例 / 长边尺寸时占比自动跟随，不需要重新摆。
 *
 * ⚠️ 坐标：所有命中判定、拖拽换算都在「元素布局像素」里做。
 *    getBoundingClientRect() 给的是**屏幕像素（含画布缩放）**，必须除以
 *    clientWidth / offsetWidth 的比值还原——否则缩放 ≠ 100% 时角点永远抓不到、滚轮也失效。
 */

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import {
    setWidgetValue,
    setWidgetHidden,
    refreshWidgets,
    sizeDomWidget,
    bindNodes2BoxFill,
    lockNodeComputeSize,
    isNodes2,
} from "./xb_compat.js";

const NODE_TYPE = "XB_OutpaintBoard";

// 与后端 ASPECT_RATIOS / RATIO_MAP 一一对应（顺序也必须一致）
const RATIO_MAP = {
    "1:1 (Square)": 1,
    "2:3 (Portrait Photo)": 2 / 3,
    "3:2 (Photo)": 3 / 2,
    "3:4 (Portrait Standard)": 3 / 4,
    "4:3 (Standard)": 4 / 3,
    "9:16 (Portrait Widescreen)": 9 / 16,
    "16:9 (Widescreen)": 16 / 9,
    "21:9 (Ultrawide)": 21 / 9,
};

const BOARD_BG = "#141419";
const FRAME_FILL_DEFAULT = "#808080";
const FRAME_LINE = "#5aa9ff";
const HANDLE_FILL = "#ffffff";
const HANDLE_LINE = "#1b1b20";
const TEXT_COLOR = "#c9d1db";

const PREVIEW_MIN = 160;
const PREVIEW_DEFAULT_W = 380;
const CORNER_HIT = 11;          // 四角命中半径（CSS px）
const CORNER_CURSORS = ["nwse-resize", "nesw-resize", "nesw-resize", "nwse-resize"];
// 四个角（左上/右上/左下/右下）相对图片中心的「外」方向：-1 = 左/上，+1 = 右/下
const CORNER_SIGNS = [[-1, -1], [1, -1], [-1, 1], [1, 1]];
const SCALE_FACTOR_MAX = 4;     // 与后端一致：图片最大 4 × 画布
const THUMB_MAX = 1024;         // 绘制用的缩略图长边（大图不再每帧重采样）

const IMAGE_FILE_RE = /\.(png|jpe?g|webp|bmp|gif|tiff?|avif)$/i;
const IMAGE_WIDGET_NAMES = ["image", "图像", "file", "filename", "image_file", "source_image"];
const SKIP_NODE_TYPES = new Set(["Reroute", "PrimitiveNode", "Note", "MarkdownNote"]);

/* ============================================================
 *  小工具（几何算法必须与后端逐行等价）
 * ============================================================ */
function findWidget(node, name) {
    return (node?.widgets || []).find((w) => w && w.name === name) || null;
}

function readInt(node, name, dflt) {
    const v = Number(findWidget(node, name)?.value);
    return Number.isFinite(v) ? Math.round(v) : dflt;
}

function readStr(node, name, dflt) {
    const v = findWidget(node, name)?.value;
    return typeof v === "string" ? v : dflt;
}

function clampN(v, lo, hi) {
    return Math.min(hi, Math.max(lo, v));
}

function multipleOf(node) {
    return clampN(readInt(node, "multiple", 16), 8, 128);
}

function snap(v, m) {
    const mm = Math.max(1, m | 0);
    return Math.floor(v / mm + 0.5) * mm;
}

function fillColorValue(node) {
    const raw = String(readStr(node, "fill_color", FRAME_FILL_DEFAULT) || "").trim();
    const hex = raw.startsWith("#") ? raw.slice(1) : raw;
    if (/^[0-9a-f]{3}$/i.test(hex)) return "#" + hex.split("").map((c) => c + c).join("");
    return /^[0-9a-f]{6}$/i.test(hex) ? "#" + hex.toLowerCase() : FRAME_FILL_DEFAULT;
}

/** 颜色 → 可读的前景色（亮底用黑字、暗底用白字） */
function contrastText(hex) {
    const h = String(hex || "").replace("#", "");
    if (h.length !== 6) return "#ffffff";
    const r = parseInt(h.slice(0, 2), 16);
    const g = parseInt(h.slice(2, 4), 16);
    const b = parseInt(h.slice(4, 6), 16);
    return (0.299 * r + 0.587 * g + 0.114 * b) > 140 ? "#1b1b20" : "#ffffff";
}

/**
 * 原生取色器默认带内边距 + 色块圆角，视觉上只有中间一小块是颜色。
 * 这里用一条样式把 swatch 铺满整个输入框 —— 整格按钮就是颜色本身。
 */
function ensureColorCss() {
    const ID = "xb-ob-color-css";
    try {
        if (document.getElementById?.(ID)) return;
        const style = document.createElement("style");
        style.id = ID;
        style.textContent =
            "input.xb-ob-color{-webkit-appearance:none;appearance:none;padding:0;margin:0;" +
            "border:1px solid #4a4a52;border-radius:6px;background:none;cursor:pointer;display:block;}" +
            "input.xb-ob-color::-webkit-color-swatch-wrapper{padding:0;background:none;}" +
            "input.xb-ob-color::-webkit-color-swatch{border:none;border-radius:5px;}" +
            "input.xb-ob-color::-moz-color-swatch{border:none;border-radius:5px;}";
        const parent = document.head || document.body;
        if (parent) parent.appendChild(style);
    } catch (_) { /* ignore */ }
}

/** 画布尺寸：与后端 board_size() 等价（宽高互随，联动规则同「图片参数大全」） */
function boardSize(node) {
    const m = multipleOf(node);
    const clampS = (v) => clampN(Number.isFinite(v) ? v : 1024, 64, 8192);
    let w = snap(clampS(readInt(node, "width", 1024)), m);
    let h = snap(clampS(readInt(node, "height", 1024)), m);
    const ratio = RATIO_MAP[readStr(node, "aspect_ratio", "自定义")];
    if (Number.isFinite(ratio) && ratio > 0) {
        if (w >= h) h = Math.max(m, snap(w / ratio, m));
        else w = Math.max(m, snap(h * ratio, m));
    }
    return [Math.max(m, w), Math.max(m, h)];
}

function parseLayout(text) {
    if (!text) return null;
    let data = text;
    if (typeof text === "string") {
        const raw = text.trim();
        if (!raw) return null;
        try { data = JSON.parse(raw); } catch (_) { return null; }
    }
    if (!data || typeof data !== "object") return null;
    const s = Number(data.s), cx = Number(data.cx), cy = Number(data.cy);
    if (!(s > 0) || !Number.isFinite(cx) || !Number.isFinite(cy)) return null;
    return { s, cx, cy };
}

function layoutText(layout) {
    const r6 = (v) => Math.round(v * 1e6) / 1e6;
    return JSON.stringify({ v: 1, s: r6(layout.s), cx: r6(layout.cx), cy: r6(layout.cy) });
}

/**
 * 摆放矩形：与后端 placement() 等价（画布像素）。
 * 图片框**不做对齐吸附**（否则「正好放下 / 居中填满」会凑整留出几像素空隙）；
 * 吸附只发生在拖拽 / 滚轮的交互里。位置夹取保证「至少有一个真实的角在画布内」。
 */
function rectPx(node, layout, imgW, imgH, cw, ch) {
    const m = multipleOf(node);
    const limit = SCALE_FACTOR_MAX * Math.max(cw, ch);
    const aspect = imgW / imgH;
    let w, cx, cy;
    if (layout) {
        w = layout.s * cw;
        cx = layout.cx * cw;
        cy = layout.cy * ch;
    } else {
        // 自动摆放 = contain：整图完整落在画布内（长边贴边），且不放大原图
        const scale = Math.min(cw / imgW, ch / imgH, 1);
        w = imgW * scale;
        cx = cw / 2;
        cy = ch / 2;
    }
    w = Math.min(limit, Math.max(m, Math.round(w)));
    const h = Math.min(limit, Math.max(m, Math.round(w / aspect)));
    const x = clampAxis(Math.round(cx - w / 2), w, cw);
    const y = clampAxis(Math.round(cy - h / 2), h, ch);
    return { x, y, w, h };
}

/**
 * 单轴夹取：与后端 _clamp_axis() 等价。
 * 合法区间 =「左上角在内（离边 ≥ margin）」∪「右下角在内（离边 ≥ margin）」；
 * 两段分开（图比画布大）时取最近的一段 —— 任何状态下都至少有一个真实角在画布内。
 */
function clampAxis(value, imageSize, canvasSize) {
    const farLow = -imageSize;
    const farHigh = canvasSize - imageSize;
    const nearLow = 0;
    const nearHigh = canvasSize;
    if (farHigh >= nearLow) return clampN(value, farLow, nearHigh);
    if (value <= farHigh) return clampN(value, farLow, farHigh);
    if (value >= nearLow) return clampN(value, nearLow, nearHigh);
    return (value - farHigh) <= (nearLow - value) ? farHigh : nearLow;
}

function layoutFromRect(rect, cw, ch) {
    return {
        s: rect.w / cw,
        cx: (rect.x + rect.w / 2) / cw,
        cy: (rect.y + rect.h / 2) / ch,
    };
}

/* ============================================================
 *  上游图片（只认「图像」端口上的连线）
 * ============================================================ */
function looksLikeImageFile(value) {
    if (typeof value !== "string") return false;
    const text = value.trim();
    if (!text || text === "none" || text.length < 4) return false;
    return IMAGE_FILE_RE.test(text.replace(/\s*\[(input|output|temp)\]\s*$/i, ""));
}

function parseAnnotated(value) {
    let text = String(value || "").trim();
    let type = "input";
    const m = text.match(/^(.*?)\s*\[(input|output|temp)\]\s*$/i);
    if (m) {
        text = m[1];
        type = m[2].toLowerCase();
    }
    const slash = text.lastIndexOf("/");
    return slash >= 0
        ? { subfolder: text.slice(0, slash), filename: text.slice(slash + 1), type }
        : { subfolder: "", filename: text, type };
}

function viewUrl(value, seq) {
    const { subfolder, filename, type } = parseAnnotated(value);
    if (!filename) return "";
    const params = new URLSearchParams({ filename, type, subfolder });
    if (seq) params.set("t", String(seq));
    return api.apiURL("/view?" + params.toString());
}

function fileUrl(file, seq) {
    if (!file || !file.filename) return "";
    const params = new URLSearchParams({
        filename: file.filename,
        type: file.type || "temp",
        subfolder: file.subfolder || "",
    });
    if (seq) params.set("t", String(seq));
    return api.apiURL("/view?" + params.toString());
}

function candidateFromNode(n) {
    if (!n || SKIP_NODE_TYPES.has(n.type)) return null;
    const widgets = n.widgets || [];
    const pick = (w) => w && looksLikeImageFile(w.value);
    const named = widgets.find((w) => IMAGE_WIDGET_NAMES.includes(w.name) && pick(w));
    if (named) return String(named.value);
    const any = widgets.find(pick);
    return any ? String(any.value) : null;
}

function linkById(graph, id) {
    const links = graph?.links;
    if (!links || id == null) return null;
    if (Array.isArray(links)) return links.find((l) => l && l[0] === id) || null;
    return links[id] || null;
}

/** 只顺着「图像」输入端口的连线往上游找图片文件（不做全图扫描） */
function linkedImageValue(node) {
    const graph = node.graph || app.graph;
    const seen = new Set();
    let cur = node;
    for (let hop = 0; hop < 8 && cur; hop += 1) {
        if (seen.has(cur)) break;
        seen.add(cur);
        const input = (cur.inputs || []).find((i) => i && i.name === "image");
        const link = input && linkById(graph, input.link);
        if (!link) break;
        const originId = link.origin_id !== undefined ? link.origin_id : link[1];
        const upstream = graph?.getNodeById?.(originId);
        if (!upstream) break;
        const value = candidateFromNode(upstream);
        if (value) return value;
        cur = upstream;
    }
    return null;
}

/* ---------------- 缩略图 / 透明通道遮罩 ---------------- */
function buildThumb(img, maxSide) {
    const iw = img.naturalWidth || img.width || 0;
    const ih = img.naturalHeight || img.height || 0;
    if (!iw || !ih) return img;
    const scale = Math.min(1, maxSide / Math.max(iw, ih));
    if (scale >= 1) return img;
    const c = document.createElement("canvas");
    c.width = Math.max(1, Math.round(iw * scale));
    c.height = Math.max(1, Math.round(ih * scale));
    c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
    return c;
}

/** 从图片 alpha 还原遮罩（官方 Load Image 的遮罩就是 1 - alpha）；不透明图返回 null。 */
function alphaMaskFromImage(img, maxSide) {
    try {
        const iw = img.naturalWidth || img.width || 0;
        const ih = img.naturalHeight || img.height || 0;
        if (!iw || !ih) return null;
        const scale = Math.min(1, maxSide / Math.max(iw, ih));
        const sw = Math.max(1, Math.round(iw * scale));
        const sh = Math.max(1, Math.round(ih * scale));
        const src = document.createElement("canvas");
        src.width = sw;
        src.height = sh;
        const sctx = src.getContext("2d", { willReadFrequently: true });
        sctx.drawImage(img, 0, 0, sw, sh);
        const data = sctx.getImageData(0, 0, sw, sh).data;
        let opaque = true;
        const out = document.createElement("canvas");
        out.width = sw;
        out.height = sh;
        const octx = out.getContext("2d");
        const outData = octx.createImageData(sw, sh);
        for (let i = 0; i < data.length; i += 4) {
            const a = data[i + 3];
            if (a !== 255) opaque = false;
            outData.data[i] = 255;
            outData.data[i + 1] = 60;
            outData.data[i + 2] = 60;
            outData.data[i + 3] = 255 - a;
        }
        if (opaque) return null;
        octx.putImageData(outData, 0, 0);
        return out;
    } catch (_) {
        return null;
    }
}

/* ============================================================
 *  节点安装
 * ============================================================ */
function setup(node) {
    // 前端在「加载工作流」收尾会跑一段只增不减的尺寸修正（node.computeSize() 求和 DOM 部件的最小高度），
    // 不锁住的话每刷新一次页面节点就被顶高一次。锁成「就地返回当前尺寸」即可。
    try { lockNodeComputeSize(node); } catch (_) { /* ignore */ }

    const wLayout = findWidget(node, "layout");
    const wFill = findWidget(node, "fill_color");
    if (wLayout) setWidgetHidden(node, wLayout, true);
    if (wFill) setWidgetHidden(node, wFill, true);

    const st = {
        node, wLayout, wFill,
        pw: 0, ph: 0, dpr: 1,
        img: null, thumb: null, imgW: 0, imgH: 0,
        mask: null,
        canvasMask: null,
        note: "",
        layout: parseLayout(readStr(node, "layout", "")),
        lastLayoutRaw: null,
        frame: { k: 1, x: 0, y: 0, w: 1, h: 1 },
        rect: null,
        drag: null,
        hoverCorner: -1,
        cursor: "",
        widgetStamp: "",
        colorInput: null,
        raf: 0,
        raf2: 0,
        alive: true,
        loadSeq: 0,
    };

    /* ── 控制行：遮罩选色 / 刷新图片 / 居中填满（三等分）─────────── */
    const CELL_CSS =
        "flex:1 1 0;min-width:0;height:26px;box-sizing:border-box;border-radius:6px;" +
        "border:1px solid #4a4a52;background:#2f2f36;color:#e8e8ea;font-size:12px;line-height:1;" +
        "cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-family:inherit;";

    const mkButton = (text, title, onClick) => {
        const b = document.createElement("button");
        b.type = "button";
        b.textContent = text;
        b.title = title;
        b.style.cssText = CELL_CSS;
        b.addEventListener("pointerdown", (e) => e.stopPropagation());
        b.addEventListener("mouseenter", () => { b.style.filter = "brightness(1.25)"; });
        b.addEventListener("mouseleave", () => { b.style.filter = ""; });
        b.addEventListener("click", (e) => { e.stopPropagation(); onClick(); });
        return b;
    };

    /** 颜色格子：整块就是 input[type=color]（色块铺满），文字浮在上面 */
    const mkColorCell = (node) => {
        ensureColorCss();
        const cell = document.createElement("div");
        cell.style.cssText = "position:relative;flex:1 1 0;min-width:0;height:26px;";
        const input = document.createElement("input");
        input.type = "color";
        input.className = "xb-ob-color";
        input.value = fillColorValue(node);
        input.title = "外补区域（遮罩白区）的填充色";
        input.style.cssText =
            "position:absolute;inset:0;width:100%;height:100%;box-sizing:border-box;";
        const label = document.createElement("span");
        label.textContent = "遮罩选色";
        label.style.cssText =
            "position:absolute;inset:0;display:flex;align-items:center;justify-content:center;" +
            "font-size:12px;line-height:1;pointer-events:none;overflow:hidden;white-space:nowrap;" +
            "font-family:inherit;text-shadow:0 0 3px rgba(0,0,0,.55);";
        const syncLook = () => {
            const hex = fillColorValue(node);
            if (input.value !== hex) input.value = hex;
            label.style.color = contrastText(hex);
        };
        syncLook();
        input.addEventListener("pointerdown", (e) => e.stopPropagation());
        input.addEventListener("input", () => {
            setWidgetValue(st.wFill, input.value);
            label.style.color = contrastText(input.value);
            requestDraw();
        });
        cell.appendChild(input);
        cell.appendChild(label);
        return { cell, input, syncLook };
    };

    try {
        const row = document.createElement("div");
        row.style.cssText = "display:flex;gap:6px;width:100%;box-sizing:border-box;align-items:center;";
        const colorCell = mkColorCell(node);
        row.appendChild(colorCell.cell);
        row.appendChild(mkButton("刷新图片", "从「图像」端口的连线读取上游图片（含透明通道遮罩）；双击预览窗也可以", () => refreshImage(true)));
        row.appendChild(mkButton("居中填满", "整图等比缩放并居中，完整落在画幅框内", () => centerFill()));
        const controls = node.addDOMWidget("xb_ob_controls", "xb_ob_controls", row, {
            serialize: false,
            hideOnZoom: false,
            getMinHeight: () => 30,
        });
        sizeDomWidget(node, controls, 30);
        st.colorInput = colorCell.input;
        st.syncColor = colorCell.syncLook;
    } catch (err) {
        console.warn("[XB-BOX 外补画板] 控制行不可用（前端不支持 DOM 部件）", err);
    }

    /* ── 预览窗 ─────────────────────────────────────────────────── */
    const wrap = document.createElement("div");
    wrap.style.cssText =
        "position:relative;width:100%;height:100%;display:flex;align-items:stretch;justify-content:stretch;" +
        "background:" + BOARD_BG + ";border:1px solid #33333d;border-radius:8px;overflow:hidden;box-sizing:border-box;";
    const cv = document.createElement("canvas");
    cv.style.cssText = "display:block;width:100%;height:100%;touch-action:none;cursor:default;";
    wrap.appendChild(cv);

    let widget = null;
    try {
        widget = node.addDOMWidget("xb_ob_preview", "preview", wrap, {
            serialize: false,
            hideOnZoom: false,
            getMinHeight: () => PREVIEW_MIN,
        });
        sizeDomWidget(node, widget, PREVIEW_MIN);
    } catch (err) {
        console.error("[XB-BOX 外补画板] 显示窗不可用：当前前端不支持 DOM 部件（addDOMWidget）", err);
    }
    if (widget) {
        try { bindNodes2BoxFill(node, wrap, { min: PREVIEW_MIN }); } catch (_) { /* ignore */ }
        // 经典画布没有 CSS 跟随：按节点剩余空间给高度
        // ⚠️ Nodes 2.0 下必须返回固定的最小高度：把节点自身高度算进内容高度会自我放大
        //    （刷新页面 → 内容比节点高 → 前端把节点撑高 → 下次刷新再撑高），预览高度由 CSS 铺满负责。
        try {
            widget.computeSize = () => {
                const w = Math.max(1, (node.size?.[0] || PREVIEW_DEFAULT_W) - 16);
                if (isNodes2()) return [w, PREVIEW_MIN];
                const avail = Math.max(1, (node.size?.[1] || 0) - 150);
                return [w, Math.max(PREVIEW_MIN, avail)];
            };
        } catch (_) { /* ignore */ }
    }
    st.widget = widget;

    /* ── 坐标换算（关键：抵消画布缩放）─────────────────────────── */
    const localPoint = (ev) => {
        const r = cv.getBoundingClientRect();
        const sx = r.width / Math.max(1, cv.offsetWidth || 1);
        const sy = r.height / Math.max(1, cv.offsetHeight || 1);
        return { px: (ev.clientX - r.left) / (sx || 1), py: (ev.clientY - r.top) / (sy || 1) };
    };

    const toCanvas = (ev) => {
        const p = localPoint(ev);
        const f = st.frame;
        return { px: p.px, py: p.py, x: (p.px - f.x) / (f.k || 1), y: (p.py - f.y) / (f.k || 1) };
    };

    /* ── 尺寸：预览窗吃满节点剩余空间（不再强留正方形，避免浪费显示范围）── */
    const measure = () => {
        const w = Math.max(40, Math.floor(wrap.clientWidth || 0));
        const h = Math.max(40, Math.floor(wrap.clientHeight || 0));
        const dpr = clampN(window.devicePixelRatio || 1, 1, 2);
        if (w !== st.pw || h !== st.ph || dpr !== st.dpr) {
            st.pw = w;
            st.ph = h;
            st.dpr = dpr;
            cv.width = Math.round(w * dpr);
            cv.height = Math.round(h * dpr);
        }
        return { w: st.pw, h: st.ph };
    };

    /* ── 四角调节点：贴在图片的「真实四角」上，方块整体画在图片内部 ──── */
    const cornerPoints = () => {
        const r = st.rect, F = st.frame;
        if (!r) return [];
        const raw = [[r.x, r.y], [r.x + r.w, r.y], [r.x, r.y + r.h], [r.x + r.w, r.y + r.h]];
        return raw.map(([x, y], i) => {
            const px = F.x + x * F.k, py = F.y + y * F.k;
            return {
                x: clampN(px, 0, st.pw),
                y: clampN(py, 0, st.ph),
                sx: CORNER_SIGNS[i][0],
                sy: CORNER_SIGNS[i][1],
                visible: px >= -1 && px <= st.pw + 1 && py >= -1 && py <= st.ph + 1,
            };
        });
    };

    /* ── 绘制 ───────────────────────────────────────────────────── */
    const paint = () => {
        const { w: pw, h: ph } = measure();
        const ctx = cv.getContext("2d");
        if (!ctx) return;
        ctx.setTransform(st.dpr, 0, 0, st.dpr, 0, 0);
        ctx.clearRect(0, 0, pw, ph);

        const [cw, ch] = boardSize(node);
        // 方框贴边：长边方向严丝合缝，另一方向居中（不留人为留白）
        const k = Math.max(0.0001, Math.min(pw / cw, ph / ch));
        const fw = cw * k, fh = ch * k;
        st.frame = { k, x: (pw - fw) / 2, y: (ph - fh) / 2, w: fw, h: fh };
        const F = st.frame;

        ctx.fillStyle = fillColorValue(node);
        ctx.fillRect(F.x, F.y, F.w, F.h);
        ctx.strokeStyle = FRAME_LINE;
        ctx.lineWidth = 1;
        ctx.strokeRect(F.x + 0.5, F.y + 0.5, Math.max(1, F.w - 1), Math.max(1, F.h - 1));

        let rect = null;
        if (st.thumb && st.imgW > 0 && st.imgH > 0) {
            rect = rectPx(node, st.layout, st.imgW, st.imgH, cw, ch);
            st.rect = rect;
            const dx = F.x + rect.x * k, dy = F.y + rect.y * k;
            const dw = Math.max(1, rect.w * k), dh = Math.max(1, rect.h * k);
            ctx.save();
            ctx.beginPath();
            ctx.rect(F.x, F.y, F.w, F.h);       // 超出画布的部分 = 裁剪（预览也裁掉）
            ctx.clip();
            try {
                ctx.imageSmoothingQuality = "high";
                ctx.drawImage(st.thumb, dx, dy, dw, dh);
                if (st.mask) ctx.drawImage(st.mask, dx, dy, dw, dh);   // 图片自带 alpha 遮罩：跟图片框
                if (st.canvasMask) {
                    // 后端返回的最终遮罩是「画布尺寸」，必须铺满画布框，不能塞进图片框
                    ctx.save();
                    ctx.globalAlpha = 0.35;
                    ctx.drawImage(st.canvasMask, F.x, F.y, F.w, F.h);
                    ctx.restore();
                }
            } catch (_) { /* ignore */ }
            ctx.setLineDash([4, 4]);
            ctx.strokeStyle = "rgba(255,255,255,.5)";
            ctx.lineWidth = 1;
            ctx.strokeRect(dx + 0.5, dy + 0.5, dw - 1, dh - 1);
            ctx.restore();
            const pts = cornerPoints();
            for (let i = 0; i < pts.length; i += 1) {
                const p = pts[i];
                if (!p.visible) continue;
                const hot = st.hoverCorner === i;
                const s = hot ? 10 : 8;
                // 方块整体落在图片内部：左/上角向右下画，右/下角向左上画
                const x0 = p.sx < 0 ? p.x : p.x - s;
                const y0 = p.sy < 0 ? p.y : p.y - s;
                ctx.fillStyle = hot ? FRAME_LINE : HANDLE_FILL;
                ctx.strokeStyle = HANDLE_LINE;
                ctx.lineWidth = 1;
                ctx.beginPath();
                ctx.rect(x0 + 0.5, y0 + 0.5, s - 1, s - 1);
                ctx.fill();
                ctx.stroke();
            }
        } else {
            st.rect = null;
            ctx.fillStyle = "rgba(0,0,0,.45)";
            ctx.font = "13px system-ui, sans-serif";
            ctx.textAlign = "center";
            ctx.textBaseline = "middle";
            ctx.fillText(st.note || "点「刷新图片」读取上游图片", pw / 2, ph / 2);
        }

        // 状态行（带底衬，贴在预览窗左下角）
        ctx.textAlign = "left";
        ctx.textBaseline = "alphabetic";
        ctx.font = "11px ui-monospace, Consolas, monospace";
        const parts = [`画布 ${cw}×${ch}`];
        if (rect) parts.push(`图 ${rect.w}×${rect.h} @ ${rect.x},${rect.y}`);
        if (st.canvasMask) parts.push("红 = 重绘区");
        if (st.note) parts.push(st.note);
        const label = parts.join("  ·  ");
        const textW = ctx.measureText(label).width;
        ctx.fillStyle = "rgba(10,10,14,.72)";
        ctx.fillRect(0, ph - 19, Math.min(pw, textW + 12), 19);
        ctx.fillStyle = TEXT_COLOR;
        ctx.fillText(label, 6, ph - 5);
    };

    const requestDraw = () => {
        if (st.raf) return;
        st.raf = requestAnimationFrame(() => {
            st.raf = 0;
            if (!st.alive) return;
            try { paint(); } catch (err) { console.warn("[XB-BOX 外补画板] 绘制失败", err); }
        });
    };

    /* ── layout 写回（只在松手 / 滚轮时写，拖拽过程零部件写入）──── */
    const writeLayout = () => {
        if (!st.alive || !st.layout) return;
        const text = layoutText(st.layout);
        if (readStr(node, "layout", "") === text) return;
        setWidgetValue(st.wLayout, text);
    };
    const setLayout = (layout) => {
        // 防脏写：任何一步算出 NaN 都直接丢掉，绝不让坏值进工作流
        if (!layout || !Number.isFinite(layout.s) || !Number.isFinite(layout.cx)
            || !Number.isFinite(layout.cy)) return;
        st.layout = layout;
        st.canvasMask = null;     // 摆放变了，上一次跑出来的遮罩就过期了
        requestDraw();
    };

    /* ── 取图 ───────────────────────────────────────────────────── */
    const applyImage = (img, mask) => {
        st.img = img;
        st.imgW = img.naturalWidth || img.width || 0;
        st.imgH = img.naturalHeight || img.height || 0;
        st.thumb = buildThumb(img, THUMB_MAX);
        st.mask = mask || null;
        st.canvasMask = null;
        st.note = "";
        requestDraw();
    };

    /** 手动刷新：只读「图像」端口连线指向的上游图片 */
    function refreshImage(announce) {
        const value = linkedImageValue(node);
        if (!value) {
            if (announce) {
                st.img = null; st.thumb = null; st.mask = null;
                st.imgW = st.imgH = 0;
                st.note = "「图像」端口没有可读的图片文件";
                requestDraw();
            }
            return;
        }
        const url = viewUrl(value, ++st.loadSeq);
        if (!url) return;
        const img = new Image();
        img.onload = () => {
            if (!st.alive) return;
            applyImage(img, alphaMaskFromImage(img, 512));
        };
        img.onerror = () => {
            if (!st.alive) return;
            st.img = null; st.thumb = null; st.mask = null;
            st.imgW = st.imgH = 0;
            st.note = "图片读不到：" + (parseAnnotated(value).filename || "?");
            requestDraw();
        };
        img.src = url;
    }

    /** 居中填满：整图完整落在「画幅约束框」内（可放大），等比、居中、不留凑整空隙 */
    function centerFill() {
        if (!st.imgW || !st.imgH) { refreshImage(true); return; }
        const [cw, ch] = boardSize(node);
        const limit = SCALE_FACTOR_MAX * Math.max(cw, ch);
        const aspect = st.imgW / st.imgH;
        const scale = Math.min(cw / st.imgW, ch / st.imgH);   // contain：长边贴框，整图可见
        const w = Math.min(limit, Math.max(1, Math.round(st.imgW * scale)));
        const h = Math.min(limit, Math.max(1, Math.round(w / aspect)));
        setLayout(layoutFromRect({
            x: Math.round((cw - w) / 2), y: Math.round((ch - h) / 2), w, h,
        }, cw, ch));
        writeLayout();
    }

    /* ── 交互 ───────────────────────────────────────────────────── */
    const hitCorner = (px, py) => {
        const pts = cornerPoints();
        for (let i = 0; i < pts.length; i += 1) {
            if (!pts[i].visible) continue;
            if (Math.abs(px - pts[i].x) <= CORNER_HIT && Math.abs(py - pts[i].y) <= CORNER_HIT) return i;
        }
        return -1;
    };

    const insideImage = (pt) => {
        const r = st.rect;
        if (!r) return false;
        return pt.x >= r.x && pt.x <= r.x + r.w && pt.y >= r.y && pt.y <= r.y + r.h;
    };

    const setCursor = (next) => {
        if (st.cursor === next) return;
        st.cursor = next;
        cv.style.cursor = next;
    };

    const updateHover = (ev) => {
        if (!st.rect) { st.hoverCorner = -1; setCursor("default"); return; }
        const p = localPoint(ev);
        const corner = hitCorner(p.px, p.py);
        if (corner >= 0) {
            const changed = st.hoverCorner !== corner;
            st.hoverCorner = corner;
            setCursor(CORNER_CURSORS[corner]);
            if (changed) requestDraw();
            return;
        }
        const hadCorner = st.hoverCorner >= 0;
        st.hoverCorner = -1;
        setCursor(insideImage(toCanvas(ev)) ? "grab" : "default");
        if (hadCorner) requestDraw();
    };

    const onPointerDown = (ev) => {
        if (ev.button !== 0) return;
        ev.preventDefault();
        ev.stopPropagation();
        if (!st.rect || !st.thumb) { refreshImage(true); return; }
        const p = localPoint(ev);
        const corner = hitCorner(p.px, p.py);
        const pt = toCanvas(ev);
        const base = { ...st.rect };
        if (corner >= 0) {
            // 相对位移缩放：锚定对角（.x/.y 对象，绝不是数组）
            const sign = CORNER_SIGNS[corner];
            st.drag = { mode: "resize", corner, sign, start: pt, base };
            setCursor(CORNER_CURSORS[corner]);
        } else if (insideImage(pt)) {
            st.drag = {
                mode: "move", base,
                grabX: pt.x - (base.x + base.w / 2),
                grabY: pt.y - (base.y + base.h / 2),
            };
            setCursor("grabbing");
        } else {
            return;
        }
        try { cv.setPointerCapture(ev.pointerId); } catch (_) { /* ignore */ }
        requestDraw();
    };

    const onPointerMove = (ev) => {
        if (!st.drag) { updateHover(ev); return; }
        ev.preventDefault();
        ev.stopPropagation();
        const pt = toCanvas(ev);
        const [cw, ch] = boardSize(node);
        const drag = st.drag;
        if (drag.mode === "move") {
            const base = drag.base;
            const cx = pt.x - drag.grabX;
            const cy = pt.y - drag.grabY;
            setLayout(layoutFromRect({ x: cx - base.w / 2, y: cy - base.h / 2, w: base.w, h: base.h }, cw, ch));
            return;
        }
        const m = multipleOf(node);
        const limit = SCALE_FACTOR_MAX * Math.max(cw, ch);
        const aspect = st.imgW / st.imgH;
        const base = drag.base;
        const [sx, sy] = drag.sign;
        // 相对起始点的位移 → 目标尺寸（同时取两轴里更"外"的那个，保持等比）
        const dx = (pt.x - drag.start.x) * sx;
        const dy = (pt.y - drag.start.y) * sy;
        let w = Math.max(base.w + dx, (base.h + dy) * aspect);
        w = clampN(snap(w, m), m, limit);
        const h = clampN(Math.max(m, snap(w / aspect, m)), m, limit);
        // 锚定**对角**：拖右/下角时左/上边固定，拖左/上角时右/下边固定
        const x = sx > 0 ? base.x : (base.x + base.w) - w;
        const y = sy > 0 ? base.y : (base.y + base.h) - h;
        setLayout(layoutFromRect({ x, y, w, h }, cw, ch));
    };

    const onPointerUp = (ev) => {
        if (!st.drag) return;
        st.drag = null;
        try { cv.releasePointerCapture(ev.pointerId); } catch (_) { /* ignore */ }
        writeLayout();
        updateHover(ev);
    };

    const onWheel = (ev) => {
        if (!st.thumb || !st.rect) return;
        const pt = toCanvas(ev);
        if (!insideImage(pt)) return;        // 只有「悬停在图片上」才缩放
        ev.preventDefault();
        ev.stopPropagation();
        const m = multipleOf(node);
        const [cw, ch] = boardSize(node);
        const limit = SCALE_FACTOR_MAX * Math.max(cw, ch);
        const aspect = st.imgW / st.imgH;
        const dir = ev.deltaY > 0 ? -1 : 1;  // 上滚放大
        const w = clampN(snap(st.rect.w + dir * m, m), m, limit);
        const h = clampN(Math.max(m, snap(w / aspect, m)), m, limit);
        const cx = st.rect.x + st.rect.w / 2;
        const cy = st.rect.y + st.rect.h / 2;
        setLayout(layoutFromRect({ x: cx - w / 2, y: cy - h / 2, w, h }, cw, ch));
        writeLayout();
    };

    cv.addEventListener("pointerdown", onPointerDown);
    cv.addEventListener("pointermove", onPointerMove);
    cv.addEventListener("pointerup", onPointerUp);
    cv.addEventListener("pointercancel", onPointerUp);
    cv.addEventListener("wheel", onWheel, { passive: false });
    cv.addEventListener("pointerleave", () => {
        if (st.drag) return;
        st.hoverCorner = -1;
        setCursor("default");
        requestDraw();
    });
    cv.addEventListener("dblclick", (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        refreshImage(true);
    });

    /* ── 宽高互随 + 步长锁 = 对齐倍数（与「图片参数大全」同一套）───── */
    const wWidth = findWidget(node, "width");
    const wHeight = findWidget(node, "height");
    const wRatio = findWidget(node, "aspect_ratio");
    const wMultiple = findWidget(node, "multiple");

    /** 把数字部件的步长锁到当前对齐倍数（经典画布看 options.step，Nodes 2.0 同源） */
    const applyStep = () => {
        const m = multipleOf(node);
        for (const w of [wWidth, wHeight]) {
            if (!w) continue;
            try { w.options = w.options || {}; } catch (_) { w.options = {}; }
            // 2.0 的 ± 按钮步长读 options.step2（getWidgetStep = step2 || step*0.1），
            // 吸附网格是 min + round((v-min)/step)*step。
            // 三者必须同源：只要「步长 < 网格」或锚点不是 m 的整数倍，
            // “+” 能动、“−” 会被四舍五入吃回原值（对齐倍数 32 时 100% 复现）。
            try { w.options.step = m; } catch (_) { /* ignore */ }
            try { w.options.step2 = m; } catch (_) { /* ignore */ }
            try { w.options.min = m; } catch (_) { /* ignore */ }   // 锚点 = m 的整数倍 ⇒ 等价于从 0 对齐，与后端一致
            try { w.step = m; } catch (_) { /* ignore */ }
            try { w.options.round = m; } catch (_) { /* ignore */ }
        }
    };

    /** 把值写到部件（值没变就不写，避免触发重渲染） */
    const writeIfDiff = (w, value) => {
        if (!w) return;
        const next = Number(value);
        if (Number(w.value) !== next) setWidgetValue(w, next);
    };

    let syncing = false;
    /** 以宽度为基准修正高度（切比例 / 改宽 / 改对齐倍数都走这里） */
    const syncFromWidth = () => {
        if (syncing) return;
        const m = multipleOf(node);
        const ratio = RATIO_MAP[readStr(node, "aspect_ratio", "自定义")];
        syncing = true;
        try {
            const w = snap(clampN(readInt(node, "width", 1024), 64, 8192), m);
            writeIfDiff(wWidth, w);
            if (Number.isFinite(ratio) && ratio > 0) {
                writeIfDiff(wHeight, Math.max(m, snap(w / ratio, m)));
            } else {
                writeIfDiff(wHeight, snap(clampN(readInt(node, "height", 1024), 64, 8192), m));
            }
        } finally { syncing = false; }
    };

    /** 以高度为基准修正宽度 */
    const syncFromHeight = () => {
        if (syncing) return;
        const m = multipleOf(node);
        const ratio = RATIO_MAP[readStr(node, "aspect_ratio", "自定义")];
        syncing = true;
        try {
            const h = snap(clampN(readInt(node, "height", 1024), 64, 8192), m);
            writeIfDiff(wHeight, h);
            if (Number.isFinite(ratio) && ratio > 0) {
                writeIfDiff(wWidth, Math.max(m, snap(h * ratio, m)));
            } else {
                writeIfDiff(wWidth, snap(clampN(readInt(node, "width", 1024), 64, 8192), m));
            }
        } finally { syncing = false; }
    };

    const chainCallback = (w, handler) => {
        if (!w) return;
        const original = w.callback;
        w.callback = function (...args) {
            try { if (original) original.apply(this, args); } catch (err) { console.warn(err); }
            try { handler(); } catch (_) { /* ignore */ }
        };
    };

    applyStep();
    chainCallback(wRatio, syncFromWidth);
    chainCallback(wWidth, syncFromWidth);
    chainCallback(wHeight, syncFromHeight);
    chainCallback(wMultiple, () => { applyStep(); syncFromWidth(); });
    st.syncStep = applyStep;
    st.syncFromWidth = syncFromWidth;

    /* ── 参数变化 → 重画（只在值真变时刷）───────────────────────── */
    const watchWidgets = () => {
        const raw = readStr(node, "layout", "");
        const stamp = [readStr(node, "aspect_ratio", ""), readInt(node, "width", 0),
                       readInt(node, "height", 0), readInt(node, "multiple", 0),
                       readInt(node, "feathering", 0), readStr(node, "resample", ""),
                       raw, fillColorValue(node)].join("|");
        if (stamp === st.widgetStamp) return;
        st.widgetStamp = stamp;
        st.canvasMask = null;      // 参数变了，上一次跑出来的遮罩就过期了
        if (raw !== st.lastLayoutRaw) {
            st.lastLayoutRaw = raw;
            const parsed = parseLayout(raw);
            if (parsed && !st.drag) st.layout = parsed;
        }
        if (st.colorInput) {
            try { st.syncColor?.(); } catch (_) { /* ignore */ }
        }
        requestDraw();
    };

    st.paint = paint;
    st.refresh = () => refreshImage(true);
    st.watch = watchWidgets;
    node.__xbObState = st;
    try { st.syncFromWidth(); } catch (_) { /* ignore */ }

    // 参数部件在 Nodes 2.0 里是 Vue 组件、没有可靠回调，用 rAF 做「值变化检测」：
    // 每 3 帧（≈20fps）比几个字符串，值变了才重画，开销可以忽略。
    let frameCount = 0;
    const tick = () => {
        if (!st.alive) return;
        frameCount += 1;
        if (frameCount % 3 === 0) {
            try { watchWidgets(); } catch (_) { /* ignore */ }
        }
        st.raf2 = requestAnimationFrame(tick);
    };

    try {
        if (typeof ResizeObserver === "function") {
            st.observer = new ResizeObserver(() => requestDraw());
            st.observer.observe(wrap);
        }
    } catch (_) { /* ignore */ }
    window.addEventListener("resize", requestDraw);

    setTimeout(() => { requestDraw(); try { refreshImage(false); } catch (_) { /* ignore */ } }, 0);
    setTimeout(() => { requestDraw(); }, 400);

    /**
     * 新建节点：按实际内容高度补一次合理尺寸。
     * 加载工作流（走了 onConfigure）时尺寸由文件决定，这里绝不插手，否则又会「刷新就变高」。
     */
    const applyDefaultSize = () => {
        try {
            if (node.__xbConfigured) return;
            const el = document.querySelector('.lg-node[data-node-id="' + node.id + '"]');
            if (!el) return;
            const scale = Math.abs(Number(app?.canvas?.ds?.scale)) || 1;
            const needW = Math.ceil((el.offsetWidth || 0) / scale);
            const needH = Math.ceil((el.offsetHeight || 0) / scale);
            const w = Math.max(Number(node.size?.[0]) || 0, Math.min(needW || 0, 900), 420);
            const h = Math.max(Number(node.size?.[1]) || 0, Math.min(needH || 0, 900));
            if (h > (Number(node.size?.[1]) || 0) + 4 || w > (Number(node.size?.[0]) || 0) + 4) {
                node.setSize([w, h]);
            }
        } catch (_) { /* ignore */ }
    };
    setTimeout(applyDefaultSize, 600);
    st.raf2 = requestAnimationFrame(tick);

    const origRemoved = node.onRemoved;
    node.onRemoved = function () {
        st.alive = false;
        try { cancelAnimationFrame(st.raf2); } catch (_) { /* ignore */ }
        try { cancelAnimationFrame(st.raf); } catch (_) { /* ignore */ }
        try { st.observer?.disconnect?.(); } catch (_) { /* ignore */ }
        try { window.removeEventListener("resize", requestDraw); } catch (_) { /* ignore */ }
        return origRemoved?.apply(this, arguments);
    };

    // 后端 ui 预览：跑过一次之后，把「最终遮罩」铺在画布框上（红色 = 会被模型重绘的区域）。
    // 注意：绝不能拿返回的「画布图」当预览底图 —— 那是外补后的画布，会顶掉可编辑的原图。
    node.onExecuted = function (message) {
        try {
            const maskFile = message?.xb_outpaint_mask?.[0];
            if (!maskFile) return;
            const mi = new Image();
            mi.onload = () => {
                if (!st.alive) return;
                st.canvasMask = mi;
                requestDraw();
            };
            mi.onerror = () => { st.canvasMask = null; };
            mi.src = fileUrl(maskFile, ++st.loadSeq);
        } catch (err) {
            console.warn("[XB-BOX 外补画板] 处理运行结果预览失败", err);
        }
    };
}

/* ============================================================
 *  扩展注册
 * ============================================================ */
app.registerExtension({
    name: "XB_ToolBox.OutpaintBoard",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_TYPE) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            if (onNodeCreated) onNodeCreated.apply(this, arguments);
            try {
                setup(this);
            } catch (err) {
                console.error("[XB-BOX 外补画板] 初始化失败", err);
            }
        };

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            this.__xbConfigured = true;      // 尺寸来自工作流文件，不要再按内容“纠正”
            const r = onConfigure ? onConfigure.apply(this, arguments) : undefined;
            const node = this;
            setTimeout(() => {
                try {
                    const wLayout = (node.widgets || []).find((x) => x && x.name === "layout");
                    const wFill = (node.widgets || []).find((x) => x && x.name === "fill_color");
                    if (wLayout) setWidgetHidden(node, wLayout, true);
                    if (wFill) setWidgetHidden(node, wFill, true);
                    refreshWidgets(node);
                    const st = node.__xbObState;
                    if (st) {
                        st.layout = parseLayout(readStr(node, "layout", ""));
                        st.widgetStamp = "";
                        st.lastLayoutRaw = null;
                        st.drag = null;
                        try { st.syncStep?.(); st.syncFromWidth?.(); } catch (_) { /* ignore */ }
                        try { st.syncColor?.(); } catch (_) { /* ignore */ }
                        if (typeof st.watch === "function") st.watch();   // 恢复「短边尺寸」显隐
                        if (typeof st.paint === "function") st.paint();
                        st.refresh?.();
                    }
                } catch (err) {
                    console.warn("[XB-BOX 外补画板] 载入后刷新失败", err);
                }
            }, 0);
            return r;
        };
    },
});
