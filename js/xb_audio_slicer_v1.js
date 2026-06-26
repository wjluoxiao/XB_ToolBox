import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// ============================================================
// XB_AudioSlicerV1 — 通用波形 + 边缘拖拽吸附 + 丝滑定位
// ============================================================

const PAD = 10, HANDLE_HIT = 12;

app.registerExtension({
    name: "XB_ToolBox.AudioSlicerV1",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "XB_AudioSlicerV1") return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            if (onNodeCreated) onNodeCreated.apply(this, arguments);
            const node = this;

            const wAudio = node.widgets.find(w => w.name === "audio");
            const wFps   = node.widgets.find(w => w.name === "fps");
            const wStart = node.widgets.find(w => w.name === "start_time");
            const wEnd   = node.widgets.find(w => w.name === "end_time");
            const wDur   = node.widgets.find(w => w.name === "duration_display");

            if (wDur) {
                setTimeout(() => {
                    const el = wDur.inputEl || wDur.element;
                    if (el) {
                        el.readOnly = true;
                        el.style.cssText = "background-color:#1a1a1a;color:#00E676;text-align:center;font-weight:bold;font-size:15px;min-width:120px;white-space:nowrap;overflow:hidden;";
                    }
                }, 100);
            }

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

            const ctr = document.createElement("div");
            Object.assign(ctr.style, { display:"flex", flexDirection:"column", gap:"6px", width:"100%", padding:"6px", boxSizing:"border-box", background:"#161616", borderRadius:"6px", color:"#ccc", fontFamily:"sans-serif", marginTop:"4px" });

            const audioEl = document.createElement("audio");
            audioEl.controls = true; audioEl.style.cssText = "width:100%;height:34px;outline:none;";
            ctr.appendChild(audioEl);

            const canvas = document.createElement("canvas");
            canvas.style.cssText = "width:100%;height:40px;border-radius:4px;background:#111;cursor:pointer;display:block;";
            const dpr = window.devicePixelRatio || 1;
            canvas.width = 1200 * dpr; canvas.height = 80 * dpr;
            ctr.appendChild(canvas);

            const domWidget = node.addDOMWidget("xb2_ui", "custom", ctr);
            domWidget.computeSize = () => [node.size[0] - 16, 100];
            if (node.size[1] < 270) node.size[1] = 270;

            let totalDur = 0, _lastFile = null, _pausing = false;
            let peaks = null, drag = null;

            const getDur = () => totalDur || 10;
            const getS = () => parseFloat(wStart?.value) || 0;
            const getE = () => { const e = parseFloat(wEnd?.value); return e > 0 ? e : getDur(); };
            const mouseToCanvasX = (clientX) => { const rect = canvas.getBoundingClientRect(); return (clientX - rect.left) * (canvas.width / rect.width); };

            const syncWidgets = () => {
                let s = getS(), e = getE();
                const fps = parseFloat(wFps?.value) || 25, fDur = 1.0 / fps;
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

                // --- 处理拖拽边框 ---
                let gx = vm.toCSS(s), rx = vm.toCSS(e);
                if (drag && drag.type === "start_line" && typeof drag.tempX === "number") gx = drag.tempX;
                if (drag && drag.type === "end_line" && typeof drag.tempX === "number") rx = drag.tempX;
                if (gx > rx) { const tmp = gx; gx = rx; rx = tmp; }

                ctx.fillStyle = "rgba(0,0,0,0.65)"; ctx.fillRect(PAD, 0, gx - PAD, H); ctx.fillRect(rx, 0, W - PAD - rx, H);
                ctx.fillStyle = "#4CAF50"; ctx.fillRect(gx - 2, 0, 4, H);
                ctx.fillStyle = "#F44336"; ctx.fillRect(rx - 2, 0, 4, H);

                // --- 播放指针 ---
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

            // ============================================================
            // 事件引擎：恢复拖拽与吸附
            // ============================================================
            canvas.onmousedown = (ev) => {
                if (totalDur <= 0) return;
                const mx = mouseToCanvasX(ev.clientX) / dpr, vm = visMapper();
                const sx = vm.toCSS(getS()), ex = vm.toCSS(getE());
                drag = null;
                if (Math.abs(mx - sx) < HANDLE_HIT) { drag = { type: "start_line" }; return; }
                if (Math.abs(mx - ex) < HANDLE_HIT) { drag = { type: "end_line" }; return; }

                // 点击非边缘区 → 直接跳转播放指针
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
                    const fps = parseFloat(wFps?.value) || 25, snap = v => Math.round(v * fps) / fps;
                    if (drag.type === "start_line") wStart.value = snap(Math.max(0, Math.min(newVal, getE() - 0.1)));
                    if (drag.type === "end_line") wEnd.value = snap(Math.min(totalDur, Math.max(newVal, getS() + 0.1)));
                    syncWidgets(); if (audioEl.readyState >= 1) audioEl.currentTime = getS();
                }
                drag = null;
            });

            // ============================================================
            // 核心逻辑
            // ============================================================
            const updateSrc = () => { const f = wAudio?.value; if (f && f !== "none" && f !== _lastFile) { _lastFile = f; totalDur = 0; audioEl.src = api.apiURL("/view?" + new URLSearchParams({ filename: f, type: "input", t: Date.now() })); } };
            audioEl.addEventListener("loadedmetadata", () => { totalDur = audioEl.duration; const fps = parseFloat(wFps?.value) || 25; const curStart = parseFloat(wStart?.value) || 0; const curEnd = parseFloat(wEnd?.value) || 0; if (curStart === 0 && (curEnd <= 0 || curEnd > totalDur + 1 || Math.abs(curEnd - 10.0) < 0.001)) { wStart.value = 0; wEnd.value = Math.floor(totalDur * fps) / fps; } syncWidgets(); audioEl.currentTime = parseFloat(wStart?.value) || 0; });
            audioEl.addEventListener("play", () => { _pausing = false; const st = getS(), et = getE(); if (audioEl.currentTime < st || audioEl.currentTime >= et) audioEl.currentTime = st; });
            audioEl.addEventListener("timeupdate", () => { if (_pausing) return; if (audioEl.currentTime >= getE()) { _pausing = true; audioEl.pause(); audioEl.currentTime = getS(); setTimeout(() => { _pausing = false; }, 100); } });

            const fetchPeaks = async (filename) => {
                if (!filename || filename === "none") { peaks = null; return; }
                try { const resp = await api.fetchApi("/xb_toolbox/audio_waveform", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ filename, num_peaks: 4000 }) }); if (resp.ok) { const data = await resp.json(); peaks = data.peaks; totalDur = data.duration || 10; } } catch (e) {}
            };

            if (wAudio) { const orig = wAudio.callback; wAudio.callback = function () { orig?.apply(this, arguments); updateSrc(); fetchPeaks(wAudio.value).then(() => { const curStart = parseFloat(wStart?.value) || 0; const curEnd = parseFloat(wEnd?.value) || 0; if (curStart === 0 && (curEnd <= 0 || curEnd > totalDur + 1 || Math.abs(curEnd - 10.0) < 0.001)) { wStart.value = 0; if (totalDur > 0) { const fps = parseFloat(wFps?.value) || 25; wEnd.value = Math.floor(totalDur * fps) / fps; } } syncWidgets(); }); }; }
            const onTimeChange = (resetPlayback) => { let s = getS(), e = getE(), dur = getDur(); if (e < s + 0.01) { e = Math.min(s + 0.01, dur); wEnd.value = e; } syncWidgets(); if (resetPlayback && audioEl.readyState >= 1) audioEl.currentTime = s; };
            if (wStart) { const orig = wStart.callback; wStart.callback = function () { orig?.apply(this, arguments); onTimeChange(true); }; }
            if (wEnd) { const orig = wEnd.callback; wEnd.callback = function () { orig?.apply(this, arguments); onTimeChange(false); }; }

            let _running = true;
            const renderLoop = () => { if (!_running) return; if (totalDur > 0) { syncWidgets(); draw(); } requestAnimationFrame(renderLoop); };
            renderLoop();

            setTimeout(() => { updateSrc(); if (wAudio?.value && wAudio.value !== "none") fetchPeaks(wAudio.value); }, 400);
            const o2 = node.onRemoved; node.onRemoved = () => { _running = false; o2?.apply(node); };
        };
    }
});