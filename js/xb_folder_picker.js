import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// ============================================================
// XB_BatchFolderLoader — 文件夹选择器 UI
// ============================================================

const isZH = navigator.language.startsWith("zh");

app.registerExtension({
    name: "XB_ToolBox.FolderPicker",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (nodeData.name === "XB_BatchFolderLoader") {
            const onNodeCreated = nodeType.prototype.onNodeCreated;
            
            nodeType.prototype.onNodeCreated = function () {
                const r = onNodeCreated ? onNodeCreated.apply(this, arguments) : undefined;
                const dirWidget = this.widgets.find(w => w.name === "directory");
                
                const btnLabel = isZH ? "📁 浏览文件夹..." : "📁 Browse Folder...";
                const btnWidget = this.addWidget("button", btnLabel, "browse", () => {
                    api.fetchApi("/xb_toolbox/choose_folder", { method: "POST" })
                    .then(res => res.json())
                    .then(data => {
                        if (data.path) {
                            dirWidget.value = data.path;
                        }
                    }).catch(err => {});
                });
                return r;
            };
        }
    }
});