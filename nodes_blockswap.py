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
    return "--enable-dynamic-vram" in sys.argv

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

        if is_dynamic_vram_flag_used():
            print("\n\033[92m[XB UNet Block Swap]\033[0m: ⚠️ Detected parameter [--enable-dynamic-vram], block swap node auto-sleeping.")
            return (unet_model,)

        def swap_blocks(model_patcher: ModelPatcher, device_to, lowvram_model_memory, force_patch_weights, full_load):
            base_model = model_patcher.model
            main_device = torch.device('cuda')
            
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

            print(f"\033[96m[XB UNet Block Swap]\033[0m: Static physical block swap activated! Locked {len(all_blocks)} engine modules.")

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

        if is_dynamic_vram_flag_used():
            print("\n\033[92m[XB Checkpoint Block Swap]\033[0m: ⚠️ Detected parameter [--enable-dynamic-vram], block swap node auto-sleeping.")
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
                print(f"\033[96m[XB Checkpoint Block Swap]\033[0m: Static physical block swap activated! Locked {len(all_blocks)} engine modules.")
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