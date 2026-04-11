import { app } from "../../scripts/app.js";

// ==============================================================================
// 🛠️ 核心工具：深度比较，防死循环
// ==============================================================================
function isValEqual(v1, v2) {
    if (v1 === v2) return true;
    if (typeof v1 === 'object' && typeof v2 === 'object') {
        try { return JSON.stringify(v1) === JSON.stringify(v2); } 
        catch(e) { return false; }
    }
    return false;
}

// ==============================================================================
// 🚨 存档清洗协议：清除上一版的魔改残留，恢复 100% 原生 Group 功能
// ==============================================================================
function cleanCorruptedGroups() {
    if (!app.graph) return;
    const group = app.graph._groups.find(g => g.title === "🎮 XB 远程控制中心");
    if (group) {
        // 删除我们之前强加的自定义绘画和属性，让引擎接管
        if (group._xb_patched) {
            delete group.draw;
            delete group._xb_patched;
        }
        if (group.hasOwnProperty('recomputeInsideNodes')) {
            delete group.recomputeInsideNodes; // 恢复原生拖拽抓取能力
        }
    }
}

// ==============================================================================
// 🛠️ 终极同步引擎：大动脉直连 + 强制继承
// ==============================================================================
function applyMirrorSyncLogic(proxyNode) {
    if (proxyNode._xb_sync_interval) return; 

    const targetId = proxyNode.properties.xb_mirror_target_id;
    const realTarget = app.graph.getNodeById(targetId);
    
    if (!realTarget) return;

    // 强制继承初始值
    if (proxyNode.widgets && realTarget.widgets) {
        for (let i = 0; i < proxyNode.widgets.length; i++) {
            let pw = proxyNode.widgets[i];
            let tw = realTarget.widgets.find(w => w.name === pw.name);
            if (pw && tw) {
                pw.value = tw.value;
                if (pw.inputEl) pw.inputEl.value = tw.value;
                if (pw.element) pw.element.value = tw.value;
                pw._xb_last_value = (typeof tw.value === 'object' && tw.value !== null) ? JSON.parse(JSON.stringify(tw.value)) : tw.value;
                tw._xb_last_value = pw._xb_last_value;
            }
        }
    }
    proxyNode.imgs = realTarget.imgs ? [...realTarget.imgs] : null;

    proxyNode._xb_sync_interval = setInterval(() => {
        try {
            if (!app.graph) return;
            const currentTarget = app.graph.getNodeById(targetId);
            
            if (!currentTarget) {
                if (proxyNode.title !== "⚠️ 母节点已断开") {
                    proxyNode.title = "⚠️ 母节点已断开";
                    proxyNode.color = "#880000";
                    proxyNode.setDirtyCanvas(true, true);
                }
                return;
            } else if (proxyNode.title === "⚠️ 母节点已断开") {
                proxyNode.title = "🪞 " + (currentTarget.title || currentTarget.type);
                if (currentTarget.color) proxyNode.color = currentTarget.color;
                else delete proxyNode.color;
                if (currentTarget.bgcolor) proxyNode.bgcolor = currentTarget.bgcolor;
                else delete proxyNode.bgcolor;
                proxyNode.setDirtyCanvas(true, true);
            }

            let needRedraw = false;

            // 大动脉直连出图
            if (app.nodeOutputs && app.nodeOutputs[targetId]) {
                const motherOutput = app.nodeOutputs[targetId];
                const proxyOutput = app.nodeOutputs[proxyNode.id];
                if (motherOutput && proxyOutput !== motherOutput) {
                    app.nodeOutputs[proxyNode.id] = motherOutput; 
                    if (proxyNode.onExecuted) {
                        try { proxyNode.onExecuted(motherOutput); } catch(e) {}
                    }
                    needRedraw = true;
                }
            }

            // 图像指纹雷达
            const getImgFingerprint = (imgs) => imgs ? imgs.map(img => img.src || "").join('|') + '|' + imgs.length : "null";
            const currentImgState = getImgFingerprint(currentTarget.imgs);
            if (proxyNode._xb_last_img_state !== currentImgState) {
                proxyNode.imgs = currentTarget.imgs; 
                proxyNode._xb_last_img_state = currentImgState;
                needRedraw = true;
            }

            if (proxyNode.imageIndex !== currentTarget.imageIndex) { proxyNode.imageIndex = currentTarget.imageIndex; needRedraw = true; }
            if (proxyNode.animatedImages !== currentTarget.animatedImages) { proxyNode.animatedImages = currentTarget.animatedImages; needRedraw = true; }

            // 参数双向绑定
            if (proxyNode.widgets && currentTarget.widgets) {
                for (let i = 0; i < proxyNode.widgets.length; i++) {
                    let pw = proxyNode.widgets[i];
                    let tw = currentTarget.widgets.find(w => w.name === pw.name);
                    
                    if (pw && tw) {
                        if (!isValEqual(pw.value, tw.value)) {
                            let pActive = (pw.inputEl && document.activeElement === pw.inputEl) || (pw.element && document.activeElement === pw.element);
                            let tActive = (tw.inputEl && document.activeElement === tw.inputEl) || (tw.element && document.activeElement === tw.element);

                            if (pActive) {
                                tw.value = pw.value;
                                if (tw.inputEl && tw.inputEl.value !== pw.value) tw.inputEl.value = pw.value;
                                if (tw.element && tw.element.value !== pw.value) tw.element.value = pw.value;
                                try { if (tw.callback) tw.callback(tw.value, app.canvas, currentTarget, null, {}); } catch(e) {}
                                needRedraw = true;
                            } else if (tActive) {
                                pw.value = tw.value;
                                if (pw.inputEl && pw.inputEl.value !== tw.value) pw.inputEl.value = tw.value;
                                if (pw.element && pw.element.value !== tw.value) pw.element.value = tw.value;
                                try { if (pw.callback) pw.callback(pw.value, app.canvas, proxyNode, null, {}); } catch(e) {}
                                needRedraw = true;
                            } else {
                                if (!isValEqual(pw.value, pw._xb_last_value)) {
                                    tw.value = pw.value;
                                    if (tw.inputEl) tw.inputEl.value = pw.value;
                                    if (tw.element) tw.element.value = pw.value;
                                    try { if (tw.callback) tw.callback(tw.value, app.canvas, currentTarget, null, {}); } catch(e) {}
                                } else if (!isValEqual(tw.value, tw._xb_last_value)) {
                                    pw.value = tw.value;
                                    if (pw.inputEl) pw.inputEl.value = tw.value;
                                    if (pw.element) pw.element.value = tw.value;
                                    try { if (pw.callback) pw.callback(pw.value, app.canvas, proxyNode, null, {}); } catch(e) {}
                                } else {
                                    pw.value = tw.value;
                                    if (pw.inputEl) pw.inputEl.value = tw.value;
                                    if (pw.element) pw.element.value = tw.value;
                                }
                                needRedraw = true;
                            }
                        }
                        pw._xb_last_value = (typeof pw.value === 'object' && pw.value !== null) ? JSON.parse(JSON.stringify(pw.value)) : pw.value;
                        tw._xb_last_value = (typeof tw.value === 'object' && tw.value !== null) ? JSON.parse(JSON.stringify(tw.value)) : tw.value;
                    }
                }
            }

            if (needRedraw) {
                proxyNode.setDirtyCanvas(true, true);
                currentTarget.setDirtyCanvas(true, true);
            }
        } catch (err) {}
    }, 50);

    const origOnRemoved = proxyNode.onRemoved;
    proxyNode.onRemoved = function() {
        clearInterval(this._xb_sync_interval);
        if (origOnRemoved) origOnRemoved.apply(this, arguments);
    };
}

// 读档拦截恢复影子
const origOnNodeAdded = LGraph.prototype.add;
LGraph.prototype.add = function(node, skip_compute_order) {
    origOnNodeAdded.apply(this, arguments);
    if (node.properties && node.properties.xb_mirror_target_id) {
        while(node.inputs && node.inputs.length > 0) node.removeInput(0);
        while(node.outputs && node.outputs.length > 0) node.removeOutput(0);
        node.isVirtualNode = true; 
        applyMirrorSyncLogic(node);
    }
};

// ==============================================================================
// 📦 原生组件选择弹窗
// ==============================================================================
function showMultiPickerModal(validNodes, onConfirmCallback) {
    const existing = document.getElementById("xb-picker-modal");
    if (existing) existing.remove();

    const overlay = document.createElement("div");
    overlay.id = "xb-picker-modal";
    overlay.style.cssText = `
        position: fixed; top: 0; left: 0; width: 100vw; height: 100vh;
        background: rgba(0,0,0,0.7); backdrop-filter: blur(8px);
        display: flex; justify-content: center; align-items: center; z-index: 10000;
    `;

    overlay.onpointerdown = e => e.stopPropagation();
    overlay.onmousedown = e => e.stopPropagation();
    overlay.onwheel = e => e.stopPropagation();
    overlay.oncontextmenu = e => e.stopPropagation();

    const box = document.createElement("div");
    box.style.cssText = `
        background: #151a21; border: 1px solid #334; border-radius: 12px;
        width: 500px; max-height: 80vh; display: flex; flex-direction: column;
        box-shadow: 0 20px 50px rgba(0,0,0,0.8); overflow: hidden; font-family: sans-serif;
    `;

    const header = document.createElement("div");
    header.style.cssText = "padding: 15px 20px; background: #1c232d; border-bottom: 1px solid #334; display: flex; justify-content: space-between; align-items: center;";
    header.innerHTML = `<span style="color: #fff; font-weight: bold; font-size: 16px;">📦 批量选择要克隆的组件</span>`;
    
    const closeBtn = document.createElement("button");
    closeBtn.innerText = "✖";
    closeBtn.style.cssText = "background: none; border: none; color: #889; cursor: pointer; font-size: 16px;";
    closeBtn.onclick = (e) => { e.preventDefault(); overlay.remove(); };
    header.appendChild(closeBtn);

    const listContainer = document.createElement("div");
    listContainer.style.cssText = "padding: 15px; overflow-y: auto; flex: 1; display: flex; flex-direction: column; gap: 8px;";
    
    const checkboxes = [];

    if (validNodes.length === 0) {
        listContainer.innerHTML = `<div style="padding: 20px; text-align: center; color: #666;">当前工作流无可用节点。</div>`;
    } else {
        validNodes.forEach(node => {
            const label = document.createElement("label");
            label.style.cssText = `
                background: #1e2630; border: 1px solid #2a3441; border-radius: 6px; padding: 12px 15px;
                color: #ccc; cursor: pointer; display: flex; align-items: center; gap: 15px; transition: 0.2s;
            `;
            
            const cb = document.createElement("input");
            cb.type = "checkbox";
            cb.value = node.id;
            cb.style.cssText = "width: 18px; height: 18px; cursor: pointer;";
            checkboxes.push(cb);

            const textDiv = document.createElement("div");
            textDiv.style.cssText = "display: flex; flex-direction: column;";
            textDiv.innerHTML = `
                <span style="font-weight: bold; font-size: 14px; color: #fff;">${node.title || node.type}</span>
                <span style="font-size: 11px; color: #667; margin-top: 4px;">ID: ${node.id} | 类型: ${node.type}</span>
            `;

            label.appendChild(cb);
            label.appendChild(textDiv);
            label.onmouseover = () => { label.style.background = "#283442"; label.style.borderColor = "#4a5a70"; };
            label.onmouseout = () => { label.style.background = "#1e2630"; label.style.borderColor = "#2a3441"; };
            
            listContainer.appendChild(label);
        });
    }

    const footer = document.createElement("div");
    footer.style.cssText = "padding: 15px 20px; background: #1c232d; border-top: 1px solid #334; display: flex; justify-content: space-between; align-items: center;";
    
    const selectAllBtn = document.createElement("button");
    selectAllBtn.innerText = "☑ 全选 / 反选";
    selectAllBtn.style.cssText = "padding: 8px 15px; background: #2a3441; color: white; border: none; border-radius: 4px; cursor: pointer;";
    selectAllBtn.onclick = (e) => {
        e.preventDefault();
        const allChecked = checkboxes.every(cb => cb.checked);
        checkboxes.forEach(cb => cb.checked = !allChecked);
    };

    const confirmBtn = document.createElement("button");
    confirmBtn.innerText = "🚀 执行克隆";
    confirmBtn.style.cssText = "padding: 8px 20px; background: #4CAF50; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: bold;";
    
    confirmBtn.onclick = (e) => {
        e.preventDefault();
        const selectedIds = checkboxes.filter(cb => cb.checked).map(cb => Number(cb.value));
        const selectedNodes = selectedIds.map(id => app.graph.getNodeById(id));
        
        overlay.remove(); 
        if (selectedNodes.length > 0) {
            setTimeout(() => onConfirmCallback(selectedNodes), 15);
        }
    };

    footer.appendChild(selectAllBtn);
    footer.appendChild(confirmBtn);

    box.appendChild(header);
    box.appendChild(listContainer);
    box.appendChild(footer);
    overlay.appendChild(box);
    document.body.appendChild(overlay);
}

// ==============================================================================
// 🚀 核心控制台：100% 拥抱原生 API，拒绝任何底层魔改
// ==============================================================================
app.registerExtension({
    name: "XB_ToolBox.Dashboard",

    loadedGraphNode(node) {
        if (node.properties && node.properties.xb_mirror_target_id) {
            while(node.inputs && node.inputs.length > 0) node.removeInput(0);
            while(node.outputs && node.outputs.length > 0) node.removeOutput(0);
            node.isVirtualNode = true; 
            applyMirrorSyncLogic(node);
        }
    },
    
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (nodeData.name === "XB_Dashboard_Zen") {
            
            const origConfigure = nodeType.prototype.configure;
            nodeType.prototype.configure = function(info) {
                if (info && info.widgets_values) info.widgets_values = []; 
                if (origConfigure) origConfigure.apply(this, arguments);
                
                // 启动清洗协议：把旧存档里被污染的组洗白
                setTimeout(() => cleanCorruptedGroups(), 200);
            };

            const onNodeCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                if (onNodeCreated) onNodeCreated.apply(this, arguments);
                
                this.title = "🪄 XB 远程控制中心";
                this.properties = this.properties || {};
                
                this.addWidget("button", "➕ 克隆组件", "extract", () => {
                    setTimeout(() => this.openExtractModal(), 15);
                });

                this.addWidget("button", "🧹 清除组件", "clear", () => {
                    setTimeout(() => this.destroyAllMirrors(), 15);
                });
                
                this.size = this.computeSize();
            };

            nodeType.prototype.openExtractModal = function() {
                const validNodes = app.graph._nodes.filter(n => 
                    n.id !== this.id && 
                    n.type !== "Group" &&
                    n.type !== "Reroute" &&
                    !(n.properties && n.properties.xb_mirror_target_id)
                );

                showMultiPickerModal(validNodes, (selectedNodes) => {
                    this.createMirrorsInPlace(selectedNodes);
                });
            };

            nodeType.prototype.createMirrorsInPlace = function(nodesToClone) {
                // 1. 完全调用官方 API 创建原生组
                let group = app.graph._groups.find(g => g.title === "🎮 XB 远程控制中心");
                if (!group) {
                    group = new LiteGraph.LGraphGroup();
                    group.title = "🎮 XB 远程控制中心";
                    app.graph.add(group);
                }

                // 2. 根据中枢节点计算坐标
                let newGroupX = this.pos[0] - 40;
                let newGroupY = this.pos[1] - 100;

                let startX = this.pos[0] + this.size[0] + 40; 
                let startY = this.pos[1]; 
                
                let maxRightEdge = this.pos[0] + this.size[0];
                let maxBottomEdge = this.pos[1] + this.size[1];

                const existingProxies = app.graph._nodes.filter(n => n.properties && n.properties.xb_mirror_target_id);
                if (existingProxies.length > 0) {
                    existingProxies.forEach(p => {
                        const pRight = p.pos[0] + p.size[0];
                        const pBottom = p.pos[1] + p.size[1];
                        if (pRight + 40 > startX) startX = pRight + 40;
                        if (pRight > maxRightEdge) maxRightEdge = pRight;
                        if (pBottom > maxBottomEdge) maxBottomEdge = pBottom;
                    });
                }

                // 3. 克隆节点
                nodesToClone.forEach(target => {
                    const existingProxy = existingProxies.find(n => n.properties.xb_mirror_target_id === target.id);
                    if (existingProxy) return;

                    const proxy = LiteGraph.createNode(target.type);
                    app.graph.add(proxy);

                    while(proxy.inputs && proxy.inputs.length > 0) proxy.removeInput(0);
                    while(proxy.outputs && proxy.outputs.length > 0) proxy.removeOutput(0);
                    
                    proxy.isVirtualNode = true;
                    proxy.title = "🪞 " + (target.title || target.type);
                    
                    // 完全继承原生颜色
                    if (target.color) proxy.color = target.color;
                    if (target.bgcolor) proxy.bgcolor = target.bgcolor;
                    
                    proxy.properties = proxy.properties || {};
                    proxy.properties.xb_mirror_target_id = target.id;

                    proxy.pos = [startX, startY];
                    
                    const proxyRight = proxy.pos[0] + proxy.size[0];
                    const proxyBottom = proxy.pos[1] + proxy.size[1];
                    
                    if (proxyRight > maxRightEdge) maxRightEdge = proxyRight;
                    if (proxyBottom > maxBottomEdge) maxBottomEdge = proxyBottom;

                    startX += proxy.size[0] + 40;

                    applyMirrorSyncLogic(proxy);
                });

                // 4. 给原生组赋值尺寸
                group.pos = [newGroupX, newGroupY];
                group.size = [maxRightEdge - newGroupX + 40, maxBottomEdge - newGroupY + 40];

                // 5. 🚨 终极原生奥义：直接调用 LiteGraph 原生的重算方法，让引擎自己去抓节点、写内存！
                if (group.recomputeInsideNodes) {
                    group.recomputeInsideNodes();
                }

                app.graph.change();
                app.canvas.setDirtyCanvas(true, true);
            };

            nodeType.prototype.destroyAllMirrors = function() {
                if (confirm("确定要销毁所有克隆组件吗？（原工作流完全不受影响）")) {
                    const proxies = app.graph._nodes.filter(n => n.properties && n.properties.xb_mirror_target_id);
                    proxies.forEach(p => app.graph.remove(p));

                    const group = app.graph._groups.find(g => g.title === "🎮 XB 远程控制中心");
                    if (group) app.graph.remove(group);

                    app.graph.change();
                    app.canvas.setDirtyCanvas(true, true);
                }
            };
        }
    }
});