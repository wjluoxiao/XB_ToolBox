class XB_VideoParamsMaster:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                # ✅ 极简模式：大道至简的三分法
                "model_type": (["视频模式 (Video)", "图片模式 (Image)", "自由模式 (Free)"], {"default": "视频模式 (Video)"}),
                "aspect_ratio": (["自由 (Free)", "1:1", "16:9", "9:16", "4:3", "3:4", "21:9"], {"default": "自由 (Free)"}),
                
                "duration_display": ("STRING", {"default": "视频时长: 0.00 秒", "multiline": False}),
                "width": ("INT", {"default": 1024, "min": 64, "max": 8192, "step": 1}),
                "height": ("INT", {"default": 1024, "min": 64, "max": 8192, "step": 1}),
                "length": ("INT", {"default": 1, "min": 1, "max": 9999, "step": 1}),
                "fps": ("INT", {"default": 16, "min": 1, "max": 120, "step": 1}),
                "fps_float": ("FLOAT", {"default": 16.0, "min": 1.0, "max": 120.0, "step": 0.01}),
            }
        }

    # 👇 增加了一个 INT 类型的输出，名称为 "缩放尺寸"
    RETURN_TYPES = ("INT", "INT", "INT", "INT", "FLOAT", "INT")
    RETURN_NAMES = ("宽度", "高度", "总帧数", "帧率", "帧率_浮点", "缩放尺寸")
    FUNCTION = "process"
    CATEGORY = "小白工具箱/图像参数"

    def process(self, model_type, aspect_ratio, duration_display, width, height, length, fps, fps_float):
        # ==========================================
        # 1. 自由模式：原样输出，完全解封
        # ==========================================
        if "自由" in model_type:
            # 👇 返回值最后增加 max(width, height)
            return (width, height, length, int(round(fps)), float(fps), max(width, height))

        # ==========================================
        # 2. 视频模式的特殊守护：黄金档位强劫持
        # ==========================================
        if "视频" in model_type:
            golden_buckets = {
                "16:9": [(832, 480), (960, 544), (1280, 720), (1920, 1088)],
                "9:16": [(480, 832), (544, 960), (720, 1280), (1088, 1920)]
            }
            if aspect_ratio in golden_buckets:
                buckets = golden_buckets[aspect_ratio]
                # 寻找距离用户输入宽度最近的官方预设档位
                closest = min(buckets, key=lambda b: abs(b[0] - width))
                safe_w, safe_h = closest[0], closest[1]
                safe_len = max(1, ((length - 1) // 8) * 8 + 1)
                final_fps = int(round(fps))
                # 👇 返回值最后增加 max(safe_w, safe_h)
                return (safe_w, safe_h, safe_len, final_fps, float(final_fps), max(safe_w, safe_h))

        # ==========================================
        # 3. 图片及其他常规模式：16步长安全兜底
        # ==========================================
        step = 16
        safe_w = max(step, (width // step) * step)
        safe_h = max(step, (height // step) * step)
        
        if "图片" in model_type:
            safe_len = 1
        else:
            safe_len = max(1, ((length - 1) // 8) * 8 + 1)
            
        final_fps = int(round(fps))
        # 👇 返回值最后增加 max(safe_w, safe_h)
        return (safe_w, safe_h, safe_len, final_fps, float(final_fps), max(safe_w, safe_h))
