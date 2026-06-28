"""
XB-BOX AI 漫画文字渲染节点 (生产版 v3.0)
=========================================
基于"文本光栅化物理渲染 + CV视觉锚定 + 前端提示词分流"三层架构，
从根本上解决扩散模型生成中文对白时的笔画畸形、鬼影残留与排版错位问题。

节点清单:
  XB_ComicPromptParser      — 前端：智能提示词解析分流 + 字数-气泡尺寸映射
  XB_ComicTextRenderer      — 第一代：手动精确坐标渲染 (旁白/拟声词降级预案)
  XB_AutoBubbleTextRenderer — 第二代：全自动 CV 寻迹 + 数字涂改液 + 三层防御
"""

import os
import re
import textwrap
import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False


# ============================================================
# 字体工具
# ============================================================
def _find_cjk_fonts():
    """扫描系统常见中文字体，返回可用字体路径列表"""
    font_paths = []
    win_font_dir = os.environ.get("WINDIR", "C:\\Windows") + "\\Fonts"
    for fname in ["msyh.ttc", "msyhbd.ttc", "simhei.ttf", "simsun.ttc",
                   "simkai.ttf", "Deng.ttf", "simfang.ttf"]:
        fp = os.path.join(win_font_dir, fname)
        if os.path.exists(fp):
            font_paths.append(fp)
    # Linux / macOS fallback
    if not font_paths:
        for d in ["/usr/share/fonts/truetype/", "/System/Library/Fonts/"]:
            if os.path.isdir(d):
                for f in os.listdir(d):
                    if f.endswith((".ttf", ".ttc", ".otf")):
                        font_paths.append(os.path.join(d, f))
    return font_paths


def _load_font(font_name, font_size):
    """加载字体：支持直接路径、文件名模糊搜索、系统回退"""
    if not font_name:
        font_name = ""
    if os.path.isfile(font_name):
        try:
            return ImageFont.truetype(font_name, font_size)
        except Exception:
            pass
    for fp in _find_cjk_fonts():
        if font_name.lower() in os.path.basename(fp).lower():
            try:
                return ImageFont.truetype(fp, font_size)
            except Exception:
                continue
    for fp in _find_cjk_fonts():
        try:
            return ImageFont.truetype(fp, font_size)
        except Exception:
            continue
    return ImageFont.load_default()


def _parse_hex(color_str):
    """#RRGGBB → (R, G, B, 255)"""
    c = color_str.lstrip("#")
    if len(c) >= 6:
        return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), 255)
    return (0, 0, 0, 255)


def _wrap_text(text, font, max_width, draw):
    """按最大宽度自动换行，返回行列表"""
    if not text or max_width <= 0:
        return [text] if text else []
    lines = []
    for para in text.split("\n"):
        if not para:
            lines.append("")
            continue
        cur = ""
        for ch in para:
            test = cur + ch
            bw = draw.textbbox((0, 0), test, font=font)[2]
            if bw > max_width and cur:
                lines.append(cur)
                cur = ch
            else:
                cur = test
        if cur:
            lines.append(cur)
    return lines


# ============================================================
# 节点 A: XB_ComicPromptParser — 前端提示词智能分流
# ============================================================
class XB_ComicPromptParser:
    """从含 [台词] 标记的剧本中提取台词并清洗提示词。
    自动根据字数向大模型注入匹配的气泡尺寸描述，实现 SSOT 单一数据源架构。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "raw_prompt": ("STRING", {
                    "default": "第一格大图，男生冷酷，[宋琛眉眼清秀，嘴里却叼着根突兀烟]，左侧气泡，[真难看。]",
                    "multiline": True,
                    "tooltip": "完整剧本。用方括号 [台词] 标记对白，节点会自动提取和清洗"
                }),
                "base_bubble_desc": ("STRING", {
                    "default": "纯白干净的空白对话框",
                    "tooltip": "气泡基础描述。节点会根据字数自动追加微小/标准/宽大/超大等修饰词"
                }),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("洗净给大模型的提示词", "给渲染节点的台词(|分隔)")
    FUNCTION = "parse"
    CATEGORY = "XB_ToolBox/Comic"
    DESCRIPTION = (
        "前端提示词拦截解析器 —— SSOT 架构核心。\n"
        "输入含 [台词] 的完整剧本，自动:\n"
        "1. 提取 [] 内台词，拼接为台词1|台词2 格式\n"
        "2. 根据字数映射气泡尺寸 (<=3:微小, <=8:标准, <=18:宽大, >18:超大)\n"
        "3. 清洗提示词，彻底屏蔽大模型看到汉字，根除鬼影"
    )

    def parse(self, raw_prompt, base_bubble_desc):
        dialogues = []

        def replacer(m):
            text = m.group(1).strip()
            if not text:
                return ""
            dialogues.append(text)
            n = len(text)
            if n <= 3:
                adj = "一个微小紧凑的"
            elif n <= 8:
                adj = "一个标准大小的"
            elif n <= 18:
                adj = "一个宽大的"
            else:
                adj = "一个占据极大面积的超大长条形"
            return adj + base_bubble_desc

        cleaned = re.sub(r"\[(.*?)\]", replacer, raw_prompt, flags=re.DOTALL)
        pipeline = " | ".join(dialogues)
        print(f"[XB_ComicPromptParser] 提取 {len(dialogues)} 句台词，已按字数映射气泡尺寸")
        return (cleaned, pipeline)


# ============================================================
# 节点 B: XB_ComicTextRenderer — 手动精确坐标 (降级预案)
# ============================================================
class XB_ComicTextRenderer:
    """在图像指定坐标用系统字体精确渲染文字。
    用于全自动节点无法覆盖的场景：旁白、拟声词、无气泡文本。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "text": ("STRING", {"default": "", "multiline": True,
                                     "tooltip": "要渲染的文字。支持 \\n 换行"}),
                "font_name": ("STRING", {"default": "msyh.ttc",
                                          "tooltip": "字体名或路径，如 msyh.ttc / simhei.ttf"}),
                "font_size": ("INT", {"default": 36, "min": 8, "max": 500, "step": 1}),
                "x": ("INT", {"default": 100, "min": 0, "max": 8192, "step": 1,
                               "tooltip": "文字起始 X 坐标"}),
                "y": ("INT", {"default": 100, "min": 0, "max": 8192, "step": 1,
                               "tooltip": "文字起始 Y 坐标"}),
                "max_width": ("INT", {"default": 400, "min": 0, "max": 8192, "step": 1,
                                       "tooltip": "最大宽度(px)，超宽自动换行；0=不限制"}),
                "alignment": (["left", "center", "right"], {"default": "center"}),
                "text_color": ("STRING", {"default": "#000000"}),
                "outline_width": ("INT", {"default": 0, "min": 0, "max": 10, "step": 1}),
                "outline_color": ("STRING", {"default": "#FFFFFF"}),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("图像",)
    FUNCTION = "render"
    CATEGORY = "XB_ToolBox/Comic"
    DESCRIPTION = (
        "第一代物理光栅化节点 —— 手动指定 X/Y 坐标，用系统原生字体精确渲染。\n"
        "用于处理旁白、拟声词、无气泡文本等全自动节点无法覆盖的特殊场景。\n"
        "提示: 如需多句不同位置，请串联多个此节点分层叠加。"
    )

    def render(self, image, text, font_name, font_size, x, y, max_width,
               alignment, text_color, outline_width, outline_color):
        fg = _parse_hex(text_color)
        og = _parse_hex(outline_color)
        font = _load_font(font_name, font_size)

        B = image.shape[0]
        out = []
        for b in range(B):
            arr = (image[b].cpu().numpy() * 255).astype(np.uint8)
            pil = Image.fromarray(arr).convert("RGBA")
            draw = ImageDraw.Draw(pil)
            lines = _wrap_text(text, font, max_width, draw)
            bb = draw.textbbox((0, 0), "啊", font=font)
            lh = bb[3] - bb[1] + 4

            for i, line in enumerate(lines):
                lw = draw.textbbox((0, 0), line, font=font)[2]
                if alignment == "center" and max_width > 0:
                    lx = x + (max_width - lw) // 2
                elif alignment == "right" and max_width > 0:
                    lx = x + max_width - lw
                else:
                    lx = x
                ly = y + i * lh
                if outline_width > 0:
                    for dx in range(-outline_width, outline_width + 1):
                        for dy in range(-outline_width, outline_width + 1):
                            if dx or dy:
                                draw.text((lx + dx, ly + dy), line, font=font, fill=og)
                draw.text((lx, ly), line, font=font, fill=fg)

            result = np.array(pil.convert("RGB")).astype(np.float32) / 255.0
            out.append(torch.from_numpy(result))
        return (torch.stack(out, dim=0),)


# ============================================================
# 节点 C: XB_AutoBubbleTextRenderer — 全自动 CV 寻迹 + 涂改液
# ============================================================
class XB_AutoBubbleTextRenderer:
    """OpenCV 自动扫描白色对话框 -> 涂改液抹除鬼影 -> 填入台词。
    含三层防御: 暗黑模式 / 形状过滤 / 边界分离。
    形态学预处理解决气泡内纹理导致的识别断裂。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "text": ("STRING", {"default": "", "multiline": True,
                                     "tooltip": "台词，竖线 | 分隔。如: 台词1 | 台词2"}),
                "font_name": ("STRING", {"default": "msyh.ttc",
                                          "tooltip": "字体名或路径，如 msyh.ttc / simhei.ttf"}),
                "font_size": ("INT", {"default": 36, "min": 8, "max": 500, "step": 1}),
                "text_color": ("STRING", {"default": "#000000"}),
                "bubble_margin": ("INT", {"default": 15, "min": 0, "max": 200, "step": 1}),
                "auto_clear_bubble": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "数字涂改液: 用纯白填满气泡内部，彻底抹除 AI 鬼影乱码后再印字"
                }),
                "white_threshold": ("INT", {"default": 220, "min": 160, "max": 255, "step": 1,
                                              "tooltip": "白色阈值。降低可检测带光影的气泡"}),
                "min_bubble_area": ("INT", {"default": 5000, "min": 500, "max": 1000000, "step": 100}),
                "sort_mode": (["auto", "top_to_bottom", "left_to_right", "largest_first"], {"default": "auto"}),
                "invert_mode": ("BOOLEAN", {"default": False,
                                             "tooltip": "暗黑模式: 取反后检测深色气泡"}),
                "shape_filter_enabled": ("BOOLEAN", {"default": True,
                                                      "tooltip": "形状过滤: 排除白T恤等长条形误检"}),
                "min_extent": ("FLOAT", {"default": 0.4, "min": 0.1, "max": 1.0, "step": 0.05}),
                "max_aspect_ratio": ("FLOAT", {"default": 3.5, "min": 1.0, "max": 10.0, "step": 0.1}),
                "erode_iterations": ("INT", {"default": 1, "min": 0, "max": 5, "step": 1,
                                              "tooltip": "边界分离: 腐蚀迭代，分离粘连气泡"}),
                "morph_close_size": ("INT", {"default": 15, "min": 3, "max": 51, "step": 2,
                                              "tooltip": "形态学内核尺寸。增大可填平气泡内的噪点和残影"}),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("图像", "检测信息")
    FUNCTION = "render_auto"
    CATEGORY = "XB_ToolBox/Comic"
    DESCRIPTION = (
        "第二代全自动 CV 视觉锚定节点 (v3.0 生产版)。\n\n"
        "流程: 灰度化 -> 形态学闭运算填平噪点 -> 二值化 -> 轮廓检测 -> 涂改液抹白 -> 填字。\n\n"
        "核心能力:\n"
        "- auto_clear_bubble: 数字涂改液，先抹后写彻底根除鬼影\n"
        "- morph_close_size: 形态学预处理，解决气泡内纹理/残影导致的识别断裂\n"
        "- 三层防御: 暗黑模式(invert) + 形状过滤(shape_filter) + 边界分离(erode)\n"
        "- 台词框输入 台词1 | 台词2 | 台词3，一键自动排版"
    )

    def render_auto(self, image, text, font_name, font_size, text_color,
                    bubble_margin, auto_clear_bubble, white_threshold,
                    min_bubble_area, sort_mode, invert_mode=False,
                    shape_filter_enabled=True, min_extent=0.4,
                    max_aspect_ratio=3.5, erode_iterations=1, morph_close_size=15):
        if not HAS_CV2:
            raise ImportError(
                "[XB_AutoBubbleTextRenderer] 需要 opencv-python。请运行: pip install opencv-python")

        fg = _parse_hex(text_color)
        dialogues = [d.strip() for d in text.split("|") if d.strip()]
        font = _load_font(font_name, font_size)

        B = image.shape[0]
        results = []
        info = []

        for b in range(B):
            # ---- torch -> numpy -> BGR ----
            arr = (image[b].cpu().numpy() * 255).astype(np.uint8)
            if arr.shape[2] == 4:
                cv_rgb = cv2.cvtColor(arr, cv2.COLOR_RGBA2RGB)
            else:
                cv_rgb = arr.copy()
            cv_bgr = cv2.cvtColor(cv_rgb, cv2.COLOR_RGB2BGR)

            # ---- 1. 灰度 + 暗黑模式 ----
            gray = cv2.cvtColor(cv_bgr, cv2.COLOR_BGR2GRAY)
            if invert_mode:
                gray = cv2.bitwise_not(gray)
                info.append("  🌙 暗黑模式: 已取反")

            # ---- 2. 形态学预处理 (关键!) ----
            #    先用大核闭运算把气泡内 AI 残影/噪点/纹理糊成一片
            mk = cv2.getStructuringElement(cv2.MORPH_RECT, (morph_close_size, morph_close_size))
            gray = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, mk)

            # ---- 3. 二值化 ----
            _, binary = cv2.threshold(gray, white_threshold, 255, cv2.THRESH_BINARY)

            # ---- 4. 边界分离 (开运算) ----
            if erode_iterations > 0:
                ek = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
                binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, ek, iterations=erode_iterations)

            # ---- 5. 二次闭运算 (弥合腐蚀造成的小缺口) ----
            ck = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
            binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, ck, iterations=2)

            # ---- 6. 轮廓检测 ----
            contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            # ---- 7. 筛选 (面积 + 形状先验) ----
            filtered = 0
            bubbles = []
            for cnt in contours:
                area = cv2.contourArea(cnt)
                if area < min_bubble_area:
                    continue
                rx, ry, rw, rh = cv2.boundingRect(cnt)

                if shape_filter_enabled:
                    bbox_area = float(rw * rh)
                    extent = area / bbox_area if bbox_area > 0 else 0.0
                    if extent < min_extent:
                        filtered += 1
                        continue
                    ar = max(rw, rh) / min(rw, rh) if min(rw, rh) > 0 else 999.0
                    if ar > max_aspect_ratio:
                        filtered += 1
                        continue

                bubbles.append({
                    "x": rx, "y": ry, "width": rw, "height": rh,
                    "cx": rx + rw // 2, "cy": ry + rh // 2,
                    "area": area, "contour": cnt,
                })

            if filtered:
                info.append(f"  🛡️ 形状过滤: 排除 {filtered} 个误检")

            # ---- 8. 排序 ----
            if sort_mode == "top_to_bottom":
                bubbles.sort(key=lambda b: (b["cy"], b["cx"]))
            elif sort_mode == "left_to_right":
                bubbles.sort(key=lambda b: (b["cx"], b["cy"]))
            elif sort_mode == "largest_first":
                bubbles.sort(key=lambda b: -b["area"])
            else:
                if bubbles:
                    avg_h = sum(b["height"] for b in bubbles) / len(bubbles)
                    row_th = avg_h * 0.5
                    bubbles.sort(key=lambda b: b["cx"])
                    rows = []
                    for bu in bubbles:
                        placed = False
                        for row in rows:
                            if abs(bu["cy"] - row[0]["cy"]) < row_th:
                                row.append(bu)
                                placed = True
                                break
                        if not placed:
                            rows.append([bu])
                    for row in rows:
                        row.sort(key=lambda b: b["cx"])
                    rows.sort(key=lambda r: r[0]["cy"])
                    bubbles = [b for row in rows for b in row]

            info.append(f"🫧 Batch {b+1}: 检测 {len(bubbles)} 气泡, 台词 {len(dialogues)} 句")

            if not bubbles:
                info.append("  ⚠️ 未检测到气泡! 请降低 white_threshold 或增大 morph_close_size")
                results.append(torch.from_numpy(arr.astype(np.float32) / 255.0))
                continue

            # ---- 9. 涂改液: 用轮廓填充纯白 ----
            if auto_clear_bubble:
                valid_cnts = [b["contour"] for b in bubbles]
                cv2.drawContours(cv_rgb, valid_cnts, -1, (255, 255, 255), thickness=cv2.FILLED)
                info.append(f"  🧼 涂改液: 擦除 {len(valid_cnts)} 个气泡内部鬼影")

            # ---- 10. PIL 渲染文字 ----
            pil = Image.fromarray(cv_rgb)
            draw = ImageDraw.Draw(pil)

            for i, bubble in enumerate(bubbles):
                if i >= len(dialogues):
                    break
                line_text = dialogues[i]
                avail_w = max(font_size, bubble["width"] - 2 * bubble_margin)
                text_lines = _wrap_text(line_text, font, avail_w, draw)
                bb = draw.textbbox((0, 0), "啊", font=font)
                lh = bb[3] - bb[1] + 4
                total_h = len(text_lines) * lh
                start_y = bubble["y"] + (bubble["height"] - total_h) // 2

                for j, tline in enumerate(text_lines):
                    tlw = draw.textbbox((0, 0), tline, font=font)[2]
                    tlx = bubble["x"] + (bubble["width"] - tlw) // 2
                    tly = start_y + j * lh
                    draw.text((tlx, tly), tline, font=font, fill=fg)

                info.append(
                    f"  💬 气泡{i+1}: ({bubble['x']},{bubble['y']}) "
                    f"{bubble['width']}x{bubble['height']} -> \"{line_text[:20]}{'...' if len(line_text) > 20 else ''}\""
                )

            result = np.array(pil).astype(np.float32) / 255.0
            results.append(torch.from_numpy(result))

        out_info = "\n".join(info)
        print(f"[XB_AutoBubbleTextRenderer]\n{out_info}")
        return (torch.stack(results, dim=0), out_info)
