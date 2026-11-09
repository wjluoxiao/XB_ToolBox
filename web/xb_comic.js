import { app } from "../../scripts/app.js";

app.registerExtension({
    name: "XB_ToolBox.Comic",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        try {
            if (nodeData.name === "XB_ComicPromptParser") {
                const orig = nodeType.prototype.onNodeCreated || function () { };
                nodeType.prototype.onNodeCreated = function () {
                    const r = orig.apply(this, arguments);
                    this.size = [440, 260];
                    return r;
                };
            }
            if (nodeData.name === "XB_ComicTextRenderer") {
                const orig = nodeType.prototype.onNodeCreated || function () { };
                nodeType.prototype.onNodeCreated = function () {
                    const r = orig.apply(this, arguments);
                    this.size = [340, 380];
                    return r;
                };
            }
            if (nodeData.name === "XB_AutoBubbleTextRenderer") {
                const orig = nodeType.prototype.onNodeCreated || function () { };
                nodeType.prototype.onNodeCreated = function () {
                    const r = orig.apply(this, arguments);
                    this.size = [400, 560];
                    return r;
                };
            }
        } catch (e) {
            console.warn("[XB_ToolBox.Comic] JS skipped:", e);
        }
    },
});
