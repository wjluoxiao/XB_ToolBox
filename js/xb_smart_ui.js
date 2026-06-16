import { app } from "../../scripts/app.js";

// ============================================================
// XB_Wan_RelayNode — 接力点智能 UI
// ============================================================

const isZH = navigator.language.startsWith("zh");

app.registerExtension({
    name: "XB_ToolBox.SmartUI",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (nodeData.name === "XB_Wan_RelayNode") {
            
            nodeType.prototype.updateWidgetState = function () {
                const optInput = this.inputs?.find(i => i.name === "opt_end_image");
                const imgCombo = this.widgets?.find(w => w.name === "end_image_file");
                
                let uploadBtn = this.widgets?.find(w => w.type === "button" && !w.name.includes("randomize"));

                if (optInput && imgCombo && uploadBtn) {
                    const isConnected = !!optInput.link; 
                    
                    if (isConnected) {
                        imgCombo.disabled = true;
                        
                        if (!uploadBtn._orig_callback) uploadBtn._orig_callback = uploadBtn.callback;
                        uploadBtn.name = isZH ? "🔒 端口已被连线接管" : "Locked by connection"; 
                        uploadBtn.label = isZH ? "🔒 端口已被连线接管" : "Locked by connection"; 
                        uploadBtn.callback = null; 

                    } else {
                        imgCombo.disabled = false;
                        
                        uploadBtn.name = isZH ? "选择上传尾帧图片" : "Select/Upload End Frame"; 
                        uploadBtn.label = isZH ? "选择上传尾帧图片" : "Select/Upload End Frame"; 
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