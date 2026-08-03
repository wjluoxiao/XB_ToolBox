"""
XB-ToolBox 海螺H3视频参数节点
==============================
分辨率公式复刻官方 ResolutionSelector（MP×1024² → sqrt → round/multiple）。
时间调节（步长0.5秒），帧数自动推算。
"""

import math
import nodes

ASPECT_RATIOS = {
    "1:1 (Square)":             (1, 1),
    "2:3 (Portrait Photo)":     (2, 3),
    "3:2 (Photo)":              (3, 2),
    "3:4 (Portrait Standard)":  (3, 4),
    "4:3 (Standard)":           (4, 3),
    "9:16 (Portrait Widescreen)": (9, 16),
    "16:9 (Widescreen)":        (16, 9),
    "21:9 (Ultrawide)":         (21, 9),
}


class XB_HailuoH3VideoParams:
    """海螺H3视频参数 — ResolutionSelector 分辨率公式 + 时间控制。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "aspect_ratio": (list(ASPECT_RATIOS.keys()), {"default": "16:9 (Widescreen)"}),
                "megapixels": ("FLOAT", {"default": 1.0, "min": 0.1, "max": 16.0, "step": 0.1}),
                "multiple": ("INT", {"default": 16, "min": 8, "max": 128, "step": 4}),
                "frames_display": ("STRING", {"default": "Frames: 0", "multiline": False}),
                "duration": ("FLOAT", {"default": 3.0, "min": 1.0, "max": 300.0, "step": 1.0}),
                "fps": ("INT", {"default": 16, "min": 1, "max": 120, "step": 1}),
                "fps_float": ("FLOAT", {"default": 16.0, "min": 1.0, "max": 120.0, "step": 0.01}),
            }
        }

    RETURN_TYPES = ("INT", "INT", "INT", "INT", "FLOAT", "INT")
    RETURN_NAMES = ("Width", "Height", "Frames", "FPS", "FPS_Float", "Scale Size")
    FUNCTION = "process"
    CATEGORY = "XB_ToolBox/Image_Params"

    def process(self, aspect_ratio, megapixels, multiple, frames_display, duration, fps, fps_float):
        final_fps = int(round(fps))

        # ── 分辨率：官方 ResolutionSelector 公式 ──
        w_ratio, h_ratio = ASPECT_RATIOS.get(aspect_ratio, (16, 9))
        total_pixels = megapixels * 1024 * 1024
        scale = math.sqrt(total_pixels / (w_ratio * h_ratio))
        safe_w = round(w_ratio * scale / multiple) * multiple
        safe_h = round(h_ratio * scale / multiple) * multiple

        # ── 时间 → 帧数换算 ──
        base = max(5, round(duration * 24))
        safe_len = base + (5 - (base % 17)) % 17

        return (safe_w, safe_h, safe_len, final_fps, float(final_fps), max(safe_w, safe_h))
