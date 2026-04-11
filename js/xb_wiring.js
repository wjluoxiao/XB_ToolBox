import { app } from "../../scripts/app.js";

// ==============================================================================
// 独立模块：深色工业风自定义弹窗 
// ==============================================================================
function showCustomPrompt(title, defaultValue, callback) {
    const existing = document.getElementById("xb-custom-prompt");
    if (existing) existing.remove();

    const overlay = document.createElement("div");
    overlay.id = "xb-custom-prompt";
    overlay.style.cssText = `
        position: fixed; top: 0; left: 0; width: 100vw; height: 100vh;
        background: rgba(0,0,0,0.6); display: flex; justify-content: center; align-items: center;
        z-index: 10000; backdrop-filter: blur(4px); font-family: sans-serif;
    `;

    const box = document.createElement("div");
    box.style.cssText = `
        background: #1c1c1c; border: 1px solid #444; border-radius: 8px;
        padding: 20px 25px; width: 320px; box-shadow: 0 10px 30px rgba(0,0,0,0.7);
    `;

    const titleEl = document.createElement("div");
    titleEl.innerText = title;
    titleEl.style.cssText = "color: #e0e0e0; margin-bottom: 15px; font-size: 14px; line-height: 1.5;";

    const inputEl = document.createElement("input");
    inputEl.type = "text";
    inputEl.value = defaultValue;
    inputEl.style.cssText = `
        width: 100%; padding: 10px; box-sizing: border-box; border: 1px solid #555;
        background: #0f0f0f; color: #fff; border-radius: 4px; outline: none; margin-bottom: 20px;
        font-size: 14px; font-weight: bold; text-align: center; transition: 0.2s;
    `;
    inputEl.onfocus = () => { inputEl.style.borderColor = "#4CAF50"; inputEl.style.boxShadow = "0 0 5px rgba(76,175,80,0.5)"; };
    inputEl.onblur = () => { inputEl.style.borderColor = "#555"; inputEl.style.boxShadow = "none"; };

    const btnContainer = document.createElement("div");
    btnContainer.style.cssText = "display: flex; justify-content: flex-end; gap: 12px;";

    const btnCancel = document.createElement("button");
    btnCancel.innerText = "取消";
    btnCancel.style.cssText = "padding: 8px 16px; background: transparent; border: 1px solid #666; color: #ccc; border-radius: 4px; cursor: pointer; font-size: 13px; transition: 0.2s;";
    btnCancel.onmouseover = () => { btnCancel.style.background = "#333"; };
    btnCancel.onmouseout = () => { btnCancel.style.background = "transparent"; };

    const btnOk = document.createElement("button");
    btnOk.innerText = "确定";
    btnOk.style.cssText = "padding: 8px 16px; background: #4CAF50; border: none; color: #fff; border-radius: 4px; cursor: pointer; font-size: 13px; transition: 0.2s;";
    btnOk.onmouseover = () => { btnOk.style.background = "#45a049"; };
    btnOk.onmouseout = () => { btnOk.style.background = "#4CAF50"; };

    const close = () => { document.body.removeChild(overlay); };

    btnCancel.onclick = close;
    btnOk.onclick = () => { callback(inputEl.value); close(); };
    inputEl.onkeydown = (e) => {
        if (e.key === "Enter") { e.preventDefault(); btnOk.click(); }
        if (e.key === "Escape") { e.preventDefault(); btnCancel.click(); }
    };

    btnContainer.appendChild(btnCancel);
    btnContainer.appendChild(btnOk);
    box.appendChild(titleEl);
    box.appendChild(inputEl);
    box.appendChild(btnContainer);
    overlay.appendChild(box);
    document.body.appendChild(overlay);

    inputEl.focus();
    inputEl.select();
}

app.registerExtension({
    name: "XB_ToolBox.Wiring",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        
        if (nodeData.name === "XB_DynamicBus") {
            const onNodeCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                if (onNodeCreated) { onNodeCreated.apply(this, arguments); }
                
                this.portCount = 1;
                this.showTypes = true; 
                
                while (this.inputs && this.inputs.length > 1) this.removeInput(this.inputs.length - 1);
                while (this.outputs && this.outputs.length > 1) this.removeOutput(this.outputs.length - 1);

                this.inputs[0].label = " ";
                this.outputs[0].label = " ";
                this.inputs[0].customType = "*"; 

                this.widgets = [];
                this.title = ""; 
                this.color = "#151e29";
                this.bgcolor = "#0B1116";
                // 初始化极度压缩的尺寸
                this.size = [120, 46]; 
            };

            // ==========================================
            // 【究极榨干法】：高度死锁公式极限压缩
            // ==========================================
            const getExactHeight = (node) => {
                const rows = Math.max(node.inputs ? node.inputs.length : 0, node.outputs ? node.outputs.length : 0);
                // 30(标题高) + 孔位总高 + 16(极限底部留白，原先是28)
                return 30 + rows * LiteGraph.NODE_SLOT_HEIGHT + 16;
            };

            nodeType.prototype.computeSize = function(out) {
                return [90, getExactHeight(this)]; 
            };

            nodeType.prototype.onResize = function(size) {
                size[1] = getExactHeight(this); // 高度绝对死锁
                if (size[0] < 90) size[0] = 90; // 宽度防崩
            };

            const onConnectionsChange = nodeType.prototype.onConnectionsChange;
            nodeType.prototype.onConnectionsChange = function(slotType, slot, isConnected, link_info, ioSlot) {
                if (onConnectionsChange) { onConnectionsChange.apply(this, arguments); }

                if (slotType === LiteGraph.INPUT) {
                    if (isConnected && link_info) {
                        const originNode = app.graph.getNodeById(link_info.origin_id);
                        if (originNode) {
                            const originType = originNode.outputs[link_info.origin_slot].type;
                            this.inputs[slot].type = originType;
                            this.outputs[slot].type = originType;
                            this.inputs[slot].customType = originType;
                        }
                    } else {
                        this.inputs[slot].type = "*";
                        this.outputs[slot].type = "*";
                        this.inputs[slot].customType = "*";
                    }
                }
            };

            const onDrawForeground = nodeType.prototype.onDrawForeground;
            nodeType.prototype.onDrawForeground = function(ctx) {
                if (onDrawForeground) { onDrawForeground.apply(this, arguments); }
                
                this.size[1] = getExactHeight(this);

                if (this.showTypes && this.inputs) {
                    ctx.save();
                    ctx.fillStyle = "#A0B0C0";
                    ctx.font = "bold 12px Arial";
                    ctx.textAlign = "center";
                    ctx.textBaseline = "middle";

                    for (let i = 0; i < this.inputs.length; i++) {
                        const portY = this.getConnectionPos(true, i)[1] - this.pos[1];
                        let text = this.inputs[i].customType || "*";
                        if (text === "*") text = "ANY";
                        ctx.fillText(text, this.size[0] / 2, portY);
                    }
                    ctx.restore();
                }

                ctx.save();
                ctx.textAlign = "center";
                ctx.textBaseline = "middle";

                const centerX = this.size[0] / 2;    
                // 按钮核心位置极限上提！距底部仅 10 像素
                const btnY = this.size[1] - 10;      
                const btnInterval = 28;              

                // 深色护盾也同步压缩高度 (18像素高，完美包裹字体)
                const baseW = btnInterval * 2 + 28;
                ctx.fillStyle = "#0B1116";
                ctx.beginPath();
                ctx.roundRect(centerX - baseW/2, btnY - 9, baseW, 18, 5);
                ctx.fill();

                ctx.font = "16px Arial"; 
                // 调整视觉重心，让 emoji 看起来在护盾的正中央
                ctx.fillStyle = "#4CAF50"; ctx.fillText("➕", centerX - btnInterval, btnY);
                ctx.fillStyle = "#FFC107"; ctx.fillText("⭕", centerX,               btnY);
                ctx.fillStyle = "#F44336"; ctx.fillText("➖", centerX + btnInterval, btnY);

                ctx.restore();
            };

            const onMouseDown = nodeType.prototype.onMouseDown;
            nodeType.prototype.onMouseDown = function(e, pos, canvas) {
                const centerX = this.size[0] / 2;
                // Hitbox 同步极限上提
                const btnY = this.size[1] - 10;
                const btnInterval = 28;
                
                const hitRadiusSq = 13 * 13; 
                const distSq = (x1, y1, x2, y2) => (x1 - x2) ** 2 + (y1 - y2) ** 2;

                let hit = false;
                
                if (distSq(pos[0], pos[1], centerX - btnInterval, btnY) < hitRadiusSq) {
                    if (this.portCount < 20) {
                        this.portCount++;
                        const idx = this.portCount;
                        this.addInput("in_" + idx, "*");
                        this.addOutput("out_" + idx, "*");
                        this.inputs[idx - 1].label = " ";
                        this.outputs[idx - 1].label = " ";
                        this.inputs[idx - 1].customType = "*";
                    }
                    hit = true;
                } else if (distSq(pos[0], pos[1], centerX, btnY) < hitRadiusSq) {
                    this.showTypes = !this.showTypes;
                    hit = true;
                } else if (distSq(pos[0], pos[1], centerX + btnInterval, btnY) < hitRadiusSq) {
                    if (this.portCount > 1) {
                        const idx = this.portCount - 1;
                        if ((this.inputs[idx] && this.inputs[idx].link !== null) ||
                            (this.outputs[idx] && this.outputs[idx].links && this.outputs[idx].links.length > 0)) {
                            alert("【防呆设计】该通道上还有连线，请拔除线缆后再移除通道！");
                        } else {
                            this.removeInput(idx);
                            this.removeOutput(idx);
                            this.portCount--;
                        }
                    }
                    hit = true;
                }

                if (hit) {
                    this.size[1] = getExactHeight(this);
                    this.setDirtyCanvas(true, true);
                    return true; 
                }
                
                if (onMouseDown) { return onMouseDown.apply(this, arguments); }
                return false;
            };

            const onDblClick = nodeType.prototype.onDblClick;
            nodeType.prototype.onDblClick = function(e, pos, canvas) {
                if (this.showTypes) {
                    let clickedRow = -1;
                    for(let i = 0; i < this.inputs.length; i++) {
                        const portY = this.getConnectionPos(true, i)[1] - this.pos[1];
                        if (Math.abs(pos[1] - portY) < LiteGraph.NODE_SLOT_HEIGHT / 2) {
                            clickedRow = i;
                            break;
                        }
                    }

                    if (clickedRow >= 0) {
                        const currentType = this.inputs[clickedRow].customType || "*";
                        showCustomPrompt(
                            `📌 修改通道 ${clickedRow + 1} 的自定义类型:\n(留空则恢复为通配符 ANY)`, 
                            currentType === "*" ? "" : currentType, 
                            (newType) => {
                                const t = newType.trim() === "" ? "*" : newType.toUpperCase();
                                this.inputs[clickedRow].customType = t;
                                this.inputs[clickedRow].type = t;
                                this.outputs[clickedRow].type = t;
                                this.setDirtyCanvas(true, true);
                            }
                        );
                        return true; 
                    }
                }
                if (onDblClick) { return onDblClick.apply(this, arguments); }
                return false;
            };

            const onConfigure = nodeType.prototype.onConfigure;
            nodeType.prototype.onConfigure = function(info) {
                if (info.inputs) {
                    const savedPortCount = info.inputs.length;
                    while (this.inputs.length < savedPortCount) {
                        const nextIdx = this.inputs.length + 1;
                        this.addInput("in_" + nextIdx, "*");
                        this.addOutput("out_" + nextIdx, "*");
                    }
                    this.portCount = savedPortCount;
                    
                    for(let i=0; i<this.inputs.length; i++){
                        this.inputs[i].label = " ";
                        this.outputs[i].label = " ";
                    }
                }
                if (info.properties && info.properties.showTypes !== undefined) {
                    this.showTypes = info.properties.showTypes;
                }
                if (onConfigure) { onConfigure.apply(this, arguments); }
            };

            const onSerialize = nodeType.prototype.onSerialize;
            nodeType.prototype.onSerialize = function(o) {
                if (onSerialize) { onSerialize.apply(this, arguments); }
                o.properties = o.properties || {};
                o.properties.showTypes = this.showTypes;
            };
        }
    }
});