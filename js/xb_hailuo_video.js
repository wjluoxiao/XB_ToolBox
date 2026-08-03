/**
 * XB_HailuoH3VideoParams — 海螺H3视频参数 UI
 * =============================================
 * 分辨率：官方 ResolutionSelector 公式（MP × 1024² → sqrt → round/multiple）
 * 时间调节替代帧数，帧数估算替代时长。
 */

import { app } from "../../scripts/app.js";

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
    name: "xiaobai.hailuo.h3params",

    async nodeCreated(node) {
        if (node.comfyClass !== "XB_HailuoH3VideoParams") return;

        const wF = node.widgets?.find(w => w.name === "fps");
        const wFF = node.widgets?.find(w => w.name === "fps_float");
        const wDur = node.widgets?.find(w => w.name === "duration");

        // fps ↔ fps_float 双向同步
        if (wF && wFF) {
            const of = wF.callback; wF.callback = function (v) {
                if (of) of.apply(this, arguments); if (node._xb_syncing || node._xb_from_polling) return;
                const val = Math.round(Number(v)); if (wFF.value !== val) { node._xb_syncing = true; wFF.value = val; xb_dispatch(wFF, val); node._xb_syncing = false; }
            };
            const off = wFF.callback; wFF.callback = function (v) {
                if (off) off.apply(this, arguments); if (node._xb_syncing || node._xb_from_polling) return;
                const val = Math.round(Number(v)); if (wF.value !== val) { node._xb_syncing = true; wF.value = val; xb_dispatch(wF, val); node._xb_syncing = false; }
            };
        }

        // duration 步长 = 0.5
        if (wDur) {
            node._xb_last_dur = parseFloat(wDur.value) || 3.5;
            const od = wDur.callback; wDur.callback = function (v) {
                if (od) od.apply(this, arguments);
                if (node._xb_syncing || node._xb_from_polling) return;
                let d = parseFloat(v) || 1.0;
                d = Math.round(d);
                d = Math.max(1.0, Math.min(300.0, d));
                if (wDur.value !== d) { node._xb_syncing = true; wDur.value = d; xb_dispatch(wDur, d); node._xb_syncing = false; }
                node._xb_last_dur = d;
            };
        }
    },

    init() {
        setInterval(() => {
            if (!app.graph || !app.graph._nodes) return;

            for (const node of app.graph._nodes) {
                if (node.comfyClass !== "XB_HailuoH3VideoParams" || !node.widgets) continue;

                const wRatio = node.widgets.find(w => w.name === "aspect_ratio");
                const wMP = node.widgets.find(w => w.name === "megapixels");
                const wMul = node.widgets.find(w => w.name === "multiple");
                const wDisp = node.widgets.find(w => w.name === "frames_display");
                const wDur = node.widgets.find(w => w.name === "duration");
                const wFps = node.widgets.find(w => w.name === "fps");
                const wFpsF = node.widgets.find(w => w.name === "fps_float");

                if (!wDisp || !wDur || !wFps || !wFpsF || !wRatio || !wMP || !wMul) continue;

                node._xb_from_polling = true;

                // Style frames_display
                let dispEl = wDisp.inputEl || wDisp.element;
                if (dispEl && dispEl.style && dispEl.style.backgroundColor !== "rgb(34, 34, 34)") {
                    dispEl.readOnly = true;
                    dispEl.style.backgroundColor = "#222222";
                    dispEl.style.color = "#00FF00";
                    dispEl.style.textAlign = "center";
                    dispEl.style.fontWeight = "bold";
                }
                wFpsF.options.precision = 2;

                if (node._xb_last_ratio === undefined) {
                    node._xb_last_ratio = wRatio.value;
                    node._xb_last_mp = parseFloat(wMP.value) || 1.0;
                    node._xb_last_mul = parseInt(wMul.value, 10) || 16;
                    node._xb_last_fps = wFps.value;
                    node._xb_last_fps_float = wFpsF.value;
                }

                let needsUpdate = false;

                // Resolution Selector formula: W × H
                const ratioMap = {
                    "1:1 (Square)": [1, 1],
                    "2:3 (Portrait Photo)": [2, 3],
                    "3:2 (Photo)": [3, 2],
                    "3:4 (Portrait Standard)": [3, 4],
                    "4:3 (Standard)": [4, 3],
                    "9:16 (Portrait Widescreen)": [9, 16],
                    "16:9 (Widescreen)": [16, 9],
                    "21:9 (Ultrawide)": [21, 9],
                };
                const [wr, hr] = ratioMap[wRatio.value] || [16, 9];
                const mp = parseFloat(wMP.value) || 1.0;
                const mul = parseInt(wMul.value, 10) || 16;
                const totalPx = mp * 1024 * 1024;
                const sc = Math.sqrt(totalPx / (wr * hr));
                const calcW = Math.round(wr * sc / mul) * mul;
                const calcH = Math.round(hr * sc / mul) * mul;

                // fps sync
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

                // duration snap
                let dur = parseFloat(wDur.value) || 1.0;
                dur = Math.round(dur);
                dur = Math.max(1.0, Math.min(300.0, dur));
                if (wDur.value !== dur) {
                    wDur.value = dur;
                    xb_dispatch(wDur, dur);
                    needsUpdate = true;
                }

                // Frames from duration
                const base = Math.max(5, Math.round(dur * 24));
                const frames = base + ((5 - (base % 17) + 17) % 17);

                // Display: "1024 × 576 | 估算帧数: 73"
                const resText = `${calcW} × ${calcH}`;
                const framesText = isZH ? `估算帧数: ${frames}` : `Frames: ${frames}`;
                const expectedText = `${resText}  |  ${framesText}`;
                if (wDisp.value !== expectedText) {
                    wDisp.value = expectedText;
                    xb_dispatch(wDisp, expectedText);
                    let dEl = wDisp.inputEl || wDisp.element;
                    if (dEl && dEl.style) dEl.style.color = "#00FF00";
                    needsUpdate = true;
                }

                if (needsUpdate) app.graph.setDirtyCanvas(true, true);
                node._xb_from_polling = false;
            }
        }, 250);
    },
});
