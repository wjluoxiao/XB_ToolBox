import traceback

# ==========================================
# 🎨 定义终端彩色输出函数，让提示在黑框里极其醒目
# ==========================================
def print_success(msg):
    print(f"\033[92m{msg}\033[0m")  # 亮绿色

def print_error(msg):
    print(f"\033[91m{msg}\033[0m")  # 亮红色

def print_warning(msg):
    print(f"\033[93m{msg}\033[0m")  # 亮黄色

# 初始化空字典，防止报错时 ComfyUI 找不到变量而二次崩溃
NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}
WEB_DIRECTORY = "./js"

try:
    # 尝试导入所有节点
    from .nodes_vis import XB_VRAM_Calculator, XB_ChunkVisualization
    from .nodes_vram import XTX_VRAM_Cleaner, XTX_Data_Radar
    from .nodes_video import XB_VideoParamsMaster
    from .nodes_blockswap import XB_UNetBlockSwap, XB_CheckpointBlockSwap 
    from .nodes_wiring import XB_DynamicBus
    from .nodes_dashboard import XB_Dashboard_Zen
    from .nodes_tile import XB_SamplerChunkMaster

    # 如果全部导入成功，则注册节点
    NODE_CLASS_MAPPINGS = { 
        "XB_VRAM_Calculator": XB_VRAM_Calculator,
        "XB_ChunkVisualization": XB_ChunkVisualization,
        "XTX_VRAM_Cleaner": XTX_VRAM_Cleaner,
        "XTX_Data_Radar": XTX_Data_Radar,
        "XB_VideoParamsMaster": XB_VideoParamsMaster,
        "XB_UNetBlockSwap": XB_UNetBlockSwap,
        "XB_CheckpointBlockSwap": XB_CheckpointBlockSwap,
        "XB_DynamicBus": XB_DynamicBus,
        "XB_Dashboard_Zen": XB_Dashboard_Zen,
        "XB_SamplerChunkMaster": XB_SamplerChunkMaster 
    }

    NODE_DISPLAY_NAME_MAPPINGS = { 
        "XB_VRAM_Calculator": "XB-BOX - 📟 可用显存计算",
        "XB_ChunkVisualization": "XB-BOX - 🧊 时空分块预览",
        "XTX_VRAM_Cleaner": "XB-BOX- 🧹 显存清理大师",
        "XTX_Data_Radar": "XB-BOX - 🪞 生成数据预览",
        "XB_VideoParamsMaster": "XB-BOX - 🎬 图像参数大全",
        "XB_UNetBlockSwap": "XB-BOX - ✂️ 模型分块交换（UNet）",
        "XB_CheckpointBlockSwap": "XB-BOX - ✂️ 模型分块交换（checkpoints）",
        "XB_DynamicBus": "XB-BOX - 🎛️ 动态总线 (极客版)",
        "XB_Dashboard_Zen": "XB-BOX - 🪄 XB 远程控制中心",
        "XB_SamplerChunkMaster": "XB-BOX - 🧊 采样分块大师" 
    }
    
    # 打印超级醒目的成功提示
    print_success("\n" + "="*50)
    print_success("🚀 [XB-BOX] 小白工具箱 核心模块加载成功！")
    print_success("="*50 + "\n")

except Exception as e:
    # 如果有任何文件有语法错误或缺少模块，进入警报模式！
    print_error("\n" + "="*50)
    print_error("🚨 [XB-BOX] 致命错误：小白工具箱 加载失败！")
    print_error(f"❌ 错误简述: {str(e)}")
    print_warning("🔍 详细追踪信息如下 (请根据此处排查 Bug)：")
    traceback.print_exc()  # 打印出具体是哪一行代码报错
    print_error("="*50 + "\n")

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS', 'WEB_DIRECTORY']