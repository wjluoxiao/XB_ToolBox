import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// ============================================================
// XB_DigitalHumanParams_Single — 数字人参数调节（单人）
// 融合 视频参数大全 + 音频切片V1 的 UI 交互
// ============================================================

const PAD = 10, HANDLE_HIT = 12;
const isZH = navigator.language.startsWith("zh");

const xb_dispatch = (w, val) => {
    if (w.inputEl) {
        w.inputEl.value = val;
        w.inputEl.dispatchEvent(new Event("input", { bubbles: true }));
    } else if (w.element) {
        w.element.value = val;
        w.element.dispatchEvent(new Event("input", { bubbles: true }));
    } else if (w.callback) {
        w.callback(val);
    }
};

app.registerExtension({
    name: "XB_ToolBox.DigitalHumanParams_Single",

    // —— nodeCreated：画幅联动 + 音频上传 + 波形可视化 ——
    async nodeCreated(node) {
        if (node.comfyClass !== "XB_DigitalHumanParams_Single") return;

        // ── 控件引用 ──
        const wR = node.widgets?.find(w => w.name === "aspect_ratio");
        const wW = node.widgets?.find(w => w.name === "width");
        const wH = node.widgets?.find(w => w.name === "height");
        const wF = node.widgets?.find(w => w.name === "fps");
        const wFF = node.widgets?.find(w => w.name === "fps_float");
        const wAudio = node.widgets?.find(w => w.name === "audio");
        const wStart = node.widgets?.find(w => w.name === "start_time");
        const wEnd = node.widgets?.find(w => w.name === "end_time");
        const wDur = node.widgets?.find(w => w.name === "duration_display");

        // ── 画幅联动（来自 xb_video.js）──
        if (wR && wW && wH) {
            node._xb_syncing = false;
            const rS = { "1:1": 1, "16:9": 16 / 9, "9:16": 9 / 16, "4:3": 4 / 3, "3:4": 3 / 4, "21:9": 21 / 9 };
            const rL = { "16:9 (LTX)": 16 / 9, "9:16 (LTX)": 9 / 16, "4:3 (LTX)": 4 / 3, "3:4 (LTX)": 3 / 4 };

            const sW = () => {
                if (node._xb_syncing || node._xb_from_polling) return;
                const r = wR.value; if (r.includes("Free")) return;
                const isL = r.includes("(LTX)"); const rm = isL ? rL : rS; const cr = rm[r]; if (!cr) return;
                const s = isL ? 32 : 16;
                let w = Math.round((parseInt(wW.value, 10) || s) / s) * s; w = Math.max(s, w);
                let h = Math.round((w / cr) / s) * s; h = Math.max(s, h);
                if (h !== parseInt(wH.value, 10)) { node._xb_syncing = true; wH.value = h; xb_dispatch(wH, h); node._xb_syncing = false; }
            };
            const sH = () => {
                if (node._xb_syncing || node._xb_from_polling) return;
                const r = wR.value; if (r.includes("Free")) return;
                const isL = r.includes("(LTX)"); const rm = isL ? rL : rS; const cr = rm[r]; if (!cr) return;
                const s = isL ? 32 : 16;
                let h = Math.round((parseInt(wH.value, 10) || s) / s) * s; h = Math.max(s, h);
                let w = Math.round((h * cr) / s) * s; w = Math.max(s, w);
                if (w !== parseInt(wW.value, 10)) { node._xb_syncing = true; wW.value = w; xb_dispatch(wW, w); node._xb_syncing = false; }
            };

            const oc = wR.callback; wR.callback = function (v) { if (oc) oc.apply(this, arguments); if (node._xb_from_polling) return; sW(); };
            const ow = wW.callback; wW.callback = function (v) { if (ow) ow.apply(this, arguments); sW(); };
            const oh = wH.callback; wH.callback = function (v) { if (oh) oh.apply(this, arguments); sH(); };
        }

        // ── 帧率联动 ──
        if (wF && wFF) {
            const of = wF.callback; wF.callback = function (v) { if (of) of.apply(this, arguments); if (node._xb_syncing || node._xb_from_polling) return; const val = Math.round(Number(v)); if (wFF.value !== val) { node._xb_syncing = true; wFF.value = val; xb_dispatch(wFF, val); node._xb_syncing = false; } };
            const off = wFF.callback; wFF.callback = function (v) { if (off) off.apply(this, arguments); if (node._xb_syncing || node._xb_from_polling) return; const val = Math.round(Number(v)); if (wF.value !== val) { node._xb_syncing = true; wF.value = val; xb_dispatch(wF, val); node._xb_syncing = false; } };
        }

        // ── duration_display 样式 ──
        if (wDur) {
            setTimeout(() => {
                const el = wDur.inputEl || wDur.element;
                if (el) {
                    el.readOnly = true;
                    el.style.cssText = "background-color:#1a1a1a;color:#00E676;text-align:center;font-weight:bold;font-size:15px;min-width:120px;white-space:nowrap;overflow:hidden;";
                }
            }, 100);
        }

        // ── 音频上传按钮（来自 xb_audio_slicer_v1.js）──
        if (wAudio) {
            const fi = document.createElement("input");
            fi.type = "file"; fi.accept = "audio/*,video/*"; fi.style.display = "none";
            fi.onchange = async () => {
                if (!fi.files.length) return;
                const body = new FormData(); body.append("image", fi.files[0]);
                const resp = await api.fetchApi("/upload/image", { method: "POST", body });
                if (resp.status === 200) {
                    const d = await resp.json(); const n = d.name || fi.files[0].name;
                    if (!wAudio.options.values.includes(n)) wAudio.options.values.push(n);
                    wAudio.value = n; if (wAudio.callback) wAudio.callback(n);
                }
            };
            document.body.appendChild(fi);
            const btn = node.addWidget("button", "选择音频上传", "image", () => { app.canvas.node_widget = null; fi.click(); });
            btn.options.serialize = false;
            const o1 = node.onRemoved; node.onRemoved = () => { fi?.remove(); o1?.apply(node); };
        }

        // ── 波形可视化 UI（来自 xb_audio_slicer_v1.js）──
        const ctr = document.createElement("div");
        Object.assign(ctr.style, { display: "flex", flexDirection: "column", gap: "6px", width: "100%", padding: "6px", boxSizing: "border-box", background: "#161616", borderRadius: "6px", color: "#ccc", fontFamily: "sans-serif", marginTop: "4px" });

        const audioEl = document.createElement("audio");
        audioEl.controls = true; audioEl.style.cssText = "width:100%;height:34px;outline:none;";
        ctr.appendChild(audioEl);

        const canvas = document.createElement("canvas");
        canvas.style.cssText = "width:100%;height:40px;border-radius:4px;background:#111;cursor:pointer;display:block;";
        const dpr = window.devicePixelRatio || 1;
        canvas.width = 1200 * dpr; canvas.height = 80 * dpr;
        ctr.appendChild(canvas);

        const domWidget = node.addDOMWidget("xb_dh_single_ui", "custom", ctr);
        domWidget.computeSize = () => [node.size[0] - 16, 100];
        if (node.size[1] < 320) node.size[1] = 320;

        let totalDur = 0, _lastFile = null, _pausing = false;
        let peaks = null, drag = null;

        const getDur = () => totalDur || 10;
        const getS = () => parseFloat(wStart?.value) || 0;
        const getE = () => { const e = parseFloat(wEnd?.value); return e > 0 ? e : getDur(); };
        const mouseToCanvasX = (clientX) => { const rect = canvas.getBoundingClientRect(); return (clientX - rect.left) * (canvas.width / rect.width); };

        const syncWidgets = () => {
            let s = getS(), e = getE();
            const fps = parseFloat(wF?.value) || 25, fDur = 1.0 / fps;
            if (e < s + fDur) e = s + fDur;
            const dur = getDur(); if (e > dur) e = dur;
            if (wStart.value !== s) { wStart.value = s; if (wStart.inputEl) wStart.inputEl.value = s; if (wStart.element) wStart.element.value = s; }
            if (wEnd.value !== e) { wEnd.value = e; if (wEnd.inputEl) wEnd.inputEl.value = e; if (wEnd.element) wEnd.element.value = e; }
            if (wDur) {
                const durSec = Math.max(0, e - s);
                const frames = Math.max(1, Math.floor((Math.round(durSec * fps) + 2) / 4) * 4 + 1);
                const txt = frames + " 帧 (" + durSec.toFixed(2) + "s)";
                if (wDur.value !== txt) { wDur.value = txt; if (wDur.inputEl) wDur.inputEl.value = txt; if (wDur.element) wDur.element.value = txt; }
            }
        };

        const visMapper = () => {
            const dur = getDur(), s = getS(), e = getE(), selW = (e - s) || 0.01;
            const sVis = Math.max(0, s - 0.125 * selW), eVis = Math.min(dur, e + 0.125 * selW);
            const visW = (eVis - sVis) || 0.01, wwCSS = (canvas.width / dpr) - PAD * 2;
            return { sVis, eVis, visW, wwCSS, toCSS: (time) => PAD + ((time - sVis) / visW) * wwCSS, toTime: (cssX) => sVis + ((cssX - PAD) / wwCSS) * visW };
        };

        const draw = () => {
            const ctx = canvas.getContext("2d"), w = canvas.width, h = canvas.height;
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
            const W = w / dpr, H = h / dpr;
            ctx.clearRect(0, 0, W, H); ctx.fillStyle = "#111"; ctx.fillRect(0, 0, W, H);

            const dur = getDur(), s = getS(), e = getE(), vm = visMapper(), ww = vm.wwCSS, mid = H / 2;

            if (peaks && peaks.length > 1) {
                const startIdx = Math.max(0, Math.floor((vm.sVis / dur) * peaks.length));
                const endIdx = Math.min(peaks.length - 1, Math.ceil((vm.eVis / dur) * peaks.length));
                const vp = peaks.slice(startIdx, endIdx + 1);
                if (vp.length > 1) {
                    const DISPLAY_POINTS = Math.min(1000, Math.floor(ww * 1.5));
                    let maxPoints = [], minPoints = [];
                    const step = vp.length / DISPLAY_POINTS;
                    for (let i = 0; i < DISPLAY_POINTS; i++) {
                        const idx = i * step, lo = Math.floor(idx), hi = Math.min(lo + 1, vp.length - 1), frac = idx - lo;
                        maxPoints.push(vp[lo][0] * (1 - frac) + vp[hi][0] * frac); minPoints.push(vp[lo][1] * (1 - frac) + vp[hi][1] * frac);
                    }
                    const absMax = Math.max(Math.max(...maxPoints, 0.001), Math.abs(Math.min(...minPoints, -0.001)));
                    const scale = (v) => (v / absMax) * (H * 0.48);

                    const pathActive = new Path2D(), pathInactive = new Path2D();
                    pathActive.moveTo(PAD, mid); pathInactive.moveTo(PAD, mid);
                    for (let i = 0; i < DISPLAY_POINTS; i++) {
                        const x = PAD + (i / (DISPLAY_POINTS - 1)) * ww, tAt = vm.sVis + (i / (DISPLAY_POINTS - 1)) * vm.visW;
                        if (tAt >= s && tAt <= e) pathActive.lineTo(x, mid - scale(maxPoints[i])); else pathInactive.lineTo(x, mid - scale(maxPoints[i]));
                    }
                    for (let i = DISPLAY_POINTS - 1; i >= 0; i--) {
                        const x = PAD + (i / (DISPLAY_POINTS - 1)) * ww, tAt = vm.sVis + (i / (DISPLAY_POINTS - 1)) * vm.visW;
                        if (tAt >= s && tAt <= e) pathActive.lineTo(x, mid - scale(minPoints[i])); else pathInactive.lineTo(x, mid - scale(minPoints[i]));
                    }
                    pathActive.closePath(); pathInactive.closePath();
                    ctx.fillStyle = "rgba(100,100,100,0.3)"; ctx.fill(pathInactive); ctx.fillStyle = "#4FC3F7"; ctx.fill(pathActive);
                }
            }

            let gx = vm.toCSS(s), rx = vm.toCSS(e);
            if (drag && drag.type === "start_line" && typeof drag.tempX === "number") gx = drag.tempX;
            if (drag && drag.type === "end_line" && typeof drag.tempX === "number") rx = drag.tempX;
            if (gx > rx) { const tmp = gx; gx = rx; rx = tmp; }

            ctx.fillStyle = "rgba(0,0,0,0.65)"; ctx.fillRect(PAD, 0, gx - PAD, H); ctx.fillRect(rx, 0, W - PAD - rx, H);
            ctx.fillStyle = "#4CAF50"; ctx.fillRect(gx - 2, 0, 4, H);
            ctx.fillStyle = "#F44336"; ctx.fillRect(rx - 2, 0, 4, H);

            if (audioEl.readyState >= 1 && audioEl.currentTime > 0) {
                const px = vm.toCSS(audioEl.currentTime);
                if (px > PAD && px < W - PAD) { ctx.fillStyle = "#FFF"; ctx.fillRect(px - 1, 0, 2, H); }
            }

            ctx.fillStyle = "#fff"; ctx.font = "bold 11px sans-serif";
            ctx.fillText(s.toFixed(2) + "s", Math.max(PAD + 4, gx - 45), 18);
            const ewt = ctx.measureText(e.toFixed(2) + "s").width;
            ctx.fillText(e.toFixed(2) + "s", Math.min(W - PAD - ewt - 4, rx + 6), 18);
            ctx.setTransform(1, 0, 0, 1, 0, 0);
        };

        // ── 事件引擎 ──
        canvas.onmousedown = (ev) => {
            if (totalDur <= 0) return;
            const mx = mouseToCanvasX(ev.clientX) / dpr, vm = visMapper();
            const sx = vm.toCSS(getS()), ex = vm.toCSS(getE());
            drag = null;
            if (Math.abs(mx - sx) < HANDLE_HIT) { drag = { type: "start_line" }; return; }
            if (Math.abs(mx - ex) < HANDLE_HIT) { drag = { type: "end_line" }; return; }
            const clickTime = vm.toTime(mx);
            if (audioEl.readyState >= 1) audioEl.currentTime = Math.max(0, Math.min(totalDur, clickTime));
        };

        window.addEventListener("mousemove", (ev) => {
            const mx = mouseToCanvasX(ev.clientX) / dpr;
            if (drag) {
                drag.tempX = Math.max(PAD, Math.min(canvas.width / dpr - PAD, mx));
            } else {
                const rect = canvas.getBoundingClientRect();
                if (ev.clientX >= rect.left && ev.clientX <= rect.right && ev.clientY >= rect.top && ev.clientY <= rect.bottom) {
                    const vm = visMapper(), sx = vm.toCSS(getS()), ex = vm.toCSS(getE());
                    canvas.style.cursor = (Math.abs(mx - sx) < HANDLE_HIT || Math.abs(mx - ex) < HANDLE_HIT) ? "ew-resize" : "pointer";
                }
            }
        });

        window.addEventListener("mouseup", () => {
            if (drag && typeof drag.tempX === "number") {
                const vm = visMapper(), newVal = vm.toTime(drag.tempX);
                const fps = parseFloat(wF?.value) || 25, snap = v => Math.round(v * fps) / fps;
                if (drag.type === "start_line") wStart.value = snap(Math.max(0, Math.min(newVal, getE() - 0.1)));
                if (drag.type === "end_line") wEnd.value = snap(Math.min(totalDur, Math.max(newVal, getS() + 0.1)));
                syncWidgets(); if (audioEl.readyState >= 1) audioEl.currentTime = getS();
            }
            drag = null;
        });

        // ── 音频核心逻辑 ──
        const updateSrc = () => { const f = wAudio?.value; if (f && f !== "none" && f !== _lastFile) { _lastFile = f; totalDur = 0; audioEl.src = api.apiURL("/view?" + new URLSearchParams({ filename: f, type: "input", t: Date.now() })); } };
        audioEl.addEventListener("loadedmetadata", () => { totalDur = audioEl.duration; const fps = parseFloat(wF?.value) || 25; const curStart = parseFloat(wStart?.value) || 0; const curEnd = parseFloat(wEnd?.value) || 0; if (curStart === 0 && (curEnd <= 0 || curEnd > totalDur + 1 || Math.abs(curEnd - 10.0) < 0.001)) { wStart.value = 0; wEnd.value = Math.floor(totalDur * fps) / fps; } syncWidgets(); audioEl.currentTime = parseFloat(wStart?.value) || 0; });
        audioEl.addEventListener("play", () => { _pausing = false; const st = getS(), et = getE(); if (audioEl.currentTime < st || audioEl.currentTime >= et) audioEl.currentTime = st; });
        audioEl.addEventListener("timeupdate", () => { if (_pausing) return; if (audioEl.currentTime >= getE()) { _pausing = true; audioEl.pause(); audioEl.currentTime = getS(); setTimeout(() => { _pausing = false; }, 100); } });

        const fetchPeaks = async (filename) => {
            if (!filename || filename === "none") { peaks = null; return; }
            try { const resp = await api.fetchApi("/xb_toolbox/audio_waveform", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ filename, num_peaks: 4000 }) }); if (resp.ok) { const data = await resp.json(); peaks = data.peaks; totalDur = data.duration || 10; } } catch (e) { }
        };

        if (wAudio) { const orig = wAudio.callback; wAudio.callback = function () { orig?.apply(this, arguments); updateSrc(); fetchPeaks(wAudio.value).then(() => { const curStart = parseFloat(wStart?.value) || 0; const curEnd = parseFloat(wEnd?.value) || 0; if (curStart === 0 && (curEnd <= 0 || curEnd > totalDur + 1 || Math.abs(curEnd - 10.0) < 0.001)) { wStart.value = 0; if (totalDur > 0) { const fps = parseFloat(wF?.value) || 25; wEnd.value = Math.floor(totalDur * fps) / fps; } } syncWidgets(); }); }; }
        const onTimeChange = (resetPlayback) => { let s = getS(), e = getE(), dur = getDur(); if (e < s + 0.01) { e = Math.min(s + 0.01, dur); wEnd.value = e; } syncWidgets(); if (resetPlayback && audioEl.readyState >= 1) audioEl.currentTime = s; };
        if (wStart) { const orig = wStart.callback; wStart.callback = function () { orig?.apply(this, arguments); onTimeChange(true); }; }
        if (wEnd) { const orig = wEnd.callback; wEnd.callback = function () { orig?.apply(this, arguments); onTimeChange(false); }; }

        let _running = true;
        const renderLoop = () => { if (!_running) return; if (totalDur > 0) { syncWidgets(); draw(); } requestAnimationFrame(renderLoop); };
        renderLoop();

        setTimeout(() => { updateSrc(); if (wAudio?.value && wAudio.value !== "none") fetchPeaks(wAudio.value); }, 400);
        const o2 = node.onRemoved; node.onRemoved = () => { _running = false; o2?.apply(node); };
    },

    // ── init：轮询更新步长和时长显示（来自 xb_video.js）──
    init() {
        setInterval(() => {
            if (!app.graph || !app.graph._nodes) return;

            for (const node of app.graph._nodes) {
                if (node.comfyClass === "XB_DigitalHumanParams_Single" && node.widgets) {
                    const wRatio = node.widgets.find(w => w.name === "aspect_ratio");
                    const wWidth = node.widgets.find(w => w.name === "width");
                    const wHeight = node.widgets.find(w => w.name === "height");
                    const wFps = node.widgets.find(w => w.name === "fps");
                    const wFpsF = node.widgets.find(w => w.name === "fps_float");
                    const wDur = node.widgets.find(w => w.name === "duration_display");

                    if (wRatio && wWidth && wHeight && wFps && wFpsF) {
                        node._xb_from_polling = true;

                        if (node._xb_last_fps === undefined) {
                            node._xb_last_fps = wFps.value;
                            node._xb_last_fps_float = wFpsF.value;
                            node._xb_last_width = parseInt(wWidth.value, 10) || 480;
                            node._xb_last_height = parseInt(wHeight.value, 10) || 832;
                            node._xb_last_ratio = wRatio.value;
                        }

                        let needsUpdate = false;
                        let valRatio = wRatio.value;
                        let isFree = valRatio.includes("Free");
                        let rChanged = valRatio !== node._xb_last_ratio;
                        let isLTX = valRatio.includes("(LTX)");

                        let currentStep = isFree ? 1 : (isLTX ? 32 : 16);
                        wWidth.options.step = currentStep; wHeight.options.step = currentStep;
                        if (wWidth.inputEl) { wWidth.inputEl.step = currentStep; wWidth.inputEl.setAttribute("step", String(currentStep)); }
                        else if (wWidth.element) { wWidth.element.step = currentStep; wWidth.element.setAttribute("step", String(currentStep)); }
                        if (wHeight.inputEl) { wHeight.inputEl.step = currentStep; wHeight.inputEl.setAttribute("step", String(currentStep)); }
                        else if (wHeight.element) { wHeight.element.step = currentStep; wHeight.element.setAttribute("step", String(currentStep)); }

                        let wid = parseInt(wWidth.value, 10) || currentStep;
                        let hei = parseInt(wHeight.value, 10) || currentStep;
                        let wChanged = wid !== node._xb_last_width;
                        let hChanged = hei !== node._xb_last_height;

                        if (wChanged || hChanged || rChanged) {
                            if (!isFree && !isLTX) {
                                const ratioMap = { "1:1": 1.0, "16:9": 16.0 / 9.0, "9:16": 9.0 / 16.0, "4:3": 4.0 / 3.0, "3:4": 3.0 / 4.0, "21:9": 21.0 / 9.0 };
                                let currentRatio = ratioMap[valRatio];
                                if (wChanged && wid % currentStep !== 0) wid = wid > node._xb_last_width ? Math.ceil(wid / currentStep) * currentStep : Math.floor(wid / currentStep) * currentStep;
                                else wid = Math.round(wid / currentStep) * currentStep;
                                wid = Math.max(currentStep, wid);
                                if (hChanged && hei % currentStep !== 0) hei = hei > node._xb_last_height ? Math.ceil(hei / currentStep) * currentStep : Math.floor(hei / currentStep) * currentStep;
                                else hei = Math.round(hei / currentStep) * currentStep;
                                hei = Math.max(currentStep, hei);
                                if (currentRatio) {
                                    if (rChanged || wChanged) { hei = Math.round((wid / currentRatio) / currentStep) * currentStep; hei = Math.max(currentStep, hei); }
                                    else if (hChanged) { wid = Math.round((hei * currentRatio) / currentStep) * currentStep; wid = Math.max(currentStep, wid); }
                                }
                            } else if (isLTX) {
                                const ratioMap = { "16:9 (LTX)": 16.0 / 9.0, "9:16 (LTX)": 9.0 / 16.0, "4:3 (LTX)": 4.0 / 3.0, "3:4 (LTX)": 3.0 / 4.0 };
                                let currentRatio = ratioMap[valRatio];
                                if (wChanged && wid % currentStep !== 0) wid = wid > node._xb_last_width ? Math.ceil(wid / currentStep) * currentStep : Math.floor(wid / currentStep) * currentStep;
                                else wid = Math.round(wid / currentStep) * currentStep;
                                wid = Math.max(currentStep, wid);
                                if (hChanged && hei % currentStep !== 0) hei = hei > node._xb_last_height ? Math.ceil(hei / currentStep) * currentStep : Math.floor(hei / currentStep) * currentStep;
                                else hei = Math.round(hei / currentStep) * currentStep;
                                hei = Math.max(currentStep, hei);
                                if (currentRatio) {
                                    if (rChanged || wChanged) { hei = Math.round((wid / currentRatio) / currentStep) * currentStep; hei = Math.max(currentStep, hei); }
                                    else if (hChanged) { wid = Math.round((hei * currentRatio) / currentStep) * currentStep; wid = Math.max(currentStep, wid); }
                                }
                            }
                            wWidth.value = wid; wHeight.value = hei;
                            node._xb_last_width = wid; node._xb_last_height = hei;
                            node._xb_last_ratio = valRatio;
                            xb_dispatch(wWidth, wid);
                            xb_dispatch(wHeight, hei);
                            needsUpdate = true;
                        }

                        if (wFps.value !== node._xb_last_fps) {
                            let val = Math.round(Number(wFps.value)); wFps.value = val; wFpsF.value = val;
                            node._xb_last_fps = val; node._xb_last_fps_float = val;
                            xb_dispatch(wFps, val); xb_dispatch(wFpsF, val);
                            needsUpdate = true;
                        } else if (wFpsF.value !== node._xb_last_fps_float) {
                            let val = Math.round(Number(wFpsF.value)); wFps.value = val; wFpsF.value = val;
                            node._xb_last_fps = val; node._xb_last_fps_float = val;
                            xb_dispatch(wFps, val); xb_dispatch(wFpsF, val);
                            needsUpdate = true;
                        }

                        wFpsF.options.precision = 2;

                        if (needsUpdate) app.graph.setDirtyCanvas(true, true);
                        node._xb_from_polling = false;
                    }
                }
            }
        }, 200);
    }
});
