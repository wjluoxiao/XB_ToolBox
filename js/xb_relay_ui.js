import { app } from "../../scripts/app.js";

// ============================================================
// XB_Wan_RelayNode — 首尾帧接力点 UI 交互
// ============================================================

app.registerExtension({
    name: "xiaobai.relay_node_ui_master",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (nodeData.name === "XB_Wan_RelayNode") {
            const onNodeCreated = nodeType.prototype.onNodeCreated;
            
            nodeType.prototype.onNodeCreated = function () {
                if (onNodeCreated) onNodeCreated.apply(this, arguments);
                const node = this;

                // ====================================================================
                // 🪄 魔法 1：隐身大法 - 拦截图片绘制并生成背景锁头提示
                // ====================================================================
                const origOnDrawBackground = node.onDrawBackground;
                node.onDrawBackground = function (ctx) {
                    const isConnected = this.inputs?.find(inp => inp.name === "opt_end_image")?.link != null;

                    if (isConnected) {
                        // 没收图片数据指针，防止引擎渲染图片，但保留原本占用的物理空间！
                        const tempImgs = this.imgs;
                        this.imgs = undefined; 
                        
                        if (origOnDrawBackground) origOnDrawBackground.apply(this, arguments);
                        
                        this.imgs = tempImgs; // 渲染完背景后悄悄还回来
                        
                        // 动态计算原本图片所在区域的 Y 坐标
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
                            ctx.fillText("🔒 尾图已由连线接管", this.size[0] / 2, startY + maskHeight / 2 + 6);
                            ctx.restore();
                        }
                    } else {
                        if (origOnDrawBackground) origOnDrawBackground.apply(this, arguments);
                    }
                };

                // ====================================================================
                // 🪄 魔法 2：变灰大法 - 在下拉框和按钮表面盖一层半透明黑色蒙版
                // ====================================================================
                const origOnDrawForeground = node.onDrawForeground;
                node.onDrawForeground = function(ctx) {
                    if (origOnDrawForeground) origOnDrawForeground.apply(this, arguments);

                    const isConnected = this.inputs?.find(inp => inp.name === "opt_end_image")?.link != null;
                    if (isConnected) {
                        ctx.save();
                        for (let w of this.widgets) {
                            if (w.name === "end_image_file" || w.name === "image_upload" || w.name === "upload" || w.type === "button") {
                                if (w.last_y !== undefined) {
                                    let h = w.computeSize ? w.computeSize()[1] : 20;
                                    
                                    // 画一块半透明黑色蒙版，让部件看起来变成“禁用态灰色”
                                    ctx.fillStyle = "rgba(30, 30, 30, 0.65)"; 
                                    ctx.fillRect(10, w.last_y, this.size[0] - 20, h);
                                    
                                    // 在最右侧画一个小锁头图标
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

                // ====================================================================
                // 🪄 魔法 3：拦截大法 - 阻断 Canvas 画布层的鼠标点击
                // ====================================================================
                const origOnMouseDown = node.onMouseDown;
                node.onMouseDown = function(e, pos, canvas) {
                    const isConnected = this.inputs?.find(inp => inp.name === "opt_end_image")?.link != null;
                    if (isConnected) {
                        for (let w of this.widgets) {
                            if (w.name === "end_image_file" || w.name === "image_upload" || w.name === "upload" || w.type === "button") {
                                if (w.last_y !== undefined) {
                                    let h = w.computeSize ? w.computeSize()[1] : 20;
                                    // 识别鼠标点击区域，如果在被锁定的部件上，直接吃掉事件！
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

                // ====================================================================
                // 🪄 魔法 4：物理阉割大法 - 剥夺 HTML 原生透明按钮的交互能力
                // ====================================================================
                const updateDOM = () => {
                    const isConnected = node.inputs?.find(inp => inp.name === "opt_end_image")?.link != null;
                    node.widgets.forEach(w => {
                        if (w.name === "end_image_file" || w.name === "image_upload" || w.name === "upload" || w.type === "button") {
                            // 让悬浮在画布上层的 DOM 元素彻底丧失鼠标响应，并变得透明虚化
                            if (w.inputEl) {
                                w.inputEl.style.pointerEvents = isConnected ? "none" : "auto";
                                w.inputEl.style.opacity = isConnected ? "0.2" : "1";
                            }
                            if (w.element) {
                                w.element.style.pointerEvents = isConnected ? "none" : "auto";
                                w.element.style.opacity = isConnected ? "0.2" : "1";
                            }
                        }
                    });
                    app.graph.setDirtyCanvas(true, false);
                };

                // 监听连线的物理插拔动作
                const origOnConnectionsChange = node.onConnectionsChange;
                node.onConnectionsChange = function (type, index, connected, link_info) {
                    if (origOnConnectionsChange) origOnConnectionsChange.apply(this, arguments);
                    setTimeout(updateDOM, 10);
                };

                // 页面加载时的双重保险
                setTimeout(updateDOM, 50);
                setTimeout(updateDOM, 300);
            };
        }
    }
});