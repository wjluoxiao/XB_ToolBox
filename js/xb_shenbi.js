/**
 * XB-BOX - 🖌️ 神笔（ShenBi）— 画板节点前端
 * ============================================================================
 * · 无输入端，只有一个 Image 输出；两个模式：创作 / 编辑
 * · 画幅比例 + 宽高：32 步长对齐 + 比例联动（与「XB-BOX - 🖼️ 图片参数大全mini」同一套算法）
 * · 节点布局（自上而下）：模式 / 画幅比例 / 宽度 / 高度 / 画布底色 或 图片+上传
 *   → 操作按钮 → 显示窗。显示窗**两个模式都有**，且高度吸附节点：
 *       创作模式 —— 没有画板存档时显示「设定分辨率 + 画布底色」的纯色画布（默认纯白）；
 *       编辑模式 —— 显示画板存档，没画过则显示源图；
 *       画过之后两个模式都显示画板存档。
 * · 显示窗只做显示，不做点击编辑（避免和操作按钮重复成两个编辑入口）；
 *   官方 image_upload 自带的 `upload` 按钮按模式显隐，`$$canvas-image-preview` 面板一律隐藏，
 *   保证「显示窗」全节点只有一个。
 * · 画板（参考官方 Load Image 节点「右击 → 在遮罩编辑器中打开」的交互）：画笔粗细 /
 *   颜色 / 橡皮 / 水平·垂直翻转 / 左·右旋转 / 上一步 / 下一步 / 清空。
 * · 画板**以图片文件形式存**（和官方遮罩编辑器同一套做法，POST /upload/image 到 input/xb_shenbi/），
 *   节点里只存文件名。⚠️ 绝不能把 PNG base64 塞进部件值：一幅 1024² 的图就有 1.7MB，
 *   工作流 JSON 会从 1.6KB 涨到 3.4MB，超过浏览器草稿存储配额后**整个工作流都存不下来**
 *   （刷新就丢失）。老工作流里已存在的 dataURL 仍能正常显示（后端也兼容解码）。
 */

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import { setWidgetValue, setWidgetHidden, refreshWidgets } from "./xb_compat.js";

const NODE_TYPE = "XB_ShenBi";
const MODE_CREATE = "创作";
const MODE_EDIT = "编辑";

// 官方 image_upload 自动带来的两个部件（都要按模式接管，否则和显示窗重复成两个窗口）
const WIDGET_UPLOAD = "upload";
const WIDGET_OFFICIAL_PREVIEW = "$$canvas-image-preview";

// 画板文件落在 input/xb_shenbi/ 下，命名 = xb_shenbi_<节点id>_<模式>.png（同名覆盖，不堆垃圾文件）
const PAINT_SUBFOLDER = "xb_shenbi";
const PAINT_EXT_RE = /\.(png|jpe?g|webp|bmp|tiff?)$/i;

const STEP = 32;
const SIZE_MIN = 32;
const SIZE_MAX = 16384;
const RATIO_MAP = { "1:1": 1, "16:9": 16 / 9, "9:16": 9 / 16, "4:3": 4 / 3, "3:4": 3 / 4, "21:9": 21 / 9 };

const BG_WHITE = "白色";
const BG_BLACK = "黑色";
const WHITE = "#ffffff";
const BLACK = "#000000";

const PANEL_MIN = 120;     // 显示窗最小高度（节点被拖到最小时的下限）
const PANEL_EXTRA = 180;   // 新建节点时额外给显示窗的高度
const TICK_MS = 500;
const BLANK_MAX_PX = 512;  // 纯色画布预览图的边长上限（只用来示意比例，不需要全分辨率）

const BRUSH_MIN = 1;
const BRUSH_MAX = 300;
const BRUSH_DEFAULT = 8;
const UNDO_LIMIT = 24;
const UNDO_BYTES = 192 * 1024 * 1024;

const SWATCHES = [WHITE, BLACK, "#ff4d4d", "#ff9a3d", "#ffe14d", "#5ddc5d", "#4dd2ff", "#4d7dff", "#b366ff", "#ff66b3", "#8c6239"];

/* ============================================================
 *  小工具
 * ============================================================ */
function findWidget(node, name) {
    return (node?.widgets || []).find((w) => w && w.name === name) || null;
}

function getVal(node, name) {
    const w = findWidget(node, name);
    return w ? w.value : undefined;
}

function snap(value) {
    const raw = Number(value);
    const base = Number.isFinite(raw) ? raw : SIZE_MIN;
    return Math.min(SIZE_MAX, Math.max(SIZE_MIN, Math.round(base / STEP) * STEP));
}

/** 与后端 _resolve_size 等价：比例联动 + 32 步长对齐 */
function resolveTarget(node) {
    let w = snap(getVal(node, "width"));
    let h = snap(getVal(node, "height"));
    const ratio = RATIO_MAP[String(getVal(node, "aspect_ratio") || "Free")];
    if (ratio) {
        if (w >= h) h = snap(w / ratio);
        else w = snap(h * ratio);
    }
    return [w, h];
}

function notify(message, type) {
    try {
        if (app?.extensionManager?.toast?.add) {
            app.extensionManager.toast.add({ severity: type || "info", summary: "🖌️ 神笔", detail: message, life: 4000 });
            return;
        }
    } catch (_) { /* ignore */ }
    console.log(`[XB-BOX 神笔] ${message}`);
}

function viewUrl(name) {
    const parts = String(name || "").split("/");
    const filename = parts.pop();
    const params = new URLSearchParams({ filename, type: "input" });
    if (parts.length) params.set("subfolder", parts.join("/"));
    return api.apiURL("/view?" + params.toString());
}

/** 纯色画布预览图（按设定分辨率等比缩到 ≤512，只用于示意比例与底色） */
const blankCache = new Map();
function blankCanvasUrl(width, height, color) {
    const key = `${width}x${height}|${color}`;
    if (blankCache.has(key)) return blankCache.get(key);
    const scale = Math.min(1, BLANK_MAX_PX / Math.max(width, height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(width * scale));
    canvas.height = Math.max(1, Math.round(height * scale));
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = color === BG_BLACK ? BLACK : WHITE;
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    const url = canvas.toDataURL("image/png");
    blankCache.set(key, url);
    return url;
}

function loadBitmap(url) {
    return new Promise((resolve, reject) => {
        const img = new Image();
        img.onload = () => resolve(img);
        img.onerror = () => reject(new Error("图片加载失败"));
        img.src = url;
    });
}

/** 等比覆盖式绘制（等价后端 _cover_crop，保证不留黑边） */
function drawCover(ctx, bitmap, width, height) {
    const sw = bitmap.naturalWidth || bitmap.width || 0;
    const sh = bitmap.naturalHeight || bitmap.height || 0;
    if (!sw || !sh) return;
    const scale = Math.max(width / sw, height / sh);
    const dw = sw * scale;
    const dh = sh * scale;
    ctx.drawImage(bitmap, (width - dw) / 2, (height - dh) / 2, dw, dh);
}

function cloneCanvas(source) {
    const copy = document.createElement("canvas");
    copy.width = source.width;
    copy.height = source.height;
    copy.getContext("2d").drawImage(source, 0, 0);
    return copy;
}

function canvasToBlob(canvas) {
    return new Promise((resolve) => {
        try {
            canvas.toBlob((blob) => resolve(blob || null), "image/png");
        } catch (_) {
            resolve(null);
        }
    });
}

/** 画板存档 → 可显示的 URL：文件名走 /view，老工作流的内嵌 dataURL 直接用 */
function paintingUrl(value) {
    const text = String(value || "");
    if (!text) return "";
    return text.startsWith("data:") ? text : viewUrl(text);
}

/** 画板存档是否是有效内容：dataURL 或 input 里的图片文件名（脏值如 "image" 一律当空） */
function isPainting(value) {
    const text = String(value || "").trim();
    if (!text) return false;
    if (text.startsWith("data:image/")) return true;
    return PAINT_EXT_RE.test(text) && !/[\n\r]/.test(text);
}

/** 把画布 PNG 传到 input/xb_shenbi/ 下，返回节点里要存的文件名（"子目录/文件名"） */
async function uploadPainting(blob, filename) {
    const body = new FormData();
    body.append("image", blob, filename);
    body.append("type", "input");
    body.append("subfolder", PAINT_SUBFOLDER);
    body.append("overwrite", "true");
    const resp = await api.fetchApi("/upload/image", { method: "POST", body });
    if (resp.status !== 200) throw new Error("上传失败 HTTP " + resp.status);
    const data = await resp.json();
    if (!data?.name) throw new Error("上传返回异常");
    return data.subfolder ? `${data.subfolder}/${data.name}` : data.name;
}

/** dataURL → Blob（用于上传） */
async function canvasBlobOf(dataUrl) {
    const resp = await fetch(dataUrl);
    return resp.ok ? resp.blob() : null;
}

/* ============================================================
 *  画板编辑器（模态）
 * ============================================================ */
let styleInjected = false;
function ensureStyle() {
    if (styleInjected || document.getElementById("xb-shenbi-style")) { styleInjected = true; return; }
    styleInjected = true;
    const css = [
        ".xb-sb-mask{position:fixed;left:0;top:0;right:0;bottom:0;z-index:100000;background:rgba(8,8,10,.95);",
        "display:flex;flex-direction:column;color:#eaeaf0;font-size:15px;user-select:none;",
        "font-family:system-ui,-apple-system,'Segoe UI','Microsoft YaHei',sans-serif;}",
        ".xb-sb-top{display:flex;align-items:center;gap:10px;padding:14px 20px;background:#202027;border-bottom:1px solid #3a3a45;flex-wrap:wrap;}",
        ".xb-sb-title{font-size:20px;font-weight:700;white-space:nowrap;}",
        ".xb-sb-title em{font-style:normal;font-weight:500;color:#a7aeba;margin-left:14px;font-size:15px;}",
        ".xb-sb-sp{flex:1 1 auto;}",
        ".xb-sb-btn{background:#31313c;border:1px solid #474754;color:#eaeaf0;border-radius:8px;padding:11px 17px;",
        "font-size:15px;line-height:1;cursor:pointer;white-space:nowrap;transition:background .12s;}",
        ".xb-sb-btn:hover:not(:disabled){background:#43434f;}",
        ".xb-sb-btn:disabled{opacity:.35;cursor:default;}",
        ".xb-sb-btn.on{background:#3b6fd4;border-color:#6191ea;}",
        ".xb-sb-btn.ok{background:#2f7d44;border-color:#43a75e;font-weight:700;}",
        ".xb-sb-btn.ok:hover{background:#379150;}",
        ".xb-sb-bar{display:flex;align-items:center;gap:20px;padding:12px 20px;background:#17171c;border-bottom:1px solid #2e2e38;",
        "flex-wrap:wrap;font-size:15px;color:#c4cad4;}",
        ".xb-sb-bar label{display:flex;align-items:center;gap:9px;}",
        ".xb-sb-bar input[type=range]{width:220px;height:26px;accent-color:#6191ea;}",
        ".xb-sb-bar input[type=number]{width:88px;background:#26262f;border:1px solid #474754;color:#eaeaf0;",
        "border-radius:7px;padding:7px 9px;font-size:15px;}",
        ".xb-sb-bar input[type=color]{width:52px;height:38px;padding:0;border:1px solid #474754;background:#26262f;",
        "border-radius:7px;cursor:pointer;}",
        ".xb-sb-swatches{display:flex;align-items:center;gap:7px;}",
        ".xb-sb-sw{width:28px;height:28px;border-radius:50%;border:2px solid #55555f;cursor:pointer;box-sizing:border-box;}",
        ".xb-sb-sw:hover{transform:scale(1.08);}",
        ".xb-sb-sw.on{border-color:#fff;box-shadow:0 0 0 3px #6191ea;}",
        ".xb-sb-stage{flex:1 1 auto;display:flex;align-items:center;justify-content:center;padding:26px;overflow:auto;",
        "background:repeating-conic-gradient(#2a2a31 0% 25%,#212127 0% 50%) 50%/28px 28px;}",
        ".xb-sb-stage canvas{max-width:100%;max-height:100%;box-shadow:0 0 0 1px #4f4f5b,0 14px 44px rgba(0,0,0,.7);",
        "cursor:crosshair;touch-action:none;background:#fff;}",
        ".xb-sb-tip{color:#9aa2ae;font-size:15px;}",
    ].join("");
    const style = document.createElement("style");
    style.id = "xb-shenbi-style";
    style.textContent = css;
    document.head.appendChild(style);
}

/**
 * 打开画板。
 * cfg = { mode, width, height, fillColor, imageUrl?, paintedUrl?, targetW?, targetH? }
 * 返回 Promise<{dataUrl,width,height}|null>
 */
async function openBrushEditor(cfg) {
    ensureStyle();

    // ── 1. 决定工作画布尺寸 & 底图 ──────────────────────────────────
    let width = 0;
    let height = 0;
    let bitmap = null;
    try {
        if (cfg.paintedUrl) {
            bitmap = await loadBitmap(cfg.paintedUrl);
            width = bitmap.naturalWidth;
            height = bitmap.naturalHeight;
        } else if (cfg.imageUrl) {
            bitmap = await loadBitmap(cfg.imageUrl);
            const sw = bitmap.naturalWidth;
            const sh = bitmap.naturalHeight;
            // 编辑模式：大于设定分辨率才缩小裁切，小于则保持原尺寸
            if (cfg.targetW && cfg.targetH && (sw > cfg.targetW || sh > cfg.targetH)) {
                width = cfg.targetW;
                height = cfg.targetH;
            } else {
                width = sw;
                height = sh;
            }
        }
    } catch (err) {
        notify("图片载入失败：" + ((err && err.message) || err), "error");
        return null;
    }
    if (!width || !height) { width = cfg.width || 1024; height = cfg.height || 1024; }

    return new Promise((resolve) => {
        /* ── DOM ─────────────────────────────────────────────────── */
        const mask = document.createElement("div");
        mask.className = "xb-sb-mask";

        const top = document.createElement("div");
        top.className = "xb-sb-top";
        const title = document.createElement("div");
        title.className = "xb-sb-title";
        title.textContent = cfg.mode === MODE_CREATE ? "🎨 创作画布" : "🖌️ 编辑图片";
        const meta = document.createElement("em");
        meta.textContent = `${width} × ${height}`;
        title.appendChild(meta);
        top.appendChild(title);
        top.appendChild(Object.assign(document.createElement("div"), { className: "xb-sb-sp" }));

        const mkBtn = (label, act, cls, hint) => {
            const b = document.createElement("button");
            b.className = "xb-sb-btn" + (cls ? " " + cls : "");
            b.textContent = label;
            if (hint) b.title = hint;
            b.dataset.act = act;
            return b;
        };
        const actions = {
            undo: mkBtn("↩ 上一步", "undo", "", "撤销上一笔（Ctrl+Z）"),
            redo: mkBtn("↪ 下一步", "redo", "", "重做（Ctrl+Shift+Z）"),
            fliph: mkBtn("⇄ 水平翻转", "fliph", "", "左右翻转画布"),
            flipv: mkBtn("⇅ 垂直翻转", "flipv", "", "上下翻转画布"),
            rotl: mkBtn("↺ 左转90°", "rotl", "", "逆时针旋转 90°"),
            rotr: mkBtn("↻ 右转90°", "rotr", "", "顺时针旋转 90°"),
            clear: mkBtn("🧽 清空", "clear", "", "用画布底色重新铺满"),
        };
        for (const key of ["undo", "redo", "fliph", "flipv", "rotl", "rotr", "clear"]) top.appendChild(actions[key]);
        const cancel = mkBtn("✖ 取消", "cancel");
        const save = mkBtn("✔ 保存", "save", "ok", "保存画板（Ctrl+S）");
        top.appendChild(cancel);
        top.appendChild(save);

        const bar = document.createElement("div");
        bar.className = "xb-sb-bar";

        const sizeLabel = document.createElement("label");
        sizeLabel.append("画笔粗细");
        const sizeRange = document.createElement("input");
        sizeRange.type = "range";
        sizeRange.min = String(BRUSH_MIN);
        sizeRange.max = String(BRUSH_MAX);
        sizeRange.step = "1";
        sizeRange.value = String(BRUSH_DEFAULT);
        const sizeNum = document.createElement("input");
        sizeNum.type = "number";
        sizeNum.min = String(BRUSH_MIN);
        sizeNum.max = String(BRUSH_MAX);
        sizeNum.value = String(BRUSH_DEFAULT);
        sizeLabel.append(sizeRange, sizeNum, "px");

        const colorLabel = document.createElement("label");
        colorLabel.append("颜色");
        const swatchBox = document.createElement("div");
        swatchBox.className = "xb-sb-swatches";
        const colorInput = document.createElement("input");
        colorInput.type = "color";
        colorInput.value = BLACK;
        const swatchEls = SWATCHES.map((color) => {
            const dot = document.createElement("div");
            dot.className = "xb-sb-sw";
            dot.style.background = color;
            dot.dataset.color = color;
            dot.addEventListener("click", () => pickColor(color));
            swatchBox.appendChild(dot);
            return dot;
        });
        colorLabel.append(swatchBox, colorInput);

        const eraserLabel = document.createElement("label");
        const eraserBtn = mkBtn("🩹 橡皮", "eraser");
        eraserLabel.appendChild(eraserBtn);

        const hint = document.createElement("span");
        hint.className = "xb-sb-tip";
        hint.textContent = "按住左键拖动即可作画";

        bar.append(sizeLabel, colorLabel, eraserLabel, Object.assign(document.createElement("div"), { className: "xb-sb-sp" }), hint);

        const stage = document.createElement("div");
        stage.className = "xb-sb-stage";
        const canvas = document.createElement("canvas");
        canvas.width = width;
        canvas.height = height;
        stage.appendChild(canvas);

        mask.append(top, bar, stage);
        document.body.appendChild(mask);

        /* ── 画布状态 ────────────────────────────────────────────── */
        let ctx = canvas.getContext("2d", { willReadFrequently: true });
        /** 底色层：橡皮擦除时用来还原原始像素 */
        const baseCanvas = document.createElement("canvas");
        baseCanvas.width = width;
        baseCanvas.height = height;
        let bctx = baseCanvas.getContext("2d", { willReadFrequently: true });
        const scratch = document.createElement("canvas");
        scratch.width = width;
        scratch.height = height;
        let sctx = scratch.getContext("2d", { willReadFrequently: true });

        let brushSize = BRUSH_DEFAULT;
        let brushColor = BLACK;
        let eraser = false;

        const fill = () => {
            ctx.setTransform(1, 0, 0, 1, 0, 0);
            ctx.globalCompositeOperation = "source-over";
            ctx.fillStyle = cfg.fillColor || WHITE;
            ctx.fillRect(0, 0, canvas.width, canvas.height);
        };

        /** 初始内容：有底图就覆盖式画上去，否则铺底色；底色层同步一份 */
        const initContent = () => {
            if (bitmap) drawCover(ctx, bitmap, canvas.width, canvas.height);
            else fill();
            bctx.setTransform(1, 0, 0, 1, 0, 0);
            bctx.globalCompositeOperation = "source-over";
            bctx.clearRect(0, 0, baseCanvas.width, baseCanvas.height);
            bctx.drawImage(canvas, 0, 0);
        };
        initContent();

        /* ── 历史（上一步 / 下一步） ─────────────────────────────── */
        const history = [];
        let hIndex = -1;
        let hBytes = 0;
        let restoring = false;

        const entryBytes = (item) => item.w * item.h * 4 * 2;

        function pushHistory() {
            if (restoring) return;
            history.splice(hIndex + 1);
            const item = {
                w: canvas.width,
                h: canvas.height,
                main: cloneCanvas(canvas),
                base: cloneCanvas(baseCanvas),
            };
            history.push(item);
            hBytes += entryBytes(item);
            hIndex = history.length - 1;
            while (history.length > UNDO_LIMIT || (hBytes > UNDO_BYTES && history.length > 2)) {
                hBytes -= entryBytes(history.shift());
                hIndex -= 1;
            }
            updateButtons();
        }

        function restoreHistory(index) {
            const item = history[index];
            if (!item) return;
            restoring = true;
            resizeSurface(item.w, item.h);
            ctx.setTransform(1, 0, 0, 1, 0, 0);
            ctx.globalCompositeOperation = "source-over";
            ctx.clearRect(0, 0, item.w, item.h);
            ctx.drawImage(item.main, 0, 0);
            bctx.setTransform(1, 0, 0, 1, 0, 0);
            bctx.globalCompositeOperation = "source-over";
            bctx.clearRect(0, 0, item.w, item.h);
            bctx.drawImage(item.base, 0, 0);
            hIndex = index;
            restoring = false;
            updateButtons();
        }

        function resizeSurface(w, h) {
            canvas.width = w;
            canvas.height = h;
            baseCanvas.width = w;
            baseCanvas.height = h;
            scratch.width = w;
            scratch.height = h;
            ctx = canvas.getContext("2d", { willReadFrequently: true });
            bctx = baseCanvas.getContext("2d", { willReadFrequently: true });
            sctx = scratch.getContext("2d", { willReadFrequently: true });
            meta.textContent = `${w} × ${h}`;
        }

        function updateButtons() {
            actions.undo.disabled = hIndex <= 0;
            actions.redo.disabled = hIndex < 0 || hIndex >= history.length - 1;
        }

        /* ── 画笔 ────────────────────────────────────────────────── */
        function pickColor(color) {
            brushColor = color;
            colorInput.value = color;
            eraser = false;
            eraserBtn.classList.remove("on");
            for (const dot of swatchEls) dot.classList.toggle("on", dot.dataset.color.toLowerCase() === String(color).toLowerCase());
        }

        function setBrushSize(value, syncRange) {
            const num = Math.min(BRUSH_MAX, Math.max(BRUSH_MIN, Math.round(Number(value) || BRUSH_MIN)));
            brushSize = num;
            if (syncRange) sizeRange.value = String(num);
            sizeNum.value = String(num);
        }

        function strokeStyleOf(target) {
            target.lineCap = "round";
            target.lineJoin = "round";
            target.lineWidth = brushSize;
            target.strokeStyle = brushColor;
            target.globalCompositeOperation = "source-over";
        }

        /** 橡皮：把底色层里对应位置的原始像素贴回画布（保留 alpha 边缘的柔和过渡） */
        function eraseSegment(x0, y0, x1, y1) {
            sctx.setTransform(1, 0, 0, 1, 0, 0);
            sctx.globalCompositeOperation = "source-over";
            sctx.clearRect(0, 0, scratch.width, scratch.height);
            strokeStyleOf(sctx);
            sctx.strokeStyle = BLACK;
            sctx.beginPath();
            sctx.moveTo(x0, y0);
            sctx.lineTo(x1, y1);
            sctx.stroke();
            sctx.globalCompositeOperation = "source-in";
            sctx.drawImage(baseCanvas, 0, 0);
            ctx.globalCompositeOperation = "source-over";
            ctx.drawImage(scratch, 0, 0);
        }

        function paintSegment(x0, y0, x1, y1) {
            if (eraser) { eraseSegment(x0, y0, x1, y1); return; }
            strokeStyleOf(ctx);
            ctx.beginPath();
            ctx.moveTo(x0, y0);
            ctx.lineTo(x1, y1);
            ctx.stroke();
        }

        /* ── 指针事件 ────────────────────────────────────────────── */
        let drawing = false;
        let last = null;

        const toCanvas = (event) => {
            const rect = canvas.getBoundingClientRect();
            return {
                x: (event.clientX - rect.left) * (canvas.width / rect.width),
                y: (event.clientY - rect.top) * (canvas.height / rect.height),
            };
        };

        canvas.addEventListener("pointerdown", (event) => {
            if (event.button !== 0 && event.pointerType === "mouse") return;
            event.preventDefault();
            try { canvas.setPointerCapture(event.pointerId); } catch (_) { /* 合成事件无有效 pointerId */ }
            drawing = true;
            const p = toCanvas(event);
            last = p;
            paintSegment(p.x, p.y, p.x + 0.01, p.y + 0.01);
        });

        canvas.addEventListener("pointermove", (event) => {
            if (!drawing) return;
            event.preventDefault();
            const p = toCanvas(event);
            paintSegment(last.x, last.y, p.x, p.y);
            last = p;
        });

        const endStroke = (event) => {
            if (!drawing) return;
            drawing = false;
            last = null;
            try { canvas.releasePointerCapture(event.pointerId); } catch (_) { /* ignore */ }
            pushHistory();
        };
        canvas.addEventListener("pointerup", endStroke);
        canvas.addEventListener("pointercancel", endStroke);

        /* ── 变换 ────────────────────────────────────────────────── */
        function transformCanvas(mode) {
            const w = canvas.width;
            const h = canvas.height;
            const mainCopy = cloneCanvas(canvas);
            const baseCopy = cloneCanvas(baseCanvas);
            const nextW = (mode === "rotl" || mode === "rotr") ? h : w;
            const nextH = (mode === "rotl" || mode === "rotr") ? w : h;
            resizeSurface(nextW, nextH);

            const apply = (target, source) => {
                target.setTransform(1, 0, 0, 1, 0, 0);
                target.globalCompositeOperation = "source-over";
                target.clearRect(0, 0, nextW, nextH);
                target.save();
                if (mode === "rotl") { target.translate(0, w); target.rotate(-Math.PI / 2); }
                else if (mode === "rotr") { target.translate(h, 0); target.rotate(Math.PI / 2); }
                else if (mode === "fliph") { target.translate(w, 0); target.scale(-1, 1); }
                else if (mode === "flipv") { target.translate(0, h); target.scale(1, -1); }
                target.drawImage(source, 0, 0);
                target.restore();
            };
            apply(ctx, mainCopy);
            apply(bctx, baseCopy);
        }

        /* ── 顶部 / 工具条按钮 ───────────────────────────────────── */
        top.addEventListener("click", (event) => {
            const act = event.target?.dataset?.act;
            if (!act) return;
            if (act === "undo") { restoreHistory(hIndex - 1); return; }
            if (act === "redo") { restoreHistory(hIndex + 1); return; }
            if (act === "clear") { fill(); pushHistory(); return; }
            if (act === "cancel") { finish(null); return; }
            if (act === "save") { finish(canvas.toDataURL("image/png")); return; }
            transformCanvas(act);
            pushHistory();
        });

        eraserBtn.addEventListener("click", () => {
            eraser = !eraser;
            eraserBtn.classList.toggle("on", eraser);
            hint.textContent = eraser ? "橡皮：擦回画布底色 / 原图" : "按住左键拖动即可作画";
        });

        sizeRange.addEventListener("input", () => setBrushSize(sizeRange.value, false));
        sizeNum.addEventListener("input", () => setBrushSize(sizeNum.value, true));
        colorInput.addEventListener("input", () => pickColor(colorInput.value));

        /* ── 键盘 ────────────────────────────────────────────────── */
        const onKey = (event) => {
            const ctrl = event.ctrlKey || event.metaKey;
            if (event.key === "Escape") { event.preventDefault(); finish(null); return; }
            if (ctrl && event.key.toLowerCase() === "s") { event.preventDefault(); finish(canvas.toDataURL("image/png")); return; }
            if (ctrl && event.key.toLowerCase() === "z") {
                event.preventDefault();
                if (event.shiftKey) restoreHistory(hIndex + 1); else restoreHistory(hIndex - 1);
            }
        };
        window.addEventListener("keydown", onKey, true);

        function finish(dataUrl) {
            window.removeEventListener("keydown", onKey, true);
            mask.remove();
            if (!dataUrl) { resolve(null); return; }
            resolve({ dataUrl, width: canvas.width, height: canvas.height });
        }

        pickColor(BLACK);
        setBrushSize(BRUSH_DEFAULT, true);
        pushHistory();
    });
}

/* ============================================================
 *  节点挂载
 * ============================================================ */
function setupNode(node) {
    if (!node || node.__xbSbReady) return;
    const wMode = findWidget(node, "mode");
    const wAR = findWidget(node, "aspect_ratio");
    const wW = findWidget(node, "width");
    const wH = findWidget(node, "height");
    const wColor = findWidget(node, "canvas_color");
    const wImage = findWidget(node, "image");
    const wPaint = findWidget(node, "painted_data");
    const wCreate = findWidget(node, "created_data");
    if (!wMode || !wAR || !wW || !wH || !wPaint) return;
    node.__xbSbReady = true;

    setWidgetHidden(node, wPaint, true);
    setWidgetHidden(node, wCreate, true);

    /** 两种模式各存各的画板：创作 = created_data，编辑 = painted_data（互不串台） */
    const paintWidget = (create) => (create ? wCreate : wPaint);
    const isCreateMode = () => String(getVal(node, "mode")) !== MODE_EDIT;
    /** 只认真正的图片存档（dataURL 或 input 里的文件名）——老工作流按位还原时可能把别的值挤进槽位 */
    const paintValue = (create) => {
        const raw = paintWidget(create === undefined ? isCreateMode() : create)?.value;
        return isPainting(raw) ? String(raw).trim() : "";
    };
    /** 预览用时间戳：文件名固定（同名覆盖），加个后缀避免浏览器拿到旧缓存图 */
    let paintStamp = Date.now();
    const paintingSrc = (value) => {
        const text = String(value || "");
        if (!text) return "";
        return text.startsWith("data:") ? text : `${viewUrl(text)}&xb=${paintStamp}`;
    };
    /** 后端还没重启（object_info 里还没有 created_data）时，创作画板只在本次会话里临时撑住显示窗 */
    const transientPaint = () => (wCreate ? "" : String(node.__xbSbTransient || ""));

    /* ── 显示窗的尺寸策略：吸附节点 ─────────────────────────────
       前端 ComfyNode._arrangeWidgets 把部件分两类：
         · 有 computeSize 的 → 固定高度；· 只有 computeLayoutSize 的 → 弹性部件，
       用 distributeSpace() 把「节点高 - 其它部件」的剩余空间全部分给它（不足 minHeight 时
       取 minHeight 并把节点撑高）。所以显示窗**只能**给 computeLayoutSize：
       给了 computeSize 就会被当成固定高度，节点拖高时显示窗不跟着变；
       而如果让 computeSize 反过来读 node.size[1]，会和 _arrangeWidgets 互相喂数无限长高。 */
    let panel = null;
    let panelImg = null;
    let panelHint = null;
    let panelCaption = null;

    /* ── 按钮：打开画板（放在显示窗上面） ─────────────────────── */
    const openBoard = async () => {
        const create = isCreateMode();
        const [targetW, targetH] = resolveTarget(node);
        const painted = paintValue(create);
        const source = String(getVal(node, "image") || "");
        const color = String(getVal(node, "canvas_color") || BG_WHITE);

        const cfg = {
            mode: create ? MODE_CREATE : MODE_EDIT,
            width: targetW,
            height: targetH,
            fillColor: color === BG_BLACK ? BLACK : WHITE,
        };

        if (painted) {
            // 继续编辑上一次的画板（尺寸取画板自身，避免二次重采样）
            cfg.paintedUrl = paintingSrc(painted);
        } else if (!create && source) {
            cfg.imageUrl = viewUrl(source);
            cfg.targetW = targetW;
            cfg.targetH = targetH;
        } else if (!create) {
            notify("请先在图片下拉里选择/上传一张本地图片，当前以 " + targetW + "×" + targetH + " 空白画布打开", "warn");
        }

        const result = await openBrushEditor(cfg);
        if (!result) return;

        // 画板以**图片文件**形式存（和官方遮罩编辑器同套路），节点里只留文件名：
        // 内嵌 PNG base64 会让工作流 JSON 涨到几 MB，撑爆浏览器草稿配额 → 整个工作流刷新后丢失
        const fileName = `xb_shenbi_${node.id ?? 0}_${create ? "create" : "edit"}.png`;
        let stored = "";
        try {
            const blob = await canvasBlobOf(result.dataUrl);
            stored = blob ? await uploadPainting(blob, fileName) : result.dataUrl;
        } catch (err) {
            stored = result.dataUrl;   // 上传失败就退回内嵌，先保住用户的画
            notify("画板保存到 input 目录失败，已退回内嵌存档（工作流会变大）：" + ((err && err.message) || err), "warn");
        }
        paintStamp = Date.now();

        const target = paintWidget(create);
        if (target) {
            setWidgetValue(target, stored);
        } else {
            // 后端还没重启（没有 created_data 输入）：先临时留在显示窗上，并明确提示需要重启
            node.__xbSbTransient = stored;
            if (!node.__xbSbWarned) {
                node.__xbSbWarned = true;
                notify("创作画板需要重启 ComfyUI 才能存档（后端新增了 created_data 输入），当前只在本次会话临时显示", "warn");
            }
        }
        refreshPanel();
    };

    const actionWidget = node.addWidget("button", "🎨 创作画布", null, () => openBoard());
    if (actionWidget) { try { actionWidget.serialize = false; } catch (_) { /* ignore */ } }

    /* ── 显示窗（两个模式都有，只做显示） ─────────────────────── */
    try {
        const box = document.createElement("div");
        box.style.cssText = "position:relative;width:100%;height:100%;display:flex;align-items:center;" +
            "justify-content:center;background:#141419;border:1px solid #33333d;border-radius:8px;" +
            "overflow:hidden;box-sizing:border-box;";
        panelImg = document.createElement("img");
        // width/height:100% + object-fit:contain —— 小分辨率（如 64×64）的预览图也要撑满显示窗，
        // 不能只靠 max-width（那会让小图保持原始像素尺寸，在窗口中间缩成一个小方块）
        panelImg.style.cssText = "width:100%;height:100%;object-fit:contain;display:none;";
        panelHint = document.createElement("span");
        panelHint.style.cssText = "color:#8a929e;font-size:14px;padding:16px;text-align:center;line-height:1.7;";
        panelCaption = document.createElement("span");
        panelCaption.style.cssText = "position:absolute;left:10px;top:10px;padding:4px 11px;border-radius:999px;" +
            "background:rgba(20,20,25,.78);color:#cfd5df;font-size:12px;line-height:1;pointer-events:none;display:none;";
        box.append(panelImg, panelHint, panelCaption);
        panel = node.addDOMWidget("xb_sb_preview", "preview", box, { serialize: false, hideOnZoom: false });
    } catch (err) {
        panel = null;
        console.warn("[XB-BOX 神笔] 显示窗不可用：", err);
    }
    if (panel) {
        // 只给 computeLayoutSize（弹性）——不能给 computeSize，否则会被当成固定高度部件
        try { delete panel.computeSize; } catch (_) { panel.computeSize = undefined; }
        panel.computeLayoutSize = () => ({ minHeight: PANEL_MIN, maxHeight: undefined, minWidth: 0 });
        // 显示窗纯展示，不进 widgets_values（保持存档里的参数顺序干净）
        try { panel.serialize = false; } catch (_) { /* ignore */ }
    }

    function refreshPanel() {
        if (!panelImg) return;
        const create = isCreateMode();
        const painted = paintValue(create);
        const source = String(getVal(node, "image") || "");
        const [targetW, targetH] = resolveTarget(node);
        const color = String(getVal(node, "canvas_color") || BG_WHITE);

        let url = "";
        if (painted) url = paintingSrc(painted);
        else if (create) {
            const temp = transientPaint();
            url = temp ? paintingSrc(temp) : blankCanvasUrl(targetW, targetH, color);
        } else if (source) url = viewUrl(source);

        if (url) {
            if (panelImg.getAttribute("src") !== url) panelImg.src = url;
            panelImg.style.display = "block";
            panelHint.style.display = "none";
        } else {
            panelImg.removeAttribute("src");
            panelImg.style.display = "none";
            panelHint.style.display = "block";
            panelHint.textContent = "尚未作画\n请先在「图片」里选择或上传一张本地图片";
        }

        // 标注两个模式都显示：切换分辨率时这里会立刻反映目标尺寸
        if (panelCaption) {
            panelCaption.style.display = "block";
            panelCaption.textContent = create
                ? `${targetW} × ${targetH} · ${color}画布`
                : `目标 ${targetW} × ${targetH}`;
        }
    }

    /* ── 模式联动 ────────────────────────────────────────────── */
    // 创作：隐藏官方 图片下拉 / upload 上传按钮（不加载本地图片），显示底色行 + 纯色画布预览
    // 编辑：显示官方 图片下拉 + upload 上传按钮，显示源图 / 画板存档
    // 两个模式：官方 $$canvas-image-preview 一律隐藏，全节点只有本显示窗
    const applyMode = () => {
        const create = isCreateMode();
        setWidgetHidden(node, wColor, !create);
        setWidgetHidden(node, wImage, create);
        if (actionWidget) {
            actionWidget.name = create ? "🎨 创作画布" : "🖌️ 编辑图片";
            actionWidget.label = actionWidget.name;
        }
        refreshWidgets(node);
        refreshPanel();
        try { node.setDirtyCanvas?.(true, true); } catch (_) { /* ignore */ }
    };

    const needChange = (w, wantHidden) => !!w && (wantHidden ? !w.__xbHide : !!w.__xbHide);

    /** 官方 image_upload 的 upload 按钮 / $$canvas-image-preview 面板是后加的、可能被重建，按周期兜住 */
    const enforceOfficial = () => {
        const create = isCreateMode();
        const upload = findWidget(node, WIDGET_UPLOAD);
        if (needChange(upload, create)) setWidgetHidden(node, upload, create);
        const official = findWidget(node, WIDGET_OFFICIAL_PREVIEW);
        if (needChange(official, true)) setWidgetHidden(node, official, true);
    };

    /* ── 画幅比例 + 宽高：32 步长联动 ─────────────────────────── */
    node._xbSbSyncing = false;
    const snapWidget = (w, value) => {
        if (!w) return;
        const next = snap(value);
        if (Number(w.value) !== next) setWidgetValue(w, next);
    };
    const syncFromWidth = () => {
        if (node._xbSbSyncing) return;
        const ratio = RATIO_MAP[String(getVal(node, "aspect_ratio"))];
        node._xbSbSyncing = true;
        snapWidget(wW, getVal(node, "width"));
        if (ratio) {
            const w = snap(getVal(node, "width"));
            snapWidget(wH, w / ratio);
        }
        node._xbSbSyncing = false;
        refreshPanel();
    };
    const syncFromHeight = () => {
        if (node._xbSbSyncing) return;
        const ratio = RATIO_MAP[String(getVal(node, "aspect_ratio"))];
        node._xbSbSyncing = true;
        snapWidget(wH, getVal(node, "height"));
        if (ratio) {
            const h = snap(getVal(node, "height"));
            snapWidget(wW, h * ratio);
        }
        node._xbSbSyncing = false;
        refreshPanel();
    };

    const chain = (w, handler) => {
        if (!w) return;
        const original = w.callback;
        w.callback = function (value, ...rest) {
            if (original) original.apply(this, [value, ...rest]);
            handler(value);
        };
    };

    chain(wAR, () => { syncFromWidth(); });
    chain(wW, () => syncFromWidth());
    chain(wH, () => syncFromHeight());
    chain(wMode, () => applyMode());
    if (wColor) chain(wColor, () => refreshPanel());

    // 换了源图 → 只丢掉**编辑模式**的画板存档（它贴在源图上）；创作模式的画板跟源图无关，保留
    // ⚠️ 两道保险：读工作流期间（__xbSbLoading）不响应；新旧值相同也不响应
    if (wImage) {
        let lastImage = String(getVal(node, "image") ?? "");
        node.__xbSbRefreshLastImage = () => { lastImage = String(getVal(node, "image") ?? ""); };
        const original = wImage.callback;
        wImage.callback = function (value, ...rest) {
            if (original) original.apply(this, [value, ...rest]);
            const next = String(value ?? "");
            const changed = next !== lastImage;
            lastImage = next;
            if (changed && !node.__xbSbLoading && wPaint && String(wPaint.value || "")) {
                setWidgetValue(wPaint, "");
            }
            refreshPanel();
        };
    }

    node.__xbSbSync = applyMode;
    node.__xbSbEnforce = enforceOfficial;

    /* ── 老工作流迁移：内嵌 base64 画板 → 文件 ────────────────────
       以前版本把画板以 dataURL 存在部件里，一幅 1024² 就有 1.7MB，工作流 JSON 涨到几 MB，
       草稿写不进 localStorage → 刷新后工作流失踪。这里载入时一次性搬到 input/xb_shenbi/，
       把部件值换成文件名，工作流立即瘦回去。迁移失败就保留原值，绝不弄丢用户的画。 */
    const migrateLegacy = async () => {
        let changed = false;
        for (const [widget, tag] of [[wPaint, "edit"], [wCreate, "create"]]) {
            if (!widget) continue;
            const raw = String(widget.value || "");
            if (!raw.startsWith("data:image/")) continue;
            try {
                const blob = await canvasBlobOf(raw);
                if (!blob) continue;
                const key = await uploadPainting(blob, `xb_shenbi_${node.id ?? 0}_${tag}.png`);
                setWidgetValue(widget, key);
                changed = true;
            } catch (err) {
                console.warn("[XB-BOX 神笔] 画板搬迁失败（保留内嵌存档）：", err);
            }
        }
        if (changed) {
            paintStamp = Date.now();
            refreshPanel();
            notify("已把内嵌的画板搬迁为文件存档，工作流体积恢复正常", "info");
        }
    };
    node.__xbSbMigrate = migrateLegacy;
    setTimeout(migrateLegacy, 800);

    /* ── 周期兜底：官方部件后到 / 被重建时保持一致 ────────────── */
    let lastSig = "";
    let tickCount = 0;
    const tick = () => {
        if (node.__xbSbRemoved || !node.graph) return;
        enforceOfficial();
        const sig = [getVal(node, "mode"), getVal(node, "image") || "", getVal(node, "canvas_color"),
            getVal(node, "width"), getVal(node, "height"),
            getVal(node, "painted_data") ? "1" : "0", getVal(node, "created_data") ? "1" : "0"].join("|");
        if (sig !== lastSig) {
            lastSig = sig;
            applyMode();
        }
        // 刚建/刚载入的头两秒跑密一点，避免官方预览面板有一瞬间露出来
        tickCount += 1;
        node.__xbSbTimer = setTimeout(tick, tickCount < 20 ? 120 : TICK_MS);
    };

    const onRemoved = node.onRemoved;
    node.onRemoved = function () {
        node.__xbSbRemoved = true;
        if (node.__xbSbTimer) { clearTimeout(node.__xbSbTimer); node.__xbSbTimer = null; }
        if (onRemoved) onRemoved.apply(this, arguments);
    };

    applyMode();
    enforceOfficial();
    node.__xbSbTimer = setTimeout(tick, TICK_MS);

    // 新建节点时给显示窗一个舒服的初始高度（读工作流载入的节点保留存档尺寸）
    setTimeout(() => {
        if (node.__xbSbRemoved || node.__xbSbConfigured) return;
        try {
            node.setSize([node.size[0], Math.round(node.size[1]) + PANEL_EXTRA]);
            refreshWidgets(node);
            node.setDirtyCanvas?.(true, true);
        } catch (_) { /* ignore */ }
    }, 180);
}
app.registerExtension({
    name: "XB_ToolBox.ShenBi",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData?.name !== NODE_TYPE) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            try { setupNode(this); } catch (err) { console.error("[XB-BOX 神笔] 初始化失败：", err); }
            return result;
        };

        // 官方 image_upload 的 upload 按钮 / $$canvas-image-preview 面板是「后加」的，
        // 这里挂住 addWidget，部件一落地就按模式接管，避免那一瞬间的重复窗口（刷新时闪一下）
        for (const method of ["addWidget", "addCustomWidget"]) {
            const original = nodeType.prototype[method];
            if (typeof original !== "function") continue;
            nodeType.prototype[method] = function () {
                const added = original.apply(this, arguments);
                try { this.__xbSbEnforce?.(); } catch (_) { /* ignore */ }
                return added;
            };
        }

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const result = onConfigure?.apply(this, arguments);
            const self = this;
            // 读工作流期间前端可能回放一次 widget 回调，这里先立旗再同步，避免误清画板存档
            self.__xbSbLoading = true;
            self.__xbSbConfigured = true;
            setTimeout(() => {
                try { self.__xbSbRefreshLastImage?.(); } catch (_) { /* ignore */ }
                try { self.__xbSbSync?.(); } catch (_) { /* ignore */ }
                self.__xbSbLoading = false;
            }, 0);
            return result;
        };
    },
});
