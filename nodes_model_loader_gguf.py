"""
XB-ToolBox 模型加载大全节点 (GGUF版)
=====================================
V1_GGUF: UNet(GGUF) + CLIP(GGUF) + LoRA(多槽) + VAE + Sage + BlockSwap
V2_GGUF: 高噪/低噪 UNet(GGUF) + CLIP(GGUF) + 双LoRA + 双Sage + 双BlockSwap
V3_GGUF: UNet(GGUF) + 双CLIP(GGUF) + 双VAE + LoRA/Sage/BlockSwap

套壳 ComfyUI-GGUF 官方节点 + ComfyUI 原生节点。
"""

import os
import sys
import importlib.util

import folder_paths
import nodes  # ComfyUI 官方节点


# ══════════════════════════════════════════════════════════
# GGUF 模块动态加载
# ══════════════════════════════════════════════════════════
_GGUF_LOADED = False


def _find_gguf_root():
    for base in folder_paths.get_folder_paths("custom_nodes"):
        for n in os.listdir(base):
            if n == "ComfyUI-GGUF" or n.lower().startswith("comfyui-gguf"):
                p = os.path.join(base, n)
                if os.path.exists(os.path.join(p, "nodes.py")):
                    return p
    raise RuntimeError("ComfyUI-GGUF 未安装！请先安装 GGUF 节点包。")


def _load_gguf():
    global _GGUF_LOADED
    if _GGUF_LOADED:
        return
    root = _find_gguf_root()
    pkg_name = "_xb_gguf_nodes"

    # 加载包 __init__.py
    init_path = os.path.join(root, "__init__.py")
    if pkg_name not in sys.modules:
        spec = importlib.util.spec_from_file_location(pkg_name, init_path, submodule_search_locations=[root])
        mod = importlib.util.module_from_spec(spec)
        sys.modules[pkg_name] = mod
        try:
            spec.loader.exec_module(mod)
        except ImportError:
            pass

    # 加载依赖子模块
    for sub in ["ops", "loader", "dequant"]:
        sub_name = pkg_name + "." + sub
        if sub_name not in sys.modules:
            sub_path = os.path.join(root, sub + ".py")
            if os.path.exists(sub_path):
                s = importlib.util.spec_from_file_location(sub_name, sub_path)
                m = importlib.util.module_from_spec(s)
                sys.modules[sub_name] = m
                s.loader.exec_module(m)

    # 加载 nodes 模块
    nodes_full = pkg_name + ".nodes"
    if nodes_full not in sys.modules:
        s = importlib.util.spec_from_file_location(nodes_full, os.path.join(root, "nodes.py"))
        m = importlib.util.module_from_spec(s)
        sys.modules[nodes_full] = m
        s.loader.exec_module(m)

    _GGUF_LOADED = True


def _gguf_nodes():
    _load_gguf()
    return sys.modules["_xb_gguf_nodes.nodes"]


# ══════════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════════
def _filter_by_keyword(folder_type, keyword: str):
    if not keyword or not keyword.strip():
        return ["(请先输入模型类型)"]
    kw = keyword.strip().lower()
    base_dirs = folder_paths.get_folder_paths(folder_type)
    result = []
    valid_exts = {".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".gguf"}
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
# XB_ModelLoaderV1_GGUF
# ══════════════════════════════════════════════════════════
class XB_ModelLoaderV1_GGUF:

    MAX_LORA_SLOTS = 8

    @classmethod
    def INPUT_TYPES(cls):
        clip_types = nodes.CLIPLoader.INPUT_TYPES()["required"]["type"][0]
        inputs = {
            "required": {
                "model_type": ("STRING", {"default": "", "multiline": False}),
                "model": (["(请先输入模型类型)"],),
                "clip": (["(请先输入模型类型)"],),
                "clip_type": (clip_types, {"default": "stable_diffusion"}),
                "lora_1": (["无"],),
                "lora_1_on": ("BOOLEAN", {"default": True}),
                "lora_1_strength": ("FLOAT", {"default": 1.0, "min": -100.0, "max": 100.0, "step": 0.05}),
                "vae": (["(请先输入模型类型)"],),
                "sage_preset": (["关闭","自动","内置模式 A (128x128x32)","内置模式 B (128x64x96)",
                    "内置模式 C (128x16x16)","内置模式 D (64x64x16)",
                    "自定模式 A","自定模式 B","自定模式 C"], {"default": "关闭"}),
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
    CATEGORY = "XB_ToolBox/Model_Loader_GGUF"

    def load_all(self, model_type, model, clip, clip_type, vae, sage_preset, blocks_to_swap, **kwargs):
        gguf = _gguf_nodes()
        model_loaded = gguf.UnetLoaderGGUFAdvanced().load_unet(model)[0]
        clip_loaded = gguf.CLIPLoaderGGUF().load_clip(clip, clip_type)[0]
        vae_loaded = nodes.VAELoader().load_vae(vae)[0]
        lora = nodes.LoraLoader()
        for i in range(1, self.MAX_LORA_SLOTS + 1):
            ln = kwargs.get(f"lora_{i}", "无")
            if kwargs.get(f"lora_{i}_on", False) and ln and ln != "无":
                s = kwargs.get(f"lora_{i}_strength", 1.0)
                model_loaded, clip_loaded = lora.load_lora(model_loaded, clip_loaded, ln, s, s)
        model_loaded = _apply_sage_attention(model_loaded, sage_preset)
        model_loaded = _apply_block_swap(model_loaded, blocks_to_swap)
        print(f"\033[92m[GGUF V1]\033[0m UNet:{model} CLIP:{clip}({clip_type}) VAE:{vae}")
        return (model_loaded, clip_loaded, vae_loaded)


# ══════════════════════════════════════════════════════════
# XB_ModelLoaderV2_GGUF
# ══════════════════════════════════════════════════════════
class XB_ModelLoaderV2_GGUF:

    MAX_LORA_SLOTS = 4

    @classmethod
    def INPUT_TYPES(cls):
        clip_types = nodes.CLIPLoader.INPUT_TYPES()["required"]["type"][0]
        sage_opts = ["关闭","自动","内置模式 A (128x128x32)","内置模式 B (128x64x96)",
            "内置模式 C (128x16x16)","内置模式 D (64x64x16)","自定模式 A","自定模式 B","自定模式 C"]
        inputs = {
            "required": {
                "model_type": ("STRING", {"default": "", "multiline": False}),
                "model_high": (["(请先输入模型类型)"],),
                "lora_high_1": (["无"],), "lora_high_1_on": ("BOOLEAN", {"default": True}),
                "lora_high_1_strength": ("FLOAT", {"default": 1.0, "min": -100.0, "max": 100.0, "step": 0.05}),
                "sage_high": (sage_opts, {"default": "关闭"}),
                "blockswap_high": ("INT", {"default": 0, "min": 0, "max": 200, "step": 1}),
                "model_low": (["(请先输入模型类型)"],),
                "lora_low_1": (["无"],), "lora_low_1_on": ("BOOLEAN", {"default": True}),
                "lora_low_1_strength": ("FLOAT", {"default": 1.0, "min": -100.0, "max": 100.0, "step": 0.05}),
                "sage_low": (sage_opts, {"default": "关闭"}),
                "blockswap_low": ("INT", {"default": 0, "min": 0, "max": 200, "step": 1}),
                "clip": (["(请先输入模型类型)"],),
                "clip_type": (clip_types, {"default": "stable_diffusion"}),
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
    CATEGORY = "XB_ToolBox/Model_Loader_GGUF"

    def load_all(self, model_type, model_high, sage_high, blockswap_high,
                 model_low, sage_low, blockswap_low, clip, clip_type, vae, **kwargs):
        gguf = _gguf_nodes()
        clip_loaded = gguf.CLIPLoaderGGUF().load_clip(clip, clip_type)[0]
        vae_loaded = nodes.VAELoader().load_vae(vae)[0]
        unet_loader = gguf.UnetLoaderGGUFAdvanced()
        lora = nodes.LoraLoader()

        mh = unet_loader.load_unet(model_high)[0]
        for i in range(1, self.MAX_LORA_SLOTS + 1):
            ln = kwargs.get(f"lora_high_{i}", "无")
            if kwargs.get(f"lora_high_{i}_on", False) and ln and ln != "无":
                s = kwargs.get(f"lora_high_{i}_strength", 1.0)
                mh, clip_loaded = lora.load_lora(mh, clip_loaded, ln, s, s)
        mh = _apply_sage_attention(mh, sage_high)
        mh = _apply_block_swap(mh, blockswap_high)

        ml = unet_loader.load_unet(model_low)[0]
        for i in range(1, self.MAX_LORA_SLOTS + 1):
            ln = kwargs.get(f"lora_low_{i}", "无")
            if kwargs.get(f"lora_low_{i}_on", False) and ln and ln != "无":
                s = kwargs.get(f"lora_low_{i}_strength", 1.0)
                ml, clip_loaded = lora.load_lora(ml, clip_loaded, ln, s, s)
        ml = _apply_sage_attention(ml, sage_low)
        ml = _apply_block_swap(ml, blockswap_low)

        print(f"\033[92m[GGUF V2]\033[0m 高噪:{model_high} 低噪:{model_low} CLIP:{clip}({clip_type}) VAE:{vae}")
        return (mh, ml, clip_loaded, vae_loaded)


# ══════════════════════════════════════════════════════════
# XB_ModelLoaderV3_GGUF
# ══════════════════════════════════════════════════════════
class XB_ModelLoaderV3_GGUF:

    MAX_LORA_SLOTS = 8

    @classmethod
    def INPUT_TYPES(cls):
        dual_clip_types = nodes.DualCLIPLoader.INPUT_TYPES()["required"]["type"][0]
        sage_opts = ["关闭","自动","内置模式 A (128x128x32)","内置模式 B (128x64x96)",
            "内置模式 C (128x16x16)","内置模式 D (64x64x16)","自定模式 A","自定模式 B","自定模式 C"]
        inputs = {
            "required": {
                "model_type": ("STRING", {"default": "", "multiline": False}),
                "model": (["(请先输入模型类型)"],),
                "clip1": (["(请先输入模型类型)"],),
                "clip2": (["(请先输入模型类型)"],),
                "clip_type": (dual_clip_types, {"default": "ltxv"}),
                "lora_1": (["无"],), "lora_1_on": ("BOOLEAN", {"default": True}),
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
    CATEGORY = "XB_ToolBox/Model_Loader_GGUF"

    def load_all(self, model_type, model, clip1, clip2, clip_type,
                 vae1, vae2, sage_preset, blocks_to_swap, **kwargs):
        gguf = _gguf_nodes()
        model_loaded = gguf.UnetLoaderGGUFAdvanced().load_unet(model)[0]
        clip_loaded = gguf.DualCLIPLoaderGGUF().load_clip(clip1, clip2, clip_type)[0]
        vae1_loaded = nodes.VAELoader().load_vae(vae1)[0]
        vae2_loaded = nodes.VAELoader().load_vae(vae2)[0]
        lora = nodes.LoraLoader()
        for i in range(1, self.MAX_LORA_SLOTS + 1):
            ln = kwargs.get(f"lora_{i}", "无")
            if kwargs.get(f"lora_{i}_on", False) and ln and ln != "无":
                s = kwargs.get(f"lora_{i}_strength", 1.0)
                model_loaded, clip_loaded = lora.load_lora(model_loaded, clip_loaded, ln, s, s)
        model_loaded = _apply_sage_attention(model_loaded, sage_preset)
        model_loaded = _apply_block_swap(model_loaded, blocks_to_swap)
        print(f"\033[92m[GGUF V3]\033[0m UNet:{model} DualCLIP:{clip1}+{clip2}({clip_type}) VAE1:{vae1} VAE2:{vae2}")
        return (model_loaded, clip_loaded, vae1_loaded, vae2_loaded)
