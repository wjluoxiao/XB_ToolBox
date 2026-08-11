"""
XB-ToolBox 批量图像节点
=========================
复刻官方 BatchImagesNode，所有图片输入可选。
上游被 mute/跳过的图片自动忽略，顺延读取后续有效图片。
"""

import torch
import comfy.utils
from .nodes_reference_any import FlexibleOptionalInputType

MAX_IMAGES = 50


def batch_images(images: list) -> torch.Tensor:
    """同官方：补齐通道 → 统一尺寸 → 合并。"""
    if len(images) == 0:
        raise ValueError("至少需要1张图片")

    # 补齐通道到最大值
    max_c = max(img.shape[-1] for img in images)
    padded = []
    for img in images:
        if img.shape[-1] < max_c:
            padded.append(torch.nn.functional.pad(img, (0, 1), mode='constant', value=1.0))
        else:
            padded.append(img)

    # 统一尺寸到第一张
    first = padded[0].shape
    resized = []
    for img in padded:
        if img.shape[1:] != first[1:]:
            r = comfy.utils.common_upscale(img.movedim(-1, 1), first[2], first[1], "bilinear", "center")
            resized.append(r.movedim(1, -1))
        else:
            resized.append(img)

    return torch.cat(resized, dim=0)


class XB_BatchImages:
    """批量图像 — 所有图片可选，自动跳过 mute/空输入。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {},
            "optional": FlexibleOptionalInputType("IMAGE", {
                "图片1": ("IMAGE", {"optional": True}),
            }),
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("图像",)
    FUNCTION = "batch"
    CATEGORY = "XB_ToolBox/Utils"

    def batch(self, **kwargs):
        # 收集所有有效图片（跳过 None/mute）
        images = []
        for k, v in kwargs.items():
            if v is not None and isinstance(v, torch.Tensor):
                images.append(v)

        if len(images) == 0:
            return (None,)

        return (batch_images(images),)
