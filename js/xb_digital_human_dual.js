import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// ============================================================
// XB_DigitalHumanParams_Dual — 数字人参数调节（双人）
// 融合 视频参数大全 + 音频切片V3 的 UI 交互
// ============================================================

const PAD = 10, HANDLE_HIT = 12;

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
    name: "XB_ToolBox.DigitalHumanParams_Dual",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "XB_DigitalHumanParams_Dual") return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            if (onNodeCreated) onNodeCreated.apply(this, arguments);
            const node = this;

            // ── 控件引用 ──
            const w = {};
            ["audio1", "start1", "end1", "mute_count1", "mutes1_data",
                "audio2", "start2", "end2", "mute_count2", "mutes2_data",
                "merge_mode", "total_display"].forEach(n => { w[n] = node.widgets.find(x => x.name === n); });
            const wR = node.widgets.find(x => x.name === "aspect_ratio");
            const wW = node.widgets.find(x => x.name === "width");
            const wH = node.widgets.find(x => x.name === "height");
            const wFps = node.widgets.find(x => x.name === "fps");
            const wFF = node.widgets.find(x => x.name === "fps_float");
            if (!w.audio1 || !w.audio2) return;

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
                    let wv = Math.round((parseInt(wW.value, 10) || s) / s) * s; wv = Math.max(s, wv);
                    let hv = Math.round((wv / cr) / s) * s; hv = Math.max(s, hv);
                    if (hv !== parseInt(wH.value, 10)) { node._xb_syncing = true; wH.value = hv; xb_dispatch(wH, hv); node._xb_syncing = false; }
                };
                const sH = () => {
                    if (node._xb_syncing || node._xb_from_polling) return;
                    const r = wR.value; if (r.includes("Free")) return;
                    const isL = r.includes("(LTX)"); const rm = isL ? rL : rS; const cr = rm[r]; if (!cr) return;
                    const s = isL ? 32 : 16;
                    let hv = Math.round((parseInt(wH.value, 10) || s) / s) * s; hv = Math.max(s, hv);
                    let wv = Math.round((hv * cr) / s) * s; wv = Math.max(s, wv);
                    if (wv !== parseInt(wW.value, 10)) { node._xb_syncing = true; wW.value = wv; xb_dispatch(wW, wv); node._xb_syncing = false; }
                };

                const oc = wR.callback; wR.callback = function (v) { if (oc) oc.apply(this, arguments); if (node._xb_from_polling) return; sW(); };
                const ow = wW.callback; wW.callback = function (v) { if (ow) ow.apply(this, arguments); sW(); };
                const oh = wH.callback; wH.callback = function (v) { if (oh) oh.apply(this, arguments); sH(); };
            }

            // ── 帧率联动 ──
            if (wFps && wFF) {
                const of = wFps.callback; wFps.callback = function (v) { if (of) of.apply(this, arguments); if (node._xb_syncing || node._xb_from_polling) return; const val = Math.round(Number(v)); if (wFF.value !== val) { node._xb_syncing = true; wFF.value = val; xb_dispatch(wFF, val); node._xb_syncing = false; } };
                const off = wFF.callback; wFF.callback = function (v) { if (off) off.apply(this, arguments); if (node._xb_syncing || node._xb_from_polling) return; const val = Math.round(Number(v)); if (wFps.value !== val) { node._xb_syncing = true; wFps.value = val; xb_dispatch(wFps, val); node._xb_syncing = false; } };
            }

            // ── 隐藏隐形总线 ──
            [w.mutes1_data, w.mutes2_data].forEach(wd => { if (wd) { wd.type = "hidden"; wd.computeSize = () => [0, -4]; } });
            if (w.total_display) setTimeout(() => { const el = w.total_display.inputEl || w.total_display.element; if (el) { el.readOnly = true; el.style.cssText = "background-color:#1a1a1a;color:#00E676;text-align:center;font-weight:bold;font-size:14px;border:none;"; } }, 200);

            // ── 轨道状态机（来自 xb_audio_slicer_v3.js）──
            const tracks = {
                1: { wA: w.audio1, wS: w.start1, wE: w.end1, wMC: w.mute_count1, wMD: w.mutes1_data, peaks: null, dur: 10, cvs: null, ctx: null, ael: null, mutes: [], drag: null, fetchId: 0, vpRange: null },
                2: { wA: w.audio2, wS: w.start2, wE: w.end2, wMC: w.mute_count2, wMD: w.mutes2_data, peaks: null, dur: 10, cvs: null, ctx: null, ael: null, mutes: [], drag: null, fetchId: 0, vpRange: null }
            };
            const dpr = window.devicePixelRatio || 1;

            const updateTot = () => {
                if (!w.total_display) return;
                const fps = parseFloat(wFps?.value) || 24;
                const d1 = Math.max(0, (parseFloat(w.end1?.value) || 0) - (parseFloat(w.start1?.value) || 0));
                const d2 = Math.max(0, (parseFloat(w.end2?.value) || 0) - (parseFloat(w.start2?.value) || 0));
                const mode = w.merge_mode?.value || "接力";
                const rf1 = Math.round(d1 * fps), rf2 = Math.round(d2 * fps);
                const rawTotal = mode === "接力" ? rf1 + rf2 : Math.max(rf1, rf2);
                const totF = Math.max(1, Math.floor((rawTotal + 2) / 4) * 4 + 1);
                const totS = mode === "接力" ? d1 + d2 : Math.max(d1, d2);
                w.total_display.value = `${totF} 帧 (${totS.toFixed(2)}s)`;
            };

            const parseMutes = (t) => {
                const tr = tracks[t], str = (tr.wMD?.value || "").trim();
                tr.mutes = str ? str.split(";").filter(x => x).map(m => { const [s, e] = m.split(","); return { s: parseFloat(s) || 0, e: parseFloat(e) || 0 }; }) : [];
                const count = parseInt(tr.wMC?.value) || 0;
                while (tr.mutes.length < count) {
                    const s = parseFloat(tr.wS?.value) || 0, e = parseFloat(tr.wE?.value) || (s + 10);
                    const mid = (s + e) / 2, half = (e - s) * 0.1;
                    tr.mutes.push({ s: mid - half, e: mid + half });
                }
                while (tr.mutes.length > count) tr.mutes.pop();
                if (tr.wMD) tr.wMD.value = tr.mutes.map(m => m.s.toFixed(3) + "," + m.e.toFixed(3)).join(";");
            };

            const fetchPeaks = async (filename, t) => {
                if (!filename || filename === "none") { tracks[t].peaks = null; return; }
                try {
                    const tr = tracks[t];
                    const currentFetchId = ++tr.fetchId;
                    const m = getMapper(tr, tr.cvs);
                    let payload = { filename, num_peaks: 400, start_time: m.sVis, end_time: m.eVis };
                    const resp = await api.fetchApi("/xb_audio_waveform", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
                    if (resp.ok) {
                        const d = await resp.json();
                        if (tr.fetchId !== currentFetchId) return;
                        tracks[t].peaks = d.peaks;
                        tracks[t].dur = d.duration || 10;
                        tracks[t].vpRange = { s: payload.start_time, e: payload.end_time };
                    }
                } catch (e) { }
            };

            const ctr = document.createElement("div");
            Object.assign(ctr.style, { display: "flex", flexDirection: "column", gap: "6px", width: "100%", padding: "6px", boxSizing: "border-box", background: "#161616", borderRadius: "6px" });

            const mkUpload = (aw, label) => {
                const fi = document.createElement("input"); fi.type = "file"; fi.accept = "audio/*,video/*"; fi.style.display = "none";
                fi.onchange = async () => {
                    if (!fi.files.length) return;
                    const body = new FormData(); body.append("image", fi.files[0]);
                    const resp = await api.fetchApi("/upload/image", { method: "POST", body });
                    if (resp.status === 200) { const d = await resp.json(); const n = d.name || fi.files[0].name; if (!aw.options.values.includes(n)) aw.options.values.push(n); aw.value = n; if (aw.callback) aw.callback(n); }
                };
                document.body.appendChild(fi);
                const btn = node.addWidget("button", label, "image", () => { app.canvas.node_widget = null; fi.click(); });
                if (btn.options) btn.options.serialize = false;
                return fi;
            };
            mkUpload(w.audio1, "📁 上传音频1"); mkUpload(w.audio2, "📁 上传音频2");

            [1, 2].forEach(t => {
                const tr = tracks[t], color = t === 1 ? "#4FC3F7" : "#F44336", tag = t === 1 ? "🎵 轨道 1" : "🎵 轨道 2";
                const lbl = document.createElement("div"); lbl.textContent = tag; lbl.style.cssText = `font-size:11px;color:${color};font-weight:bold;margin-top:4px;`; ctr.appendChild(lbl);
                const ael = document.createElement("audio"); ael.controls = true; ael.style.cssText = "width:100%;height:30px;outline:none;"; ctr.appendChild(ael); tr.ael = ael;
                const cvs = document.createElement("canvas"); cvs.style.cssText = "width:100%;height:64px;border-radius:4px;background:#0A0A0A;cursor:crosshair;display:block;";
                cvs.width = 1200 * dpr; cvs.height = 128 * dpr; ctr.appendChild(cvs);
                tr.cvs = cvs; tr.ctx = cvs.getContext("2d");
            });

            const domWidget = node.addDOMWidget("xb_dh_dual_ui", "custom", ctr);
            domWidget.computeSize = () => [node.size[0] - 16, 280];
            if (node.size[1] < 500) node.size[1] = 500;

            const getMapper = (tr, cvs) => {
                const s = parseFloat(tr.wS?.value) || 0, e = parseFloat(tr.wE?.value) || (s + 10), dur = tr.dur || 10;
                const selW = Math.max(0.01, e - s);
                const sVis = Math.max(0, s - 0.125 * selW), eVis = Math.min(dur, e + 0.125 * selW);
                const visW = Math.max(0.01, eVis - sVis);
                const cssW = cvs.width / dpr, wwCSS = cssW - PAD * 2;
                return { s, e, dur, sVis, eVis, visW, cssW, wwCSS, toCSS: (t) => PAD + ((t - sVis) / visW) * wwCSS, toTime: (cssX) => sVis + ((cssX - PAD) / wwCSS) * visW };
            };
            const getMouseCSSX = (ev, cvs) => { const rect = cvs.getBoundingClientRect(); return (ev.clientX - rect.left) * ((cvs.width / dpr) / rect.width); };

            const drawWave = (t) => {
                const tr = tracks[t], ctx = tr.ctx;
                if (!ctx) return;
                ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
                const W = tr.cvs.width / dpr, H = tr.cvs.height / dpr;
                ctx.clearRect(0, 0, W, H); ctx.fillStyle = "#111"; ctx.fillRect(0, 0, W, H);

                if (!tr.peaks || tr.peaks.length === 0) {
                    ctx.fillStyle = "#555"; ctx.font = "14px sans-serif";
                    ctx.fillText("分析波形中...", PAD, H / 2);
                    ctx.setTransform(1, 0, 0, 1, 0, 0); return;
                }

                const m = getMapper(tr, tr.cvs);
                const mid = H / 2;
                const vp = tr.peaks;

                if (vp && vp.length > 1 && tr.vpRange) {
                    const localMax = Math.max(...vp.map(p => p[0]), 0.001);
                    const localMin = Math.min(...vp.map(p => p[1]), -0.001);
                    const absMax = Math.max(localMax, Math.abs(localMin));
                    const scale = (v) => (v / absMax) * (H * 0.45);
                    const rangeDur = tr.vpRange.e - tr.vpRange.s;

                    const pathActive = new Path2D(), pathInactive = new Path2D();
                    pathActive.moveTo(PAD, mid); pathInactive.moveTo(PAD, mid);
                    for (let i = 0; i < vp.length; i++) {
                        const tAt = tr.vpRange.s + (i / (vp.length - 1)) * rangeDur;
                        const x = m.toCSS(tAt), y = mid - scale(vp[i][0]);
                        if (tAt >= m.s && tAt <= m.e) pathActive.lineTo(x, y); else pathInactive.lineTo(x, y);
                    }
                    for (let i = vp.length - 1; i >= 0; i--) {
                        const tAt = tr.vpRange.s + (i / (vp.length - 1)) * rangeDur;
                        const x = m.toCSS(tAt), y = mid - scale(vp[i][1]);
                        if (tAt >= m.s && tAt <= m.e) pathActive.lineTo(x, y); else pathInactive.lineTo(x, y);
                    }
                    pathActive.closePath(); pathInactive.closePath();

                    ctx.fillStyle = "rgba(100,100,100,0.3)"; ctx.fill(pathInactive);
                    ctx.fillStyle = t === 1 ? "#4FC3F7" : "#F44336"; ctx.fill(pathActive);
                }

                tr.mutes.forEach(mt => {
                    if (mt.e > m.sVis && mt.s < m.eVis) {
                        const xS = m.toCSS(Math.max(m.sVis, mt.s)), xE = m.toCSS(Math.min(m.eVis, mt.e));
                        ctx.fillStyle = "rgba(100,100,100,0.65)";
                        ctx.fillRect(xS, 0, xE - xS, H);
                        ctx.fillStyle = "#9ca3af";
                        ctx.fillRect(xS, 0, 2, H); ctx.fillRect(xE - 2, 0, 2, H);
                    }
                });

                let gx = m.toCSS(m.s), rx = m.toCSS(m.e);
                if (tr.drag && tr.drag.type === "start_line" && typeof tr.drag.tempX === "number") gx = tr.drag.tempX;
                if (tr.drag && tr.drag.type === "end_line" && typeof tr.drag.tempX === "number") rx = tr.drag.tempX;
                if (gx > rx) { const tmp = gx; gx = rx; rx = tmp; }

                ctx.fillStyle = "rgba(0,0,0,0.65)"; ctx.fillRect(PAD, 0, gx - PAD, H); ctx.fillRect(rx, 0, W - PAD - rx, H);
                const bc = t === 1 ? "#4CAF50" : "#FF9800";
                ctx.fillStyle = bc; ctx.fillRect(gx - 2, 0, 4, H); ctx.fillRect(rx - 2, 0, 4, H);

                if (tr.ael.readyState >= 1 && tr.ael.currentTime > 0) {
                    const px = m.toCSS(tr.ael.currentTime);
                    if (px > PAD && px < W - PAD) { ctx.fillStyle = "#FFF"; ctx.fillRect(px - 1, 0, 2, H); }
                }

                ctx.fillStyle = "#fff"; ctx.font = "bold 11px sans-serif";
                ctx.fillText(m.s.toFixed(2) + "s", Math.max(PAD + 4, gx - 45), 18);
                const ew = ctx.measureText(m.e.toFixed(2) + "s").width;
                ctx.fillText(m.e.toFixed(2) + "s", Math.min(W - PAD - ew - 4, rx + 6), 18);
                ctx.setTransform(1, 0, 0, 1, 0, 0);
            };

            [1, 2].forEach(t => {
                const tr = tracks[t], cvs = tr.cvs;
                cvs.onmousedown = (ev) => {
                    const mx = getMouseCSSX(ev, cvs), m = getMapper(tr, cvs);
                    const sx = m.toCSS(m.s), ex = m.toCSS(m.e);
                    tr.drag = null;
                    if (Math.abs(mx - sx) < HANDLE_HIT) { tr.drag = { type: "start_line" }; return; }
                    if (Math.abs(mx - ex) < HANDLE_HIT) { tr.drag = { type: "end_line" }; return; }
                    for (let i = 0; i < tr.mutes.length; i++) {
                        const xS = m.toCSS(tr.mutes[i].s), xE = m.toCSS(tr.mutes[i].e);
                        if (Math.abs(mx - xS) < HANDLE_HIT) { tr.drag = { type: "mute_s", i }; return; }
                        if (Math.abs(mx - xE) < HANDLE_HIT) { tr.drag = { type: "mute_e", i }; return; }
                        if (mx > xS && mx < xE) { tr.drag = { type: "mute_body", i, offset: m.toTime(mx) - tr.mutes[i].s }; return; }
                    }
                    if (!tr.drag) { const clickTime = Math.max(0, Math.min(tr.dur, m.toTime(mx))); if (tr.ael.readyState >= 1) tr.ael.currentTime = clickTime; }
                };

                cvs.onmousemove = (ev) => {
                    const mx = getMouseCSSX(ev, cvs), m = getMapper(tr, cvs);
                    if (tr.drag) {
                        cvs.style.cursor = tr.drag.type === "mute_body" ? "grabbing" : "ew-resize";
                        tr.drag.tempX = Math.max(PAD, Math.min(cvs.width / dpr - PAD, mx));
                        if (tr.drag.type === "mute_s") tr.mutes[tr.drag.i].s = Math.min(Math.max(0, m.toTime(mx)), tr.mutes[tr.drag.i].e - 0.02);
                        if (tr.drag.type === "mute_e") tr.mutes[tr.drag.i].e = Math.max(Math.min(m.dur, m.toTime(mx)), tr.mutes[tr.drag.i].s + 0.02);
                        if (tr.drag.type === "mute_body") {
                            const md = tr.mutes[tr.drag.i].e - tr.mutes[tr.drag.i].s;
                            tr.mutes[tr.drag.i].s = Math.max(0, Math.min(m.dur - md, m.toTime(mx) - tr.drag.offset));
                            tr.mutes[tr.drag.i].e = tr.mutes[tr.drag.i].s + md;
                        }
                        if (tr.drag.type.includes("mute")) { if (tr.wMD) tr.wMD.value = tr.mutes.map(mt => mt.s.toFixed(3) + "," + mt.e.toFixed(3)).join(";"); }
                    } else {
                        const sx = m.toCSS(m.s), ex = m.toCSS(m.e);
                        let cursor = "crosshair";
                        if (Math.abs(mx - sx) < HANDLE_HIT || Math.abs(mx - ex) < HANDLE_HIT) {
                            cursor = "ew-resize";
                        } else {
                            let inBody = false;
                            for (let i = 0; i < tr.mutes.length; i++) {
                                const xS = m.toCSS(tr.mutes[i].s), xE = m.toCSS(tr.mutes[i].e);
                                if (Math.abs(mx - xS) < HANDLE_HIT || Math.abs(mx - xE) < HANDLE_HIT) {
                                    cursor = "ew-resize"; inBody = false; break;
                                } else if (mx > xS && mx < xE) {
                                    inBody = true;
                                }
                            }
                            if (cursor !== "ew-resize" && inBody) cursor = "grab";
                        }
                        cvs.style.cursor = cursor;
                    }
                };
            });

            window.addEventListener("mouseup", () => {
                [1, 2].forEach(t => {
                    const tr = tracks[t];
                    if (tr.drag && (tr.drag.type === "start_line" || tr.drag.type === "end_line") && typeof tr.drag.tempX === "number") {
                        const m = getMapper(tr, tr.cvs), newVal = m.toTime(tr.drag.tempX);
                        const fps = parseFloat(wFps?.value) || 24, snap = v => Math.round(v * fps) / fps;
                        if (tr.drag.type === "start_line") tr.wS.value = snap(Math.max(0, Math.min(newVal, m.e - 0.1)));
                        if (tr.drag.type === "end_line") tr.wE.value = snap(Math.min(tr.dur, Math.max(newVal, m.s + 0.1)));
                        updateTot(); if (tr.ael.readyState >= 1) tr.ael.currentTime = parseFloat(tr.wS.value);
                        fetchPeaks(tr.wA?.value, t);
                    }
                    tr.drag = null;
                });
            });

            const updateSrc = (t) => {
                const tr = tracks[t], f = tr.wA?.value;
                if (f && f !== "none") tr.ael.src = api.apiURL("/view?" + new URLSearchParams({ filename: f, type: "input", t: Date.now() }));
            };

            [1, 2].forEach(t => {
                const tr = tracks[t];
                if (tr.wA) { const o = tr.wA.callback; tr.wA.callback = function () { o?.apply(this, arguments); updateSrc(t); fetchPeaks(tr.wA.value, t).then(() => drawWave(t)); }; }
                if (tr.wMC) { const o = tr.wMC.callback; tr.wMC.callback = function () { o?.apply(this, arguments); parseMutes(t); drawWave(t); }; }
                if (tr.wS) { const o = tr.wS.callback; tr.wS.callback = function () { o?.apply(this, arguments); const val = parseFloat(tr.wS?.value) || 0; if (val < 0) tr.wS.value = 0; updateTot(); if (tr.ael.readyState >= 1) tr.ael.currentTime = parseFloat(tr.wS?.value) || 0; }; }
                if (tr.wE) { const o = tr.wE.callback; tr.wE.callback = function () { o?.apply(this, arguments); const dur = tr.dur || 10; const val = parseFloat(tr.wE?.value) || 0; if (val > dur) { const fps = parseFloat(wFps?.value) || 24; tr.wE.value = Math.floor(dur * fps) / fps; } updateTot(); }; }

                tr.ael.addEventListener("loadedmetadata", () => { tr.dur = tr.ael.duration; const fps = parseFloat(wFps?.value) || 24; const curStart = parseFloat(tr.wS?.value) || 0; const curEnd = parseFloat(tr.wE?.value) || 0; if (curStart === 0 && (curEnd <= 0 || curEnd > tr.dur + 1 || Math.abs(curEnd - 10.0) < 0.001)) { tr.wS.value = 0; tr.wE.value = Math.floor(tr.dur * fps) / fps; } updateTot(); fetchPeaks(tr.wA?.value, t); });

                tr.ael.addEventListener("timeupdate", () => {
                    const s = parseFloat(tr.wS?.value) || 0, e = parseFloat(tr.wE?.value) || 10;
                    if (tr.ael.currentTime >= e) { tr.ael.pause(); tr.ael.currentTime = s; }
                    let isMute = false;
                    for (const m of tr.mutes) { if (tr.ael.currentTime >= m.s && tr.ael.currentTime < m.e) { isMute = true; break; } }
                    tr.ael.muted = isMute;
                });
            });

            if (w.merge_mode) { const o = w.merge_mode.callback; w.merge_mode.callback = function () { o?.apply(this, arguments); updateTot(); }; }

            let _running = true;
            const renderLoop = () => {
                if (!_running) return;
                drawWave(1); drawWave(2);
                requestAnimationFrame(renderLoop);
            };
            renderLoop();

            setTimeout(() => { [1, 2].forEach(t => { parseMutes(t); updateSrc(t); if (tracks[t].wA?.value && tracks[t].wA.value !== "none") fetchPeaks(tracks[t].wA.value, t); }); updateTot(); }, 400);

            const o2 = node.onRemoved;
            node.onRemoved = () => { _running = false; o2?.apply(node); };
        };
    },

    // ── init：轮询更新步长（来自 xb_video.js）──
    init() {
        setInterval(() => {
            if (!app.graph || !app.graph._nodes) return;

            for (const node of app.graph._nodes) {
                if (node.comfyClass === "XB_DigitalHumanParams_Dual" && node.widgets) {
                    const wRatio = node.widgets.find(w => w.name === "aspect_ratio");
                    const wWidth = node.widgets.find(w => w.name === "width");
                    const wHeight = node.widgets.find(w => w.name === "height");
                    const wFps = node.widgets.find(w => w.name === "fps");
                    const wFF = node.widgets.find(w => w.name === "fps_float");

                    if (wRatio && wWidth && wHeight && wFps && wFF) {
                        node._xb_from_polling = true;

                        if (node._xb_last_fps === undefined) {
                            node._xb_last_fps = wFps.value;
                            node._xb_last_fps_float = wFF.value;
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
                            let val = Math.round(Number(wFps.value)); wFps.value = val; wFF.value = val;
                            node._xb_last_fps = val; node._xb_last_fps_float = val;
                            xb_dispatch(wFps, val); xb_dispatch(wFF, val);
                            needsUpdate = true;
                        } else if (wFF.value !== node._xb_last_fps_float) {
                            let val = Math.round(Number(wFF.value)); wFps.value = val; wFF.value = val;
                            node._xb_last_fps = val; node._xb_last_fps_float = val;
                            xb_dispatch(wFps, val); xb_dispatch(wFF, val);
                            needsUpdate = true;
                        }

                        wFF.options.precision = 2;

                        if (needsUpdate) app.graph.setDirtyCanvas(true, true);
                        node._xb_from_polling = false;
                    }
                }
            }
        }, 200);
    }
});
