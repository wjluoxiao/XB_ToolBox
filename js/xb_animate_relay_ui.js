import { app } from "../../scripts/app.js";
import { installRelayLock } from "./xb_compat.js";

// ============================================================
// Animate & SCAIL 无限接力点 — 独立参考图 锁定/解锁 UI
//   XB_WanAnimate_RelayNode(_New) / XB_WanInfiniteTalk_RelayNode_MultiRef(_AllInOne)
// ============================================================
// 【Nodes 2.0 适配说明】
//   · 原实现把 🔒 蒙版画在 onDrawForeground、点击拦截放在 onMouseDown、预览屏蔽放在 onDrawBackground，
//     这三个钩子在 Nodes 2.0（DOM 渲染）下都不会被调用 → 锁定态完全失效。
//   · 现统一走 installRelayLock：锁定态直接隐藏"参考图文件 / 上传按钮"等本地部件，
//     并显示一个 DOM widget 提示条（经典模式与 2.0 表现一致）。

const RELAY_LOCK_NODES = ["XB_WanAnimate_RelayNode", "XB_WanAnimate_RelayNode_New", "XB_WanInfiniteTalk_RelayNode_MultiRef", "XB_WanInfiniteTalk_RelayNode_AllInOne"];

const MODE_WIDGETS = ["use_local_ref_image", "start_image_mode"];
const UNLOCKED_VALUE = "独立参考图";

app.registerExtension({
    name: "xiaobai.animate_scail_relay_lock_ui",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (!RELAY_LOCK_NODES.includes(nodeData.name)) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            if (onNodeCreated) onNodeCreated.apply(this, arguments);
            const node = this;

            // 找不到模式开关时按"锁定"处理（与旧实现保持一致）：默认走总线全局参考图
            const isLocked = (n) => {
                let tw = (n.widgets || []).find(w => w.name === "use_local_ref_image");
                if (!tw) tw = (n.widgets || []).find(w => w.name === "start_image_mode");
                if (!tw) return true;
                return tw.value !== UNLOCKED_VALUE;
            };

            installRelayLock(node, {
                text: "🔒 参考图继承自总线全局图",
                bannerName: "xb_animate_relay_banner",
                names: ["ref_image_file", "image_upload", "upload"],
                watch: MODE_WIDGETS,
                hideImgs: true,
                locked: isLocked,
            });
        };
    },
});
