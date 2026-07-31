"""
XB-ToolBox FLUX多图编码节点
============================
套壳官方的 ResizeImagesByLongerEdge + VAEEncode + ReferenceLatent 串联。
"""

import node_helpers
import nodes
from comfy_extras.nodes_dataset import ResizeImagesByLongerEdgeNode


class XB_FluxMultiImageEncode:
    """FLUX多图编码 — 缩放→VAE编码→ReferenceLatent串联。
    VAE和图片1为必需，图片2/3可选接入。
    输出正面条件与负面条件（两个并行的ReferenceLatent链）。"""

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
            "optional": {
                "image2": ("IMAGE",),
                "image3": ("IMAGE",),
            },
        }

    RETURN_TYPES = ("CONDITIONING", "CONDITIONING")
    RETURN_NAMES = ("正面条件", "负面条件")
    FUNCTION = "encode"
    CATEGORY = "XB_ToolBox/FLUX"

    def encode(self, positive, negative, vae, image1, longer_edge, image2=None, image3=None):
        # ── 收集图片，缩放后 VAE 编码 ──
        latents = []
        for img in [image1, image2, image3]:
            if img is not None:
                # 官方 ResizeImagesByLongerEdge（缩放图像-长边）
                resized = ResizeImagesByLongerEdgeNode._process(img, longer_edge=longer_edge)
                # 官方 VAEEncode
                latent = nodes.VAEEncode().encode(vae, resized)[0]
                latents.append(latent)

        # ── 正面条件链（从输入的 positive 开始串联）──
        pos_cond = positive
        for lat in latents:
            pos_cond = node_helpers.conditioning_set_values(
                pos_cond, {"reference_latents": [lat["samples"]]}, append=True)

        # ── 负面条件链（从输入的 negative 开始串联）──
        neg_cond = negative
        for lat in latents:
            neg_cond = node_helpers.conditioning_set_values(
                neg_cond, {"reference_latents": [lat["samples"]]}, append=True)

        print(f"\033[92m[FLUX多图编码]\033[0m 图片数: {len(latents)} | 长边: {longer_edge}px")
        return (pos_cond, neg_cond)
