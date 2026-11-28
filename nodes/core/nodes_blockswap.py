import comfy.model_management as mm
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

BLOCK_PATHS = [
    'transformer_blocks', 'blocks', 'down_blocks', 'up_blocks', 'mid_block',
    'layers', 'attention_blocks', 'input_blocks', 'middle_block', 'output_blocks',
    'double_blocks', 'single_blocks', 'joint_blocks'
]


def is_dynamic_vram_active(model=None):
    """判断 DynamicVRAM（comfy-aimdo）是否生效。

    DynamicVRAM 只要装了 comfy-aimdo 且驱动/torch 满足条件就由 ComfyUI 默认启用
    （见 main.py），与是否传 --enable-dynamic-vram 无关。因此优先按运行时真实状态判断，
    否则用户没加参数时分块照常执行，会与 aimdo 的权重流式加载冲突。
    """
    if model is not None:
        try:
            is_dynamic = getattr(model, "is_dynamic", None)
            if callable(is_dynamic) and is_dynamic():
                return True
        except Exception:
            pass
    try:
        import comfy.memory_management
        if getattr(comfy.memory_management, "aimdo_enabled", False):
            return True
    except Exception:
        pass
    return "--enable-dynamic-vram" in sys.argv


def _fmt_gb(n):
    return f"{n / (1024 ** 3):.2f}GB"


def _free_memory():
    try:
        return mm.get_free_memory()
    except Exception:
        return 0


def _collect_blocks(diffusion_model):
    """收集模型里可独立卸载的 block（各架构的叫法不同，只收认识的容器）。"""
    all_blocks = []
    for path in BLOCK_PATHS:
        if not hasattr(diffusion_model, path):
            continue
        attr = getattr(diffusion_model, path)
        if isinstance(attr, (list, torch.nn.ModuleList)):
            all_blocks.extend(attr)
        elif isinstance(attr, torch.nn.Module) and path in ('mid_block', 'middle_block'):
            all_blocks.append(attr)
    return all_blocks


def _offload_blocks(model_patcher, all_blocks, blocks_to_swap, lowvram_model_memory,
                    tag, non_blocking=False):
    """把前 blocks_to_swap 个 block 卸载到 offload_device，返回 (卸载数量, 释放显存字节)。

    只有 ComfyUI 判定"整个模型能装进显存"（lowvram_model_memory <= 0）时，才把其余 block
    推回主设备；lowvram 模式下其余 block 的摆放交给 ComfyUI，避免加载阶段就把显存顶爆。
    """
    total_blocks = len(all_blocks)
    if total_blocks == 0:
        return 0, 0

    effective = min(blocks_to_swap, total_blocks)
    fit_full = lowvram_model_memory is None or lowvram_model_memory <= 0
    free_before = _free_memory()

    for b, block in enumerate(tqdm(all_blocks, total=total_blocks, desc=f"[{tag}] Slicing pipeline")):
        if b < effective:
            block.to(model_patcher.offload_device, non_blocking=non_blocking)
        elif fit_full:
            block.to(model_patcher.load_device, non_blocking=non_blocking)

    mm.soft_empty_cache()
    return effective, max(0, _free_memory() - free_before)


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
                "unet_model": ("MODEL", {"tooltip": "纯 UNet / DiT 模型输入"}),
                "blocks_to_swap": ("INT", {
                    "default": 10,  
                    "min": 0,       
                    "max": 200,     
                    "step": 1,      
                    "tooltip": "卸载到系统内存的核心模块数量。0=关闭分块，数值越大越省显存但越慢。"
                }),
            },
        }
    
    RETURN_TYPES = ("MODEL",)
    RETURN_NAMES = ("unet_model",)
    CATEGORY = "XB_ToolBox/VRAM_Hacks"
    FUNCTION = "set_callback"

    def set_callback(self, unet_model: ModelPatcher, blocks_to_swap):
        if not isinstance(unet_model, ModelPatcher):
            return (unet_model,)

        # ── 0 = 关闭分块功能：直接穿透，不做任何检测、不输出动态显存休眠警告 ──
        if blocks_to_swap == 0:
            print("\033[96m[XB UNet Block Swap]\033[0m: 分块数量 = 0，分块功能已关闭（节点穿透）")
            return (unet_model,)

        if is_dynamic_vram_active(unet_model):
            print("\033[93m[XB UNet Block Swap]\033[0m: ⚠️ 检测到 DynamicVRAM（comfy-aimdo）已启用，分块功能已休眠。\n"
                  "   动态显存下权重本来就在系统内存里、按块流式加载，再把 block 搬到内存是无操作、省不到显存。\n"
                  "   需要降显存：降低分辨率/帧数，或使用降低激活峰值的节点。")
            return (unet_model,)

        def swap_blocks(model_patcher: ModelPatcher, device_to, lowvram_model_memory, force_patch_weights, full_load):
            if is_dynamic_vram_active(model_patcher):
                print("\033[93m[XB UNet Block Swap]\033[0m: 加载时检测到动态显存，跳过分块。")
                return

            diffusion_model = getattr(model_patcher.model, 'diffusion_model', None)
            if not diffusion_model:
                return

            unsupported_name = is_unsupported_model(diffusion_model)
            if unsupported_name:
                print(f"\033[93m[XB-BOX 拦截盾]\033[0m: 模型 ({unsupported_name}) 属于高耦合架构，不支持物理分块。已自动跳过！")
                return

            all_blocks = _collect_blocks(diffusion_model)
            if not all_blocks:
                print("\033[93m[XB UNet Block Swap]\033[0m: 未找到可卸载的 block 容器，已跳过。")
                return

            total_blocks = len(all_blocks)
            effective = min(blocks_to_swap, total_blocks)
            tag = "匹配最大可分块参数" if blocks_to_swap > total_blocks else "匹配用户设置的参数"
            print(f"\033[96m[XB UNet Block Swap]\033[0m: 静态物理分块交换已激活！"
                  f"已找到 {total_blocks} 个引擎模块，分割 {effective} 个分块（{tag}）。")

            effective, freed = _offload_blocks(model_patcher, all_blocks, blocks_to_swap,
                                               lowvram_model_memory, "XB UNet Block Swap")
            print(f"\033[96m[XB UNet Block Swap]\033[0m: 已卸载 {effective} 个分块，"
                  f"释放显存 {_fmt_gb(freed)}。")
        
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
                "checkpoint_model": ("MODEL", {"tooltip": "模型输入（UNet / Checkpoint 里的 MODEL）"}),
                "blocks_to_swap": ("INT", {
                    "default": 15, "min": 0, "max": 1000, "step": 1,
                    "tooltip": "卸载到系统内存的核心模块数量。0=关闭分块。"
                }),
                "offload_img_emb": ("BOOLEAN", {"default": True, "tooltip": "把图像嵌入层也卸载到系统内存"}),
                "offload_txt_emb": ("BOOLEAN", {"default": True, "tooltip": "把文本嵌入层也卸载到系统内存"}),
                "use_non_blocking": ("BOOLEAN", {"default": False, "tooltip": "卸载时使用非阻塞拷贝（作用于 block 与嵌入层）"}),
            },
        }

    RETURN_TYPES = ("MODEL",)
    RETURN_NAMES = ("checkpoint_model",)
    CATEGORY = "XB_ToolBox/VRAM_Hacks"
    FUNCTION = "set_callback"

    def set_callback(self, checkpoint_model: ModelPatcher, blocks_to_swap, offload_txt_emb, offload_img_emb,
                     use_non_blocking):
        if not isinstance(checkpoint_model, ModelPatcher):
            return (checkpoint_model,)

        # ── 0 = 关闭分块功能：直接穿透，不做任何检测、不输出动态显存休眠警告 ──
        if blocks_to_swap == 0:
            print("\033[96m[XB Checkpoint Block Swap]\033[0m: 分块数量 = 0，分块功能已关闭（节点穿透）")
            return (checkpoint_model,)

        if is_dynamic_vram_active(checkpoint_model):
            print("\033[93m[XB Checkpoint Block Swap]\033[0m: ⚠️ 检测到 DynamicVRAM（comfy-aimdo）已启用，分块功能已休眠。\n"
                  "   动态显存下权重本来就在系统内存里、按块流式加载，再把 block 搬到内存是无操作、省不到显存。\n"
                  "   需要降显存：降低分辨率/帧数，或使用降低激活峰值的节点。")
            return (checkpoint_model,)

        def swap_blocks(model_patcher: ModelPatcher, device_to, lowvram_model_memory, force_patch_weights, full_load):
            if is_dynamic_vram_active(model_patcher):
                print("\033[93m[XB Checkpoint Block Swap]\033[0m: 加载时检测到动态显存，跳过分块。")
                return

            diffusion_model = getattr(model_patcher.model, 'diffusion_model', None)
            if not diffusion_model:
                return

            unsupported_name = is_unsupported_model(diffusion_model)
            if unsupported_name:
                print(f"\033[93m[XB-BOX 拦截盾]\033[0m: 模型 ({unsupported_name}) 属于高耦合架构，不支持物理分块。已自动跳过！")
                return

            all_blocks = _collect_blocks(diffusion_model)
            freed = 0
            if all_blocks:
                total_blocks = len(all_blocks)
                effective = min(blocks_to_swap, total_blocks)
                tag = "匹配最大可分块参数" if blocks_to_swap > total_blocks else "匹配用户设置的参数"
                print(f"\033[96m[XB Checkpoint Block Swap]\033[0m: 静态物理分块交换已激活！"
                      f"已找到 {total_blocks} 个引擎模块，分割 {effective} 个分块（{tag}）。")
                effective, freed = _offload_blocks(model_patcher, all_blocks, blocks_to_swap,
                                                   lowvram_model_memory, "XB Checkpoint Block Swap",
                                                   non_blocking=use_non_blocking)
            else:
                print("\033[93m[XB Checkpoint Block Swap]\033[0m: 未找到可卸载的 block 容器，仅处理嵌入层。")

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
            if all_blocks:
                print(f"\033[96m[XB Checkpoint Block Swap]\033[0m: 已卸载 {effective} 个分块"
                      f"{' + 嵌入层' if (offload_txt_emb or offload_img_emb) else ''}，释放显存 {_fmt_gb(freed)}。")

        checkpoint_model = checkpoint_model.clone()
        checkpoint_model.add_callback(CallbacksMP.ON_LOAD, swap_blocks)

        return (checkpoint_model, )