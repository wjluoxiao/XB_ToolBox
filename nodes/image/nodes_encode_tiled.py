"""
XB-ToolBox 编码分块节点
========================
两个「套皮官方节点 + 只改 VAE 编码」的测试节点：

  🖼️ MiniMax H3 图像条件化（分块）   ← comfy_extras/nodes_minimax_h3.py: MiniMaxH3ImageConditioning
  📝 文本编码 Qwen Image 2.1（分块）  ← comfy_extras/nodes_qwen.py:      TextEncodeQwenImage21

为什么需要分块：
  官方节点的参考图 VAE 编码是整幅一次性编码。Windows + DirectML 没有 CUDA 那种
  "显存不足就抛 OOM" 的硬闸门 —— 显存不够时驱动会静默溢出到共享内存（任务管理器里
  那条一路涨的「共享 GPU 内存」），于是计算被拉成锯齿状，比老老实实分块慢得多。
  这里把 vae.encode(...) 临时换成 vae.encode_tiled(...)，只改这一点，其余
  （图片缩放尺寸、tokenize 模板、conditioning 键名、空 latent）全部走官方代码。

分块细节（tile_size / overlap / 模式）：
  - tile_size = 0 → 按当前可用显存自动挑（vae.memory_used_encode 估算），
    整幅装得进一块时自动退回官方整幅编码（比强行切块更快）。
  - overlap = 0 → 自动取 tile/8（下限 16，上限 128）。
  - 单遍(快)：官方 encode_tiled_ 默认会跑 3 遍不同切法再平均（3 倍开销），
    这里只跑 1 遍；官方三遍(稳)则保留官方行为。
"""

import re
import types

import torch

import comfy.model_management
import comfy.utils
import nodes

from ..core.nodes_reference_any import FlexibleOptionalInputType

_MODE_SINGLE = "单遍(快)"
_MODE_TRIPLE = "官方三遍(稳)"
_MODE_OPTIONS = [_MODE_SINGLE, _MODE_TRIPLE]

_TILE_CANDIDATES = (1024, 896, 768, 640, 512, 448, 384, 320, 256, 192, 128)

_MISSING = object()

_IMAGE_KEY = re.compile(r"image_(\d+)$")


def _pixel_hw(pixels):
    """返回像素空间的 (H, W)；兼容 [B,H,W,C] 与 [B,C,H,W]（含视频 5 维）。"""
    shape = tuple(pixels.shape)
    if len(shape) == 4:
        return (shape[1], shape[2]) if shape[-1] in (1, 3, 4) else (shape[2], shape[3])
    if len(shape) == 5:
        return (shape[2], shape[3]) if shape[-1] in (1, 3, 4) else (shape[3], shape[4])
    return None


def _auto_tile(vae, height, width):
    """按当前可用显存估算一块「装得下」的分块边长（像素）。

    自动模式上限 1MP（见 _TILE_CANDIDATES）：再大的单块在 Windows + A 卡上容易
    溢出到共享内存，反而比切块慢。整幅装得进这一块时调用方会直接走官方整幅编码。
    """
    try:
        budget = int(comfy.model_management.get_free_memory(vae.device) * 0.35)
        per_pixel = vae.memory_used_encode((1, 3, 512, 512), vae.vae_dtype) / (512.0 * 512.0)
    except Exception:
        return 512
    if budget <= 0 or per_pixel <= 0:
        return 512
    for tile in _TILE_CANDIDATES:
        if per_pixel * tile * tile <= budget:
            return tile
    return 256


def _single_pass_encode_tiled_(self, pixel_samples, tile_x=512, tile_y=512, overlap=64):
    """官方 VAE.encode_tiled_ 的单遍版本（去掉另外两遍不同切法的平均）。"""
    encode_fn = lambda a: self.first_stage_model.encode(
        (self.process_input(a)).to(self.vae_dtype).to(self.device)
    ).to(dtype=self.vae_output_dtype())
    return comfy.utils.tiled_scale(
        pixel_samples, encode_fn, tile_x, tile_y, overlap,
        upscale_amount=(1 / self.downscale_ratio),
        out_channels=self.latent_channels,
        output_device=self.output_device,
    )


class _TiledVAEContext:
    """临时把 vae.encode 换成「按块编码」，退出时原样还原。"""

    def __init__(self, vae, tile_size=0, overlap=0, tile_mode=_MODE_SINGLE, free_after=True):
        self.vae = vae
        self.tile_size = max(0, int(tile_size or 0))
        self.overlap = max(0, int(overlap or 0))
        self.single_pass = tile_mode != _MODE_TRIPLE
        self.free_after = bool(free_after)
        self.encode_calls = 0
        self.tiled_calls = 0
        self._restore = {}

    def __enter__(self):
        vae = self.vae
        if vae is None or not hasattr(vae, "encode_tiled"):
            return self

        ctx = self
        self._restore["encode"] = vae.__dict__.get("encode", _MISSING)
        if self.single_pass and hasattr(vae, "encode_tiled_"):
            self._restore["encode_tiled_"] = vae.__dict__.get("encode_tiled_", _MISSING)
            vae.encode_tiled_ = types.MethodType(_single_pass_encode_tiled_, vae)

        original = vae.encode

        def _chunked_encode(pixel_samples=None, *args, **kwargs):
            if not isinstance(pixel_samples, torch.Tensor):
                return original(pixel_samples, *args, **kwargs)
            ctx.encode_calls += 1
            hw = _pixel_hw(pixel_samples)
            if hw is None:
                return original(pixel_samples, *args, **kwargs)

            height, width = hw
            tile = ctx.tile_size or _auto_tile(vae, height, width)
            if height <= tile and width <= tile:
                return original(pixel_samples, *args, **kwargs)

            ctx.tiled_calls += 1
            overlap = ctx.overlap or max(16, min(128, tile // 8))
            print(f"\033[96m[XB 编码分块]\033[0m VAE 参考图 {height}×{width} → "
                  f"分块 {tile}px / 重叠 {overlap}px / {'单遍' if ctx.single_pass else '官方三遍'}",
                  flush=True)
            try:
                result = vae.encode_tiled(pixel_samples, tile_x=tile, tile_y=tile, overlap=overlap)
            except Exception as e:
                print(f"\033[93m[XB 编码分块 警告]\033[0m 分块编码失败，回退整幅：{e}", flush=True)
                result = original(pixel_samples, *args, **kwargs)
            if ctx.free_after:
                comfy.model_management.soft_empty_cache()
            return result

        vae.encode = _chunked_encode
        return self

    def __exit__(self, *exc_info):
        vae = self.vae
        if vae is not None:
            for name, value in self._restore.items():
                if value is _MISSING:
                    vae.__dict__.pop(name, None)
                else:
                    vae.__dict__[name] = value
        self._restore.clear()
        return False


def _collect_images(kwargs):
    """把 image_0 / images.image_3 这类动态输入收成官方需要的 {"image_N": tensor}。"""
    images = {}
    for key, value in kwargs.items():
        if not isinstance(value, torch.Tensor):
            continue
        match = _IMAGE_KEY.search(key)
        if match:
            images[f"image_{match.group(1)}"] = value
    return images


_OFFICIAL_SOURCES = {
    "MiniMaxH3ImageConditioning": ("comfy_extras.nodes_minimax_h3", "MiniMaxH3ImageConditioning"),
    "TextEncodeQwenImage21": ("comfy_extras.nodes_qwen", "TextEncodeQwenImage21"),
}
_CLASS_CACHE = {}


def _official_class(node_id):
    if node_id in _CLASS_CACHE:
        return _CLASS_CACHE[node_id]
    cls = None
    try:
        from nodes import NODE_CLASS_MAPPINGS
        cls = NODE_CLASS_MAPPINGS.get(node_id)
    except Exception:
        cls = None
    if cls is None:
        module_name, attr = _OFFICIAL_SOURCES[node_id]
        try:
            import importlib
            cls = getattr(importlib.import_module(module_name), attr, None)
        except Exception as e:
            print(f"\033[93m[XB 编码分块]\033[0m 找不到官方节点 {node_id}：{e}", flush=True)
    _CLASS_CACHE[node_id] = cls
    return cls


def _call_official(cls, kwargs):
    """调用官方节点（V3 io.ComfyNode 优先，兼容旧版 V1 类），返回普通元组。"""
    execute = getattr(cls, "execute", None)
    if callable(execute):
        result = execute(**kwargs)
        return tuple(getattr(result, "args", result))
    instance = cls()
    return getattr(instance, getattr(cls, "FUNCTION", "execute"))(**kwargs)


def _warn_if_unused(vae, images, tiler):
    """官方节点换了实现、不再走 vae.encode 时，至少让人看得见分块没生效。"""
    if vae is not None and images and tiler.encode_calls == 0:
        print("\033[93m[XB 编码分块]\033[0m 提示：官方节点本次没有调用 vae.encode（版本差异？），分块未生效",
              flush=True)


_TILE_WIDGETS = {
    "tile_size": ("INT", {"default": 0, "min": 0, "max": 4096, "step": 64,
                          "tooltip": "参考图 VAE 编码分块边长（像素）。0 = 按当前可用显存自动挑\n"
                                     "整幅装得进一块时不切，直接走官方整幅编码（更快）"}),
    "overlap": ("INT", {"default": 0, "min": 0, "max": 512, "step": 16,
                        "tooltip": "分块重叠像素，防止接缝。0 = 自动（tile/8，16~128）"}),
    "tile_mode": (_MODE_OPTIONS, {"default": _MODE_SINGLE,
                                  "tooltip": "单遍(快)=只切一遍（显存最低、速度最快）\n"
                                             "官方三遍(稳)=官方 encode_tiled_ 行为，跑 3 遍不同切法再平均（慢 3 倍）"}),
    "free_after": ("BOOLEAN", {"default": True,
                               "tooltip": "每张参考图编码完清一次显存缓存，避免图多了堆积"}),
}


class XB_MiniMaxH3ImageConditioningTiled:
    """MiniMax H3 图像条件化（分块）— 官方 MiniMaxH3ImageConditioning + 参考图 VAE 分块编码。"""

    @classmethod
    def INPUT_TYPES(cls):
        optional = {
            "vae": ("VAE", {"optional": True,
                            "tooltip": "MiniMax-H3-Image 的 VAE。接入后参考图才会额外锚成 reference latent；\n"
                                       "不接则只喂文本编码器的视觉塔"}),
            "image_0": ("IMAGE", {"optional": True,
                                  "tooltip": "参考图从 image_0 开始编号；接上一个自动长出下一个（image_1、image_2…）"}),
        }
        return {
            "required": {
                "clip": ("CLIP",),
                "prompt": ("STRING", {"multiline": True, "dynamicPrompts": True,
                                      "tooltip": "提示词里用 <Picture 1>、<Picture 2>… 指代参考图；image_0 是被编辑的那张"}),
                "width": ("INT", {"default": 0, "min": 0, "max": nodes.MAX_RESOLUTION, "step": 32,
                                  "tooltip": "0 = 用 image_0 参考缩放后的宽度（无图时 2048）。模型按 2048×2048 面积调优"}),
                "height": ("INT", {"default": 0, "min": 0, "max": nodes.MAX_RESOLUTION, "step": 32,
                                   "tooltip": "0 = 用 image_0 参考缩放后的高度（无图时 2048）"}),
                **_TILE_WIDGETS,
            },
            "optional": FlexibleOptionalInputType("IMAGE", optional),
        }

    RETURN_TYPES = ("CONDITIONING", "LATENT")
    RETURN_NAMES = ("positive", "latent")
    FUNCTION = "encode"
    CATEGORY = "XB_ToolBox/编码分块"

    def encode(self, clip, prompt, width, height,
               tile_size=0, overlap=0, tile_mode=_MODE_SINGLE, free_after=True,
               vae=None, **kwargs):
        official = _official_class("MiniMaxH3ImageConditioning")
        if official is None:
            raise RuntimeError(
                "未找到官方节点 MiniMaxH3ImageConditioning（需要 ComfyUI 支持 MiniMax-H3-Image 的版本）"
            )

        images = _collect_images(kwargs)
        tiler = _TiledVAEContext(vae, tile_size, overlap, tile_mode, free_after)
        with tiler:
            result = _call_official(official, {
                "clip": clip,
                "prompt": prompt,
                "width": width,
                "height": height,
                "vae": vae,
                "images": images,
            })
        _warn_if_unused(vae, images, tiler)
        return result


class XB_TextEncodeQwenImage21Tiled:
    """文本编码 Qwen Image 2.1（分块）— 官方 TextEncodeQwenImage21 + 参考图 VAE 分块编码。"""

    @classmethod
    def INPUT_TYPES(cls):
        optional = {
            "vae": ("VAE", {"optional": True,
                            "tooltip": "Qwen Image 2.1 的 VAE。接入后参考图会切成 reference latent 拼进序列；\n"
                                       "不接则参考图只进视觉塔"}),
            "image_1": ("IMAGE", {"optional": True,
                                  "tooltip": "参考图从 image_1 开始编号；接上一个自动长出下一个（image_2、image_3…）"}),
        }
        return {
            "required": {
                "clip": ("CLIP",),
                "prompt": ("STRING", {"multiline": True, "dynamicPrompts": True}),
                "negative_prompt": ("STRING", {"multiline": True, "dynamicPrompts": True, "default": ""}),
                "resolution": ("INT", {"default": 1024, "min": 0, "max": 4096, "step": 32,
                                       "tooltip": "参考图缩放到约 resolution×resolution（32 的倍数，保持比例）；\n"
                                                  "0 = 保持原尺寸（对齐到 32）"}),
                **_TILE_WIDGETS,
            },
            "optional": FlexibleOptionalInputType("IMAGE", optional),
        }

    RETURN_TYPES = ("CONDITIONING", "CONDITIONING", "LATENT")
    RETURN_NAMES = ("positive", "negative", "latent")
    FUNCTION = "encode"
    CATEGORY = "XB_ToolBox/编码分块"

    def encode(self, clip, prompt, negative_prompt, resolution=1024,
               tile_size=0, overlap=0, tile_mode=_MODE_SINGLE, free_after=True,
               vae=None, **kwargs):
        official = _official_class("TextEncodeQwenImage21")
        if official is None:
            raise RuntimeError(
                "未找到官方节点 TextEncodeQwenImage21（需要 ComfyUI 支持 Qwen Image 2.1 的版本）"
            )

        images = _collect_images(kwargs)
        tiler = _TiledVAEContext(vae, tile_size, overlap, tile_mode, free_after)
        with tiler:
            result = _call_official(official, {
                "clip": clip,
                "prompt": prompt,
                "negative_prompt": negative_prompt,
                "vae": vae,
                "resolution": resolution,
                "images": images,
            })
        _warn_if_unused(vae, images, tiler)
        return result
