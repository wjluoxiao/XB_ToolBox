# ============================================================
# XB_ImageParamsMaster — 图像参数主控
# ============================================================
class XB_ImageParamsMaster:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "aspect_ratio": (["Free", "1:1", "16:9", "9:16", "4:3", "3:4", "21:9"], {"default": "Free"}),
                "width": ("INT", {"default": 1024, "min": 64, "max": 8192, "step": 1}),
                "height": ("INT", {"default": 1024, "min": 64, "max": 8192, "step": 1}),
                "batch_size": ("INT", {"default": 1, "min": 1, "max": 1000, "step": 1}),
                "strength_float": ("FLOAT", {"default": 1.00, "min": 0.00, "max": 10.00, "step": 0.01}),
                "strength_int": ("INT", {"default": 1, "min": 0, "max": 1000, "step": 1}),
            }
        }

    RETURN_TYPES = ("INT", "INT", "INT", "FLOAT", "INT", "INT")
    RETURN_NAMES = ("Image Width", "Image Height", "Batch Size", "Float Control", "Int Control", "Scale Size")
    FUNCTION = "process"
    CATEGORY = "XB_ToolBox/Image_Params"

    def process(self, aspect_ratio, width, height, batch_size, strength_float, strength_int):
        if "Free" in aspect_ratio:
            return (width, height, batch_size, float(strength_float), int(strength_int), max(width, height))

        # 解析宽高比约束，使用 round() 而非 // 避免累积误差
        ratio_map = {"1:1": 1.0, "16:9": 16/9, "9:16": 9/16, "4:3": 4/3, "3:4": 3/4, "21:9": 21/9}
        target_ratio = ratio_map.get(aspect_ratio, 1.0)
        step = 16

        if width >= height:
            safe_w = max(step, round(width / step) * step)
            safe_h = max(step, round((safe_w / target_ratio) / step) * step)
        else:
            safe_h = max(step, round(height / step) * step)
            safe_w = max(step, round((safe_h * target_ratio) / step) * step)

        return (safe_w, safe_h, batch_size, float(strength_float), int(strength_int), max(safe_w, safe_h))

# ============================================================
# XB_VideoParamsMaster — 视频参数主控
# ============================================================
class XB_VideoParamsMaster:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "aspect_ratio": (["Free", "1:1", "16:9", "9:16", "4:3", "3:4", "21:9", "16:9 (LTX)", "9:16 (LTX)", "4:3 (LTX)", "3:4 (LTX)"], {"default": "Free"}),
                "duration_display": ("STRING", {"default": "Video Duration: 0.00 s", "multiline": False}),
                "width": ("INT", {"default": 480, "min": 64, "max": 8192, "step": 1}),
                "height": ("INT", {"default": 832, "min": 64, "max": 8192, "step": 1}),
                "length": ("INT", {"default": 81, "min": 1, "max": 9999, "step": 1}),
                "fps": ("INT", {"default": 16, "min": 1, "max": 120, "step": 1}),
                "fps_float": ("FLOAT", {"default": 16.0, "min": 1.0, "max": 120.0, "step": 0.01}),
            }
        }

    RETURN_TYPES = ("INT", "INT", "INT", "INT", "FLOAT", "INT")
    RETURN_NAMES = ("Width", "Height", "Frames", "FPS", "FPS_Float", "Scale Size")
    FUNCTION = "process"
    CATEGORY = "XB_ToolBox/Image_Params"

    def process(self, aspect_ratio, duration_display, width, height, length, fps, fps_float):
        final_fps = int(round(fps))

        if "Free" in aspect_ratio:
            return (width, height, length, final_fps, float(final_fps), max(width, height))

        golden_buckets = {
            "16:9": [(832, 480), (960, 544), (1280, 720), (1920, 1088)],
            "9:16": [(480, 832), (544, 960), (720, 1280), (1088, 1920)]
        }
        
        if aspect_ratio in golden_buckets:
            buckets = golden_buckets[aspect_ratio]
            closest = min(buckets, key=lambda b: abs(b[0] - width))
            safe_w, safe_h = closest[0], closest[1]
        elif "LTX" in aspect_ratio:
            # LTX 模式使用 step=32
            step = 32
            ratio_map = {"16:9 (LTX)": 16/9, "9:16 (LTX)": 9/16, "4:3 (LTX)": 4/3, "3:4 (LTX)": 3/4}
            target_ratio = ratio_map.get(aspect_ratio, 16/9)
            if width >= height:
                safe_w = max(step, round(width / step) * step)
                safe_h = max(step, round((safe_w / target_ratio) / step) * step)
            else:
                safe_h = max(step, round(height / step) * step)
                safe_w = max(step, round((safe_h * target_ratio) / step) * step)
        else:
            # 解析宽高比并强制约束，使用 round() 避免累积误差
            step = 16
            ratio_map = {"1:1": 1.0, "4:3": 4/3, "3:4": 3/4, "21:9": 21/9}
            target_ratio = ratio_map.get(aspect_ratio, 1.0)
            if width >= height:
                safe_w = max(step, round(width / step) * step)
                safe_h = max(step, round((safe_w / target_ratio) / step) * step)
            else:
                safe_h = max(step, round(height / step) * step)
                safe_w = max(step, round((safe_h * target_ratio) / step) * step)

        safe_len = max(1, round((length - 1) / 8) * 8 + 1)

        return (safe_w, safe_h, safe_len, final_fps, float(final_fps), max(safe_w, safe_h))

# ============================================================
# XB_MasterParameter — 万能参数控制器
# ============================================================
class XB_MasterParameter:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "mode": (["Free Mode", "Model Mode", "Encode Mode", "Decode Mode", "Ratio Mode", "Other Mode"], {"default": "Free Mode"}),
                "value": ("FLOAT", {"default": 1024.0, "min": 0.0, "max": 9999.0, "step": 0.01}),
            }
        }

    RETURN_TYPES = ("INT", "FLOAT")
    RETURN_NAMES = ("Integer (INT)", "Float (FLOAT)")
    FUNCTION = "get_value"
    CATEGORY = "XB_ToolBox/Params_Control"

    def get_value(self, mode, value):
        if mode == "Free Mode":
            val = max(0.0, min(9999.0, value))
        elif mode == "Model Mode":
            val = max(0.0, min(50.0, value))
        elif mode in ["Encode Mode", "Decode Mode"]:
            val = max(64.0, min(3840.0, value))
            val = round(val / 32) * 32
        elif mode == "Ratio Mode":
            val = max(0.0, min(1.0, value))
        elif mode == "Other Mode":
            val = max(0.0, min(9999.0, value))
        else:
            val = value

        return (int(round(val)), float(val))