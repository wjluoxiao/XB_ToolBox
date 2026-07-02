import os
import traceback

from server import PromptServer
from aiohttp import web

HAS_TKINTER = False
try:
    import tkinter as tk
    from tkinter import filedialog
    HAS_TKINTER = True
except ImportError:
    pass  # 静默放行，不要让整个节点加载失败

@PromptServer.instance.routes.post("/xb_toolbox/choose_folder")
async def choose_folder(request):
    if not HAS_TKINTER:
        return web.json_response({"path": "", "error": "当前整合包环境缺少弹窗依赖，请手动输入或粘贴文件夹路径。"})
    
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        folder_path = filedialog.askdirectory()
        root.destroy()
        return web.json_response({"path": folder_path})
    except Exception as e:
        return web.json_response({"path": "", "error": f"弹窗调用失败: {str(e)}"})


from .nodes_audio_slicer import handle_audio_waveform

@PromptServer.instance.routes.post("/xb_toolbox/audio_waveform")
async def get_audio_waveform(request):
    return await handle_audio_waveform(request)


def print_success(msg):
    print(f"\033[92m{msg}\033[0m")  

def print_error(msg):
    print(f"\033[91m{msg}\033[0m")  

def print_warning(msg):
    print(f"\033[93m{msg}\033[0m")  

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}
WEB_DIRECTORY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "js")

try:
    from .nodes_vis import XB_VRAM_Calculator, XB_ChunkVisualization
    from .nodes_vram import XTX_Data_Radar
    from .nodes_video import XB_VideoParamsMaster, XB_ImageParamsMaster, XB_MasterParameter, XB_VideoLoader, XB_VideoCombine
    from .nodes_blockswap import XB_UNetBlockSwap, XB_CheckpointBlockSwap 
    from .nodes_wiring import XB_DynamicBus, XB_UNetNameBroadcaster, XB_CLIPNameBroadcaster
    from .nodes_dashboard import XB_Dashboard_Zen
    from .nodes_tile import XB_SamplerChunkMaster
    from .nodes_wan_vae import (XB_WanImageToVideo, XB_WanFirstLastFrameToVideo, XB_WanSoundImageToVideo, XB_WanFunControlToVideo, XB_WanVaceToVideo, XB_Wan22FunControlToVideo, XB_WanInfiniteTalkToVideo, XB_WanInfiniteTalkToVideo_Single, XB_WanInfiniteTalkToVideo_Dual, XB_WanVAEDecodeTiled, XB_WanFunInpaintToVideo, XB_WanCameraImageToVideo, XB_WanPhantomSubjectToVideo, XB_WanHuMoImageToVideo, XB_Wan22ImageToVideoLatent, XB_WanSoundImageToVideoExtend, XB_WanSCAILToVideo, XB_WanSCAILToVideoPro, XB_BerniniConditioning)
    from .nodes_batch import XB_BatchFolderLoader
    from .nodes_pipeline import XB_Wan_ParamBus, XB_Wan_RelayNode, XB_Wan_InfiniteRelayNode, XB_Video_Merger, XB_StoryboardSlicer,XB_WanAnimate_ParamBus,XB_WanAnimate_RelayNode, XB_WanInfiniteTalk_ParamBus, XB_WanInfiniteTalk_RelayNode, XB_Wan_InfiniteRelayNode_New, XB_WanAnimate_RelayNode_New, XB_WanInfiniteTalk_RelayNode_New, XB_WanSCAIL_ParamBus_New, XB_WanSCAIL_RelayNode_New
    from .nodes_sageatt import XB_SageAttentionAccelerator
    from .nodes_wan_t5 import XB_WanT5Loader
    from .nodes_wan import (XB_WanCompileSettings, XB_WanModelLoader, XB_WanBlockSwap,
                             XB_WanSampler, XB_WanTextEncode, XB_WanVAELoader, XB_WanDecode,
                             XB_WanAnimateToVideo)

    from .nodes_label import XB_CanvasLabel
    from .nodes_audio_slicer import XB_AudioSlicer, XB_AudioSlicerV1, XB_AudioSlicerV2, XB_AudioSlicerV3
    from .nodes_segmentation import XB_HumanSegModelLoader, XB_HumanSegmentation

    # 注册视频转码端点（预览窗口实时缩放依赖）
    from . import xb_video_server
    from .nodes_rocm import XB_ROCmMemCleaner
    from .nodes_vanilla_wrappers import (XB_KSampler, XB_KSamplerAdvanced,
                                          XB_SamplerCustom, XB_SamplerCustomAdvanced,
                                          XB_VAEDecode, XB_VAEDecodeTiled,
                                          XB_VAEDecodeTiledImage,
                                          XB_VAEEncode, XB_VAEEncodeTiled,
                                          XB_VAEEncodeForInpaint,
                                          _AliasKSampler, _AliasKSamplerAdvanced,
                                          _AliasSamplerCustom, _AliasSamplerCustomAdvanced,
                                          _AliasVAEDecode, _AliasVAEDecodeTemporal,
                                          _AliasLTXVAEDecode, _AliasVAEEncode)
    from .nodes_string_merge import XB_StringMerge
    from .nodes_msr import XB_MSR
    from .nodes_comic import XB_ComicPromptParser, XB_ComicTextRenderer, XB_AutoBubbleTextRenderer

    NODE_CLASS_MAPPINGS = { 
        "XB_VRAM_Calculator": XB_VRAM_Calculator,
        "XB_ChunkVisualization": XB_ChunkVisualization,
        "XTX_Data_Radar": XTX_Data_Radar,
        "XB_VideoParamsMaster": XB_VideoParamsMaster,
        "XB_ImageParamsMaster": XB_ImageParamsMaster, 
        "XB_MasterParameter": XB_MasterParameter,
        "XB_VideoLoader": XB_VideoLoader,
        "XB_VideoCombine": XB_VideoCombine,
        "XB_UNetBlockSwap": XB_UNetBlockSwap,
        "XB_CheckpointBlockSwap": XB_CheckpointBlockSwap,
        "XB_DynamicBus": XB_DynamicBus,
        "XB_UNetNameBroadcaster": XB_UNetNameBroadcaster,
        "XB_CLIPNameBroadcaster": XB_CLIPNameBroadcaster,
        "XB_Dashboard_Zen": XB_Dashboard_Zen,
        "XB_SamplerChunkMaster": XB_SamplerChunkMaster,
        "XB_WanImageToVideo": XB_WanImageToVideo,
        "XB_WanFirstLastFrameToVideo": XB_WanFirstLastFrameToVideo,
        "XB_WanFunControlToVideo": XB_WanFunControlToVideo,
        "XB_WanVaceToVideo": XB_WanVaceToVideo,
        "XB_Wan22FunControlToVideo": XB_Wan22FunControlToVideo,
        "XB_WanSoundImageToVideo": XB_WanSoundImageToVideo,
        "XB_WanInfiniteTalkToVideo": XB_WanInfiniteTalkToVideo,
        "XB_WanInfiniteTalkToVideo_Single": XB_WanInfiniteTalkToVideo_Single,
        "XB_WanInfiniteTalkToVideo_Dual": XB_WanInfiniteTalkToVideo_Dual,
        "XB_WanVAEDecodeTiled": XB_WanVAEDecodeTiled,
        "XB_WanFunInpaintToVideo": XB_WanFunInpaintToVideo,
        "XB_WanCameraImageToVideo": XB_WanCameraImageToVideo,
        "XB_WanPhantomSubjectToVideo": XB_WanPhantomSubjectToVideo,
        "XB_WanHuMoImageToVideo": XB_WanHuMoImageToVideo,
        "XB_Wan22ImageToVideoLatent": XB_Wan22ImageToVideoLatent,
        "XB_WanSoundImageToVideoExtend": XB_WanSoundImageToVideoExtend,
        "XB_WanSCAILToVideo": XB_WanSCAILToVideo,
        "XB_WanSCAILToVideoPro": XB_WanSCAILToVideoPro,
        "XB_BerniniConditioning": XB_BerniniConditioning,
        "XB_BatchFolderLoader": XB_BatchFolderLoader,
        "XB_Wan_ParamBus": XB_Wan_ParamBus,
        "XB_Wan_RelayNode": XB_Wan_RelayNode,
        "XB_Wan_InfiniteRelayNode": XB_Wan_InfiniteRelayNode,
        "XB_Video_Merger": XB_Video_Merger,
        "XB_StoryboardSlicer": XB_StoryboardSlicer,
        "XB_SageAttentionAccelerator": XB_SageAttentionAccelerator,
        "XB_ROCmMemCleaner": XB_ROCmMemCleaner,
        # ── 借尸还魂：旧 ROCm 节点 ID → 别名类（兼容旧参数名） ──
        "XB_ROCmKSampler": _AliasKSampler,
        "XB_ROCmKSamplerAdvanced": _AliasKSamplerAdvanced,
        "XB_ROCmSamplerCustom": _AliasSamplerCustom,
        "XB_ROCmSamplerCustomAdvanced": _AliasSamplerCustomAdvanced,
        "XB_ROCmVAEDecode": _AliasVAEDecode,
        "XB_ROCmVAEEncode": _AliasVAEEncode,
        "XB_ROCmVAEDecodeTemporal": _AliasVAEDecodeTemporal,
        "XB_ROCmLTXVAEDecode": _AliasLTXVAEDecode,
        # ── 新原版优化节点 ──
        "XB_KSampler": XB_KSampler,
        "XB_KSamplerAdvanced": XB_KSamplerAdvanced,
        "XB_SamplerCustom": XB_SamplerCustom,
        "XB_SamplerCustomAdvanced": XB_SamplerCustomAdvanced,
        "XB_VAEDecode": XB_VAEDecode,
        "XB_VAEDecodeTiled": XB_VAEDecodeTiled,
        "XB_VAEDecodeTiledImage": XB_VAEDecodeTiledImage,
        "XB_VAEEncode": XB_VAEEncode,
        "XB_VAEEncodeTiled": XB_VAEEncodeTiled,
        "XB_VAEEncodeForInpaint": XB_VAEEncodeForInpaint,
        "XB_WanT5Loader": XB_WanT5Loader,
        "XB_WanCompileSettings": XB_WanCompileSettings,
        "XB_WanModelLoader": XB_WanModelLoader,
        "XB_WanBlockSwap": XB_WanBlockSwap,
        "XB_WanSampler": XB_WanSampler,
        "XB_WanTextEncode": XB_WanTextEncode,
        "XB_WanVAELoader": XB_WanVAELoader,
        "XB_WanDecode": XB_WanDecode,
        "XB_WanAnimateToVideo": XB_WanAnimateToVideo,
        "XB_WanAnimate_ParamBus": XB_WanAnimate_ParamBus,
        "XB_WanAnimate_RelayNode": XB_WanAnimate_RelayNode,
        "XB_WanInfiniteTalk_ParamBus": XB_WanInfiniteTalk_ParamBus,
        "XB_WanInfiniteTalk_RelayNode": XB_WanInfiniteTalk_RelayNode,
        "XB_Wan_InfiniteRelayNode_New": XB_Wan_InfiniteRelayNode_New,
        "XB_WanAnimate_RelayNode_New": XB_WanAnimate_RelayNode_New,
        "XB_WanInfiniteTalk_RelayNode_New": XB_WanInfiniteTalk_RelayNode_New,
        "XB_WanSCAIL_ParamBus_New": XB_WanSCAIL_ParamBus_New,
        "XB_WanSCAIL_RelayNode_New": XB_WanSCAIL_RelayNode_New,
        "XB_HumanSegmentation": XB_HumanSegmentation,
        "XB_HumanSegModelLoader": XB_HumanSegModelLoader,
        "XB_CanvasLabel": XB_CanvasLabel,
        "XB_AudioSlicer": XB_AudioSlicer,
        "XB_AudioSlicerV1": XB_AudioSlicerV1,
        "XB_AudioSlicerV2": XB_AudioSlicerV2,
        "XB_AudioSlicerV3": XB_AudioSlicerV3,
        "XB_StringMerge": XB_StringMerge,
        "XB_MSR": XB_MSR,
        "XB_ComicPromptParser": XB_ComicPromptParser,
        "XB_ComicTextRenderer": XB_ComicTextRenderer,
        "XB_AutoBubbleTextRenderer": XB_AutoBubbleTextRenderer
    }

    NODE_DISPLAY_NAME_MAPPINGS = { 
        "XB_VRAM_Calculator": "XB-BOX - VRAM Calculator",
        "XB_ChunkVisualization": "XB-BOX - Chunk Visualization",
        "XTX_Data_Radar": "XB-BOX - Data Radar",
        "XB_VideoParamsMaster": "XB-BOX - Video Params Master", 
        "XB_ImageParamsMaster": "XB-BOX - Image Params Master",
        "XB_MasterParameter": "XB-BOX - Master Parameter",
        "XB_VideoLoader": "XB-BOX - 🎬 视频加载器（修复预览BUG）",
        "XB_VideoCombine": "XB-BOX - 🎬 视频拼接输出",
        "XB_UNetBlockSwap": "XB-BOX - UNet Block Swap",
        "XB_CheckpointBlockSwap": "XB-BOX - Checkpoint Block Swap",
        "XB_DynamicBus": "XB-BOX - Dynamic Bus",
        "XB_UNetNameBroadcaster": "XB-BOX - UNet Name Broadcaster",
        "XB_CLIPNameBroadcaster": "XB-BOX - CLIP Name Broadcaster",
        "XB_Dashboard_Zen": "XB-BOX - Dashboard Zen",
        "XB_SamplerChunkMaster": "XB-BOX - Sampler Chunk Master",
        "XB_WanImageToVideo": "XB-BOX - Wan Image2Video",
        "XB_WanFirstLastFrameToVideo": "XB-BOX - Wan First/Last Frame2Video",
        "XB_BatchFolderLoader": "XB-BOX - Batch Folder Loader",
        "XB_Wan_ParamBus": "XB-BOX - Wan Param Bus",
        "XB_Wan_RelayNode": "XB-BOX - Wan Relay Node",
        "XB_Wan_InfiniteRelayNode": "XB-BOX - Wan Infinite Relay Node",
        "XB_Video_Merger": "XB-BOX - Video Merger",
        "XB_StoryboardSlicer": "XB-BOX - Storyboard Slicer",
        "XB_SageAttentionAccelerator": "XB-BOX - SageAttention Accelerator",
        "XB_ROCmMemCleaner": "XB-BOX - 🧹 显存清理",
        # ── 借尸还魂：旧节点名 + 新的优化版显示名 ──
        "XB_ROCmKSampler": "XB-BOX - 采样器（原版优化）",
        "XB_ROCmKSamplerAdvanced": "XB-BOX - 高级采样器（原版优化）",
        "XB_ROCmSamplerCustom": "XB-BOX - 自定义采样器（原版优化）",
        "XB_ROCmSamplerCustomAdvanced": "XB-BOX - 自定义高级采样器（原版优化）",
        "XB_ROCmVAEDecode": "XB-BOX - VAE解码（原版优化）",
        "XB_ROCmVAEEncode": "XB-BOX - VAE编码（原版优化）",
        "XB_ROCmVAEDecodeTemporal": "XB-BOX - VAE分块解码（原版优化）",
        "XB_ROCmLTXVAEDecode": "XB-BOX - VAE分块解码（原版优化）",
        # ── 新优化版节点 ──
        "XB_KSampler": "XB-BOX - 采样器（原版优化）",
        "XB_KSamplerAdvanced": "XB-BOX - 高级采样器（原版优化）",
        "XB_SamplerCustom": "XB-BOX - 自定义采样器（原版优化）",
        "XB_SamplerCustomAdvanced": "XB-BOX - 自定义高级采样器（原版优化）",
        "XB_VAEDecode": "XB-BOX - VAE解码（原版优化）",
        "XB_VAEDecodeTiled": "XB-BOX - VAE分块解码（原版优化）",
        "XB_VAEDecodeTiledImage": "XB-BOX - VAE解码（原版优化）",
        "XB_VAEEncode": "XB-BOX - VAE编码（原版优化）",
        "XB_VAEEncodeTiled": "XB-BOX - VAE分块编码（原版优化）",
        "XB_VAEEncodeForInpaint": "XB-BOX - VAE修补编码（原版优化）",
        "XB_WanT5Loader": "XB-BOX - 📝 Wan T5 加载器(FP8)",
        "XB_WanCompileSettings": "XB-BOX - ⚡ Wan 编译设置",
        "XB_WanModelLoader": "XB-BOX - 🧠 Wan 模型加载",
        "XB_WanBlockSwap": "XB-BOX - 🔄 Wan 分块交换",
        "XB_WanSampler": "XB-BOX - 🎯 Wan 采样器",
        "XB_WanTextEncode": "XB-BOX - ✍️ Wan 文本编码",
        "XB_WanVAELoader": "XB-BOX - 🎨 Wan VAE 加载",
        "XB_WanDecode": "XB-BOX - 🖼️ Wan VAE 解码",
        "XB_WanAnimateToVideo": "XB-BOX - 🎬 Wan 动画转视频",
        "XB_WanAnimate_ParamBus": "XB-BOX - 🎬 Animate 动作迁移总线",
        "XB_WanAnimate_RelayNode": "XB-BOX - 🏃‍♀️ Animate 无限接力点",
        "XB_WanInfiniteTalk_ParamBus": "XB-BOX - 🎵 InfiniteTalk 无限对口型总线",
        "XB_WanInfiniteTalk_RelayNode": "XB-BOX - 🏃 InfiniteTalk 无限对口型接力点",
        "XB_Wan_InfiniteRelayNode_New": "XB-BOX - 🆕 Wan 无限接力点 (New)",
        "XB_WanAnimate_RelayNode_New": "XB-BOX - 🆕 Animate 无限接力点 (New)",
        "XB_WanInfiniteTalk_RelayNode_New": "XB-BOX - 🆕 InfiniteTalk 无限接力点 (New)",
        "XB_WanSCAIL_ParamBus_New": "XB-BOX - 🆕 SCAIL 总线 (New)",
        "XB_WanSCAIL_RelayNode_New": "XB-BOX - 🆕 SCAIL 无限接力点 (New)",
        "XB_HumanSegmentation": "XB-BOX - ✂️ 人物分割 (DirectML/ROCm)",
        "XB_HumanSegModelLoader": "XB-BOX - 📥 人物分割模型加载",
        "XB_CanvasLabel": "XB-BOX - 🏷️ Canvas Label (文字标签)",
        "XB_AudioSlicer": "XB-BOX - 🎵 音频切片（基础）",
        "XB_AudioSlicerV1": "XB-BOX - 🎵 音频切片V1（单人）",
        "XB_AudioSlicerV2": "XB-BOX - 🎵 音频切片V2（双人）",
        "XB_AudioSlicerV3": "XB-BOX - 🎵 音频切片V3（高级）",
        "XB_WanInfiniteTalkToVideo": "XB-BOX - 🎵 语音转视频分块",
        "XB_WanInfiniteTalkToVideo_Single": "XB-BOX - 🎵 语音转视频分块（单人）",
        "XB_WanInfiniteTalkToVideo_Dual": "XB-BOX - 🎵 语音转视频分块（双人）",
        "XB_StringMerge": "XB-BOX - 📝 字符串合并",
        "XB_MSR": "XB-BOX - 🎞️ MSR 多图合成帧序列",
        "XB_ComicPromptParser": "XB-BOX - 📝 漫画提示词智能解析",
        "XB_ComicTextRenderer": "XB-BOX - 💬 漫画文字渲染 (精确坐标)",
        "XB_AutoBubbleTextRenderer": "XB-BOX - 🤖 漫画文字渲染 (全自动带涂改液)",
        "XB_BerniniConditioning": "XB-BOX - 🎨 Bernini 条件注入（VAE分块）",
    }

    print_success("\n" + "="*50)
    print_success("🚀 [XB-BOX] XB_ToolBox Core Modules Loaded Successfully!")
    print_success("="*50 + "\n")

except Exception as e:
    print_error("\n" + "="*50)
    print_error("🚨 [XB-BOX] FATAL ERROR: XB_ToolBox Loading Failed!")
    print_error(f"❌ Error Detail: {str(e)}")
    traceback.print_exc()  
    print_error("="*50 + "\n")

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS', 'WEB_DIRECTORY']