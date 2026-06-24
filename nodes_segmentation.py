"""
XB-ToolBox 人物分割节点 (ROCm/DirectML 优化)
============================================
完全独立，零外部节点依赖。使用 onnxruntime-directml 在 AMD 显卡上 GPU 运行。

配套节点:
  XB_HumanSegModelLoader  → 加载 ONNX 模型 (文件选择器)
  XB_HumanSegmentation    → 人物分割 (蒙版 + 抠图)

模型下载: https://huggingface.co/briaai/RMBG-1.4
放入: ComfyUI/models/rembg/u2net_human_seg.onnx
"""

import os
import numpy as np
import torch
import folder_paths


# 注册 rembg 模型文件夹
if "rembg" not in folder_paths.folder_names_and_paths:
    folder_paths.folder_names_and_paths["rembg"] = (
        [os.path.join(folder_paths.models_dir, "rembg")],
        {".onnx"}
    )


def _get_ort_session(model_path: str):
    """获取 ONNX Runtime 会话，优先 DirectML GPU，回退 CPU"""
    import onnxruntime as ort

    providers = ort.get_available_providers()
    if "DmlExecutionProvider" in providers:
        print(f"[XB-Seg] ✅ DirectML GPU 加速已启用")
        return ort.InferenceSession(model_path, providers=["DmlExecutionProvider"])
    elif "ROCMExecutionProvider" in providers:
        print(f"[XB-Seg] ✅ ROCm GPU 加速已启用")
        return ort.InferenceSession(model_path, providers=["ROCMExecutionProvider"])
    elif "CUDAExecutionProvider" in providers:
        print(f"[XB-Seg] ✅ CUDA GPU 加速已启用")
        return ort.InferenceSession(model_path, providers=["CUDAExecutionProvider"])
    else:
        print(f"[XB-Seg] ⚠️ 未检测到 GPU 加速器，使用 CPU (速度较慢)")
        return ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])


def _preprocess(image_bchw: torch.Tensor) -> np.ndarray:
    """[B, 3, 320, 320] → numpy, ImageNet 标准化"""
    mean = np.array([0.485, 0.456, 0.406], dtype=np.float32).reshape(1, 3, 1, 1)
    std = np.array([0.229, 0.224, 0.225], dtype=np.float32).reshape(1, 3, 1, 1)
    x = image_bchw.cpu().numpy().astype(np.float32)
    return (x - mean) / std


def _postprocess_batch(output: np.ndarray, orig_h: int, orig_w: int, device: torch.device) -> torch.Tensor:
    """ONNX 输出 [B, 1, 320, 320] → GPU 批量 resize 到 [B, H, W] mask，零 for 循环"""
    mask_tensor = torch.from_numpy(output).to(device)  # [B, 1, 320, 320]
    mask_resized = torch.nn.functional.interpolate(
        mask_tensor, size=(orig_h, orig_w), mode="bilinear", align_corners=False
    )
    return torch.clamp(mask_resized.squeeze(1), 0, 1)  # [B, H, W]


# ============================================================
# XB_HumanSegModelLoader — 人物分割模型加载器
# ============================================================
class XB_HumanSegModelLoader:
    """加载 u2net ONNX 模型，输出给分割节点使用"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": (folder_paths.get_filename_list("rembg"),),
            }
        }

    RETURN_TYPES = ("XB_HUMANSEG_MODEL",)
    RETURN_NAMES = ("分割模型",)
    FUNCTION = "load"
    CATEGORY = "XB_ToolBox/Segment"

    def load(self, model: str):
        model_path = folder_paths.get_full_path_or_raise("rembg", model)
        session = _get_ort_session(model_path)
        print(f"[XB-Seg] 已加载: {model}")
        return (session,)


# ============================================================
# XB_HumanSegmentation — 人物分割
# ============================================================
class XB_HumanSegmentation:
    """输入图像 + 分割模型，输出人物蒙版和抠图"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "seg_model": ("XB_HUMANSEG_MODEL",),
                "image": ("IMAGE",),
            }
        }

    RETURN_TYPES = ("MASK", "IMAGE")
    RETURN_NAMES = ("人物蒙版", "人物抠图")
    FUNCTION = "segment"
    CATEGORY = "XB_ToolBox/Segment"

    def segment(self, seg_model, image: torch.Tensor):
        """
        seg_model: onnxruntime.InferenceSession
        image: [B, H, W, C] float32 [0, 1]
        """
        session = seg_model
        B, orig_h, orig_w, C = image.shape

        # --- 1. 预处理: resize 到 320x320，BCHW ---
        img_bchw = image.permute(0, 3, 1, 2)  # [B, C, H, W]
        img_bchw = torch.nn.functional.interpolate(
            img_bchw, size=(320, 320), mode="bilinear", align_corners=False
        )
        inp = _preprocess(img_bchw)  # numpy [B, 3, 320, 320]

        # --- 2. ONNX 推理 ---
        ort_inputs = {session.get_inputs()[0].name: inp}
        ort_outputs = session.run(None, ort_inputs)
        mask_np = ort_outputs[0]  # [B, 1, 320, 320]

        # --- 3. 纯 GPU 批量后处理（一行替代 81 次 OpenCV for 循环）---
        mask_stack = _postprocess_batch(mask_np, orig_h, orig_w, image.device)  # [B, H, W]
        cutout_stack = image * mask_stack.unsqueeze(-1)  # [B, H, W, C] 广播

        return (mask_stack, cutout_stack)


__all__ = ["XB_HumanSegModelLoader", "XB_HumanSegmentation"]
