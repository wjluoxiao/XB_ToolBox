import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// ============================================================
// XB_AudioSlicer — 复刻 VHS 加载音频 + 结束时间 + 自动时长
// ============================================================

app.registerExtension({
    name: "XB_ToolBox.AudioSlicer",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "XB_AudioSlicer") return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            if (onNodeCreated) onNodeCreated.apply(this, arguments);
            const node = this;

            const wAudio = node.widgets.find(w => w.name === "audio");
            const wFps   = node.widgets.find(w => w.name === "fps");
            const wStart = node.widgets.find(w => w.name === "start_time");
            const wEnd   = node.widgets.find(w => w.name === "end_time");
            const wDur   = node.widgets.find(w => w.name === "duration_display");

            // ============================================================
            // 1. 时长显示设为只读+绿色样式
            // ============================================================
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
            // 2. 上传按钮 (VHS addWidget 模式)
            // ============================================================
            if (wAudio) {
                const fileInput = document.createElement("input");
                Object.assign(fileInput, {
                    type: "file",
                    accept: "audio/*,video/*",
                    style: "display: none",
                    onchange: async () => {
                        if (!fileInput.files.length) return;
                        const file = fileInput.files[0];
                        try {
                            const body = new FormData();
                            body.append("image", file);
                            const resp = await api.fetchApi("/upload/image", { method: "POST", body });
                            if (resp.status === 200) {
                                const data = await resp.json();
                                const name = data.name || file.name;
                                if (!wAudio.options.values.includes(name))
                                    wAudio.options.values.push(name);
                                wAudio.value = name;
                                if (wAudio.callback) wAudio.callback(name);
                            }
                        } catch (err) {
                            console.error("[XB_AudioSlicer] 上传失败:", err);
                        }
                    }
                });
                document.body.appendChild(fileInput);
                node.onRemoved = (() => {
                    const orig = node.onRemoved;
                    return () => { fileInput?.remove(); orig?.apply(node); };
                })();

                const uploadBtn = node.addWidget("button", "选择音频上传", "image", () => {
                    app.canvas.node_widget = null;
                    fileInput.click();
                });
                uploadBtn.options.serialize = false;
            }

            // ============================================================
            // 3. 音频播放器 — 限制在 start_time ~ end_time 范围
            // ============================================================
            const playerContainer = document.createElement("div");
            Object.assign(playerContainer.style, {
                width: "100%", padding: "4px 0", boxSizing: "border-box"
            });

            const audioEl = document.createElement("audio");
            audioEl.controls = true;
            audioEl.style.cssText = "width:100%;height:36px;outline:none;";
            playerContainer.appendChild(audioEl);

            const domWidget = node.addDOMWidget("xb_player", "custom", playerContainer);
            domWidget.computeSize = function () { return [node.size[0] - 16, 52]; };

            // --- 扩展节点初始高度 ---
            if (node.size[1] < 280) node.size[1] = 280;

            // --- 限制播放范围 ---
            audioEl.addEventListener("loadedmetadata", () => {
                const st = parseFloat(wStart?.value) || 0;
                if (st > 0 && st < audioEl.duration) {
                    audioEl.currentTime = st;
                }
                // 首次加载时自动设置 end_time = 全长（对齐到帧）
                if (audioEl.duration > 0) {
                    const fps = parseFloat(wFps?.value) || 25;
                    const et = parseFloat(wEnd?.value) || 0;
                    if (et <= 0 || et > audioEl.duration + 1) {
                        const r = Math.floor(audioEl.duration * fps) / fps;
                        wEnd.value = r;
                        if (wEnd.inputEl) wEnd.inputEl.value = r;
                        if (wEnd.element) wEnd.element.value = r;
                    }
                }
                updateDuration();
            });

            // 播放时限制在范围内；到达 end_time 后自动暂停并重置到 start_time
            audioEl.addEventListener("timeupdate", () => {
                const et = parseFloat(wEnd?.value) || audioEl.duration;
                if (audioEl.currentTime >= et) {
                    audioEl.pause();
                    const st = parseFloat(wStart?.value) || 0;
                    audioEl.currentTime = st;  // 重置到开头，下次点击播放从头开始
                }
            });

            // 禁止拖拽进度条超过 end_time 或低于 start_time
            audioEl.addEventListener("seeking", () => {
                const et = parseFloat(wEnd?.value) || audioEl.duration;
                const st = parseFloat(wStart?.value) || 0;
                if (audioEl.currentTime > et) audioEl.currentTime = et;
                if (audioEl.currentTime < st) audioEl.currentTime = st;
            });

            // --- 更新音频源（同一文件不重复加载）---
            let _xb_lastAudioFile = null;
            const updateAudioSrc = () => {
                const f = wAudio?.value;
                if (f && f !== "none") {
                    if (f === _xb_lastAudioFile && audioEl.src && audioEl.readyState > 0) {
                        playerContainer.style.display = "";
                        return;  // 同一文件，已在播放，不重置
                    }
                    _xb_lastAudioFile = f;
                    audioEl.src = api.apiURL("/view?" + new URLSearchParams({
                        filename: f, type: "input", t: Date.now()
                    }));
                    playerContainer.style.display = "";
                } else {
                    playerContainer.style.display = "none";
                }
            };

            // ============================================================
            // 4. 帧数自动计算
            // ============================================================
            const updateDuration = () => {
                let s = parseFloat(wStart?.value) || 0;
                let e = parseFloat(wEnd?.value) || 0;
                const fps = parseFloat(wFps?.value) || 25;
                const fDur = 1.0 / fps;
                // 防止 end_time < start_time + 1帧
                if (e < s + fDur) {
                    e = s + fDur;
                    wEnd.value = e;
                    if (wEnd.inputEl) wEnd.inputEl.value = e;
                    if (wEnd.element) wEnd.element.value = e;
                }
                const durSec = Math.max(0, e - s);
                const rawFrames = Math.round(durSec * fps);
                const frames = Math.max(1, Math.floor((rawFrames + 2) / 4) * 4 + 1);
                const txt = frames + " 帧 (" + durSec.toFixed(2) + "s)";
                if (wDur && wDur.value !== txt) {
                    wDur.value = txt;
                    if (wDur.inputEl) wDur.inputEl.value = txt;
                    if (wDur.element) wDur.element.value = txt;
                }
            };

            // --- start/end 变化 → 同步播放器位置 ---
            const onTimeWidgetChange = () => {
                // 防止 end < start + 1帧
                let s = parseFloat(wStart?.value) || 0;
                let e = parseFloat(wEnd?.value) || 0;
                const fps = parseFloat(wFps?.value) || 25;
                const fDur = 1.0 / fps;
                if (e < s + fDur) {
                    e = s + fDur;
                    wEnd.value = e;
                    if (wEnd.inputEl) wEnd.inputEl.value = e;
                    if (wEnd.element) wEnd.element.value = e;
                }
                updateDuration();
                if (audioEl.readyState >= 1)
                    audioEl.currentTime = s;
            };
            if (wStart) {
                const origSCb = wStart.callback;
                wStart.callback = function () { origSCb?.apply(this, arguments); onTimeWidgetChange(); };
            }
            if (wEnd) {
                const origECb = wEnd.callback;
                wEnd.callback = function () { origECb?.apply(this, arguments); onTimeWidgetChange(); };
            }

            // ============================================================
            // 5. 音频选择变化 → 更新播放器源
            // ============================================================
            if (wAudio) {
                const origAudioCb = wAudio.callback;
                wAudio.callback = function () {
                    if (origAudioCb) origAudioCb.apply(this, arguments);
                    updateAudioSrc();
                    updateDuration();
                };
            }

            // ============================================================
            // 6. 定时同步 + 初始加载
            // ============================================================
            node._xb_interval = setInterval(updateDuration, 100);

            setTimeout(() => {
                updateAudioSrc();
            }, 400);

            node.onRemoved = (() => {
                const orig = node.onRemoved;
                return () => {
                    clearInterval(node._xb_interval);
                    orig?.apply(node);
                };
            })();
        };
    }
});
