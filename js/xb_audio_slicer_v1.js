import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// ============================================================
// XB_AudioSlicerV2 — 通用波形 + 双拖拽线 + 时长数字
// ============================================================

const PAD = 10, HANDLE_HIT = 16;

app.registerExtension({
    name: "XB_ToolBox.AudioSlicerV2",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "XB_AudioSlicerV1") return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            if (onNodeCreated) onNodeCreated.apply(this, arguments);
            const node = this;

            const wAudio = node.widgets.find(w => w.name === "audio");
            const wStart = node.widgets.find(w => w.name === "start_time");
            const wEnd   = node.widgets.find(w => w.name === "end_time");
            const wDur   = node.widgets.find(w => w.name === "duration_display");

            // --- 时长窗口设为只读+绿色样式 ---
            if (wDur) {
                setTimeout(() => {
                    const el = wDur.inputEl || wDur.element;
                    if (el) {
                        el.readOnly = true;
                        el.style.backgroundColor = "#1a1a1a";
                        el.style.color = "#00E676";
                        el.style.textAlign = "center";
                        el.style.fontWeight = "bold";
                        el.style.fontSize = "13px";
                    }
                }, 100);
            }

            // ============================================================
            // 1. 上传按钮
            // ============================================================
            if (wAudio) {
                const fi = document.createElement("input");
                fi.type = "file"; fi.accept = "audio/*,video/*"; fi.style.display = "none";
                fi.onchange = async () => {
                    if (!fi.files.length) return;
                    const body = new FormData(); body.append("image", fi.files[0]);
                    const resp = await api.fetchApi("/upload/image", { method: "POST", body });
                    if (resp.status === 200) {
                        const d = await resp.json();
                        const n = d.name || fi.files[0].name;
                        if (!wAudio.options.values.includes(n)) wAudio.options.values.push(n);
                        wAudio.value = n;
                        if (wAudio.callback) wAudio.callback(n);
                    }
                };
                document.body.appendChild(fi);
                const btn = node.addWidget("button", "选择音频上传", "image", () => { app.canvas.node_widget = null; fi.click(); });
                btn.options.serialize = false;
                const o1 = node.onRemoved;
                node.onRemoved = () => { fi?.remove(); o1?.apply(node); };
            }

            // ============================================================
            // 2. 容器
            // ============================================================
            const ctr = document.createElement("div");
            Object.assign(ctr.style, { display:"flex", flexDirection:"column", gap:"6px", width:"100%", padding:"6px", boxSizing:"border-box", background:"#161616", borderRadius:"6px", color:"#ccc", fontFamily:"sans-serif", marginTop:"4px" });

            const audioEl = document.createElement("audio");
            audioEl.controls = true;
            audioEl.style.cssText = "width:100%;height:34px;outline:none;";
            ctr.appendChild(audioEl);

            // Canvas — 高度 30%，波形填满
            const canvas = document.createElement("canvas");
            canvas.style.cssText = "width:100%;height:40px;border-radius:4px;background:#111;cursor:pointer;display:block;";
            const dpr = window.devicePixelRatio || 1;
            canvas.width = 1200 * dpr; canvas.height = 80 * dpr;
            ctr.appendChild(canvas);

            const domWidget = node.addDOMWidget("xb2_ui", "custom", ctr);
            domWidget.computeSize = () => [node.size[0] - 16, 100];
            if (node.size[1] < 270) node.size[1] = 270;

            // ============================================================
            // 3. 状态
            // ============================================================
            let totalDur = 0, dragging = null, dragRS = 0, dragRE = 0, _lastFile = null, _pausing = false;

            // ============================================================
            // 4. 辅助函数
            // ============================================================
            const getDur = () => totalDur || 10;
            const getS = () => parseFloat(wStart?.value) || 0;
            const getE = () => { const e = parseFloat(wEnd?.value); return e > 0 ? e : getDur(); };

            // 关键修复：鼠标坐标转换为 Canvas 像素坐标（处理 CSS 缩放）
            const mouseToCanvasX = (clientX) => {
                const rect = canvas.getBoundingClientRect();
                return (clientX - rect.left) * (canvas.width / rect.width);
            };

            const xToTime = (canvasX) => {
                const dur = getDur();
                const ww = canvas.width - PAD * 2;
                return Math.max(0, Math.min(dur, ((canvasX - PAD) / ww) * dur));
            };

            const timeToX = (t) => {
                const dur = getDur();
                const ww = canvas.width - PAD * 2;
                return PAD + (t / dur) * ww;
            };

            const syncWidgets = () => {
                let s = getS(), e = getE();
                // 防止 end_time < start_time
                if (e < s + 0.01) e = s + 0.01;
                const dur = getDur();
                if (e > dur) e = dur;
                if (wStart.value !== s) wStart.value = s;
                if (wEnd.value !== e) wEnd.value = e;
                if (wStart.inputEl) wStart.inputEl.value = s;
                if (wEnd.inputEl)   wEnd.inputEl.value   = e;
                if (wStart.element) wStart.element.value = s;
                if (wEnd.element)   wEnd.element.value   = e;
                // 同步 duration_display
                if (wDur) {
                    const d = Math.max(0, e - s).toFixed(2);
                    const txt = d + " s";
                    if (wDur.value !== txt) {
                        wDur.value = txt;
                        if (wDur.inputEl) wDur.inputEl.value = txt;
                        if (wDur.element) wDur.element.value = txt;
                    }
                }
            };

            // ============================================================
            // 5. 绘制
            // ============================================================
            const draw = () => {
                const ctx = canvas.getContext("2d");
                const w = canvas.width, h = canvas.height;
                ctx.setTransform(dpr, 0, 0, dpr, 0, 0); // 适配 devicePixelRatio
                const W = w / dpr, H = h / dpr;
                ctx.clearRect(0, 0, W, H);

                ctx.fillStyle = "#111";
                ctx.fillRect(0, 0, W, H);

                const dur = getDur(), s = getS(), e = getE();
                const sx = timeToX(s) / dpr, ex = timeToX(e) / dpr;
                const ww = (W - PAD * 2), mid = H / 2;

                // 通用波形（填满高度）
                const nBars = 100;
                const barW = Math.max(2, ww / nBars);
                for (let i = 0; i < nBars; i++) {
                    const x = PAD + (i / nBars) * ww;
                    const amp = Math.abs(Math.sin(i * 0.4) * Math.cos(i * 0.15) * Math.sin(i * 0.08 + 1.2));
                    const bh = Math.max(1, amp * H * 0.49);  // 填满 98% 高度
                    const inSel = x >= sx && x <= ex;
                    ctx.fillStyle = inSel ? "#4FC3F7" : "rgba(79,195,247,0.15)";
                    ctx.fillRect(x, mid - bh, Math.max(1, barW - 0.5), bh * 2);
                }

                // 选中高亮
                ctx.fillStyle = "rgba(76,175,80,0.08)";
                ctx.fillRect(sx, 0, ex - sx, H);

                // 刻度
                ctx.fillStyle = "#555";
                ctx.font = "9px sans-serif";
                ctx.textAlign = "center";
                const step = Math.max(1, Math.floor(dur / 6));
                for (let t = 0; t <= dur + 0.01; t += step) {
                    const tx = timeToX(t) / dpr;
                    ctx.fillText(t.toFixed(1) + "s", tx, H - 3);
                }

                // 拖拽线
                [sx, ex].forEach((x, i) => {
                    const c = i === 0 ? "#4CAF50" : "#F44336";
                    ctx.strokeStyle = c; ctx.lineWidth = 3;
                    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke();
                    ctx.fillStyle = c;
                    ctx.beginPath(); ctx.moveTo(x, 3); ctx.lineTo(x - 7, -6); ctx.lineTo(x + 7, -6); ctx.closePath(); ctx.fill();
                    ctx.beginPath(); ctx.moveTo(x, H - 3); ctx.lineTo(x - 7, H + 6); ctx.lineTo(x + 7, H + 6); ctx.closePath(); ctx.fill();
                });

                // 时长数字
                const outDur = Math.max(0, e - s).toFixed(2);
                ctx.fillStyle = "#00E676";
                ctx.font = "bold 13px sans-serif";
                ctx.textAlign = "right";
                ctx.fillText(outDur + " s", W - PAD, 16);

                ctx.setTransform(1, 0, 0, 1, 0, 0); // 恢复
            };

            // ============================================================
            // 6. 鼠标交互（所有坐标都转 canvas 像素）
            // ============================================================
            canvas.onmousedown = (ev) => {
                if (totalDur <= 0) return;
                const mx = mouseToCanvasX(ev.clientX);
                const sxPx = timeToX(getS()), exPx = timeToX(getE());

                if (Math.abs(mx - sxPx) < HANDLE_HIT) dragging = "start";
                else if (Math.abs(mx - exPx) < HANDLE_HIT) dragging = "end";
                else if (mx > sxPx + HANDLE_HIT && mx < exPx - HANDLE_HIT) {
                    dragging = "range"; dragRS = getS(); dragRE = getE();
                }
            };

            canvas.onmousemove = (ev) => {
                if (totalDur <= 0) return;
                if (dragging) {
                    const t = xToTime(mouseToCanvasX(ev.clientX));
                    const s = getS(), e = getE(), dur = getDur();

                    if (dragging === "start")
                        wStart.value = Math.round(Math.max(0, Math.min(t, e - 0.01)) * 100) / 100;
                    else if (dragging === "end")
                        wEnd.value = Math.round(Math.min(dur, Math.max(t, s + 0.01)) * 100) / 100;
                    else if (dragging === "range") {
                        const dx = t - (dragRS + dragRE) / 2;
                        let ns = dragRS + dx, ne = dragRE + dx;
                        if (ns < 0) { ne -= ns; ns = 0; }
                        if (ne > dur) { ns -= ne - dur; ne = dur; }
                        wStart.value = Math.round(Math.max(0, ns) * 100) / 100;
                        wEnd.value = Math.round(Math.min(dur, ne) * 100) / 100;
                    }
                    syncWidgets(); draw();
                } else {
                    const mx = mouseToCanvasX(ev.clientX);
                    const sxPx = timeToX(getS()), exPx = timeToX(getE());
                    canvas.style.cursor = Math.abs(mx - sxPx) < HANDLE_HIT || Math.abs(mx - exPx) < HANDLE_HIT ? "ew-resize"
                        : (mx > sxPx && mx < exPx) ? "grab" : "default";
                }
            };

            window.addEventListener("mouseup", () => { dragging = null; });

            // ============================================================
            // 7. 音频 — 播放范围限制
            // ============================================================
            const updateSrc = () => {
                const f = wAudio?.value;
                if (f && f !== "none" && f !== _lastFile) {
                    _lastFile = f;
                    totalDur = 0;
                    audioEl.src = api.apiURL("/view?" + new URLSearchParams({ filename: f, type: "input", t: Date.now() }));
                }
            };

            audioEl.addEventListener("loadedmetadata", () => {
                totalDur = audioEl.duration;
                if (getE() <= 0 || getE() > totalDur) {
                    wEnd.value = Math.round(totalDur * 100) / 100;
                    syncWidgets();
                }
                // 跳到 start_time
                const st = getS();
                if (st > 0) audioEl.currentTime = st;
                draw();
            });

            // 每次点击播放时确保从 start_time 开始
            audioEl.addEventListener("play", () => {
                _pausing = false;
                const st = getS(), et = getE();
                if (audioEl.currentTime < st || audioEl.currentTime >= et)
                    audioEl.currentTime = st;
            });

            audioEl.addEventListener("timeupdate", () => {
                if (_pausing) return;
                const et = getE();
                if (audioEl.currentTime >= et) {
                    _pausing = true;
                    audioEl.pause();
                    audioEl.currentTime = getS();
                    setTimeout(() => { _pausing = false; }, 100);
                }
            });

            audioEl.addEventListener("seeking", () => {
                const st = getS(), et = getE();
                if (audioEl.currentTime < st) audioEl.currentTime = st;
                if (audioEl.currentTime > et) audioEl.currentTime = et;
            });

            // ============================================================
            // 8. Widget 回调 + 初始化
            // ============================================================
            if (wAudio) {
                const orig = wAudio.callback;
                wAudio.callback = function () { orig?.apply(this, arguments); updateSrc(); };
            }
            // start/end 变化 → 同步播放器位置和波形
            const onTimeChange = () => {
                // 防止 end < start
                let s = getS(), e = getE(), dur = getDur();
                if (e < s + 0.01) { e = Math.min(s + 0.01, dur); wEnd.value = e; }
                syncWidgets(); draw();
                if (audioEl.readyState >= 1)
                    audioEl.currentTime = s;
            };
            if (wStart) {
                const orig = wStart.callback;
                wStart.callback = function () { orig?.apply(this, arguments); onTimeChange(); };
            }
            if (wEnd) {
                const orig = wEnd.callback;
                wEnd.callback = function () { orig?.apply(this, arguments); onTimeChange(); };
            }

            setInterval(() => { if (totalDur > 0) { syncWidgets(); draw(); } }, 150);
            setTimeout(() => updateSrc(), 400);

            const o2 = node.onRemoved;
            node.onRemoved = () => { o2?.apply(node); };
        };
    }
});
