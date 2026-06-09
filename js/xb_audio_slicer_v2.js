import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// ============================================================
// XB_AudioSlicerV3 — 双人音频：音频1 + 间隔 + 音频2
// ============================================================

const PAD = 10, HANDLE_HIT = 16;

app.registerExtension({
    name: "XB_ToolBox.AudioSlicerV3",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "XB_AudioSlicerV2") return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            if (onNodeCreated) onNodeCreated.apply(this, arguments);
            const node = this;

            // widgets
            const wA1 = node.widgets.find(w => w.name === "audio1");
            const wS1 = node.widgets.find(w => w.name === "start1");
            const wE1 = node.widgets.find(w => w.name === "end1");
            const wA2 = node.widgets.find(w => w.name === "audio2");
            const wS2 = node.widgets.find(w => w.name === "start2");
            const wE2 = node.widgets.find(w => w.name === "end2");
            const wGap = node.widgets.find(w => w.name === "gap_frames");
            const wFps = node.widgets.find(w => w.name === "fps");
            const wTot = node.widgets.find(w => w.name === "total_display");

            // total_display 样式
            if (wTot) setTimeout(() => { const el = wTot.inputEl || wTot.element; if (el) { el.readOnly = true; el.style.backgroundColor = "#1a1a1a"; el.style.color = "#00E676"; el.style.textAlign = "center"; el.style.fontWeight = "bold"; el.style.fontSize = "13px"; } }, 100);

            // 状态
            const audioEl1 = document.createElement("audio"); audioEl1.controls = true; audioEl1.style.cssText = "width:100%;height:30px;outline:none;";
            const audioEl2 = document.createElement("audio"); audioEl2.controls = true; audioEl2.style.cssText = "width:100%;height:30px;outline:none;";
            let dur1 = 0, dur2 = 0, drag = null, drs = 0, dre = 0, pausing = false, _last1 = null, _last2 = null;
            let activeTrack = 1; // 1 or 2

            // ============================================================
            // 容器
            // ============================================================
            const ctr = document.createElement("div");
            Object.assign(ctr.style, { display:"flex", flexDirection:"column", gap:"4px", width:"100%", padding:"6px", boxSizing:"border-box", background:"#161616", borderRadius:"6px", color:"#ccc", fontFamily:"sans-serif", marginTop:"4px" });

            // 上传按钮
            const mkUpload = (w, label) => {
                const fi = document.createElement("input"); fi.type = "file"; fi.accept = "audio/*,video/*"; fi.style.display = "none";
                fi.onchange = async () => {
                    if (!fi.files.length) return;
                    const body = new FormData(); body.append("image", fi.files[0]);
                    const resp = await api.fetchApi("/upload/image", { method: "POST", body });
                    if (resp.status === 200) {
                        const d = await resp.json(); const n = d.name || fi.files[0].name;
                        if (!w.options.values.includes(n)) w.options.values.push(n);
                        w.value = n; if (w.callback) w.callback(n);
                    }
                };
                document.body.appendChild(fi);
                const btn = node.addWidget("button", label, "image", () => { app.canvas.node_widget = null; fi.click(); });
                btn.options.serialize = false;
                return fi;
            };
            const fi1 = mkUpload(wA1, "上传音频1");
            const fi2 = mkUpload(wA2, "上传音频2");

            // 播放器1 + 波形1
            const label1 = document.createElement("div");
            label1.textContent = "🎵 音频1"; label1.style.cssText = "font-size:11px;color:#4FC3F7;font-weight:bold;";
            ctr.appendChild(label1);
            ctr.appendChild(audioEl1);
            const canvas1 = document.createElement("canvas");
            canvas1.style.cssText = "width:100%;height:36px;border-radius:3px;background:#111;cursor:pointer;display:block;";
            const dpr = window.devicePixelRatio || 1;
            canvas1.width = 1200 * dpr; canvas1.height = 72 * dpr;
            ctr.appendChild(canvas1);

            // 播放器2 + 波形2
            const label2 = document.createElement("div");
            label2.textContent = "🎵 音频2"; label2.style.cssText = "font-size:11px;color:#F44336;font-weight:bold;";
            ctr.appendChild(label2);
            ctr.appendChild(audioEl2);
            const canvas2 = document.createElement("canvas");
            canvas2.style.cssText = "width:100%;height:36px;border-radius:3px;background:#111;cursor:pointer;display:block;";
            canvas2.width = 1200 * dpr; canvas2.height = 72 * dpr;
            ctr.appendChild(canvas2);

            const domWidget = node.addDOMWidget("xb3_ui", "custom", ctr);
            domWidget.computeSize = () => [node.size[0] - 16, 240];
            if (node.size[1] < 520) node.size[1] = 520;

            // ============================================================
            // 辅助
            // ============================================================
            const getD = (t) => t === 1 ? (dur1 || 10) : (dur2 || 10);
            const getS = (t) => t === 1 ? (parseFloat(wS1?.value) || 0) : (parseFloat(wS2?.value) || 0);
            const getE = (t) => { const e = t === 1 ? (parseFloat(wE1?.value) || 0) : (parseFloat(wE2?.value) || 0); return e > 0 ? e : getD(t); };
            const mouseToX = (cx, cvs) => { const r = cvs.getBoundingClientRect(); return (cx - r.left) * (cvs.width / r.width); };
            const xToT = (cx, cvs, t) => { const d = getD(t), ww = cvs.width - PAD * 2; return Math.max(0, Math.min(d, ((cx - PAD) / ww) * d)); };
            const tToX = (tv, cvs, t) => { const d = getD(t), ww = cvs.width - PAD * 2; return PAD + (tv / d) * ww; };

            const syncW = (t) => {
                const s = getS(t), e = getE(t), ws = t === 1 ? wS1 : wS2, we = t === 1 ? wE1 : wE2;
                if (ws) { ws.value = s; if (ws.inputEl) ws.inputEl.value = s; if (ws.element) ws.element.value = s; }
                if (we) { we.value = e; if (we.inputEl) we.inputEl.value = e; if (we.element) we.element.value = e; }
                // 更新音频标签：显示已选秒数
                const durSec = Math.max(0, e - s);
                const lbl = t === 1 ? label1 : label2;
                const tag = t === 1 ? "🎵 音频1" : "🎵 音频2";
                lbl.textContent = tag + " (已选择 " + durSec.toFixed(2) + "秒)";
                if (wTot) {
                    const fps = parseFloat(wFps?.value) || 25;
                    const g = parseInt(wGap?.value) || 0;
                    const d1 = Math.max(0, getE(1) - getS(1));
                    const d2 = Math.max(0, getE(2) - getS(2));
                    const rf1 = Math.round(d1 * fps);
                    const rf2 = Math.round(d2 * fps);
                    const f1 = Math.max(1, Math.floor((rf1 + 2) / 4) * 4 + 1);
                    const f2 = Math.max(1, Math.floor((rf2 + 2) / 4) * 4 + 1);
                    const rawTotal = rf1 + g + rf2;
                    const totalFrames = Math.max(1, Math.floor((rawTotal + 2) / 4) * 4 + 1);
                    const totalSec = d1 + g / fps + d2;
                    const tot = totalFrames + " 帧 (" + totalSec.toFixed(2) + "s)";
                    if (wTot.value !== tot) { wTot.value = tot; if (wTot.inputEl) wTot.inputEl.value = tot; if (wTot.element) wTot.element.value = tot; }
                }
            };

            // ============================================================
            // 绘制
            // ============================================================
            const drawWave = (cvs, t) => {
                const ctx = cvs.getContext("2d"), W = cvs.width / dpr, H = cvs.height / dpr;
                ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
                ctx.clearRect(0, 0, W, H); ctx.fillStyle = "#111"; ctx.fillRect(0, 0, W, H);
                const d = getD(t), s = getS(t), e = getE(t), sx = tToX(s, cvs, t) / dpr, ex = tToX(e, cvs, t) / dpr;
                const ww = W - PAD * 2, mid = H / 2, nBars = 100, barW = Math.max(2, ww / nBars);
                for (let i = 0; i < nBars; i++) {
                    const x = PAD + (i / nBars) * ww, amp = Math.abs(Math.sin(i * 0.5) * Math.cos(i * 0.13) * Math.sin(i * 0.07 + 1.8));
                    const bh = Math.max(1, amp * H * 0.48);
                    ctx.fillStyle = (x >= sx && x <= ex) ? "#4FC3F7" : "rgba(79,195,247,0.12)";
                    ctx.fillRect(x, mid - bh, Math.max(1, barW - 0.5), bh * 2);
                }
                ctx.fillStyle = "rgba(76,175,80,0.08)"; ctx.fillRect(sx, 0, ex - sx, H);
                [sx, ex].forEach((x, i) => {
                    const c = i === 0 ? "#4CAF50" : "#F44336";
                    ctx.strokeStyle = c; ctx.lineWidth = 2.5; ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke();
                    ctx.fillStyle = c; ctx.beginPath(); ctx.moveTo(x, 2); ctx.lineTo(x - 6, -5); ctx.lineTo(x + 6, -5); ctx.closePath(); ctx.fill();
                });
                ctx.fillStyle = "#555"; ctx.font = "8px sans-serif"; ctx.textAlign = "center";
                const step = Math.max(1, Math.floor(d / 5));
                for (let t2 = 0; t2 <= d + 0.01; t2 += step) ctx.fillText(t2.toFixed(1) + "s", tToX(t2, cvs, t) / dpr, H - 3);
                ctx.setTransform(1, 0, 0, 1, 0, 0);
            };

            // ============================================================
            // Canvas 鼠标
            // ============================================================
            const bindMouse = (cvs, t) => {
                cvs.onmousedown = (ev) => { if (getD(t) <= 0) return; const mx = mouseToX(ev.clientX, cvs), sxPx = tToX(getS(t), cvs, t), exPx = tToX(getE(t), cvs, t); activeTrack = t; if (Math.abs(mx - sxPx) < HANDLE_HIT) drag = "start"; else if (Math.abs(mx - exPx) < HANDLE_HIT) drag = "end"; else if (mx > sxPx + HANDLE_HIT && mx < exPx - HANDLE_HIT) { drag = "range"; drs = getS(t); dre = getE(t); } };
                cvs.onmousemove = (ev) => {
                    if (getD(activeTrack) <= 0) return;
                    if (drag) {
                        const tv = xToT(mouseToX(ev.clientX, cvs), cvs, activeTrack), s = getS(activeTrack), e = getE(activeTrack), d = getD(activeTrack), ws = activeTrack === 1 ? wS1 : wS2, we = activeTrack === 1 ? wE1 : wE2;
                        const fps = parseFloat(wFps?.value) || 25;
                        const fDur = 1.0 / fps;
                        const snap = (v) => Math.round(v * fps) / fps;
                        if (drag === "start") ws.value = snap(Math.max(0, Math.min(tv, e - fDur)));
                        else if (drag === "end") we.value = snap(Math.min(d, Math.max(tv, s + fDur)));
                        else { const dx = tv - (drs + dre) / 2; let ns = drs + dx, ne = dre + dx; if (ns < 0) { ne -= ns; ns = 0; } if (ne > d) { ns -= ne - d; ne = d; } ws.value = snap(Math.max(0, ns)); we.value = snap(Math.min(d, ne)); }
                        syncW(activeTrack); drawWave(cvs, activeTrack);
                    }
                };
            };
            bindMouse(canvas1, 1); bindMouse(canvas2, 2);
            window.addEventListener("mouseup", () => { drag = null; });

            // ============================================================
            // 音频播放
            // ============================================================
            const updateSrc = (ael, w, t, _last) => {
                const f = w?.value;
                if (f && f !== "none" && f !== _last) {
                    if (t === 1) _last1 = f; else _last2 = f;
                    ael.src = api.apiURL("/view?" + new URLSearchParams({ filename: f, type: "input", t: Date.now() }));
                }
            };
            const bindAudio = (ael, t) => {
                ael.addEventListener("loadedmetadata", () => { if (t === 1) dur1 = ael.duration; else dur2 = ael.duration; const e = getE(t), d = getD(t); if (e <= 0 || e > d + 1) { const we = t === 1 ? wE1 : wE2; const fps = parseFloat(wFps?.value) || 25; we.value = Math.round(d * fps) / fps; } syncW(t); drawWave(t === 1 ? canvas1 : canvas2, t); ael.currentTime = getS(t); });
                ael.addEventListener("play", () => { const s = getS(t); if (ael.currentTime < s || ael.currentTime >= getE(t)) ael.currentTime = s; });
                ael.addEventListener("timeupdate", () => { if (pausing) return; if (ael.currentTime >= getE(t)) { pausing = true; ael.pause(); ael.currentTime = getS(t); setTimeout(() => { pausing = false; }, 100); } });
                ael.addEventListener("seeking", () => { const s = getS(t), e = getE(t); if (ael.currentTime < s) ael.currentTime = s; if (ael.currentTime > e) ael.currentTime = e; });
            };
            bindAudio(audioEl1, 1); bindAudio(audioEl2, 2);

            // ============================================================
            // 回调
            // ============================================================
            const onTimeChange = (t) => { syncW(t); drawWave(t === 1 ? canvas1 : canvas2, t); const ael = t === 1 ? audioEl1 : audioEl2; if (ael.readyState >= 1) ael.currentTime = getS(t); };
            [wA1, wA2].forEach((w, i) => { if (w) { const o = w.callback; w.callback = function () { o?.apply(this, arguments); updateSrc(i === 0 ? audioEl1 : audioEl2, w, i + 1, i === 0 ? _last1 : _last2); }; } });
            [wS1, wE1].forEach(w => { if (w) { const o = w.callback; w.callback = function () { o?.apply(this, arguments); onTimeChange(1); }; } });
            [wS2, wE2].forEach(w => { if (w) { const o = w.callback; w.callback = function () { o?.apply(this, arguments); onTimeChange(2); }; } });
            if (wGap) { const o = wGap.callback; wGap.callback = function () { o?.apply(this, arguments); syncW(1); syncW(2); }; }

            setInterval(() => { if (dur1 > 0 || dur2 > 0) { syncW(1); syncW(2); drawWave(canvas1, 1); drawWave(canvas2, 2); } }, 150);
            setTimeout(() => { updateSrc(audioEl1, wA1, 1, _last1); updateSrc(audioEl2, wA2, 2, _last2); }, 400);

            const oo = node.onRemoved;
            node.onRemoved = () => { oo?.apply(node); };
        };
    }
});
