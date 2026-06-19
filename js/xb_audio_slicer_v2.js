import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// ============================================================
// XB_AudioSlicerV2 — 双人音频切片 + 边缘拖拽吸附 + 丝滑定位
// ============================================================

const PAD = 10, HANDLE_HIT = 12;

app.registerExtension({
    name: "XB_ToolBox.AudioSlicerV2",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "XB_AudioSlicerV2") return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            if (onNodeCreated) onNodeCreated.apply(this, arguments);
            const node = this;

            const wA1 = node.widgets.find(w => w.name === "audio1");
            const wS1 = node.widgets.find(w => w.name === "start1");
            const wE1 = node.widgets.find(w => w.name === "end1");
            const wA2 = node.widgets.find(w => w.name === "audio2");
            const wS2 = node.widgets.find(w => w.name === "start2");
            const wE2 = node.widgets.find(w => w.name === "end2");
            const wGap = node.widgets.find(w => w.name === "gap_frames");
            const wFps = node.widgets.find(w => w.name === "fps");
            const wTot = node.widgets.find(w => w.name === "total_display");

            if (wTot) setTimeout(() => { const el = wTot.inputEl || wTot.element; if (el) { el.readOnly = true; el.style.cssText = "background-color:#1a1a1a;color:#00E676;text-align:center;font-weight:bold;font-size:14px;min-width:120px;white-space:nowrap;overflow:hidden;"; } }, 100);

            const audioEl1 = document.createElement("audio"); audioEl1.controls = true; audioEl1.style.cssText = "width:100%;height:30px;outline:none;";
            const audioEl2 = document.createElement("audio"); audioEl2.controls = true; audioEl2.style.cssText = "width:100%;height:30px;outline:none;";
            let dur1 = 0, dur2 = 0, pausing = false, _last1 = null, _last2 = null;
            let peaks1 = null, peaks2 = null;
            let drags = { 1: null, 2: null }; // 存储双轨的拖动状态

            const ctr = document.createElement("div");
            Object.assign(ctr.style, { display:"flex", flexDirection:"column", gap:"4px", width:"100%", padding:"6px", boxSizing:"border-box", background:"#161616", borderRadius:"6px", color:"#ccc", fontFamily:"sans-serif", marginTop:"4px" });

            const mkUpload = (w, label) => {
                const fi = document.createElement("input"); fi.type = "file"; fi.accept = "audio/*,video/*"; fi.style.display = "none";
                fi.onchange = async () => {
                    if (!fi.files.length) return;
                    const body = new FormData(); body.append("image", fi.files[0]);
                    const resp = await api.fetchApi("/upload/image", { method: "POST", body });
                    if (resp.status === 200) { const d = await resp.json(); const n = d.name || fi.files[0].name; if (!w.options.values.includes(n)) w.options.values.push(n); w.value = n; if (w.callback) w.callback(n); }
                };
                document.body.appendChild(fi);
                const btn = node.addWidget("button", label, "image", () => { app.canvas.node_widget = null; fi.click(); });
                if (btn.options) btn.options.serialize = false;
                return fi;
            };
            mkUpload(wA1, "📁 上传音频 1"); mkUpload(wA2, "📁 上传音频 2");

            const dpr = window.devicePixelRatio || 1;
            const label1 = document.createElement("div"); label1.textContent = "🎵 音频1"; label1.style.cssText = "font-size:11px;color:#4FC3F7;font-weight:bold;";
            ctr.appendChild(label1); ctr.appendChild(audioEl1);
            const canvas1 = document.createElement("canvas"); canvas1.style.cssText = "width:100%;height:36px;border-radius:3px;background:#111;cursor:pointer;display:block;";
            canvas1.width = 1200 * dpr; canvas1.height = 72 * dpr; ctr.appendChild(canvas1);

            const label2 = document.createElement("div"); label2.textContent = "🎵 音频2"; label2.style.cssText = "font-size:11px;color:#F44336;font-weight:bold;";
            ctr.appendChild(label2); ctr.appendChild(audioEl2);
            const canvas2 = document.createElement("canvas"); canvas2.style.cssText = "width:100%;height:36px;border-radius:3px;background:#111;cursor:pointer;display:block;";
            canvas2.width = 1200 * dpr; canvas2.height = 72 * dpr; ctr.appendChild(canvas2);

            const domWidget = node.addDOMWidget("xb3_ui", "custom", ctr);
            domWidget.computeSize = () => [node.size[0] - 16, 240];
            if (node.size[1] < 520) node.size[1] = 520;

            const getD = (t) => t === 1 ? (dur1 || 10) : (dur2 || 10);
            const getS = (t) => t === 1 ? (parseFloat(wS1?.value) || 0) : (parseFloat(wS2?.value) || 0);
            const getE = (t) => { const e = t === 1 ? (parseFloat(wE1?.value) || 0) : (parseFloat(wE2?.value) || 0); return e > 0 ? e : getD(t); };
            const mouseToX = (cx, cvs) => { const r = cvs.getBoundingClientRect(); return (cx - r.left) * (cvs.width / r.width); };

            const syncW = (t) => {
                const s = getS(t), e = getE(t), ws = t === 1 ? wS1 : wS2, we = t === 1 ? wE1 : wE2;
                const dur = getD(t); if (e > dur) { if (we) we.value = dur; }
                if (ws) { ws.value = s; if (ws.inputEl) ws.inputEl.value = s; if (ws.element) ws.element.value = s; }
                if (we) { we.value = e; if (we.inputEl) we.inputEl.value = e; if (we.element) we.element.value = e; }
                const durSec = Math.max(0, e - s);
                const lbl = t === 1 ? label1 : label2;
                lbl.textContent = (t === 1 ? "🎵 音频1" : "🎵 音频2") + " (已选择 " + durSec.toFixed(2) + "秒)";
                if (wTot) {
                    const fps = parseFloat(wFps?.value) || 25, g = parseInt(wGap?.value) || 0;
                    const d1 = Math.max(0, getE(1) - getS(1)), d2 = Math.max(0, getE(2) - getS(2));
                    const totalFrames = Math.max(1, Math.floor(((Math.round(d1 * fps) + g + Math.round(d2 * fps)) + 2) / 4) * 4 + 1);
                    const tot = totalFrames + " 帧 (" + (d1 + g / fps + d2).toFixed(2) + "s)";
                    if (wTot.value !== tot) { wTot.value = tot; if (wTot.inputEl) wTot.inputEl.value = tot; if (wTot.element) wTot.element.value = tot; }
                }
            };

            const fetchPeaks = async (filename, track) => {
                if (!filename || filename === "none") { if (track === 1) peaks1 = null; else peaks2 = null; return; }
                try {
                    const resp = await api.fetchApi("/xb_toolbox/audio_waveform", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ filename, num_peaks: 4000 }) });
                    if (resp.ok) { const data = await resp.json(); if (track === 1) { peaks1 = data.peaks; dur1 = data.duration; } else { peaks2 = data.peaks; dur2 = data.duration; } }
                } catch (e) {}
            };

            const visMapper = (cvs, t) => {
                const s = getS(t), e = getE(t), dur = getD(t), selW = (e - s) || 0.01;
                const sVis = Math.max(0, s - 0.125 * selW), eVis = Math.min(dur, e + 0.125 * selW);
                const visW = (eVis - sVis) || 0.01, wwCSS = (cvs.width / dpr) - PAD * 2;
                return { sVis, eVis, visW, wwCSS, toCSS: (time) => PAD + ((time - sVis) / visW) * wwCSS, toTime: (cssX) => sVis + ((cssX - PAD) / wwCSS) * visW };
            };

            const drawWave = (cvs, t) => {
                const ctx = cvs.getContext("2d"), W = cvs.width / dpr, H = cvs.height / dpr;
                ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
                ctx.clearRect(0, 0, W, H); ctx.fillStyle = "#111"; ctx.fillRect(0, 0, W, H);
                const d = getD(t), s = getS(t), e = getE(t), vm = visMapper(cvs, t), ww = vm.wwCSS, mid = H / 2;
                const peaks = t === 1 ? peaks1 : peaks2;

                if (peaks && peaks.length > 1) {
                    const startIdx = Math.max(0, Math.floor((vm.sVis / d) * peaks.length)), endIdx = Math.min(peaks.length - 1, Math.ceil((vm.eVis / d) * peaks.length));
                    const vp = peaks.slice(startIdx, endIdx + 1);
                    if (vp.length > 1) {
                        const DISPLAY_POINTS = Math.min(1000, Math.floor((vm.wwCSS || ww) * 1.5));
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
                        ctx.fillStyle = "rgba(100,100,100,0.3)"; ctx.fill(pathInactive); ctx.fillStyle = t === 1 ? "#4FC3F7" : "#F44336"; ctx.fill(pathActive);
                    }
                }

                // 处理拖拽边框
                let gx = vm.toCSS(s), rx = vm.toCSS(e);
                if (drags[t] && drags[t].type === "start_line" && typeof drags[t].tempX === "number") gx = drags[t].tempX;
                if (drags[t] && drags[t].type === "end_line" && typeof drags[t].tempX === "number") rx = drags[t].tempX;
                if (gx > rx) { const tmp = gx; gx = rx; rx = tmp; }

                ctx.fillStyle = "rgba(0,0,0,0.65)"; ctx.fillRect(PAD, 0, gx - PAD, H); ctx.fillRect(rx, 0, W - PAD - rx, H);
                ctx.fillStyle = "#4CAF50"; ctx.fillRect(gx - 2, 0, 4, H);
                ctx.fillStyle = "#F44336"; ctx.fillRect(rx - 2, 0, 4, H);

                const ael = t === 1 ? audioEl1 : audioEl2;
                if (ael.readyState >= 1 && ael.currentTime > 0) {
                    const px = vm.toCSS(ael.currentTime);
                    if (px > PAD && px < W - PAD) { ctx.fillStyle = "#FFF"; ctx.fillRect(px - 1, 0, 2, H); }
                }

                ctx.fillStyle = "#fff"; ctx.font = "bold 10px sans-serif";
                ctx.fillText(s.toFixed(2) + "s", Math.max(PAD + 4, gx - 45), 14);
                const ewt = ctx.measureText(e.toFixed(2) + "s").width;
                ctx.fillText(e.toFixed(2) + "s", Math.min(W - PAD - ewt - 4, rx + 6), 14);
                ctx.setTransform(1, 0, 0, 1, 0, 0);
            };

            // ============================================================
            // 鼠标事件引擎
            // ============================================================
            const bindMouse = (cvs, t) => {
                cvs.onmousedown = (ev) => {
                    if (getD(t) <= 0) return;
                    const mx = mouseToX(ev.clientX, cvs) / dpr, vm = visMapper(cvs, t);
                    const sx = vm.toCSS(getS(t)), ex = vm.toCSS(getE(t));
                    drags[t] = null;
                    if (Math.abs(mx - sx) < HANDLE_HIT) { drags[t] = { type: "start_line" }; return; }
                    if (Math.abs(mx - ex) < HANDLE_HIT) { drags[t] = { type: "end_line" }; return; }

                    const clickTime = vm.toTime(mx), ael = t === 1 ? audioEl1 : audioEl2;
                    if (ael.readyState >= 1) ael.currentTime = Math.max(0, Math.min(getD(t), clickTime));
                };

                window.addEventListener("mousemove", (ev) => {
                    const mx = mouseToX(ev.clientX, cvs) / dpr;
                    if (drags[t]) {
                        drags[t].tempX = Math.max(PAD, Math.min(cvs.width / dpr - PAD, mx));
                    } else {
                        const rect = cvs.getBoundingClientRect();
                        if (ev.clientX >= rect.left && ev.clientX <= rect.right && ev.clientY >= rect.top && ev.clientY <= rect.bottom) {
                            const vm = visMapper(cvs, t), sx = vm.toCSS(getS(t)), ex = vm.toCSS(getE(t));
                            cvs.style.cursor = (Math.abs(mx - sx) < HANDLE_HIT || Math.abs(mx - ex) < HANDLE_HIT) ? "ew-resize" : "pointer";
                        }
                    }
                });
            };
            bindMouse(canvas1, 1); bindMouse(canvas2, 2);

            window.addEventListener("mouseup", () => {
                [1, 2].forEach(t => {
                    if (drags[t] && typeof drags[t].tempX === "number") {
                        const cvs = t === 1 ? canvas1 : canvas2, vm = visMapper(cvs, t), newVal = vm.toTime(drags[t].tempX);
                        const fps = parseFloat(wFps?.value) || 25, snap = v => Math.round(v * fps) / fps;
                        const ws = t === 1 ? wS1 : wS2, we = t === 1 ? wE1 : wE2;
                        if (drags[t].type === "start_line") ws.value = snap(Math.max(0, Math.min(newVal, getE(t) - 0.1)));
                        if (drags[t].type === "end_line") we.value = snap(Math.min(getD(t), Math.max(newVal, getS(t) + 0.1)));
                        syncW(t); const ael = t === 1 ? audioEl1 : audioEl2; if (ael.readyState >= 1) ael.currentTime = getS(t);
                    }
                    drags[t] = null;
                });
            });

            // ============================================================
            // 音频逻辑
            // ============================================================
            const updateSrc = (ael, w, t, _last) => { const f = w?.value; if (f && f !== "none" && f !== _last) { if (t === 1) _last1 = f; else _last2 = f; ael.src = api.apiURL("/view?" + new URLSearchParams({ filename: f, type: "input", t: Date.now() })); } };
            const bindAudio = (ael, t) => {
                ael.addEventListener("loadedmetadata", () => { if (t === 1) dur1 = ael.duration; else dur2 = ael.duration; const d = getD(t); const ws = t === 1 ? wS1 : wS2, we = t === 1 ? wE1 : wE2; const fps = parseFloat(wFps?.value) || 25; ws.value = 0; we.value = Math.floor(d * fps) / fps; syncW(t); ael.currentTime = 0; });
                ael.addEventListener("play", () => { const s = getS(t); if (ael.currentTime < s || ael.currentTime >= getE(t)) ael.currentTime = s; });
                ael.addEventListener("timeupdate", () => { if (pausing) return; if (ael.currentTime >= getE(t)) { pausing = true; ael.pause(); ael.currentTime = getS(t); setTimeout(() => { pausing = false; }, 100); } });
            };
            bindAudio(audioEl1, 1); bindAudio(audioEl2, 2);

            const onTimeChange = (t, resetPlayback) => { syncW(t); if (resetPlayback) { const ael = t === 1 ? audioEl1 : audioEl2; if (ael.readyState >= 1) ael.currentTime = getS(t); } };
            
            [wA1, wA2].forEach((w, i) => { if (w) { const o = w.callback; w.callback = function () { o?.apply(this, arguments); const t = i + 1; const fn = w.value; fetchPeaks(fn, t).then(() => { const ws = t === 1 ? wS1 : wS2, we = t === 1 ? wE1 : wE2; const d = t === 1 ? dur1 : dur2; const fps = parseFloat(wFps?.value) || 25; ws.value = 0; we.value = Math.floor(d * fps) / fps; syncW(t); }); updateSrc(i === 0 ? audioEl1 : audioEl2, w, t, i === 0 ? _last1 : _last2); }; } });
            [wS1].forEach(w => { if (w) { const o = w.callback; w.callback = function () { o?.apply(this, arguments); onTimeChange(1, true); }; } });
            [wE1].forEach(w => { if (w) { const o = w.callback; w.callback = function () { o?.apply(this, arguments); onTimeChange(1, false); }; } });
            [wS2].forEach(w => { if (w) { const o = w.callback; w.callback = function () { o?.apply(this, arguments); onTimeChange(2, true); }; } });
            [wE2].forEach(w => { if (w) { const o = w.callback; w.callback = function () { o?.apply(this, arguments); onTimeChange(2, false); }; } });
            if (wGap) { const o = wGap.callback; wGap.callback = function () { o?.apply(this, arguments); syncW(1); syncW(2); }; }

            let _running = true;
            const renderLoop = () => { if (!_running) return; if (dur1 > 0 || dur2 > 0) { syncW(1); syncW(2); drawWave(canvas1, 1); drawWave(canvas2, 2); } requestAnimationFrame(renderLoop); };
            renderLoop();

            setTimeout(() => { updateSrc(audioEl1, wA1, 1, _last1); updateSrc(audioEl2, wA2, 2, _last2); if (wA1?.value && wA1.value !== "none") fetchPeaks(wA1.value, 1); if (wA2?.value && wA2.value !== "none") fetchPeaks(wA2.value, 2); }, 400);

            const oo = node.onRemoved; node.onRemoved = () => { _running = false; oo?.apply(node); };
        };
    }
});