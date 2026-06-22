import { app } from "../../scripts/app.js";

// ============================================================
// 每个节点独立尺寸参数，格式： "节点名": [默认初始宽度, 绝对最小宽度]
// ============================================================

const SIZES = {
    "XB_VRAM_Calculator": [360, 200],
    "XB_ChunkVisualization": [360, 200],
    "XB_VideoParamsMaster": [360, 200],
    "XB_ImageParamsMaster": [360, 200],
    "XB_MasterParameter": [360, 200],
    "XB_UNetBlockSwap": [360, 200],
    "XB_CheckpointBlockSwap": [360, 200],
    "XB_UNetNameBroadcaster": [360, 200],
    "XB_CLIPNameBroadcaster": [360, 200],
    "XB_Dashboard_Zen": [360, 200],
    "XB_SamplerChunkMaster": [360, 200],
    "XB_WanImageToVideo": [360, 200],
    "XB_WanFirstLastFrameToVideo": [360, 200],
    "XB_WanFunControlToVideo": [360, 200],
    "XB_WanVaceToVideo": [360, 200],
    "XB_Wan22FunControlToVideo": [360, 200],
    "XB_WanSoundImageToVideo": [360, 200],
    "XB_WanInfiniteTalkToVideo": [360, 200],
    "XB_WanInfiniteTalkToVideo_Single": [360, 200],
    "XB_WanInfiniteTalkToVideo_Dual": [360, 200],
    "XB_WanVAEDecodeTiled": [360, 200],
    "XB_WanFunInpaintToVideo": [360, 200],
    "XB_WanCameraImageToVideo": [360, 200],
    "XB_WanPhantomSubjectToVideo": [360, 200],
    "XB_WanHuMoImageToVideo": [360, 200],
    "XB_Wan22ImageToVideoLatent": [360, 200],
    "XB_WanSoundImageToVideoExtend": [360, 200],
    "XB_WanSCAILToVideo": [360, 200],
    "XB_WanSCAILToVideoPro": [360, 200],
    "XB_BatchFolderLoader": [360, 200],
    "XB_Wan_ParamBus": [360, 200],
    "XB_Wan_RelayNode": [360, 200],
    "XB_Wan_InfiniteRelayNode": [360, 200],
    "XB_Video_Merger": [360, 200],
    "XB_StoryboardSlicer": [360, 200],
    "XB_SageAttentionAccelerator": [360, 200],
    "XB_ROCmKSampler": [360, 200],
    "XB_ROCmKSamplerAdvanced": [360, 200],
    "XB_ROCmSamplerCustom": [360, 200],
    "XB_ROCmSamplerCustomAdvanced": [360, 200],
    "XB_ROCmVAEDecode": [360, 200],
    "XB_ROCmVAEEncode": [360, 200],
    "XB_ROCmVAEDecodeTemporal": [360, 200],
    "XB_ROCmMemCleaner": [360, 200],
    "XB_WanT5Loader": [360, 200],
    "XB_WanCompileSettings": [360, 200],
    "XB_WanModelLoader": [360, 200],
    "XB_WanBlockSwap": [360, 200],
    "XB_WanSampler": [360, 200],
    "XB_WanTextEncode": [360, 200],
    "XB_WanVAELoader": [360, 200],
    "XB_WanDecode": [360, 200],
    "XB_WanAnimateToVideo": [360, 200],
    "XB_WanAnimate_ParamBus": [360, 200],
    "XB_WanAnimate_RelayNode": [360, 200],
    "XB_WanInfiniteTalk_ParamBus": [360, 200],
    "XB_WanInfiniteTalk_RelayNode": [360, 200],
    "XB_HumanSegmentation": [360, 200],
    "XB_HumanSegModelLoader": [360, 200],
    "XB_CanvasLabel": [360, 200],
    "XB_AudioSlicer": [360, 200],
    "XB_AudioSlicerV1": [360, 200],
    "XB_AudioSlicerV2": [360, 200],
    "XB_AudioSlicerV3": [360, 200],
    "XB_StringMerge": [360, 200],
};

app.registerExtension({
    name: "XB_ToolBox.NodeSizer",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        const sizeConfig = SIZES[nodeData.name];
        if (sizeConfig === undefined) return;

        const [defW, minW] = sizeConfig;

        // 🛡️ 核心修复：解除“棘轮效应”，恢复自由缩放
        const origComputeSize = nodeType.prototype.computeSize;
        nodeType.prototype.computeSize = function (out) {
            let size = origComputeSize
                ? origComputeSize.apply(this, arguments)
                : LiteGraph.LGraphNode.prototype.computeSize.apply(this, arguments);
            
            // 告诉底层引擎：无论里面的文字多长、无论当前节点有多宽，
            // 它的物理底线永远是 minW (200)！
            // 这样系统就会允许用户用鼠标自由地把它缩小，直到 200 为止。
            size[0] = minW;
            return size;
        };

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            if (onNodeCreated) onNodeCreated.apply(this, arguments);
            // 节点新建落地瞬间，赋予默认的 360 大气尺寸
            if (this.size) this.size[0] = defW;
        };

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function (info) {
            if (onConfigure) onConfigure.apply(this, arguments);
            // 读取旧工作流时：可以继承保存的宽度，但若窄于 200，则强制拉到 200 底线
            if (this.size && this.size[0] < minW) {
                this.size[0] = minW;
            }
        };

        const onResize = nodeType.prototype.onResize;
        nodeType.prototype.onResize = function (size) {
            // 用户鼠标拖拽的最后一道防线：低于 200 坚决推不动
            if (size[0] < minW) size[0] = minW;
            if (onResize) onResize.apply(this, arguments);
        };
    }
});