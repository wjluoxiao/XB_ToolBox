import torch
import numpy as np
import os
from PIL import Image, ImageDraw, ImageFont

# ==========================================
# 极客魔法：标识数据来源，并携带分层数据的超级浮点数
# ==========================================
class CalculatedFloat(float):
    pass

# ==========================================
# 📟 可用显存计算
# ==========================================
class XB_VRAM_Calculator:
    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "显卡总显存_GB": ("INT", {"default": 24, "min": 4, "max": 128, "step": 1, "display": "number"}),
                "系统及背景开销_GB": ("FLOAT", {"default": 2.0, "min": 0.0, "max": 64.0, "step": 0.5, "display": "number"}),
                "视频主模型": (["LTX-2.3 (22B)", "WAN2.2-I2V (14B)", "WAN2.2-T2V (14B)", "WAN2.2-Animate (14B)"], {"default": "LTX-2.3 (22B)"}),
                "模型量化": (["FP16/BF16", "FP8", "GGUF-Q8", "GGUF-Q6", "GGUF-Q4"], {"default": "FP8"}),
                "主模型总层数": ("INT", {"default": 48, "min": 1, "max": 200, "step": 1, "display": "number"}),
                "分层交换数值": ("INT", {"default": 0, "min": 0, "max": 200, "step": 1, "display": "number"}),
                "LoRA及插件总计_GB": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 64.0, "step": 0.1, "display": "number"}),
            }
        }

    RETURN_TYPES = ("FLOAT",)
    RETURN_NAMES = ("可用显存输出",)
    FUNCTION = "calculate_vram"
    CATEGORY = "小白工具箱/分块预览"

    def calculate_vram(self, 显卡总显存_GB, 系统及背景开销_GB, 视频主模型, 模型量化, 主模型总层数, 分层交换数值, LoRA及插件总计_GB):
        vram_map = {
            "LTX-2.3 (22B)": {"FP16/BF16": 44.0, "FP8": 22.5, "GGUF-Q8": 22.8, "GGUF-Q6": 17.8, "GGUF-Q4": 13.5},
            "WAN2.2-I2V (14B)": {"FP16/BF16": 28.0, "FP8": 14.0, "GGUF-Q8": 14.5, "GGUF-Q6": 11.0, "GGUF-Q4": 9.0},
            "WAN2.2-T2V (14B)": {"FP16/BF16": 28.0, "FP8": 14.0, "GGUF-Q8": 14.5, "GGUF-Q6": 11.0, "GGUF-Q4": 9.0},
            "WAN2.2-Animate (14B)": {"FP16/BF16": 28.0, "FP8": 14.0, "GGUF-Q8": 14.5, "GGUF-Q6": 11.0, "GGUF-Q4": 9.0},
        }
        
        full_model_size = vram_map.get(视频主模型, {}).get(模型量化, 14.0)
        stay_layers = max(0, 主模型总层数 - 分层交换数值)
        active_model_vram = (full_model_size / max(1, 主模型总层数)) * stay_layers
        available_vram = 显卡总显存_GB - 系统及背景开销_GB - active_model_vram - LoRA及插件总计_GB
        available_vram = max(0.1, available_vram)
        
        res = CalculatedFloat(available_vram)
        res._stay = stay_layers
        res._total = 主模型总层数
        
        return (res,)

# ==========================================
# 🧊 极简双区浏览器：左 2D 原生镂空 + 右完美重叠圆柱
# ==========================================
class XB_ChunkVisualization:
    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "统计模式": (["仅画面", "仅时间", "画面与时间"], {"default": "画面与时间"}),
                "可用显存_GB": ("FLOAT", {"default": 12.0, "min": 0.1, "max": 128.0, "step": 0.1, "display": "number"}),
                "图像宽度": ("INT", {"default": 1024, "min": 64, "max": 8192, "step": 16, "display": "number"}),
                "图像高度": ("INT", {"default": 1024, "min": 64, "max": 8192, "step": 16, "display": "number"}),
                "图像帧数": ("INT", {"default": 1, "min": 1, "max": 10000, "step": 4, "display": "number"}),
                "当前阶段": (["编码阶段", "解码阶段"], {"default": "解码阶段"}),
                "图像分块大小": ("INT", {"default": 512, "min": 64, "max": 8192, "step": 32, "display": "number"}),
                "图像分块重叠": ("INT", {"default": 64, "min": 0, "max": 4096, "step": 32, "display": "number"}),
                "帧数分段大小": ("INT", {"default": 33, "min": 8, "max": 10000, "step": 4, "display": "number"}),
                "帧数分段重叠": ("INT", {"default": 4, "min": 0, "max": 1000, "step": 4, "display": "number"}),
            },
            "optional": { 
                "图像输入": ("IMAGE",) 
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("preview_image",)
    FUNCTION = "visualize_chunks"
    CATEGORY = "小白工具箱"

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

    def visualize_chunks(self, 统计模式, 可用显存_GB, 图像宽度, 图像高度, 图像帧数, 当前阶段, 
                         图像分块大小, 图像分块重叠, 帧数分段大小, 帧数分段重叠, 图像输入=None):
        
        active_vram = float(可用显存_GB)
        is_calc = type(可用显存_GB).__name__ == "CalculatedFloat"
        stay_info = f" (模型驻留:{可用显存_GB._stay}/{可用显存_GB._total}层)" if (is_calc and hasattr(可用显存_GB, '_stay')) else ""

        if 图像输入 is not None:
            B, H_orig, W_orig, C = 图像输入.shape
            source_img = Image.fromarray((图像输入[0].cpu().numpy() * 255).astype(np.uint8)).convert("RGBA")
            res_info = f"【图像尺寸】: {W_orig}x{H_orig} (来自图像输入)"
        else:
            W_orig, H_orig = 图像宽度, 图像高度
            source_img = Image.new("RGBA", (W_orig, H_orig), (25, 25, 25, 255))
            res_info = f"【图像尺寸】: {W_orig}x{H_orig} (来自手动参数)"

        x_chunks = self.get_1d_chunks(W_orig, 图像分块大小 if "画面" in 统计模式 else 0, 图像分块重叠)
        y_chunks = self.get_1d_chunks(H_orig, 图像分块大小 if "画面" in 统计模式 else 0, 图像分块重叠)
        t_chunks = self.get_1d_chunks(图像帧数, 帧数分段大小 if "时间" in 统计模式 else 0, 帧数分段重叠)
        total_batches = len(x_chunks) * len(y_chunks) * len(t_chunks)
        
        base_vol = W_orig * H_orig * 图像帧数
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
            p = os.path.join(os.environ.get('WINDIR', 'C:/Windows'), "Fonts", "msyh.ttc")
            return ImageFont.truetype(p, size) if os.path.exists(p) else ImageFont.load_default()
        
        f_info = get_font(22)
        f_num = get_font(28) # 大号字体用于分区大标题和块标号
        temp_draw = ImageDraw.Draw(Image.new("RGBA", (1,1)))

        # ==========================================
        # 📐 独立区域布局计算
        # ==========================================
        show_time = ("时间" in 统计模式 and 图像帧数 > 1)
        sidebar_w = 250 if show_time else 0
        gap = 50 if show_time else 0
        padding = 70 # 增加顶部 padding 以容纳大标题
        
        draw_W = W_orig + gap + sidebar_w
        new_W = max(draw_W + 80, 700) # 左右各留 40
        max_txt_w = new_W - 50

        # 数据面板排版
        info_cats = [
            {"text": f"【统计模式】: {统计模式}  /  【当前阶段】: {当前阶段}", "color": (0, 255, 255)},
            {"text": res_info, "color": (220, 220, 220)},
            {"text": f"【加载批次】: {total_batches} 批 (图像:{len(x_chunks)*len(y_chunks)} × 时间:{len(t_chunks)})", "color": (255, 255, 255)},
            {"text": f"【可用显存】: {active_vram:.1f}G{stay_info} ({'计算参数' if is_calc else '手输参数'})", "color": (150, 200, 255)},
            {"text": f"【总数据量】: {real_vol/1e6:.1f}M (基准:{base_vol/1e6:.1f}M | 冗余:+{redundancy:.1f}%) [注:M为百万像素点]", "color": (255, 150, 200)},
            {"text": f"【单批体积】: {max_chunk_vol/1e6:.1f}M / 批  /  【显存压力】: {kappa:.2f}", "color": p_color}
        ]

        final_lines = []
        for cat in info_cats:
            prefix, content = cat["text"].split("】: ", 1) if "】: " in cat["text"] else ("", cat["text"])
            if prefix: prefix += "】: "
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
        
        # 画布定位
        paste_x = int((new_W - draw_W) / 2)
        paste_y = header_H + padding
        
        full_canvas = Image.new("RGBA", (int(new_W), int(paste_y + H_orig + 40)), (20, 20, 20, 255))
        
        if 统计模式 != "仅时间":
            full_canvas.paste(source_img, (paste_x, paste_y))
        else:
            faded = source_img.copy()
            faded.putalpha(60)
            full_canvas.paste(faded, (paste_x, paste_y), faded)

        draw = ImageDraw.Draw(full_canvas, "RGBA")
        
        # 数据区文本
        y = 15
        for txt, clr, x_off in final_lines:
            draw.text((25 + x_off, y), txt, fill=clr, font=f_info)
            y += line_h
            
        draw.rounded_rectangle([25, y+10, 525, y+22], radius=6, fill=(45, 45, 45))
        draw.rounded_rectangle([25, y+10, 25 + int(500 * (p_percent/100)), y+22], radius=6, fill=p_color)

        colors = [(0, 255, 0), (0, 255, 255), (255, 255, 0), (255, 0, 255), (0, 150, 255), (255, 120, 0), (255, 50, 50)]

        # 🚨 绘制分区大标题
        title_y = paste_y - 45
        bar_cx = paste_x + W_orig + gap + sidebar_w // 2 - 40
        if "画面" in 统计模式:
            draw.text((paste_x + W_orig//2 - 84, title_y), "【图像分块】", fill=(220,220,220,255), font=f_num)
        if show_time:
            draw.text((bar_cx - 84, title_y), "【时间分块】", fill=(220,220,220,255), font=f_num)

        # ==========================================
        # 🖼️ 1. 左侧：绝对原版的镂空 2D 网格
        # ==========================================
        if "画面" in 统计模式:
            spatial_idx = 0
            for y1, y2 in y_chunks:
                for x1, x2 in x_chunks:
                    c = colors[spatial_idx % len(colors)]
                    # 绝对镂空，不加任何透明底色
                    rect = [paste_x + x1, paste_y + y1, paste_x + x2, paste_y + y2]
                    draw.rectangle(rect, fill=None, outline=c, width=3)
                    
                    if total_batches < 150:
                        lbl_x, lbl_y = paste_x + x1 + 10, paste_y + y1 + 10
                        draw.text((lbl_x, lbl_y), f"S{spatial_idx+1}", fill=c, font=f_num, stroke_width=3, stroke_fill=(0,0,0,255))
                    
                    spatial_idx += 1

        # ==========================================
        # ⏱️ 2. 右侧：完美的 3D 画家算法圆柱堆叠
        # ==========================================
        if show_time:
            rx = 60  
            ry = 18  
            
            # 画轨道底线
            draw.line([bar_cx, paste_y, bar_cx, paste_y + H_orig], fill=(70, 70, 70, 255), width=2)
            
            scale_y = H_orig / max(1, 图像帧数)
            
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

            # 2.1 画家算法排序：从底部的切片开始往上画
            for i in range(len(t_chunks)-1, -1, -1):
                t1, t2 = t_chunks[i]
                y1 = paste_y + int(t1 * scale_y)
                y2 = paste_y + int(t2 * scale_y)
                
                # 🚨 修正核心：对称膨胀，保证真理中心绝对不偏移
                true_mid_y = (y1 + y2) / 2
                if y2 - y1 < ry * 2: 
                    y1 = true_mid_y - ry
                    y2 = true_mid_y + ry

                c = colors[i % len(colors)]
                body_color = (c[0]//5, c[1]//5, c[2]//5, 200) 
                draw_cylinder(draw, bar_cx, y1, y2, rx, ry, fill_color=body_color, outline_color=c, line_width=2)
                
                # 指示线永远对准 true_mid_y
                draw.line([bar_cx + rx + 5, true_mid_y, bar_cx + rx + 15, true_mid_y], fill=c, width=3)
                draw.text((bar_cx + rx + 22, true_mid_y - 15), f"T{i+1}: F{t1}-{t2}", fill=c, font=f_info, stroke_width=3, stroke_fill=(0,0,0,255))

            # 2.2 提取并绘制纯白的“极粗覆盖重叠框”
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
                
                # 🚨 修正核心：对称膨胀，保证真理中心绝对不偏移
                true_mid_y = (y1 + y2) / 2
                if y2 - y1 < ry * 2: 
                    y1 = true_mid_y - ry
                    y2 = true_mid_y + ry
                
                # 🚨 使用与彩色圆柱相同的半径，但加粗到 4，完美吞没多余边缘！
                draw_cylinder(draw, bar_cx, y1, y2, rx, ry, fill_color=None, outline_color=(255, 255, 255, 255), line_width=4)
                
                # 🚨 警示黄高亮，彻底解决红底黑字不清晰的问题
                hl_color = (255, 255, 0, 255) # 纯黄
                draw.line([bar_cx + rx + 4, true_mid_y, bar_cx + rx + 30, true_mid_y], fill=hl_color, width=3)
                draw.text((bar_cx + rx + 35, true_mid_y - 15), "重叠区", fill=hl_color, font=f_info, stroke_width=2, stroke_fill=(0,0,0,255))

        return (torch.from_numpy(np.array(full_canvas.convert("RGB")).astype(np.float32) / 255.0).unsqueeze(0),)