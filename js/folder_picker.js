import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

app.registerExtension({
    name: "XB_ToolBox.FolderPicker",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        // 精准狙击我们的批量加载节点
        if (nodeData.name === "XB_BatchFolderLoader") {
            const onNodeCreated = nodeType.prototype.onNodeCreated;
            
            nodeType.prototype.onNodeCreated = function () {
                const r = onNodeCreated ? onNodeCreated.apply(this, arguments) : undefined;
                
                // 找到那个蠢笨的 directory 文本输入框
                const dirWidget = this.widgets.find(w => w.name === "directory");
                
                // 在节点上凭空捏造一个高大上的“选择文件夹”按钮
                const btnWidget = this.addWidget("button", "📁 浏览文件夹...", "browse", () => {
                    
                    // 呼叫后端 Python 弹出 Windows 窗口
                    api.fetchApi("/xb_toolbox/choose_folder", { method: "POST" })
                    .then(res => res.json())
                    .then(data => {
                        // 如果用户选了路径，直接塞进文本框里
                        if (data.path) {
                            dirWidget.value = data.path;
                        }
                    }).catch(err => console.error("文件夹选择器唤醒失败:", err));
                    
                });
                
                return r;
            };
        }
    }
});