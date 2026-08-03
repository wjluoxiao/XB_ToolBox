"""
XB-ToolBox FLUX多图编码节点
============================
套壳官方的 ResizeImagesByLongerEdge + VAEEncode + ReferenceLatent 串联。
图片输入动态增加：默认1个，接入后自动新增（最多9个）。
"""

import node_helpers
import nodes
from comfy_extras.nodes_dataset import ResizeImagesByLongerEdgeNode
from .nodes_reference_any import FlexibleOptionalInputType


class XB_FluxMultiImageEncode:
    """FLUX多图编码 — 缩放→VAE编码→ReferenceLatent串联。
    图片输入动态扩展（最多9张），其他逻辑不变。"""

    MAX_IMAGES = 9

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "positive": ("CONDITIONING",),
                "negative": ("CONDITIONING",),
                "vae": ("VAE",),
                "image1": ("IMAGE",),
                "longer_edge": ("INT", {"default": 1024, "min": 64, "max": 8192, "step": 64}),
            },
            "optional": FlexibleOptionalInputType("IMAGE"),
        }

    RETURN_TYPES = ("CONDITIONING", "CONDITIONING")
    RETURN_NAMES = ("正面条件", "负面条件")
    FUNCTION = "encode"
    CATEGORY = "XB_ToolBox/FLUX"

    def encode(self, positive, negative, vae, image1, longer_edge, **kwargs):
        # ── 收集图片（image1 + 动态槽位）──
        images = [image1]
        for key, value in kwargs.items():
            if value is not None and key != "longer_edge":
                images.append(value)

        # ── 缩放 → VAE编码 ──
        latents = []
        for img in images:
            resized = ResizeImagesByLongerEdgeNode._process(img, longer_edge=longer_edge)
            latent = nodes.VAEEncode().encode(vae, resized)[0]
            latents.append(latent)

        # ── 正面条件链 ──
        pos_cond = positive
        for lat in latents:
            pos_cond = node_helpers.conditioning_set_values(
                pos_cond, {"reference_latents": [lat["samples"]]}, append=True)

        # ── 负面条件链 ──
        neg_cond = negative
        for lat in latents:
            neg_cond = node_helpers.conditioning_set_values(
                neg_cond, {"reference_latents": [lat["samples"]]}, append=True)

        print(f"\033[92m[FLUX多图编码]\033[0m 图片数: {len(latents)} | 长边: {longer_edge}px")
        return (pos_cond, neg_cond)
