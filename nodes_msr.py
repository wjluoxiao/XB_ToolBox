import torch
import comfy.utils


_SCALE_METHODS = ["lanczos", "bilinear", "bicubic", "nearest-exact", "area"]
_CROP_MODES = ["center", "disabled"]


class XB_MSR:
    """多图合成帧序列节点 - 纯 PyTorch 零损耗重构版"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "width": ("INT", {"default": 736, "min": 200, "max": 8192, "step": 32}),
                "height": ("INT", {"default": 1280, "min": 200, "max": 8192, "step": 32}),
                "frame_count": ("INT", {"default": 17, "min": 1, "max": 1024, "step": 1}),
                "scale_method": (_SCALE_METHODS, {"default": "lanczos"}),
                "crop_mode": (_CROP_MODES, {"default": "center"}),
            },
            "optional": {
                "img_1": ("IMAGE",),
                "img_2": ("IMAGE",),
                "img_3": ("IMAGE",),
                "img_4": ("IMAGE",),
                "background": ("IMAGE",),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("output",)
    FUNCTION = "create_video"
    CATEGORY = "XB_ToolBox/Image_Params"

    def create_video(self, width, height, frame_count, scale_method, crop_mode, **kwargs):
        # 1. 收集有效图像，统一取第一张为 [1, H, W, C]
        images = []
        for name in ("img_1", "img_2", "img_3", "img_4", "background"):
            img = kwargs.get(name)
            if img is not None:
                if img.ndim == 3:
                    img = img.unsqueeze(0)
                else:
                    img = img[0:1]
                images.append(img)

        if not images:
            raise ValueError("【XB_MSR 报错】至少需要连接一张图片输入！")

        # 2. 统一尺寸 — 纯 PyTorch，零损耗
        processed_frames = []
        for img in images:
            # [B, H, W, C] → [B, C, H, W] → upscale → [B, C, H', W'] → [B, H', W', C]
            img_moved = img.movedim(-1, 1)
            upscaled = comfy.utils.common_upscale(img_moved, width, height, scale_method, crop_mode)
            processed_frames.append(upscaled.movedim(1, -1))

        # 3. 按帧数分配并张量扩展
        base_count = frame_count // len(processed_frames)
        remainder = frame_count % len(processed_frames)

        final_frames = []
        for i, frame in enumerate(processed_frames):
            repeats = base_count + (1 if i < remainder else 0)
            if repeats > 0:
                final_frames.append(frame.repeat(repeats, 1, 1, 1))

        # 4. 一次 cat 完成拼接
        output = torch.cat(final_frames, dim=0)
        return (output,)


NODE_CLASS_MAPPINGS = {
    "XB_MSR": XB_MSR,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "XB_MSR": "XB-BOX - 🎞️ MSR 多图合成帧序列",
}
