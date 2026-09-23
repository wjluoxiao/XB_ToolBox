"""XB-BOX - 🖼️ 生图提示词预设（提示词 + 空latent 一体化）。
================================================================================
一个节点顶替「提示词输入框 + 画幅比例节点 + 官方空 latent」三件套：

· 表面参数（顺序 = 节点上从上到下的显示顺序）：
    空latent类型 / 输出语言 / 预设模式 / 预设句（三视图·四视图·背景纯透明 三个模式显示）
    / 画幅比例 / 宽度 / 高度 / 生成数量
  —— 画幅比例 + 步长锁定 + 比例联动 100% 复刻本包「XB-BOX - 🖼️ 图片参数大全」
     （去掉强度(小数)/强度(整数)/缩放尺寸三项）
· 表面 6 个按钮（UI 在 js/xb_image_prompt_preset.js）：
     🏷️ 风格 ｜ 🎥 视角 ｜ 👤 主体 ｜ 🎬 姿态 ｜ 👚 装扮 ｜ 🎒 道具 ｜ 💡 光影 ｜ 🏞️ 背景
     每个按钮打开**该分类**的独立面板；面板顶部「分类签」切换子类
     （例：风格 → 真人/动画/3D/绘画插画/特殊风格），选项行 = ➕ ➖ 选项名 添加详细描述
· 输出①「提示词」= 预设句（人物三视图 / 人物四视图 / 背景纯透明；常规文生图无预设句）+ 正文（节点提示词框 ↔ 面板预览框双向同步）
· 输出②「空latent」= 主流模型直接可用的空 latent（选项名 = 模型名，规格按官方 latent_format；
  通道数 / 下采样除数 / 步长 / 上下限 / batch 上限 / downscale 元数据逐项对齐）：
     · Z-image   16 通道 · /8   · 步长 16  （官方 latent_format = Flux）
     · Flux2     128 通道 · /16 · 步长 16  （官方 EmptyFlux2LatentImage）
     · Qwen-image 16 通道 · /8  · 步长 32  （官方 latent_format = Wan21，采样时自动补 T 维；按用户要求锁 32）
     · Krea2     16 通道 · /8   · 步长 16  （官方 latent_format = Wan21）
     · Anima     16 通道 · /8   · 步长 8   （官方模板用 4 通道 EmptyLatentImage，零 latent 会被自动补齐）
     · Boogu     16 通道 · /8   · 步长 8   （同上，官方 latent_format = Flux）
     · SDXL      4 通道 · /8    · 步长 8   （官方 EmptyLatentImage）
     · SD3       16 通道 · /8   · 步长 16  （官方 EmptySD3LatentImage）
     · Hunyuan   64 通道 · /32  · 步长 32  （官方 EmptyHunyuanImageLatent / HunyuanImage 2.1）
  ⚠️ 通道/步长等专业细节只写在 tooltip 与控制台日志里，**不占选项文字**（保持选项名干净）。
  ⚠️ 全零 latent 即使类型选错也能跑：comfy/sample.py:fix_empty_latent_channels 会按模型补通道
     + 按 downscale_ratio_spacial 缩放尺寸 + 自动补 T 维；但选对类型少一步转换、更稳。

配置存法（与本包风格一致，不依赖任何后端接口）：
· `manager_settings`（内部字段，由前端面板隐藏，表面不显示）只存**元素面板配置 JSON**
  （已选词条 / 自建槽位 / 补充描述 / 自动保存），随工作流保存、节点间互不影响；
· `internal_prompt`（内部字段，同上前端隐藏）存提示词正文；
· 空latent类型 / 输出语言 / 预设模式 / 预设句 都是**节点表面参数**（随工作流保存）。
"""

import json
import math

import torch
import comfy.model_management
import nodes

# ── 画幅比例（与本包 XB_ImageParamsMaster 完全一致的选项顺序） ──────────────
ASPECT_RATIO_OPTIONS = ["Free", "1:1", "16:9", "9:16", "4:3", "3:4", "21:9"]
ASPECT_RATIO_MAP = {"1:1": 1.0, "16:9": 16 / 9, "9:16": 9 / 16,
                    "4:3": 4 / 3, "3:4": 3 / 4, "21:9": 21 / 9}
SIZE_STEP = 16            # 宽高步长的兜底值（实际以「空latent类型」的官方最小步长为准：8/16/32）
SIZE_MIN = 16
BATCH_MAX = 4096          # 官方 EmptyLatentImage / EmptySD3LatentImage 的 batch 上限
MAX_RESOLUTION = int(getattr(nodes, "MAX_RESOLUTION", 16384) or 16384)

# ── 面板枚举（字符串即存储值，前端面板与后端按同一份字符串对齐） ────────────
OUTPUT_LANGS = ["中文 [ZH]", "英文 [EN]"]
PRESET_MODES = ["常规文生图", "人物三视图", "人物四视图", "背景纯透明"]

LANG_ZH = OUTPUT_LANGS[0]
MODE_TEXT2IMG = PRESET_MODES[0]
MODE_THREE_VIEW = PRESET_MODES[1]
MODE_FOUR_VIEW = PRESET_MODES[2]
MODE_TRANSPARENT = PRESET_MODES[3]

# ── 主流模型的空 latent 规格表（逐项抄自 ComfyUI：comfy/latent_formats.py + 官方空 latent 节点）──
# 选项文字 = 模型名（干净，不带专业参数；细节放 tooltip 与日志）；规格仍完整保留以保证对得上模型：
#   每行： (选项名, 通道数, 下采样除数_h, _w, 尺寸步长, 最小, 最大, batch上限, downscale_ratio_spacial)#   · 尺寸步长 = 各模型**官方最小步长**（= 下采样 × patch2）：
#     Anima/Boogu/SDXL = 8（/8）、Flux2 = 16（/16）、Krea2/SD3/Z-image = 16（/8×patch2）、
#     Qwen-image = 32（用户指定：Qwen 系工作流习惯锁 32）、Hunyuan = 32（/32）。
#     不做全局统一的 32，避免把 1080 这类尺寸无谓地顶到 1088。#   · downscale_ratio_spacial = 官方 EmptyLatentImage/EmptySD3 带回的元数据（供
#     comfy/sample.py:fix_empty_latent_channels 判断是否需要缩放尺寸）
_OFFICIAL_LATENT_ROWS = [
    ("Anima",       16, 8,  8,  8,  16, MAX_RESOLUTION, 4096, 8),
    ("Boogu",       16, 8,  8,  8,  16, MAX_RESOLUTION, 4096, 8),
    ("Flux2",      128, 16, 16, 16, 16, MAX_RESOLUTION, 4096, 16),
    ("Hunyuan",     64, 32, 32, 32, 64, MAX_RESOLUTION, 4096, 32),
    ("Krea2",       16, 8,  8,  16, 16, MAX_RESOLUTION, 4096, 8),
    ("Qwen-image",  16, 8,  8,  32, 32, MAX_RESOLUTION, 4096, 8),
    ("SD3",         16, 8,  8,  16, 16, MAX_RESOLUTION, 4096, 8),
    ("SDXL",        4,  8,  8,  8,  16, MAX_RESOLUTION, 4096, 8),
    ("Z-image",     16, 8,  8,  16, 16, MAX_RESOLUTION, 4096, 8),
]

LATENT_KINDS = [row[0] for row in _OFFICIAL_LATENT_ROWS]
LATENT_KIND_SPEC = {
    row[0]: {
        "label": row[0], "channels": row[1], "h_div": row[2], "w_div": row[3],
        "step": row[4], "min": row[5], "max": row[6], "batch_max": row[7],
        "downscale": row[8],
    }
    for row in _OFFICIAL_LATENT_ROWS
}
# 默认值固定为 Z-image（不随选项排序变化，保证老工作流/默认体验不变）
DEFAULT_LATENT_KIND = "Z-image"
# 各预设模式的默认预设句（可编辑字段 three_view_text 的默认值）：按「预设模式 × 输出语言」给。
# · 常规文生图 = 无预设句（原样输出正文，用户完全可控）
# · 人物三视图 / 人物四视图 / 背景纯透明 = 成句时自动把预设句拼在正文前（中文「。」/英文 ". "）
PRESET_TEXT = {
    MODE_THREE_VIEW: {
        LANG_ZH: "生成平行排列的角色概念设计图，画面从左到右由四个独立面板组成："
                 "第一个面板是角色面部的精细特写肖像，第二个面板是人物正面全身站姿，"
                 "第三个面板是人物侧面全身站姿，第四个面板是人物背面全身站姿。",
        OUTPUT_LANGS[1]: "Generate a character concept design sheet arranged in parallel panels, "
                         "the image is composed of four separate panels from left to right: "
                         "the first panel is a finely detailed close-up portrait of the character's face, "
                         "the second panel is a full-body front standing pose, "
                         "the third panel is a full-body side standing pose, "
                         "the fourth panel is a full-body back standing pose.",
    },
    MODE_FOUR_VIEW: {
        LANG_ZH: "生成四宫格排列的角色概念设计图，画面左上角面板是角色面部的精细特写肖像，"
                 "画面右上角面板是角色面部侧面的的精细特写肖像，"
                 "画面左下角面板是无头部人物正面衣着展示图，画面右下角面板是人物背面全身站姿。",
        OUTPUT_LANGS[1]: "Generate a character concept design sheet arranged in a 2x2 grid, "
                         "the top-left panel is a finely detailed close-up portrait of the character's face, "
                         "the top-right panel is a finely detailed close-up profile portrait of the character's face, "
                         "the bottom-left panel is a headless front-facing outfit display view, "
                         "the bottom-right panel is a full-body back standing pose.",
    },
    MODE_TRANSPARENT: {
        LANG_ZH: "生成一张具有透明度的 RGBA 格式图像，包含 Alpha 通道，背景为纯透明。",
        OUTPUT_LANGS[1]: "Generate an RGBA image with an alpha channel and a fully transparent background.",
    },
}
# 兼容旧引用（三视图预设句）
THREE_VIEW_TEXT = PRESET_TEXT[MODE_THREE_VIEW]

# 元素分类白名单（必须与 js/xb_image_prompt_preset.js 的 CATEGORIES 顺序逐字一致；
# 自测会断言两者相等）。这里只用来过滤配置里的脏数据。
# 顺序 = 节点上 8 个按钮的顺序：风格 / 视角 / 主体 / 姿态 / 装扮 / 道具 / 光影 / 背景
# （必须与 js/xb_image_prompt_preset.js 的 CAT_ORDER 完全一致，自测会断言）
ELEMENT_CATEGORIES = ("prefix", "angle", "subject", "action", "clothes", "props", "environment", "background")


# ============================================================================
# 配置读写（None / 缺字段 / 非法值一律安全兜底）
# ============================================================================
def _default_settings():
    """节点默认配置（与前端 js/xb_image_prompt_preset.js 的 defaultSettings() 一一对应）。

    ⚠️ 自 0.9.x 起：输出语言 / 预设模式 / 预设句 / 空latent类型 已上提为**节点表面参数**，
    不再存在这份 JSON 里（JSON 只留元素面板配置 + 自动保存开关）。
    """
    return {
        "auto_save": True,
        "elements": {
            "selected": {},   # {分类: [词条 key, ...]}（有序，决定「按选择重建」的拼接顺序）
            "custom": {},     # {分类: [{"key":..., "zh":..., "en":...}, ...]} 用户自建槽位
            "noted": {},      # {"分类|key": "用户补充描述"}（稀疏：只存非空）
        },
    }


def _as_dict(value):
    return value if isinstance(value, dict) else {}


def _as_list(value):
    return value if isinstance(value, list) else []


def _as_str(value, default=""):
    return value if isinstance(value, str) else default


def _pick(options, value, default):
    """把配置值归一到合法枚举（缺失/None/非法 → default）。"""
    v = _as_str(value).strip()
    return v if v in options else default


def _parse_settings(raw):
    """manager_settings(JSON 字符串) → 完整配置；任何异常都退回默认，绝不让节点崩。"""
    cfg = _default_settings()
    if isinstance(raw, dict):
        data = raw
    else:
        try:
            data = json.loads(raw) if (raw or "").strip() else {}
        except Exception:
            data = {}
    if not isinstance(data, dict):
        data = {}

    if isinstance(data.get("auto_save"), bool):
        cfg["auto_save"] = data["auto_save"]

    el = _as_dict(data.get("elements"))
    sel = {}
    for cat, keys in _as_dict(el.get("selected")).items():
        # 只认白名单分类 + 只收字符串 key + 去重（脏数据一律丢，不让它影响拼装）
        if str(cat) not in ELEMENT_CATEGORIES:
            continue
        seq = []
        for k in _as_list(keys):
            if not isinstance(k, str):
                continue
            k = k.strip()
            if k and k not in seq:
                seq.append(k)
        if seq:
            sel[str(cat)] = seq
    cfg["elements"]["selected"] = sel

    cus = {}
    for cat, items in _as_dict(el.get("custom")).items():
        if str(cat) not in ELEMENT_CATEGORIES:
            continue
        seq = []
        seen = set()
        for it in _as_list(items):
            if not isinstance(it, dict):
                continue
            k = _as_str(it.get("key")).strip()
            if not k or k in seen:
                continue
            seen.add(k)
            seq.append({"key": k, "zh": _as_str(it.get("zh")), "en": _as_str(it.get("en"))})
        if seq:
            cus[str(cat)] = seq
    cfg["elements"]["custom"] = cus

    noted = {}
    for key, desc in _as_dict(el.get("noted")).items():
        d = _as_str(desc).strip()
        if d:
            noted[str(key)] = d
    cfg["elements"]["noted"] = noted
    return cfg


# ============================================================================
# 画幅比例 + 步长联动（与 XB_ImageParamsMaster.process 逐行等价）
# ============================================================================
def _round_step(value, step=SIZE_STEP, min_size=SIZE_MIN, max_size=MAX_RESOLUTION):
    """按 step 四舍五入并钳制上下限。

    ⚠️ 必须用 `floor(x + 0.5)` 而不是 Python 内置 `round()`：
    Python 的 round 是「银行家舍入」（round-half-to-even，`round(62.5) == 62`），
    而前端用的是 JS `Math.round`（`Math.round(62.5) == 63`，四舍五入）。
    两者在 x.5 处会差一个步长（1000px → Python 992 / JS 1008），会让节点表面与
    执行结果不一致（同一工作流重跑一次尺寸就变）。这里统一按 JS 语义，保证所见即所得。
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        v = step
    if v != v:  # NaN
        v = step
    n = int(math.floor(v / step + 0.5)) * step
    return max(min_size, min(max_size, n))


def latent_kind_spec(label):
    """下拉值 → 官方规格 dict（未知值/缺省/None → 默认 4 通道，老工作流不会崩）。"""
    return LATENT_KIND_SPEC.get(str(label or ""), LATENT_KIND_SPEC[DEFAULT_LATENT_KIND])


def latent_step_of(label):
    """该空 latent 类型的尺寸步长（前端画幅联动用同一套值）。"""
    return int(latent_kind_spec(label)["step"])


def latent_shape_of(label, width, height, batch_size=1):
    """该模型下最终 latent 张量形状（元组；只用于日志与自测，不参与计算）。"""
    spec = latent_kind_spec(label)
    w = _round_step(width, spec["step"], spec["min"], spec["max"])
    h = _round_step(height, spec["step"], spec["min"], spec["max"])
    b = max(1, min(spec["batch_max"], int(batch_size or 1)))
    return (b, spec["channels"], max(1, h // spec["h_div"]), max(1, w // spec["w_div"]))


def normalize_size(aspect_ratio, width, height, step=SIZE_STEP,
                   min_size=SIZE_MIN, max_size=MAX_RESOLUTION):
    """按画幅比例归一宽高：Free 只做步长锁定；固定比例以「输入中较大的一边」为基准反算另一边。

    与前端 js/xb_image_prompt_preset.js 的 snapFromWidth/snapFromHeight 结果一致（幂等）：
    前端负责「按你正在改的那一边为基准」即时联动，后端只做无方向归一，两者对已联动过的
    数值不产生二次改动。step/min/max 由当前空 latent 类型决定（官方各节点步长并不相同）。
    """
    w = _round_step(width, step, min_size, max_size)
    h = _round_step(height, step, min_size, max_size)
    if "Free" in _as_str(aspect_ratio):
        return w, h
    ratio = ASPECT_RATIO_MAP.get(_as_str(aspect_ratio).strip())
    if not ratio:
        return w, h
    if w >= h:
        safe_w = w
        safe_h = _round_step(safe_w / ratio, step, min_size, max_size)
    else:
        safe_h = h
        safe_w = _round_step(safe_h * ratio, step, min_size, max_size)
    return safe_w, safe_h


def build_empty_latent(latent_kind, width, height, batch_size=1):
    """主流模型的空 latent（形状/下采样/步长/上下限逐项对齐官方 latent_format）。

    形状恒为 [B, C, H//h_div, W//w_div]，并带回 `downscale_ratio_spacial`（官方
    EmptyLatentImage / EmptySD3LatentImage 同款元数据），让
    `comfy/sample.py:fix_empty_latent_channels` 能正确判断尺寸是否需要缩放：
      · 尺寸与模型声明一致 → 不缩放；选错类型则按比例自动缩放（全零 latent 可自由转换）
      · 通道数不一致时官方会把零通道 repeat 到模型通道数 → 选错也不会崩
    零张量 dtype 不影响结果（采样器统一 cast），统一用 intermediate_device。
    """
    spec = latent_kind_spec(latent_kind)
    step, min_size, max_size = spec["step"], spec["min"], spec["max"]
    w = _round_step(width, step, min_size, max_size)
    h = _round_step(height, step, min_size, max_size)
    b = max(1, min(int(spec["batch_max"]), int(batch_size or 1)))
    z = torch.zeros(
        [b, int(spec["channels"]),
         max(1, h // int(spec["h_div"])), max(1, w // int(spec["w_div"]))],
        device=comfy.model_management.intermediate_device(),
    )
    out = {"samples": z}
    if spec["downscale"]:
        out["downscale_ratio_spacial"] = int(spec["downscale"])
    return out


# ============================================================================
# 提示词拼装
# ============================================================================
def build_prompt(lang, preset_mode, three_view_text, body):
    """预设句（人物三视图 / 人物四视图 / 背景纯透明） + 正文，按输出语言使用合适的分句符。

    正文 = 节点表面提示词框（也等于面板预览框，两者双向同步）。
    常规文生图：预设句不参与 → 原样输出正文（保持用户完全可控）。
    """
    core = (body if isinstance(body, str) else "").strip()
    mode = _pick(PRESET_MODES, preset_mode, PRESET_MODES[0])
    defaults = PRESET_TEXT.get(mode)
    if not defaults:
        return core
    lg = _pick(OUTPUT_LANGS, lang, LANG_ZH)
    preset = _as_str(three_view_text).strip() or defaults[lg]
    if not core:
        return preset
    if lg == OUTPUT_LANGS[1]:
        return preset.rstrip(".").rstrip() + ". " + core
    return preset.rstrip("。．.").rstrip() + "。" + core


# ============================================================================
# 节点
# ============================================================================
class XB_ImagePromptPreset:
    """XB-BOX - 🖼️ 生图提示词预设：画幅参数 + 提示词拼装 + 官方空 latent 一体化。

    · 表面参数顺序 = 输出语言 / 预设模式 / 空latent类型 / 预设句（三视图·四视图·背景纯透明 显示）
      / 画幅比例 / 宽度 / 高度 / 生成数量；
    · 「提示词」输出 = 预设句（人物三视图）+ 节点提示词框正文；
    · 「空latent」输出 = 官方空 latent（见 LATENT_KINDS，共 9 种，逐字段对齐，选项按首字母排列）。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                # ── 空latent 类型放最顶（用户要求）──
                "latent_kind": (list(LATENT_KINDS), {
                    "default": DEFAULT_LATENT_KIND,
                    "tooltip": "空latent类型：选你正在用的模型即可（自动适配形状/下采样/步长）。\n"
                               "Z-image 16ch·/8·16　Flux2 128ch·/16·16　Qwen-image 16ch·/8·32\n"
                               "Krea2 16ch·/8·16　Anima 16ch·/8·8　Boogu 16ch·/8·8\n"
                               "SDXL 4ch·/8·8　SD3 16ch·/8·16　Hunyuan 64ch·/32·32\n"
                               "（步长 = 各模型官方最小步长，仅 Qwen-image 按需求锁 32；通道/下采样同样按官方 latent_format）",
                }),
                # ── 以下 3 项由原「⚙️ 输出设置」面板上提为节点表面参数 ──
                "output_lang": (list(OUTPUT_LANGS), {
                    "default": LANG_ZH,
                    "tooltip": "输出语言：影响预设句、元素拼装分隔符（面板里新加入的词条也按此语言）",
                }),
                "preset_mode": (list(PRESET_MODES), {
                    "default": PRESET_MODES[0],
                    "tooltip": "预设模式：常规文生图=只输出正文（完全可控）；"
                               "人物三视图 / 人物四视图 / 背景纯透明 = 成句自动在正文前加对应预设句"
                               "（下方预设句框仅这三个模式显示，切模式时未改过的默认句会自动跟随）",
                }),
                "three_view_text": ("STRING", {
                    "default": THREE_VIEW_TEXT[LANG_ZH], "multiline": True,
                    "tooltip": "预设句（人物三视图 / 人物四视图 / 背景纯透明 三个模式生效；常规文生图时本框自动隐藏）",
                }),
                "aspect_ratio": (list(ASPECT_RATIO_OPTIONS), {
                    "default": "Free",
                    "tooltip": "画幅比例：Free=自由（仅按步长锁定）；固定比例时以输入中较大的一边为基准，"
                               "自动反算另一边并锁定到步长倍数（与「图片参数大全」完全一致）",
                }),
                "width": ("INT", {
                    "default": 1024, "min": SIZE_MIN, "max": MAX_RESOLUTION, "step": SIZE_STEP,
                    "tooltip": "图片宽度（像素）。固定比例下改宽度会按比例重算高度；步长按「空latent类型」的官方最小步长"
                               "（SDXL/Anima/Boogu=8，Flux2/Krea2/SD3/Z-image=16，Qwen-image/Hunyuan=32）",
                }),
                "height": ("INT", {
                    "default": 1024, "min": SIZE_MIN, "max": MAX_RESOLUTION, "step": SIZE_STEP,
                    "tooltip": "图片高度（像素）。固定比例下改高度会按比例重算宽度；步长按「空latent类型」的官方最小步长（8/16/32）",
                }),
                "batch_size": ("INT", {
                    "default": 1, "min": 1, "max": BATCH_MAX,
                    "tooltip": "一次生成的图片数量（空 latent 的 batch 维度）",
                }),
                # ↓ 两个内部字段：节点表面由前端面板（js/xb_image_prompt_preset.js 的 hideInternal）隐藏。
                #   不再用 advanced=True —— 它会让前端在节点底部挂一个「显示高级输入」开关，
                #   而那里面只有这两个已被隐藏的字段，点了没有任何可见变化（用户反馈纯碍眼）。
                "internal_prompt": ("STRING", {
                    "default": "", "multiline": True,
                    "tooltip": "节点内编辑的提示词正文（与元素面板的预览框双向同步，随工作流保存）。"
                               "人物三视图 / 人物四视图 / 背景纯透明模式下，本字段前面会自动拼上对应预设句",
                }),
                "manager_settings": ("STRING", {
                    "default": "", "multiline": True,
                    "tooltip": "本节点独立保存的元素面板配置 JSON（已选词条 / 自建槽位 / 补充描述），"
                               "随工作流保存，节点间互不影响",
                }),
            }
        }

    RETURN_TYPES = ("STRING", "LATENT")
    RETURN_NAMES = ("提示词", "空latent")
    FUNCTION = "generate"
    CATEGORY = "XB_ToolBox/Image_Params"
    DESCRIPTION = ("生图提示词预设：空latent类型（主流模型一键适配 Z-image/Flux2/Qwen-image/Krea2/"
                   "Anima/Boogu/SDXL/SD3/Hunyuan）+ 输出语言/预设模式 + 画幅比例/宽度/高度/生成数量"
                   "（步长按各模型官方最小步长 8/16/32 + 比例联动）＋ 提示词拼装（8 大类：风格/视角/主体/姿态/穿搭/道具/光影/背景）。"
                   "输出：①提示词 ②空latent。")

    @classmethod
    def IS_CHANGED(cls, manager_settings="", **kwargs):
        """任一表面参数/提示词/配置变化都让缓存失效（保证改参数即重跑）。"""
        keys = ("output_lang", "preset_mode", "latent_kind", "three_view_text",
                "aspect_ratio", "width", "height", "batch_size", "internal_prompt")
        sig = {k: kwargs.get(k) for k in keys}
        return f"{manager_settings}|{sig}"

    def generate(self, output_lang, preset_mode, latent_kind, three_view_text, aspect_ratio,
                 width, height, batch_size, internal_prompt="", manager_settings=""):
        # ① 画幅归一：步长/上下限按当前空 latent 类型（官方各节点并不一致）
        spec = latent_kind_spec(latent_kind)
        w, h = normalize_size(aspect_ratio, width, height,
                              spec["step"], spec["min"], spec["max"])

        # ② 空 latent（官方同款张量）
        latent = build_empty_latent(latent_kind, w, h, batch_size)

        # ③ 提示词（预设句 + 正文）
        prompt = build_prompt(output_lang, preset_mode, three_view_text, internal_prompt)

        # ④ 控制台日志（节点表面不再有信息行，调试信息只打日志）
        try:
            shape = tuple(latent.get("samples").shape)
        except Exception:
            shape = ()
        print(f"[XB-生图提示词预设] {spec['label']} 丨 {w}x{h}（{aspect_ratio}·步长 {spec['step']}）"
              f"丨数量 {shape[0] if shape else batch_size}丨空latent {shape}"
              f"丨模式 {preset_mode}丨语言 {output_lang}丨提示词 {len(prompt)} 字")
        if prompt:
            print(f"[XB-生图提示词预设] 提示词：{prompt[:200]}{'…' if len(prompt) > 200 else ''}")

        return (prompt, latent)


# 供自测脚本直接调用（避免依赖私有名）
__all__ = [
    "XB_ImagePromptPreset",
    "ASPECT_RATIO_OPTIONS", "ASPECT_RATIO_MAP", "SIZE_STEP", "SIZE_MIN", "MAX_RESOLUTION",
    "BATCH_MAX", "OUTPUT_LANGS", "PRESET_MODES", "PRESET_TEXT", "THREE_VIEW_TEXT",
    "LATENT_KINDS", "LATENT_KIND_SPEC", "DEFAULT_LATENT_KIND", "ELEMENT_CATEGORIES",
    "default_settings", "parse_settings", "round_step", "normalize_size",
    "latent_kind_spec", "latent_step_of", "latent_shape_of",
    "build_empty_latent", "build_prompt",
]

# 别名：公开名与私有名同体（自测脚本可读，节点内部继续用下划线短名）
default_settings = _default_settings
parse_settings = _parse_settings
round_step = _round_step
