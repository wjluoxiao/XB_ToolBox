import torch
import numpy as np
import os
from PIL import Image, ImageDraw, ImageFont

class CalculatedFloat(float):
    pass

# ============================================================
# XB_VRAM_Calculator — 显存计算器
# ============================================================
class XB_VRAM_Calculator:
    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "Total_VRAM_GB": ("INT", {"default": 24, "min": 4, "max": 128, "step": 1, "display": "number"}),
                "System_Overhead_GB": ("FLOAT", {"default": 2.0, "min": 0.0, "max": 64.0, "step": 0.5, "display": "number"}),
                "Main_Video_Model": (["LTX-2.3 (22B)", "WAN2.2-I2V (14B)", "WAN2.2-T2V (14B)", "WAN2.2-Animate (14B)"], {"default": "LTX-2.3 (22B)"}),
                "Model_Quantization": (["FP16/BF16", "FP8", "GGUF-Q8", "GGUF-Q6", "GGUF-Q4"], {"default": "FP8"}),
                "Total_Model_Layers": ("INT", {"default": 48, "min": 1, "max": 200, "step": 1, "display": "number"}),
                "Layers_to_Swap": ("INT", {"default": 0, "min": 0, "max": 200, "step": 1, "display": "number"}),
                "LoRA_Plugin_VRAM_GB": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 64.0, "step": 0.1, "display": "number"}),
            }
        }

    RETURN_TYPES = ("FLOAT",)
    RETURN_NAMES = ("Available_VRAM",)
    FUNCTION = "calculate_vram"
    CATEGORY = "XB_ToolBox/Chunk_Preview"

    def calculate_vram(self, Total_VRAM_GB, System_Overhead_GB, Main_Video_Model, Model_Quantization, Total_Model_Layers, Layers_to_Swap, LoRA_Plugin_VRAM_GB):
        vram_map = {
            "LTX-2.3 (22B)": {"FP16/BF16": 44.0, "FP8": 22.5, "GGUF-Q8": 22.8, "GGUF-Q6": 17.8, "GGUF-Q4": 13.5},
            "WAN2.2-I2V (14B)": {"FP16/BF16": 28.0, "FP8": 14.0, "GGUF-Q8": 14.5, "GGUF-Q6": 11.0, "GGUF-Q4": 9.0},
            "WAN2.2-T2V (14B)": {"FP16/BF16": 28.0, "FP8": 14.0, "GGUF-Q8": 14.5, "GGUF-Q6": 11.0, "GGUF-Q4": 9.0},
            "WAN2.2-Animate (14B)": {"FP16/BF16": 28.0, "FP8": 14.0, "GGUF-Q8": 14.5, "GGUF-Q6": 11.0, "GGUF-Q4": 9.0},
        }
        
        full_model_size = vram_map.get(Main_Video_Model, {}).get(Model_Quantization, 14.0)
        stay_layers = max(0, Total_Model_Layers - Layers_to_Swap)
        active_model_vram = (full_model_size / max(1, Total_Model_Layers)) * stay_layers
        available_vram = Total_VRAM_GB - System_Overhead_GB - active_model_vram - LoRA_Plugin_VRAM_GB
        available_vram = max(0.1, available_vram)
        
        res = CalculatedFloat(available_vram)
        res._stay = stay_layers
        res._total = Total_Model_Layers
        
        return (res,)

# ============================================================
# XB_ChunkVisualization — 分块可视化
# ============================================================
class XB_ChunkVisualization:
    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "Stat_Mode": (["Spatial Only", "Temporal Only", "Spatial & Temporal"], {"default": "Spatial & Temporal"}),
                "Available_VRAM_GB": ("FLOAT", {"default": 12.0, "min": 0.1, "max": 128.0, "step": 0.1, "display": "number"}),
                "Image_Width": ("INT", {"default": 1024, "min": 64, "max": 8192, "step": 16, "display": "number"}),
                "Image_Height": ("INT", {"default": 1024, "min": 64, "max": 8192, "step": 16, "display": "number"}),
                "Image_Frames": ("INT", {"default": 1, "min": 1, "max": 10000, "step": 4, "display": "number"}),
                "Current_Stage": (["Encode Stage", "Decode Stage"], {"default": "Decode Stage"}),
                "Spatial_Tile_Size": ("INT", {"default": 512, "min": 64, "max": 8192, "step": 32, "display": "number"}),
                "Spatial_Tile_Overlap": ("INT", {"default": 64, "min": 0, "max": 4096, "step": 32, "display": "number"}),
                "Temporal_Chunk_Size": ("INT", {"default": 33, "min": 8, "max": 10000, "step": 4, "display": "number"}),
                "Temporal_Chunk_Overlap": ("INT", {"default": 4, "min": 0, "max": 1000, "step": 4, "display": "number"}),
            },
            "optional": { 
                "Image_Input": ("IMAGE",) 
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("preview_image",)
    FUNCTION = "visualize_chunks"
    CATEGORY = "XB_ToolBox"

    def get_1d_chunks(self, total_len, chunk_size, overlap):
        chunks = []
        if chunk_size <= 0: return [(0, total_len)]
        stride = max(1, chunk_size - min(overlap, int(chunk_size * 0.9)))
        curr = 0
        while curr < total_len:
            start, end = curr, min(curr + chunk_size, total_len)
            chunks.append((start, end))
            if end >= total_len: break
            curr += stride
        return chunks

    def visualize_chunks(self, Stat_Mode, Available_VRAM_GB, Image_Width, Image_Height, Image_Frames, Current_Stage, 
                         Spatial_Tile_Size, Spatial_Tile_Overlap, Temporal_Chunk_Size, Temporal_Chunk_Overlap, Image_Input=None):
        
        active_vram = float(Available_VRAM_GB)
        is_calc = type(Available_VRAM_GB).__name__ == "CalculatedFloat"
        stay_info = f" (Reside:{Available_VRAM_GB._stay}/{Available_VRAM_GB._total}L)" if (is_calc and hasattr(Available_VRAM_GB, '_stay')) else ""

        if Image_Input is not None:
            B, H_orig, W_orig, C = Image_Input.shape
            source_img = Image.fromarray((Image_Input[0].cpu().numpy() * 255).astype(np.uint8)).convert("RGBA")
            res_info = f"[Size]: {W_orig}x{H_orig} (Input)"
        else:
            W_orig, H_orig = Image_Width, Image_Height
            source_img = Image.new("RGBA", (W_orig, H_orig), (25, 25, 25, 255))
            res_info = f"[Size]: {W_orig}x{H_orig} (Param)"

        x_chunks = self.get_1d_chunks(W_orig, Spatial_Tile_Size if "Spatial" in Stat_Mode else 0, Spatial_Tile_Overlap)
        y_chunks = self.get_1d_chunks(H_orig, Spatial_Tile_Size if "Spatial" in Stat_Mode else 0, Spatial_Tile_Overlap)
        t_chunks = self.get_1d_chunks(Image_Frames, Temporal_Chunk_Size if "Temporal" in Stat_Mode else 0, Temporal_Chunk_Overlap)
        total_batches = len(x_chunks) * len(y_chunks) * len(t_chunks)
        
        base_vol = W_orig * H_orig * Image_Frames
        real_vol, max_chunk_vol = 0, 0
        for x1, x2 in x_chunks:
            for y1, y2 in y_chunks:
                for t1, t2 in t_chunks:
                    v = (x2-x1)*(y2-y1)*(t2-t1)
                    real_vol += v
                    max_chunk_vol = max(max_chunk_vol, v)

        redundancy = ((real_vol - base_vol) / base_vol * 100) if base_vol > 0 else 0
        
        safe_unit = active_vram * 5_000_000 
        kappa = (max_chunk_vol / max(1, safe_unit)) ** 1.15
        p_percent = min(100, (kappa / 2.0) * 100)
        p_color = (0, 255, 0) if p_percent < 60 else ((255, 200, 0) if p_percent < 85 else (255, 50, 50))

        def get_font(size):
            font_paths = [
                # Windows
                os.path.join(os.environ.get('WINDIR', 'C:/Windows'), "Fonts", "msyh.ttc"),
                os.path.join(os.environ.get('WINDIR', 'C:/Windows'), "Fonts", "simhei.ttf"),
                # Linux
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
                # macOS
                "/System/Library/Fonts/STHeiti Medium.ttc",
                "/System/Library/Fonts/Helvetica.ttc",
            ]
            for p in font_paths:
                if os.path.exists(p):
                    try:
                        return ImageFont.truetype(p, size)
                    except Exception:
                        continue
            return ImageFont.load_default()
        
        f_info = get_font(22)
        f_num = get_font(28) 
        temp_draw = ImageDraw.Draw(Image.new("RGBA", (1,1)))

        show_time = ("Temporal" in Stat_Mode and Image_Frames > 1)
        sidebar_w = 250 if show_time else 0
        gap = 50 if show_time else 0
        padding = 70 
        
        draw_W = W_orig + gap + sidebar_w
        new_W = max(draw_W + 80, 700) 
        max_txt_w = new_W - 50

        info_cats = [
            {"text": f"[Mode]: {Stat_Mode}  /  [Stage]: {Current_Stage}", "color": (0, 255, 255)},
            {"text": res_info, "color": (220, 220, 220)},
            {"text": f"[Batches]: {total_batches} (S:{len(x_chunks)*len(y_chunks)} x T:{len(t_chunks)})", "color": (255, 255, 255)},
            {"text": f"[VRAM]: {active_vram:.1f}G{stay_info}", "color": (150, 200, 255)},
            {"text": f"[Volume]: {real_vol/1e6:.1f}M (Base:{base_vol/1e6:.1f}M | Redundancy:+{redundancy:.1f}%)", "color": (255, 150, 200)},
            {"text": f"[Chunk]: {max_chunk_vol/1e6:.1f}M/b  /  [Pressure]: {kappa:.2f}", "color": p_color}
        ]

        final_lines = []
        for cat in info_cats:
            prefix, content = cat["text"].split("]: ", 1) if "]: " in cat["text"] else ("", cat["text"])
            if prefix: prefix += "]: "
            prefix_w = int(temp_draw.textlength(prefix, font=f_info))
            curr, is_first = "", True
            for char in content:
                limit = max_txt_w if is_first else (max_txt_w - prefix_w)
                if temp_draw.textlength(curr + char, font=f_info) <= limit: 
                    curr += char
                else:
                    final_lines.append((prefix + curr if is_first else curr, cat["color"], 0 if is_first else prefix_w))
                    curr, is_first = char, False
            if curr: 
                final_lines.append((prefix + curr if is_first else curr, cat["color"], 0 if is_first else prefix_w))

        line_h = 36
        header_H = len(final_lines) * line_h + 80
        
        paste_x = int((new_W - draw_W) / 2)
        paste_y = header_H + padding
        
        full_canvas = Image.new("RGBA", (int(new_W), int(paste_y + H_orig + 40)), (20, 20, 20, 255))
        
        if Stat_Mode != "Temporal Only":
            full_canvas.paste(source_img, (paste_x, paste_y))
        else:
            faded = source_img.copy()
            faded.putalpha(60)
            full_canvas.paste(faded, (paste_x, paste_y), faded)

        draw = ImageDraw.Draw(full_canvas, "RGBA")
        
        y = 15
        for txt, clr, x_off in final_lines:
            draw.text((25 + x_off, y), txt, fill=clr, font=f_info)
            y += line_h
            
        draw.rounded_rectangle([25, y+10, 525, y+22], radius=6, fill=(45, 45, 45))
        draw.rounded_rectangle([25, y+10, 25 + int(500 * (p_percent/100)), y+22], radius=6, fill=p_color)

        colors = [(0, 255, 0), (0, 255, 255), (255, 255, 0), (255, 0, 255), (0, 150, 255), (255, 120, 0), (255, 50, 50)]

        title_y = paste_y - 45
        bar_cx = paste_x + W_orig + gap + sidebar_w // 2 - 40
        if "Spatial" in Stat_Mode:
            draw.text((paste_x + W_orig//2 - 84, title_y), "[Spatial]", fill=(220,220,220,255), font=f_num)
        if show_time:
            draw.text((bar_cx - 84, title_y), "[Temporal]", fill=(220,220,220,255), font=f_num)

        if "Spatial" in Stat_Mode:
            spatial_idx = 0
            for y1, y2 in y_chunks:
                for x1, x2 in x_chunks:
                    c = colors[spatial_idx % len(colors)]
                    rect = [paste_x + x1, paste_y + y1, paste_x + x2, paste_y + y2]
                    draw.rectangle(rect, fill=None, outline=c, width=3)
                    
                    if total_batches < 150:
                        lbl_x, lbl_y = paste_x + x1 + 10, paste_y + y1 + 10
                        draw.text((lbl_x, lbl_y), f"S{spatial_idx+1}", fill=c, font=f_num, stroke_width=3, stroke_fill=(0,0,0,255))
                    
                    spatial_idx += 1

        if show_time:
            rx = 60  
            ry = 18  
            
            draw.line([bar_cx, paste_y, bar_cx, paste_y + H_orig], fill=(70, 70, 70, 255), width=2)
            scale_y = H_orig / max(1, Image_Frames)
            
            def draw_cylinder(d, cx, cy1, cy2, rx, ry, fill_color, outline_color, line_width):
                if fill_color:
                    d.ellipse([cx - rx, cy2 - ry, cx + rx, cy2 + ry], fill=fill_color, outline=outline_color, width=line_width)
                    d.rectangle([cx - rx, cy1, cx + rx, cy2], fill=fill_color)
                    d.line([cx - rx, cy1, cx - rx, cy2], fill=outline_color, width=line_width)
                    d.line([cx + rx, cy1, cx + rx, cy2], fill=outline_color, width=line_width)
                    d.ellipse([cx - rx, cy1 - ry, cx + rx, cy1 + ry], fill=fill_color, outline=outline_color, width=line_width)
                else:
                    d.ellipse([cx - rx, cy2 - ry, cx + rx, cy2 + ry], fill=None, outline=outline_color, width=line_width)
                    d.line([cx - rx, cy1, cx - rx, cy2], fill=outline_color, width=line_width)
                    d.line([cx + rx, cy1, cx + rx, cy2], fill=outline_color, width=line_width)
                    d.ellipse([cx - rx, cy1 - ry, cx + rx, cy1 + ry], fill=None, outline=outline_color, width=line_width)

            for i in range(len(t_chunks)-1, -1, -1):
                t1, t2 = t_chunks[i]
                y1 = paste_y + int(t1 * scale_y)
                y2 = paste_y + int(t2 * scale_y)
                
                true_mid_y = (y1 + y2) / 2
                if y2 - y1 < ry * 2: 
                    y1 = true_mid_y - ry
                    y2 = true_mid_y + ry

                c = colors[i % len(colors)]
                body_color = (c[0]//5, c[1]//5, c[2]//5, 200) 
                draw_cylinder(draw, bar_cx, y1, y2, rx, ry, fill_color=body_color, outline_color=c, line_width=2)
                
                draw.line([bar_cx + rx + 5, true_mid_y, bar_cx + rx + 15, true_mid_y], fill=c, width=3)
                draw.text((bar_cx + rx + 22, true_mid_y - 15), f"T{i+1}: F{t1}-{t2}", fill=c, font=f_info, stroke_width=3, stroke_fill=(0,0,0,255))

            overlaps = []
            for i in range(len(t_chunks)):
                for j in range(i+1, len(t_chunks)):
                    a, b = t_chunks[i]
                    c, d = t_chunks[j]
                    o_start, o_end = max(a, c), min(b, d)
                    if o_start < o_end:
                        overlaps.append((o_start, o_end))

            for o_start, o_end in overlaps:
                y1 = paste_y + int(o_start * scale_y)
                y2 = paste_y + int(o_end * scale_y)
                
                true_mid_y = (y1 + y2) / 2
                if y2 - y1 < ry * 2: 
                    y1 = true_mid_y - ry
                    y2 = true_mid_y + ry
                
                draw_cylinder(draw, bar_cx, y1, y2, rx, ry, fill_color=None, outline_color=(255, 255, 255, 255), line_width=4)
                
                hl_color = (255, 255, 0, 255) 
                draw.line([bar_cx + rx + 4, true_mid_y, bar_cx + rx + 30, true_mid_y], fill=hl_color, width=3)
                draw.text((bar_cx + rx + 35, true_mid_y - 15), "Overlap", fill=hl_color, font=f_info, stroke_width=2, stroke_fill=(0,0,0,255))

        return (torch.from_numpy(np.array(full_canvas.convert("RGB")).astype(np.float32) / 255.0).unsqueeze(0),)