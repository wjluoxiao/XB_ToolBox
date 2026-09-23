import { app } from "../../scripts/app.js";
import { installRelayLock, setWidgetValue } from "./xb_compat.js";

// ============================================================
// XB_Wan_RelayNode — 首尾帧接力点 UI 交互
// ============================================================
// 【Nodes 2.0 适配说明】
//   · 原来的 🔒 蒙版画在 onDrawForeground、点击拦截靠 onMouseDown —— 2.0 下这两个钩子都不会被调用，
//     现统一改为：端口被连线接管时 **直接隐藏本地部件** + DOM widget 提示条（经典/2.0 通用）。
//   · 原来在 onDrawBackground 里把 this.imgs 置空以屏蔽预览的写法 2.0 下无效，
//     改为在锁定状态变化时整体收走 / 归还 node.imgs（不再依赖绘制钩子）。
//   · 经典模式下 onConnectionsChange 仍会触发，因此两种模式行为一致。

app.registerExtension({
    name: "xiaobai.relay_node_ui_master",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (nodeData.name !== "XB_Wan_RelayNode") return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            if (onNodeCreated) onNodeCreated.apply(this, arguments);
            const node = this;

            installRelayLock(node, {
                text: "🔒 尾图已由连线接管",
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

// ============================================================
// 🧮 _New 接力点自动计算：总计 = 单次帧数 × 接力数量 − 重叠帧数 × (接力数量−1)
// 重叠参数已在接力节点上，直接读本地 widget，无需轮询
// ============================================================
const RELAY_NODES_CALC = [
    "XB_WanAnimate_RelayNode_New",
    "XB_WanInfiniteTalk_RelayNode_New",
    "XB_WanSCAIL_RelayNode_New",
    "XB_WanInfiniteTalk_RelayNode_MultiRef",
    "XB_WanInfiniteTalk_RelayNode_AllInOne",
];

const RELAY_OVERLAP = {
    "XB_WanAnimate_RelayNode_New":    "continue_motion_max_frames",
    "XB_WanInfiniteTalk_RelayNode_New": "motion_frame_count",
    "XB_WanSCAIL_RelayNode_New":      "previous_frame_count",
    "XB_WanInfiniteTalk_RelayNode_MultiRef": "motion_frame_count",
    "XB_WanInfiniteTalk_RelayNode_AllInOne": "motion_frame_count",
};

app.registerExtension({
    name: "xiaobai.relay_new_auto_calc",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (!RELAY_NODES_CALC.includes(nodeData.name)) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            if (onNodeCreated) onNodeCreated.apply(this, arguments);
            const node = this;

            const wSeg = node.widgets?.find(w => w.name === "segment_length");
            const wCnt = node.widgets?.find(w => w.name === "relay_count");
            const wDisp = node.widgets?.find(w => w.name === "total_frames_display");
            const ovName = RELAY_OVERLAP[node.comfyClass];
            const wOvl = ovName ? node.widgets?.find(w => w.name === ovName) : null;

            if (!wSeg || !wCnt || !wDisp) return;

            const update = () => {
                const seg = parseInt(wSeg.value) || 0;
                const cnt = parseInt(wCnt.value) || 0;
                if (seg <= 0 || cnt <= 0) { setWidgetValue(wDisp, ""); return; }
                const ovl = wOvl ? (parseInt(wOvl.value) || 0) : 0;
                setWidgetValue(wDisp, String(Math.max(1, seg * cnt - ovl * (cnt - 1))));
                app.graph.setDirtyCanvas(true, false);
            };

            [wSeg, wCnt, wOvl].forEach(w => {
                if (!w) return;
                const orig = w.callback;
                w.callback = function(v) { if (orig) orig.call(this, v); update(); };
            });

            setTimeout(update, 50);
        };
    }
});
