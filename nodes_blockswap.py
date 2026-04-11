import comfy.model_management as mm
import gc
import torch
from comfy.patcher_extension import CallbacksMP
from comfy.model_patcher import ModelPatcher
from tqdm import tqdm

class AnyType(str):
    def __ne__(self, __value: object) -> bool:
        return False
anyType = AnyType("*")

# ==============================================================================
# 节点 1：UNet/DiT 纯净版切割
# ==============================================================================
class XB_UNetBlockSwap:
    """
    极简、纯净的 UNet/DiT 专用块交换节点。
    严格遵守单一职责，剥离所有与 CLIP/VAE 相关的逻辑，专精于处理去噪主干的显存溢出。
    """
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
                    "tooltip": "切断流水线的位置：将前 N 个核心块外包给系统内存。数值越大越省显存，但速度越慢。"
                }),
            },
        }
    
    RETURN_TYPES = (anyType,)
    RETURN_NAMES = ("unet_model",)
    CATEGORY = "小白工具箱/显存特攻"
    FUNCTION = "set_callback"

    def set_callback(self, unet_model: ModelPatcher, blocks_to_swap):
        if not isinstance(unet_model, ModelPatcher):
            print("\033[31m[XB UNet块交换]\033[0m: 拦截失败！输入的数据流不是合法的模型对象。")
            return (unet_model,)

        def swap_blocks(model_patcher: ModelPatcher, device_to, lowvram_model_memory, force_patch_weights, full_load):
            base_model = model_patcher.model
            main_device = torch.device('cuda')
            
            diffusion_model = getattr(base_model, 'diffusion_model', None)
            if not diffusion_model:
                return

            all_blocks = []
            block_paths = [
                'transformer_blocks', 
                'blocks',             
                'down_blocks',        
                'up_blocks',          
                'mid_block'
            ]
            
            found_path = None
            for path in block_paths:
                if hasattr(diffusion_model, path):
                    attr = getattr(diffusion_model, path)
                    if isinstance(attr, (list, torch.nn.ModuleList)):
                        all_blocks.extend(attr)
                        found_path = path
                        break 
            
            if not all_blocks:
                return

            print(f"\033[36m[XB UNet块交换]\033[0m: 精确锁定 {len(all_blocks)} 个引擎模块 (路径: {found_path})")

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
# 节点 2：Checkpoint 混合包裹切割
# ==============================================================================
class XB_CheckpointBlockSwap:
    """
    用于 Checkpoint 大包裹 (包含 UNet + CLIP/VAE 等) 的通用分块交换节点。
    已彻底修复离线设备指针作用域 Bug 及 NoneType 空载报错。
    """
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "checkpoint_model": (anyType, {"tooltip": "接受任何模型输入 (含 CLIP/VAE 等完整架构)。"}),
                "blocks_to_swap": ("INT", {
                    "default": 15,
                    "min": 0,
                    "max": 1000,
                    "step": 1,
                    "tooltip": "要交换的模型核心块数量。这些块将被保留在系统内存中。"
                }),
                "offload_img_emb": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "是否将图像嵌入层(如存在)也强制卸载到内存中。"
                }),
                "offload_txt_emb": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "是否将文本嵌入层(CLIP/T5等)也强制卸载到内存中以节省显存。"
                }),
                "use_non_blocking": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "使用非阻塞内存传输。可加快转移速度，但会极大地增加 CPU 与内存瞬间压力。"
                }),
            },
        }

    RETURN_TYPES = (anyType,)
    RETURN_NAMES = ("checkpoint_model",)
    CATEGORY = "小白工具箱/显存特攻"
    FUNCTION = "set_callback"

    def set_callback(self, checkpoint_model: ModelPatcher, blocks_to_swap, offload_txt_emb, offload_img_emb, use_non_blocking):
        if not isinstance(checkpoint_model, ModelPatcher):
            print("\033[31m[XB Checkpoint块交换]\033[0m: 拦截失败！输入的数据流不是合法的模型对象。")
            return (checkpoint_model,)

        def swap_blocks(model_patcher: ModelPatcher, device_to, lowvram_model_memory, force_patch_weights, full_load):
            base_model = model_patcher.model
            main_device = torch.device('cuda')

            diffusion_model = getattr(base_model, 'diffusion_model', None)
            if not diffusion_model:
                return

            all_blocks = []
            block_paths = [
                'transformer_blocks',
                'blocks',
                'down_blocks',
                'up_blocks',
                'mid_block',
                'layers',
                'attention_blocks',
                'input_blocks',
                'middle_block',
                'output_blocks',
            ]

            found_path = None
            for path in block_paths:
                if hasattr(diffusion_model, path):
                    attr = getattr(diffusion_model, path)
                    if isinstance(attr, (list, torch.nn.ModuleList)):
                        all_blocks.extend(attr)
                        found_path = path
                        break

            if all_blocks:
                print(f"\033[36m[XB Checkpoint块交换]\033[0m: 从路径 '{found_path}' 找到 {len(all_blocks)} 个块。")
                for b, block in tqdm(enumerate(all_blocks), total=len(all_blocks), desc="正在切割 Checkpoint 流水线"):
                    if b > blocks_to_swap:
                        block.to(main_device)
                    else:
                        block.to(model_patcher.offload_device) 

            embedding_paths = {
                'text': ['text_embedding', 'caption_encoder', 'text_encoder'],
                'img': ['img_emb', 'image_encoder', 'visual_encoder']
            }

            if offload_txt_emb:
                for path in embedding_paths['text']:
                    if hasattr(diffusion_model, path) and getattr(diffusion_model, path) is not None:
                        getattr(diffusion_model, path).to(model_patcher.offload_device, non_blocking=use_non_blocking)
                        print(f"\033[36m[XB Checkpoint块交换]\033[0m: 已将文本层 '{path}' 卸载到内存。")
                        break

            if offload_img_emb:
                for path in embedding_paths['img']:
                    if hasattr(diffusion_model, path) and getattr(diffusion_model, path) is not None:
                        getattr(diffusion_model, path).to(model_patcher.offload_device, non_blocking=use_non_blocking)
                        print(f"\033[36m[XB Checkpoint块交换]\033[0m: 已将视觉层 '{path}' 卸载到内存。")
                        break

            mm.soft_empty_cache()
            gc.collect()

        checkpoint_model = checkpoint_model.clone()
        checkpoint_model.add_callback(CallbacksMP.ON_LOAD, swap_blocks)

        return (checkpoint_model, )