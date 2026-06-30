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

def is_unsupported_model(diffusion_model):
    """检测已知不支持物理分块的模型架构（仅黑名单，不检测量化格式）。
    
    Qwen / FLUX 等模型的 GGUF 版本虽然参数类型特殊，但 module.to() 仍可正常工作，
    不应被拦截。只有当模型的 C++ 量化引擎（如 comfy_kitchen）确实会因 module.to()
    而崩溃时才需要拦截——但这类崩溃无法通过参数类型静态判断，由用户自行取舍。
    """
    model_type = type(diffusion_model).__name__
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

        # ── blocks_to_swap=0 等同于关闭，直接穿透 ──
        if blocks_to_swap == 0:
            print("\033[96m[XB UNet Block Swap]\033[0m: 分块数量为 0，节点穿透（无操作）")
            return (unet_model,)

        def swap_blocks(model_patcher: ModelPatcher, device_to, lowvram_model_memory, force_patch_weights, full_load):
            base_model = model_patcher.model
            # 🛡️ 动态获取 ComfyUI 分配的 GPU 设备，绝不写死 'cuda:0'
            main_device = model_patcher.load_device
            
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

            total_blocks = len(all_blocks)
            # 🛡️ 防呆：用户输入不可超过模型总块数
            if blocks_to_swap > total_blocks:
                effective = total_blocks
                tag = "匹配最大可分块参数"
            else:
                effective = blocks_to_swap
                tag = "匹配用户设置的参数"
            print(f"\033[96m[XB UNet Block Swap]\033[0m: 静态物理分块交换已激活！已找到 {total_blocks} 个引擎模块，分割 {effective} 个分块（{tag}）。")

            for b, block in tqdm(enumerate(all_blocks), total=total_blocks, desc="Slicing UNet pipeline"):
                if b > effective:
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

        # ── blocks_to_swap=0 等同于关闭，直接穿透 ──
        if blocks_to_swap == 0:
            print("\033[96m[XB Checkpoint Block Swap]\033[0m: 分块数量为 0，节点穿透（无操作）")
            return (checkpoint_model,)

        def swap_blocks(model_patcher: ModelPatcher, device_to, lowvram_model_memory, force_patch_weights, full_load):
            base_model = model_patcher.model
            # 🛡️ 动态获取 ComfyUI 分配的 GPU 设备
            main_device = model_patcher.load_device

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
                total_blocks = len(all_blocks)
                # 🛡️ 防呆：用户输入不可超过模型总块数
                if blocks_to_swap > total_blocks:
                    effective = total_blocks
                    tag = "匹配最大可分块参数"
                else:
                    effective = blocks_to_swap
                    tag = "匹配用户设置的参数"
                print(f"\033[96m[XB Checkpoint Block Swap]\033[0m: 静态物理分块交换已激活！已找到 {total_blocks} 个引擎模块，分割 {effective} 个分块（{tag}）。")

                for b, block in tqdm(enumerate(all_blocks), total=total_blocks, desc="Slicing Checkpoint pipeline"):
                    if b > effective:
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