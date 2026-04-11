import torch
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import gc

class XB_SamplerChunkMaster:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "model": ("MODEL",),
                "stat_mode": (["完整预览", "仅显示分块"], {"default": "完整预览"}),
                "tile_size": ("INT", {"default": 448, "min": 128, "max": 1024, "step": 32}),
                "tile_overlap": ("INT", {"default": 32, "min": 0, "max": 128, "step": 8}),
                "frame_chunk_size": ("INT", {"default": 17, "min": 1, "max": 129, "step": 8}),
                "frame_chunk_overlap": ("INT", {"default": 4, "min": 0, "max": 16, "step": 1}),
                "rocm_optimized": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "latent_info": ("LATENT",),
            }
        }

    RETURN_TYPES = ("MODEL", "IMAGE")
    RETURN_NAMES = ("model", "preview_image")
    FUNCTION = "apply_and_preview"
    CATEGORY = "小白工具箱/分块工具"

    def apply_and_preview(self, model, stat_mode, tile_size, tile_overlap, frame_chunk_size, frame_chunk_overlap, rocm_optimized, latent_info=None):
        # 🚨 架构级修复：绝对禁止使用 clone()！直接原地暴力注入，确保底层 C++/HIP 钩子能抓取到内存地址！
        model.model_options["wan_tile_size"] = tile_size
        model.model_options["wan_tile_overlap"] = tile_overlap
        model.model_options["wan_frame_chunk"] = frame_chunk_size
        model_copy = model # 返回原对象引用

        # 针对 ROCm 的激进策略适配
        if rocm_optimized:
            model.model_options["wan_frame_overlap"] = frame_chunk_overlap
            model.model_options["rocm_optimized"] = True
            
            # 🧹 执行分块注入前，强制进行一次深度垃圾回收，打破 PyTorch 显存缓存池假象
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect() # 针对多线程显存碎片

        # 📊 自动推算显示参数
        width = 1280
        height = 720
        total_frames = 81
        if latent_info and "samples" in latent_info:
            samples = latent_info["samples"]
            if len(samples.shape) == 5:
                total_frames = samples.shape[2]
                height = samples.shape[3] * 8
                width = samples.shape[4] * 8
            elif len(samples.shape) == 4:
                height = samples.shape[2] * 8
                width = samples.shape[3] * 8

        # 🎨 绘制高级可视化面板
        preview_img = self.draw_complex_preview(
            stat_mode, width, height, total_frames, 
            tile_size, tile_overlap, 
            frame_chunk_size, frame_chunk_overlap
        )

        return (model_copy, preview_img)

    def draw_complex_preview(self, mode, W, H, F, ts, to, cs, co):
        canvas_w = W + 300
        canvas_h = max(H + 100, 400)
        img = Image.new("RGBA", (canvas_w, canvas_h), (20, 20, 20, 255))
        draw = ImageDraw.Draw(img)
        
        stride = max(1, ts - to)
        rows = (H + stride - 1) // stride
        cols = (W + stride - 1) // stride
        
        colors = [(0, 255, 0), (0, 255, 255), (255, 255, 0), (255, 0, 255), (0, 150, 255)]
        
        for r in range(rows):
            for c in range(cols):
                color = colors[(r + c) % len(colors)]
                x1, y1 = c * stride, r * stride
                x2, y2 = min(x1 + ts, W), min(y1 + ts, H)
                draw.rectangle([x1, y1, x2, y2], outline=color, width=2)
                draw.text((x1+5, y1+5), f"S{r*cols+c+1}", fill=color)

        bar_x = W + 100
        draw.line([bar_x, 0, bar_x, H], fill=(100, 100, 100), width=2)
        
        t_stride = max(1, cs - co)
        t_steps = (F + t_stride - 1) // t_stride
        for i in range(t_steps):
            ty = (i * (H / max(1, t_steps)))
            color = colors[i % len(colors)]
            draw.ellipse([bar_x-30, ty, bar_x+30, ty+40], outline=color, width=2)
            draw.text((bar_x + 40, ty + 10), f"T{i+1}: Chunk", fill=color)

        img_np = np.array(img.convert("RGB")).astype(np.float32) / 255.0
        return torch.from_numpy(img_np).unsqueeze(0)