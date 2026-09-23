import { app } from "../../scripts/app.js";
import { installRelayLock } from "./xb_compat.js";

// ============================================================
// XB_Wan_RelayNode — 接力点智能 UI（端口被连线接管时锁定本地部件）
// ============================================================
// 【Nodes 2.0 适配说明】
//   旧实现靠 widget.disabled + 改 label + 直接改 inputEl/element 样式，在 Nodes 2.0 下：
//     · 数字/下拉是 Vue 组件，没有 inputEl/element（样式与 pointerEvents 失效）
//     · widget.disabled 在经典画布下不起作用（部件照样能点）
//   现在统一交给 installRelayLock（与 xb_relay_ui.js 同一套实现，靠 node._xbRelayLock 去重，
//   两个扩展同时存在也不会重复生效）。

app.registerExtension({
    name: "XB_ToolBox.SmartUI",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (nodeData.name !== "XB_Wan_RelayNode") return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            if (onNodeCreated) onNodeCreated.apply(this, arguments);
            const node = this;

            installRelayLock(node, {
                text: "🔒 端口已被连线接管",
                bannerName: "xb_relay_banner",
                names: ["end_image_file", "image_upload", "upload"],
                hideImgs: true,
                locked: (n) => {
                    const inp = n.inputs?.find((i) => i.name === "opt_end_image");
                    return inp?.link != null;
                },
            });
        };
    },
});
