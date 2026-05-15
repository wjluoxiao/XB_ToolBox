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
    name: "xiaobai.mediaparams.split",
    init() {
        setInterval(() => {
            if (!app.graph || !app.graph._nodes) return;
            
            for (const node of app.graph._nodes) {
                if (node.comfyClass === "XB_VideoParamsMaster" && node.widgets) {
                    const wRatio = node.widgets.find(w => w.name === "aspect_ratio");
                    const wDisp = node.widgets.find(w => w.name === "duration_display");
                    const wLen = node.widgets.find(w => w.name === "length");
                    const wFps = node.widgets.find(w => w.name === "fps");
                    const wFpsF = node.widgets.find(w => w.name === "fps_float");
                    const wWidth = node.widgets.find(w => w.name === "width");
                    const wHeight = node.widgets.find(w => w.name === "height");
                    
                    if (wDisp && wLen && wFps && wFpsF && wWidth && wHeight && wRatio) {
                        let dispEl = wDisp.inputEl || wDisp.element;
                        if (dispEl && dispEl.style && dispEl.style.backgroundColor !== "rgb(34, 34, 34)") {
                            dispEl.readOnly = true;
                            dispEl.style.backgroundColor = "#222222";
                            dispEl.style.color = "#00FF00";
                            dispEl.style.textAlign = "center";
                            dispEl.style.fontWeight = "bold";
                        }
                        wFpsF.options.precision = 2;

                        if (node._xb_last_fps === undefined) {
                            node._xb_last_fps = wFps.value;
                            node._xb_last_fps_float = wFpsF.value;
                            node._xb_last_length = parseInt(wLen.value, 10) || 1;
                            node._xb_last_width = parseInt(wWidth.value, 10) || 1024;
                            node._xb_last_height = parseInt(wHeight.value, 10) || 1024;
                            node._xb_last_ratio = wRatio.value;
                        }
                        
                        let needsUpdate = false;
                        let valRatio = wRatio.value;
                        let isFree = valRatio.includes("Free");
                        let rChanged = valRatio !== node._xb_last_ratio;
                        let isGoldenZone = (valRatio === "16:9" || valRatio === "9:16");
                        
                        let currentStep = isGoldenZone ? 1 : (isFree ? 1 : 16);
                        wWidth.options.step = currentStep; wHeight.options.step = currentStep;
                        if (wWidth.inputEl) wWidth.inputEl.step = currentStep; else if (wWidth.element) wWidth.element.step = currentStep;
                        if (wHeight.inputEl) wHeight.inputEl.step = currentStep; else if (wHeight.element) wHeight.element.step = currentStep;

                        let wid = parseInt(wWidth.value, 10) || currentStep;
                        let hei = parseInt(wHeight.value, 10) || currentStep;
                        let wChanged = wid !== node._xb_last_width;
                        let hChanged = hei !== node._xb_last_height;

                        if (wChanged || hChanged || rChanged) {
                            if (isGoldenZone) {
                                const goldenBuckets = {
                                    "16:9": [ {w: 832, h: 480}, {w: 960, h: 544}, {w: 1280, h: 720}, {w: 1920, h: 1088} ],
                                    "9:16": [ {w: 480, h: 832}, {w: 544, h: 960}, {w: 720, h: 1280}, {w: 1088, h: 1920} ]
                                };
                                let buckets = goldenBuckets[valRatio];
                                
                                if (rChanged) {
                                    wid = buckets[0].w; hei = buckets[0].h; 
                                } else if (wChanged || hChanged) {
                                    let wDelta = wid - node._xb_last_width;
                                    let hDelta = hei - node._xb_last_height;
                                    let currIdx = buckets.findIndex(b => b.w === node._xb_last_width && b.h === node._xb_last_height);
                                    if (currIdx === -1) currIdx = 0;

                                    if (wChanged) {
                                        if (wDelta === 1) currIdx = Math.min(currIdx + 1, buckets.length - 1);
                                        else if (wDelta === -1) currIdx = Math.max(currIdx - 1, 0);
                                        else {
                                            let closest = buckets.reduce((prev, curr) => Math.abs(curr.w - wid) < Math.abs(prev.w - wid) ? curr : prev);
                                            currIdx = buckets.indexOf(closest);
                                        }
                                    } else if (hChanged) {
                                        if (hDelta === 1) currIdx = Math.min(currIdx + 1, buckets.length - 1);
                                        else if (hDelta === -1) currIdx = Math.max(currIdx - 1, 0);
                                        else {
                                            let closest = buckets.reduce((prev, curr) => Math.abs(curr.h - hei) < Math.abs(prev.h - hei) ? curr : prev);
                                            currIdx = buckets.indexOf(closest);
                                        }
                                    }
                                    wid = buckets[currIdx].w;
                                    hei = buckets[currIdx].h;
                                }
                            } else {
                                const ratioMap = {
                                    "1:1": 1.0, "16:9": 16.0 / 9.0, "9:16": 9.0 / 16.0,
                                    "4:3": 4.0 / 3.0, "3:4": 3.0 / 4.0, "21:9": 21.0 / 9.0
                                };
                                let currentRatio = ratioMap[valRatio];

                                if (wChanged && wid % currentStep !== 0) {
                                    wid = wid > node._xb_last_width ? Math.ceil(wid / currentStep) * currentStep : Math.floor(wid / currentStep) * currentStep;
                                } else { wid = Math.round(wid / currentStep) * currentStep; }
                                wid = Math.max(currentStep, wid);

                                if (hChanged && hei % currentStep !== 0) {
                                    hei = hei > node._xb_last_height ? Math.ceil(hei / currentStep) * currentStep : Math.floor(hei / currentStep) * currentStep;
                                } else { hei = Math.round(hei / currentStep) * currentStep; }
                                hei = Math.max(currentStep, hei);

                                if (currentRatio) {
                                    if (rChanged || wChanged) {
                                        hei = Math.round((wid / currentRatio) / currentStep) * currentStep;
                                        hei = Math.max(currentStep, hei);
                                    } else if (hChanged) {
                                        wid = Math.round((hei * currentRatio) / currentStep) * currentStep;
                                        wid = Math.max(currentStep, wid);
                                    }
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
                            xb_dispatch(wFps, val);
                            xb_dispatch(wFpsF, val);
                            needsUpdate = true;
                        } else if (wFpsF.value !== node._xb_last_fps_float) {
                            let val = Math.round(Number(wFpsF.value)); wFps.value = val; wFpsF.value = val;
                            node._xb_last_fps = val; node._xb_last_fps_float = val;
                            xb_dispatch(wFps, val);
                            xb_dispatch(wFpsF, val);
                            needsUpdate = true;
                        }

                        let alignStepLen = isFree ? 1 : 8;
                        if (wLen.inputEl) wLen.inputEl.step = alignStepLen; else if (wLen.element) wLen.element.step = alignStepLen;

                        let len = parseInt(wLen.value, 10) || 1;
                        let safeLen = len;

                        if (!isFree && (len - 1) % alignStepLen !== 0) {
                            if (len > node._xb_last_length) safeLen = Math.ceil((len - 1) / alignStepLen) * alignStepLen + 1;
                            else safeLen = Math.floor((len - 1) / alignStepLen) * alignStepLen + 1;
                        }
                        safeLen = Math.max(1, safeLen);
                        if (wLen.value !== safeLen) {
                            wLen.value = safeLen;
                            xb_dispatch(wLen, safeLen);
                            needsUpdate = true;
                        }
                        node._xb_last_length = safeLen;

                        let fps = parseInt(wFps.value, 10) || 1;
                        let seconds = ((safeLen - 1) / fps).toFixed(2);
                        let expectedText = isZH ? `视频时长: ${seconds} 秒` : `Video Duration: ${seconds} s`;
                        if (wDisp.value !== expectedText) {
                            wDisp.value = expectedText;
                            xb_dispatch(wDisp, expectedText);
                            let dEl = wDisp.inputEl || wDisp.element;
                            if (dEl && dEl.style) dEl.style.color = "#00FF00";
                            needsUpdate = true;
                        }

                        if (needsUpdate) app.graph.setDirtyCanvas(true, true);
                    }
                }

                if (node.comfyClass === "XB_ImageParamsMaster" && node.widgets) {
                    const wRatio = node.widgets.find(w => w.name === "aspect_ratio");
                    const wWidth = node.widgets.find(w => w.name === "width");
                    const wHeight = node.widgets.find(w => w.name === "height");
                    
                    if (wRatio && wWidth && wHeight) {

                        if (node._xb_last_ratio === undefined) {
                            node._xb_last_width = parseInt(wWidth.value, 10) || 1024;
                            node._xb_last_height = parseInt(wHeight.value, 10) || 1024;
                            node._xb_last_ratio = wRatio.value;
                        }

                        let needsUpdate = false;
                        let valRatio = wRatio.value;
                        let isFree = valRatio.includes("Free");
                        let rChanged = valRatio !== node._xb_last_ratio;

                        let currentStep = isFree ? 1 : 16;
                        wWidth.options.step = currentStep; wHeight.options.step = currentStep;
                        if (wWidth.inputEl) wWidth.inputEl.step = currentStep; else if (wWidth.element) wWidth.element.step = currentStep;
                        if (wHeight.inputEl) wHeight.inputEl.step = currentStep; else if (wHeight.element) wHeight.element.step = currentStep;

                        let wid = parseInt(wWidth.value, 10) || currentStep;
                        let hei = parseInt(wHeight.value, 10) || currentStep;
                        let wChanged = wid !== node._xb_last_width;
                        let hChanged = hei !== node._xb_last_height;

                        if (wChanged || hChanged || rChanged) {
                            const ratioMap = {
                                "1:1": 1.0, "16:9": 16.0 / 9.0, "9:16": 9.0 / 16.0,
                                "4:3": 4.0 / 3.0, "3:4": 3.0 / 4.0, "21:9": 21.0 / 9.0
                            };
                            let currentRatio = ratioMap[valRatio];

                            if (wChanged && wid % currentStep !== 0) {
                                wid = wid > node._xb_last_width ? Math.ceil(wid / currentStep) * currentStep : Math.floor(wid / currentStep) * currentStep;
                            } else { wid = Math.round(wid / currentStep) * currentStep; }
                            wid = Math.max(currentStep, wid);

                            if (hChanged && hei % currentStep !== 0) {
                                hei = hei > node._xb_last_height ? Math.ceil(hei / currentStep) * currentStep : Math.floor(hei / currentStep) * currentStep;
                            } else { hei = Math.round(hei / currentStep) * currentStep; }
                            hei = Math.max(currentStep, hei);

                            if (currentRatio) {
                                if (rChanged || wChanged) {
                                    hei = Math.round((wid / currentRatio) / currentStep) * currentStep;
                                    hei = Math.max(currentStep, hei);
                                } else if (hChanged) {
                                    wid = Math.round((hei * currentRatio) / currentStep) * currentStep;
                                    wid = Math.max(currentStep, wid);
                                }
                            }

                            wWidth.value = wid; wHeight.value = hei;
                            node._xb_last_width = wid; node._xb_last_height = hei;
                            node._xb_last_ratio = valRatio;
                            xb_dispatch(wWidth, wid);
                            xb_dispatch(wHeight, hei);
                            needsUpdate = true;
                        }

                        if (needsUpdate) app.graph.setDirtyCanvas(true, true);
                    }
                }
            }
        }, 50);
    }
});