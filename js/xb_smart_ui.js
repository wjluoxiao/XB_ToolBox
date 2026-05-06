import { app } from "../../scripts/app.js";

app.registerExtension({
    name: "XB_ToolBox.SmartUI",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (nodeData.name === "XB_Wan_RelayNode") {
            
            nodeType.prototype.updateWidgetState = function () {
                const optInput = this.inputs?.find(i => i.name === "opt_end_image");
                // 🔴 核心修复：只认原始名字，绝不乱改名
                const imgCombo = this.widgets?.find(w => w.name === "end_image_file");
                
                let uploadBtn = this.widgets?.find(w => w.type === "button" && !w.name.includes("randomize"));

                if (optInput && imgCombo && uploadBtn) {
                    const isConnected = !!optInput.link; 
                    
                    if (isConnected) {
                        // 🔒 连线状态：只变灰，绝对不准改 imgCombo.name ！(否则会导致后端报错)
                        imgCombo.disabled = true;
                        
                        // 按钮可以随意改名，因为它不负责往后端发数据
                        if (!uploadBtn._orig_callback) uploadBtn._orig_callback = uploadBtn.callback;
                        uploadBtn.name = "🔒 端口已被连线接管"; 
                        uploadBtn.label = "🔒 端口已被连线接管"; 
                        uploadBtn.callback = null; 

                    } else {
                        // 🔓 断线状态：恢复使用
                        imgCombo.disabled = false;
                        
                        uploadBtn.name = "选择上传尾帧图片"; 
                        uploadBtn.label = "选择上传尾帧图片"; 
                        if (uploadBtn._orig_callback) uploadBtn.callback = uploadBtn._orig_callback;
                    }
                    this.setDirtyCanvas(true, true);
                }
            };

            const onConnectionsChange = nodeType.prototype.onConnectionsChange;
            nodeType.prototype.onConnectionsChange = function (type, index, connected, link_info) {
                if (onConnectionsChange) {
                    onConnectionsChange.apply(this, arguments);
                }
                if (type === 1 && this.inputs && this.inputs[index].name === "opt_end_image") {
                    this.updateWidgetState();
                }
            };

            const onNodeCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                if (onNodeCreated) {
                    onNodeCreated.apply(this, arguments);
                }
                setTimeout(() => this.updateWidgetState(), 300);
            };
        }
    }
});