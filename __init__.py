import traceback
import tkinter as tk
from tkinter import filedialog
from server import PromptServer
from aiohttp import web

@PromptServer.instance.routes.post("/xb_toolbox/choose_folder")
async def choose_folder(request):

    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    folder_path = filedialog.askdirectory()
    root.destroy()
    
    return web.json_response({"path": folder_path})

def print_success(msg):
    print(f"\033[92m{msg}\033[0m")  

def print_error(msg):
    print(f"\033[91m{msg}\033[0m")  

def print_warning(msg):
    print(f"\033[93m{msg}\033[0m")  

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}
WEB_DIRECTORY = "./js"

try:

    from .nodes_vis import XB_VRAM_Calculator, XB_ChunkVisualization
    from .nodes_vram import XTX_VRAM_Cleaner, XTX_Data_Radar
    from .nodes_video import XB_VideoParamsMaster, XB_ImageParamsMaster, XB_MasterParameter 
    from .nodes_blockswap import XB_UNetBlockSwap, XB_CheckpointBlockSwap 
    from .nodes_wiring import XB_DynamicBus, XB_UNetNameBroadcaster, XB_CLIPNameBroadcaster
    from .nodes_dashboard import XB_Dashboard_Zen
    from .nodes_tile import XB_SamplerChunkMaster
    from .nodes_wan_vae import XB_WanImageToVideo, XB_WanFirstLastFrameToVideo
    from .nodes_batch import XB_BatchFolderLoader
    from .nodes_pipeline import XB_Wan_ParamBus, XB_Wan_RelayNode, XB_Video_Merger, XB_StoryboardSlicer

    NODE_CLASS_MAPPINGS = { 
        "XB_VRAM_Calculator": XB_VRAM_Calculator,
        "XB_ChunkVisualization": XB_ChunkVisualization,
        "XTX_VRAM_Cleaner": XTX_VRAM_Cleaner,
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
        "XB_BatchFolderLoader": XB_BatchFolderLoader,
        "XB_Wan_ParamBus": XB_Wan_ParamBus,
        "XB_Wan_RelayNode": XB_Wan_RelayNode,
        "XB_Video_Merger": XB_Video_Merger,
        "XB_StoryboardSlicer": XB_StoryboardSlicer
    }

    NODE_DISPLAY_NAME_MAPPINGS = { 
        "XB_VRAM_Calculator": "XB-BOX - 📟 可用显存计算",
        "XB_ChunkVisualization": "XB-BOX - 🧊 时空分块预览",
        "XTX_VRAM_Cleaner": "XB-BOX- 🧹 显存清理大师",
        "XTX_Data_Radar": "XB-BOX - 🪞 生成数据预览",
        "XB_VideoParamsMaster": "XB-BOX - 🎬 视频参数大全", 
        "XB_ImageParamsMaster": "XB-BOX - 🖼️ 图片参数大全",
        "XB_MasterParameter": "XB-BOX - 🎛️ 全能参数控制",
        "XB_UNetBlockSwap": "XB-BOX - ✂️ 模型分块交换（UNet）",
        "XB_CheckpointBlockSwap": "XB-BOX - ✂️ 模型分块交换（checkpoints）",
        "XB_DynamicBus": "XB-BOX - 🎛️ 动态总线插排",
        "XB_UNetNameBroadcaster": "XB-BOX - 🗂️ UNet 名称分发",
        "XB_CLIPNameBroadcaster": "XB-BOX - 🗂️ CLIP 名称分发",
        "XB_Dashboard_Zen": "XB-BOX - 🪄 远程控制中心",
        "XB_SamplerChunkMaster": "XB-BOX - 🧊 采样分块大师",
        "XB_WanImageToVideo": "XB-BOX - 🖼️ 单图转视频分块 (Wan)",
        "XB_WanFirstLastFrameToVideo": "XB-BOX - 🎞️ 首尾帧视频分块(Wan)",
        "XB_BatchFolderLoader": "XB-BOX - 📂 图片批量加载",
        "XB_Wan_ParamBus": "XB-BOX - 📦 视频参数总线",
        "XB_Wan_RelayNode": "XB-BOX - 🏃 首尾帧接力点",
        "XB_Video_Merger": "XB-BOX - 🧩 视频无缝拼接",
        "XB_StoryboardSlicer": "XB-BOX - 🧊 分镜图片切割"
    }
    
    # 打印超级醒目的成功提示
    print_success("\n" + "="*50)
    print_success("🚀 [XB-BOX] 小白工具箱 核心模块加载成功！")
    print_success("="*50 + "\n")

except Exception as e:
    print_error("\n" + "="*50)
    print_error("🚨 [XB-BOX] 致命错误：小白工具箱 加载失败！")
    print_error(f"❌ 错误简述: {str(e)}")
    print_warning("🔍 详细追踪信息如下 (请根据此处排查 Bug)：")
    traceback.print_exc()  
    print_error("="*50 + "\n")

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS', 'WEB_DIRECTORY']