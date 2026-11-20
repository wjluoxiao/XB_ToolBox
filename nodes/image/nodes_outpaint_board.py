"""
XB-BOX - 🖼️ 外补画板（Outpaint Board）
================================================================================
参考官方「Pad Image for Outpainting」的语义，把**画布尺寸**和**图片摆放**拆成两件事：

· 画布 —— 画幅比例 + 长边尺寸 + 对齐倍数 ⇒ 目标画布 W × H（宽高都是对齐倍数的整数倍）
· 摆放 —— 前端可视化窗口里拖拽 / 滚轮决定的图片矩形，由隐藏部件 layout 回传：
              {"v":1, "s": 图片宽/画布宽, "cx": 图片中心x/画布宽, "cy": 图片中心y/画布高}
          没摆过（或数据失效）时自动「等比放进画布、居中、不放大原图」

· 输出 —— 图像 = 画布（外补区填 #808080 中性灰）+ 原图按摆放矩形贴进去；
          遮罩 = 外补区 1、图片区 0；接了「遮罩」输入时取并集（外补区 ∪ 输入遮罩），
          所以一个节点同时支持「向外扩图」和「图内局部重绘」。

为什么 layout 存归一化值：改画幅比例 / 长边尺寸时图片占比会自动跟随，
不需要重新摆一遍；后端也只吃这三个浮点，任何前端版本都能还原出同一张画布。

坐标系约定：画布左上角为 (0, 0)，图片矩形 (x, y, w, h) 全部对齐「对齐倍数」，
允许 x / y 为负、w / h 超过画布（等于带裁剪的扩图），上限 4 × 画布。
"""

import json
import math

import numpy as np
import torch

# ── 画幅比例（选项顺序与「XB-BOX - 🖼️ 图片参数大全」完全一致）──────────────
ASPECT_RATIOS = [
    "自定义",
    "1:1 (Square)",
    "2:3 (Portrait Photo)",
    "3:2 (Photo)",
    "3:4 (Portrait Standard)",
    "4:3 (Standard)",
    "9:16 (Portrait Widescreen)",
    "16:9 (Widescreen)",
    "21:9 (Ultrawide)",
]
RATIO_MAP = {
    "1:1 (Square)": 1.0,
    "2:3 (Portrait Photo)": 2.0 / 3.0,
    "3:2 (Photo)": 3.0 / 2.0,
    "3:4 (Portrait Standard)": 3.0 / 4.0,
    "4:3 (Standard)": 4.0 / 3.0,
    "9:16 (Portrait Widescreen)": 9.0 / 16.0,
    "16:9 (Widescreen)": 16.0 / 9.0,
    "21:9 (Ultrawide)": 21.0 / 9.0,
}

FILL_RGB = (128.0 / 255.0,) * 3   # 外补区默认填充色 #808080（与官方 Pad Image 一致）
SIZE_MIN, SIZE_MAX = 64, 8192      # 画布宽高范围
MULTIPLE_MIN, MULTIPLE_MAX = 8, 128
SCALE_FACTOR_MAX = 4               # 图片最大 = 4 × 画布长边
LAYOUT_VERSION = 1
SEAM_VERSION = 1                   # 「参数」的结构版本
SEAM_TYPE = "XB_OUTPAINT_SEAM"     # 自定义类型：外补画板 → 外补融合
PREVIEW_MAX_SIDE = 640             # 预览临时图的长边上限（只是给节点里看，别为预览写 4K PNG）
FEATHER_MAX = 512                  # 羽化上限（px）

# 图片被缩放（放大或缩小）时用的重采样算法；尺寸完全一致时不会重采样
RESAMPLE_OPTIONS = ["bicubic", "lanczos", "area", "bilinear", "nearest-exact"]
_PIL_FILTERS = {"lanczos": "LANCZOS", "area": "BOX", "bicubic": "BICUBIC",
                "bilinear": "BILINEAR", "nearest-exact": "NEAREST"}


# ── 数值工具 ────────────────────────────────────────────────────────────────
def _floor_half(value):
    """JS Math.round 的等价实现（Python 内置 round 是银行家舍入，会和前端差一格）。"""
    return math.floor(value + 0.5)


def _multiple(value):
    """对齐倍数规整成 [8, 128] 的整数。"""
    try:
        v = int(_floor_half(float(value)))
    except (TypeError, ValueError):
        v = 16
    return max(MULTIPLE_MIN, min(MULTIPLE_MAX, v))


def _snap(value, multiple, minimum=None):
    """吸附到 multiple 的整数倍（可选下限）。"""
    try:
        v = float(value)
    except (TypeError, ValueError):
        v = float(multiple)
    if not math.isfinite(v):
        v = float(multiple)
    snapped = int(_floor_half(v / multiple) * multiple)
    if minimum is not None:
        snapped = max(int(minimum), snapped)
    return snapped


def _finite(value, default):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return v if math.isfinite(v) else default


def _clamp_axis(value, image_size, canvas_size):
    """把起点夹到「至少有一个角落在画布内」的最近区间。

    合法区间 =「左上角在内」∪「右下角在内」。图片比画布大时这两段是分开的，取离当前值
    最近的一段——这样任何摆放状态下都至少有一个真实角落在画布内，前端贴在图片真实四角上的
    调节点永远抓得到。区间端点都是对齐倍数的整数倍，夹完不会破坏对齐。
    """
    far_low, far_high = -image_size, canvas_size - image_size
    near_low, near_high = 0, canvas_size
    if far_high >= near_low:
        return max(far_low, min(near_high, value))
    if value <= far_high:
        return max(far_low, min(far_high, value))
    if value >= near_low:
        return max(near_low, min(near_high, value))
    return far_high if (value - far_high) <= (near_low - value) else near_low


def parse_color(text, default=FILL_RGB):
    """'#RRGGBB' / '#RGB' / 'RRGGBB' → (r, g, b) 0~1；非法值回落到默认灰。"""
    raw = str(text or "").strip().lstrip("#")
    if len(raw) == 3:
        raw = "".join(c * 2 for c in raw)
    if len(raw) != 6:
        return tuple(default)
    try:
        return tuple(int(raw[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    except ValueError:
        return tuple(default)


# ── 几何 ────────────────────────────────────────────────────────────────────
def board_size(aspect_ratio, width, height, multiple):
    """画幅比例 + 宽度 + 高度 → 画布 (W, H)，两边都对齐倍数。

    联动规则与「XB-BOX - 🖼️ 图片参数大全」逐行一致（前端也是同一套）：
    先各自吸附到对齐倍数，再按比例修正「较大那一边」对应的另一边：
        w >= h  →  h = snap(w / ratio)
        w <  h  →  w = snap(h * ratio)
    「自定义」比例不做任何联动（宽高就是用户填的两个数）。
    """
    m = _multiple(multiple)
    w = max(SIZE_MIN, min(SIZE_MAX, _snap(_finite(width, 1024), m)))
    h = max(SIZE_MIN, min(SIZE_MAX, _snap(_finite(height, 1024), m)))

    ratio = RATIO_MAP.get(aspect_ratio)
    if ratio and ratio > 0:
        if w >= h:
            h = max(m, _snap(w / ratio, m))
        else:
            w = max(m, _snap(h * ratio, m))
    return int(max(m, w)), int(max(m, h))


def parse_layout(text):
    """layout 部件值 → {"s","cx","cy"}；任何脏数据都返回 None（走自动摆放）。"""
    if isinstance(text, dict):
        data = text
    else:
        raw = (text or "").strip()
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return None
    if not isinstance(data, dict):
        return None
    size = _finite(data.get("s"), float("nan"))
    cx = _finite(data.get("cx"), float("nan"))
    cy = _finite(data.get("cy"), float("nan"))
    if not (size > 0 and math.isfinite(cx) and math.isfinite(cy)):
        return None
    return {"s": size, "cx": cx, "cy": cy}


def placement(layout, canvas_w, canvas_h, image_w, image_h, multiple):
    """摆放矩形 (x, y, w, h)（画布像素）。

    · 画布尺寸由 board_size() 保证对齐倍数；图片框本身**不再强制吸附**——
      否则「正好放下 / 居中填满」会为了凑整留下几像素空隙（长边方向被 floor 掉）。
    · layout 为空时：等比缩放到「正好放下」并居中，且**不放大原图**（保留原始像素）。
    """
    m = _multiple(multiple)
    canvas_w, canvas_h = int(canvas_w), int(canvas_h)
    image_w = max(1, int(image_w))
    image_h = max(1, int(image_h))
    aspect = image_w / float(image_h)
    limit = SCALE_FACTOR_MAX * max(canvas_w, canvas_h)

    if layout:
        width = layout["s"] * canvas_w
        center_x = layout["cx"] * canvas_w
        center_y = layout["cy"] * canvas_h
    else:
        # 自动摆放 = contain：整图完整落在画布内（长边贴边，不可能有缝），且不放大原图
        scale = min(canvas_w / float(image_w), canvas_h / float(image_h), 1.0)
        width = image_w * scale
        center_x = canvas_w / 2.0
        center_y = canvas_h / 2.0

    width = int(min(limit, max(m, _floor_half(width))))
    height = int(min(limit, max(m, _floor_half(width / aspect))))
    x = _floor_half(center_x - width / 2.0)
    y = _floor_half(center_y - height / 2.0)
    # 位置夹取：图片可以拖出画布（= 裁剪），但**始终至少有一个真实的角在画布内**，
    # 所以贴在图片四角上的调节点永远抓得到。
    x = int(_clamp_axis(x, width, canvas_w))
    y = int(_clamp_axis(y, height, canvas_h))
    return x, y, width, height


def _seam_band(left, top, right, bottom, box_w, box_h, x, y, feathering):
    """图片矩形内、可见区域上的「羽化带」：((feather - d) / feather)²，边缘 1 → 内侧 0。

    与官方 Pad Image for Outpaint 的 feathering 同款曲线；羽化半径夹到图片短边一半以内；
    只在可见区域上计算（大图不会因为一张全尺寸 float 数组把内存吃满）。
    """
    visible_h, visible_w = bottom - top, right - left
    if visible_h <= 0 or visible_w <= 0:
        return None
    feather = int(max(0, min(FEATHER_MAX, feathering)))
    feather = min(feather, max(1, min(box_w, box_h) // 2 - 1))
    if feather <= 0:
        return np.zeros((visible_h, visible_w), dtype=np.float32)
    rows = np.arange(top - y, top - y + visible_h, dtype=np.float32)
    cols = np.arange(left - x, left - x + visible_w, dtype=np.float32)
    dist_y = np.minimum(rows, box_h - 1 - rows)
    dist_x = np.minimum(cols, box_w - 1 - cols)
    dist = np.minimum(dist_y[:, None], dist_x[None, :])
    return (np.clip((feather - dist) / float(feather), 0.0, 1.0) ** 2).astype(np.float32)


def _apply_feather(out_mask, left, top, right, bottom, box_w, box_h, x, y, feathering):
    """把羽化带并进外补遮罩（只抬高、不降低）。feathering ≤ 0 时原图像素 100% 不变。"""
    band = _seam_band(left, top, right, bottom, box_w, box_h, x, y, feathering)
    if band is None or not band.any():
        return
    band_t = torch.from_numpy(band).to(out_mask.dtype)
    out_mask[:, top:bottom, left:right] = torch.maximum(
        out_mask[:, top:bottom, left:right], band_t.unsqueeze(0))


# ── 张量工具（不依赖 ComfyUI，保证节点可独立运行）───────────────────────────
def _resize_image_pil(image, width, height, resample):
    """走 PIL 的 LANCZOS / BOX（torch 没有这两个）；失败返回 None 让调用方回退。"""
    try:
        import numpy as np
        from PIL import Image
    except Exception:
        return None
    try:
        resampling = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
        filters = getattr(Image, "Resampling", Image)
        filt = getattr(filters, _PIL_FILTERS.get(resample, "BICUBIC"), resampling)
        data = (image.clamp(0.0, 1.0).cpu().numpy() * 255.0 + 0.5).astype(np.uint8)
        out = [np.asarray(Image.fromarray(frame).resize((width, height), filt),
                          dtype=np.float32) / 255.0 for frame in data]
        return torch.from_numpy(np.stack(out, axis=0))
    except Exception:
        return None


def _resize_image(image, width, height, resample="bicubic"):
    """[B,H,W,C] → [B,height,width,C]；尺寸一致时原样返回（不重采样）。

    · bicubic  —— torch 双三次 + antialias，浮点精度（缩小也干净）
    · bilinear —— torch 双线性 + antialias，最快
    · lanczos  —— PIL LANCZOS，最锐利（8bit 往返）
    · area     —— PIL BOX，缩小最干净的「面积平均」
    """
    if image.shape[1] == height and image.shape[2] == width:
        return image
    if resample in ("lanczos", "area"):
        out = _resize_image_pil(image, width, height, resample)
        if out is not None:
            return out
    x = image.movedim(-1, 1)
    if resample == "nearest-exact":
        # 最近邻不支持 antialias；逐像素取最近格（不模糊、不混合）
        x = torch.nn.functional.interpolate(x, size=(height, width), mode="nearest-exact")
    else:
        mode = "bilinear" if resample == "bilinear" else "bicubic"
        x = torch.nn.functional.interpolate(x, size=(height, width), mode=mode,
                                            align_corners=False, antialias=True)
    return x.movedim(1, -1).clamp_(0.0, 1.0)


def _resize_mask(mask, width, height):
    if mask.shape[-2] == height and mask.shape[-1] == width:
        return mask
    x = mask.unsqueeze(1)
    x = torch.nn.functional.interpolate(x, size=(height, width), mode="bilinear",
                                        align_corners=False, antialias=True)
    return x.squeeze(1).clamp_(0.0, 1.0)


def _match_batch(tensor, batch, channels=None):
    """把批次对齐到 batch（单张时复用）。"""
    if tensor.shape[0] == batch:
        return tensor
    if tensor.shape[0] == 1:
        return tensor.expand(batch, *tensor.shape[1:])
    return tensor[:batch]


def _preview_payload(image, out_mask):
    """给前端（onExecuted）的两张临时预览图：原图 + 红色半透明的最终遮罩。

    只用 PIL / folder_paths（ComfyUI 必然有）；纯 CPU 单元测试里这些不存在，
    任何异常都吞掉——预览只是锦上添花，绝不能因为它让出图中断。
    """
    try:
        import os
        import time

        import numpy as np
        from PIL import Image
        import folder_paths
    except Exception:
        return {}

    def save(tensor, suffix):
        arr = (tensor.clamp(0.0, 1.0).numpy() * 255.0).round().astype(np.uint8)
        pil = Image.fromarray(arr)
        pil.thumbnail((PREVIEW_MAX_SIDE, PREVIEW_MAX_SIDE))
        name = f"xb_outpaint_{suffix}_{int(time.time() * 1000)}.png"
        pil.save(os.path.join(folder_paths.get_temp_directory(), name), compress_level=1)
        return {"filename": name, "subfolder": "", "type": "temp"}

    ui = {}
    try:
        if isinstance(image, torch.Tensor) and image.shape[0] > 0:
            ui["xb_outpaint_src"] = [save(image[0], "src")]
        if isinstance(out_mask, torch.Tensor) and out_mask.shape[0] > 0:
            mask = out_mask[0].clamp(0.0, 1.0)
            alpha = (mask.numpy() * 255.0).round().astype(np.uint8)
            rgba = np.zeros(alpha.shape + (4,), dtype=np.uint8)
            rgba[..., 0] = 255
            rgba[..., 1] = 60
            rgba[..., 2] = 60
            rgba[..., 3] = alpha
            pil = Image.fromarray(rgba)
            pil.thumbnail((PREVIEW_MAX_SIDE, PREVIEW_MAX_SIDE))
            name = f"xb_outpaint_mask_{int(time.time() * 1000)}.png"
            pil.save(os.path.join(folder_paths.get_temp_directory(), name), compress_level=1)
            ui["xb_outpaint_mask"] = [{"filename": name, "subfolder": "", "type": "temp"}]
    except Exception:
        return {}
    return ui


# ── 节点 ────────────────────────────────────────────────────────────────────
class XB_OutpaintBoard:
    """🖼️ 外补画板 —— 按「画幅比例 + 宽高」铺画布，把图片摆进画布并输出外补遮罩。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "aspect_ratio": (ASPECT_RATIOS, {
                    "default": "1:1 (Square)",
                    "tooltip": "画幅比例；换比例时宽高自动按比例互相跟随，「自定义」则不联动",
                }),
                "width": ("INT", {
                    "default": 1024, "min": SIZE_MIN, "max": SIZE_MAX, "step": 16,
                    "tooltip": "画布宽度；调它时高度会按画幅比例自动跟随（步长 = 对齐倍数）",
                }),
                "height": ("INT", {
                    "default": 1024, "min": SIZE_MIN, "max": SIZE_MAX, "step": 16,
                    "tooltip": "画布高度；调它时宽度会按画幅比例自动跟随（步长 = 对齐倍数）",
                }),
                "multiple": ("INT", {
                    "default": 16, "min": MULTIPLE_MIN, "max": MULTIPLE_MAX, "step": 4,
                    "tooltip": "对齐倍数：画布宽高、图片位置与尺寸都必须是它的整数倍（扩散 latent 才对得上）",
                }),
                "feathering": ("INT", {
                    "default": 0, "min": 0, "max": FEATHER_MAX, "step": 4,
                    "tooltip": (
                        "羽化：图片边缘内侧 N px 的遮罩渐变（官方 Pad Image for Outpaint 同款），"
                        "让接缝处的生成内容与原图平滑过渡。\n"
                        "0（默认）= 关闭，原图像素 100% 不变；接缝有硬边时试 16~64。"
                    ),
                }),
                "fill_color": ("STRING", {
                    "default": "#808080",
                    "multiline": False,
                    "tooltip": "外补区域的填充色（节点表面用色块选择器调，这里只存 #RRGGBB）",
                }),
                "resample": (RESAMPLE_OPTIONS, {
                    "default": "bicubic",
                    "tooltip": (
                        "图片被缩放时用的重采样算法（尺寸刚好一致时不重采样）：\n"
                        "bicubic = 双三次+抗锯齿（默认，通用）\n"
                        "lanczos = 最锐利，放大小图首选\n"
                        "area = 面积平均，缩小大图最干净\n"
                        "bilinear = 双线性，最快\n"
                        "nearest-exact = 最近邻精确版，像素画/硬边（不模糊）"
                    ),
                }),
                "layout": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "tooltip": "内部字段：可视化窗口的图片摆放（归一化值），请用鼠标在预览窗里拖拽 / 滚轮调整",
                }),
            },
            "optional": {
                "image": ("IMAGE", {"tooltip": "要放进画布的图片；不接则输出整块外补色画布"}),
                "mask": ("MASK", {"tooltip": "已有局部遮罩：与外补区取并集后输出（白色 = 需要生成）"}),
            },
        }

    RETURN_TYPES = ("IMAGE", "MASK", SEAM_TYPE)
    RETURN_NAMES = ("图像", "遮罩", "参数")
    FUNCTION = "render"
    CATEGORY = "XB_ToolBox/Image"
    DESCRIPTION = (
        "外补画板：按画幅比例 + 宽高铺一张对齐倍数的画布，把输入图片按可视化窗口里的"
        "摆放（拖拽 / 滚轮）贴进画布，外补区填设定颜色。输出图像 + 遮罩（外补区 1、图片区 0，"
        "接了「遮罩」输入时取并集）+ 「参数」（原图 / 原图尺寸 / 摆放矩形 / 羽化值，"
        "给「外补融合」精准贴回用）。可选羽化让接缝渐变过渡，缩放时可选择重采样算法。"
    )

    @classmethod
    def VALIDATE_INPUTS(cls, **kwargs):
        # 宽容校验：layout / fill_color 是前端自由字段，输入图片可能被上游断开，都不该拦住执行
        return True

    def render(self, aspect_ratio="自定义", width=1024, height=1024, multiple=16, feathering=0,
               fill_color="#808080", resample="bicubic", layout="", image=None, mask=None):
        m = _multiple(multiple)
        source = image if isinstance(image, torch.Tensor) and image.ndim == 4 else None

        if source is not None:
            source = source[..., :3].to(torch.float32).cpu()
            image_h, image_w = int(source.shape[1]), int(source.shape[2])
        else:
            image_h = image_w = 1

        canvas_w, canvas_h = board_size(aspect_ratio, width, height, m)
        batch = 1 if source is None else int(source.shape[0])

        fill = torch.tensor(parse_color(fill_color), dtype=torch.float32)
        canvas = fill.expand(batch, canvas_h, canvas_w, 3).clone()
        out_mask = torch.ones((batch, canvas_h, canvas_w), dtype=torch.float32)

        seam = {
            "v": SEAM_VERSION,
            "canvas": (canvas_w, canvas_h),
            "rect": None,
            "source": (image_w, image_h) if source is not None else None,
            "original": source,
            "feather": int(max(0, min(FEATHER_MAX, int(feathering or 0)))),
            "resample": resample,
            "fill": parse_color(fill_color),
        }

        if source is None:
            return {"ui": _preview_payload(None, out_mask), "result": (canvas, out_mask, seam)}

        x, y, box_w, box_h = placement(parse_layout(layout), canvas_w, canvas_h,
                                       image_w, image_h, m)
        seam["rect"] = (x, y, box_w, box_h)
        resized = _resize_image(source, box_w, box_h, resample)

        # 画布与图片矩形的交集（图片允许超出画布 = 裁剪）
        left, top = max(0, x), max(0, y)
        right, bottom = min(canvas_w, x + box_w), min(canvas_h, y + box_h)
        if right > left and bottom > top:
            crop = resized[:, top - y:top - y + (bottom - top),
                           left - x:left - x + (right - left), :]
            canvas[:, top:bottom, left:right, :] = crop
            out_mask[:, top:bottom, left:right] = 0.0

            if isinstance(mask, torch.Tensor) and mask.ndim >= 3 and mask.numel() > 0:
                source_mask = _match_batch(mask.to(torch.float32).cpu().reshape(
                    mask.shape[0], mask.shape[-2], mask.shape[-1]), batch)
                box_mask = _resize_mask(source_mask, box_w, box_h)
                region = box_mask[:, top - y:top - y + (bottom - top),
                                  left - x:left - x + (right - left)]
                existing = out_mask[:, top:bottom, left:right]
                out_mask[:, top:bottom, left:right] = torch.maximum(
                    existing, region.clamp(0.0, 1.0))

        # 羽化（可选）：图片内侧 N px 的遮罩渐变，0 = 不动
        _apply_feather(out_mask, left, top, right, bottom, box_w, box_h, x, y, feathering)

        # 前端预览：把「原图」和「最终遮罩」各存一张临时图，工作流一跑就能在节点里看到
        return {"ui": _preview_payload(source, out_mask), "result": (canvas, out_mask, seam)}


# ── 颜色还原（贴回时消除模型整体偏色）─────────────────────────────────────
def _color_match_offset(gen_region, ref_region, band, strength):
    """估一个「生成图 → 原图」的偏移量（每通道），只在模型基本没改动的像素上取中位数。

    gen_region / ref_region: [B, h, w, 3]，band: [h, w]（0 = 原图区，1 = 完全生成）。
    只在 band ≈ 0（模型不该动的地方）且颜色差很小的像素上统计，夹在 ±24/255 内。
    """
    if strength <= 0 or gen_region.numel() == 0:
        return None
    core = torch.from_numpy(band <= 0.02)
    if int(core.sum()) < 256:
        return None
    diff = (gen_region - ref_region).abs().amax(dim=-1)[:, core]        # [B, N]
    sel = diff <= (24.0 / 255.0)
    counts = sel.sum(dim=1)
    if int(counts.min()) < 256:
        return None
    offsets = []
    for b in range(gen_region.shape[0]):
        g = gen_region[b][core][sel[b]]
        r = ref_region[b][core][sel[b]]
        offsets.append((g - r).median(dim=0).values)
    offset = torch.stack(offsets).clamp(-24.0 / 255.0, 24.0 / 255.0)
    return (offset * float(strength)).view(-1, 1, 1, 3)


class XB_OutpaintMerge:
    """🖼️ 外补融合 —— 把生成好的外补画布按「参数」精准贴回原图，原图区逐位保留。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE", {
                    "tooltip": "采样 / 解码后的外补画布（尺寸应与「外补画板」输出的画布一致）",
                }),
                "seam": (SEAM_TYPE, {
                    "tooltip": "「外补画板」的「参数」输出：原图、原图尺寸、摆放矩形、羽化值",
                }),
                "sync_feather": ("BOOLEAN", {
                    "default": True,
                    "label_on": "跟随画板羽化",
                    "label_off": "自定义羽化",
                    "tooltip": "开启 = 直接用「参数」里记录的羽化值（和喂给模型的遮罩一致，接缝最自然）",
                }),
                "feather": ("INT", {
                    "default": 0, "min": 0, "max": FEATHER_MAX, "step": 4,
                    "tooltip": "关闭「跟随画板羽化」时用这个值：图片内侧 N px 渐变（0 = 硬边，原图区严格逐位保留）",
                }),
                "color_match": ("FLOAT", {
                    "default": 0.5, "min": 0.0, "max": 1.0, "step": 0.1,
                    "tooltip": "颜色还原强度：只统计模型基本没改动的像素估整体偏移，把接缝处的偏色拉回原图；0 = 关闭",
                }),
            }
        }

    RETURN_TYPES = ("IMAGE", "MASK")
    RETURN_NAMES = ("图像", "遮罩")
    FUNCTION = "merge"
    CATEGORY = "XB_ToolBox/Image"
    DESCRIPTION = (
        "把外补画布融合回原图：图片矩形内（羽化带以内）逐位使用原图像素，矩形外使用生成内容。"
        "用它兜住「模型改写原图」的问题——不管模型把原图画成什么样，原图区都不会变。"
    )

    @classmethod
    def VALIDATE_INPUTS(cls, **kwargs):
        return True

    def merge(self, image, seam, sync_feather=True, feather=0, color_match=0.5):
        info = seam if isinstance(seam, dict) else {}
        gen = image if isinstance(image, torch.Tensor) and image.ndim == 4 else None
        if gen is None:
            empty = torch.zeros((1, 64, 64), dtype=torch.float32)
            return (image, empty)

        gen = gen[..., :3].to(torch.float32).cpu()
        canvas_w, canvas_h = info.get("canvas") or (int(gen.shape[2]), int(gen.shape[1]))
        resample = info.get("resample") or "bicubic"
        if (int(gen.shape[2]), int(gen.shape[1])) != (canvas_w, canvas_h):
            print(f"[XB-BOX 外补融合] 生成图 {gen.shape[2]}×{gen.shape[1]} 与画布 "
                  f"{canvas_w}×{canvas_h} 不一致，已按画布尺寸重采样")
            gen = _resize_image(gen, canvas_w, canvas_h, resample)
        batch = int(gen.shape[0])

        original = info.get("original")
        rect = info.get("rect")
        if not isinstance(original, torch.Tensor) or original.ndim != 4 or not rect:
            # 没有原图（画板没接图）：生成内容原样输出，遮罩全 0（没有"生成覆盖原图"的区域）
            return (gen, torch.zeros((batch, canvas_h, canvas_w), dtype=torch.float32))

        feather_px = int(info.get("feather") or 0) if sync_feather else int(feather or 0)
        x, y, box_w, box_h = (int(v) for v in rect)
        box_w, box_h = max(1, box_w), max(1, box_h)

        out = gen.clone()
        out_mask = torch.ones((batch, canvas_h, canvas_w), dtype=torch.float32)

        left, top = max(0, x), max(0, y)
        right, bottom = min(canvas_w, x + box_w), min(canvas_h, y + box_h)
        if right <= left or bottom <= top:
            return (out.clamp(0.0, 1.0), out_mask)

        band = _seam_band(left, top, right, bottom, box_w, box_h, x, y, feather_px)
        if band is None:
            return (out.clamp(0.0, 1.0), out_mask)

        placed = _resize_image(_match_batch(original[..., :3].to(torch.float32).cpu(), batch),
                               box_w, box_h, resample)
        original_region = placed[:, top - y:top - y + (bottom - top),
                                 left - x:left - x + (right - left), :].clone()
        gen_region = gen[:, top:bottom, left:right, :]

        offset = _color_match_offset(gen_region, original_region, band, color_match)
        if offset is not None:
            gen_region = (gen_region - offset).clamp(0.0, 1.0)

        band_t = torch.from_numpy(band).to(torch.float32).unsqueeze(-1)     # [h, w, 1]
        out[:, top:bottom, left:right, :] = gen_region * band_t + original_region * (1.0 - band_t)
        out_mask[:, top:bottom, left:right] = torch.from_numpy(band)
        return (out.clamp(0.0, 1.0), out_mask)


NODE_CLASS_MAPPINGS = {
    "XB_OutpaintBoard": XB_OutpaintBoard,
    "XB_OutpaintMerge": XB_OutpaintMerge,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "XB_OutpaintBoard": "XB-BOX - 🖼️ 外补画板",
    "XB_OutpaintMerge": "XB-BOX - 🖼️ 外补融合",
}
