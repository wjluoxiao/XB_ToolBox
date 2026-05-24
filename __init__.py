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
    from .nodes_video import XB_VideoParamsMaster, XB_ImageParamsMaster, XB_MasterParameter 
    from .nodes_blockswap import XB_UNetBlockSwap, XB_CheckpointBlockSwap 
    from .nodes_wiring import XB_DynamicBus, XB_UNetNameBroadcaster, XB_CLIPNameBroadcaster
    from .nodes_dashboard import XB_Dashboard_Zen
    from .nodes_tile import XB_SamplerChunkMaster
    from .nodes_wan_vae import XB_WanImageToVideo, XB_WanFirstLastFrameToVideo, XB_WanSoundImageToVideo, XB_WanFunControlToVideo, XB_Wan22FunControlToVideo
    from .nodes_batch import XB_BatchFolderLoader
    # 在 from .nodes_pipeline 这一行，加上 XB_Wan_InfiniteRelayNode
    from .nodes_pipeline import XB_Wan_ParamBus, XB_Wan_RelayNode, XB_Wan_InfiniteRelayNode, XB_Video_Merger, XB_StoryboardSlicer
    from .nodes_sageatt import XB_SageAttentionAccelerator

    # --- ROCm 节点：6个自包含节点 ---
    from .nodes_rocm import (XB_ROCmKSampler, XB_ROCmKSamplerAdvanced, XB_ROCmVAEDecode,
                              XB_ROCmVAEEncode, XB_ROCmVAEDecodeTemporal, XB_ROCmMemCleaner)

    NODE_CLASS_MAPPINGS = { 
        "XB_VRAM_Calculator": XB_VRAM_Calculator,
        "XB_ChunkVisualization": XB_ChunkVisualization,
        "XTX_Data_Radar": XTX_Data_Radar,
        "XB_VideoParamsMaster": XB_VideoParamsMaster,
        "XB_ImageParamsMaster": XB_ImageParamsMaster, 
        "XB_MasterParameter": XB_MasterParameter,
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
        "XB_Wan22FunControlToVideo": XB_Wan22FunControlToVideo,
        "XB_WanSoundImageToVideo": XB_WanSoundImageToVideo,
        "XB_BatchFolderLoader": XB_BatchFolderLoader,
        "XB_Wan_ParamBus": XB_Wan_ParamBus,
        "XB_Wan_RelayNode": XB_Wan_RelayNode,
        "XB_Wan_InfiniteRelayNode": XB_Wan_InfiniteRelayNode,
        "XB_Video_Merger": XB_Video_Merger,
        "XB_StoryboardSlicer": XB_StoryboardSlicer,
        "XB_SageAttentionAccelerator": XB_SageAttentionAccelerator,
        "XB_ROCmKSampler": XB_ROCmKSampler,
        "XB_ROCmKSamplerAdvanced": XB_ROCmKSamplerAdvanced,
        "XB_ROCmVAEDecode": XB_ROCmVAEDecode,
        "XB_ROCmVAEEncode": XB_ROCmVAEEncode,
        "XB_ROCmVAEDecodeTemporal": XB_ROCmVAEDecodeTemporal,
        "XB_ROCmMemCleaner": XB_ROCmMemCleaner,
    }

    NODE_DISPLAY_NAME_MAPPINGS = { 
        "XB_VRAM_Calculator": "XB-BOX - VRAM Calculator",
        "XB_ChunkVisualization": "XB-BOX - Chunk Visualization",
        "XTX_Data_Radar": "XB-BOX - Data Radar",
        "XB_VideoParamsMaster": "XB-BOX - Video Params Master", 
        "XB_ImageParamsMaster": "XB-BOX - Image Params Master",
        "XB_MasterParameter": "XB-BOX - Master Parameter",
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
        "XB_ROCmKSampler": "XB-BOX - 🚀 ROCm 采样器",
        "XB_ROCmKSamplerAdvanced": "XB-BOX - 🚀 ROCm 高级采样器",
        "XB_ROCmVAEDecode": "XB-BOX - 🖼️ ROCm VAE 解码",
        "XB_ROCmVAEEncode": "XB-BOX - 📦 ROCm VAE 编码",
        "XB_ROCmVAEDecodeTemporal": "XB-BOX - 🎬 ROCm VAE 时空解码",
        "XB_ROCmMemCleaner": "XB-BOX - 🧹 ROCm 显存清理",
    }

    print_success("   🚀 ROCm: KSampler | KSamplerAdvanced | VAE Decode | VAE Encode | VAE Decode Temporal | MemCleaner")
    
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