class XB_ImageParamsMaster:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "aspect_ratio": (["自由 (Free)", "1:1", "16:9", "9:16", "4:3", "3:4", "21:9"], {"default": "自由 (Free)"}),
                "width": ("INT", {"default": 1024, "min": 64, "max": 8192, "step": 1}),
                "height": ("INT", {"default": 1024, "min": 64, "max": 8192, "step": 1}),
                "batch_size": ("INT", {"default": 1, "min": 1, "max": 1000, "step": 1}),
                "strength_float": ("FLOAT", {"default": 1.00, "min": 0.00, "max": 10.00, "step": 0.01}),
                "strength_int": ("INT", {"default": 1, "min": 0, "max": 1000, "step": 1}),
            }
        }

    RETURN_TYPES = ("INT", "INT", "INT", "FLOAT", "INT", "INT")
    RETURN_NAMES = ("图片宽度", "图片高度", "生成数量", "浮点控制", "整数控制", "缩放尺寸")
    FUNCTION = "process"
    CATEGORY = "小白工具箱/图像参数"

    def process(self, aspect_ratio, width, height, batch_size, strength_float, strength_int):
        if "自由" in aspect_ratio:
            return (width, height, batch_size, float(strength_float), int(strength_int), max(width, height))

        step = 16
        safe_w = max(step, (width // step) * step)
        safe_h = max(step, (height // step) * step)
        
        return (safe_w, safe_h, batch_size, float(strength_float), int(strength_int), max(safe_w, safe_h))


class XB_VideoParamsMaster:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "aspect_ratio": (["自由 (Free)", "1:1", "16:9", "9:16", "4:3", "3:4", "21:9"], {"default": "自由 (Free)"}),
                "duration_display": ("STRING", {"default": "视频时长: 0.00 秒", "multiline": False}),
                "width": ("INT", {"default": 480, "min": 64, "max": 8192, "step": 1}),
                "height": ("INT", {"default": 832, "min": 64, "max": 8192, "step": 1}),
                "length": ("INT", {"default": 81, "min": 1, "max": 9999, "step": 1}),
                "fps": ("INT", {"default": 16, "min": 1, "max": 120, "step": 1}),
                "fps_float": ("FLOAT", {"default": 16.0, "min": 1.0, "max": 120.0, "step": 0.01}),
            }
        }

    RETURN_TYPES = ("INT", "INT", "INT", "INT", "FLOAT", "INT")
    RETURN_NAMES = ("宽度", "高度", "帧数", "帧率", "帧率_浮点", "缩放尺寸")
    FUNCTION = "process"
    CATEGORY = "小白工具箱/图像参数"

    def process(self, aspect_ratio, duration_display, width, height, length, fps, fps_float):
        if "自由" in aspect_ratio:
            return (width, height, length, int(round(fps)), float(fps), max(width, height))

        golden_buckets = {
            "16:9": [(832, 480), (960, 544), (1280, 720), (1920, 1088)],
            "9:16": [(480, 832), (544, 960), (720, 1280), (1088, 1920)]
        }
        
        if aspect_ratio in golden_buckets:
            buckets = golden_buckets[aspect_ratio]
            closest = min(buckets, key=lambda b: abs(b[0] - width))
            safe_w, safe_h = closest[0], closest[1]
        else:
            step = 16
            safe_w = max(step, (width // step) * step)
            safe_h = max(step, (height // step) * step)

        safe_len = max(1, ((length - 1) // 8) * 8 + 1)
        final_fps = int(round(fps))
        
        return (safe_w, safe_h, safe_len, final_fps, float(final_fps), max(safe_w, safe_h))


# ==========================================
# 🎛️ 新增：全能参数控制节点
# ==========================================
class XB_MasterParameter:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "mode": (["自由模式", "模型模式", "编码模式", "解码模式", "比例模式", "其他模式"], {"default": "自由模式"}),
                # 🟢 恢复最纯正的 0-9999 范围，默认步长 0.01
                "value": ("FLOAT", {"default": 1024.0, "min": 0.0, "max": 9999.0, "step": 0.01}),
            }
        }

    RETURN_TYPES = ("INT", "FLOAT")
    RETURN_NAMES = ("整数 (INT)", "浮点 (FLOAT)")
    FUNCTION = "get_value"
    CATEGORY = "小白工具箱/参数控制"

    def get_value(self, mode, value):
        if mode == "自由模式":
            val = max(0.0, min(9999.0, value))
        elif mode == "模型模式":
            val = max(0.0, min(50.0, value))
        elif mode in ["编码模式", "解码模式"]:
            val = max(64.0, min(3840.0, value))
            val = round(val / 32) * 32
        elif mode == "比例模式":
            val = max(0.0, min(1.0, value))
        elif mode == "其他模式":
            val = max(0.0, min(9999.0, value))
        else:
            val = value

        return (int(round(val)), float(val))