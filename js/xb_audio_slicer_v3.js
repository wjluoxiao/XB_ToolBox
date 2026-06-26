import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// ============================================================
// XB_AudioSlicerV3 — 高级双人音频切片
// 区域频谱 + 滑块自动吸附 + 静音色块 + 接力/重叠合并
// ============================================================

const PAD = 10, HANDLE_HIT = 12;

app.registerExtension({
    name: "XB_ToolBox.AudioSlicerV3",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "XB_AudioSlicerV3") return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            if (onNodeCreated) onNodeCreated.apply(this, arguments);
            const node = this;

            // --- widgets ---
            const w = {};
            ["audio1","start1","end1","mute_count1","mutes1_data",
             "audio2","start2","end2","mute_count2","mutes2_data",
             "merge_mode","total_display"].forEach(n => { w[n] = node.widgets.find(x => x.name === n); });
            const wFps = node.widgets.find(x => x.name === "fps");
            if (!w.audio1 || !w.audio2) return;

            // 隐藏隐形总线
            [w.mutes1_data, w.mutes2_data].forEach(wd => { if (wd) { wd.type = "hidden"; wd.computeSize = () => [0, -4]; } });
            if (w.total_display) setTimeout(() => { const el = w.total_display.inputEl || w.total_display.element; if (el) { el.readOnly = true; el.style.cssText = "background-color:#1a1a1a;color:#00E676;text-align:center;font-weight:bold;font-size:14px;border:none;"; } }, 200);

            // 轨道状态机
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
                if(tr.wMD) tr.wMD.value = tr.mutes.map(m => m.s.toFixed(3) + "," + m.e.toFixed(3)).join(";");
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
                } catch (e) {}
            };

            const ctr = document.createElement("div");
            Object.assign(ctr.style, { display:"flex", flexDirection:"column", gap:"6px", width:"100%", padding:"6px", boxSizing:"border-box", background:"#161616", borderRadius:"6px" });

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
                
                // 🚀 修改 1：大幅压缩高度，从 100px 减为 64px
                const cvs = document.createElement("canvas"); cvs.style.cssText = "width:100%;height:64px;border-radius:4px;background:#0A0A0A;cursor:crosshair;display:block;";
                cvs.width = 1200 * dpr; cvs.height = 128 * dpr; ctr.appendChild(cvs);
                tr.cvs = cvs; tr.ctx = cvs.getContext("2d");
            });

            // 🚀 同步缩小 Widget 和 Node 的整体尺寸
            const domWidget = node.addDOMWidget("xb_v3_ui", "custom", ctr);
            domWidget.computeSize = () => [node.size[0] - 16, 280]; 
            if (node.size[1] < 450) node.size[1] = 450;

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
                
                // 🚀 修改 2：全局智能鼠标样式，为静音块和边缘加入专业手感
                cvs.onmousemove = (ev) => {
                    const mx = getMouseCSSX(ev, cvs), m = getMapper(tr, cvs);
                    if (tr.drag) {
                        // 拖拽中：身体显示抓紧小手，边缘显示水平拖拉
                        cvs.style.cursor = tr.drag.type === "mute_body" ? "grabbing" : "ew-resize";
                        
                        tr.drag.tempX = Math.max(PAD, Math.min(cvs.width / dpr - PAD, mx));
                        if (tr.drag.type === "mute_s") tr.mutes[tr.drag.i].s = Math.min(Math.max(0, m.toTime(mx)), tr.mutes[tr.drag.i].e - 0.02);
                        if (tr.drag.type === "mute_e") tr.mutes[tr.drag.i].e = Math.max(Math.min(m.dur, m.toTime(mx)), tr.mutes[tr.drag.i].s + 0.02);
                        if (tr.drag.type === "mute_body") {
                            const md = tr.mutes[tr.drag.i].e - tr.mutes[tr.drag.i].s;
                            tr.mutes[tr.drag.i].s = Math.max(0, Math.min(m.dur - md, m.toTime(mx) - tr.drag.offset));
                            tr.mutes[tr.drag.i].e = tr.mutes[tr.drag.i].s + md;
                        }
                        if (tr.drag.type.includes("mute")) { if(tr.wMD) tr.wMD.value = tr.mutes.map(mt => mt.s.toFixed(3) + "," + mt.e.toFixed(3)).join(";"); }
                    } else {
                        // 悬停中：检测当前处于什么元素的上方
                        const sx = m.toCSS(m.s), ex = m.toCSS(m.e);
                        let cursor = "crosshair"; // 默认是点击跳转的十字星
                        
                        if (Math.abs(mx - sx) < HANDLE_HIT || Math.abs(mx - ex) < HANDLE_HIT) {
                            cursor = "ew-resize";
                        } else {
                            let inBody = false;
                            for (let i = 0; i < tr.mutes.length; i++) {
                                const xS = m.toCSS(tr.mutes[i].s);
                                const xE = m.toCSS(tr.mutes[i].e);
                                if (Math.abs(mx - xS) < HANDLE_HIT || Math.abs(mx - xE) < HANDLE_HIT) {
                                    cursor = "ew-resize";
                                    inBody = false;
                                    break;
                                } else if (mx > xS && mx < xE) {
                                    inBody = true;
                                }
                            }
                            if (cursor !== "ew-resize" && inBody) {
                                cursor = "grab"; // 悬停在色块中间显示可抓取的小手
                            }
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
                if (tr.wA) { const o = tr.wA.callback; tr.wA.callback = function () { o?.apply(this, arguments); updateSrc(t); fetchPeaks(tr.wA.value, t).then(() => draw(t)); }; }
                if (tr.wMC) { const o = tr.wMC.callback; tr.wMC.callback = function () { o?.apply(this, arguments); parseMutes(t); draw(t); }; }
                if (tr.wS) { const o = tr.wS.callback; tr.wS.callback = function () { o?.apply(this, arguments); const val = parseFloat(tr.wS?.value) || 0; if (val < 0) tr.wS.value = 0; updateTot(); if (tr.ael.readyState >= 1) tr.ael.currentTime = parseFloat(tr.wS?.value) || 0; }; }
                if (tr.wE) { const o = tr.wE.callback; tr.wE.callback = function () { o?.apply(this, arguments); const dur = tr.dur || 10; const val = parseFloat(tr.wE?.value) || 0; if (val > dur) { const fps = parseFloat(wFps?.value) || 24; tr.wE.value = Math.floor(dur * fps) / fps; } updateTot(); }; }
                
                tr.ael.addEventListener("loadedmetadata", () => { tr.dur = tr.ael.duration; const fps = parseFloat(wFps?.value) || 24; const curStart = parseFloat(tr.wS?.value) || 0; const curEnd = parseFloat(tr.wE?.value) || 0; if (curStart === 0 && (curEnd <= 0 || curEnd > tr.dur + 1 || Math.abs(curEnd - 10.0) < 0.001)) { tr.wS.value = 0; tr.wE.value = Math.floor(tr.dur * fps) / fps; } updateTot(); fetchPeaks(tr.wA?.value, t); });
                
                tr.ael.addEventListener("timeupdate", () => {
                    const s = parseFloat(tr.wS?.value) || 0, e = parseFloat(tr.wE?.value) || 10;
                    if (tr.ael.currentTime >= e) { tr.ael.pause(); tr.ael.currentTime = s; }
                    
                    let isMute = false;
                    for (const m of tr.mutes) { 
                        if (tr.ael.currentTime >= m.s && tr.ael.currentTime < m.e) { 
                            isMute = true; 
                            break; 
                        } 
                    }
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
    }
});