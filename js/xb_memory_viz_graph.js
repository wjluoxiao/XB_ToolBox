// Graph subsystem: history ring buffer, persistence, drawGraph, graph submenu.
//
// External dependencies (palette, color utilities, persistence) are wired by
// initGraph(deps) — graph.js doesn't import from aimdo_viz.js so the dependency
// graph stays one-way (main → graph).

let C = null;
let hexToRgb = null;
let hexToRgba = null;
let saveState = null;
let _t = null;

export function initGraph(deps) {
    C = deps.C;
    hexToRgb = deps.hexToRgb;
    hexToRgba = deps.hexToRgba;
    saveState = deps.saveState;
    _t = deps._t || ((k) => k);
}

export const GRAPH_POINTS = 120;          // visible window size on the canvas
export const HISTORY_BUFFER = 1200;       // total points retained for scrollback (~20 min @ 1s)
export const HISTORY_TICK_MS = 1000;      // min interval between history snapshots
const EXEC_EVENTS_MAX = 200;
const EXEC_NOOP_MS = 1500;                // start→end shorter than this is treated as a no-op
const HISTORY_DB_NAME = "aimdo_viz";
const HISTORY_DB_VERSION = 1;
const HISTORY_STORE = "kv";
const HISTORY_KEY = "history";
const HISTORY_SCHEMA = 1;                 // bump when the stored record shape changes
const GPU_SMOOTH_WINDOW = 3;

// Mutable graph state. Both main and graph mutate via property assignment so
// `let` exports' read-only semantics don't get in the way.
export const graphState = {
    gpuLineVisible: true,
    graphStyle: "area",                   // "area" | "dots" | "ticker" | "bars"
    graphVramColor: null,                 // null = use theme C.vram; otherwise hex override
    graphTotalColor: null,                // null = use theme C.totalLine; otherwise hex override
    graphTotalSmoothness: 0,              // 0 = raw, larger = wider moving-average window radius
};

export const history = {
    torch_active: new Float64Array(HISTORY_BUFFER),
    aimdo_usage: new Float64Array(HISTORY_BUFFER),
    free_vram: new Float64Array(HISTORY_BUFFER),
    gpu_util: new Float64Array(HISTORY_BUFFER),
    times: new Float64Array(HISTORY_BUFFER),
    total_vram: 1,
    head: 0,
    len: 0,
    pushCount: 0,                         // monotonic total pushes; absolute sample id
    viewOffset: 0,                        // points back from newest; 0 = right edge (live)
    followLive: true,
    execEvents: [],                       // {type: "start"|"end", time: ms}
};

// hover-line state for the graph; null when cursor is outside the data range.
export const graphHover = { x: null, idx: null };

const gpuRawBuf = [];
export function smoothGpuUtil(raw) {
    // NVML util frequently dips to 0 mid-workload; peak-hold preserves real peaks.
    if (raw == null) {
        gpuRawBuf.length = 0;
        return null;
    }
    gpuRawBuf.push(raw);
    if (gpuRawBuf.length > GPU_SMOOTH_WINDOW) gpuRawBuf.shift();
    let m = 0;
    for (const v of gpuRawBuf) if (v > m) m = v;
    return m;
}

export function pushExecEvent(type) {
    if (type === "end" && history.execEvents.length > 0) {
        const last = history.execEvents[history.execEvents.length - 1];
        if (last.type === "start" && Date.now() - last.time < EXEC_NOOP_MS) {
            history.execEvents.pop();
            return;
        }
    }
    history.execEvents.push({ type, time: Date.now() });
    if (history.execEvents.length > EXEC_EVENTS_MAX) {
        history.execEvents.splice(0, history.execEvents.length - EXEC_EVENTS_MAX);
    }
}

export function pushHistory(data) {
    history.total_vram = data.total_vram;
    const i = history.head;
    // store non-overlapping values matching the bar logic
    if (data.aimdo_usage > 0) {
        history.aimdo_usage[i] = data.aimdo_usage;
        history.torch_active[i] = 0;
    } else {
        history.aimdo_usage[i] = 0;
        history.torch_active[i] = data.torch_active;
    }
    history.free_vram[i] = data.free_vram;
    history.gpu_util[i] = data.gpu_util != null ? data.gpu_util : 0;
    history.times[i] = Date.now();
    history.head = (i + 1) % HISTORY_BUFFER;
    if (history.len < HISTORY_BUFFER) history.len++;
    history.pushCount++;
    // when scrolled back, advance viewOffset so the user's pinned window keeps
    // showing the same chronological data instead of sliding with new points.
    if (!history.followLive) {
        const maxOffset = Math.max(0, history.len - GRAPH_POINTS);
        history.viewOffset = Math.min(maxOffset, history.viewOffset + 1);
    }
}

export function historyGet(arr, idx) {
    // idx 0 = oldest valid, idx len-1 = newest
    return arr[(history.head - history.len + idx + HISTORY_BUFFER) % HISTORY_BUFFER];
}

export function resetHistoryState() {
    history.head = 0;
    history.len = 0;
    history.pushCount = 0;
    history.viewOffset = 0;
    history.followLive = true;
    history.torch_active.fill(0);
    history.aimdo_usage.fill(0);
    history.free_vram.fill(0);
    history.gpu_util.fill(0);
    history.times.fill(0);
    history.execEvents.length = 0;
}

let _dbPromise = null;
function openHistoryDb() {
    if (_dbPromise) return _dbPromise;
    _dbPromise = new Promise((resolve, reject) => {
        const req = indexedDB.open(HISTORY_DB_NAME, HISTORY_DB_VERSION);
        req.onupgradeneeded = () => req.result.createObjectStore(HISTORY_STORE);
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
    });
    _dbPromise.catch(() => { _dbPromise = null; });  // allow retry after open failure
    return _dbPromise;
}

// cleanup the localStorage key for users upgrading from the previous version.
try { localStorage.removeItem("aimdo_viz_history"); } catch {}

export async function saveHistory() {
    if (history.len === 0) return;
    try {
        const db = await openHistoryDb();
        db.transaction(HISTORY_STORE, "readwrite").objectStore(HISTORY_STORE).put({
            v: HISTORY_SCHEMA,
            head: history.head,
            len: history.len,
            buffer_size: HISTORY_BUFFER,
            total_vram: history.total_vram,
            times: history.times,
            torch_active: history.torch_active,
            aimdo_usage: history.aimdo_usage,
            free_vram: history.free_vram,
            gpu_util: history.gpu_util,
            execEvents: history.execEvents,
        }, HISTORY_KEY);
    } catch (err) {
        if (!saveHistory._warned) {
            saveHistory._warned = true;
            console.warn("aimdo-viz: history save failed", err);
        }
    }
}

export async function clearHistoryStorage() {
    try {
        const db = await openHistoryDb();
        db.transaction(HISTORY_STORE, "readwrite").objectStore(HISTORY_STORE).delete(HISTORY_KEY);
    } catch (err) { console.warn("aimdo-viz: history clear failed", err); }
}

export async function loadHistory() {
    try {
        const db = await openHistoryDb();
        const data = await new Promise((resolve, reject) => {
            const req = db.transaction(HISTORY_STORE, "readonly").objectStore(HISTORY_STORE).get(HISTORY_KEY);
            req.onsuccess = () => resolve(req.result);
            req.onerror = () => reject(req.error);
        });
        if (!data || data.v !== HISTORY_SCHEMA || typeof data.len !== "number") return;
        if (!data.times || data.times.length !== HISTORY_BUFFER) return;
        const copy = (target, source) => { if (source) target.set(source); };
        history.total_vram = data.total_vram || 1;
        copy(history.times, data.times);
        copy(history.torch_active, data.torch_active);
        copy(history.aimdo_usage, data.aimdo_usage);
        copy(history.free_vram, data.free_vram);
        copy(history.gpu_util, data.gpu_util);
        history.len = Math.min(data.len, HISTORY_BUFFER);
        history.head = (typeof data.head === "number" ? data.head : history.len) % HISTORY_BUFFER;
        history.pushCount = history.len;
        if (Array.isArray(data.execEvents)) history.execEvents = data.execEvents.slice(-EXEC_EVENTS_MAX);
    } catch (err) { console.warn("aimdo-viz: history load failed", err); }
}

export function loadGraphSavedState(saved) {
    if (typeof saved.gpuLineVisible === "boolean") graphState.gpuLineVisible = saved.gpuLineVisible;
    if (typeof saved.graphStyle === "string") graphState.graphStyle = saved.graphStyle;
    if (typeof saved.graphVramColor === "string") graphState.graphVramColor = saved.graphVramColor;
    if (typeof saved.graphTotalColor === "string") graphState.graphTotalColor = saved.graphTotalColor;
    if (typeof saved.graphTotalSmoothness === "number") {
        graphState.graphTotalSmoothness = Math.max(0, Math.min(20, saved.graphTotalSmoothness | 0));
    }
}

export function drawGraph(ctx, w, h) {
    const total = history.total_vram;
    const len = history.len;
    if (len < 2) return;

    const visible = Math.min(GRAPH_POINTS, len - history.viewOffset);
    if (visible < 2) return;
    const startIdx = len - visible - history.viewOffset;

    ctx.clearRect(0, 0, w, h);

    ctx.strokeStyle = C.gridLine;
    ctx.lineWidth = 1;
    for (const pct of [0.25, 0.5, 0.75]) {
        const y = Math.round(h - h * pct) + 0.5;
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(w, y);
        ctx.stroke();
    }

    const stepX = w / (GRAPH_POINTS - 1);
    const yFor = val => h - (val / total) * h;
    const dataStartX = (GRAPH_POINTS - visible) * stepX;
    const xFor = i => (GRAPH_POINTS - visible + i) * stepX;
    const at = (arr, i) => historyGet(arr, startIdx + i);

    // smoothed total-used values, precomputed once per frame and shared by the total
    // line, dots, and area-"other" layer so dots/areas stay at-or-below the line.
    const smoothN = graphState.graphTotalSmoothness;
    const totalValues = new Float64Array(visible);
    for (let i = 0; i < visible; i++) totalValues[i] = total - at(history.free_vram, i);
    let smoothedValues;
    if (smoothN > 0 && visible > 0) {
        smoothedValues = new Float64Array(visible);
        let sum = 0, count = 0;
        const initEnd = Math.min(visible - 1, smoothN);
        for (let k = 0; k <= initEnd; k++) { sum += totalValues[k]; count++; }
        smoothedValues[0] = sum / count;
        for (let i = 1; i < visible; i++) {
            const add = i + smoothN;
            const drop = i - smoothN - 1;
            if (add < visible) { sum += totalValues[add]; count++; }
            if (drop >= 0) { sum -= totalValues[drop]; count--; }
            smoothedValues[i] = sum / count;
        }
    } else {
        smoothedValues = totalValues;
    }
    const valueAt = (i) => smoothedValues[i];

    const style = graphState.graphStyle;
    const vramHex = graphState.graphVramColor || C.vram;
    if (style === "area") {
        ctx.beginPath();
        ctx.moveTo(dataStartX, h);
        for (let i = 0; i < visible; i++) {
            ctx.lineTo(xFor(i), yFor(at(history.aimdo_usage, i)));
        }
        ctx.lineTo(xFor(visible - 1), h);
        ctx.closePath();
        ctx.fillStyle = hexToRgba(vramHex, 0.35);
        ctx.fill();

        ctx.beginPath();
        ctx.moveTo(dataStartX, yFor(at(history.aimdo_usage, 0)));
        for (let i = 0; i < visible; i++) {
            ctx.lineTo(xFor(i), yFor(at(history.aimdo_usage, i) + at(history.torch_active, i)));
        }
        for (let i = visible - 1; i >= 0; i--) {
            ctx.lineTo(xFor(i), yFor(at(history.aimdo_usage, i)));
        }
        ctx.closePath();
        ctx.fillStyle = hexToRgba(C.torch, 0.4);
        ctx.fill();

        const stackTop = (i) => at(history.aimdo_usage, i) + at(history.torch_active, i);
        const topFor = (i) => Math.max(stackTop(i), valueAt(i));
        ctx.beginPath();
        ctx.moveTo(dataStartX, yFor(stackTop(0)));
        for (let i = 0; i < visible; i++) {
            ctx.lineTo(xFor(i), yFor(topFor(i)));
        }
        for (let i = visible - 1; i >= 0; i--) {
            ctx.lineTo(xFor(i), yFor(stackTop(i)));
        }
        ctx.closePath();
        ctx.fillStyle = hexToRgba(C.other, 0.4);
        ctx.fill();
    } else if (style === "bars") {
        const groupSize = 3;
        const barStep = stepX * groupSize;
        const barW = Math.max(4, barStep - 4);
        ctx.fillStyle = hexToRgba(vramHex, 0.55);
        const newestAbs = history.pushCount - 1 - history.viewOffset;
        const oldestAbs = newestAbs - visible + 1;
        const firstGroupAbs = Math.floor(oldestAbs / groupSize) * groupSize;
        const lastGroupAbs = Math.floor(newestAbs / groupSize) * groupSize;
        for (let absG = firstGroupAbs; absG <= lastGroupAbs; absG += groupSize) {
            const sStart = Math.max(absG, oldestAbs);
            const sEnd = Math.min(absG + groupSize - 1, newestAbs);
            let peak = 0;
            for (let a = sStart; a <= sEnd; a++) {
                const v = total - at(history.free_vram, a - oldestAbs);
                if (v > peak) peak = v;
            }
            const centerRel = (absG - oldestAbs) + (groupSize - 1) / 2;
            const cx = xFor(centerRel);
            const y = yFor(peak);
            ctx.fillRect(cx - barW / 2, y, barW, h - y);
        }
    } else if (style === "ticker") {
        const groupSize = 3;
        const candleStep = stepX * groupSize;
        const barW = Math.max(5, candleStep - 3);
        const up = "#10b981";
        const down = "#ef4444";
        const newestAbs = history.pushCount - 1 - history.viewOffset;
        const oldestAbs = newestAbs - visible + 1;
        const firstGroupAbs = Math.floor(oldestAbs / groupSize) * groupSize;
        const lastGroupAbs = Math.floor(newestAbs / groupSize) * groupSize;
        ctx.lineWidth = 1;
        for (let absG = firstGroupAbs; absG <= lastGroupAbs; absG += groupSize) {
            const sStart = Math.max(absG, oldestAbs);
            const sEnd = Math.min(absG + groupSize - 1, newestAbs);
            const oRel = sStart - oldestAbs;
            const cRel = sEnd - oldestAbs;
            const o = total - at(history.free_vram, oRel);
            const c = total - at(history.free_vram, cRel);
            const hiLoStartRel = Math.max(0, oRel - 1);
            const hiLoEndRel = Math.min(visible - 1, cRel + 1);
            let hi = o, lo = o;
            for (let rel = hiLoStartRel; rel <= hiLoEndRel; rel++) {
                const v = total - at(history.free_vram, rel);
                if (v > hi) hi = v;
                if (v < lo) lo = v;
            }
            const yO = yFor(o), yC = yFor(c);
            const yTop = Math.min(yO, yC);
            const bodyH = Math.max(1, Math.abs(yC - yO));
            const centerRel = (absG - oldestAbs) + (groupSize - 1) / 2;
            const cx = xFor(centerRel);
            const isUp = c >= o;
            const color = isUp ? up : down;
            const yBot = yTop + bodyH;
            ctx.strokeStyle = color;
            const wickX = Math.round(cx) + 0.5;
            const yHi = yFor(hi);
            const yLo = yFor(lo);
            if (yHi < yTop) {
                ctx.beginPath();
                ctx.moveTo(wickX, yHi);
                ctx.lineTo(wickX, yTop);
                ctx.stroke();
            }
            if (yLo > yBot) {
                ctx.beginPath();
                ctx.moveTo(wickX, yBot);
                ctx.lineTo(wickX, yLo);
                ctx.stroke();
            }
            const bx = Math.round(cx - barW / 2);
            if (isUp) {
                ctx.strokeRect(bx + 0.5, Math.round(yTop) + 0.5, barW - 1, bodyH);
            } else {
                ctx.fillStyle = color;
                ctx.fillRect(bx, Math.round(yTop), barW, bodyH);
            }
        }
    } else if (style === "dots") {
        const dotR = 1;
        const dotStep = 8;
        const colStep = 2;
        const [r, g, b] = hexToRgb(vramHex);
        for (let y = 0; y < h; y += dotStep) {
            const f = 1 - y / h;
            ctx.fillStyle = `rgba(${r},${g},${b},${(0.15 + 0.65 * f).toFixed(3)})`;
            ctx.beginPath();
            for (let i = 0; i < visible; i += colStep) {
                if (y < yFor(valueAt(i))) continue;
                const x = xFor(i);
                ctx.moveTo(x + dotR, y);
                ctx.arc(x, y, dotR, 0, Math.PI * 2);
            }
            ctx.fill();
        }
    }

    // total used line — ticker already encodes the value in each candle's edge,
    // so skip the line to avoid overlapping the bars.
    if (style !== "ticker") {
        ctx.beginPath();
        ctx.strokeStyle = graphState.graphTotalColor || C.totalLine;
        ctx.lineWidth = 1.5;
        ctx.lineJoin = "round";
        ctx.lineCap = "round";
        if (smoothN > 0 && visible >= 3) {
            const xs = new Float64Array(visible);
            const ys = new Float64Array(visible);
            for (let i = 0; i < visible; i++) { xs[i] = xFor(i); ys[i] = yFor(valueAt(i)); }
            ctx.moveTo(xs[0], ys[0]);
            for (let i = 1; i < visible - 1; i++) {
                const mx = (xs[i] + xs[i + 1]) / 2;
                const my = (ys[i] + ys[i + 1]) / 2;
                ctx.quadraticCurveTo(xs[i], ys[i], mx, my);
            }
            ctx.lineTo(xs[visible - 1], ys[visible - 1]);
        } else {
            for (let i = 0; i < visible; i++) {
                const x = xFor(i);
                const y = yFor(valueAt(i));
                if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
            }
        }
        ctx.stroke();
    }

    // capacity line
    ctx.strokeStyle = C.capLine;
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(0, yFor(total));
    ctx.lineTo(w, yFor(total));
    ctx.stroke();
    ctx.setLineDash([]);

    // exec start/end markers — positioned by interpolating each event's time into the
    // visible sample times array, so markers stay glued to the data during scrubbing
    // even if pollInterval drifts between ticks.
    if (history.execEvents.length) {
        const sampleTimes = new Float64Array(visible);
        for (let i = 0; i < visible; i++) sampleTimes[i] = historyGet(history.times, startIdx + i);
        const tFirst = sampleTimes[0];
        const tLast = sampleTimes[visible - 1];
        ctx.lineWidth = 1;
        ctx.setLineDash([2, 3]);
        for (const evt of history.execEvents) {
            if (evt.time < tFirst || evt.time > tLast) continue;
            let lo = 0, hi = visible - 1;
            while (lo < hi) {
                const mid = (lo + hi + 1) >> 1;
                if (sampleTimes[mid] <= evt.time) lo = mid; else hi = mid - 1;
            }
            const tA = sampleTimes[lo];
            const tB = lo < visible - 1 ? sampleTimes[lo + 1] : tA;
            const frac = tB > tA ? (evt.time - tA) / (tB - tA) : 0;
            const x = xFor(lo + frac);
            ctx.strokeStyle = evt.type === "start" ? C.torch : C.gpuUtilHi;
            ctx.beginPath();
            ctx.moveTo(x + 0.5, 0);
            ctx.lineTo(x + 0.5, h);
            ctx.stroke();
        }
        ctx.setLineDash([]);
    }

    // gpu line uses its own 0..100 scale, not the VRAM byte scale
    if (graphState.gpuLineVisible) {
        ctx.beginPath();
        ctx.strokeStyle = C.gpuUtil;
        ctx.lineWidth = 1.25;
        for (let i = 0; i < visible; i++) {
            const y = h - (at(history.gpu_util, i) / 100) * h;
            if (i === 0) ctx.moveTo(xFor(i), y); else ctx.lineTo(xFor(i), y);
        }
        ctx.stroke();
    }

    if (graphHover.x != null && graphHover.idx != null) {
        const hi = graphHover.idx - startIdx;
        if (hi >= 0 && hi < visible) {
            ctx.strokeStyle = C.vram;
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(graphHover.x + 0.5, 0);
            ctx.lineTo(graphHover.x + 0.5, h);
            ctx.stroke();

            const dot = (x, y, fill) => {
                ctx.beginPath();
                ctx.arc(x, y, 3, 0, Math.PI * 2);
                ctx.fillStyle = fill;
                ctx.fill();
                ctx.lineWidth = 1.5;
                ctx.strokeStyle = C.graphBg;
                ctx.stroke();
            };
            const totalY = yFor(total - at(history.free_vram, hi));
            dot(graphHover.x, totalY, C.totalLine);
            if (graphState.gpuLineVisible) {
                const gpuY = h - (at(history.gpu_util, hi) / 100) * h;
                dot(graphHover.x, gpuY, C.gpuUtil);
            }
        }
    }
}

// Build the "Graph" submenu (style + colors + smoothness). The caller passes the
// submenu container + a redraw callback that's tied to the active panel instance.
export function buildGraphSubmenu(submenu, redrawGraph) {
    const graphStyles = [
        { key: "area",   label: _t("graphArea") },
        { key: "bars",   label: _t("graphBars") },
        { key: "ticker", label: _t("graphTicker") },
        { key: "dots",   label: _t("graphDots") },
    ];
    const items = new Map();
    function renderItems() {
        for (const [k, item] of items) {
            const on = k === graphState.graphStyle;
            const label = graphStyles.find(s => s.key === k).label;
            item.innerHTML = `<span class="aimdo-check">${on ? "✓" : ""}</span>${label}`;
        }
    }
    for (const s of graphStyles) {
        const item = document.createElement("div");
        item.className = "aimdo-menu-item";
        item.addEventListener("click", (e) => {
            e.stopPropagation();
            graphState.graphStyle = s.key;
            saveState({ graphStyle: s.key });
            renderItems();
            redrawGraph();
        });
        submenu.appendChild(item);
        items.set(s.key, item);
    }
    renderItems();

    // VRAM color picker
    const colorRow = document.createElement("div");
    colorRow.style.cssText = `padding:6px 10px;display:flex;align-items:center;gap:8px;font-size:0.917em;`;
    colorRow.addEventListener("click", (e) => e.stopPropagation());
    const colorInput = document.createElement("input");
    colorInput.type = "color";
    colorInput.value = graphState.graphVramColor || C.vram;
    colorInput.style.cssText = `width:24px;height:18px;padding:0;border:none;background:transparent;cursor:pointer;`;
    colorInput.addEventListener("input", () => {
        graphState.graphVramColor = colorInput.value;
        saveState({ graphVramColor: colorInput.value });
        redrawGraph();
    });
    const resetColor = document.createElement("span");
    resetColor.textContent = _t("reset");
    resetColor.style.cssText = `margin-left:auto;color:var(--aimdo-textDim);cursor:pointer;font-size:0.833em;`;
    resetColor.addEventListener("click", () => {
        graphState.graphVramColor = null;
        saveState({ graphVramColor: null });
        colorInput.value = C.vram;
        redrawGraph();
    });
    colorRow.appendChild(colorInput);
    colorRow.appendChild(document.createTextNode(_t("vramColor")));
    colorRow.appendChild(resetColor);
    submenu.appendChild(colorRow);

    // Total-line color picker
    const totalColorRow = document.createElement("div");
    totalColorRow.style.cssText = colorRow.style.cssText;
    totalColorRow.addEventListener("click", (e) => e.stopPropagation());
    const totalColorInput = document.createElement("input");
    totalColorInput.type = "color";
    totalColorInput.value = graphState.graphTotalColor || C.totalLine;
    totalColorInput.style.cssText = colorInput.style.cssText;
    totalColorInput.addEventListener("input", () => {
        graphState.graphTotalColor = totalColorInput.value;
        saveState({ graphTotalColor: totalColorInput.value });
        redrawGraph();
    });
    const resetTotalColor = document.createElement("span");
    resetTotalColor.textContent = _t("reset");
    resetTotalColor.style.cssText = resetColor.style.cssText;
    resetTotalColor.addEventListener("click", () => {
        graphState.graphTotalColor = null;
        saveState({ graphTotalColor: null });
        totalColorInput.value = C.totalLine;
        redrawGraph();
    });
    totalColorRow.appendChild(totalColorInput);
    totalColorRow.appendChild(document.createTextNode(_t("totalColor")));
    totalColorRow.appendChild(resetTotalColor);
    submenu.appendChild(totalColorRow);

    // Total-line smoothness slider
    const smoothRow = document.createElement("div");
    smoothRow.style.cssText = `padding:6px 10px;display:flex;flex-direction:column;gap:4px;min-width:180px;font-size:0.833em;`;
    smoothRow.addEventListener("click", (e) => e.stopPropagation());
    const smoothLabel = document.createElement("div");
    smoothLabel.style.cssText = `display:flex;justify-content:space-between;color:var(--aimdo-textDim);`;
    smoothLabel.innerHTML = `<span>${_t("smoothness")}</span><span class="aimdo-sm-val">${graphState.graphTotalSmoothness}</span>`;
    const smoothSlider = document.createElement("input");
    smoothSlider.type = "range";
    smoothSlider.min = "0";
    smoothSlider.max = "20";
    smoothSlider.step = "1";
    smoothSlider.value = String(graphState.graphTotalSmoothness);
    smoothSlider.style.cssText = `width:100%;accent-color:var(--aimdo-vram);cursor:pointer;`;
    const smoothValSpan = smoothLabel.querySelector(".aimdo-sm-val");
    smoothSlider.addEventListener("input", () => {
        graphState.graphTotalSmoothness = parseInt(smoothSlider.value, 10);
        smoothValSpan.textContent = String(graphState.graphTotalSmoothness);
        saveState({ graphTotalSmoothness: graphState.graphTotalSmoothness });
        redrawGraph();
    });
    smoothRow.appendChild(smoothLabel);
    smoothRow.appendChild(smoothSlider);
    submenu.appendChild(smoothRow);
}
