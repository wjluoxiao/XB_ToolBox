import { app } from "../../scripts/app.js";
import { setWidgetValue } from "./xb_compat.js";

// ============================================================
// XB_VideoParamsMaster / XB_ImageParamsMaster / XB_MasterParameter — 参数主控 UI
// ============================================================

const isZH = navigator.language.startsWith("zh");

// 「时长估算」在 Nodes 2.0 里是 PrimeVue 文本框（padding 8px 16px → 31px 高），
// 比旁边的数字框高一截；用一段 CSS 压成同样高度、同样的透明背景。
const PARAMS_CSS = `
div[node-type="XB_VideoParamsMaster"] input.p-inputtext[readonly] {
  height: 24px !important;
  min-height: 24px !important;
  max-height: 24px !important;
  padding: 0 8px !important;
  background: var(--color-component-node-widget-background, rgb(49, 50, 53)) !important;
  border: 0 !important;
  border-radius: 6px !important;
  box-shadow: none !important;
  font-size: 12px !important;
  line-height: 24px !important;
  color: inherit !important;
}
`;

const injectParamsCss = () => {
    try {
        if (document.getElementById("xb-params-css")) return;
        const st = document.createElement("style");
        st.id = "xb-params-css";
        st.textContent = PARAMS_CSS;
        document.head.append(st);
    } catch (_) { /* ignore */ }
};
injectParamsCss();

// 共用「画幅比例 + 步长」联动的图像参数节点
const IMAGE_PARAMS_NODES = new Set(["XB_ImageParamsMaster", "XB_ImageParamsMasterMini"]);
const VIDEO_PARAMS_NODE = "XB_VideoParamsMaster";

// 画幅比例：自定义 + 官方 Resolution Selector 的比例（旧值自动迁移）
const RATIO_ALIAS = {
    "Free": "自定义",
    "1:1": "1:1 (Square)",
    "2:3": "2:3 (Portrait Photo)",
    "3:2": "3:2 (Photo)",
    "3:4": "3:4 (Portrait Standard)",
    "4:3": "4:3 (Standard)",
    "9:16": "9:16 (Portrait Widescreen)",
    "16:9": "16:9 (Widescreen)",
    "21:9": "21:9 (Ultrawide)",
};

const isCustomRatio = (name) => {
    const v = String(name ?? "");
    return !v || v.includes("自定义") || v.includes("Free");
};

/** "16:9 (Widescreen)" / "16:9 (LTX)" / "16:9" → 16/9 */
const ratioOf = (name) => {
    if (isCustomRatio(name)) return null;
    const m = /^(\d+):(\d+)/.exec(String(name));
    if (!m) return null;
    const w = Number(m[1]);
    const h = Number(m[2]);
    return h ? w / h : null;
};

/** 旧存档里的 "Free" / "16:9" / "16:9 (LTX)" 换成新选项名（值不在选项里就修） */
const migrateRatio = (node, wRatio) => {
    if (!wRatio) return false;
    const opts = wRatio.options?.values || [];
    const val = String(wRatio.value ?? "");
    if (!opts.length || opts.includes(val)) return false;
    const fixed = RATIO_ALIAS[val] || (val.includes("(LTX)") ? RATIO_ALIAS[val.split(" ")[0]] : null);
    if (!fixed) return false;
    wRatio.value = fixed;
    xb_dispatch(wRatio, fixed);
    return true;
};

/** 「倍数」当前值（缺省 16） */
const multipleOf = (node) => {
    const w = node.widgets?.find((x) => x.name === "multiple");
    const v = Math.round(Number(w?.value));
    return Number.isFinite(v) && v >= 8 ? v : 16;
};

/** 把宽高按比例 + 倍数（步长）规整，保证两边都能整除 */
const fitSize = (ratioName, w, h, step) => {
    const snap = (v) => Math.max(step, Math.round((Number(v) || step) / step) * step);
    let wid = snap(w);
    let hei = snap(h);
    const r = ratioOf(ratioName);
    if (r) {
        if (wid >= hei) hei = snap(wid / r);
        else wid = snap(hei * r);
    }
    return { wid: Math.max(step, wid), hei: Math.max(step, hei) };
};

/** 步长控件（数字框的上下箭头步长）；min 也设成步长，
 *  否则 Nodes 2.0 的数字框会按 min + k*step 取整，结果可能不是倍数的整数倍。 */
const applyStep = (w, step) => {
    if (!w) return;
    w.options = w.options || {};
    w.options.step = step;
    w.options.step2 = step;
    w.options.min = step;
    const el = w.inputEl || w.element;
    if (el && typeof el.setAttribute === "function") {
        el.step = step;
        el.min = step;
        el.setAttribute("step", String(step));
        el.setAttribute("min", String(step));
    }
};

// 旧版写值函数（仅输入框/回调，Nodes 2.0 下会漏写 widget.value）
const __xbLegacyDispatch = (w, val) => {
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

// Nodes 2.0：数字/下拉是 Vue 组件（无 inputEl/element），统一走 setWidgetValue（element + value + callback）
const xb_dispatch = (w, val) => setWidgetValue(w, val);

app.registerExtension({
    name: "xiaobai.mediaparams.split",

    // —— nodeCreated：画幅比例 + 倍数（步长）联动 ——
    async nodeCreated(node) {
        if (IMAGE_PARAMS_NODES.has(node.comfyClass)) {
            const wR = node.widgets?.find(w => w.name === "aspect_ratio");
            const wW = node.widgets?.find(w => w.name === "width");
            const wH = node.widgets?.find(w => w.name === "height");
            const wM = node.widgets?.find(w => w.name === "multiple");
            if (!wR || !wW || !wH) return;
            node._xb_syncing = false;
            migrateRatio(node, wR);
            applyStep(wW, multipleOf(node));
            applyStep(wH, multipleOf(node));

            const sync = () => {
                if (node._xb_syncing || node._xb_from_polling) return;
                const step = multipleOf(node);
                const { wid, hei } = fitSize(wR.value, wW.value, wH.value, step);
                node._xb_syncing = true;
                if (parseInt(wW.value, 10) !== wid) { wW.value = wid; xb_dispatch(wW, wid); }
                if (parseInt(wH.value, 10) !== hei) { wH.value = hei; xb_dispatch(wH, hei); }
                node._xb_syncing = false;
            };

            const oc = wR.callback; wR.callback = function (v) { if (oc) oc.apply(this, arguments); if (node._xb_from_polling) return; sync(); };
            const ow = wW.callback; wW.callback = function (v) { if (ow) ow.apply(this, arguments); sync(); };
            const oh = wH.callback; wH.callback = function (v) { if (oh) oh.apply(this, arguments); sync(); };
            const om = wM?.callback; if (wM) wM.callback = function (v) {
                if (om) om.apply(this, arguments);
                const step = multipleOf(node);
                applyStep(wW, step); applyStep(wH, step);
                sync();
            };
        }

        if (node.comfyClass === VIDEO_PARAMS_NODE) {
            const wR = node.widgets?.find(w => w.name === "aspect_ratio");
            const wW = node.widgets?.find(w => w.name === "width");
            const wH = node.widgets?.find(w => w.name === "height");
            const wF = node.widgets?.find(w => w.name === "fps");
            const wFF = node.widgets?.find(w => w.name === "fps_float");
            const wL = node.widgets?.find(w => w.name === "length");
            const wM = node.widgets?.find(w => w.name === "multiple");
            if (!wR || !wW || !wH) return;
            node._xb_syncing = false;
            migrateRatio(node, wR);
            applyStep(wW, multipleOf(node));
            applyStep(wH, multipleOf(node));

            const sync = (driveBy) => {
                if (node._xb_syncing || node._xb_from_polling) return;
                const step = multipleOf(node);
                const { wid, hei } = fitSize(wR.value, wW.value, wH.value, step);
                node._xb_syncing = true;
                if (parseInt(wW.value, 10) !== wid) { wW.value = wid; xb_dispatch(wW, wid); }
                if (parseInt(wH.value, 10) !== hei) { wH.value = hei; xb_dispatch(wH, hei); }
                node._xb_syncing = false;
            };

            const oc = wR.callback; wR.callback = function (v) { if (oc) oc.apply(this, arguments); if (node._xb_from_polling) return; sync("w"); };
            const ow = wW.callback; wW.callback = function (v) { if (ow) ow.apply(this, arguments); sync("w"); };
            const oh = wH.callback; wH.callback = function (v) { if (oh) oh.apply(this, arguments); sync("h"); };
            const om = wM?.callback; if (wM) wM.callback = function (v) {
                if (om) om.apply(this, arguments);
                const step = multipleOf(node);
                applyStep(wW, step); applyStep(wH, step);
                sync("w");
            };

            if(wF&&wFF){const of=wF.callback;wF.callback=function(v){if(of)of.apply(this,arguments);if(node._xb_syncing||node._xb_from_polling)return;
                const val=Math.round(Number(v));if(wFF.value!==val){node._xb_syncing=true;wFF.value=val;xb_dispatch(wFF,val);node._xb_syncing=false;}};
                const off=wFF.callback;wFF.callback=function(v){if(off)off.apply(this,arguments);if(node._xb_syncing||node._xb_from_polling)return;
                const val=Math.round(Number(v));if(wF.value!==val){node._xb_syncing=true;wF.value=val;xb_dispatch(wF,val);node._xb_syncing=false;}};}
            if(wL){node._xb_last_len=parseInt(wL.value,10)||1;const ol=wL.callback;wL.callback=function(v){if(ol)ol.apply(this,arguments);if(node._xb_syncing||node._xb_from_polling)return;
                const isF=isCustomRatio(wR.value);const as=isF?1:8;
                let len=parseInt(v,10)||1;if(!isF&&(len-1)%as!==0){len=len>node._xb_last_len?Math.ceil((len-1)/as)*as+1:Math.floor((len-1)/as)*as+1;len=Math.max(1,len);
                if(wL.value!==len){node._xb_syncing=true;wL.value=len;xb_dispatch(wL,len);node._xb_syncing=false;}}node._xb_last_len=len;};}
        }
    },

    init() {
        injectParamsCss();
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
                        // Nodes 2.0：显示型字段走 options.read_only（Vue 部件没有 element 可改）
                        try { if (wDisp.options) wDisp.options.read_only = true; } catch (_) {}
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
                            node._xb_need_normalize = true;   // 载入后先规整一次
                        }
                        if (migrateRatio(node, wRatio)) node._xb_need_normalize = true;

                        let needsUpdate = false;
                        let valRatio = wRatio.value;
                        let isFree = isCustomRatio(valRatio);
                        let rChanged = valRatio !== node._xb_last_ratio;

                        // 步长 = 倍数（宽高必须能被它整除）
                        let currentStep = multipleOf(node);
                        applyStep(wWidth, currentStep);
                        applyStep(wHeight, currentStep);

                        let wid = parseInt(wWidth.value, 10) || currentStep;
                        let hei = parseInt(wHeight.value, 10) || currentStep;
                        let wChanged = wid !== node._xb_last_width;
                        let hChanged = hei !== node._xb_last_height;

                        if (wChanged || hChanged || rChanged || node._xb_need_normalize) {
                            node._xb_need_normalize = false;
                            const snap = (v) => Math.max(currentStep, Math.round(v / currentStep) * currentStep);
                            let nw = snap(wid);
                            let nh = snap(hei);
                            const currentRatio = ratioOf(valRatio);
                            if (currentRatio) {
                                const ratioOnly = rChanged && !wChanged && !hChanged;
                                if (ratioOnly) {
                                    // ????????????????? Python ????
                                    if (nw >= nh) nh = snap(nw / currentRatio);
                                    else nw = snap(nh * currentRatio);
                                } else if (wChanged || !hChanged) {
                                    nh = snap(nw / currentRatio);
                                } else {
                                    nw = snap(nh * currentRatio);
                                }
                            }

                            wWidth.value = nw; wHeight.value = nh;
                            node._xb_last_width = nw; node._xb_last_height = nh;
                            node._xb_last_ratio = valRatio;
                            xb_dispatch(wWidth, nw);
                            xb_dispatch(wHeight, nh);
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
                        wLen.options.step = wLen.options.step2 = alignStepLen;
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

                if (IMAGE_PARAMS_NODES.has(node.comfyClass) && node.widgets) {
                    const wRatio = node.widgets.find(w => w.name === "aspect_ratio");
                    const wWidth = node.widgets.find(w => w.name === "width");
                    const wHeight = node.widgets.find(w => w.name === "height");

                    if (wRatio && wWidth && wHeight) {
                        node._xb_from_polling = true;

                        if (node._xb_last_ratio === undefined) {
                            node._xb_last_width = parseInt(wWidth.value, 10) || 1024;
                            node._xb_last_height = parseInt(wHeight.value, 10) || 1024;
                            node._xb_last_ratio = wRatio.value;
                            node._xb_need_normalize = true;   // ????????
                        }
                        if (migrateRatio(node, wRatio)) node._xb_need_normalize = true;

                        let needsUpdate = false;
                        let valRatio = wRatio.value;
                        let rChanged = valRatio !== node._xb_last_ratio;

                        // 步长 = 倍数（宽高必须能被它整除）
                        let currentStep = multipleOf(node);
                        applyStep(wWidth, currentStep);
                        applyStep(wHeight, currentStep);

                        let wid = parseInt(wWidth.value, 10) || currentStep;
                        let hei = parseInt(wHeight.value, 10) || currentStep;
                        let wChanged = wid !== node._xb_last_width;
                        let hChanged = hei !== node._xb_last_height;

                        if (wChanged || hChanged || rChanged || node._xb_need_normalize) {
                            node._xb_need_normalize = false;
                            const snap = (v) => Math.max(currentStep, Math.round(v / currentStep) * currentStep);
                            let nw = snap(wid);
                            let nh = snap(hei);
                            const currentRatio = ratioOf(valRatio);
                            if (currentRatio) {
                                const ratioOnly = rChanged && !wChanged && !hChanged;
                                if (ratioOnly) {
                                    // ????????????????? Python ????
                                    if (nw >= nh) nh = snap(nw / currentRatio);
                                    else nw = snap(nh * currentRatio);
                                } else if (wChanged || !hChanged) {
                                    nh = snap(nw / currentRatio);
                                } else {
                                    nw = snap(nh * currentRatio);
                                }
                            }

                            wWidth.value = nw; wHeight.value = nh;
                            node._xb_last_width = nw; node._xb_last_height = nh;
                            node._xb_last_ratio = valRatio;
                            xb_dispatch(wWidth, nw);
                            xb_dispatch(wHeight, nh);
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