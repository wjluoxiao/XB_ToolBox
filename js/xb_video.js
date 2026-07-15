import { app } from "../../scripts/app.js";

// ============================================================
// XB_VideoParamsMaster / XB_ImageParamsMaster / XB_MasterParameter — 参数主控 UI
// ============================================================

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

    // —— nodeCreated：子工作流画幅联动（步长由 Python step=16 负责）——
    async nodeCreated(node) {
        if (node.comfyClass === "XB_ImageParamsMaster") {
            const wR = node.widgets?.find(w => w.name === "aspect_ratio");
            const wW = node.widgets?.find(w => w.name === "width");
            const wH = node.widgets?.find(w => w.name === "height");
            if (!wR || !wW || !wH) return;
            node._xb_syncing = false;
            const rm = {"1:1":1,"16:9":16/9,"9:16":9/16,"4:3":4/3,"3:4":3/4,"21:9":21/9};

            const sW = () => { if(node._xb_syncing||node._xb_from_polling) return;
                const r=wR.value; if(r.includes("Free")) return; const cr=rm[r]; if(!cr) return;
                let w=Math.round((parseInt(wW.value,10)||16)/16)*16; w=Math.max(16,w);
                let h=Math.round((w/cr)/16)*16; h=Math.max(16,h);
                if(h!==parseInt(wH.value,10)){node._xb_syncing=true;wH.value=h;xb_dispatch(wH,h);node._xb_syncing=false;} };
            const sH = () => { if(node._xb_syncing||node._xb_from_polling) return;
                const r=wR.value; if(r.includes("Free")) return; const cr=rm[r]; if(!cr) return;
                let h=Math.round((parseInt(wH.value,10)||16)/16)*16; h=Math.max(16,h);
                let w=Math.round((h*cr)/16)*16; w=Math.max(16,w);
                if(w!==parseInt(wW.value,10)){node._xb_syncing=true;wW.value=w;xb_dispatch(wW,w);node._xb_syncing=false;} };

            const oc=wR.callback; wR.callback=function(v){if(oc)oc.apply(this,arguments);if(node._xb_from_polling)return;sW();};
            const ow=wW.callback; wW.callback=function(v){if(ow)ow.apply(this,arguments);sW();};
            const oh=wH.callback; wH.callback=function(v){if(oh)oh.apply(this,arguments);sH();};
        }

        if (node.comfyClass === "XB_VideoParamsMaster") {
            const wR = node.widgets?.find(w => w.name === "aspect_ratio");
            const wW = node.widgets?.find(w => w.name === "width");
            const wH = node.widgets?.find(w => w.name === "height");
            const wF = node.widgets?.find(w => w.name === "fps");
            const wFF = node.widgets?.find(w => w.name === "fps_float");
            const wL = node.widgets?.find(w => w.name === "length");
            if (!wR || !wW || !wH) return;
            node._xb_syncing = false;
            const rS={"1:1":1,"16:9":16/9,"9:16":9/16,"4:3":4/3,"3:4":3/4,"21:9":21/9};
            const rL={"16:9 (LTX)":16/9,"9:16 (LTX)":9/16,"4:3 (LTX)":4/3,"3:4 (LTX)":3/4};

            const sW = () => { if(node._xb_syncing||node._xb_from_polling) return;
                const r=wR.value; if(r.includes("Free")) return;
                const isL=r.includes("(LTX)"); const rm=isL?rL:rS; const cr=rm[r]; if(!cr) return;
                const s=isL?32:16;
                let w=Math.round((parseInt(wW.value,10)||s)/s)*s; w=Math.max(s,w);
                let h=Math.round((w/cr)/s)*s; h=Math.max(s,h);
                if(h!==parseInt(wH.value,10)){node._xb_syncing=true;wH.value=h;xb_dispatch(wH,h);node._xb_syncing=false;} };
            const sH = () => { if(node._xb_syncing||node._xb_from_polling) return;
                const r=wR.value; if(r.includes("Free")) return;
                const isL=r.includes("(LTX)"); const rm=isL?rL:rS; const cr=rm[r]; if(!cr) return;
                const s=isL?32:16;
                let h=Math.round((parseInt(wH.value,10)||s)/s)*s; h=Math.max(s,h);
                let w=Math.round((h*cr)/s)*s; w=Math.max(s,w);
                if(w!==parseInt(wW.value,10)){node._xb_syncing=true;wW.value=w;xb_dispatch(wW,w);node._xb_syncing=false;} };

            const oc=wR.callback; wR.callback=function(v){if(oc)oc.apply(this,arguments);if(node._xb_from_polling)return;sW();};
            const ow=wW.callback; wW.callback=function(v){if(ow)ow.apply(this,arguments);sW();};
            const oh=wH.callback; wH.callback=function(v){if(oh)oh.apply(this,arguments);sH();};

            if(wF&&wFF){const of=wF.callback;wF.callback=function(v){if(of)of.apply(this,arguments);if(node._xb_syncing||node._xb_from_polling)return;
                const val=Math.round(Number(v));if(wFF.value!==val){node._xb_syncing=true;wFF.value=val;xb_dispatch(wFF,val);node._xb_syncing=false;}};
                const off=wFF.callback;wFF.callback=function(v){if(off)off.apply(this,arguments);if(node._xb_syncing||node._xb_from_polling)return;
                const val=Math.round(Number(v));if(wF.value!==val){node._xb_syncing=true;wF.value=val;xb_dispatch(wF,val);node._xb_syncing=false;}};}
            if(wL){node._xb_last_len=parseInt(wL.value,10)||1;const ol=wL.callback;wL.callback=function(v){if(ol)ol.apply(this,arguments);if(node._xb_syncing||node._xb_from_polling)return;
                const isF=(wR.value||"").includes("Free");const as=isF?1:8;
                let len=parseInt(v,10)||1;if(!isF&&(len-1)%as!==0){len=len>node._xb_last_len?Math.ceil((len-1)/as)*as+1:Math.floor((len-1)/as)*as+1;len=Math.max(1,len);
                if(wL.value!==len){node._xb_syncing=true;wL.value=len;xb_dispatch(wL,len);node._xb_syncing=false;}}node._xb_last_len=len;};}
        }
    },

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
                        node._xb_from_polling = true;
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
                            node._xb_last_dur = parseFloat(wDisp.value) || 0;
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
                            } else if (isLTX) {
                                const ratioMap = {
                                    "16:9 (LTX)": 16.0 / 9.0, "9:16 (LTX)": 9.0 / 16.0,
                                    "4:3 (LTX)": 4.0 / 3.0, "3:4 (LTX)": 3.0 / 4.0
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
                        wLen.options.step = alignStepLen;
                        if (wLen.inputEl) { wLen.inputEl.step = alignStepLen; wLen.inputEl.setAttribute("step", String(alignStepLen)); }
                        else if (wLen.element) { wLen.element.step = alignStepLen; wLen.element.setAttribute("step", String(alignStepLen)); }

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
                        node._xb_from_polling = false;
                    }
                }

                if (node.comfyClass === "XB_ImageParamsMaster" && node.widgets) {
                    const wRatio = node.widgets.find(w => w.name === "aspect_ratio");
                    const wWidth = node.widgets.find(w => w.name === "width");
                    const wHeight = node.widgets.find(w => w.name === "height");
                    
                    if (wRatio && wWidth && wHeight) {
                        node._xb_from_polling = true;

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
                        if (wWidth.inputEl) { wWidth.inputEl.step = currentStep; wWidth.inputEl.setAttribute("step", String(currentStep)); }
                        else if (wWidth.element) { wWidth.element.step = currentStep; wWidth.element.setAttribute("step", String(currentStep)); }
                        if (wHeight.inputEl) { wHeight.inputEl.step = currentStep; wHeight.inputEl.setAttribute("step", String(currentStep)); }
                        else if (wHeight.element) { wHeight.element.step = currentStep; wHeight.element.setAttribute("step", String(currentStep)); }

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
                        node._xb_from_polling = false;
                    }
                }
            }
        }, 50);
    }
});