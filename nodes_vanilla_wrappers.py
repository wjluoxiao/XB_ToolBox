"""
XB_ToolBox 原版优化节点 (Vanilla Wrappers) — v1.0
=================================================
一字不差地调用 ComfyUI 官方节点，仅在其执行前插入分级显存清理。
彻底放弃自定义底层算法，完全依赖官方维护的采样/解码逻辑。

设计原则:
  - 动态继承 INPUT_TYPES → 官方新增参数自动同步
  - **kwargs 透传 → 参数名/数量永不过时
  - 不做任何底层魔改 → 零维护成本
"""

import torch
import gc
import copy
import comfy.model_management as mm
import comfy.samplers
import nodes

# 安全导入: comfy_extras 在未来版本可能被移除
try:
    from comfy_extras import nodes_custom_sampler as _ncs
except ImportError:
    _ncs = None


# ═══════════════════════════════════════════════════════════════
# 统一的清理调度器
# ═══════════════════════════════════════════════════════════════

_CLEANUP_OPTIONS = [
    "不做任何清理",
    "单次缓存清理",
    "卸载显存模型",
    "卸载全量模型",
]


def _execute_cleanup(level: str, label: str = ""):
    """分级清理显存，在正式节点运行前强行制造显存真空区。

    四级策略：
      L0【不做任何清理】→ 透传
      L1【单次缓存清理】→ soft_empty_cache + empty_cache，清除碎片
      L2【卸载显存模型】→ unload_all_models，把模型退至内存
      L3【卸载全量模型】→ L2 + cleanup_models + cleanup_models_gc + gc.collect + ipc_collect
    """
    prefix = f"[XB_Wrapper{':'+label if label else ''}]"
    if level == "不做任何清理":
        return

    print(f"{prefix} 🧹 执行 {level} ...", flush=True)

    mm.soft_empty_cache()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    if level in ("卸载显存模型", "卸载全量模型"):
        mm.unload_all_models()
        mm.soft_empty_cache()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    if level == "卸载全量模型":
        mm.cleanup_models()
        mm.cleanup_models_gc()
        gc.collect()
        if torch.cuda.is_available() and hasattr(torch.cuda, "ipc_collect"):
            torch.cuda.ipc_collect()

    print(f"{prefix} ✅ 清理完成，显存环境纯净", flush=True)


# ═══════════════════════════════════════════════════════════════
# 采样器 Wrapper 节点
# ═══════════════════════════════════════════════════════════════

class XB_KSampler:
    """原版 KSampler 套皮 — 仅注入清理，参数零改动"""

    @classmethod
    def INPUT_TYPES(cls):
        inputs = copy.deepcopy(nodes.KSampler.INPUT_TYPES())
        inputs["required"]["cleanup"] = (_CLEANUP_OPTIONS, {"default": "不做任何清理"})
        return inputs

    RETURN_TYPES = nodes.KSampler.RETURN_TYPES
    FUNCTION = "sample"
    CATEGORY = "XB_ToolBox/原版优化"

    def sample(self, **kwargs):
        cleanup = kwargs.pop("cleanup", "不做任何清理")
        _execute_cleanup(cleanup, "采样器")
        return nodes.KSampler().sample(**kwargs)


class XB_KSamplerAdvanced:
    """原版 KSamplerAdvanced 套皮 — 仅注入清理，参数零改动"""

    @classmethod
    def INPUT_TYPES(cls):
        inputs = copy.deepcopy(nodes.KSamplerAdvanced.INPUT_TYPES())
        inputs["required"]["cleanup"] = (_CLEANUP_OPTIONS, {"default": "不做任何清理"})
        return inputs

    RETURN_TYPES = nodes.KSamplerAdvanced.RETURN_TYPES
    FUNCTION = "sample"
    CATEGORY = "XB_ToolBox/原版优化"

    def sample(self, **kwargs):
        cleanup = kwargs.pop("cleanup", "不做任何清理")
        _execute_cleanup(cleanup, "高级采样器")
        return nodes.KSamplerAdvanced().sample(**kwargs)


class XB_SamplerCustom:
    """原版 SamplerCustom 套皮 — 仅注入清理，参数零改动"""

    @classmethod
    def INPUT_TYPES(cls):
        inputs = copy.deepcopy(_ncs.SamplerCustom.INPUT_TYPES())
        inputs["required"]["cleanup"] = (_CLEANUP_OPTIONS, {"default": "不做任何清理"})
        return inputs

    RETURN_TYPES = _ncs.SamplerCustom.RETURN_TYPES
    FUNCTION = "sample"
    CATEGORY = "XB_ToolBox/原版优化"

    def sample(self, **kwargs):
        cleanup = kwargs.pop("cleanup", "不做任何清理")
        _execute_cleanup(cleanup, "自定义采样器")
        return _ncs.SamplerCustom.sample(**kwargs)


class XB_SamplerCustomAdvanced:
    """原版 SamplerCustomAdvanced 套皮 — 仅注入清理，参数零改动"""

    @classmethod
    def INPUT_TYPES(cls):
        inputs = copy.deepcopy(_ncs.SamplerCustomAdvanced.INPUT_TYPES())
        inputs["required"]["cleanup"] = (_CLEANUP_OPTIONS, {"default": "不做任何清理"})
        return inputs

    RETURN_TYPES = _ncs.SamplerCustomAdvanced.RETURN_TYPES
    FUNCTION = "sample"
    CATEGORY = "XB_ToolBox/原版优化"

    def sample(self, **kwargs):
        cleanup = kwargs.pop("cleanup", "不做任何清理")
        _execute_cleanup(cleanup, "自定义高级采样器")
        return _ncs.SamplerCustomAdvanced.sample(**kwargs)


# ═══════════════════════════════════════════════════════════════
# VAE 解码器 Wrapper 节点
# ═══════════════════════════════════════════════════════════════

class XB_VAEDecode:
    """原版 VAEDecode 套皮 — 仅注入清理，参数零改动"""

    @classmethod
    def INPUT_TYPES(cls):
        inputs = copy.deepcopy(nodes.VAEDecode.INPUT_TYPES())
        inputs["required"]["cleanup"] = (_CLEANUP_OPTIONS, {"default": "不做任何清理"})
        return inputs

    RETURN_TYPES = nodes.VAEDecode.RETURN_TYPES
    FUNCTION = "decode"
    CATEGORY = "XB_ToolBox/原版优化"

    def decode(self, **kwargs):
        cleanup = kwargs.pop("cleanup", "不做任何清理")
        _execute_cleanup(cleanup, "VAE解码")
        # 🛡️ AMD MIOpen 防护：确保 latent 是连续内存
        samples = kwargs.get("samples")
        if isinstance(samples, dict):
            lat = samples.get("samples")
            if hasattr(lat, 'is_contiguous') and not lat.is_contiguous():
                kwargs["samples"] = {**samples, "samples": lat.contiguous()}
        return nodes.VAEDecode().decode(**kwargs)


class XB_VAEDecodeTiled:
    """原版 VAEDecodeTiled 套皮 — 仅注入清理，参数零改动"""

    @classmethod
    def INPUT_TYPES(cls):
        inputs = copy.deepcopy(nodes.VAEDecodeTiled.INPUT_TYPES())
        inputs["required"]["cleanup"] = (_CLEANUP_OPTIONS, {"default": "不做任何清理"})
        return inputs

    RETURN_TYPES = nodes.VAEDecodeTiled.RETURN_TYPES
    FUNCTION = "decode"
    CATEGORY = "XB_ToolBox/原版优化"

    def decode(self, **kwargs):
        cleanup = kwargs.pop("cleanup", "不做任何清理")
        _execute_cleanup(cleanup, "VAE分块解码")
        return nodes.VAEDecodeTiled().decode(**kwargs)


class XB_VAEDecodeTiledImage:
    """原版 VAEDecodeTiled 图片专用套皮 — 仅空间分块，无时间维度"""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "samples": ("LATENT",),
            "vae": ("VAE",),
            "tile_size": ("INT", {"default": 512, "min": 256, "max": 4096, "step": 64,
                                 "tooltip": "空间分块大小(像素)"}),
            "overlap": ("INT", {"default": 64, "min": 0, "max": 256, "step": 16,
                                "tooltip": "空间块重叠(像素)"}),
            "cleanup": (_CLEANUP_OPTIONS, {"default": "不做任何清理"}),
        }}

    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "decode"
    CATEGORY = "XB_ToolBox/原版优化"

    def decode(self, **kwargs):
        cleanup = kwargs.pop("cleanup", "不做任何清理")
        _execute_cleanup(cleanup, "VAE分块解码(图片)")
        # 透传给官方 VAEDecodeTiled，时间参数用默认值
        kwargs.setdefault("temporal_size", 64)
        kwargs.setdefault("temporal_overlap", 8)
        return nodes.VAEDecodeTiled().decode(**kwargs)


class XB_VAEEncode:
    """原版 VAEEncode 套皮 — 仅注入清理，参数零改动"""

    @classmethod
    def INPUT_TYPES(cls):
        inputs = copy.deepcopy(nodes.VAEEncode.INPUT_TYPES())
        inputs["required"]["cleanup"] = (_CLEANUP_OPTIONS, {"default": "不做任何清理"})
        return inputs

    RETURN_TYPES = nodes.VAEEncode.RETURN_TYPES
    FUNCTION = "encode"
    CATEGORY = "XB_ToolBox/原版优化"

    def encode(self, **kwargs):
        cleanup = kwargs.pop("cleanup", "不做任何清理")
        _execute_cleanup(cleanup, "VAE编码")
        return nodes.VAEEncode().encode(**kwargs)


class XB_VAEEncodeTiled:
    """原版 VAEEncodeTiled 套皮 — 仅注入清理，参数零改动"""

    @classmethod
    def INPUT_TYPES(cls):
        inputs = copy.deepcopy(nodes.VAEEncodeTiled.INPUT_TYPES())
        inputs["required"]["cleanup"] = (_CLEANUP_OPTIONS, {"default": "不做任何清理"})
        return inputs

    RETURN_TYPES = nodes.VAEEncodeTiled.RETURN_TYPES
    FUNCTION = "encode"
    CATEGORY = "XB_ToolBox/原版优化"

    def encode(self, **kwargs):
        cleanup = kwargs.pop("cleanup", "不做任何清理")
        _execute_cleanup(cleanup, "VAE分块编码")
        return nodes.VAEEncodeTiled().encode(**kwargs)


class XB_VAEEncodeForInpaint:
    """原版 VAEEncodeForInpaint 套皮 — 仅注入清理，参数零改动"""

    @classmethod
    def INPUT_TYPES(cls):
        inputs = copy.deepcopy(nodes.VAEEncodeForInpaint.INPUT_TYPES())
        inputs["required"]["cleanup"] = (_CLEANUP_OPTIONS, {"default": "不做任何清理"})
        return inputs

    RETURN_TYPES = nodes.VAEEncodeForInpaint.RETURN_TYPES
    FUNCTION = "encode"
    CATEGORY = "XB_ToolBox/原版优化"

    def encode(self, **kwargs):
        cleanup = kwargs.pop("cleanup", "不做任何清理")
        _execute_cleanup(cleanup, "VAE修补编码")
        return nodes.VAEEncodeForInpaint().encode(**kwargs)


# ═══════════════════════════════════════════════════════════════
# 别名类 — 匹配旧 ROCm 节点参数名，保证旧工作流连线兼容
#         清理选项统一使用新的四级体系
# ═══════════════════════════════════════════════════════════════


class _AliasKSampler:
    """别名: XB_ROCmKSampler — latent→latent_image, sampler→sampler_name"""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "model": ("MODEL",),
            "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
            "steps": ("INT", {"default": 20, "min": 1, "max": 10000}),
            "cfg": ("FLOAT", {"default": 8.0, "min": 0.0, "max": 100.0, "step": 0.1}),
            "sampler": (comfy.samplers.KSampler.SAMPLERS,),
            "scheduler": (comfy.samplers.KSampler.SCHEDULERS,),
            "positive": ("CONDITIONING",),
            "negative": ("CONDITIONING",),
            "latent": ("LATENT",),
            "denoise": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01}),
            "cleanup": (_CLEANUP_OPTIONS, {"default": "不做任何清理"}),
        }}
    RETURN_TYPES = ("LATENT",)
    FUNCTION = "sample"
    CATEGORY = "XB_ToolBox/原版优化"

    def sample(self, **kwargs):
        cleanup = kwargs.pop("cleanup", "不做任何清理")
        _execute_cleanup(cleanup, "采样器")
        if "latent" in kwargs:
            kwargs["latent_image"] = kwargs.pop("latent")
        if "sampler" in kwargs:
            kwargs["sampler_name"] = kwargs.pop("sampler")
        return nodes.KSampler().sample(**kwargs)


class _AliasKSamplerAdvanced:
    """别名: XB_ROCmKSamplerAdvanced — latent→latent_image, sampler→sampler_name"""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "model": ("MODEL",),
            "add_noise": (["enable", "disable"], {}),
            "noise_seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
            "steps": ("INT", {"default": 20, "min": 1, "max": 10000}),
            "cfg": ("FLOAT", {"default": 8.0, "min": 0.0, "max": 100.0, "step": 0.1}),
            "sampler": (comfy.samplers.KSampler.SAMPLERS,),
            "scheduler": (comfy.samplers.KSampler.SCHEDULERS,),
            "positive": ("CONDITIONING",),
            "negative": ("CONDITIONING",),
            "latent": ("LATENT",),
            "start_at_step": ("INT", {"default": 0, "min": 0, "max": 10000}),
            "end_at_step": ("INT", {"default": 10000, "min": 0, "max": 10000}),
            "return_with_leftover_noise": (["disable", "enable"], {}),
            "cleanup": (_CLEANUP_OPTIONS, {"default": "不做任何清理"}),
        }}
    RETURN_TYPES = ("LATENT",)
    FUNCTION = "sample"
    CATEGORY = "XB_ToolBox/原版优化"

    def sample(self, **kwargs):
        cleanup = kwargs.pop("cleanup", "不做任何清理")
        _execute_cleanup(cleanup, "高级采样器")
        if "latent" in kwargs:
            kwargs["latent_image"] = kwargs.pop("latent")
        if "sampler" in kwargs:
            kwargs["sampler_name"] = kwargs.pop("sampler")
        return nodes.KSamplerAdvanced().sample(**kwargs)


class _AliasSamplerCustom:
    """别名: XB_ROCmSamplerCustom — 参数名一致，仅加清理"""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "model": ("MODEL",),
            "add_noise": ("BOOLEAN", {"default": True}),
            "noise_seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
            "cfg": ("FLOAT", {"default": 8.0, "min": 0.0, "max": 100.0, "step": 0.1}),
            "positive": ("CONDITIONING",),
            "negative": ("CONDITIONING",),
            "sampler": ("SAMPLER",),
            "sigmas": ("SIGMAS",),
            "latent_image": ("LATENT",),
            "cleanup": (_CLEANUP_OPTIONS, {"default": "不做任何清理"}),
        }}
    RETURN_TYPES = ("LATENT", "LATENT")
    RETURN_NAMES = ("output", "denoised_output")
    FUNCTION = "sample"
    CATEGORY = "XB_ToolBox/原版优化"

    def sample(self, **kwargs):
        cleanup = kwargs.pop("cleanup", "不做任何清理")
        _execute_cleanup(cleanup, "自定义采样器")
        return _ncs.SamplerCustom.sample(**kwargs)


class _AliasSamplerCustomAdvanced:
    """别名: XB_ROCmSamplerCustomAdvanced — 参数名一致，仅加清理"""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "noise": ("NOISE",),
            "guider": ("GUIDER",),
            "sampler": ("SAMPLER",),
            "sigmas": ("SIGMAS",),
            "latent_image": ("LATENT",),
            "cleanup": (_CLEANUP_OPTIONS, {"default": "不做任何清理"}),
        }}
    RETURN_TYPES = ("LATENT", "LATENT")
    RETURN_NAMES = ("output", "denoised_output")
    FUNCTION = "sample"
    CATEGORY = "XB_ToolBox/原版优化"

    def sample(self, **kwargs):
        cleanup = kwargs.pop("cleanup", "不做任何清理")
        _execute_cleanup(cleanup, "自定义高级采样器")
        return _ncs.SamplerCustomAdvanced.sample(**kwargs)


class _AliasVAEDecode:
    """别名: XB_ROCmVAEDecode — tile→tile_size, 走图片分块解码"""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "samples": ("LATENT",),
            "vae": ("VAE",),
            "tile": ("INT", {"default": 0, "min": 0, "max": 4096, "step": 64}),
            "overlap": ("INT", {"default": 0, "min": 0, "max": 256, "step": 16}),
            "cleanup": (_CLEANUP_OPTIONS, {"default": "不做任何清理"}),
        }}
    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "decode"
    CATEGORY = "XB_ToolBox/原版优化"

    def decode(self, **kwargs):
        cleanup = kwargs.pop("cleanup", "不做任何清理")
        _execute_cleanup(cleanup, "VAE解码")
        if "tile" in kwargs:
            kwargs["tile_size"] = kwargs.pop("tile") if kwargs["tile"] > 0 else 512
        kwargs.setdefault("temporal_size", 64)
        kwargs.setdefault("temporal_overlap", 8)
        return nodes.VAEDecodeTiled().decode(**kwargs)


class _AliasVAEDecodeTemporal:
    """别名: XB_ROCmVAEDecodeTemporal — tile→tile_size, t_tile→temporal_size, t_overlap→temporal_overlap"""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "samples": ("LATENT",),
            "vae": ("VAE",),
            "tile": ("INT", {"default": 0, "min": 0, "max": 4096, "step": 64}),
            "overlap": ("INT", {"default": 0, "min": 0, "max": 256, "step": 16}),
            "t_tile": ("INT", {"default": 0, "min": 0, "max": 1024, "step": 16}),
            "t_overlap": ("INT", {"default": 0, "min": 0, "max": 128, "step": 8}),
            "cleanup": (_CLEANUP_OPTIONS, {"default": "不做任何清理"}),
        }}
    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "decode"
    CATEGORY = "XB_ToolBox/原版优化"

    def decode(self, **kwargs):
        cleanup = kwargs.pop("cleanup", "不做任何清理")
        _execute_cleanup(cleanup, "VAE分块解码")
        if "tile" in kwargs:
            kwargs["tile_size"] = kwargs.pop("tile") if kwargs["tile"] > 0 else 512
        if "t_tile" in kwargs:
            kwargs["temporal_size"] = kwargs.pop("t_tile") if kwargs["t_tile"] > 0 else 64
        if "t_overlap" in kwargs:
            kwargs["temporal_overlap"] = kwargs.pop("t_overlap") if kwargs["t_overlap"] > 0 else 8
        return nodes.VAEDecodeTiled().decode(**kwargs)


class _AliasVAEEncode:
    """别名: XB_ROCmVAEEncode — tile→tile_size"""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "pixels": ("IMAGE",),
            "vae": ("VAE",),
            "tile": ("INT", {"default": 0, "min": 0, "max": 4096, "step": 64}),
            "overlap": ("INT", {"default": 0, "min": 0, "max": 256, "step": 16}),
            "temporal_size": ("INT", {"default": 0, "min": 0, "max": 1024, "step": 16}),
            "temporal_overlap": ("INT", {"default": 0, "min": 0, "max": 64, "step": 4}),
            "cleanup": (_CLEANUP_OPTIONS, {"default": "不做任何清理"}),
        }}
    RETURN_TYPES = ("LATENT",)
    FUNCTION = "encode"
    CATEGORY = "XB_ToolBox/原版优化"

    def encode(self, **kwargs):
        cleanup = kwargs.pop("cleanup", "不做任何清理")
        _execute_cleanup(cleanup, "VAE编码")
        if "tile" in kwargs:
            kwargs["tile_size"] = kwargs.pop("tile") if kwargs["tile"] > 0 else 512
        return nodes.VAEEncodeTiled().encode(**kwargs)


# LTX 别名直接复用 Temporal 别名类
_AliasLTXVAEDecode = _AliasVAEDecodeTemporal


# ═══════════════════════════════════════════════════════════════
# 节点注册
# ═══════════════════════════════════════════════════════════════

NODE_CLASS_MAPPINGS = {
    "XB_KSampler": XB_KSampler,
    "XB_KSamplerAdvanced": XB_KSamplerAdvanced,
    "XB_VAEDecode": XB_VAEDecode,
    "XB_VAEDecodeTiled": XB_VAEDecodeTiled,
    "XB_VAEDecodeTiledImage": XB_VAEDecodeTiledImage,
    "XB_VAEEncode": XB_VAEEncode,
    "XB_VAEEncodeTiled": XB_VAEEncodeTiled,
    "XB_VAEEncodeForInpaint": XB_VAEEncodeForInpaint,
}

# 仅在 comfy_extras 可用时注册自定义采样器
if _ncs is not None:
    NODE_CLASS_MAPPINGS["XB_SamplerCustom"] = XB_SamplerCustom
    NODE_CLASS_MAPPINGS["XB_SamplerCustomAdvanced"] = XB_SamplerCustomAdvanced

NODE_DISPLAY_NAME_MAPPINGS = {
    "XB_KSampler": "XB-采样器（原版优化）",
    "XB_KSamplerAdvanced": "XB-高级采样器（原版优化）",
    "XB_VAEDecode": "XB-VAE解码（原版优化）",
    "XB_VAEDecodeTiled": "XB-VAE分块解码（原版优化）",
    "XB_VAEDecodeTiledImage": "XB-VAE解码（原版优化）",
    "XB_VAEEncode": "XB-VAE编码（原版优化）",
    "XB_VAEEncodeTiled": "XB-VAE分块编码（原版优化）",
    "XB_VAEEncodeForInpaint": "XB-VAE修补编码（原版优化）",
}
if _ncs is not None:
    NODE_DISPLAY_NAME_MAPPINGS["XB_SamplerCustom"] = "XB-自定义采样器（原版优化）"
    NODE_DISPLAY_NAME_MAPPINGS["XB_SamplerCustomAdvanced"] = "XB-自定义高级采样器（原版优化）"
