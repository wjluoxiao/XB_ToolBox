import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import {
    GRAPH_POINTS, HISTORY_TICK_MS,
    history, graphHover, graphState,
    pushHistory, pushExecEvent, historyGet, smoothGpuUtil,
    loadHistory, saveHistory, clearHistoryStorage,
    loadGraphSavedState, resetHistoryState,
    drawGraph, buildGraphSubmenu, initGraph,
} from "./xb_memory_viz_graph.js";

let pollInterval = 500;
const FADE_TICKS = 6;

const execState = { running: false, node: null, progress: null };
let peakVramUsed = 0;
let modelCollapsed = {};
let colorModelBars = false;
let colorModelStroke = true;
let colorModelName = true;
let showLegends = true;
let showRamInMini = true;
let showVramInMini = true;
let showGpuInMini = true;
let showCpuInMini = true;
let showPagefileInMini = false;
let showDiskInMini = false;
const DISK_PEAK_FLOOR = 50 * 1024 * 1024;  // 50 MB/s — small enough idle activity is visible
const DISK_PEAK_HALFLIFE = 30;             // seconds — peak decays back toward floor when quiet
const diskState = {
    prevRead: null, prevWrite: null, prevTime: 0,
    peakRead: DISK_PEAK_FLOOR, peakWrite: DISK_PEAK_FLOOR,
};
let showFaultsInMini = false;
const FAULT_PEAK_FLOOR = 50;   // faults/s — keeps light activity visible
const FAULT_PEAK_HALFLIFE = 30;
const faultState = { prev: null, prevTime: 0, peak: FAULT_PEAK_FLOOR };
// Free-disk-space monitor — array of selected mountpoints (e.g. ["C:\\","D:\\"]).
// allDisksCache holds the most recent full enumeration so the tooltip can list
// every fixed drive even when only some are pinned to the bar.
let selectedDisks = [];
let allDisksCache = [];
let wantDisksList = false;  // one-shot — set when settings menu wants a fresh drive list
let _rebuildDriveMenu = null;  // assigned by createPanel; called from renderData when allDisksCache refreshes
let showHwNames = true;
let showTitle = true;
let showExecBtn = false;  // optional play / cancel-running button in the header
let miniShowNumbers = true;
let miniShowUnits = true;
let miniShowType = true;
let miniShowGpuTemp = true;
let miniShowGpuPower = true;
let miniShowSeparators = true;
let graphHeight = 80;
let currentTheme = "default";
let fontSize = 12;  // 面板基础字号 (px)
let lang = "zh";    // 界面语言: "zh" | "en"

// ── 中英文翻译映射表 ──
const L = {
    zh: {
        title: "硬件监控", titleAimdo: "硬件监控 (aimdo)",
        unload: "卸载 ▾", unloadTitle: "卸载模型 / 释放缓存 (点击查看选项)",
        popout: "弹出到画中画窗口", collapse: "折叠 / 展开面板",
        cancelRun: "取消正在运行的工作流", runWorkflow: "运行工作流",
        dragMove: "拖拽移动 (或拖到顶部停靠)", dragResize: "拖拽调整大小",
        dragResizeGraph: "拖拽调整图表高度",
        ram: "内存", vram: "显存", pagefile: "页面文件", faults: "硬缺页",
        disk: "磁盘", diskSpace: "磁盘空间",
        noGpu: "不可用 (GPU未检测到)", fetchError: "数据获取失败",
        peak: "峰值", cache: "缓存", running: "运行中", idle: "空闲",
        noModels: "暂无已加载模型", clickCollapse: "点击折叠/展开",
        unloadModel: "卸载此模型", pinned: "固定", loaded: "已加载",
        unloaded: "未加载", ramLabel: "内存", static_: "静态",
        pinnedRAM: "固定内存", loadedRAM: "已加载内存", vramLabel: "显存",
        ramTooltip: "内存", wm: "水位", wmTitle: "重置水位线",
        na: "无数据", live: "实时",
        models: "模型", torch: "PyTorch", other: "其他", python: "Python",
        total: "总量", gpuPct: "GPU利用率",
        pageVRAM: "页显存", pageUnloaded: "页未加载",
        vramColor: "显存颜色", totalColor: "总量颜色", smoothness: "平滑度",
        reset: "重置",
        graphArea: "面积图 (堆叠)", graphBars: "柱状图", graphTicker: "K线图", graphDots: "点阵 (渐变)",
        menuScale: "缩放", menuFontSize: "字号", menuPoll: "轮询间隔",
        menuDisplay: "显示", menuMini: "迷你视图", menuGraph: "图表",
        menuTheme: "主题", menuDockWidth: "停靠宽度", menuLang: "语言",
        dockSectionW: "区域宽度", dockLeft: "停靠左侧", dockRight: "停靠右侧",
        undock: "取消停靠 (浮动)", dockTop: "停靠到顶栏",
        resetHistory: "重置历史", resetHistoryTitle: "重置峰值显存标记并清除历史图表",
        toggleColorBars: "模型条着色", toggleColorStroke: "模型边框着色",
        toggleColorName: "模型名着色", toggleShowLegends: "显示图例",
        toggleShowTitle: "显示标题", toggleExecBtn: "执行按钮",
        toggleRam: "内存", toggleVram: "显存", togglePagefile: "页面文件",
        toggleIO: "I/O", toggleFaults: "页面抖动 (硬缺页)",
        toggleUtil: "利用率", toggleNames: "设备名称",
        toggleNumbers: "数值显示", toggleUnits: "单位显示",
        toggleType: "类型标签", toggleTemp: "温度", togglePower: "功耗",
        toggleSeparators: "分隔线", toggleDisk: "磁盘", drives: "磁盘驱动器",
        detecting: "检测中…",
        unloadAimdo: "aimdo (立即卸载)", unloadAimdoTitle: "立即卸载 aimdo 管理的模型",
        unloadModels: "模型", unloadModelsTitle: "ComfyUI /free — 下次队列时卸载模型",
        unloadCache: "模型 + 节点缓存", unloadCacheTitle: "ComfyUI /free — 卸载模型并清除节点输出缓存",
        diskUnavailable: "不可用", diskUsed: "已用", diskFree: "剩余",
        gpuPowerTitle: "GPU功耗 / 上限", gpuLineTitle: "点击切换图表上的GPU曲线",
        langZh: "中文", langEn: "English",
    },
    en: {
        title: "Memory", titleAimdo: "Memory (aimdo)",
        unload: "unload ▾", unloadTitle: "Unload models / free cache (click for options)",
        popout: "Pop out into a Picture-in-Picture window", collapse: "Collapse / expand panel",
        cancelRun: "Cancel running workflow", runWorkflow: "Run workflow",
        dragMove: "Drag to move (or to dock at the top)", dragResize: "Drag to resize",
        dragResizeGraph: "Drag to resize graph",
        ram: "RAM", vram: "VRAM", pagefile: "Pagefile", faults: "Faults",
        disk: "Disk", diskSpace: "Disk space",
        noGpu: "Not available (GPU not detected)", fetchError: "Error fetching data",
        peak: "peak", cache: "cache", running: "running", idle: "idle",
        noModels: "No models loaded", clickCollapse: "Click to collapse/expand",
        unloadModel: "Unload this model", pinned: "pinned", loaded: "loaded",
        unloaded: "unloaded", ramLabel: "RAM", static_: "static",
        pinnedRAM: "pinned RAM", loadedRAM: "loaded RAM", vramLabel: "VRAM",
        ramTooltip: "RAM", wm: "wm", wmTitle: "reset watermark",
        na: "N/A", live: "live",
        models: "models", torch: "torch", other: "other", python: "python",
        total: "total", gpuPct: "GPU %",
        pageVRAM: "VRAM", pageUnloaded: "unloaded",
        vramColor: "VRAM color", totalColor: "Total color", smoothness: "Total smoothness",
        reset: "reset",
        graphArea: "Area (stacked)", graphBars: "Bars", graphTicker: "Ticker", graphDots: "Dots (fade)",
        menuScale: "Scale", menuFontSize: "Font size", menuPoll: "Polling interval",
        menuDisplay: "Display", menuMini: "Mini view", menuGraph: "Graph",
        menuTheme: "Theme", menuDockWidth: "Dock width", menuLang: "Language",
        dockSectionW: "Section width", dockLeft: "Dock left", dockRight: "Dock right",
        undock: "Undock to floating", dockTop: "Dock to top",
        resetHistory: "Reset history", resetHistoryTitle: "Reset peak VRAM marker and clear history graph",
        toggleColorBars: "Color model bars", toggleColorStroke: "Color model stroke",
        toggleColorName: "Color model name", toggleShowLegends: "Show legends",
        toggleShowTitle: "Show title", toggleExecBtn: "Execute button",
        toggleRam: "RAM", toggleVram: "VRAM", togglePagefile: "Pagefile",
        toggleIO: "I/O", toggleFaults: "Thrashing (hard faults)",
        toggleUtil: "util", toggleNames: "Device names",
        toggleNumbers: "Numbers", toggleUnits: "Units",
        toggleType: "Type labels", toggleTemp: "temp", togglePower: "power",
        toggleSeparators: "Separators", toggleDisk: "Disk", drives: "Drives",
        detecting: "detecting…",
        unloadAimdo: "aimdo (immediate)", unloadAimdoTitle: "Immediately unload aimdo-managed models",
        unloadModels: "models", unloadModelsTitle: "ComfyUI /free — unload models on next queue tick",
        unloadCache: "models + node cache", unloadCacheTitle: "ComfyUI /free — unload models and clear node output cache",
        diskUnavailable: "unavailable", diskUsed: "used", diskFree: "free",
        gpuPowerTitle: "GPU power draw / cap", gpuLineTitle: "Click to toggle GPU line on graph",
        langZh: "中文", langEn: "English",
    }
};

function _t(key) { return (L[lang] && L[lang][key]) || key; }

const STORAGE_KEY = "aimdo_viz_state";
function loadState() {
    try { return JSON.parse(localStorage.getItem(STORAGE_KEY)) || {}; }
    catch { return {}; }
}
function saveState(patch) {
    const s = loadState();
    Object.assign(s, patch);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(s));
}

// Themes live in aimdo_viz.css as `[data-aimdo-theme="<name>"]` blocks layered
// over a :root default. Selecting a theme is just setting that attribute on
// <html> — CSS does the rest. JS keeps a parallel `C` palette object only
// because <canvas> can't read CSS variables; canvas rendering reads hex/rgb
// strings from C, which we refresh from computed CSS on each theme switch.
const THEME_NAMES = ["default", "comfy", "light", "sepia", "fallout", "pink", "lucifer"];

// Keys whose values are color strings the canvas can read directly. fadeOutFrom /
// fadeOutTo are stored as comma-separated RGB triplets in CSS and parsed into
// [r,g,b] arrays for the canvas fade animation.
const PALETTE_KEYS = Object.freeze([
    "vram","torch","pinned","loadedRam","unloaded","torchCache","python","other",
    "text","textDim","running","bg","rowBg","headerBg","border","btn","btnText",
    "graphBg","gridLine","totalLine","gpuUtil","gpuUtilHi","capLine","barBg",
]);
const MODEL_TYPE_KEYS = Object.freeze([
    "model","vae","clip","clip_vision","controlnet","style_model","gligen","upscale_model",
]);
const RGB_KEYS = Object.freeze(["fadeOutFrom", "fadeOutTo"]);

// Filled by applyPalette() from computed CSS once the stylesheet is loaded.
// Canvas drawing reads from here because <canvas> can't read CSS variables;
// the DOM reads var(--aimdo-X) directly from CSS and never touches C.
const C = {};
const MODEL_TYPE_COLOR = {};

// Load the stylesheet and expose the load as a promise. Init code awaits this
// before touching C so the canvas never draws against an unpopulated palette.
const cssLoaded = new Promise((resolve) => {
    const id = "aimdo-viz-stylesheet";
    if (document.getElementById(id)) { resolve(); return; }
    const link = document.createElement("link");
    link.id = id;
    link.rel = "stylesheet";
    link.href = new URL("xb_memory_viz.css", import.meta.url).href;
    link.addEventListener("load", () => resolve(), { once: true });
    link.addEventListener("error", () => resolve(), { once: true });  // proceed even on 404
    document.head.appendChild(link);
});

// The panel uses a custom element, hook disconnectedCallback to detect whena something removes it from the DOM
if (!customElements.get("aimdo-viz-panel")) {
    customElements.define("aimdo-viz-panel", class extends HTMLElement {
        disconnectedCallback() { if (this._onDisconnect) this._onDisconnect(); }
    });
}

function parseRgbTriplet(s) {
    const parts = s.split(",").map(x => parseInt(x.trim(), 10));
    if (parts.length === 3 && parts.every(Number.isFinite)) return parts;
    return null;
}

// Set the theme on <html> so the matching CSS block takes effect, then
// refresh C from computed CSS variables for canvas use.
function applyPalette(name) {
    const root = document.documentElement;
    if (name && name !== "default" && THEME_NAMES.includes(name)) {
        root.dataset.aimdoTheme = name;
    } else {
        delete root.dataset.aimdoTheme;
    }
    const cs = getComputedStyle(root);
    for (const k of PALETTE_KEYS) {
        const v = cs.getPropertyValue(`--aimdo-${k}`).trim();
        if (v) C[k] = v;
    }
    for (const k of MODEL_TYPE_KEYS) {
        const v = cs.getPropertyValue(`--aimdo-type-${k}`).trim();
        if (v) MODEL_TYPE_COLOR[k] = v;
    }
    for (const k of RGB_KEYS) {
        const v = cs.getPropertyValue(`--aimdo-${k}`).trim();
        const rgb = v && parseRgbTriplet(v);
        if (rgb) C[k] = rgb;
    }
}

// The "comfy" theme maps --aimdo-* to ComfyUI's --comfy-*/--color-* tokens via
// var(). Those tokens themselves change when ComfyUI toggles its .dark-theme
// class on <html> or <body>. DOM elements track that automatically through
// the cascade, but the cached `C` palette used by the canvas does not — so we
// re-run applyPalette whenever the host's theme class flips.
function watchHostThemeFlip() {
    const reapply = () => { if (currentTheme === "comfy") applyPalette("comfy"); };
    const opts = { attributes: true, attributeFilter: ["class"] };
    new MutationObserver(reapply).observe(document.documentElement, opts);
    if (document.body) new MutationObserver(reapply).observe(document.body, opts);
}

function hexToRgb(hex) {
    const h = hex.replace("#", "");
    return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}
function hexToRgba(hex, alpha) {
    const [r, g, b] = hexToRgb(hex);
    return `rgba(${r},${g},${b},${alpha})`;
}
// blend [r,g,b] toward white. Used so fade-in stays in the type's hue family.
function lightenRgb([r, g, b], amount) {
    return [
        Math.round(r + (255 - r) * amount),
        Math.round(g + (255 - g) * amount),
        Math.round(b + (255 - b) * amount),
    ];
}

initGraph({ C, hexToRgb, hexToRgba, saveState, _t });


function escHtml(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function gpuUtilColor(pct) {
    if (pct < 10) return C.textDim;
    if (pct < 80) return C.gpuUtil;
    return C.gpuUtilHi;
}

function gpuTempColor(c) {
    if (c < 60) return C.textDim;
    if (c < 80) return C.gpuUtil;
    return C.gpuUtilHi;
}

function gpuPowerColor(draw_mW, limit_mW) {
    if (draw_mW == null) return C.textDim;
    if (limit_mW == null || limit_mW <= 0) return C.gpuUtil;
    return gpuUtilColor(draw_mW / limit_mW * 100);
}

function formatPower(draw_mW, limit_mW, withUnit = true) {
    if (draw_mW == null) return null;
    const draw = Math.round(draw_mW / 1000);
    const u = withUnit ? "W" : "";
    if (limit_mW == null || limit_mW <= 0) return `${draw}${u}`;
    return `${draw}/${Math.round(limit_mW / 1000)}${u}`;
}

function formatClock(ms) {
    const d = new Date(ms);
    const pad = n => n.toString().padStart(2, "0");
    return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function shortenGpuName(name) {
    return name.replace(/^NVIDIA\s+/i, "").replace(/^GeForce\s+/i, "").replace(/\s+Laptop GPU$/i, "");
}

function shortenCpuName(name) {
    return name
        .replace(/\(R\)|\(TM\)|\(tm\)/gi, "")
        .replace(/\s+CPU\s+@.*$/i, "")           // "i9-12900K CPU @ 3.20GHz" → "i9-12900K"
        .replace(/\s+\d+-Core\s+Processor$/i, "")// "Ryzen 9 7950X 16-Core Processor" → "Ryzen 9 7950X"
        .replace(/^Intel\s+Core\s+/i, "")
        .replace(/^AMD\s+/i, "")
        .replace(/\s+/g, " ")
        .trim();
}

function formatBytes(bytes, withUnit = true) {
    if (bytes == null) return "?";
    // non-breaking space ( ) so "8.4 GB" never line-wraps between value and unit.
    if (bytes >= 1024 ** 3) return (bytes / 1024 ** 3).toFixed(1) + (withUnit ? " GB" : "");
    if (bytes >= 1024 ** 2) return (bytes / 1024 ** 2).toFixed(0) + (withUnit ? " MB" : "");
    return (bytes / 1024).toFixed(0) + (withUnit ? " KB" : "");
}


// "C:\" → "C:", "/" stays "/". Avoids stripping a bare root slash on POSIX.
function shortMountpoint(mp) {
    if (!mp) return "";
    if (mp.length > 1) return mp.replace(/[\\\/]+$/, "");
    return mp;
}

function buildDiskTooltip(disks) {
    if (!disks || !disks.length) return "";
    return disks.map(d => {
        const mp = shortMountpoint(d.mountpoint);
        const label = d.label ? ` "${d.label}"` : "";
        if (d.total == null || d.free == null) return `${mp}${label}: ${_t("diskUnavailable")}`;
        const used = d.total - d.free;
        const pct = Math.round(used / d.total * 100);
        return `${mp}${label}: ${formatBytes(used)} / ${formatBytes(d.total)} (${_t("diskUsed")}${pct}%, ${_t("diskFree")}${formatBytes(d.free)})`;
    }).join("\n");
}

// per-model residency diff state
const modelState = {};

function diffResidency(key, residency) {
    let st = modelState[key];
    if (!st || st.prev.length !== residency.length) {
        st = { prev: new Uint8Array(residency), changeAge: new Uint8Array(residency.length) };
        modelState[key] = st;
        return st;
    }

    for (let i = 0; i < residency.length; i++) {
        if (residency[i] !== st.prev[i]) {
            st.changeAge[i] = FADE_TICKS;
        } else if (st.changeAge[i] > 0) {
            st.changeAge[i]--;
        }
        st.prev[i] = residency[i];
    }
    return st;
}

// draw page grid to canvas — much faster than 700 DOM divs.
// vramColor (hex) tints static cells and the fade-in landing color per model.
// Normal mode keeps the original yellow→vram "warm-up" pulse; per-model coloring
// uses a lightened type color so the hue stays in the model's family.
function drawPageGrid(ctx, cssW, residency, changeAge, panelScale, vramColor) {
    const vramHex = vramColor || C.vram;
    const vramRgb = hexToRgb(vramHex);
    const fadeInFromRgb = vramColor ? lightenRgb(vramRgb, 0.55) : [255, 220, 0];
    const cellSize = 6;
    const gap = 1;
    const step = cellSize + gap;
    const cols = Math.max(1, Math.floor((cssW + gap) / step));
    const rows = Math.ceil(residency.length / cols);
    const cssH = rows * step;

    const dpr = window.devicePixelRatio || 1;
    const totalScale = panelScale * dpr;
    const canvas = ctx.canvas;
    const backingW = Math.max(1, Math.round(cssW * totalScale));
    const backingH = Math.max(1, Math.round((cssH || 1) * totalScale));

    // skip draw when nothing's animating and inputs match the previous call.
    let anyAnimating = false;
    for (let i = 0; i < changeAge.length; i++) if (changeAge[i] > 0) { anyAnimating = true; break; }
    const sig = `${vramHex}|var(--aimdo-unloaded)|${backingW}x${backingH}|${residency.length}`;
    if (!anyAnimating && canvas._lastSig === sig) return;
    canvas._lastSig = sig;

    if (canvas.width !== backingW) canvas.width = backingW;
    if (canvas.height !== backingH) canvas.height = backingH;
    canvas.style.height = (cssH || 1) + "px";
    ctx.setTransform(totalScale, 0, 0, totalScale, 0, 0);
    ctx.clearRect(0, 0, cssW, cssH || 1);

    // batch: draw all static vram cells, then all static unloaded, then animated individually
    const animated = [];

    ctx.fillStyle = vramColor || C.vram;
    for (let i = 0; i < residency.length; i++) {
        if (changeAge[i] > 0) { animated.push(i); continue; }
        if (!(residency[i] & 1)) continue;
        ctx.fillRect((i % cols) * step, Math.floor(i / cols) * step, cellSize, cellSize);
    }

    ctx.fillStyle = C.unloaded;
    for (let i = 0; i < residency.length; i++) {
        if (changeAge[i] > 0 || (residency[i] & 1)) continue;
        ctx.fillRect((i % cols) * step, Math.floor(i / cols) * step, cellSize, cellSize);
    }

    // fade-in: lightened type color → type color. fade-out: red → gray (universal "removed").
    for (const i of animated) {
        const resident = residency[i] & 1;
        const t = changeAge[i] / FADE_TICKS;
        const [fr, fg, fb] = resident ? fadeInFromRgb : C.fadeOutFrom;
        const [tr, tg, tb] = resident ? vramRgb : C.fadeOutTo;
        ctx.fillStyle = `rgb(${Math.round(fr * t + tr * (1 - t))},${Math.round(fg * t + tg * (1 - t))},${Math.round(fb * t + tb * (1 - t))})`;
        ctx.fillRect((i % cols) * step, Math.floor(i / cols) * step, cellSize, cellSize);
    }
}

function createPanel() {
    const saved = loadState();
    if (saved.pollInterval) pollInterval = saved.pollInterval;
    loadGraphSavedState(saved);
    if (typeof saved.colorModelBars === "boolean") colorModelBars = saved.colorModelBars;
    if (typeof saved.colorModelStroke === "boolean") colorModelStroke = saved.colorModelStroke;
    if (typeof saved.colorModelName === "boolean") colorModelName = saved.colorModelName;
    if (typeof saved.showLegends === "boolean") showLegends = saved.showLegends;
    if (typeof saved.showRamInMini === "boolean") showRamInMini = saved.showRamInMini;
    if (typeof saved.showVramInMini === "boolean") showVramInMini = saved.showVramInMini;
    if (typeof saved.showGpuInMini === "boolean") showGpuInMini = saved.showGpuInMini;
    if (typeof saved.showCpuInMini === "boolean") showCpuInMini = saved.showCpuInMini;
    if (typeof saved.showPagefileInMini === "boolean") showPagefileInMini = saved.showPagefileInMini;
    if (typeof saved.showDiskInMini === "boolean") showDiskInMini = saved.showDiskInMini;
    if (typeof saved.showFaultsInMini === "boolean") showFaultsInMini = saved.showFaultsInMini;
    if (Array.isArray(saved.selectedDisks)) selectedDisks = saved.selectedDisks.slice();
    if (typeof saved.showHwNames === "boolean") showHwNames = saved.showHwNames;
    if (typeof saved.showTitle === "boolean") showTitle = saved.showTitle;
    if (typeof saved.showExecBtn === "boolean") showExecBtn = saved.showExecBtn;
    if (typeof saved.miniShowNumbers === "boolean") miniShowNumbers = saved.miniShowNumbers;
    if (typeof saved.miniShowUnits === "boolean") miniShowUnits = saved.miniShowUnits;
    if (typeof saved.miniShowType === "boolean") miniShowType = saved.miniShowType;
    if (typeof saved.miniShowGpuTemp === "boolean") miniShowGpuTemp = saved.miniShowGpuTemp;
    if (typeof saved.miniShowGpuPower === "boolean") miniShowGpuPower = saved.miniShowGpuPower;
    if (typeof saved.miniShowSeparators === "boolean") miniShowSeparators = saved.miniShowSeparators;
    if (typeof saved.graphHeight === "number" && saved.graphHeight > 0) graphHeight = saved.graphHeight;
    if (typeof saved.theme === "string" && THEME_NAMES.includes(saved.theme)) {
        currentTheme = saved.theme;
    }
    if (typeof saved.fontSize === "number" && saved.fontSize >= 8 && saved.fontSize <= 24) {
        fontSize = saved.fontSize;
    }
    if (typeof saved.lang === "string" && (saved.lang === "zh" || saved.lang === "en")) {
        lang = saved.lang;
    }
    // always run — primes C from computed CSS so the canvas matches the stylesheet
    applyPalette(currentTheme);
    watchHostThemeFlip();
    if (saved.modelCollapsed && typeof saved.modelCollapsed === "object") modelCollapsed = saved.modelCollapsed;
    let panelScale = typeof saved.scale === "number" ? saved.scale : 1;

    // structural styles live in aimdo_viz.css; CSS variables on :root carry the palette.
    // theme switches go through applyPalette → setCssVars; no per-element repaint here.
    const panel = document.createElement("aimdo-viz-panel");
    panel.id = "aimdo-viz-panel";
    panel.style.zoom = panelScale;
    panel.style.setProperty('--aimdo-font-size', fontSize + 'px');
    panel._scale = panelScale;
    if (saved.width != null) panel.style.width = Math.min(saved.width, window.innerWidth) / panelScale + "px";
    // explicit height only when expanded; collapsed shrinks to header.
    // separate height persistence per mode — expanding/collapsing loads the right one
    const initialHeight = saved.collapsed ? saved.heightCollapsed : saved.height;
    if (initialHeight != null) {
        panel.style.height = Math.min(initialHeight, window.innerHeight) / panelScale + "px";
    } else if (!saved.collapsed) {
        // 无保存高度时设置合理的默认高度，防止内容显示不全
        panel.style.height = Math.min(480, window.innerHeight * 0.5) / panelScale + "px";
    }

    // CSS sizes are pre-zoom (logical); divide visual targets by panelScale.
    // 50vh cap when auto-growing; relaxes to viewport when user sets explicit height.
    let pipWindow = null;  // set when the panel is moved into a PiP window
    const isPoppedOut = () => pipWindow && !pipWindow.closed;
    function applyConstraints() {
        if (isPoppedOut()) return;  // PiP fills its own window; main-page bounds don't apply
        const heightCapFrac = panel.style.height ? 1.0 : 0.5;
        panel.style.minWidth = (200 / panelScale) + "px";
        panel.style.maxWidth = (window.innerWidth / panelScale) + "px";
        panel.style.maxHeight = (window.innerHeight * heightCapFrac / panelScale) + "px";
    }
    applyConstraints();

    // .graph-canvas-panel shrinks when sidebars open; #graph-canvas-container doesn't
    function getCanvasEl() {
        return document.querySelector(".graph-canvas-panel")
            || document.getElementById("graph-canvas-container")
            || document.getElementById("graph-canvas")
            || (app && app.canvasEl)
            || null;
    }

    function getCanvasBounds() {
        const el = getCanvasEl();
        if (el) {
            const r = el.getBoundingClientRect();
            if (r.width > 0 && r.height > 0) return r;
        }
        return { left: 0, top: 0, right: window.innerWidth, bottom: window.innerHeight };
    }

    let rightOffset = saved.rightOffset != null ? saved.rightOffset : 10;
    let bottomOffset = saved.bottomOffset != null ? saved.bottomOffset : 10;

    // Topbar/tabs sit above the panel; leaf bars block only where their items actually sit.
    // Cache the layout so drag mousemoves don't trigger getBoundingClientRect on every leaf.
    let chromeCache = null;
    function refreshChromeCache() {
        const fullSels = [".comfyui-body-top", ".topbar-container", ".workflow-tabs-container", ".workflow-tabs"];
        let bottom = 0;
        for (const s of fullSels) {
            for (const el of document.querySelectorAll(s)) {
                const r = el.getBoundingClientRect();
                if (r.height > 0 && r.bottom > bottom) bottom = r.bottom;
            }
        }
        const containers = [];
        const leaves = [];
        for (const el of document.querySelectorAll(".actionbar-container")) {
            const r = el.getBoundingClientRect();
            if (r.height <= 0) continue;
            containers.push({ left: r.left, right: r.right, bottom: r.bottom });
            for (const node of el.querySelectorAll("*")) {
                if (node.children.length > 0) continue;
                const nr = node.getBoundingClientRect();
                if (nr.width <= 0 || nr.height <= 0) continue;
                leaves.push({ left: nr.left, right: nr.right, bottom: nr.bottom });
            }
        }
        const sideLeft = [];
        const sideRight = [];
        for (const el of document.querySelectorAll(".side-toolbar-container")) {
            const r = el.getBoundingClientRect();
            if (r.width <= 0) continue;
            const isLeft = r.left < 8;
            const isRight = window.innerWidth - r.right < 8;
            if (isLeft) sideLeft.push({ right: r.right, top: r.top, bottom: r.bottom });
            else if (isRight) sideRight.push({ left: r.left, top: r.top, bottom: r.bottom });
        }
        chromeCache = { fullBottom: bottom, containers, leaves, sideLeft, sideRight };
    }
    function invalidateChromeCache() { chromeCache = null; }
    // sidebars don't fire window.resize and may overlay (not shrink) the canvas, so the
    // canvas ResizeObserver alone can't catch them — drop the stale cache and re-clamp here.
    function onSideChromeChange() { invalidateChromeCache(); applyOffsets(); }
    window.addEventListener("resize", invalidateChromeCache);
    let chromeObserversAttached = false;
    function attachChromeObservers() {
        if (chromeObserversAttached) return;
        const ac = document.querySelector(".actionbar-container");
        const top = document.querySelector(".comfyui-body-top");
        if (!ac && !top) { requestAnimationFrame(attachChromeObservers); return; }
        chromeObserversAttached = true;
        const targets = [ac, top].filter(Boolean);
        for (const t of targets) {
            new MutationObserver(invalidateChromeCache).observe(t, { childList: true, subtree: true });
            if (typeof ResizeObserver !== "undefined") new ResizeObserver(invalidateChromeCache).observe(t);
        }
        // body-side wrappers are stable grid areas; the sidebar panel toggles inside them,
        // changing their width. Observe both so opening either sidebar re-clamps the panel.
        for (const sel of [".comfyui-body-left", ".comfyui-body-right"]) {
            const el = document.querySelector(sel);
            if (!el) continue;
            // childList only (no subtree) — catch the panel toggling in/out without firing
            // on the sidebar's own live content updates. Width changes covered by the resize obs.
            new MutationObserver(onSideChromeChange).observe(el, { childList: true });
            if (typeof ResizeObserver !== "undefined") new ResizeObserver(onSideChromeChange).observe(el);
        }
    }
    attachChromeObservers();

    function getTopChromeBottom(panelLeft, panelRight) {
        if (!chromeCache) refreshChromeCache();
        let bottom = chromeCache.fullBottom;
        if (panelLeft == null) {
            for (const c of chromeCache.containers) if (c.bottom > bottom) bottom = c.bottom;
            return bottom;
        }
        for (const nr of chromeCache.leaves) {
            if (nr.right <= panelLeft || nr.left >= panelRight) continue;
            if (nr.bottom > bottom) bottom = nr.bottom;
        }
        return bottom;
    }

    function getSideChromeBounds(panelTop, panelBottom) {
        if (!chromeCache) refreshChromeCache();
        let minLeft = 0;
        let maxRight = window.innerWidth;
        for (const r of chromeCache.sideLeft) {
            if (panelTop != null && (r.bottom <= panelTop || r.top >= panelBottom)) continue;
            if (r.right > minLeft) minLeft = r.right;
        }
        for (const r of chromeCache.sideRight) {
            if (panelTop != null && (r.bottom <= panelTop || r.top >= panelBottom)) continue;
            if (r.left < maxRight) maxRight = r.left;
        }
        return { minLeft, maxRight };
    }

    function clampOffsets(ro, bo) {
        const b = getCanvasBounds();
        const pr = panel.getBoundingClientRect();
        const w = pr.width, h = pr.height;
        const vw = window.innerWidth, vh = window.innerHeight;
        const panelRight = b.right - ro;
        const panelLeft = panelRight - w;
        const panelTop = b.bottom - bo - h;
        const panelBottom = b.bottom - bo;
        const minTop = getTopChromeBottom(panelLeft, panelRight);
        const { minLeft, maxRight } = getSideChromeBounds(panelTop, panelBottom);

        // when window's too short for both constraints, prefer the chrome
        // clamp over the viewport edge so we never overlap the topbar/sidebar.
        const boHi = b.bottom - h - minTop;
        const boLo = b.bottom - vh;
        const boClamped = boHi < boLo ? boHi : Math.max(boLo, Math.min(bo, boHi));

        // roLo combines viewport-right and right-chrome constraints (whichever is tighter).
        const roHi = b.right - w - minLeft;
        const roLo = Math.max(b.right - vw, b.right - maxRight);
        const roClamped = roHi < roLo ? roHi : Math.max(roLo, Math.min(ro, roHi));
        return { ro: roClamped, bo: boClamped, b, w, h };
    }

    // visual-only clamp; closure offsets stay as user intent so they survive temporary shrinks.
    // CSS zoom scales style.left/top along with size, so we divide by panelScale to land at
    // the intended viewport position rather than position × scale.
    function applyOffsets() {
        if (pipWindow && !pipWindow.closed) return;  // PiP owns layout while popped out
        if (isDocked) return;                        // docked panel lives in the actionbar flex flow
        const { ro, bo, b, w, h } = clampOffsets(rightOffset, bottomOffset);
        // while actively dragging, bypass clamping so the user can fly over the topbar
        // to reach the dock drop zone. mouseup re-clamps before persisting.
        const useRo = dragging ? rightOffset : ro;
        const useBo = dragging ? bottomOffset : bo;
        const tx = (b.right - w - useRo) / panelScale;
        const ty = (b.bottom - h - useBo) / panelScale;
        panel.style.left = "0";
        panel.style.top = "0";
        panel.style.right = "auto";
        panel.style.bottom = "auto";
        // translate3d keeps positioning on the compositor — no layout per drag move.
        panel.style.transform = `translate3d(${tx}px, ${ty}px, 0)`;
    }
    window.addEventListener("resize", () => { applyConstraints(); applyOffsets(); positionDockedBody(); });

    // --- Docking to ComfyUI's top actionbar ---
    // Same pattern as ComfyActionbar.vue: during a drag we expose a drop zone inside
    // .actionbar-container; mouseup-while-hovering reparents the panel into that container
    // and switches it to a flat horizontal mini-bar layout via the .aimdo-docked class.
    let isDocked = !!saved.docked;
    let dockSide = saved.dockSide === "left" ? "left" : "right";
    let dockExpanded = false;     // session-only: body shown as overlay below the docked mini-bar
    let autoDockPending = false;  // true while the post-load redock poll is running
    let dockSectionWidth = (typeof saved.dockSectionWidth === "number" && saved.dockSectionWidth > 40)
        ? saved.dockSectionWidth : 110;
    let savedPanelCss = null;     // snapshot before docking so undock can restore exact styles
    let preDockCollapsed = null;
    let dropZoneLeft = null;      // present only while a drag is in progress
    let dropZoneRight = null;
    let dropZoneHoverSide = null; // "left" | "right" | null
    function applyDockSectionWidth() {
        panel.style.setProperty("--aimdo-dock-section-w", dockSectionWidth + "px");
        positionDockedBody();
    }
    applyDockSectionWidth();

    // overlay anchored under the docked panel; right-docked panels extend the overlay leftward
    // so it doesn't get pushed off-screen when the panel sits at the topbar's right edge.
    function positionDockedBody() {
        if (!isDocked || !dockExpanded) return;
        const r = panel.getBoundingClientRect();
        const ac = getActionbarContainer();
        const acr = ac ? ac.getBoundingClientRect() : null;
        const overlayW = 420;
        const anchor = dockSide === "right"
            ? (acr ? acr.right - overlayW : r.right - overlayW)
            : (acr ? acr.left : r.left);
        const left = Math.max(4, Math.min(window.innerWidth - overlayW - 4, anchor));
        body.style.top = (r.bottom + 12) + "px";
        body.style.left = left + "px";
    }

    function getActionbarContainer() {
        return document.querySelector(".actionbar-container");
    }

    // two zones — one before the existing actionbar items, one after — let the user choose
    // which side to dock on via CSS order on the panel.
    function makeDropZone(side) {
        const dz = document.createElement("div");
        dz.className = "aimdo-dropzone aimdo-dropzone-" + side;
        dz.textContent = side === "left" ? _t("dockLeft") : _t("dockRight");
        dz.addEventListener("mouseenter", () => {
            if (!dragging) return;
            dropZoneHoverSide = side;
            dz.classList.add("is-hover");
        });
        dz.addEventListener("mouseleave", () => {
            if (dropZoneHoverSide === side) dropZoneHoverSide = null;
            dz.classList.remove("is-hover");
        });
        return dz;
    }
    function ensureDropZone() {
        const ac = getActionbarContainer();
        if (!ac) return null;
        if (dropZoneLeft && dropZoneLeft.parentNode === ac) return ac;
        if (dropZoneLeft) dropZoneLeft.remove();
        if (dropZoneRight) dropZoneRight.remove();
        dropZoneLeft = makeDropZone("left");
        dropZoneRight = makeDropZone("right");
        ac.appendChild(dropZoneLeft);
        ac.appendChild(dropZoneRight);
        return ac;
    }
    function clearDropZone() {
        dropZoneHoverSide = null;
        if (dropZoneLeft) { dropZoneLeft.remove(); dropZoneLeft = null; }
        if (dropZoneRight) { dropZoneRight.remove(); dropZoneRight = null; }
    }

    function dock(side) {
        const ac = getActionbarContainer();
        if (!ac) return false;
        if (side === "left" || side === "right") dockSide = side;
        if (isDocked) {
            panel.style.order = dockSide === "left" ? "-1" : "1";
            if (panel.parentNode !== ac) ac.appendChild(panel);
            saveState({ dockSide });
            return true;
        }
        preDockCollapsed = collapsed;
        if (!collapsed) {
            collapsed = true;
            body.style.display = "none";
            miniBar.style.display = "block";
            toggleBtn.textContent = "+";
        }
        dockExpanded = false;
        savedPanelCss = panel.style.cssText;
        panel.classList.add("aimdo-docked");
        panel.style.order = dockSide === "left" ? "-1" : "1";
        ac.appendChild(panel);
        isDocked = true;
        saveState({ docked: true, dockSide });
        return true;
    }

    function reconcileDocking() {
        if (!isDocked || panel.isConnected) return;
        const ac = getActionbarContainer();
        if (!ac) return;
        panel.style.order = dockSide === "left" ? "-1" : "1";
        ac.appendChild(panel);
    }
    // The panel is a custom element — its disconnectedCallback fires the instant Vue
    // (or anything else) removes it from the DOM.
    panel._onDisconnect = () => { if (isDocked) queueMicrotask(reconcileDocking); };

    function undock() {
        autoDockPending = false;  // explicit undock cancels any in-flight auto-redock poll
        if (!isDocked) return;
        dockExpanded = false;
        panel.classList.remove("aimdo-docked", "aimdo-docked-expanded");
        body.style.top = "";
        body.style.left = "";
        if (savedPanelCss != null) panel.style.cssText = savedPanelCss;
        savedPanelCss = null;
        document.body.appendChild(panel);
        isDocked = false;
        const restoreCollapsed = preDockCollapsed != null ? preDockCollapsed : false;
        preDockCollapsed = null;
        collapsed = restoreCollapsed;
        body.style.display = collapsed ? "none" : "flex";
        miniBar.style.display = collapsed ? "block" : "none";
        toggleBtn.textContent = collapsed ? "+" : "−";
        if (!collapsed) {
            const s = loadState();
            const h = s.height;
            panel.style.height = h != null ? (Math.min(h, window.innerHeight) / panelScale + "px") : "";
        }
        saveState({ collapsed, docked: false });
        applyConstraints();
        applyOffsets();
    }

    const header = document.createElement("div");
    header.className = "aimdo-header";
    // visible drag affordance matching ComfyUI's docked actionbar handle — six dots in a 2x3 grid
    const dragHandle = document.createElement("span");
    dragHandle.className = "aimdo-drag-handle";
    dragHandle.title = _t("dragMove");
    header.appendChild(dragHandle);
    const titleSpan = document.createElement("span");
    titleSpan.className = "aimdo-title";
    titleSpan.textContent = _t("title");
    header.appendChild(titleSpan);

    const miniBar = document.createElement("div");
    miniBar.className = "aimdo-mini-bar";
    miniBar.innerHTML = `<div class="mini-ram-section">
        <div class="aimdo-mini-row">
            <span class="mini-ram-label">${_t("ram")}</span><span class="mini-ram-usage"></span>
        </div>
        <div class="aimdo-mini-track mini-ram-bar">
            <div class="aimdo-seg aimdo-seg-pinned"></div>
            <div class="aimdo-seg aimdo-seg-loadedRam"></div>
            <div class="aimdo-seg aimdo-seg-python"></div>
            <div class="aimdo-seg aimdo-seg-other"></div>
        </div>
    </div>
    <div class="mini-vram-section">
        <div class="aimdo-mini-row">
            <span class="mini-vram-label">${_t("vram")}</span><span class="mini-vram-usage"></span>
        </div>
        <div class="aimdo-mini-track mini-vram-bar">
            <div class="aimdo-seg aimdo-seg-vram"></div>
            <div class="aimdo-seg aimdo-seg-torch"></div>
            <div class="aimdo-seg aimdo-seg-torchCache"></div>
            <div class="aimdo-seg aimdo-seg-other"></div>
        </div>
    </div>
    <div class="mini-pagefile-section">
        <div class="aimdo-mini-row">
            <span class="mini-pagefile-label">${_t("pagefile")}</span><span class="mini-pagefile-usage"></span>
        </div>
        <div class="aimdo-mini-track mini-pagefile-bar">
            <div class="aimdo-seg aimdo-seg-python"></div>
        </div>
    </div>
    <div class="mini-faults-section">
        <div class="aimdo-mini-row">
            <span class="mini-faults-label">${_t("faults")}</span><span class="mini-faults-usage"></span>
        </div>
        <div class="aimdo-mini-track mini-faults-bar"><div class="aimdo-mini-fill mini-faults-fill"></div></div>
    </div>
    <div class="mini-disk-section is-multibar">
        <div class="aimdo-mini-row mini-disk-row">
            <span class="mini-disk-label">${_t("disk")}</span><span class="mini-disk-header-value"></span>
        </div>
        <div class="aimdo-mini-inline mini-disk-read-row">
            <div class="aimdo-mini-track mini-disk-read-bar"><div class="aimdo-mini-fill mini-disk-read-fill"></div></div>
            <span class="mini-disk-read-usage"></span>
        </div>
        <div class="aimdo-mini-inline mini-disk-write-row">
            <div class="aimdo-mini-track mini-disk-write-bar"><div class="aimdo-mini-fill mini-disk-write-fill"></div></div>
            <span class="mini-disk-write-usage"></span>
        </div>
    </div>
    <div class="mini-diskspace-section is-multibar">
        <div class="aimdo-mini-row mini-diskspace-row">
            <span class="mini-diskspace-label">${_t("diskSpace")}</span>
        </div>
        <div class="mini-diskspace-rows"></div>
    </div>
    <div class="mini-cpu-section">
        <div class="aimdo-mini-row">
            <span class="mini-cpu-label">CPU</span><span class="mini-cpu-usage"></span>
        </div>
        <div class="aimdo-mini-track mini-cpu-bar"><div class="aimdo-mini-fill mini-cpu-fill"></div></div>
    </div>
    <div class="mini-gpu-section">
        <div class="aimdo-mini-row mini-gpu-row">
            <span class="mini-gpu-label">GPU</span><span class="mini-gpu-header-value"></span>
        </div>
        <div class="aimdo-mini-inline mini-util-row">
            <div class="aimdo-mini-track mini-gpu-bar"><div class="aimdo-mini-fill mini-gpu-fill"></div></div>
            <span class="mini-gpu-usage"></span>
        </div>
        <div class="aimdo-mini-inline mini-temp-row">
            <div class="aimdo-mini-track mini-temp-bar"><div class="aimdo-mini-fill mini-temp-fill"></div></div>
            <span class="mini-temp-usage"></span>
        </div>
        <div class="aimdo-mini-inline mini-power-row">
            <div class="aimdo-mini-track mini-power-bar"><div class="aimdo-mini-fill mini-power-fill"></div></div>
            <span class="mini-power-usage"></span>
        </div>
    </div>`;

    // refs cached once so the per-tick render path doesn't re-query
    const mbRefs = {
        bar: miniBar,
        ramSection: miniBar.querySelector(".mini-ram-section"),
        ramLabel: miniBar.querySelector(".mini-ram-label"),
        ramUsage: miniBar.querySelector(".mini-ram-usage"),
        ramSegs: miniBar.querySelectorAll(".mini-ram-bar > .aimdo-seg"),
        vramSection: miniBar.querySelector(".mini-vram-section"),
        vramLabel: miniBar.querySelector(".mini-vram-label"),
        vramUsage: miniBar.querySelector(".mini-vram-usage"),
        vramSegs: miniBar.querySelectorAll(".mini-vram-bar > .aimdo-seg"),
        cpuSection: miniBar.querySelector(".mini-cpu-section"),
        cpuLabel: miniBar.querySelector(".mini-cpu-label"),
        cpuUsage: miniBar.querySelector(".mini-cpu-usage"),
        cpuFill: miniBar.querySelector(".mini-cpu-fill"),
        pagefileSection: miniBar.querySelector(".mini-pagefile-section"),
        pagefileLabel: miniBar.querySelector(".mini-pagefile-label"),
        pagefileUsage: miniBar.querySelector(".mini-pagefile-usage"),
        pagefileSegs: miniBar.querySelectorAll(".mini-pagefile-bar > .aimdo-seg"),
        faultsSection: miniBar.querySelector(".mini-faults-section"),
        faultsLabel: miniBar.querySelector(".mini-faults-label"),
        faultsUsage: miniBar.querySelector(".mini-faults-usage"),
        faultsFill: miniBar.querySelector(".mini-faults-fill"),
        diskSection: miniBar.querySelector(".mini-disk-section"),
        diskLabel: miniBar.querySelector(".mini-disk-label"),
        diskReadUsage: miniBar.querySelector(".mini-disk-read-usage"),
        diskReadFill: miniBar.querySelector(".mini-disk-read-fill"),
        diskWriteUsage: miniBar.querySelector(".mini-disk-write-usage"),
        diskWriteFill: miniBar.querySelector(".mini-disk-write-fill"),
        diskSpaceSection: miniBar.querySelector(".mini-diskspace-section"),
        diskSpaceLabel: miniBar.querySelector(".mini-diskspace-label"),
        diskSpaceRows: miniBar.querySelector(".mini-diskspace-rows"),
        gpuSection: miniBar.querySelector(".mini-gpu-section"),
        gpuRow: miniBar.querySelector(".mini-gpu-row"),
        gpuLabel: miniBar.querySelector(".mini-gpu-label"),
        gpuHeaderValue: miniBar.querySelector(".mini-gpu-header-value"),
        utilRow: miniBar.querySelector(".mini-util-row"),
        gpuUsage: miniBar.querySelector(".mini-gpu-usage"),
        gpuFill: miniBar.querySelector(".mini-gpu-fill"),
        tempRow: miniBar.querySelector(".mini-temp-row"),
        tempUsage: miniBar.querySelector(".mini-temp-usage"),
        tempFill: miniBar.querySelector(".mini-temp-fill"),
        powerRow: miniBar.querySelector(".mini-power-row"),
        powerUsage: miniBar.querySelector(".mini-power-usage"),
        powerFill: miniBar.querySelector(".mini-power-fill"),
    };
    miniBar._refs = mbRefs;

    const headerRight = document.createElement("div");
    headerRight.className = "aimdo-header-right";

    // optional play / cancel-running button. Toggles based on execState.running which
    // setup() keeps current via api event listeners; we also call updateExecBtnState
    // directly from those listeners so the button flips the instant execution starts/ends.
    const execBtn = document.createElement("span");
    execBtn.className = "aimdo-exec-btn";
    execBtn.style.display = showExecBtn ? "" : "none";
    function updateExecBtnState() {
        if (execState.running) {
            execBtn.classList.add("is-running");
            execBtn.textContent = "■";
            execBtn.title = _t("cancelRun");
        } else {
            execBtn.classList.remove("is-running");
            execBtn.textContent = "▶";
            execBtn.title = _t("runWorkflow");
        }
    }
    updateExecBtnState();
    let execBusy = false;
    execBtn.addEventListener("click", async (e) => {
        e.stopPropagation();
        // re-entrancy guard: fast double-clicks during the in-flight request would
        // otherwise double-queue (or send a redundant interrupt).
        if (execBusy) return;
        execBusy = true;
        try {
            if (execState.running) await api.interrupt(null);
            else await app.queuePrompt(0);
        } catch (err) {
            console.error("aimdo-viz: exec/interrupt failed", err);
        } finally {
            execBusy = false;
        }
    });
    headerRight.appendChild(execBtn);

    const unloadBtn = document.createElement("span");
    unloadBtn.className = "aimdo-btn";
    unloadBtn.textContent = _t("unload");
    unloadBtn.title = _t("unloadTitle");

    const unloadMenu = document.createElement("div");
    unloadMenu.className = "aimdo-menu";
    unloadMenu.style.minWidth = "160px";
    const unloadOptions = [
        { label: _t("unloadAimdo"), title: _t("unloadAimdoTitle"), run: () =>
            api.fetchApi("/aimdo/unload_all", { method: "POST" }) },
        { label: _t("unloadModels"), title: _t("unloadModelsTitle"), run: () =>
            api.fetchApi("/free", { method: "POST",
                body: JSON.stringify({ unload_models: true }),
                headers: { "Content-Type": "application/json" } }) },
        { label: _t("unloadCache"), title: _t("unloadCacheTitle"), run: () =>
            api.fetchApi("/free", { method: "POST",
                body: JSON.stringify({ unload_models: true, free_memory: true }),
                headers: { "Content-Type": "application/json" } }) },
    ];
    for (const opt of unloadOptions) {
        const item = document.createElement("div");
        item.className = "aimdo-menu-item";
        item.textContent = opt.label;
        item.title = opt.title;
        item.addEventListener("click", async (e) => {
            e.stopPropagation();
            unloadMenu.style.display = "none";
            unloadBtn.textContent = "...";
            try { await opt.run(); }
            finally { unloadBtn.textContent = _t("unload"); }
        });
        unloadMenu.appendChild(item);
    }
    document.body.appendChild(unloadMenu);

    unloadBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        if (unloadMenu.style.display === "block") {
            unloadMenu.style.display = "none";
            return;
        }
        const r = unloadBtn.getBoundingClientRect();
        unloadMenu.style.zoom = panelScale;
        // style.left/top are pre-zoom on a zoomed element, divide visual targets by scale
        unloadMenu.style.left = (Math.max(4, r.right - 160 * panelScale) / panelScale) + "px";
        unloadMenu.style.top = ((r.bottom + 2) / panelScale) + "px";
        unloadMenu.style.display = "block";
    });
    document.addEventListener("click", (e) => {
        if (e.target !== unloadBtn && !unloadMenu.contains(e.target)) {
            unloadMenu.style.display = "none";
        }
    });

    function resetHistory() {
        peakVramUsed = 0;
        resetHistoryState();
        clearHistoryStorage();
    }

    const popoutBtn = document.createElement("span");
    popoutBtn.className = "aimdo-btn-icon";
    popoutBtn.style.fontSize = "1em";
    popoutBtn.textContent = "\u2924";
    popoutBtn.title = _t("popout");
    popoutBtn.addEventListener("click", async (e) => {
        e.stopPropagation();
        if (pipWindow && !pipWindow.closed) { pipWindow.close(); return; }
        if (!window.documentPictureInPicture) {
            alert("Picture-in-Picture isn't supported here. Try Chrome or Edge.");
            return;
        }
        // PiP rewrites size to fill its window; .aimdo-docked's !important rules would fight it
        if (isDocked) undock();
        const r = panel.getBoundingClientRect();
        pipWindow = await window.documentPictureInPicture.requestWindow({
            width: Math.max(280, Math.round(r.width)),
            height: Math.max(200, Math.round(r.height)),
        });
        // mirror the stylesheet into the PiP window. Wait for the cloned <link> to finish
        // loading before continuing, otherwise the panel briefly renders unstyled while the
        // CSS file is being fetched in the PiP document.
        const styleSrc = document.getElementById("aimdo-viz-stylesheet");
        if (styleSrc) {
            const clone = styleSrc.cloneNode(true);
            await new Promise((resolve) => {
                clone.addEventListener("load", resolve, { once: true });
                clone.addEventListener("error", resolve, { once: true });  // proceed anyway after a 404
                pipWindow.document.head.appendChild(clone);
            });
        }
        // mirror the active theme onto PiP's <html> — the cloned stylesheet contains
        // every theme's overrides, the data attribute picks which block applies
        const themeAttr = document.documentElement.dataset.aimdoTheme;
        if (themeAttr) pipWindow.document.documentElement.dataset.aimdoTheme = themeAttr;
        // remember origins so we can restore on close
        const moved = [];
        const remember = el => moved.push({ el, parent: el.parentNode, next: el.nextSibling });
        remember(panel);
        for (const m of [rootMenu, unloadMenu, ...allSubmenus]) remember(m);
        const origPanelCss = panel.style.cssText;
        // fill the PiP window; drop the fixed positioning the main-page math expects
        Object.assign(panel.style, {
            position: "static", left: "auto", top: "auto", right: "auto", bottom: "auto",
            transform: "none",
            width: "100%", height: "100vh", maxWidth: "none", maxHeight: "none",
            border: "none", borderRadius: "0", boxShadow: "none",
        });
        pipWindow.document.body.style.margin = "0";
        pipWindow.document.body.style.background = C.bg;
        for (const { el } of moved) pipWindow.document.body.appendChild(el);
        pipWindow.addEventListener("pagehide", () => {
            panel.style.cssText = origPanelCss;
            for (const { el, parent, next } of moved) {
                if (!parent) continue;
                if (next && next.parentNode === parent) parent.insertBefore(el, next);
                else parent.appendChild(el);
            }
            pipWindow = null;
            applyOffsets();
        }, { once: true });
    });

    const toggleBtn = document.createElement("span");
    toggleBtn.className = "aimdo-btn-icon";
    toggleBtn.style.fontSize = "1.333em";
    toggleBtn.textContent = "\u2212";
    toggleBtn.title = _t("collapse");

    const body = document.createElement("div");
    body.id = "aimdo-viz-body";

    let collapsed = !!saved.collapsed;
    if (collapsed) {
        body.style.display = "none";
        toggleBtn.textContent = "+";
        miniBar.style.display = "block";
    }
    toggleBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        // docked: toggle the overlay body below the docked mini-bar; stays docked
        if (isDocked) {
            dockExpanded = !dockExpanded;
            if (dockExpanded) {
                panel.classList.add("aimdo-docked-expanded");
                positionDockedBody();
                toggleBtn.textContent = "\u2212";
            } else {
                panel.classList.remove("aimdo-docked-expanded");
                toggleBtn.textContent = "+";
            }
            return;
        }
        collapsed = !collapsed;
        body.style.display = collapsed ? "none" : "flex";
        miniBar.style.display = collapsed ? "block" : "none";
        toggleBtn.textContent = collapsed ? "+" : "\u2212";
        // each mode persists its own height so toggling restores the right size.
        const s = loadState();
        const h = collapsed ? s.heightCollapsed : s.height;
        panel.style.height = h != null ? (Math.min(h, window.innerHeight) / panelScale + "px") : "";
        applyConstraints();
        saveState({ collapsed });
    });

    headerRight.appendChild(unloadBtn);
    headerRight.appendChild(popoutBtn);
    headerRight.appendChild(toggleBtn);
    header.appendChild(headerRight);
    panel.appendChild(header);
    panel.appendChild(miniBar);
    panel.appendChild(body);

    let dragging = false, dx = 0, dy = 0;
    let dragSavedPointerEvents = null;
    let dragW = 0, dragH = 0;
    let dragRafPending = false;
    let dragLastX = 0, dragLastY = 0;
    // pendingDrag distinguishes "clicking a button in the header" from "grabbing to drag".
    // mousedown only arms; we wait for >DRAG_THRESHOLD px of movement before promoting to a real drag,
    // so a click on unload/reset/popout never triggers an undock.
    let pendingDrag = null;
    const DRAG_THRESHOLD = 5;

    function promoteDrag(e) {
        if (pendingDrag.dockedAtStart && isDocked) {
            // jump the now-floating panel under the cursor with a reasonable grab offset
            undock();
            const r = panel.getBoundingClientRect();
            dx = Math.min(r.width - 20, Math.max(20, 40));
            dy = Math.min(r.height - 8, Math.max(8, 14));
            const b = getCanvasBounds();
            rightOffset = b.right - (e.clientX - dx) - r.width;
            bottomOffset = b.bottom - (e.clientY - dy) - r.height;
            applyOffsets();
        }
        // for non-docked starts, dx/dy were captured at mousedown
        dragging = true;
        pendingDrag = null;
        dragSavedPointerEvents = panel.style.pointerEvents || "";
        panel.style.pointerEvents = "none";
        const r0 = panel.getBoundingClientRect();
        dragW = r0.width;
        dragH = r0.height;
        ensureDropZone();
    }

    header.addEventListener("mousedown", (e) => {
        if (e.button !== 0) return;
        // when docked, only the drag handle starts a drag — the title and buttons
        // around it must stay plain-clickable. floating mode keeps the whole header.
        if (isDocked && !dragHandle.contains(e.target)) return;
        autoDockPending = false;  // user intent overrides the pending auto-redock
        pendingDrag = { startX: e.clientX, startY: e.clientY, dockedAtStart: isDocked };
        if (!isDocked) {
            const r = panel.getBoundingClientRect();
            dx = e.clientX - r.left;
            dy = e.clientY - r.top;
        }
    });
    // Ctrl/Cmd + mousedown anywhere on the panel starts a drag — capture phase
    // so we intercept before child elements (buttons, edge handles) react
    const isModifier = e => (e.ctrlKey || e.metaKey) && e.button === 0;
    const updateCursor = (e) => { panel.style.cursor = (e.ctrlKey || e.metaKey) ? "move" : ""; };
    document.addEventListener("keydown", updateCursor);
    document.addEventListener("keyup", updateCursor);
    window.addEventListener("blur", () => { panel.style.cursor = ""; });
    panel.addEventListener("mousedown", (e) => {
        if (!isModifier(e) || dragging || pendingDrag) return;
        e.preventDefault();
        e.stopPropagation();
        pendingDrag = { startX: e.clientX, startY: e.clientY, dockedAtStart: isDocked };
        if (!isDocked) {
            const r = panel.getBoundingClientRect();
            dx = e.clientX - r.left;
            dy = e.clientY - r.top;
        }
    }, true);
    // suppress the click that follows a Ctrl+drag so a Ctrl+click on a button
    // doesn't trigger its action after the drag ends
    panel.addEventListener("click", (e) => {
        if (isModifier(e)) {
            e.preventDefault();
            e.stopPropagation();
        }
    }, true);
    function flushDrag() {
        dragRafPending = false;
        if (!dragging) return;
        const b = getCanvasBounds();
        rightOffset = b.right - (dragLastX - dx) - dragW;
        bottomOffset = b.bottom - (dragLastY - dy) - dragH;
        applyOffsets();
    }
    document.addEventListener("mousemove", (e) => {
        if (pendingDrag) {
            const adx = Math.abs(e.clientX - pendingDrag.startX);
            const ady = Math.abs(e.clientY - pendingDrag.startY);
            if (Math.max(adx, ady) < DRAG_THRESHOLD) return;
            promoteDrag(e);
        }
        if (!dragging) return;
        dragLastX = e.clientX;
        dragLastY = e.clientY;
        if (!dragRafPending) {
            dragRafPending = true;
            requestAnimationFrame(flushDrag);
        }
    });
    // shared drag-end cleanup so a mouseup off-window (or alt-tab during drag) doesn't
    // leave pendingDrag armed, pointer-events stuck at "none", or drop zones in the DOM.
    function endDrag(commit) {
        pendingDrag = null;
        if (!dragging) {
            // pendingDrag-only path (click without movement). No drop zones to clear,
            // but call clearDropZone defensively in case a stale one slipped through.
            clearDropZone();
            return;
        }
        const wantDockSide = commit ? dropZoneHoverSide : null;
        clearDropZone();
        if (dragSavedPointerEvents !== null) {
            panel.style.pointerEvents = dragSavedPointerEvents;
            dragSavedPointerEvents = null;
        }
        dragging = false;  // before applyOffsets so it uses the clamped position
        if (commit) {
            if (wantDockSide) {
                dock(wantDockSide);
            } else {
                const c = clampOffsets(rightOffset, bottomOffset);
                rightOffset = c.ro;
                bottomOffset = c.bo;
                applyOffsets();
                saveState({ rightOffset, bottomOffset });
            }
        } else {
            // abort (blur / alt-tab): snap back into bounds visually without persisting
            applyOffsets();
        }
    }
    document.addEventListener("mouseup", () => endDrag(true));
    window.addEventListener("blur", () => endDrag(false));

    // edge handles: left grows left (right edge anchored), right grows right (left
    // edge anchored via RO ro-delta), bottom grows down (top edge anchored via bo-delta).
    let suppressWidthAnchor = false;
    let edgeDrag = null;
    function makeEdgeHandle(side) {
        const h = document.createElement("div");
        h.className = `aimdo-edge-handle aimdo-edge-${side}`;
        h.title = _t("dragResize");
        h.addEventListener("mousedown", (e) => {
            if (e.button !== 0) return;
            e.preventDefault();
            e.stopPropagation();
            // captured at drag start so the RO ro-shift mid-drag can't move the cap.
            const r = panel.getBoundingClientRect();
            const { minLeft, maxRight } = getSideChromeBounds(r.top, r.bottom);
            const maxWidth = side === "right" ? maxRight - r.left : r.right - minLeft;
            edgeDrag = { side, startX: e.clientX, startWidth: r.width, maxWidth };
            if (side === "left") suppressWidthAnchor = true;
        });
        panel.appendChild(h);
    }
    makeEdgeHandle("left");
    makeEdgeHandle("right");

    // collapsed: can't shrink below header + miniBar. expanded: keep modelsDiv top visible.
    function computeMinHeight(panelRect) {
        if (collapsed) return miniBar.getBoundingClientRect().bottom - panelRect.top + 2;
        if (refs && refs.modelsDiv) {
            return Math.max(40, refs.modelsDiv.getBoundingClientRect().top - panelRect.top + 8);
        }
        return 80;
    }

    let bottomDrag = null;
    function makeBottomHandle() {
        const h = document.createElement("div");
        // inset from the side handles so corners go to the ew-resize handles
        h.className = "aimdo-edge-handle aimdo-edge-bottom";
        h.title = _t("dragResize");
        h.addEventListener("mousedown", (e) => {
            if (e.button !== 0) return;
            e.preventDefault();
            e.stopPropagation();
            const r = panel.getBoundingClientRect();
            const minHeight = computeMinHeight(r);
            const maxHeight = window.innerHeight - r.top;
            bottomDrag = { startY: e.clientY, startHeight: r.height, minHeight, maxHeight };
        });
        panel.appendChild(h);
    }
    makeBottomHandle();

    // bottom-right corner handle: diagonal width+height drag. The grip gradient + hover
    // opacity live in aimdo_viz.css now.
    let cornerDrag = null;
    function makeCornerHandle() {
        const h = document.createElement("div");
        h.className = "aimdo-corner-handle";
        h.title = _t("dragResize");
        h.addEventListener("mousedown", (e) => {
            if (e.button !== 0) return;
            e.preventDefault();
            e.stopPropagation();
            const r = panel.getBoundingClientRect();
            const { minLeft, maxRight } = getSideChromeBounds(r.top, r.bottom);
            cornerDrag = {
                startX: e.clientX, startY: e.clientY,
                startWidth: r.width, startHeight: r.height,
                maxWidth: maxRight - r.left,
                maxHeight: window.innerHeight - r.top,
                minHeight: computeMinHeight(r),
            };
        });
        panel.appendChild(h);
    }
    makeCornerHandle();

    document.addEventListener("mousemove", (e) => {
        if (!edgeDrag) return;
        const delta = e.clientX - edgeDrag.startX;
        const newWidth = edgeDrag.side === "left" ? edgeDrag.startWidth - delta : edgeDrag.startWidth + delta;
        panel.style.width = Math.max(200, Math.min(edgeDrag.maxWidth, newWidth)) / panelScale + "px";
    });
    document.addEventListener("mousemove", (e) => {
        if (!bottomDrag) return;
        const delta = e.clientY - bottomDrag.startY;
        const newHeight = Math.max(bottomDrag.minHeight, Math.min(bottomDrag.maxHeight, bottomDrag.startHeight + delta));
        panel.style.height = (newHeight / panelScale) + "px";
        // relax the 50vh auto-grow cap once user sets an explicit height.
        applyConstraints();
    });
    document.addEventListener("mousemove", (e) => {
        if (!cornerDrag) return;
        const dx = e.clientX - cornerDrag.startX;
        const dy = e.clientY - cornerDrag.startY;
        const newWidth = Math.max(200, Math.min(cornerDrag.maxWidth, cornerDrag.startWidth + dx));
        const newHeight = Math.max(cornerDrag.minHeight, Math.min(cornerDrag.maxHeight, cornerDrag.startHeight + dy));
        panel.style.width = (newWidth / panelScale) + "px";
        panel.style.height = (newHeight / panelScale) + "px";
        applyConstraints();
    });
    document.addEventListener("mouseup", () => {
        if (edgeDrag) {
            edgeDrag = null;
            suppressWidthAnchor = false;
        }
        if (bottomDrag) bottomDrag = null;
        if (cornerDrag) cornerDrag = null;
    });

    // menu chrome lives in aimdo_viz.css (.aimdo-menu). Submenus differ only by
    // position which we set inline at openSubmenu time.
    function makeMenu() {
        const m = document.createElement("div");
        m.className = "aimdo-menu";
        return m;
    }
    const rootMenu = makeMenu();
    const scaleSubmenu = makeMenu();
    const pollSubmenu = makeMenu();
    const displaySubmenu = makeMenu();
    const miniSubmenu = makeMenu();
    const themeSubmenu = makeMenu();
    const dockWidthSubmenu = makeMenu();
    const graphSubmenu = makeMenu();
    const gpuSubmenu = makeMenu();
    const diskSubmenu = makeMenu();
    const fontSizeSubmenu = makeMenu();
    const langSubmenu = makeMenu();
    const allSubmenus = [scaleSubmenu, fontSizeSubmenu, pollSubmenu, displaySubmenu, miniSubmenu, themeSubmenu, dockWidthSubmenu, graphSubmenu, gpuSubmenu, diskSubmenu, langSubmenu];
    function closeAllSubmenus() { for (const m of allSubmenus) m.style.display = "none"; }

    // submenu overlaps parent by 1px so mouse transit doesn't trigger mouseleave-close.
    // anchorMenu defaults to rootMenu (top-level submenus) but can be another submenu
    // for nested cases; keepOpen lists ancestors that must NOT be closed when this opens.
    function openSubmenu(parentItem, submenu, anchorMenu, keepOpen) {
        anchorMenu = anchorMenu || rootMenu;
        keepOpen = keepOpen || [];
        for (const m of allSubmenus) {
            if (m === submenu || keepOpen.includes(m)) continue;
            m.style.display = "none";
        }
        submenu.style.zoom = panelScale;
        submenu.style.display = "block";
        const anchorR = anchorMenu.getBoundingClientRect();
        const itemR = parentItem.getBoundingClientRect();
        const subR = submenu.getBoundingClientRect();
        let left = anchorR.right - 1;
        if (left + subR.width > window.innerWidth) left = Math.max(2, anchorR.left - subR.width + 1);
        submenu.style.left = (left / panelScale) + "px";
        submenu.style.top = (Math.min(itemR.top, window.innerHeight - subR.height - 4) / panelScale) + "px";
    }

    // factory for a checkbox-style toggle item bound to a module-level flag.
    function makeToggleItem(label, getValue, setValue, stateKey) {
        const item = document.createElement("div");
        item.className = "aimdo-menu-item";
        const render = () => {
            item.innerHTML = `<span class="aimdo-check">${getValue() ? "✓" : ""}</span>${label}`;
        };
        render();
        item.addEventListener("click", (e) => {
            e.stopPropagation();
            if (item.classList.contains("is-disabled")) return;
            setValue(!getValue());
            saveState({ [stateKey]: getValue() });
            render();
            // visible change kicks in on the next poll tick (<= pollInterval ms).
        });
        return { item, render };
    }

    // parent item that opens a submenu on hover; chevron hints at the nesting.
    function makeSubmenuParent(label, submenu, anchorMenu, keepOpen) {
        const item = document.createElement("div");
        item.className = "aimdo-menu-parent";
        item.innerHTML = `<span>${label}</span><span class="aimdo-chevron">▸</span>`;
        item.addEventListener("mouseenter", () => openSubmenu(item, submenu, anchorMenu, keepOpen));
        return item;
    }

    // --- Scale submenu
    const scalePresets = [0.5, 0.75, 1, 1.25, 1.5, 1.75, 2];
    const scaleItems = new Map();
    function renderScaleItems() {
        for (const [s, item] of scaleItems) {
            const on = Math.abs(s - panelScale) < 1e-6;
            item.innerHTML = `<span class="aimdo-check">${on ? "✓" : ""}</span>${Math.round(s * 100)}%`;
        }
    }
    function setScale(s) {
        const r = panel.getBoundingClientRect();
        const w = r.width, h = r.height;
        const hadExplicitHeight = panel.style.height !== "";
        panelScale = s;
        panel._scale = s;
        panel.style.zoom = s;
        panel.style.width = (w / s) + "px";
        if (hadExplicitHeight) panel.style.height = (h / s) + "px";
        applyConstraints();
        applyOffsets();
        saveState({ scale: s });
    }
    for (const s of scalePresets) {
        const item = document.createElement("div");
        item.className = "aimdo-menu-item";
        item.addEventListener("click", (e) => {
            e.stopPropagation();
            setScale(s);
            renderScaleItems();
            rootMenu.style.display = "none";
            closeAllSubmenus();
        });
        scaleSubmenu.appendChild(item);
        scaleItems.set(s, item);
    }
    renderScaleItems();

    // --- Font Size submenu (single-select, like Scale)
    const fontSizePresets = [10, 11, 12, 13, 14, 16, 18, 20];
    const fontSizeItems = new Map();
    function renderFontSizeItems() {
        for (const [s, item] of fontSizeItems) {
            const on = s === fontSize;
            item.innerHTML = `<span class="aimdo-check">${on ? "✓" : ""}</span>${s}px`;
        }
    }
    function setFontSize(s) {
        fontSize = s;
        panel.style.setProperty('--aimdo-font-size', s + 'px');
        saveState({ fontSize: s });
    }
    for (const s of fontSizePresets) {
        const item = document.createElement("div");
        item.className = "aimdo-menu-item";
        item.addEventListener("click", (e) => {
            e.stopPropagation();
            setFontSize(s);
            renderFontSizeItems();
            rootMenu.style.display = "none";
            closeAllSubmenus();
        });
        fontSizeSubmenu.appendChild(item);
        fontSizeItems.set(s, item);
    }
    renderFontSizeItems();

    // --- Language submenu (single-select)
    const langPresets = [
        { key: "zh", label: _t("langZh") },
        { key: "en", label: _t("langEn") },
    ];
    const langItems = new Map();
    function renderLangItems() {
        for (const [k, item] of langItems) {
            const on = k === lang;
            const label = langPresets.find(p => p.key === k).label;
            item.innerHTML = `<span class="aimdo-check">${on ? "✓" : ""}</span>${label}`;
        }
    }
    function setLang(l) {
        lang = l;
        saveState({ lang: l });
        // 更新迷你栏静态标签
        const m = mbRefs;
        if (m) {
            m.ramLabel.textContent = _t("ram");
            m.vramLabel.textContent = _t("vram");
            m.pagefileLabel.textContent = _t("pagefile");
            m.faultsLabel.textContent = _t("faults");
            m.diskLabel.textContent = _t("disk");
            m.diskSpaceLabel.textContent = _t("diskSpace");
        }
        // 更新标题
        if (body._titleSpan && body._titleSpan.style.display !== "none") {
            body._titleSpan.textContent = _t("title");
        }
        // 更新按钮
        titleSpan.textContent = _t("title");
        unloadBtn.textContent = _t("unload");
        unloadBtn.title = _t("unloadTitle");
        popoutBtn.title = _t("popout");
        toggleBtn.title = _t("collapse");
        dragHandle.title = _t("dragMove");
        graphResize.title = _t("dragResizeGraph");
        // 更新菜单项文本（下次打开菜单时生效）
    }
    for (const p of langPresets) {
        const item = document.createElement("div");
        item.className = "aimdo-menu-item";
        item.addEventListener("click", (e) => {
            e.stopPropagation();
            setLang(p.key);
            renderLangItems();
            rootMenu.style.display = "none";
            closeAllSubmenus();
        });
        langSubmenu.appendChild(item);
        langItems.set(p.key, item);
    }
    renderLangItems();

    // --- Display submenu
    const colorBars = makeToggleItem(_t("toggleColorBars"),
        () => colorModelBars, v => { colorModelBars = v; }, "colorModelBars");
    const colorStroke = makeToggleItem(_t("toggleColorStroke"),
        () => colorModelStroke, v => { colorModelStroke = v; }, "colorModelStroke");
    const colorName = makeToggleItem(_t("toggleColorName"),
        () => colorModelName, v => { colorModelName = v; }, "colorModelName");
    const showLeg = makeToggleItem(_t("toggleShowLegends"),
        () => showLegends, v => { showLegends = v; }, "showLegends");
    const showTitleItem = makeToggleItem(_t("toggleShowTitle"),
        () => showTitle, v => { showTitle = v; }, "showTitle");
    const showExecBtnItem = makeToggleItem(_t("toggleExecBtn"),
        () => showExecBtn,
        v => { showExecBtn = v; execBtn.style.display = v ? "" : "none"; },
        "showExecBtn");
    displaySubmenu.appendChild(colorBars.item);
    displaySubmenu.appendChild(colorStroke.item);
    displaySubmenu.appendChild(colorName.item);
    displaySubmenu.appendChild(showLeg.item);
    displaySubmenu.appendChild(showTitleItem.item);
    displaySubmenu.appendChild(showExecBtnItem.item);

    // --- Mini view submenu
    const showRam = makeToggleItem(_t("toggleRam"),
        () => showRamInMini, v => { showRamInMini = v; }, "showRamInMini");
    const showVram = makeToggleItem(_t("toggleVram"),
        () => showVramInMini, v => { showVramInMini = v; }, "showVramInMini");
    const showCpu = makeToggleItem("CPU",
        () => showCpuInMini, v => { showCpuInMini = v; }, "showCpuInMini");
    const showPagefile = makeToggleItem(_t("togglePagefile"),
        () => showPagefileInMini, v => { showPagefileInMini = v; }, "showPagefileInMini");
    const showDisk = makeToggleItem(_t("toggleIO"),
        () => showDiskInMini, v => { showDiskInMini = v; }, "showDiskInMini");
    const showFaults = makeToggleItem(_t("toggleFaults"),
        () => showFaultsInMini, v => { showFaultsInMini = v; }, "showFaultsInMini");
    // labeled "util" since these live under the nested GPU submenu now
    const showGpu = makeToggleItem(_t("toggleUtil"),
        () => showGpuInMini, v => { showGpuInMini = v; }, "showGpuInMini");
    const showNames = makeToggleItem(_t("toggleNames"),
        () => showHwNames, v => { showHwNames = v; }, "showHwNames");
    const showNumbers = makeToggleItem(_t("toggleNumbers"),
        () => miniShowNumbers, v => { miniShowNumbers = v; }, "miniShowNumbers");
    const showUnits = makeToggleItem(_t("toggleUnits"),
        () => miniShowUnits, v => { miniShowUnits = v; }, "miniShowUnits");
    const showType = makeToggleItem(_t("toggleType"),
        () => miniShowType, v => { miniShowType = v; }, "miniShowType");
    const showGpuTemp = makeToggleItem(_t("toggleTemp"),
        () => miniShowGpuTemp, v => { miniShowGpuTemp = v; }, "miniShowGpuTemp");
    const showGpuPower = makeToggleItem(_t("togglePower"),
        () => miniShowGpuPower, v => { miniShowGpuPower = v; }, "miniShowGpuPower");
    const showSeparators = makeToggleItem(_t("toggleSeparators"),
        () => miniShowSeparators, v => { miniShowSeparators = v; }, "miniShowSeparators");
    miniSubmenu.appendChild(showRam.item);
    miniSubmenu.appendChild(showVram.item);
    miniSubmenu.appendChild(showCpu.item);
    miniSubmenu.appendChild(showPagefile.item);
    // GPU's util / temp / power get their own submenu since they're closely related —
    // keeps the Mini-view list flat and groups the three multibar toggles together.
    // Each is independent: any combination can be on/off, including just temp+power.
    gpuSubmenu.appendChild(showGpu.item);
    gpuSubmenu.appendChild(showGpuTemp.item);
    gpuSubmenu.appendChild(showGpuPower.item);
    miniSubmenu.appendChild(makeSubmenuParent("GPU", gpuSubmenu, miniSubmenu, [miniSubmenu]));

    // --- Disk submenu: I/O toggle + one toggle per detected fixed drive.
    // Drive items are populated lazily from the next poll once list_disks=1
    // is requested. Selecting any drive enables the disk-space mini section.
    diskSubmenu.appendChild(showDisk.item);
    diskSubmenu.appendChild(showFaults.item);
    const drivesHeader = document.createElement("div");
    drivesHeader.className = "aimdo-menu-header";
    drivesHeader.textContent = _t("drives");
    diskSubmenu.appendChild(drivesHeader);
    const drivesPlaceholder = document.createElement("div");
    drivesPlaceholder.className = "aimdo-menu-item is-disabled";
    drivesPlaceholder.innerHTML = `<span class="aimdo-check"></span>(${_t("detecting")})`;
    diskSubmenu.appendChild(drivesPlaceholder);
    const driveItems = new Map();  // mountpoint → menu item element
    function renderDriveItems() {
        for (const [mp, item] of driveItems) {
            const on = selectedDisks.includes(mp);
            const entry = allDisksCache.find(d => d.mountpoint === mp);
            // Volume labels are user-supplied (e.g. drive renamed in Explorer),
            // so escape them before splicing into innerHTML.
            const lbl = entry && entry.label ? ` ${escHtml(entry.label)}` : "";
            item.innerHTML = `<span class="aimdo-check">${on ? "✓" : ""}</span>${escHtml(shortMountpoint(mp))}${lbl}`;
        }
    }
    function rebuildDriveMenu() {
        if (!allDisksCache.length) return;
        if (drivesPlaceholder.parentNode) drivesPlaceholder.remove();
        // Remove items for drives no longer present, and add new ones.
        const present = new Set(allDisksCache.map(d => d.mountpoint));
        for (const [mp, item] of driveItems) {
            if (!present.has(mp)) { item.remove(); driveItems.delete(mp); }
        }
        for (const d of allDisksCache) {
            if (driveItems.has(d.mountpoint)) continue;
            const item = document.createElement("div");
            item.className = "aimdo-menu-item";
            item.addEventListener("click", (e) => {
                e.stopPropagation();
                const idx = selectedDisks.indexOf(d.mountpoint);
                if (idx >= 0) selectedDisks.splice(idx, 1);
                else selectedDisks.push(d.mountpoint);
                saveState({ selectedDisks });
                renderDriveItems();
            });
            diskSubmenu.appendChild(item);
            driveItems.set(d.mountpoint, item);
        }
        renderDriveItems();
    }
    _rebuildDriveMenu = rebuildDriveMenu;
    const diskParent = makeSubmenuParent(_t("toggleDisk"), diskSubmenu, miniSubmenu, [miniSubmenu]);
    // first hover triggers a fresh enumeration on the next poll
    diskParent.addEventListener("mouseenter", () => { wantDisksList = true; });
    miniSubmenu.appendChild(diskParent);

    // when the cursor enters a non-parent item in miniSubmenu, close nested submenus
    // — otherwise they'd linger open while the user is interacting with sibling toggles.
    miniSubmenu.addEventListener("mouseover", (e) => {
        const item = e.target.closest(".aimdo-menu-item, .aimdo-menu-parent");
        if (item && item.classList.contains("aimdo-menu-item")) {
            gpuSubmenu.style.display = "none";
            diskSubmenu.style.display = "none";
        }
    });
    miniSubmenu.appendChild(showNames.item);
    miniSubmenu.appendChild(showType.item);
    miniSubmenu.appendChild(showNumbers.item);
    miniSubmenu.appendChild(showUnits.item);
    miniSubmenu.appendChild(showSeparators.item);

    // --- Polling interval submenu (single-select like Scale)
    const pollPresets = [100, 250, 500, 1000, 2000, 5000];
    const pollItems = new Map();
    function renderPollItems() {
        for (const [ms, item] of pollItems) {
            const on = ms === pollInterval;
            const label = ms < 1000 ? `${ms} ms` : `${ms / 1000} s`;
            item.innerHTML = `<span class="aimdo-check">${on ? "✓" : ""}</span>${label}`;
        }
    }
    for (const ms of pollPresets) {
        const item = document.createElement("div");
        item.className = "aimdo-menu-item";
        item.addEventListener("click", (e) => {
            e.stopPropagation();
            pollInterval = ms;
            saveState({ pollInterval });
            renderPollItems();
            rootMenu.style.display = "none";
            closeAllSubmenus();
        });
        pollSubmenu.appendChild(item);
        pollItems.set(ms, item);
    }
    renderPollItems();

    // --- Theme submenu (single-select; live-applies)
    // applyPalette pushes the active palette into CSS variables on :root, so
    // most chrome repaints itself. We only need to manually clear places that
    // bake colors into innerHTML / canvas at render time and pick the new
    // palette up on their next tick.
    function applyTheme(name) {
        if (!THEME_NAMES.includes(name)) return;
        currentTheme = name;
        applyPalette(name);
        if (refs && refs.bottomLegend) {
            refs.bottomLegend.remove();
            refs.bottomLegend = null;
        }
    }
    const themeItems = new Map();
    function renderThemeItems() {
        for (const [name, item] of themeItems) {
            const on = name === currentTheme;
            const label = name[0].toUpperCase() + name.slice(1);
            item.innerHTML = `<span class="aimdo-check">${on ? "✓" : ""}</span>${label}`;
        }
    }
    for (const name of THEME_NAMES) {
        const item = document.createElement("div");
        item.className = "aimdo-menu-item";
        item.addEventListener("click", (e) => {
            e.stopPropagation();
            applyTheme(name);
            saveState({ theme: name });
            renderThemeItems();
            rootMenu.style.display = "none";
            closeAllSubmenus();
        });
        themeSubmenu.appendChild(item);
        themeItems.set(name, item);
    }
    renderThemeItems();

    // --- Dock width submenu (section width when docked into the topbar)
    const dockWidthSliderRow = document.createElement("div");
    dockWidthSliderRow.style.cssText = `padding:6px 10px;display:flex;flex-direction:column;gap:4px;min-width:180px;`;
    dockWidthSliderRow.addEventListener("click", (e) => e.stopPropagation());
    const dockWidthLabel = document.createElement("div");
    dockWidthLabel.style.cssText = `display:flex;justify-content:space-between;font-size:0.833em;color:var(--aimdo-textDim);`;
    dockWidthLabel.innerHTML = `<span>${_t("dockSectionW")}</span><span class="aimdo-dw-val">${dockSectionWidth}px</span>`;
    const dockWidthSlider = document.createElement("input");
    dockWidthSlider.type = "range";
    dockWidthSlider.min = "60";
    dockWidthSlider.max = "400";
    dockWidthSlider.step = "5";
    dockWidthSlider.value = String(dockSectionWidth);
    dockWidthSlider.style.cssText = `width:100%;accent-color:var(--aimdo-vram);cursor:pointer;`;
    const dockWidthValSpan = dockWidthLabel.querySelector(".aimdo-dw-val");
    dockWidthSlider.addEventListener("input", () => {
        dockSectionWidth = parseInt(dockWidthSlider.value, 10);
        dockWidthValSpan.textContent = dockSectionWidth + "px";
        applyDockSectionWidth();
        saveState({ dockSectionWidth });
    });
    dockWidthSliderRow.appendChild(dockWidthLabel);
    dockWidthSliderRow.appendChild(dockWidthSlider);
    dockWidthSubmenu.appendChild(dockWidthSliderRow);
    function renderDockWidthItems() {
        dockWidthSlider.value = String(dockSectionWidth);
        dockWidthValSpan.textContent = dockSectionWidth + "px";
    }

    buildGraphSubmenu(graphSubmenu, () => redrawGraph());

    // --- Root menu items
    rootMenu.appendChild(makeSubmenuParent(_t("menuScale"), scaleSubmenu));
    rootMenu.appendChild(makeSubmenuParent(_t("menuFontSize"), fontSizeSubmenu));
    rootMenu.appendChild(makeSubmenuParent(_t("menuPoll"), pollSubmenu));
    rootMenu.appendChild(makeSubmenuParent(_t("menuDisplay"), displaySubmenu));
    rootMenu.appendChild(makeSubmenuParent(_t("menuMini"), miniSubmenu));
    rootMenu.appendChild(makeSubmenuParent(_t("menuGraph"), graphSubmenu));
    rootMenu.appendChild(makeSubmenuParent(_t("menuTheme"), themeSubmenu));
    rootMenu.appendChild(makeSubmenuParent(_t("menuDockWidth"), dockWidthSubmenu));
    rootMenu.appendChild(makeSubmenuParent(_t("menuLang"), langSubmenu));

    // dock / undock toggle — present only when the actionbar is available so we don't
    // offer a no-op when ComfyUI's new menu is disabled.
    const dockItem = document.createElement("div");
    dockItem.className = "aimdo-menu-item";
    function renderDockItem() {
        const canDock = !!getActionbarContainer();
        dockItem.style.display = (isDocked || canDock) ? "" : "none";
        dockItem.innerHTML = `<span class="aimdo-check">${isDocked ? "✓" : ""}</span>${isDocked ? _t("undock") : _t("dockTop")}`;
    }
    dockItem.addEventListener("click", (e) => {
        e.stopPropagation();
        if (isDocked) undock(); else dock();
        renderDockItem();
        rootMenu.style.display = "none";
        closeAllSubmenus();
    });
    renderDockItem();
    rootMenu.appendChild(dockItem);

    // reset peak VRAM marker + clear history graph; this used to live on the header
    const resetItem = document.createElement("div");
    resetItem.className = "aimdo-menu-item";
    resetItem.innerHTML = `<span class="aimdo-check"></span>${_t("resetHistory")}`;
    resetItem.title = _t("resetHistoryTitle");
    resetItem.addEventListener("click", (e) => {
        e.stopPropagation();
        resetHistory();
        rootMenu.style.display = "none";
        closeAllSubmenus();
    });
    rootMenu.appendChild(resetItem);

    function renderColorBarsItem() {
        renderScaleItems(); renderPollItems(); renderThemeItems(); renderDockWidthItems();
        colorBars.render(); colorStroke.render(); colorName.render(); showLeg.render();
        showRam.render(); showVram.render(); showCpu.render(); showGpu.render(); showNames.render();
        showTitleItem.render(); showExecBtnItem.render();
        showType.render(); showNumbers.render(); showUnits.render();
        showGpuTemp.render(); showGpuPower.render();
        renderDockItem();
    }

    document.body.appendChild(rootMenu);
    for (const m of allSubmenus) document.body.appendChild(m);

    panel.addEventListener("contextmenu", (e) => {
        e.preventDefault();
        e.stopPropagation();
        renderColorBarsItem();
        closeAllSubmenus();
        rootMenu.style.zoom = panelScale;
        rootMenu.style.display = "block";
        const mRect = rootMenu.getBoundingClientRect();
        const mw = mRect.width || 120 * panelScale;
        const mh = mRect.height || 120 * panelScale;
        rootMenu.style.left = (Math.min(e.clientX, window.innerWidth - mw - 4) / panelScale) + "px";
        rootMenu.style.top = (Math.min(e.clientY, window.innerHeight - mh - 4) / panelScale) + "px";
    });
    document.addEventListener("click", (e) => {
        if (rootMenu.contains(e.target)) return;
        for (const m of allSubmenus) if (m.contains(e.target)) return;
        rootMenu.style.display = "none";
        closeAllSubmenus();
    });
    // moving the mouse out of the menu structure into empty space should also
    // close the submenu so it doesn't linger over unrelated UI.
    rootMenu.addEventListener("mouseleave", (e) => {
        const target = e.relatedTarget;
        if (target && (target instanceof Node) && allSubmenus.some(m => m.contains(target))) return;
        closeAllSubmenus();
    });
    for (const m of allSubmenus) {
        m.addEventListener("mouseleave", (e) => {
            const target = e.relatedTarget;
            if (target && (target instanceof Node) && (rootMenu.contains(target) || allSubmenus.some(x => x.contains(target)))) return;
            m.style.display = "none";
        });
    }

    document.body.appendChild(panel);
    applyOffsets();

    // restore docked placement once ComfyUI has built the topbar. Until the container
    // exists we wait — the panel sits floating in its persisted spot in the meantime.
    // Capped at ~3s so a user who disabled the new menu doesn't keep us polling.
    // Any user-initiated drag or explicit undock during the wait cancels the poll so
    // we don't yank the panel out from under them.
    if (isDocked) {
        isDocked = false;  // dock() guards on this; reset so it actually runs
        autoDockPending = true;
        let frames = 0;
        const tryDock = () => {
            if (!autoDockPending) return;
            if (dock(dockSide)) return;
            if (++frames > 180) { autoDockPending = false; saveState({ docked: false }); return; }
            requestAnimationFrame(tryDock);
        };
        requestAnimationFrame(tryDock);
    }

    // width changes shift ro to anchor one edge (unless suppressed by the left handle).
    // height changes always anchor the top edge by shifting bo by -Δh.
    let lastPanelWidth = null;
    let lastPanelHeight = null;
    if (typeof ResizeObserver !== "undefined") {
        new ResizeObserver(() => {
            if (isPoppedOut()) return;  // PiP resize doesn't persist back to main-page state
            if (isDocked) { lastPanelWidth = null; lastPanelHeight = null; positionDockedBody(); return; }
            const r = panel.getBoundingClientRect();
            const w = r.width, h = r.height;
            if (lastPanelWidth !== null && w !== lastPanelWidth) {
                if (!suppressWidthAnchor) rightOffset -= (w - lastPanelWidth);
                saveState({ width: w, rightOffset, bottomOffset });
            }
            if (lastPanelHeight !== null && h !== lastPanelHeight) {
                bottomOffset -= (h - lastPanelHeight);
                // persist height only on explicit drag, and key it by current mode so
                // expanded vs collapsed heights don't overwrite each other.
                if (bottomDrag || cornerDrag) {
                    const key = collapsed ? "heightCollapsed" : "height";
                    saveState({ [key]: h, bottomOffset });
                } else saveState({ bottomOffset });
            }
            lastPanelWidth = w;
            lastPanelHeight = h;
            applyOffsets();
        }).observe(panel);
    }

    // sidebar toggles don't fire window.resize. canvas may not exist yet — poll until it does.
    let observed = null;
    function attachCanvasObserver() {
        const el = getCanvasEl();
        if (!el) {
            requestAnimationFrame(attachCanvasObserver);
            return;
        }
        if (el === observed) return;
        observed = el;
        if (typeof ResizeObserver !== "undefined") {
            new ResizeObserver(() => { applyOffsets(); positionDockedBody(); }).observe(el);
        }
        applyOffsets();
    }
    attachCanvasObserver();
    body._titleSpan = titleSpan;
    body._miniBar = miniBar;
    body._panel = panel;
    body._updateExecBtnState = updateExecBtnState;
    return body;
}

// persistent DOM refs to avoid re-querying / re-creating
let refs = null;

function ensureStructure(body) {
    if (refs) return refs;

    body.innerHTML = "";

    const contentDiv = document.createElement("div");
    contentDiv.id = "aimdo-content";
    contentDiv.style.cssText = "flex-shrink: 0;";
    contentDiv.addEventListener("click", (e) => {
        const t = e.target.closest(".aimdo-gpu-util");
        if (!t) return;
        graphState.gpuLineVisible = !graphState.gpuLineVisible;
        saveState({ gpuLineVisible: graphState.gpuLineVisible });
        redrawGraph();
        t.style.opacity = graphState.gpuLineVisible ? "1" : "0.4";
    });
    // skeleton built once; renderData mutates text/widths/visibility only.
    contentDiv.innerHTML = `
        <div style="margin-bottom:4px;">
            <div style="display:flex;justify-content:space-between;gap:6px;margin-bottom:2px;">
                <span>${_t("ram")}</span>
                <span class="content-ram-usage"></span>
            </div>
            <div style="background:var(--aimdo-barBg);border-radius:3px;height:8px;overflow:hidden;display:flex;">
                <div class="aimdo-seg aimdo-seg-pinned"></div>
                <div class="aimdo-seg aimdo-seg-loadedRam"></div>
                <div class="aimdo-seg aimdo-seg-python"></div>
                <div class="aimdo-seg aimdo-seg-other"></div>
            </div>
            <div class="content-ram-legend" style="display:flex;gap:8px;font-size:0.833em;color:var(--aimdo-textDim);margin-top:2px;">
                <span><span style="color:var(--aimdo-pinned);">&#9632;</span> <span class="content-ram-pinned-txt"></span></span>
                <span><span style="color:var(--aimdo-loadedRam);">&#9632;</span> <span class="content-ram-loaded-txt"></span></span>
                <span><span style="color:var(--aimdo-python);">&#9632;</span> <span class="content-ram-python-txt"></span></span>
                <span><span style="color:var(--aimdo-other);">&#9632;</span> <span class="content-ram-other-txt"></span></span>
            </div>
        </div>
        <div style="margin-bottom:4px;">
            <div style="display:flex;justify-content:space-between;gap:6px;margin-bottom:2px;">
                <span class="content-vram-label">${_t("vram")}</span>
                <span class="content-vram-usage"></span>
            </div>
            <div style="background:var(--aimdo-barBg);border-radius:3px;height:8px;overflow:hidden;display:flex;">
                <div class="aimdo-seg aimdo-seg-vram"></div>
                <div class="aimdo-seg aimdo-seg-torch"></div>
                <div class="aimdo-seg aimdo-seg-torchCache"></div>
                <div class="aimdo-seg aimdo-seg-other"></div>
            </div>
            <div class="content-vram-legend" style="display:flex;gap:8px;font-size:0.833em;color:var(--aimdo-textDim);margin-top:2px;">
                <span class="content-vram-models-wrap"><span style="color:var(--aimdo-vram);">&#9632;</span> <span class="content-vram-models-txt"></span></span>
                <span class="content-vram-torch-wrap"><span style="color:var(--aimdo-torch);">&#9632;</span> <span class="content-vram-torch-txt"></span></span>
                <span class="content-vram-cache-wrap"><span style="color:var(--aimdo-torchCache);">&#9632;</span> <span class="content-vram-cache-txt"></span></span>
                <span><span style="color:var(--aimdo-other);">&#9632;</span> <span class="content-vram-other-txt"></span></span>
            </div>
            <div style="display:flex;gap:10px;font-size:0.833em;color:var(--aimdo-textDim);margin-top:2px;">
                <span class="content-info-peak"></span>
                <span class="content-info-cache"></span>
                <span class="aimdo-gpu-util content-info-gpu" title="${_t("gpuLineTitle")}" style="cursor:pointer;"></span>
                <span class="content-info-temp"></span>
                <span class="content-info-power" title="${_t("gpuPowerTitle")}"></span>
                <span class="content-info-state"></span>
            </div>
        </div>
        <div class="content-pagefile-section" style="margin-bottom:4px;">
            <div style="display:flex;justify-content:space-between;gap:6px;margin-bottom:2px;">
                <span>${_t("pagefile")}</span>
                <span class="content-pagefile-usage"></span>
            </div>
            <div class="content-pagefile-bar" style="background:var(--aimdo-barBg);border-radius:3px;height:8px;overflow:hidden;display:flex;">
                <div class="aimdo-seg aimdo-seg-python"></div>
            </div>
        </div>
    `;
    const _q = (s) => contentDiv.querySelector(s);
    // .aimdo-seg-other: [0]=RAM block, [1]=VRAM block
    const _others = contentDiv.querySelectorAll(".aimdo-seg-other");
    contentDiv._refs = {
        ramUsage: _q(".content-ram-usage"),
        ramSegs: [_q(".aimdo-seg-pinned"), _q(".aimdo-seg-loadedRam"), _q(".aimdo-seg-python"), _others[0]],
        ramTexts: {
            pinned: _q(".content-ram-pinned-txt"),
            loaded: _q(".content-ram-loaded-txt"),
            python: _q(".content-ram-python-txt"),
            other: _q(".content-ram-other-txt"),
        },
        ramLegend: _q(".content-ram-legend"),
        vramLabel: _q(".content-vram-label"),
        vramUsage: _q(".content-vram-usage"),
        vramSegs: [_q(".aimdo-seg-vram"), _q(".aimdo-seg-torch"), _q(".aimdo-seg-torchCache"), _others[1]],
        vramWraps: {
            models: _q(".content-vram-models-wrap"),
            torch: _q(".content-vram-torch-wrap"),
            cache: _q(".content-vram-cache-wrap"),
        },
        vramTexts: {
            models: _q(".content-vram-models-txt"),
            torch: _q(".content-vram-torch-txt"),
            cache: _q(".content-vram-cache-txt"),
            other: _q(".content-vram-other-txt"),
        },
        vramLegend: _q(".content-vram-legend"),
        infoPeak: _q(".content-info-peak"),
        infoCache: _q(".content-info-cache"),
        infoGpu: _q(".content-info-gpu"),
        infoTemp: _q(".content-info-temp"),
        infoPower: _q(".content-info-power"),
        infoState: _q(".content-info-state"),
        pagefileSection: _q(".content-pagefile-section"),
        pagefileUsage: _q(".content-pagefile-usage"),
        pagefileSegs: contentDiv.querySelectorAll(".content-pagefile-bar > .aimdo-seg"),
    };
    body.appendChild(contentDiv);

    const graphHeader = document.createElement("div");
    graphHeader.style.cssText = `display:flex;justify-content:space-between;font-size:0.75em;color:var(--aimdo-textDim);margin-bottom:2px;flex-shrink:0;`;
    graphHeader.innerHTML = `<span class="graph-time-left"></span><span class="graph-hover-info"></span><span class="graph-time-right"></span>`;
    body.appendChild(graphHeader);

    const graphCanvas = document.createElement("canvas");
    graphCanvas.className = "aimdo-graph-canvas";
    graphCanvas.width = 300;
    graphCanvas.height = graphHeight;
    graphCanvas.style.cssText = `width:100%;height:${graphHeight}px;border-radius:3px;background:var(--aimdo-graphBg);flex-shrink:0;`;
    body.appendChild(graphCanvas);

    const redrawGraph = () => {
        if (!refs || !refs.graphCtx) return;
        const panelScale = (body._panel && body._panel._scale) || 1;
        const gRect = graphCanvas.getBoundingClientRect();
        if (gRect.width > 0 && gRect.height > 0) {
            drawGraph(refs.graphCtx, gRect.width / panelScale, gRect.height / panelScale);
        }
        updateGraphTimes();
    };
    // rAF-coalesce bursts from mousemove (hover + scrub) so we draw at most once per frame
    let redrawPending = false;
    const scheduleRedraw = () => {
        if (redrawPending) return;
        redrawPending = true;
        requestAnimationFrame(() => { redrawPending = false; redrawGraph(); });
    };

    graphCanvas.addEventListener("mousemove", (e) => {
        if (scrubDrag) return;  // hover line during drag is distracting
        const rect = graphCanvas.getBoundingClientRect();
        const scale = (body._panel && body._panel._scale) || 1;
        const x = (e.clientX - rect.left) / scale;
        const w = rect.width / scale;
        const stepX = w / (GRAPH_POINTS - 1);
        const slotIdx = Math.round(x / stepX);
        const len = history.len;
        const visible = Math.min(GRAPH_POINTS, len - history.viewOffset);
        const visibleIdx = slotIdx - (GRAPH_POINTS - visible);
        if (visible < 1 || visibleIdx < 0 || visibleIdx >= visible) {
            graphHover.x = null;
            graphHover.idx = null;
        } else {
            const startIdx = len - visible - history.viewOffset;
            graphHover.idx = startIdx + visibleIdx;
            graphHover.x = slotIdx * stepX;
        }
        scheduleRedraw();
    });
    graphCanvas.addEventListener("mouseleave", () => {
        graphHover.x = null;
        graphHover.idx = null;
        redrawGraph();
    });

    // drag scrubbing: dragging the full visible window's worth scrolls by GRAPH_POINTS.
    // Drag right pulls older points into view; releasing at viewOffset 0 re-enables
    // follow-live so new data slides into the window automatically.
    let scrubDrag = null;
    graphCanvas.addEventListener("mousedown", (e) => {
        if (e.button !== 0) return;
        e.preventDefault();
        e.stopPropagation();
        const visualScale = (body._panel && body._panel._scale) || 1;
        scrubDrag = { startX: e.clientX, startOffset: history.viewOffset, scale: visualScale };
        history.followLive = false;
        graphCanvas.style.cursor = "grabbing";
    });
    document.addEventListener("mousemove", (e) => {
        if (!scrubDrag) return;
        const rect = graphCanvas.getBoundingClientRect();
        const dxPx = (e.clientX - scrubDrag.startX) / scrubDrag.scale;
        const ptsPerPx = GRAPH_POINTS / Math.max(1, rect.width / scrubDrag.scale);
        const maxOffset = Math.max(0, history.len - GRAPH_POINTS);
        history.viewOffset = Math.max(0, Math.min(maxOffset, Math.round(scrubDrag.startOffset + dxPx * ptsPerPx)));
        scheduleRedraw();
    });
    document.addEventListener("mouseup", () => {
        if (!scrubDrag) return;
        scrubDrag = null;
        graphCanvas.style.cursor = "";  // restore to CSS-default crosshair
        if (history.viewOffset <= 1) {
            history.viewOffset = 0;
            history.followLive = true;
        }
        redrawGraph();
    });

    // drag handle below the graph — adjusts canvas height; modelsDiv takes the rest.
    const graphResize = document.createElement("div");
    graphResize.className = "aimdo-graph-resize";
    graphResize.title = _t("dragResizeGraph");
    let graphDrag = null;
    graphResize.addEventListener("mousedown", (e) => {
        if (e.button !== 0) return;
        e.preventDefault();
        e.stopPropagation();
        graphDrag = { startY: e.clientY, startHeight: graphCanvas.getBoundingClientRect().height };
        graphResize.classList.add("is-dragging");
    });
    document.addEventListener("mousemove", (e) => {
        if (!graphDrag) return;
        const visualScale = (body._panel && body._panel._scale) || 1;
        const delta = (e.clientY - graphDrag.startY) / visualScale;
        const next = Math.max(20, Math.min(600, graphDrag.startHeight / visualScale + delta));
        graphHeight = Math.round(next);
        graphCanvas.style.height = graphHeight + "px";
    });
    document.addEventListener("mouseup", () => {
        if (graphDrag) {
            graphDrag = null;
            graphResize.classList.remove("is-dragging");
            saveState({ graphHeight });
        }
    });
    body.appendChild(graphResize);

    const modelsDiv = document.createElement("div");
    modelsDiv.id = "aimdo-models";
    modelsDiv.style.cssText = "flex: 1 1 auto; min-height: 0; overflow-y: auto;";
    body.appendChild(modelsDiv);

    refs = {
        contentDiv,
        graphHeader,
        graphCanvas,
        graphResize,
        graphCtx: graphCanvas.getContext("2d"),
        modelsDiv,
        pageCanvases: {},   // keyed by `${index}_${vi}`
        pageCtxs: {},
        modelRows: {},      // keyed by m.index — refs to mutable row parts
        noModelsMsg: null,
        bottomLegend: null,
    };
    return refs;
}

function updateGraphTimes() {
    if (!refs || !refs.graphHeader) return;
    refs.graphHeader.style.color = "var(--aimdo-textDim)";
    const leftEl = refs.graphHeader.querySelector(".graph-time-left");
    const hoverEl = refs.graphHeader.querySelector(".graph-hover-info");
    const rightEl = refs.graphHeader.querySelector(".graph-time-right");
    const len = history.len;
    if (len < 2) {
        leftEl.textContent = "";
        hoverEl.textContent = "";
        rightEl.textContent = "";
        return;
    }
    const visible = Math.min(GRAPH_POINTS, len - history.viewOffset);
    if (visible < 1) {
        leftEl.textContent = "";
        hoverEl.textContent = "";
        rightEl.textContent = "";
        return;
    }
    const startIdx = len - visible - history.viewOffset;
    const endIdx = len - 1 - history.viewOffset;
    leftEl.textContent = formatClock(historyGet(history.times, startIdx));
    rightEl.textContent = history.followLive ? _t("live") : formatClock(historyGet(history.times, endIdx));
    if (graphHover.idx != null) {
        const used = history.total_vram - historyGet(history.free_vram, graphHover.idx);
        const parts = [
            formatClock(historyGet(history.times, graphHover.idx)),
            formatBytes(used),
        ];
        if (graphState.gpuLineVisible) parts.push(Math.round(historyGet(history.gpu_util, graphHover.idx)) + "%");
        hoverEl.textContent = parts.join(" · ");
    } else {
        hoverEl.textContent = "";
    }
}

function applyRowCollapsed(row) {
    row.bar.style.display = row.collapsed ? "none" : "flex";
    row.legend.style.display = (row.collapsed || !showLegends) ? "none" : "flex";
    row.vbarsDiv.style.display = row.collapsed ? "none" : "";
    row.chevron.textContent = row.collapsed ? "▸" : "▾";
}

// build (or reuse) a model row, mutating only what changed
function renderModelRow(r, m, data) {
    const wantsWm = m.dynamic && data.aimdo_active;
    let row = r.modelRows[m.index];
    if (!row) {
        const el = document.createElement("div");
        el.className = "aimdo-model-row";
        const head = document.createElement("div");
        head.className = "aimdo-model-head";
        const nameWrap = document.createElement("span");
        nameWrap.className = "aimdo-model-name";
        nameWrap.title = _t("clickCollapse");
        const chevron = document.createElement("span");
        chevron.className = "aimdo-model-chevron";
        const nameSpan = document.createElement("span");
        nameWrap.appendChild(chevron);
        nameWrap.appendChild(nameSpan);
        const right = document.createElement("span");
        right.className = "aimdo-model-right";
        const sizeSpan = document.createElement("span");
        right.appendChild(sizeSpan);
        const unloadBtn = document.createElement("span");
        unloadBtn.className = "aimdo-unload-btn";
        unloadBtn.dataset.index = m.index;
        unloadBtn.textContent = "x";
        unloadBtn.title = _t("unloadModel");
        right.appendChild(unloadBtn);
        head.appendChild(nameWrap);
        head.appendChild(right);
        el.appendChild(head);
        const bar = document.createElement("div");
        bar.className = "aimdo-model-bar";
        el.appendChild(bar);
        const legend = document.createElement("div");
        legend.className = "aimdo-model-legend";
        const makeLegendEntry = () => {
            const wrap = document.createElement("span");
            const sw = document.createElement("span");
            sw.innerHTML = "&#9632;";
            const txt = document.createTextNode("");
            wrap.appendChild(sw);
            wrap.appendChild(txt);
            return { wrap, sw, txt };
        };
        const legendEntries = {
            vram: makeLegendEntry(),
            pinned: makeLegendEntry(),
            loaded: makeLegendEntry(),
            last: makeLegendEntry(),  // "unloaded" for dynamic models, "RAM" for static
        };
        legendEntries.pinned.sw.style.color = "var(--aimdo-pinned)";
        legendEntries.loaded.sw.style.color = "var(--aimdo-loadedRam)";
        legend.appendChild(legendEntries.vram.wrap);
        legend.appendChild(legendEntries.pinned.wrap);
        legend.appendChild(legendEntries.loaded.wrap);
        legend.appendChild(legendEntries.last.wrap);
        el.appendChild(legend);
        const vbarsDiv = document.createElement("div");
        el.appendChild(vbarsDiv);
        row = { el, chevron, nameSpan, sizeSpan, right, unloadBtn, bar, barSegs: [], legend, legendEntries, vbarsDiv, vbarRefs: [], wmBtn: null, lastDynamic: null, lastVbarSig: "", collapsed: false };
        nameWrap.addEventListener("click", () => {
            row.collapsed = !row.collapsed;
            modelCollapsed[m.name] = row.collapsed;
            saveState({ modelCollapsed });
            applyRowCollapsed(row);
        });
        row.collapsed = !!modelCollapsed[m.name];
        applyRowCollapsed(row);
        r.modelRows[m.index] = row;
    }

    row.nameSpan.textContent = m.name + (m.dynamic ? "" : ` (${_t("static_")})`);
    const typeColor = MODEL_TYPE_COLOR[m.type];
    const vramColor = (colorModelBars && typeColor) || C.vram;
    row.nameSpan.style.color = (colorModelName && typeColor) || C.text;
    row.el.style.borderColor = (colorModelStroke && typeColor) ? hexToRgba(typeColor, 0.4) : "transparent";
    if (!row.collapsed) row.legend.style.display = showLegends ? "flex" : "none";
    row.sizeSpan.textContent = formatBytes(m.total_size);

    if (wantsWm && !row.wmBtn) {
        const wm = document.createElement("span");
        wm.className = "aimdo-reset-wm-btn";
        wm.dataset.index = m.index;
        wm.textContent = _t("wm");
        wm.title = _t("wmTitle");
        row.right.insertBefore(wm, row.unloadBtn);
        row.wmBtn = wm;
    } else if (!wantsWm && row.wmBtn) {
        row.wmBtn.remove();
        row.wmBtn = null;
    }

    const barColors = m.dynamic ? [C.vram, C.pinned, C.loadedRam, C.unloaded] : [C.vram, C.pinned, C.loadedRam, C.pinned];
    if (row.lastDynamic !== m.dynamic || row.barSegs.length !== barColors.length) {
        row.bar.innerHTML = "";
        row.barSegs = [];
        for (const color of barColors) {
            const seg = document.createElement("div");
            seg.style.cssText = `background:${color};height:100%;`;
            row.bar.appendChild(seg);
            row.barSegs.push(seg);
        }
        row.lastDynamic = m.dynamic;
    }
    // re-apply each tick so theme changes reach the segments created once on dynamic-change rebuild.
    row.barSegs.forEach((seg, i) => { seg.style.background = i === 0 ? vramColor : barColors[i]; });

    const total = m.total_size || 1;
    const pinnedRam = m.pinned_ram || 0;
    const loadedRam = m.loaded_ram || 0;
    let vramShown, lastSize, lastLabel, lastColor, lastAlwaysShow;
    if (m.dynamic) {
        vramShown = m.vbar_loaded;
        lastSize = Math.max(0, m.total_size - m.vbar_loaded - pinnedRam - loadedRam);
        lastLabel = _t("unloaded");
        lastColor = "var(--aimdo-unloaded)";
        lastAlwaysShow = true;
    } else {
        vramShown = m.loaded_size;
        const inRam = Math.max(0, m.total_size - m.loaded_size);
        lastSize = Math.max(0, inRam - pinnedRam - loadedRam);
        lastLabel = _t("ramLabel");
        lastColor = "var(--aimdo-pinned)";
        lastAlwaysShow = false;
    }
    row.barSegs[0].style.width = (vramShown / total * 100) + "%";
    row.barSegs[0].title = _t("vramLabel") + ": " + formatBytes(vramShown);
    row.barSegs[1].style.width = (pinnedRam / total * 100) + "%";
    row.barSegs[1].title = _t("pinnedRAM") + ": " + formatBytes(pinnedRam);
    row.barSegs[2].style.width = (loadedRam / total * 100) + "%";
    row.barSegs[2].title = _t("loadedRAM") + ": " + formatBytes(loadedRam);
    row.barSegs[3].style.width = (lastSize / total * 100) + "%";
    row.barSegs[3].title = (m.dynamic ? _t("unloaded") + ": " : _t("ramTooltip") + ": ") + formatBytes(lastSize);

    const le = row.legendEntries;
    le.vram.sw.style.color = vramColor;
    le.vram.txt.nodeValue = ` ${_t("vramLabel")} ${formatBytes(vramShown)}`;
    le.pinned.wrap.style.display = pinnedRam > 0 ? "" : "none";
    if (pinnedRam > 0) le.pinned.txt.nodeValue = ` ${_t("pinned")} ${formatBytes(pinnedRam)}`;
    le.loaded.wrap.style.display = loadedRam > 0 ? "" : "none";
    if (loadedRam > 0) le.loaded.txt.nodeValue = ` ${_t("loaded")} ${formatBytes(loadedRam)}`;
    const showLast = lastAlwaysShow || lastSize > 0;
    le.last.wrap.style.display = showLast ? "" : "none";
    if (showLast) {
        le.last.sw.style.color = lastColor;
        le.last.txt.nodeValue = ` ${lastLabel} ${formatBytes(lastSize)}`;
    }

    // vbars: rebuild structure only when device list / count changes
    const vbars = (m.vbars || []).filter(v => v.residency && v.residency.length > 0);
    const sig = vbars.map(v => v.device + ":" + v.residency.length).join("|");
    if (row.lastVbarSig !== sig) {
        row.vbarsDiv.innerHTML = "";
        row.vbarRefs = [];
        const showLabel = vbars.length > 1;
        for (let vi = 0; vi < vbars.length; vi++) {
            const vb = vbars[vi];
            if (showLabel) {
                const lbl = document.createElement("div");
                lbl.style.cssText = `font-size:0.833em;color:var(--aimdo-textDim);margin-top:3px;`;
                lbl.textContent = vb.device;
                row.vbarsDiv.appendChild(lbl);
            }
            const pgrid = document.createElement("div");
            pgrid.style.cssText = "margin-top:2px;";
            row.vbarsDiv.appendChild(pgrid);
            const stats = document.createElement("div");
            stats.style.cssText = `color:var(--aimdo-textDim);font-size:0.833em;margin-top:2px;`;
            const vramSw = document.createElement("span"); vramSw.innerHTML = "&#9632;";
            const vramTxt = document.createTextNode("");
            const vramWrap = document.createElement("span");
            vramWrap.appendChild(vramSw); vramWrap.appendChild(vramTxt);
            const unloadedSw = document.createElement("span");
            unloadedSw.style.color = "var(--aimdo-unloaded)";
            unloadedSw.innerHTML = "&#9632;";
            const unloadedTxt = document.createTextNode("");
            const unloadedWrap = document.createElement("span");
            unloadedWrap.appendChild(unloadedSw); unloadedWrap.appendChild(unloadedTxt);
            stats.appendChild(vramWrap);
            stats.appendChild(document.createTextNode(" "));
            stats.appendChild(unloadedWrap);
            row.vbarsDiv.appendChild(stats);
            row.vbarRefs.push({ vi, pgrid, stats, vramSw, vramTxt, unloadedTxt });
        }
        row.lastVbarSig = sig;
    }
    return row;
}

function renderData(body, data) {
    if (!data.enabled) {
        body.innerHTML = `<div style="color:var(--aimdo-textDim);">${_t("noGpu")}</div>`;
        refs = null;
        return;
    }

    const r = ensureStructure(body);
    const pw = body._panel.getBoundingClientRect().width;
    body._titleSpan.style.display = showTitle ? "" : "none";
    body._titleSpan.textContent =
        pw >= 320 && data.aimdo_active ? _t("titleAimdo") :
        pw >= 240 ? _t("title") : "";
    data.gpu_util = smoothGpuUtil(data.gpu_util);
    // throttle history snapshots so a fast poll rate (e.g. 100 ms) doesn't fill
    // the buffer in 2 minutes; UI keeps updating at the full poll cadence.
    if (Date.now() - (history.lastPush || 0) >= HISTORY_TICK_MS) {
        pushHistory(data);
        history.lastPush = Date.now();
    }

    const used = data.total_vram - data.free_vram;
    if (used > peakVramUsed) peakVramUsed = used;

    // aimdo allocates through pytorch's caching allocator, so aimdo_usage
    // and torch_reserved overlap. Derive non-overlapping segments from
    // the driver-level total (used) as ground truth.
    let aimdo, torchActive, torchCache, otherUsed;
    if (data.aimdo_usage > 0) {
        // aimdo active: torch stats are a subset of aimdo, not additive
        aimdo = data.aimdo_usage;
        torchActive = 0;
        torchCache = 0;
        otherUsed = Math.max(0, used - aimdo);
    } else {
        // no aimdo: torch stats are the full picture
        aimdo = 0;
        torchActive = data.torch_active;
        torchCache = Math.max(0, data.torch_reserved - data.torch_active);
        otherUsed = Math.max(0, used - data.torch_reserved);
    }
    const aimdoPct = (aimdo / data.total_vram * 100).toFixed(0);
    const torchPct = (torchActive / data.total_vram * 100).toFixed(0);
    const torchCachePct = (torchCache / data.total_vram * 100).toFixed(0);
    const otherPct = (otherUsed / data.total_vram * 100).toFixed(0);

    const ramUsed = data.used_ram || 0;
    const ramTotal = data.total_ram || 1;
    const processRam = data.process_ram || 0;
    const pinnedRamTotal = data.pinned_ram || 0;
    const loadedRamTotal = data.loaded_ram || 0;
    const pythonOther = Math.max(0, processRam - pinnedRamTotal - loadedRamTotal);
    const ramOther = Math.max(0, ramUsed - processRam);
    const pinnedRamPct = (pinnedRamTotal / ramTotal * 100).toFixed(0);
    const loadedRamPct = (loadedRamTotal / ramTotal * 100).toFixed(0);
    const pythonOtherPct = (pythonOther / ramTotal * 100).toFixed(0);
    const ramOtherPct = (ramOther / ramTotal * 100).toFixed(0);

    const mb = body._miniBar;
    const m = mb._refs;  // refs cached at panel creation (see mbRefs in createPanel)
    const _u = miniShowUnits;
    const _n = miniShowNumbers;
    // "%" isn't a unit — units off should still show ratios as percentages, just
    // without GB/MB/°C/W. Quantities with a denominator (RAM/VRAM/power) become
    // "used/total" percentages; CPU/GPU util are already percentages so the "%"
    // stays on regardless; temp has no natural denominator so we drop the °C.
    // leading zero on single-digit values keeps width stable, matching the CPU/GPU util format
    const asPct = (num, total) => {
        if (total <= 0) return "?";
        const p = Math.round(num / total * 100);
        return (p < 10 ? "0" : "") + p + "%";
    };
    m.vramUsage.textContent = !_n ? "" :
        _u ? `${formatBytes(used)}|${formatBytes(data.total_vram)}`
           : asPct(used, data.total_vram);
    m.vramSegs[0].style.width = aimdoPct + "%";
    m.vramSegs[1].style.width = torchPct + "%";
    m.vramSegs[2].style.width = torchCachePct + "%";
    m.vramSegs[3].style.width = otherPct + "%";
    m.ramUsage.textContent = !_n ? "" :
        _u ? `${formatBytes(ramUsed)}|${formatBytes(ramTotal)}`
           : asPct(ramUsed, ramTotal);
    m.ramSegs[0].style.width = pinnedRamPct + "%";
    m.ramSegs[1].style.width = loadedRamPct + "%";
    m.ramSegs[2].style.width = pythonOtherPct + "%";
    m.ramSegs[3].style.width = ramOtherPct + "%";

    // toggleable "Type" label hides RAM / VRAM / CPU / GPU prefixes (plus any device suffix)
    m.ramLabel.style.display = miniShowType ? "" : "none";
    m.vramLabel.style.display = miniShowType ? "" : "none";

    m.bar.classList.toggle("has-separators", miniShowSeparators);
    m.ramSection.style.display = showRamInMini ? "" : "none";
    m.vramSection.style.display = showVramInMini ? "" : "none";
    if (data.cpu_util != null && showCpuInMini) {
        m.cpuSection.style.display = "";
        const cpuColor = gpuUtilColor(data.cpu_util);
        const cpuPct = Math.round(data.cpu_util);
        m.cpuUsage.innerHTML = _n
            ? `<span style="color:${cpuColor};">${(cpuPct < 10 ? "0" : "") + cpuPct}%</span>`
            : "";
        m.cpuFill.style.background = cpuColor;
        m.cpuFill.style.width = `${cpuPct}%`;
        m.cpuLabel.textContent = (showHwNames && data.cpu_name) ? `CPU (${shortenCpuName(data.cpu_name)})` : "CPU";
        m.cpuLabel.title = data.cpu_name || "";
        m.cpuLabel.style.display = miniShowType ? "" : "none";
    } else {
        m.cpuSection.style.display = "none";
    }
    if (showDiskInMini && data.disk_read != null && data.disk_write != null) {
        m.diskSection.style.display = "";
        const now = performance.now();
        let readRate = 0, writeRate = 0;
        if (diskState.prevRead != null && diskState.prevTime > 0) {
            const dt = (now - diskState.prevTime) / 1000;
            if (dt > 0) {
                readRate = Math.max(0, (data.disk_read - diskState.prevRead) / dt);
                writeRate = Math.max(0, (data.disk_write - diskState.prevWrite) / dt);
                const decay = Math.pow(0.5, dt / DISK_PEAK_HALFLIFE);
                diskState.peakRead = Math.max(readRate, diskState.peakRead * decay, DISK_PEAK_FLOOR);
                diskState.peakWrite = Math.max(writeRate, diskState.peakWrite * decay, DISK_PEAK_FLOOR);
            }
        }
        diskState.prevRead = data.disk_read;
        diskState.prevWrite = data.disk_write;
        diskState.prevTime = now;
        m.diskReadUsage.textContent = _n ? (formatBytes(readRate) + "/s ↓") : "";
        m.diskWriteUsage.textContent = _n ? (formatBytes(writeRate) + "/s ↑") : "";
        m.diskReadFill.style.width = (readRate / diskState.peakRead * 100) + "%";
        m.diskWriteFill.style.width = (writeRate / diskState.peakWrite * 100) + "%";
        m.diskLabel.style.display = miniShowType ? "" : "none";
    } else {
        m.diskSection.style.display = "none";
        diskState.prevRead = null;
        diskState.prevTime = 0;
    }
    // Free disk space — one row per selected drive, with all detected drives in
    // the tooltip so the user sees the full picture without checking every box.
    if (Array.isArray(data.disks)) {
        const oldMps = allDisksCache.map(d => d.mountpoint).join("|");
        const newMps = data.disks.map(d => d.mountpoint).join("|");
        allDisksCache = data.disks;
        if (_rebuildDriveMenu && oldMps !== newMps) _rebuildDriveMenu();
    }
    const visibleDisks = selectedDisks.length
        ? allDisksCache.filter(d => selectedDisks.includes(d.mountpoint))
        : [];
    if (visibleDisks.length > 0) {
        m.diskSpaceSection.style.display = "";
        m.diskSpaceSection.classList.toggle("no-units", !_u);
        const rows = m.diskSpaceRows;
        while (rows.children.length < visibleDisks.length) {
            const row = document.createElement("div");
            row.className = "aimdo-mini-inline mini-diskspace-drive-row";
            row.innerHTML = `<span class="mini-diskspace-mp"></span>`
                + `<div class="aimdo-mini-track mini-diskspace-bar"><div class="aimdo-mini-fill mini-diskspace-fill"></div></div>`
                + `<span class="mini-diskspace-usage"></span>`;
            rows.appendChild(row);
        }
        while (rows.children.length > visibleDisks.length) rows.lastChild.remove();
        for (let i = 0; i < visibleDisks.length; i++) {
            const d = visibleDisks[i];
            const row = rows.children[i];
            const mpEl = row.firstChild;
            const fillEl = row.querySelector(".mini-diskspace-fill");
            const usageEl = row.lastChild;
            const total = d.total, free = d.free;
            const used = (total != null && free != null) ? total - free : null;
            const pct = (used != null && total) ? (used / total * 100) : 0;
            mpEl.textContent = shortMountpoint(d.mountpoint);
            fillEl.style.width = pct.toFixed(1) + "%";
            // colour warms as the drive fills — same scale as gpuUtilColor (10/80 thresholds
            // are util-shaped; for free space "low → warmer" maps better at 75/90).
            fillEl.style.background = pct >= 90 ? C.gpuUtilHi : (pct >= 75 ? C.gpuUtil : C.pinned);
            usageEl.textContent = !_n ? "" :
                (free == null || !total) ? "?" :
                _u ? formatBytes(free)
                   : asPct(used, total);
        }
        m.diskSpaceSection.title = buildDiskTooltip(allDisksCache);
        m.diskSpaceLabel.style.display = miniShowType ? "" : "none";
    } else {
        m.diskSpaceSection.style.display = "none";
    }
    if (data.total_swap > 0 && showPagefileInMini) {
        m.pagefileSection.style.display = "";
        const swapPct = Math.round(data.used_swap / data.total_swap * 100);
        m.pagefileUsage.textContent = _n
            ? (_u ? `${formatBytes(data.used_swap)}|${formatBytes(data.total_swap)}` : (swapPct < 10 ? "0" : "") + swapPct + "%")
            : "";
        m.pagefileSegs[0].style.width = (data.used_swap / data.total_swap * 100) + "%";
        m.pagefileLabel.style.display = miniShowType ? "" : "none";
    } else {
        m.pagefileSection.style.display = "none";
    }
    if (showFaultsInMini && data.hard_faults != null) {
        m.faultsSection.style.display = "";
        const now = performance.now();
        let rate = 0;
        if (faultState.prev != null && faultState.prevTime > 0) {
            const dt = (now - faultState.prevTime) / 1000;
            if (dt > 0) {
                rate = Math.max(0, (data.hard_faults - faultState.prev) / dt);
                const decay = Math.pow(0.5, dt / FAULT_PEAK_HALFLIFE);
                faultState.peak = Math.max(rate, faultState.peak * decay, FAULT_PEAK_FLOOR);
            }
        }
        faultState.prev = data.hard_faults;
        faultState.prevTime = now;
        // bar height is rate vs recent peak; fixed color (height conveys activity)
        m.faultsFill.style.width = (rate / faultState.peak * 100) + "%";
        m.faultsUsage.textContent = _n ? `${Math.round(rate)}/s` : "";
        m.faultsLabel.style.display = miniShowType ? "" : "none";
    } else {
        m.faultsSection.style.display = "none";
        faultState.prev = null;
        faultState.prevTime = 0;
    }
    // each bar is independently toggleable; null data shows "N/A" rather than hiding,
    // so a missing pynvml doesn't make the whole section vanish silently.
    const _showUtil = showGpuInMini;
    const _showTemp = miniShowGpuTemp;
    const _showPower = miniShowGpuPower;
    const _utilOk = data.gpu_util != null;
    const _tempOk = data.gpu_temp != null;
    const _powerOk = data.gpu_power != null;
    const _activeBars = (_showUtil ? 1 : 0) + (_showTemp ? 1 : 0) + (_showPower ? 1 : 0);
    if (_activeBars > 0) {
        m.gpuSection.style.display = "";
        // compact 8px / 3px styling kicks in only when there's >1 bar to fit
        const isSingleBar = _activeBars === 1;
        m.gpuSection.classList.toggle("is-multibar", !isSingleBar);

        // title row — "GPU" or "GPU (RTX 4090)" on the left, value on the right when
        // only one bar is visible (then the layout matches RAM/VRAM/CPU above).
        m.gpuLabel.textContent = (showHwNames && data.gpu_name) ? `GPU (${shortenGpuName(data.gpu_name)})` : "GPU";
        m.gpuLabel.title = data.gpu_name || "";
        m.gpuLabel.style.display = miniShowType ? "" : "none";
        // keep the row visible if either the label is on, or there's a single-bar value to show
        m.gpuRow.style.display = (miniShowType || isSingleBar) ? "" : "none";

        // util row
        m.utilRow.style.display = _showUtil ? "" : "none";
        if (_showUtil) {
            if (_utilOk) {
                const gpuColor = gpuUtilColor(data.gpu_util);
                m.gpuFill.style.background = gpuColor;
                m.gpuFill.style.width = `${data.gpu_util}%`;
                m.gpuUsage.innerHTML = _n
                    ? `<span style="color:${gpuColor};">${(data.gpu_util < 10 ? "0" : "") + data.gpu_util}%</span>`
                    : "";
            } else {
                m.gpuFill.style.width = "0%";
                m.gpuUsage.textContent = _t("na");
            }
        }

        // temp row — 100°C is full scale; units-off uses "%" since the bar already
        // treats 100°C as the denominator (75°C → 75% of the bar full).
        m.tempRow.style.display = _showTemp ? "" : "none";
        if (_showTemp) {
            if (_tempOk) {
                const tempColor = gpuTempColor(data.gpu_temp);
                m.tempFill.style.background = tempColor;
                m.tempFill.style.width = `${Math.min(100, data.gpu_temp)}%`;
                const tempDisplay = _u ? `${data.gpu_temp}&deg;C` : `${Math.min(100, data.gpu_temp)}%`;
                m.tempUsage.innerHTML = _n
                    ? `<span style="color:${tempColor};">${tempDisplay}</span>`
                    : "";
            } else {
                m.tempFill.style.width = "0%";
                m.tempUsage.textContent = _t("na");
            }
        }

        // power row — fill is draw/limit; value is W or % depending on the Units toggle
        m.powerRow.style.display = _showPower ? "" : "none";
        if (_showPower) {
            if (_powerOk) {
                const powerColor = gpuPowerColor(data.gpu_power, data.gpu_power_limit);
                m.powerFill.style.background = powerColor;
                const powerPct = data.gpu_power_limit > 0
                    ? Math.min(100, data.gpu_power / data.gpu_power_limit * 100)
                    : 0;
                m.powerFill.style.width = `${powerPct}%`;
                const powerText = _u
                    ? formatPower(data.gpu_power, data.gpu_power_limit)
                    : asPct(data.gpu_power, data.gpu_power_limit);
                m.powerUsage.innerHTML = _n
                    ? `<span style="color:${powerColor};">${powerText}</span>`
                    : "";
            } else {
                m.powerFill.style.width = "0%";
                m.powerUsage.textContent = _t("na");
            }
        }

        // single-bar mode: lift the visible value into the title row so the section
        // reads like RAM/VRAM/CPU above (label + value on top, bar below).
        let headerHtml = "";
        if (isSingleBar) {
            if (_showUtil) headerHtml = m.gpuUsage.innerHTML;
            else if (_showTemp) headerHtml = m.tempUsage.innerHTML;
            else if (_showPower) headerHtml = m.powerUsage.innerHTML;
        }
        m.gpuHeaderValue.innerHTML = headerHtml;
    } else {
        m.gpuSection.style.display = "none";
    }

    // Group dividers: mark the first visible section of each non-leading group
    // so CSS can draw a separator above it. Recompute every render because the
    // first visible can change as the user toggles individual sections.
    function markFirstVisible(group) {
        let found = false;
        for (const sec of group) {
            if (!found && sec.style.display !== "none") {
                sec.classList.add("mini-group-start");
                found = true;
            } else {
                sec.classList.remove("mini-group-start");
            }
        }
    }
    markFirstVisible([m.diskSection, m.diskSpaceSection]);
    markFirstVisible([m.cpuSection, m.gpuSection]);

    const cr = r.contentDiv._refs;
    cr.ramUsage.textContent = `${formatBytes(ramUsed)}|${formatBytes(ramTotal)}`;
    cr.ramSegs[0].style.width = pinnedRamPct + "%";
    cr.ramSegs[0].title = _t("pinned") + ": " + formatBytes(pinnedRamTotal);
    cr.ramSegs[1].style.width = loadedRamPct + "%";
    cr.ramSegs[1].title = _t("loaded") + ": " + formatBytes(loadedRamTotal);
    cr.ramSegs[2].style.width = pythonOtherPct + "%";
    cr.ramSegs[2].title = _t("python") + ": " + formatBytes(pythonOther);
    cr.ramSegs[3].style.width = ramOtherPct + "%";
    cr.ramSegs[3].title = _t("other") + ": " + formatBytes(ramOther);
    cr.ramLegend.style.display = showLegends ? "flex" : "none";
    if (showLegends) {
        cr.ramTexts.pinned.textContent = `${_t("pinned")} ${formatBytes(pinnedRamTotal)}`;
        cr.ramTexts.loaded.textContent = `${_t("loaded")} ${formatBytes(loadedRamTotal)}`;
        cr.ramTexts.python.textContent = `${_t("python")} ${formatBytes(pythonOther)}`;
        cr.ramTexts.other.textContent = `${_t("other")} ${formatBytes(ramOther)}`;
    }

    cr.vramLabel.textContent = _t("vram") + ((showHwNames && data.gpu_name) ? ` (${shortenGpuName(data.gpu_name)})` : "");
    cr.vramLabel.title = data.gpu_name || "";
    cr.vramUsage.textContent = `${formatBytes(used)}|${formatBytes(data.total_vram)}`;
    cr.vramSegs[0].style.width = aimdoPct + "%";
    cr.vramSegs[0].title = _t("models") + ": " + formatBytes(aimdo);
    cr.vramSegs[1].style.width = torchPct + "%";
    cr.vramSegs[1].title = _t("torch") + ": " + formatBytes(torchActive);
    cr.vramSegs[2].style.width = torchCachePct + "%";
    cr.vramSegs[2].title = _t("cache") + ": " + formatBytes(torchCache);
    cr.vramSegs[3].style.width = otherPct + "%";
    cr.vramSegs[3].title = _t("other") + ": " + formatBytes(otherUsed);
    cr.vramLegend.style.display = showLegends ? "flex" : "none";
    if (showLegends) {
        cr.vramWraps.models.style.display = aimdo > 0 ? "" : "none";
        if (aimdo > 0) cr.vramTexts.models.textContent = `${_t("models")} ${formatBytes(aimdo)}`;
        cr.vramWraps.torch.style.display = torchActive > 0 ? "" : "none";
        if (torchActive > 0) cr.vramTexts.torch.textContent = `${_t("torch")} ${formatBytes(torchActive)}`;
        cr.vramWraps.cache.style.display = torchCache > 0 ? "" : "none";
        if (torchCache > 0) cr.vramTexts.cache.textContent = `${_t("cache")} ${formatBytes(torchCache)}`;
        cr.vramTexts.other.textContent = `${_t("other")} ${formatBytes(otherUsed)}`;
    }

    cr.infoPeak.textContent = _t("peak") + ": " + formatBytes(peakVramUsed);
    cr.infoCache.textContent = _t("cache") + ": " + formatBytes(data.torch_reserved - data.torch_active);
    if (data.gpu_util != null) {
        cr.infoGpu.style.display = "";
        cr.infoGpu.style.color = gpuUtilColor(data.gpu_util);
        cr.infoGpu.style.opacity = graphState.gpuLineVisible ? "1" : "0.4";
        cr.infoGpu.textContent = `GPU ${data.gpu_util < 10 ? "0" : ""}${data.gpu_util}%`;
    } else {
        cr.infoGpu.style.display = "none";
    }
    if (data.gpu_temp != null) {
        cr.infoTemp.style.display = "";
        cr.infoTemp.style.color = gpuTempColor(data.gpu_temp);
        cr.infoTemp.innerHTML = `${data.gpu_temp}&deg;C`;
    } else {
        cr.infoTemp.style.display = "none";
    }
    if (data.gpu_power != null) {
        cr.infoPower.style.display = "";
        cr.infoPower.style.color = gpuPowerColor(data.gpu_power, data.gpu_power_limit);
        cr.infoPower.textContent = formatPower(data.gpu_power, data.gpu_power_limit);
    } else {
        cr.infoPower.style.display = "none";
    }
    if (execState.running) {
        cr.infoState.style.color = "var(--aimdo-running)";
        cr.infoState.textContent = `● ${execState.node || _t("running")}${execState.progress ? " " + execState.progress : ""}`;
    } else {
        cr.infoState.style.color = "";
        cr.infoState.textContent = "● " + _t("idle");
    }
    if (data.total_swap > 0) {
        cr.pagefileSection.style.display = "";
        cr.pagefileSegs[0].style.width = (data.used_swap / data.total_swap * 100) + "%";
        cr.pagefileUsage.textContent = `${formatBytes(data.used_swap)}|${formatBytes(data.total_swap)}`;
    } else {
        cr.pagefileSection.style.display = "none";
    }

    // sync canvas backing to device pixels: visual viewport px × devicePixelRatio.
    // Drawing then happens in logical (panel-local) CSS px via the totalScale transform,
    // so cells/lines scale with panelScale while staying crisp on HiDPI.
    const panelScaleNow = body._panel._scale || 1;
    const dpr = window.devicePixelRatio || 1;
    const totalScale = panelScaleNow * dpr;
    const gRect = r.graphCanvas.getBoundingClientRect();
    if (gRect.width > 0 && gRect.height > 0) {
        const backingW = Math.max(1, Math.round(gRect.width * dpr));
        const backingH = Math.max(1, Math.round(gRect.height * dpr));
        if (r.graphCanvas.width !== backingW) r.graphCanvas.width = backingW;
        if (r.graphCanvas.height !== backingH) r.graphCanvas.height = backingH;
        r.graphCtx.setTransform(totalScale, 0, 0, totalScale, 0, 0);
        drawGraph(r.graphCtx, gRect.width / panelScaleNow, gRect.height / panelScaleNow);
        updateGraphTimes();
    }

    // models section — incremental DOM updates: keep rows across polls, only mutate text/widths
    if (data.models.length === 0 && !r.noModelsMsg) {
        r.noModelsMsg = document.createElement("div");
        r.noModelsMsg.textContent = _t("noModels");
        r.noModelsMsg.style.cssText = `color:var(--aimdo-textDim);margin-top:6px;`;
        r.modelsDiv.insertBefore(r.noModelsMsg, r.modelsDiv.firstChild);
    } else if (data.models.length > 0 && r.noModelsMsg) {
        r.noModelsMsg.remove();
        r.noModelsMsg = null;
    }

    // remove rows for models no longer present and clean up their canvas refs
    const liveIndices = new Set(data.models.map(m => m.index));
    for (const idx of Object.keys(r.modelRows)) {
        if (!liveIndices.has(parseInt(idx))) {
            r.modelRows[idx].el.remove();
            delete r.modelRows[idx];
        }
    }
    for (const key of Object.keys(r.pageCanvases)) {
        const idx = parseInt(key.split("_")[0]);
        if (!liveIndices.has(idx)) {
            delete r.pageCanvases[key];
            delete r.pageCtxs[key];
            delete modelState[key];
        }
    }

    if (!r.bottomLegend) {
        r.bottomLegend = document.createElement("div");
        r.bottomLegend.style.cssText = `display:flex;flex-wrap:wrap;gap:8px;font-size:0.833em;color:var(--aimdo-textDim);margin-top:4px;border-bottom:1px solid var(--aimdo-border);padding-bottom:4px;`;
        r.bottomLegend.innerHTML =
            `<span><span style="color:var(--aimdo-vram);">&#9632;</span> ${_t("vram")}</span>` +
            `<span><span style="color:var(--aimdo-pinned);">&#9632;</span> ${_t("pinned")}</span>` +
            `<span><span style="color:var(--aimdo-loadedRam);">&#9632;</span> ${_t("loaded")}</span>` +
            `<span><span style="color:var(--aimdo-unloaded);">&#9632;</span> ${_t("unloaded")}</span>` +
            `<span><span style="color:var(--aimdo-torch);">&#9632;</span> ${_t("torch")}</span>` +
            `<span><span style="color:var(--aimdo-totalLine);">&#9472;</span> ${_t("total")}</span>` +
            `<span><span style="color:var(--aimdo-gpuUtil);">&#9472;</span> ${_t("gpuPct")}</span>`;
        r.modelsDiv.insertBefore(r.bottomLegend, r.modelsDiv.firstChild);
    }
    r.bottomLegend.style.display = showLegends ? "flex" : "none";

    for (const m of data.models) {
        const isNew = !r.modelRows[m.index];
        const row = renderModelRow(r, m, data);
        if (isNew) r.modelsDiv.appendChild(row.el);
    }

    // draw page grids and update vbar stat text
    for (const m of data.models) {
        const row = r.modelRows[m.index];
        if (!row || !row.vbarRefs.length || row.collapsed) continue;
        const vbars = (m.vbars || []).filter(v => v.residency && v.residency.length > 0);
        for (let vi = 0; vi < row.vbarRefs.length; vi++) {
            const vb = vbars[vi];
            if (!vb) continue;
            const ref = row.vbarRefs[vi];
            const vkey = `${m.index}_${ref.vi}`;
            const st = diffResidency(vkey, vb.residency);
            let residentCount = 0, pinnedCount = 0;
            for (let i = 0; i < vb.residency.length; i++) {
                const flag = vb.residency[i];
                if (flag & 2) pinnedCount++;
                else if (flag & 1) residentCount++;
            }
            const PAGE = 32 * 1024 * 1024;
            const vramPages = residentCount + pinnedCount;
            const ramPages = vb.residency.length - vramPages;
            const vramColor = (colorModelBars && MODEL_TYPE_COLOR[m.type]) || C.vram;
            // swatch carries the category color; text inherits readable textDim.
            ref.vramSw.style.color = vramColor;
            ref.vramTxt.nodeValue = ` ${vramPages} ${_t("pageVRAM")} (${formatBytes(vramPages * PAGE)})`;
            ref.unloadedTxt.nodeValue = ` ${ramPages} ${_t("pageUnloaded")} (${formatBytes(ramPages * PAGE)})`;

            let canvas = r.pageCanvases[vkey];
            if (!canvas) {
                canvas = document.createElement("canvas");
                canvas.style.cssText = "width:100%;border-radius:2px;";
                r.pageCanvases[vkey] = canvas;
                r.pageCtxs[vkey] = canvas.getContext("2d");
            }
            if (canvas.parentElement !== ref.pgrid) ref.pgrid.appendChild(canvas);
            const pgVisualW = ref.pgrid.getBoundingClientRect().width
                || r.modelsDiv.getBoundingClientRect().width
                || 300 * panelScaleNow;
            const pgCssW = pgVisualW / panelScaleNow;
            drawPageGrid(r.pageCtxs[vkey], pgCssW, vb.residency, st ? st.changeAge : new Uint8Array(vb.residency.length), panelScaleNow, colorModelBars ? MODEL_TYPE_COLOR[m.type] : undefined);
        }
    }

    // attach button handlers via event delegation (once)
    if (!r.modelsDiv._delegated) {
        r.modelsDiv._delegated = true;
        r.modelsDiv.addEventListener("click", async (e) => {
            const wmBtn = e.target.closest(".aimdo-reset-wm-btn");
            if (wmBtn) {
                const idx = parseInt(wmBtn.dataset.index);
                wmBtn.textContent = "...";
                try {
                    await api.fetchApi("/aimdo/reset_watermark", {
                        method: "POST",
                        body: JSON.stringify({ index: idx }),
                        headers: { "Content-Type": "application/json" },
                    });
                } finally {
                    wmBtn.textContent = _t("wm");
                }
                return;
            }
            const unloadBtn = e.target.closest(".aimdo-unload-btn");
            if (unloadBtn) {
                const idx = parseInt(unloadBtn.dataset.index);
                unloadBtn.textContent = "...";
                try {
                    await api.fetchApi("/aimdo/unload_model", {
                        method: "POST",
                        body: JSON.stringify({ index: idx }),
                        headers: { "Content-Type": "application/json" },
                    });
                } catch { /* next poll will reflect state */ }
            }
        });
    }
}

app.registerExtension({
    name: "aimdo.VRAMVisualization",
    async setup() {
        // ── 注册 ComfyUI 设置面板开关 ──
        const SETTING_ID = "xb_toolbox.memory_viz.enabled";
        let panelEnabled = true;
        
        // 从 localStorage 读取初始状态（settings 系统可能还没就绪）
        try {
            const raw = localStorage.getItem("Comfy.Settings." + SETTING_ID);
            if (raw !== null) panelEnabled = JSON.parse(raw) !== false;
        } catch {}
        
        // 注册设置项（出现在 ComfyUI 设置 → XB_ToolBox 分类下）
        if (app.ui && app.ui.settings) {
            app.ui.settings.addSetting({
                id: SETTING_ID,
                name: "XB 📊 硬件监控面板 (Memory Visualization)",
                type: "boolean",
                defaultValue: true,
                category: ["XB_ToolBox", "硬件监控"],
                onChange: (value) => {
                    panelEnabled = value;
                    const panel = document.getElementById("aimdo-viz-panel");
                    if (panel) panel.style.display = value ? "" : "none";
                }
            });
        }
        
        if (!panelEnabled) return;  // 用户禁用了面板，不创建
        
        // wait for aimdo_viz.css so applyPalette can read CSS variables back into C —
        // canvas drawing needs real hex strings, not unresolved var() references.
        await cssLoaded;
        // load before wiring the periodic save so a stray tick can't overwrite the
        // stored history with an empty buffer between extension boot and first poll.
        await loadHistory();
        setInterval(saveHistory, 10000);
        // beforeunload is best-effort with IDB: writes are async and may not commit
        // before teardown. The 10s interval bounds loss to ~1% of the 20-min buffer.
        window.addEventListener("beforeunload", saveHistory);
        const body = createPanel();

        api.addEventListener("execution_start", () => {
            execState.running = true;
            execState.node = null;
            execState.progress = null;
            pushExecEvent("start");
            body._updateExecBtnState?.();
        });
        api.addEventListener("executing", ({ detail }) => {
            // detail is the node ID string while executing; null/undefined when done
            // (older ComfyUI) or when interrupted. Newer versions may not fire null.
            if (detail != null) {
                execState.running = true;
                execState.node = detail;
            }
            body._updateExecBtnState?.();
        });
        api.addEventListener("execution_interrupted", () => {
            execState.running = false;
            execState.node = null;
            execState.progress = null;
            pushExecEvent("end");
            body._updateExecBtnState?.();
        });
        // status event — reliable execution-end signal in newer ComfyUI (queue_remaining == 0)
        api.addEventListener("status", ({ detail }) => {
            if (detail && detail.exec_info && detail.exec_info.queue_remaining === 0) {
                if (execState.running) {
                    execState.running = false;
                    execState.node = null;
                    execState.progress = null;
                    pushExecEvent("end");
                    body._updateExecBtnState?.();
                }
            }
        });
        api.addEventListener("progress", ({ detail }) => {
            if (detail) {
                execState.progress = `${detail.value}/${detail.max}`;
            }
        });

        let pollTimer = null;
        async function poll() {
            // Skip fetch when the tab is hidden or the panel is detached
            if (document.hidden || !body.isConnected || !panelEnabled) {
                pollTimer = setTimeout(poll, pollInterval);
                return;
            }
            try {
                const params = [];
                if (showDiskInMini) params.push("disk=1");
                if (showPagefileInMini) params.push("pagefile=1");
                if (showFaultsInMini) params.push("faults=1");
                // list_disks drives both the visible bars (filtered by selectedDisks)
                // and the tooltip listing every fixed drive. The one-shot
                // wantDisksList flag lets the settings menu request a fresh list
                // even when nothing is selected yet.
                if (selectedDisks.length > 0 || wantDisksList) {
                    params.push("list_disks=1");
                    wantDisksList = false;
                }
                const url = "/aimdo/vram" + (params.length ? "?" + params.join("&") : "");
                const resp = await api.fetchApi(url);
                const data = await resp.json();
                renderData(body, data);
            } catch (e) {
                body.innerHTML = `<div style="color:#aa5555;">${_t("fetchError")}</div>`;
                refs = null;
            }
            pollTimer = setTimeout(poll, pollInterval);
        }

        // Wake immediately when the tab becomes visible
        document.addEventListener("visibilitychange", () => {
            if (!document.hidden && pollTimer != null) {
                clearTimeout(pollTimer);
                pollTimer = null;
                poll();
            }
        });

        poll();
    }
});