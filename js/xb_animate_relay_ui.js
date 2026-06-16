import { app } from "../../scripts/app.js";

// ============================================================
// XB_WanAnimate_RelayNode — Animate 无限接力点 UI
// ============================================================

app.registerExtension({
    name: "xiaobai.animate_relay_ui",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (nodeData.name === "XB_WanAnimate_RelayNode") {
            const onNodeCreated = nodeType.prototype.onNodeCreated;

            nodeType.prototype.onNodeCreated = function () {
                if (onNodeCreated) onNodeCreated.apply(this, arguments);
                const node = this;

                const isLocked = () => {
                    const tw = node.widgets.find(w => w.name === "use_local_ref_image");
                    if (!tw) return true;
                    return tw.value !== "独立参考图";
                };

                const origOnDrawBackground = node.onDrawBackground;
                node.onDrawBackground = function (ctx) {
                    if (isLocked()) {
                        const tempImgs = this.imgs;
                        this.imgs = undefined;
                        if (origOnDrawBackground) origOnDrawBackground.apply(this, arguments);
                        this.imgs = tempImgs;

                        let startY = 0;
                        for (let w of this.widgets) {
                            if (w.last_y !== undefined) {
                                let h = w.computeSize ? w.computeSize()[1] : 20;
                                startY = Math.max(startY, w.last_y + h);
                            }
                        }
                        startY += 10;
                        const maskHeight = this.size[1] - startY;
                        if (maskHeight > 30) {
                            ctx.save();
                            ctx.fillStyle = "#888";
                            ctx.font = "bold 16px Arial";
                            ctx.textAlign = "center";
                            ctx.fillText("🔒 参考图继承自总线全局图", this.size[0] / 2, startY + maskHeight / 2 + 6);
                            ctx.restore();
                        }
                    } else {
                        if (origOnDrawBackground) origOnDrawBackground.apply(this, arguments);
                    }
                };

                const origOnDrawForeground = node.onDrawForeground;
                node.onDrawForeground = function (ctx) {
                    if (origOnDrawForeground) origOnDrawForeground.apply(this, arguments);
                    if (isLocked()) {
                        ctx.save();
                        for (let w of this.widgets) {
                            if (w.name === "ref_image_file" || w.name === "image_upload" || w.name === "upload" || w.type === "button") {
                                if (w.last_y !== undefined) {
                                    let h = w.computeSize ? w.computeSize()[1] : 20;
                                    ctx.fillStyle = "rgba(30, 30, 30, 0.65)";
                                    ctx.fillRect(10, w.last_y, this.size[0] - 20, h);
                                    ctx.fillStyle = "#ddd";
                                    ctx.font = "14px Arial";
                                    ctx.textAlign = "right";
                                    ctx.fillText("🔒", this.size[0] - 20, w.last_y + h * 0.75);
                                }
                            }
                        }
                        ctx.restore();
                    }
                };

                const origOnMouseDown = node.onMouseDown;
                node.onMouseDown = function (e, pos, canvas) {
                    if (isLocked()) {
                        for (let w of this.widgets) {
                            if (w.name === "ref_image_file" || w.name === "image_upload" || w.name === "upload" || w.type === "button") {
                                if (w.last_y !== undefined) {
                                    let h = w.computeSize ? w.computeSize()[1] : 20;
                                    if (pos[1] >= w.last_y && pos[1] <= w.last_y + h) {
                                        return true;
                                    }
                                }
                            }
                        }
                    }
                    if (origOnMouseDown) return origOnMouseDown.apply(this, arguments);
                    return false;
                };

                const updateDOM = () => {
                    const locked = isLocked();
                    node.widgets.forEach(w => {
                        if (w.name === "ref_image_file" || w.name === "image_upload" || w.name === "upload" || w.type === "button") {
                            if (w.inputEl) {
                                w.inputEl.style.pointerEvents = locked ? "none" : "auto";
                                w.inputEl.style.opacity = locked ? "0.2" : "1";
                            }
                            if (w.element) {
                                w.element.style.pointerEvents = locked ? "none" : "auto";
                                w.element.style.opacity = locked ? "0.2" : "1";
                            }
                        }
                    });
                    app.graph.setDirtyCanvas(true, false);
                };

                // 延迟绑定开关回调（确保widget已创建）
                const bindToggle = () => {
                    const tw = node.widgets.find(w => w.name === "use_local_ref_image");
                    if (tw && !tw._xb_bound) {
                        tw._xb_bound = true;
                        const origCB = tw.callback;
                        tw.callback = function (v, ...args) {
                            if (origCB) origCB.apply(this, [v, ...args]);
                            updateDOM();
                        };
                    }
                };

                setTimeout(bindToggle, 50);
                setTimeout(bindToggle, 300);
                setTimeout(updateDOM, 50);
                setTimeout(updateDOM, 300);
            };
        }
    }
});
