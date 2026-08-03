"""
XB-ToolBox 批量缩放图像节点
=============================
复刻官方 ImageScale，支持动态输入/输出（最多9张）。
N进N出，共享缩放参数，每张独立处理，互不干扰。
"""

import comfy.utils
import nodes
from .nodes_reference_any import FlexibleOptionalInputType

MAX_IMAGES = 9


class XB_ImageScale:
    """批量缩放图像 — 动态输入/输出，N进N出。"""

    upscale_methods = ["nearest-exact", "bilinear", "area", "bicubic", "lanczos"]
    crop_methods = ["disabled", "center"]

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "upscale_method": (cls.upscale_methods,),
                "width": ("INT", {"default": 512, "min": 0, "max": nodes.MAX_RESOLUTION, "step": 1}),
                "height": ("INT", {"default": 512, "min": 0, "max": nodes.MAX_RESOLUTION, "step": 1}),
                "crop": (cls.crop_methods,),
                "image1": ("IMAGE",),
            },
            "optional": FlexibleOptionalInputType("IMAGE"),
        }

    RETURN_TYPES = ("IMAGE",) * MAX_IMAGES
    RETURN_NAMES = tuple(f"图像{i+1}" for i in range(MAX_IMAGES))
    FUNCTION = "upscale"
    CATEGORY = "XB_ToolBox/Utils"

    def upscale(self, upscale_method, width, height, crop, image1, **kwargs):
        # ── 收集所有图片 ──
        images = [image1]
        for key, value in kwargs.items():
            if value is not None and hasattr(value, 'movedim'):
                images.append(value)

        # ── 逐张缩放 ──
        results = []
        for img in images:
            if width == 0 and height == 0:
                results.append(img)
            else:
                samples = img.movedim(-1, 1)
                w, h = width, height
                if w == 0:
                    w = max(1, round(samples.shape[3] * h / samples.shape[2]))
                elif h == 0:
                    h = max(1, round(samples.shape[2] * w / samples.shape[3]))
                s = comfy.utils.common_upscale(samples, w, h, upscale_method, crop)
                results.append(s.movedim(1, -1))

        # ── 填充到 MAX_IMAGES 个输出 ──
        fallback = results[0] if results else image1
        while len(results) < MAX_IMAGES:
            results.append(fallback)

        return tuple(results)
