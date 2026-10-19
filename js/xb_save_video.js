import { app } from "../../scripts/app.js";
import { setupVideoPreview } from "./xb_video_preview.js";

// ============================================================
// XB-BOX - 🎬 保存视频 —— 预览播放行为
//   自动播放 / 悬停出声 / 经典模式放开预览尺寸下限 由 xb_video_preview.js 统一处理；
//   本文件额外把动态下拉子项的英文名补成中文（codec → 编解码器）。
// ============================================================

const NODE_TYPE = "XB_SaveVideo";

// 动态下拉（如 format 下面的 codec）的子项在界面上取不到后端 display_name，
// 前端会退回成英文名，这里补上中文显示。
const WIDGET_LABELS = [
    [/\.codec$/, "编解码器"],
    [/\.encoding$/, "编码模式"],
    [/\.crf$/, "CRF"],
];

/** 修正嵌套下拉部件的显示名（format 一改动部件可能重建，所以轮询里反复校正） */
function localizeWidgetLabels(node) {
    let changed = false;
    for (const w of node.widgets || []) {
        if (!w || !w.name) continue;
        for (const [re, label] of WIDGET_LABELS) {
            if (re.test(w.name) && w.label !== label) {
                w.label = label;
                changed = true;
            }
        }
    }
    if (changed) node.setDirtyCanvas?.(true, false);
}

app.registerExtension({
    name: "XB_ToolBox.SaveVideo",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData?.name !== NODE_TYPE) return;
        const origCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = origCreated?.apply(this, arguments);
            try {
                setupVideoPreview(this, { onApply: localizeWidgetLabels });
            } catch (e) {
                console.warn("[XB-BOX 保存视频] 预览控制初始化失败", e);
            }
            return r;
        };
    },
});
