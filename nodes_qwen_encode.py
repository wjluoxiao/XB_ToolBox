"""
XB-ToolBox Qwen 图像编辑编码节点
=================================
复刻官方 TextEncodeQwenImageEdit / TextEncodeQwenImageEditPlus。
转换为传统 ComfyUI 节点格式，图片输入动态增加（最多9张）。
"""

import node_helpers
import comfy.utils
import math
import torch
import nodes
from .nodes_reference_any import FlexibleOptionalInputType

LLAMA_TEMPLATE = (
    "<|im_start|>system\n"
    "Describe the key features of the input image (color, shape, size, texture, objects, background), "
    "then explain how the user's text instruction should alter or modify the image. "
    "Generate a new image that meets the user's requirements while maintaining consistency "
    "with the original input where appropriate.<|im_end|>\n"
    "<|im_start|>user\n"
    "{}<|im_end|>\n"
    "<|im_start|>assistant\n"
)


class XB_TextEncodeQwenImageEdit:
    """Qwen 图像编辑编码（基础版）— 图片输入动态扩展，最多9张。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "clip": ("CLIP",),
                "prompt": ("STRING", {"multiline": True, "dynamicPrompts": True}),
            },
            "optional": FlexibleOptionalInputType("IMAGE", {
                "vae": ("VAE", {"optional": True}),
                "image1": ("IMAGE", {"optional": True}),
            }),
        }

    RETURN_TYPES = ("CONDITIONING",)
    RETURN_NAMES = ("条件",)
    FUNCTION = "encode"
    CATEGORY = "XB_ToolBox/Qwen"

    def encode(self, clip, prompt, vae=None, image1=None, **kwargs):
        ref_latents = []
        images_vl = []

        # 收集图片
        imgs = [image1] + [v for k, v in kwargs.items() if v is not None and isinstance(v, torch.Tensor)]
        imgs = [i for i in imgs if i is not None]

        for img in imgs:
            samples = img.movedim(-1, 1)
            total = int(1024 * 1024)
            scale_by = math.sqrt(total / (samples.shape[3] * samples.shape[2]))
            width = round(samples.shape[3] * scale_by)
            height = round(samples.shape[2] * scale_by)
            s = comfy.utils.common_upscale(samples, width, height, "area", "disabled")
            img_resized = s.movedim(1, -1)
            images_vl.append(img_resized[:, :, :, :3])
            if vae is not None:
                ref_latents.append(vae.encode(img_resized[:, :, :, :3]))

        tokens = clip.tokenize(prompt, images=images_vl)
        conditioning = clip.encode_from_tokens_scheduled(tokens)
        if len(ref_latents) > 0:
            conditioning = node_helpers.conditioning_set_values(
                conditioning, {"reference_latents": ref_latents}, append=True)
        return (conditioning,)


class XB_TextEncodeQwenImageEditPlus:
    """Qwen 图像编辑编码（增强版）— 多图VL标记 + 动态图片槽位，最多9张。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "clip": ("CLIP",),
                "prompt": ("STRING", {"multiline": True, "dynamicPrompts": True}),
            },
            "optional": FlexibleOptionalInputType("IMAGE", {
                "vae": ("VAE", {"optional": True}),
                "image1": ("IMAGE", {"optional": True}),
            }),
        }

    RETURN_TYPES = ("CONDITIONING",)
    RETURN_NAMES = ("条件",)
    FUNCTION = "encode"
    CATEGORY = "XB_ToolBox/Qwen"

    def encode(self, clip, prompt, vae=None, image1=None, **kwargs):
        ref_latents = []
        images_vl = []

        # 收集图片
        imgs = [image1] + [v for k, v in kwargs.items() if v is not None and isinstance(v, torch.Tensor)]
        imgs = [i for i in imgs if i is not None]

        image_prompt = ""
        for i, image in enumerate(imgs):
            samples = image.movedim(-1, 1)

            # VL 尺寸 (384x384 区域)
            total = int(384 * 384)
            scale_by = math.sqrt(total / (samples.shape[3] * samples.shape[2]))
            width = round(samples.shape[3] * scale_by)
            height = round(samples.shape[2] * scale_by)
            s = comfy.utils.common_upscale(samples, width, height, "area", "disabled")
            images_vl.append(s.movedim(1, -1))

            # VAE 编码 (1024x1024 区域)
            if vae is not None:
                total = int(1024 * 1024)
                scale_by = math.sqrt(total / (samples.shape[3] * samples.shape[2]))
                width = round(samples.shape[3] * scale_by / 8.0) * 8
                height = round(samples.shape[2] * scale_by / 8.0) * 8
                s = comfy.utils.common_upscale(samples, width, height, "area", "disabled")
                ref_latents.append(vae.encode(s.movedim(1, -1)[:, :, :, :3]))

            image_prompt += "Picture {}: <|vision_start|><|image_pad|><|vision_end|>".format(i + 1)

        tokens = clip.tokenize(image_prompt + prompt, images=images_vl, llama_template=LLAMA_TEMPLATE)
        conditioning = clip.encode_from_tokens_scheduled(tokens)
        if len(ref_latents) > 0:
            conditioning = node_helpers.conditioning_set_values(
                conditioning, {"reference_latents": ref_latents}, append=True)
        return (conditioning,)
