"""
XB-ToolBox 模型加载大全节点 (套壳官方节点版)
============================================
V1: UNet + CLIP + LoRA(多槽) + VAE + Sage + BlockSwap
V2: 高噪/低噪 双模型 + 双LoRA + 双Sage + 双BlockSwap
V3: 双CLIP + 双VAE (LTX 2.3)

直接调用 ComfyUI 官方 nodes.py 中的加载器，
仅在上层添加关键字过滤、LoRA多槽、Sage/BlockSwap 功能。
官方节点更新时，类型列表自动跟随。
"""

import os
import torch

import folder_paths
import comfy.utils
import nodes  # ComfyUI 官方节点


# ══════════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════════
def _filter_by_keyword(folder_type, keyword: str):
    """扫描模型目录，仅返回子文件夹名包含 keyword 的文件。"""
    if not keyword or not keyword.strip():
        return ["(请先输入模型类型)"]
    kw = keyword.strip().lower()
    base_dirs = folder_paths.get_folder_paths(folder_type)
    result = []
    valid_exts = {".safetensors", ".ckpt", ".pt", ".pth", ".bin"}
    for base_dir in base_dirs:
        if not os.path.exists(base_dir):
            continue
        for root, dirs, files in os.walk(base_dir):
            rel = os.path.relpath(root, base_dir)
            if rel == ".":
                continue
            parts = rel.replace("\\", "/").split("/")
            if not any(kw in p.lower() for p in parts):
                continue
            for f in files:
                if os.path.splitext(f)[1].lower() in valid_exts:
                    result.append(os.path.join(rel, f).replace("\\", "/"))
    result.sort()
    return result if result else ["(无匹配模型)"]


def _apply_sage_attention(model, preset: str):
    if preset == "关闭" or model is None:
        return model
    try:
        from .nodes_sageatt import XB_SageAttentionAccelerator
        return XB_SageAttentionAccelerator().patch(model, preset)[0]
    except Exception:
        return model


def _apply_block_swap(model, blocks_to_swap: int):
    if blocks_to_swap == 0 or model is None:
        return model
    try:
        from .nodes_blockswap import XB_UNetBlockSwap
        return XB_UNetBlockSwap().set_callback(model, blocks_to_swap)[0]
    except Exception:
        return model


# ══════════════════════════════════════════════════════════
# XB_ModelLoaderV1
# ══════════════════════════════════════════════════════════
class XB_ModelLoaderV1:
    """UNet(官方) + CLIP(官方) + LoRA(多槽) + VAE(官方) + Sage + BlockSwap"""

    MAX_LORA_SLOTS = 8

    @classmethod
    def INPUT_TYPES(cls):
        # 直接从官方节点读取类型列表
        unet_dtypes = nodes.UNETLoader.INPUT_TYPES()["required"]["weight_dtype"][0]
        clip_types = nodes.CLIPLoader.INPUT_TYPES()["required"]["type"][0]
        inputs = {
            "required": {
                "model_type": ("STRING", {"default": "", "multiline": False,
                    "tooltip": "输入关键字（如 wan/flux/sd），只显示匹配子文件夹中的模型"}),
                "model": (["(请先输入模型类型)"],),
                "model_weight_dtype": (unet_dtypes, {"default": "default"}),
                "clip": (["(请先输入模型类型)"],),
                "clip_type": (clip_types, {"default": "stable_diffusion"}),
                "clip_device": (["default", "cpu"], {"default": "default"}),
                "lora_1": (["无"],),
                "lora_1_on": ("BOOLEAN", {"default": True}),
                "lora_1_strength": ("FLOAT", {"default": 1.0, "min": -100.0, "max": 100.0, "step": 0.05}),
                "vae": (["(请先输入模型类型)"],),
                "sage_preset": ([
                    "关闭", "自动",
                    "内置模式 A (128x128x32)", "内置模式 B (128x64x96)",
                    "内置模式 C (128x16x16)", "内置模式 D (64x64x16)",
                    "自定模式 A", "自定模式 B", "自定模式 C",
                ], {"default": "关闭"}),
                "blocks_to_swap": ("INT", {"default": 0, "min": 0, "max": 200, "step": 1}),
            }
        }
        for i in range(2, cls.MAX_LORA_SLOTS + 1):
            inputs["required"][f"lora_{i}"] = (["无"],)
            inputs["required"][f"lora_{i}_on"] = ("BOOLEAN", {"default": False})
            inputs["required"][f"lora_{i}_strength"] = ("FLOAT", {"default": 1.0, "min": -100.0, "max": 100.0, "step": 0.05})
        return inputs

    RETURN_TYPES = ("MODEL", "CLIP", "VAE")
    RETURN_NAMES = ("MODEL", "CLIP", "VAE")
    FUNCTION = "load_all"
    CATEGORY = "XB_ToolBox/Model_Loader"

    def load_all(self, model_type, model, model_weight_dtype, clip, clip_type, clip_device,
                 vae, sage_preset, blocks_to_swap, **kwargs):
        # ── 官方 UNETLoader ──
        model_loaded = nodes.UNETLoader().load_unet(model, model_weight_dtype)[0]
        # ── 官方 CLIPLoader ──
        clip_loaded = nodes.CLIPLoader().load_clip(clip, clip_type, clip_device)[0]
        # ── 官方 VAELoader ──
        vae_loaded = nodes.VAELoader().load_vae(vae)[0]
        # ── 官方 LoraLoader 栈 ──
        lora = nodes.LoraLoader()
        for i in range(1, self.MAX_LORA_SLOTS + 1):
            ln = kwargs.get(f"lora_{i}", "无")
            lo = kwargs.get(f"lora_{i}_on", False)
            ls = kwargs.get(f"lora_{i}_strength", 1.0)
            if lo and ln and ln != "无":
                model_loaded, clip_loaded = lora.load_lora(model_loaded, clip_loaded, ln, ls, ls)
        # ── Sage + BlockSwap ──
        model_loaded = _apply_sage_attention(model_loaded, sage_preset)
        model_loaded = _apply_block_swap(model_loaded, blocks_to_swap)
        print(f"\033[92m[模型加载大全V1]\033[0m UNet:{model} CLIP:{clip}({clip_type}) VAE:{vae} Sage:{sage_preset} BS:{blocks_to_swap}")
        return (model_loaded, clip_loaded, vae_loaded)


# ══════════════════════════════════════════════════════════
# XB_ModelLoaderV2 (高噪+低噪 双模型)
# ══════════════════════════════════════════════════════════
class XB_ModelLoaderV2:
    """双模型：高噪 + 低噪，各自 LoRA/Sage/BlockSwap"""

    MAX_LORA_SLOTS = 4

    @classmethod
    def INPUT_TYPES(cls):
        unet_dtypes = nodes.UNETLoader.INPUT_TYPES()["required"]["weight_dtype"][0]
        clip_types = nodes.CLIPLoader.INPUT_TYPES()["required"]["type"][0]
        sage_opts = ["关闭","自动","内置模式 A (128x128x32)","内置模式 B (128x64x96)","内置模式 C (128x16x16)","内置模式 D (64x64x16)","自定模式 A","自定模式 B","自定模式 C"]
        inputs = {
            "required": {
                "model_type": ("STRING", {"default": "", "multiline": False}),
                "model_high": (["(请先输入模型类型)"],),
                "model_high_weight_dtype": (unet_dtypes, {"default": "default"}),
                "lora_high_1": (["无"],),
                "lora_high_1_on": ("BOOLEAN", {"default": True}),
                "lora_high_1_strength": ("FLOAT", {"default": 1.0, "min": -100.0, "max": 100.0, "step": 0.05}),
                "sage_high": (sage_opts, {"default": "关闭"}),
                "blockswap_high": ("INT", {"default": 0, "min": 0, "max": 200, "step": 1}),
                "model_low": (["(请先输入模型类型)"],),
                "model_low_weight_dtype": (unet_dtypes, {"default": "default"}),
                "lora_low_1": (["无"],),
                "lora_low_1_on": ("BOOLEAN", {"default": True}),
                "lora_low_1_strength": ("FLOAT", {"default": 1.0, "min": -100.0, "max": 100.0, "step": 0.05}),
                "sage_low": (sage_opts, {"default": "关闭"}),
                "blockswap_low": ("INT", {"default": 0, "min": 0, "max": 200, "step": 1}),
                "clip": (["(请先输入模型类型)"],),
                "clip_type": (clip_types, {"default": "stable_diffusion"}),
                "clip_device": (["default", "cpu"], {"default": "default"}),
                "vae": (["(请先输入模型类型)"],),
            }
        }
        for i in range(2, cls.MAX_LORA_SLOTS + 1):
            inputs["required"][f"lora_high_{i}"] = (["无"],)
            inputs["required"][f"lora_high_{i}_on"] = ("BOOLEAN", {"default": False})
            inputs["required"][f"lora_high_{i}_strength"] = ("FLOAT", {"default": 1.0, "min": -100.0, "max": 100.0, "step": 0.05})
        for i in range(2, cls.MAX_LORA_SLOTS + 1):
            inputs["required"][f"lora_low_{i}"] = (["无"],)
            inputs["required"][f"lora_low_{i}_on"] = ("BOOLEAN", {"default": False})
            inputs["required"][f"lora_low_{i}_strength"] = ("FLOAT", {"default": 1.0, "min": -100.0, "max": 100.0, "step": 0.05})
        return inputs

    RETURN_TYPES = ("MODEL", "MODEL", "CLIP", "VAE")
    RETURN_NAMES = ("Model High", "Model Low", "CLIP", "VAE")
    FUNCTION = "load_all"
    CATEGORY = "XB_ToolBox/Model_Loader"

    def load_all(self, model_type,
                 model_high, model_high_weight_dtype, sage_high, blockswap_high,
                 model_low, model_low_weight_dtype, sage_low, blockswap_low,
                 clip, clip_type, clip_device, vae, **kwargs):
        clip_loaded = nodes.CLIPLoader().load_clip(clip, clip_type, clip_device)[0]
        vae_loaded = nodes.VAELoader().load_vae(vae)[0]
        lora = nodes.LoraLoader()

        # 高噪
        mh = nodes.UNETLoader().load_unet(model_high, model_high_weight_dtype)[0]
        for i in range(1, self.MAX_LORA_SLOTS + 1):
            ln = kwargs.get(f"lora_high_{i}", "无")
            if kwargs.get(f"lora_high_{i}_on", False) and ln and ln != "无":
                mh, clip_loaded = lora.load_lora(mh, clip_loaded, ln, kwargs.get(f"lora_high_{i}_strength", 1.0), kwargs.get(f"lora_high_{i}_strength", 1.0))
        mh = _apply_sage_attention(mh, sage_high)
        mh = _apply_block_swap(mh, blockswap_high)

        # 低噪
        ml = nodes.UNETLoader().load_unet(model_low, model_low_weight_dtype)[0]
        for i in range(1, self.MAX_LORA_SLOTS + 1):
            ln = kwargs.get(f"lora_low_{i}", "无")
            if kwargs.get(f"lora_low_{i}_on", False) and ln and ln != "无":
                ml, clip_loaded = lora.load_lora(ml, clip_loaded, ln, kwargs.get(f"lora_low_{i}_strength", 1.0), kwargs.get(f"lora_low_{i}_strength", 1.0))
        ml = _apply_sage_attention(ml, sage_low)
        ml = _apply_block_swap(ml, blockswap_low)

        print(f"\033[92m[模型加载大全V2]\033[0m 高噪:{model_high} 低噪:{model_low} CLIP:{clip}({clip_type}) VAE:{vae}")
        return (mh, ml, clip_loaded, vae_loaded)


# ══════════════════════════════════════════════════════════
# XB_ModelLoaderV3 (双CLIP + 双VAE)
# ══════════════════════════════════════════════════════════
class XB_ModelLoaderV3:
    """双CLIP(官方DualCLIPLoader合并输出) + 双VAE + LoRA/Sage/BlockSwap"""

    MAX_LORA_SLOTS = 8

    @classmethod
    def INPUT_TYPES(cls):
        unet_dtypes = nodes.UNETLoader.INPUT_TYPES()["required"]["weight_dtype"][0]
        dual_clip_types = nodes.DualCLIPLoader.INPUT_TYPES()["required"]["type"][0]
        sage_opts = ["关闭","自动","内置模式 A (128x128x32)","内置模式 B (128x64x96)","内置模式 C (128x16x16)","内置模式 D (64x64x16)","自定模式 A","自定模式 B","自定模式 C"]
        inputs = {
            "required": {
                "model_type": ("STRING", {"default": "", "multiline": False}),
                "model": (["(请先输入模型类型)"],),
                "model_weight_dtype": (unet_dtypes, {"default": "default"}),
                "clip1": (["(请先输入模型类型)"],),
                "clip2": (["(请先输入模型类型)"],),
                "clip_type": (dual_clip_types, {"default": "ltxv"}),
                "clip_device": (["default", "cpu"], {"default": "default"}),
                "lora_1": (["无"],),
                "lora_1_on": ("BOOLEAN", {"default": True}),
                "lora_1_strength": ("FLOAT", {"default": 1.0, "min": -100.0, "max": 100.0, "step": 0.05}),
                "vae1": (["(请先输入模型类型)"],),
                "vae2": (["(请先输入模型类型)"],),
                "sage_preset": (sage_opts, {"default": "关闭"}),
                "blocks_to_swap": ("INT", {"default": 0, "min": 0, "max": 200, "step": 1}),
            }
        }
        for i in range(2, cls.MAX_LORA_SLOTS + 1):
            inputs["required"][f"lora_{i}"] = (["无"],)
            inputs["required"][f"lora_{i}_on"] = ("BOOLEAN", {"default": False})
            inputs["required"][f"lora_{i}_strength"] = ("FLOAT", {"default": 1.0, "min": -100.0, "max": 100.0, "step": 0.05})
        return inputs

    RETURN_TYPES = ("MODEL", "CLIP", "VAE", "VAE")
    RETURN_NAMES = ("MODEL", "CLIP", "VAE1", "VAE2")
    FUNCTION = "load_all"
    CATEGORY = "XB_ToolBox/Model_Loader"

    def load_all(self, model_type, model, model_weight_dtype,
                 clip1, clip2, clip_type, clip_device,
                 vae1, vae2, sage_preset, blocks_to_swap, **kwargs):
        # ── 官方 UNETLoader ──
        model_loaded = nodes.UNETLoader().load_unet(model, model_weight_dtype)[0]
        # ── 官方 DualCLIPLoader（双CLIP合并为一个CLIP输出）──
        clip_loaded = nodes.DualCLIPLoader().load_clip(clip1, clip2, clip_type, clip_device)[0]
        # ── 官方 VAELoader x2 ──
        vae1_loaded = nodes.VAELoader().load_vae(vae1)[0]
        vae2_loaded = nodes.VAELoader().load_vae(vae2)[0]
        # ── LoRA 栈 ──
        lora = nodes.LoraLoader()
        for i in range(1, self.MAX_LORA_SLOTS + 1):
            ln = kwargs.get(f"lora_{i}", "无")
            lo = kwargs.get(f"lora_{i}_on", False)
            ls = kwargs.get(f"lora_{i}_strength", 1.0)
            if lo and ln and ln != "无":
                model_loaded, clip_loaded = lora.load_lora(model_loaded, clip_loaded, ln, ls, ls)
        # ── Sage + BlockSwap ──
        model_loaded = _apply_sage_attention(model_loaded, sage_preset)
        model_loaded = _apply_block_swap(model_loaded, blocks_to_swap)
        print(f"\033[92m[模型加载大全V3]\033[0m UNet:{model} DualCLIP:{clip1}+{clip2}({clip_type}) VAE1:{vae1} VAE2:{vae2}")
        return (model_loaded, clip_loaded, vae1_loaded, vae2_loaded)
