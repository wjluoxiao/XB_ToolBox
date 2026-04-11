import { app } from "../../scripts/app.js";

console.log("🚀 XB-Tools: 媒体参数节点 JS (终极架构：预设档位换挡引擎) 已加载！");

app.registerExtension({
    name: "xiaobai.mediaparams.v23",
    init() {
        setInterval(() => {
            if (!app.graph || !app.graph._nodes) return;
            
            for (const node of app.graph._nodes) {
                if (node.comfyClass === "XB_VideoParamsMaster" && node.widgets) {
                    
                    const wModel = node.widgets.find(w => w.name === "model_type");
                    const wRatio = node.widgets.find(w => w.name === "aspect_ratio");
                    const wDisp = node.widgets.find(w => w.name === "duration_display");
                    const wLen = node.widgets.find(w => w.name === "length");
                    const wFps = node.widgets.find(w => w.name === "fps");
                    const wFpsF = node.widgets.find(w => w.name === "fps_float");
                    const wWidth = node.widgets.find(w => w.name === "width");
                    const wHeight = node.widgets.find(w => w.name === "height");
                    
                    if (wDisp && wLen && wFps && wFpsF && wModel && wWidth && wHeight && wRatio) {
                        
                        node.title = "LX-BOX - 🎬 图像参数大全";
                        
                        if (wDisp.inputEl && wDisp.inputEl.style.backgroundColor !== "rgb(34, 34, 34)") {
                            wDisp.inputEl.readOnly = true;
                            wDisp.inputEl.style.backgroundColor = "#222222";
                            wDisp.inputEl.style.color = "#00FF00";
                            wDisp.inputEl.style.textAlign = "center";
                            wDisp.inputEl.style.fontWeight = "bold";
                        }
                        wFpsF.options.precision = 2;
                        
                        if (node._xb_shadow_len === undefined) node._xb_shadow_len = 121;
                        if (node._xb_shadow_fps === undefined) node._xb_shadow_fps = 24;

                        if (node._xb_last_fps === undefined) {
                            node._xb_last_fps = wFps.value;
                            node._xb_last_fps_float = wFpsF.value;
                            node._xb_last_length = parseInt(wLen.value, 10) || 1;
                            node._xb_last_width = parseInt(wWidth.value, 10) || 1024;
                            node._xb_last_height = parseInt(wHeight.value, 10) || 1024;
                            node._xb_last_ratio = wRatio.value;
                            node._xb_last_model = wModel.value;
                        }
                        
                        let needsUpdate = false;
                        
                        // ==========================================
                        // 1. 🧠 模式判定与 UI 灰化
                        // ==========================================
                        let valModel = wModel.value;
                        let isFree = valModel.includes("自由");
                        let isImage = valModel.includes("图片");
                        let isVideo = valModel.includes("视频");
                        let valRatio = wRatio.value;

                        let mChanged = valModel !== node._xb_last_model;
                        if (mChanged) {
                            if (node._xb_last_model.includes("图片") && !isImage) {
                                wLen.value = node._xb_shadow_len; wFps.value = node._xb_shadow_fps; wFpsF.value = wFps.value;
                                if (wLen.inputEl) { wLen.inputEl.value = wLen.value; wLen.inputEl.dispatchEvent(new Event("input", { bubbles: true })); }
                                if (wFps.inputEl) { wFps.inputEl.value = wFps.value; wFps.inputEl.dispatchEvent(new Event("input", { bubbles: true })); }
                            }
                            else if (!node._xb_last_model.includes("图片") && isImage) {
                                node._xb_shadow_len = parseInt(wLen.value, 10); node._xb_shadow_fps = parseInt(wFps.value, 10);
                            }
                        }

                        const toggleDisable = (w, disable) => {
                            if (!w || !w.inputEl) return;
                            if (disable) {
                                w.inputEl.disabled = true; w.inputEl.style.opacity = "0.4";
                            } else {
                                w.inputEl.disabled = false; w.inputEl.style.opacity = "1.0";
                            }
                        };
                        toggleDisable(wLen, isImage); toggleDisable(wFps, isImage); toggleDisable(wFpsF, isImage);

                        // ==========================================
                        // 2. 📐 步长接管与核心运算
                        // ==========================================
                        // 判断是否处于“黄金档位特权区”
                        let isGoldenZone = isVideo && (valRatio === "16:9" || valRatio === "9:16");
                        
                        // 巧妙设计：在特权区把原生步长设为 1，这样点击一次箭头数值就只会变化 1，我们可以借此精准识别用户的点击意图
                        let currentStep = isGoldenZone ? 1 : (isFree ? 1 : 16);
                        
                        wWidth.options.step = currentStep; wHeight.options.step = currentStep;
                        if (wWidth.inputEl) wWidth.inputEl.step = currentStep;
                        if (wHeight.inputEl) wHeight.inputEl.step = currentStep;

                        let wid = parseInt(wWidth.value, 10) || currentStep;
                        let hei = parseInt(wHeight.value, 10) || currentStep;
                        let wChanged = wid !== node._xb_last_width;
                        let hChanged = hei !== node._xb_last_height;
                        let rChanged = valRatio !== node._xb_last_ratio;

                        if (wChanged || hChanged || rChanged || mChanged) {
                            
                            if (isGoldenZone) {
                                // 🚀 触发档位切换引擎
                                const goldenBuckets = {
                                    "16:9": [ {w: 832, h: 480}, {w: 960, h: 544}, {w: 1280, h: 720}, {w: 1920, h: 1088} ],
                                    "9:16": [ {w: 480, h: 832}, {w: 544, h: 960}, {w: 720, h: 1280}, {w: 1088, h: 1920} ]
                                };
                                let buckets = goldenBuckets[valRatio];
                                
                                if (rChanged || mChanged) {
                                    // 刚切入特权区，给最小档位兜底
                                    wid = buckets[0].w; hei = buckets[0].h; 
                                } else if (wChanged || hChanged) {
                                    let wDelta = wid - node._xb_last_width;
                                    let hDelta = hei - node._xb_last_height;
                                    
                                    // 寻找自己刚才在哪个档位待着
                                    let currIdx = buckets.findIndex(b => b.w === node._xb_last_width && b.h === node._xb_last_height);
                                    if (currIdx === -1) currIdx = 0;

                                    if (wChanged) {
                                        // 如果增量正好是 1，说明是用户点了上下箭头 -> 启动换挡！
                                        if (wDelta === 1) currIdx = Math.min(currIdx + 1, buckets.length - 1);
                                        else if (wDelta === -1) currIdx = Math.max(currIdx - 1, 0);
                                        else {
                                            // 拖拽或手打数字 -> 磁吸到最近的档位
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
                                // 🚙 常规区：标准步长吸附与比例计算
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
                                    if (rChanged || mChanged || wChanged) {
                                        hei = Math.round((wid / currentRatio) / currentStep) * currentStep;
                                        hei = Math.max(currentStep, hei);
                                    } else if (hChanged) {
                                        wid = Math.round((hei * currentRatio) / currentStep) * currentStep;
                                        wid = Math.max(currentStep, wid);
                                    }
                                }
                            }

                            // 回写更新 UI
                            wWidth.value = wid; wHeight.value = hei;
                            node._xb_last_width = wid; node._xb_last_height = hei;
                            node._xb_last_ratio = valRatio; node._xb_last_model = valModel;

                            if (wWidth.inputEl) { wWidth.inputEl.value = wid; wWidth.inputEl.dispatchEvent(new Event("input", { bubbles: true })); }
                            if (wHeight.inputEl) { wHeight.inputEl.value = hei; wHeight.inputEl.dispatchEvent(new Event("input", { bubbles: true })); }
                            needsUpdate = true;
                        }

                        // ==========================================
                        // 3. ⏱️ 时间与帧率联动引擎
                        // ==========================================
                        if (wFps.value !== node._xb_last_fps) {
                            let val = Math.round(Number(wFps.value)); wFps.value = val; wFpsF.value = val;
                            node._xb_last_fps = val; node._xb_last_fps_float = val;
                            if (wFps.inputEl) { wFps.inputEl.value = val; wFps.inputEl.dispatchEvent(new Event("input", { bubbles: true })); }
                            if (wFpsF.inputEl) { wFpsF.inputEl.value = val; wFpsF.inputEl.dispatchEvent(new Event("input", { bubbles: true })); }
                            needsUpdate = true;
                        } else if (wFpsF.value !== node._xb_last_fps_float) {
                            let val = Math.round(Number(wFpsF.value)); wFps.value = val; wFpsF.value = val;
                            node._xb_last_fps = val; node._xb_last_fps_float = val;
                            if (wFps.inputEl) { wFps.inputEl.value = val; wFps.inputEl.dispatchEvent(new Event("input", { bubbles: true })); }
                            if (wFpsF.inputEl) { wFpsF.inputEl.value = val; wFpsF.inputEl.dispatchEvent(new Event("input", { bubbles: true })); }
                            needsUpdate = true;
                        }

                        if (isImage) {
                            if (wLen.value !== 1) { 
                                wLen.value = 1; 
                                if (wLen.inputEl) { wLen.inputEl.value = 1; wLen.inputEl.dispatchEvent(new Event("input", { bubbles: true })); }
                                needsUpdate = true; 
                            }
                            node._xb_last_length = 1;
                            
                            let expectedText = "视频时长: [ 已停用 ]";
                            if (wDisp.value !== expectedText) {
                                wDisp.value = expectedText;
                                if (wDisp.inputEl) {
                                    wDisp.inputEl.value = expectedText; wDisp.inputEl.style.color = "#777777";
                                    wDisp.inputEl.dispatchEvent(new Event("input", { bubbles: true }));
                                }
                                needsUpdate = true;
                            }
                        } else {
                            let alignStepLen = isFree ? 1 : 8;
                            if (wLen.inputEl) wLen.inputEl.step = alignStepLen; 

                            let len = parseInt(wLen.value, 10) || 1;
                            let safeLen = len;

                            if (!isFree && (len - 1) % alignStepLen !== 0) {
                                if (len > node._xb_last_length) safeLen = Math.ceil((len - 1) / alignStepLen) * alignStepLen + 1;
                                else safeLen = Math.floor((len - 1) / alignStepLen) * alignStepLen + 1;
                            }
                            safeLen = Math.max(1, safeLen);
                            if (wLen.value !== safeLen) {
                                wLen.value = safeLen;
                                if (wLen.inputEl) { wLen.inputEl.value = safeLen; wLen.inputEl.dispatchEvent(new Event("input", { bubbles: true })); }
                                needsUpdate = true;
                            }
                            node._xb_last_length = safeLen;

                            let fps = parseInt(wFps.value, 10) || 1;
                            let seconds = ((safeLen - 1) / fps).toFixed(2);
                            let expectedText = `视频时长: ${seconds} 秒`;
                            if (wDisp.value !== expectedText) {
                                wDisp.value = expectedText;
                                if (wDisp.inputEl) {
                                    wDisp.inputEl.value = expectedText; wDisp.inputEl.style.color = "#00FF00"; 
                                    wDisp.inputEl.dispatchEvent(new Event("input", { bubbles: true }));
                                }
                                needsUpdate = true;
                            }
                        }

                        // ==========================================
                        // 4. Tooltips 更新
                        // ==========================================
                        const tooltips = {
                            "model_type": "⚙️ 模式选择：\n  视频和图片模式提供安全的自动步长。\n自由模式解除所有限制，更灵活。",
                            "aspect_ratio": "🔒 比例档位：\n【视频模式】下，9:16 和 16:9 可以切换最佳分辨率。\n 其他情况点击宽高调节，会按照安全长度自动对齐。",
                            "width": "↔️ 宽度：按照模型安全长度自动对齐。",
                            "height": "↕️ 高度：按照模型安全长度自动对齐。",
                            "length": "🎞️ 视频帧数：按照模型要求严格锁定 1+8N 。",
                            "fps": "🎬 整数帧率：通常为16, 24 或 25。",
                            "fps_float": "🧮 浮点帧率：与整数同步，供底层高精度推算。"
                        };
                        for (const w of node.widgets) {
                            if (tooltips[w.name]) {
                                w.tooltip = tooltips[w.name];
                                if (w.inputEl) w.inputEl.title = tooltips[w.name];
                            }
                        }

                        if (needsUpdate) {
                            app.graph.setDirtyCanvas(true, true);
                        }
                    }
                }
            }
        }, 50);
    }
});