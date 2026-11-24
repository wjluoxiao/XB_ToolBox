import { app } from "../../scripts/app.js";
import { setupVideoPreview } from "./xb_video_preview.js";
import { rememberOutput, restorePreview, installAutoRestore } from "./xb_preview_restore.js";

// ============================================================
// XB-BOX - 🎬 视频批量拼接 —— 预览播放行为
//   1. 播放行为与「XB-BOX - 🎬 保存视频」一致：新视频静音自动播放，
//      鼠标指上才出声，移出立刻静音（统一走 xb_video_preview.js）。
//   2. 预览记忆（各分段 + 拼接结果）统一由 xb_preview_restore.js 处理：
//      跑完记进 node.properties，载入工作流 / 复制粘贴 / 撤销重做 时还原。
// ============================================================

const NODE_TYPE = "XB_BatchVideoMerge";

app.registerExtension({
    name: "XB_ToolBox.BatchVideoMerge",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData?.name !== NODE_TYPE) return;
        const origCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = origCreated?.apply(this, arguments);
            const origExec = this.onExecuted;
            this.onExecuted = function (output) {
                try { rememberOutput(this, output); } catch (e) { console.warn("[XB-BOX 视频批量拼接]", e); }
                return origExec?.apply(this, arguments);
            };
            try {
                setupVideoPreview(this);
            } catch (e) {
                console.warn("[XB-BOX 视频批量拼接] 预览控制初始化失败", e);
            }
            installAutoRestore(this);   // 载入工作流 / 复制粘贴 / 撤销重做 都还原预览
            return r;
        };
    },

    async loadedGraphNode(node) {
        if (node?.type !== NODE_TYPE) return;
        setTimeout(() => { restorePreview(node); }, 600);
    },
});
