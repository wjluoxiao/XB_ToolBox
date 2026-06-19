import comfy.model_management as mm
import gc
import torch
import sys
from comfy.patcher_extension import CallbacksMP
from comfy.model_patcher import ModelPatcher

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(iterable, **kwargs):
        return iterable

class AnyType(str):
    def __ne__(self, __value: object) -> bool:
        return False
anyType = AnyType("*")

def is_dynamic_vram_active():
    """仅当用户显式传参 --enable-dynamic-vram 时视为动态显存激活，分块节点休眠。"""
    if "--enable-dynamic-vram" in sys.argv:
        print("\n\033[93m[XB Block Swap]\033[0m: ⚠️ 检测到 --enable-dynamic-vram，动态显存已启用。分块节点自动休眠。")
        return True
    return False

def is_lowvram_safe() -> bool:
    """BlockSwap 依赖 ComfyUI 低显存模式的 forward hook 机制。
    未启用 lowvram/novram 时，裸 to(cpu) 会切断 GPU 前向传播链导致设备不匹配崩溃。"""
    for flag in ("--lowvram", "--novram"):
        if flag in sys.argv:
            return True
    return False

def is_unsupported_model(diffusion_model):
    model_type = type(diffusion_model).__name__
    # 黑名单列表：遇到这些底层架构，直接静默放行，拒绝分块
    blacklist = ["Lumina", "Lumina2", "ZImage", "HunyuanDiT", "ErnieImageModel"] 
    for b in blacklist:
        if b in model_type:
            return model_type
    return None

# ============================================================
# XB_UNetBlockSwap — UNet 分块交换 (显存优化)
# ============================================================
class XB_UNetBlockSwap:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "unet_model": (anyType, {"tooltip": "Accepts pure UNet/DiT model input only"}),
                "blocks_to_swap": ("INT", {
                    "default": 10,  
                    "min": 0,       
                    "max": 200,     
                    "step": 1,      
                    "tooltip": "Number of core blocks to offload to system RAM. Higher values save VRAM but slow down generation."
                }),
            },
        }
    
    RETURN_TYPES = (anyType,)
    RETURN_NAMES = ("unet_model",)
    CATEGORY = "XB_ToolBox/VRAM_Hacks"
    FUNCTION = "set_callback"

    def set_callback(self, unet_model: ModelPatcher, blocks_to_swap):
        if not isinstance(unet_model, ModelPatcher):
            return (unet_model,)

        if is_dynamic_vram_active():
            return (unet_model,)

        if not is_lowvram_safe():
            print("\033[93m[XB Block Swap]\033[0m: ⚠️ 未检测到 --lowvram/--novram 参数。")
            print("  BlockSwap 依赖 ComfyUI 低显存模式的 forward hook 机制，裸 to(cpu) 会导致设备不匹配崩溃。")
            print("  请添加 --lowvram 启动参数后重试，节点已自动跳过。")
            return (unet_model,)

        def swap_blocks(model_patcher: ModelPatcher, device_to, lowvram_model_memory, force_patch_weights, full_load):
            base_model = model_patcher.model
            main_device = torch.device('cuda')
            
            diffusion_model = getattr(base_model, 'diffusion_model', None)
            if not diffusion_model:
                return

            unsupported_name = is_unsupported_model(diffusion_model)
            if unsupported_name:
                print(f"\033[93m[XB-BOX 拦截盾]\033[0m: 模型 ({unsupported_name}) 属于高耦合架构，不支持物理分块。已自动跳过！")
                return

            all_blocks = []
            block_paths = [
                'transformer_blocks', 'blocks', 'down_blocks', 'up_blocks', 'mid_block',
                'layers', 'attention_blocks', 'input_blocks', 'middle_block', 'output_blocks',
                'double_blocks', 'single_blocks', 'joint_blocks'
            ]
            
            for path in block_paths:
                if hasattr(diffusion_model, path):
                    attr = getattr(diffusion_model, path)
                    if isinstance(attr, (list, torch.nn.ModuleList)):
                        for item in attr:
                            all_blocks.append(item)
                    elif isinstance(attr, torch.nn.Module) and path in ['mid_block', 'middle_block']:
                        all_blocks.append(attr)
            
            if not all_blocks:
                return

            print(f"\033[96m[XB UNet Block Swap]\033[0m: 静态物理分块交换已激活！已锁定 {len(all_blocks)} 个引擎模块。")

            for b, block in tqdm(enumerate(all_blocks), total=len(all_blocks), desc="Slicing UNet pipeline"):
                if b > blocks_to_swap:
                    block.to(main_device)
                else:
                    block.to(model_patcher.offload_device)
                        
            mm.soft_empty_cache()
            gc.collect()
        
        unet_model = unet_model.clone()
        unet_model.add_callback(CallbacksMP.ON_LOAD, swap_blocks)
        
        return (unet_model, )

# ============================================================
# XB_CheckpointBlockSwap — Checkpoint 分块交换 (显存优化)
# ============================================================
class XB_CheckpointBlockSwap:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "checkpoint_model": (anyType, {"tooltip": "Accepts any model input (including CLIP/VAE)."}),
                "blocks_to_swap": ("INT", {"default": 15, "min": 0, "max": 1000, "step": 1}),
                "offload_img_emb": ("BOOLEAN", {"default": True}),
                "offload_txt_emb": ("BOOLEAN", {"default": True}),
                "use_non_blocking": ("BOOLEAN", {"default": False}),
            },
        }

    RETURN_TYPES = (anyType,)
    RETURN_NAMES = ("checkpoint_model",)
    CATEGORY = "XB_ToolBox/VRAM_Hacks"
    FUNCTION = "set_callback"

    def set_callback(self, checkpoint_model: ModelPatcher, blocks_to_swap, offload_txt_emb, offload_img_emb, use_non_blocking):
        if not isinstance(checkpoint_model, ModelPatcher):
            return (checkpoint_model,)

        if is_dynamic_vram_active():
            return (checkpoint_model,)

        def swap_blocks(model_patcher: ModelPatcher, device_to, lowvram_model_memory, force_patch_weights, full_load):
            base_model = model_patcher.model
            main_device = torch.device('cuda')

            diffusion_model = getattr(base_model, 'diffusion_model', None)
            if not diffusion_model:
                return

            unsupported_name = is_unsupported_model(diffusion_model)
            if unsupported_name:
                print(f"\033[93m[XB-BOX 拦截盾]\033[0m: 模型 ({unsupported_name}) 属于高耦合架构，不支持物理分块。已自动跳过！")
                return

            all_blocks = []
            block_paths = [
                'transformer_blocks', 'blocks', 'down_blocks', 'up_blocks', 'mid_block',
                'layers', 'attention_blocks', 'input_blocks', 'middle_block', 'output_blocks',
                'double_blocks', 'single_blocks', 'joint_blocks'
            ]

            for path in block_paths:
                if hasattr(diffusion_model, path):
                    attr = getattr(diffusion_model, path)
                    if isinstance(attr, (list, torch.nn.ModuleList)):
                        for item in attr:
                            all_blocks.append(item)
                    elif isinstance(attr, torch.nn.Module) and path in ['mid_block', 'middle_block']:
                        all_blocks.append(attr)

            if all_blocks:
                print(f"\033[96m[XB Checkpoint Block Swap]\033[0m: 静态物理分块交换已激活！已锁定 {len(all_blocks)} 个引擎模块。")
                for b, block in tqdm(enumerate(all_blocks), total=len(all_blocks), desc="Slicing Checkpoint pipeline"):
                    if b > blocks_to_swap:
                        block.to(main_device)
                    else:
                        block.to(model_patcher.offload_device)

            if offload_txt_emb:
                for path in ['text_embedding', 'caption_encoder', 'text_encoder']:
                    if hasattr(diffusion_model, path) and getattr(diffusion_model, path) is not None:
                        getattr(diffusion_model, path).to(model_patcher.offload_device, non_blocking=use_non_blocking)
                        break

            if offload_img_emb:
                for path in ['img_emb', 'image_encoder', 'visual_encoder']:
                    if hasattr(diffusion_model, path) and getattr(diffusion_model, path) is not None:
                        getattr(diffusion_model, path).to(model_patcher.offload_device, non_blocking=use_non_blocking)
                        break

            mm.soft_empty_cache()
            gc.collect()

        checkpoint_model = checkpoint_model.clone()
        checkpoint_model.add_callback(CallbacksMP.ON_LOAD, swap_blocks)

        return (checkpoint_model, )