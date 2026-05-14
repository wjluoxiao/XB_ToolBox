import comfy.model_management as mm
import gc
import torch
import sys
from comfy.patcher_extension import CallbacksMP
from comfy.model_patcher import ModelPatcher
from tqdm import tqdm

class AnyType(str):
    def __ne__(self, __value: object) -> bool:
        return False
anyType = AnyType("*")

def is_dynamic_vram_flag_used():
    """嗅探用户是否在启动参数中显式使用了 --enable-dynamic-vram"""
    return "--enable-dynamic-vram" in sys.argv


# ==============================================================================
# 节点 1：UNet/DiT 纯净版切割 (严格还原第一版的纯物理转移)
# ==============================================================================
class XB_UNetBlockSwap:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "unet_model": (anyType, {"tooltip": "仅接受纯净的 UNet/DiT 模型输入"}),
                "blocks_to_swap": ("INT", {
                    "default": 10,  
                    "min": 0,       
                    "max": 200,     
                    "step": 1,      
                    "tooltip": "分配：将前 N 个核心块外包给系统内存。数值越大越省显存，但速度越慢。"
                }),
            },
        }
    
    RETURN_TYPES = (anyType,)
    RETURN_NAMES = ("unet_model",)
    CATEGORY = "小白工具箱/显存特攻"
    FUNCTION = "set_callback"

    def set_callback(self, unet_model: ModelPatcher, blocks_to_swap):
        if not isinstance(unet_model, ModelPatcher):
            return (unet_model,)

        # 🚨 嗅探与休眠机制 (亮橙色)
        if is_dynamic_vram_flag_used():
            print("\n\033[93m[XB UNet块交换]\033[0m: ⚠️ 检测到参数 [--enable-dynamic-vram]，分块节点自动休眠退让。")
            return (unet_model,)

        def swap_blocks(model_patcher: ModelPatcher, device_to, lowvram_model_memory, force_patch_weights, full_load):
            base_model = model_patcher.model
            main_device = torch.device('cuda') # 严格还原第一版的设备指定
            
            diffusion_model = getattr(base_model, 'diffusion_model', None)
            if not diffusion_model:
                return

            all_blocks = []
            block_paths = ['transformer_blocks', 'blocks', 'down_blocks', 'up_blocks', 'mid_block']
            
            for path in block_paths:
                if hasattr(diffusion_model, path):
                    attr = getattr(diffusion_model, path)
                    if isinstance(attr, (list, torch.nn.ModuleList)):
                        all_blocks.extend(attr)
                        break 
            
            if not all_blocks:
                return

            # 正常分块亮蓝色提示
            print(f"\033[96m[XB UNet块交换]\033[0m: 静态物理分块已激活！锁定 {len(all_blocks)} 个引擎模块")

            # 🚀 大道至简：完全使用第一版的最原生的转移逻辑！
            for b, block in tqdm(enumerate(all_blocks), total=len(all_blocks), desc="正在切割 UNet 流水线"):
                if b > blocks_to_swap:
                    block.to(main_device)
                else:
                    block.to(model_patcher.offload_device)
                        
            mm.soft_empty_cache()
            gc.collect()
        
        unet_model = unet_model.clone()
        unet_model.add_callback(CallbacksMP.ON_LOAD, swap_blocks)
        
        return (unet_model, )

# ==============================================================================
# 节点 2：Checkpoint 混合包裹切割 (严格还原第一版的纯物理转移)
# ==============================================================================
class XB_CheckpointBlockSwap:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "checkpoint_model": (anyType, {"tooltip": "接受任何模型输入 (含 CLIP/VAE 等完整架构)。"}),
                "blocks_to_swap": ("INT", {"default": 15, "min": 0, "max": 1000, "step": 1}),
                "offload_img_emb": ("BOOLEAN", {"default": True}),
                "offload_txt_emb": ("BOOLEAN", {"default": True}),
                "use_non_blocking": ("BOOLEAN", {"default": False}),
            },
        }

    RETURN_TYPES = (anyType,)
    RETURN_NAMES = ("checkpoint_model",)
    CATEGORY = "小白工具箱/显存特攻"
    FUNCTION = "set_callback"

    def set_callback(self, checkpoint_model: ModelPatcher, blocks_to_swap, offload_txt_emb, offload_img_emb, use_non_blocking):
        if not isinstance(checkpoint_model, ModelPatcher):
            return (checkpoint_model,)

        # 🚨 嗅探与休眠机制 (亮橙色)
        if is_dynamic_vram_flag_used():
            print("\n\033[93m[XB Checkpoint块交换]\033[0m: ⚠️ 检测到参数 [--enable-dynamic-vram]，分块节点自动休眠退让。")
            return (checkpoint_model,)

        def swap_blocks(model_patcher: ModelPatcher, device_to, lowvram_model_memory, force_patch_weights, full_load):
            base_model = model_patcher.model
            main_device = torch.device('cuda')

            diffusion_model = getattr(base_model, 'diffusion_model', None)
            if not diffusion_model:
                return

            all_blocks = []
            block_paths = ['transformer_blocks', 'blocks', 'down_blocks', 'up_blocks', 'mid_block', 'layers', 'attention_blocks', 'input_blocks', 'middle_block', 'output_blocks']

            for path in block_paths:
                if hasattr(diffusion_model, path):
                    attr = getattr(diffusion_model, path)
                    if isinstance(attr, (list, torch.nn.ModuleList)):
                        all_blocks.extend(attr)
                        break

            if all_blocks:
                print(f"\033[96m[XB Checkpoint块交换]\033[0m: 静态物理分块已激活！锁定 {len(all_blocks)} 个引擎模块")
                # 🚀 大道至简：完全使用第一版的最原生的转移逻辑！
                for b, block in tqdm(enumerate(all_blocks), total=len(all_blocks), desc="正在切割 Checkpoint 流水线"):
                    if b > blocks_to_swap:
                        block.to(main_device)
                    else:
                        block.to(model_patcher.offload_device) 

            # 原生方法处理 Embedding
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