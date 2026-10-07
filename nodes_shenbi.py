"""
XB-BOX - 🖌️ 神笔（ShenBi）
================================================================================
无输入端、只有一个 Image 输出的「画板」节点（以官方 Load Image 节点为基础改造）。

· 两种模式（部件 mode）
    创作 —— 载入白色 / 黑色纯色画布，设好分辨率后点「🎨 创作画布」作画；
             输出**严格对齐**设定的分辨率（宽 × 高）。
    编辑 —— 载入本地图片（官方 Load Image 同款下拉 + 上传按钮），点「🖌️ 编辑图片」作画；
             源图大于设定分辨率 → 等比缩小后居中裁切；小于设定分辨率 → 保持原尺寸、不放大。
· 画幅比例 / 宽度 / 高度：与「XB-BOX - 🖼️ 图片参数大全mini」同一套比例联动，步长对齐 32。
· 画笔（粗细 / 颜色 / 橡皮 / 翻转 / 旋转 / 上一步 / 下一步）在前端 js/xb_shenbi.js；
  两个模式的画板**各存各的**、互不串台。⚠️ 画板存成**图片文件**（前端 POST /upload/image 到
  input/xb_shenbi/），部件里只放文件名「xb_shenbi_<节点id>_<模式>.png」——绝不能内嵌 PNG
  base64：一幅 1024² 的图就 1.7MB，工作流 JSON 会涨到几 MB，撑爆浏览器草稿配额后**整个工作流
  刷新即丢**。老工作流里已存在的 dataURL 仍然兼容解码。
    创作模式 → created_data（空 = 按设定分辨率现铺纯色画布）
    编辑模式 → painted_data（空 = 直接用源图，只在超过设定分辨率时缩小裁切）
"""

import base64
import hashlib
import io
import math
import os

import numpy as np
import torch
from PIL import Image, ImageOps

import comfy.model_management
import folder_paths
import nodes

# ── 模式 ────────────────────────────────────────────────────────────────────
MODE_CREATE = "创作"
MODE_EDIT = "编辑"
MODES = [MODE_CREATE, MODE_EDIT]

# ── 纯色画布 ────────────────────────────────────────────────────────────────
BG_WHITE = "白色"
BG_BLACK = "黑色"
CANVAS_COLORS = [BG_WHITE, BG_BLACK]
_CANVAS_RGB = {BG_WHITE: (255, 255, 255), BG_BLACK: (0, 0, 0)}

# ── 画幅比例（与「XB-BOX - 🖼️ 图片参数大全mini」完全一致的选项顺序）────────
ASPECT_RATIOS = ["Free", "1:1", "16:9", "9:16", "4:3", "3:4", "21:9"]
RATIO_MAP = {"1:1": 1.0, "16:9": 16 / 9, "9:16": 9 / 16, "4:3": 4 / 3, "3:4": 3 / 4, "21:9": 21 / 9}

SIZE_STEP = 32
SIZE_MIN = 32
MAX_RESOLUTION = int(getattr(nodes, "MAX_RESOLUTION", 16384) or 16384)

_RESAMPLE = getattr(getattr(Image, "Resampling", Image), "LANCZOS")


# ── 尺寸工具 ────────────────────────────────────────────────────────────────
def _snap(value, step=SIZE_STEP, minimum=SIZE_MIN, maximum=MAX_RESOLUTION):
    """对齐到 step 的整数倍并夹到 [minimum, maximum]。

    ⚠️ 用 floor(x + 0.5) 而不是内置 round()：前端用的是 JS Math.round（0.5 一律进位），
       而 Python round() 是银行家舍入（round(22.5) == 22），会让「比例联动」结果和
       节点上显示 / 画板上的尺寸差一格（例：1280 宽 16:9 → 前端 736，Python 704）。
    """
    try:
        raw = float(value)
    except (TypeError, ValueError):
        raw = float(minimum)
    if not math.isfinite(raw):
        raw = float(minimum)
    steps = int(math.floor(raw / step + 0.5))
    return int(min(maximum, max(minimum, steps * step)))


def _resolve_size(aspect_ratio, width, height):
    """画幅比例联动（与 xb_master_param / 图片参数大全mini 同一套算法，步长换成 32）。"""
    safe_w = _snap(width)
    safe_h = _snap(height)
    ratio = RATIO_MAP.get(aspect_ratio)
    if not ratio:
        return safe_w, safe_h
    if safe_w >= safe_h:
        safe_h = _snap(safe_w / ratio)
    else:
        safe_w = _snap(safe_h * ratio)
    return safe_w, safe_h


# ── 图像工具 ────────────────────────────────────────────────────────────────
def _intermediate():
    """与官方 Load Image 相同的精度 / 设备策略（老版本 ComfyUI 回退到 cpu/fp32）。"""
    try:
        return comfy.model_management.intermediate_dtype(), comfy.model_management.intermediate_device()
    except Exception:
        return torch.float32, torch.device("cpu")


def _to_comfy(image):
    """PIL(RGB) → ComfyUI IMAGE 张量 [1, H, W, 3]，精度 / 设备对齐官方 Load Image。"""
    dtype, device = _intermediate()
    array = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
    tensor = torch.from_numpy(array)[None,]
    return tensor.to(device=device, dtype=dtype)


def _decode_data_url(data):
    """解码前端存档的 dataURL / base64 PNG。"""
    text = (data or "").strip()
    if not text:
        return None
    if text.startswith("data:"):
        text = text.split(",", 1)[-1]
    text = "".join(text.split())
    raw = base64.b64decode(text)
    with Image.open(io.BytesIO(raw)) as img:
        return ImageOps.exif_transpose(img).convert("RGB")


def _load_painting(value):
    """画板存档 → PIL：既支持「input 目录里的图片文件名」（正常路径，工作流里只存文件名），
    也兼容老工作流里内嵌的 dataURL。"""
    text = (value or "").strip()
    if not text:
        return None
    if text.startswith("data:"):
        return _decode_data_url(text)
    path = folder_paths.get_annotated_filepath(text)
    with Image.open(path) as img:
        return ImageOps.exif_transpose(img).convert("RGB")


def _file_stamp(value):
    """存档值的变更指纹：文件名按 mtime+size（同名覆盖也能触发重跑），dataURL 按内容哈希。"""
    text = (value or "").strip()
    if not text:
        return ""
    if text.startswith("data:"):
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    try:
        path = folder_paths.get_annotated_filepath(text)
        return f"{os.path.getmtime(path):.3f}:{os.path.getsize(path)}"
    except Exception:
        return ""


def _cover_crop(image, width, height):
    """等比缩放至完全覆盖目标框后居中裁切（结果必然是 width × height，且不留黑边）。"""
    src_w, src_h = image.size
    if src_w == width and src_h == height:
        return image
    scale = max(width / float(src_w), height / float(src_h))
    new_w = max(width, int(math.ceil(src_w * scale)))
    new_h = max(height, int(math.ceil(src_h * scale)))
    resized = image.resize((new_w, new_h), _RESAMPLE)
    left = (new_w - width) // 2
    top = (new_h - height) // 2
    return resized.crop((left, top, left + width, top + height))


def _fit_to_target(image, width, height, force=False):
    """编辑模式：源图大于设定分辨率才缩小裁切；小于设定值则原尺寸返回、绝不放大。
    创作模式（force=True）：严格对齐设定分辨率。"""
    src_w, src_h = image.size
    if force or src_w > width or src_h > height:
        return _cover_crop(image, width, height)
    return image


def _blank(width, height, canvas_color):
    return Image.new("RGB", (width, height), _CANVAS_RGB.get(canvas_color, (255, 255, 255)))


# ── 节点 ────────────────────────────────────────────────────────────────────
class XB_ShenBi:
    """🖌️ 神笔 —— 无输入、只输出 Image 的画板节点（创作 / 编辑 双模式）。"""

    @classmethod
    def INPUT_TYPES(cls):
        # 与官方 Load Image 完全一致：输入目录里的图片列表 + 上传按钮
        files = []
        try:
            input_dir = folder_paths.get_input_directory()
            files = [f for f in os.listdir(input_dir) if os.path.isfile(os.path.join(input_dir, f))]
            files = folder_paths.filter_files_content_types(files, ["image"])
        except Exception as exc:
            print(f"[XB-BOX 神笔] 读取输入目录失败：{exc}")

        return {
            "required": {
                "mode": (MODES, {"default": MODE_CREATE,
                                 "tooltip": "创作 = 纯色画布作画；编辑 = 在本地图片上作画"}),
                "aspect_ratio": (ASPECT_RATIOS, {"default": "Free",
                                                 "tooltip": "画幅比例，与宽高联动（步长 32）"}),
                "width": ("INT", {"default": 1024, "min": SIZE_MIN, "max": MAX_RESOLUTION,
                                  "step": SIZE_STEP, "tooltip": "目标宽度，对齐 32 的倍数"}),
                "height": ("INT", {"default": 1024, "min": SIZE_MIN, "max": MAX_RESOLUTION,
                                   "step": SIZE_STEP, "tooltip": "目标高度，对齐 32 的倍数"}),
                "canvas_color": (CANVAS_COLORS, {"default": BG_WHITE,
                                                 "tooltip": "创作模式的纯色画布颜色"}),
                "image": (sorted(files), {"image_upload": True,
                                          "tooltip": "编辑模式加载的本地图片"}),
                "painted_data": ("STRING", {"default": "", "multiline": False,
                                            "tooltip": "内部字段：编辑模式画板的 PNG(base64) 存档，勿手工修改"}),
                "created_data": ("STRING", {"default": "", "multiline": False,
                                            "tooltip": "内部字段：创作模式画板的 PNG(base64) 存档，勿手工修改"}),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("Image",)
    FUNCTION = "render"
    CATEGORY = "XB_ToolBox/Image"
    DESCRIPTION = ("无输入端的画板节点：创作模式输出纯色/手绘画布并严格对齐设定分辨率；"
                   "编辑模式在本地图片上手绘，图片大于设定分辨率则缩小裁切、小于则原样保留不放大。")

    @classmethod
    def VALIDATE_INPUTS(cls, **kwargs):
        # 宽容校验：图片文件被删除 / 换了目录时也不要拦住工作流执行（render 内部有兜底）
        return True

    @classmethod
    def IS_CHANGED(cls, image=None, painted_data=None, created_data=None, **kwargs):
        # 图片/画板都是「同名覆盖」的文件（官方 Load Image 也是同名文件重新上传），
        # 必须把文件的 mtime+size 计入变更指纹，否则重画后节点会命中缓存、输出旧图
        return "|".join([
            _file_stamp(image),
            _file_stamp(painted_data),
            _file_stamp(created_data),
        ])

    # ── 内部 ────────────────────────────────────────────────────────────────
    @staticmethod
    def _load_source(name):
        if not name:
            return None
        try:
            path = folder_paths.get_annotated_filepath(name)
            with Image.open(path) as img:
                return ImageOps.exif_transpose(img).convert("RGB")
        except Exception as exc:
            print(f"[XB-BOX 神笔] 无法读取图片「{name}」：{exc}")
            return None

    # ── 主流程 ──────────────────────────────────────────────────────────────
    def render(self, mode, aspect_ratio, width, height, canvas_color, image, painted_data, created_data):
        target_w, target_h = _resolve_size(aspect_ratio, width, height)
        create_mode = (mode == MODE_CREATE)

        # 两个模式各存各的画板：创作模式读 created_data，编辑模式读 painted_data
        paint_raw = created_data if create_mode else painted_data
        painting = None
        if paint_raw and paint_raw.strip():
            try:
                painting = _load_painting(paint_raw)
            except Exception as exc:
                print(f"[XB-BOX 神笔] 画板存档读取失败，已忽略：{exc}")

        if painting is not None:
            # 有画板存档：创作模式严格对齐设定分辨率；编辑模式沿用「大了才缩小裁切」规则
            out = _fit_to_target(painting, target_w, target_h, force=create_mode)
        elif create_mode:
            out = _blank(target_w, target_h, canvas_color)
        else:
            source = self._load_source(image)
            if source is None:
                out = _blank(target_w, target_h, canvas_color)
            else:
                out = _fit_to_target(source, target_w, target_h)

        return (_to_comfy(out),)
