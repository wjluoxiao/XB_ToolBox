"""
XB-BOX - 🖼️ 生图提示词预设Pro
=================================
融合「XB-BOX - 🖼️ 生图提示词预设」与「XB-llama - ✨ 提示词增强反推」两个节点：

① 生图预设（原节点全部能力）
   · 空latent类型（9 种主流模型，逐字段对齐官方 latent_format）
   · 输出语言 / 预设模式 / 设定词（三视图·四视图·五视图·背景纯透明）
       - 设定词既作为 LLM 的**增强参考**，也（启用 LLM 时）被**原封不动**加在最终提示词最顶端；
       - 用户改过的设定词按「模式 + 语言」存在本节点里，换模式 / 换语言都不会丢。
   · 画幅比例 / 宽度 / 高度 / 生成数量（步长按模型官方最小步长 8/16/32 + 比例联动）
   · 元素面板提示词拼装（8 大类词表，前端 js/xb_image_prompt_preset_pro.js）

② 提示词增强反推（原节点全部能力）
   · LLM 后端：本地 llama-cpp-python / 在线 API（配置存 ComfyUI user 目录，Key 不进工作流）
   · 增强预设（= 提示词设定）、反推预设、追加设定、输出语言
   · 采样参数、运行方式（推理模式 / 最大帧数 / 最大尺寸 / 保存对话状态 / 状态 UID）
   · 生成后控制（随机 / 固定 / 增加 / 减少，运行后回写种子）
   · 输入端口：📝 提示词、🖼️ 图像

开关 `use_llm`（节点表面可见）：
   · 关（默认）= 原「生图提示词预设」行为：只输出拼装好的提示词 + 空latent（不加载模型、不调 API）
   · 开 = 把（外接「提示词」端口 或 节点上拼装好的提示词）+ 外接「图像」交给 LLM 反推

输出：提示词（最终）/ 空latent / 提示词列表 / 提示词设定
（两个旧节点全部保留，本节点只是融合超集）

CATEGORY: XB_ToolBox/Image_Params
"""

import json
import math
import random
import re
import sys

import nodes
import torch
import comfy.model_management

from .nodes_llama import (
    LLAMA_CPP_STORAGE,
    XB_llamaInstruct,
    XB_llamaPromptEnhancer,
    preset_tags,
)
from .nodes_llama_prompt_reverse import (
    OUTPUT_FORMAT_HINT,
    _LANG_HINT,
    _OUTPUT_LANGS,
    _SEED_MAX,
    build_api_config,
    parse_settings as parse_llm_settings,
    strip_reasoning,
)

from . import xb_presets

# SKILL（技能文件 = LLM 的 system prompt，放 xb_skill/skills）
from .xb_skills import SKILL_NONE, skill_list, skill_sig, skill_text

# ════════════════════════════════════════════════════════════════════════════
#  本节点自带副本（精简版）：预设模式 / 预设文本 / 空latent 规格 / SKILL 三态
#  ⚠️ 与「生图提示词预设」「Qwen2.1提示词预设」**完全独立**：
#     这里只有 4 档模式（无预设 + 三·四·五视图）、固定文生图、不含任何图生图档位与条款。
#     改这里不会影响任何别的节点（也不受别的节点影响）。
# ════════════════════════════════════════════════════════════════════════════
# ── 画幅比例（与本包 XB_ImageParamsMaster 完全一致的选项顺序） ──────────────
ASPECT_RATIO_OPTIONS = ["Free", "1:1", "16:9", "9:16", "4:3", "3:4", "21:9", "2:3", "3:2"]
ASPECT_RATIO_MAP = {"1:1": 1.0, "16:9": 16 / 9, "9:16": 9 / 16,
                    "4:3": 4 / 3, "3:4": 3 / 4, "21:9": 21 / 9, "2:3": 2 / 3, "3:2": 3 / 2}
SIZE_STEP = 16            # 宽高步长的兜底值（实际以「空latent类型」的官方最小步长为准：8/16/32）
SIZE_MIN = 16
BATCH_MAX = 4096          # 官方 EmptyLatentImage / EmptySD3LatentImage 的 batch 上限
MAX_RESOLUTION = int(getattr(nodes, "MAX_RESOLUTION", 16384) or 16384)

OUTPUT_LANGS = ["中文 [ZH]", "英文 [EN]"]

# ── 预设模式（无预设 + xb_skill 预设文件；本节点**固定文生图**）────────────────
# 选项与「🖼️ 生图提示词预设」完全同步（同一批 txt），文件缺失时回落到内置档位名。
# ⚠️ 这里的字符串就是工作流里的存储值，改名必须同步 MODE_ALIASES
PRESET_NODE_NAME = "XB_ImagePromptPreset"
_BUILTIN_PRESET_MODES = [
    "无预设", "人物三视图", "人物四视图", "人物五视图", "背景纯透明",
    "图文版面", "信息图", "多格分镜", "广告分镜板",
    "保持主体换场景", "局部编辑", "老照片修复", "整图风格化", "360°全景", "多图指认合成",
]


def preset_lang_folder(output_lang=None):
    """「输出语言」下拉值 → 预设文件语言目录（中文 [ZH] → ZH，其余 → EN）"""
    return xb_presets.ZH if output_lang == LANG_ZH else xb_presets.EN


def preset_modes():
    """「预设模式」下拉选项：无预设 + 预设文件里的全部选项（与基础节点同一批 txt）"""
    try:
        labels = xb_presets.preset_labels(PRESET_NODE_NAME)
    except Exception:
        labels = []
    return ["无预设"] + (labels if labels else _BUILTIN_PRESET_MODES[1:])


PRESET_MODES = preset_modes()

LANG_ZH = OUTPUT_LANGS[0]
MODE_TEXT2IMG = "无预设"
MODE_THREE_VIEW = "人物三视图"
MODE_FOUR_VIEW = "人物四视图"
MODE_FIVE_VIEW = "人物五视图"

# 兼容：早期版本档位名带表情 / 旧名（工作流里可能存着旧值）→ 归一为当前档位名
MODE_ALIASES = {
    "常规文生图": "无预设",
    "📱 图文版面": "图文版面",
    "📊 信息图": "信息图",
    "🎞 多格分镜": "多格分镜",
    "🎬 广告分镜板": "广告分镜板",
    "🛍 保持主体换场景": "保持主体换场景",
    "✏️ 局部编辑": "局部编辑",
    "🧹 老照片修复": "老照片修复",
    "🎨 整图风格化": "整图风格化",
    "🌐 360°全景": "360°全景",
    "🗂 多图指认合成": "多图指认合成",
}


def normalize_mode(preset_mode):
    """把各种历史/非法值归一为当前档位名（认不出来就保持原样，由上层 _pick 兜底）"""
    m = _as_str(preset_mode).strip()
    return MODE_ALIASES.get(m, m)


# Pro 固定文生图：不存在「必须接输入图」的档位
MODE_NEEDS_IMAGE = []


def mode_needs_image(preset_mode):
    """该预设模式是否必须接输入图（Pro 无此概念 → 恒 False）"""
    return False


def mode_skill_hint(preset_mode):
    """该预设模式推荐搭配的 SKILL 文件（Pro 固定文生图 → 只推荐 prompt_t2i）"""
    return "system_prompt_t2i.txt"
# ── SKILL 三态：不用 / 手动 / 自动（默认自动）────────────────────────────
# · 自动 = 按当前预设模式自动适配（图生图档 → prompt_edit，其余 → prompt_t2i）
# · 手动 = 用节点上 skill_name 选中的那一个
# · 不用 = 完全不生效（哪怕 skill_name 选了也不生效）
SKILL_MODE_AUTO = "自动"
SKILL_MODE_MANUAL = "手动"
SKILL_MODE_OFF = "不用"
SKILL_MODES = [SKILL_MODE_AUTO, SKILL_MODE_MANUAL, SKILL_MODE_OFF]


def skill_mode_of(value):
    """归一 SKILL 模式（缺失 / None / 非法 → 自动）"""
    m = _as_str(value).strip()
    return m if m in SKILL_MODES else SKILL_MODE_AUTO


def effective_skill_name(skill_mode, skill_name, preset_mode):
    """本次实际会用到的 SKILL 文件名（供日志 / IS_CHANGED 用；不用 → 不使用）"""
    m = skill_mode_of(skill_mode)
    if m == SKILL_MODE_OFF:
        return SKILL_NONE
    if m == SKILL_MODE_MANUAL:
        return _as_str(skill_name).strip() or SKILL_NONE
    return mode_skill_hint(preset_mode)


def effective_skill_text(skill_mode, skill_name, preset_mode, use_default_template=True):
    """本次实际要送进模型的 SKILL 全文（不用 / 缺模型 / 关内置模板 → 空串）"""
    if not bool(use_default_template):
        return ""
    name = effective_skill_name(skill_mode, skill_name, preset_mode)
    if not name or name == SKILL_NONE:
        return ""
    return skill_text(name, "[XB-生图预设Pro]")


def safe_print(msg):
    """安全打印：控制台不是 UTF-8（如 Windows GBK 控制台）时把不可编码字符降级为 ? ，

    绝不因为一行带 emoji 的日志把节点执行搞崩（ComfyUI 官方启动器不一定切 UTF-8 代码页）。
    """
    try:
        print(msg)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        print(str(msg).encode(enc, "replace").decode(enc, "replace"))


# ── 主流模型的空 latent 规格表（逐项抄自 ComfyUI：comfy/latent_formats.py + 官方空 latent 节点）──
# 选项文字 = 模型名（干净，不带专业参数；细节放 tooltip 与日志）；规格仍完整保留以保证对得上模型：
#   每行： (选项名, 通道数, 下采样除数_h, _w, 尺寸步长, 最小, 最大, batch上限, downscale_ratio_spacial)
#   · 尺寸步长 = 各模型**官方最小步长**（= 下采样 × patch2）：
#     Anima/Boogu/SDXL = 8（/8）、Flux2 = 16（/16）、Krea2/SD3/Z-image = 16（/8×patch2）、
#     Qwen-image = 32（用户指定：Qwen 系工作流习惯锁 32）、Hunyuan = 32（/32）。
#     不做全局统一的 32，避免把 1080 这类尺寸无谓地顶到 1088。
#   · downscale_ratio_spacial = 官方 EmptyLatentImage/EmptySD3 带回的元数据（供
#     comfy/sample.py:fix_empty_latent_channels 判断是否需要缩放尺寸）
_OFFICIAL_LATENT_ROWS = [
    ("Anima",       16, 8,  8,  8,  16, MAX_RESOLUTION, 4096, 8),
    ("Boogu",       16, 8,  8,  8,  16, MAX_RESOLUTION, 4096, 8),
    ("Flux2",      128, 16, 16, 16, 16, MAX_RESOLUTION, 4096, 16),
    ("Flux3",      128, 16, 16, 16, 16, MAX_RESOLUTION, 4096, 16),   # 与 Flux2 同规格：只是给用户多一个选项
    ("Hunyuan",     64, 32, 32, 32, 64, MAX_RESOLUTION, 4096, 32),
    ("Krea2",       16, 8,  8,  16, 16, MAX_RESOLUTION, 4096, 8),
    ("Moss-image", 128, 16, 16, 16, 16, MAX_RESOLUTION, 4096, 16),   # 与 Flux2 同规格：只是给用户多一个选项
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
# · 无预设 = 不前置设定词（原样输出正文，用户完全可控）
# · 人物三视图 / 人物四视图 / 人物五视图 / 背景纯透明 = 成句时自动把预设句拼在正文前（中文「。」/英文 ". "）
# 各预设模式的默认预设句（可编辑字段 three_view_text 的默认值）：按「预设模式 × 输出语言」给。
# · 无预设 = 不前置设定词（原样输出正文，用户完全可控）
# · 人物三视图 / 人物四视图 / 人物五视图 / 背景纯透明 = 成句时自动把预设句拼在正文前（中文「。」/英文 ". "）
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
    MODE_FIVE_VIEW: {
        LANG_ZH: "生成五宫格排列的角色概念设计图，画面左上角面板是角色面部的精细特写肖像，"
                 "画面右上角面板是角色面部侧面的的精细特写肖像，"
                 "画面下方左侧面板是无头部人物正面衣着展示图，画面下方中间面板是无头部人物侧面衣着展示图，"
                 "画面下方右侧面板是人物背面全身站姿。",
        OUTPUT_LANGS[1]: "Generate a character concept design sheet arranged in five panels, "
                         "the top-left panel is a finely detailed close-up portrait of the character's face, "
                         "the top-right panel is a finely detailed close-up profile portrait of the character's face, "
                         "the bottom-left panel is a headless front-facing outfit display view, "
                         "the bottom-middle panel is a headless side-facing outfit display view, "
                         "the bottom-right panel is a full-body back standing pose.",
    },
}
THREE_VIEW_TEXT = PRESET_TEXT[MODE_THREE_VIEW]
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



def preset_text_for(preset_mode, output_lang=None):
    """某预设模式的**默认**设定词（先读 xb_skill 预设文件；无预设 → 永远 ""）"""
    mode = normalize_mode(preset_mode)
    lg = output_lang if output_lang in OUTPUT_LANGS else LANG_ZH
    if not mode or mode == MODE_TEXT2IMG:
        return ""
    try:
        txt = xb_presets.preset_text(PRESET_NODE_NAME, mode, preset_lang_folder(lg))
    except Exception:
        txt = ""
    if txt:
        return txt
    return PRESET_TEXT.get(mode, {}).get(lg, "")


def all_default_texts(preset_mode):
    """该模式**所有语言**的默认设定词（用于判断用户是否没改过 → 见 preset_text_of）

    · 无预设档额外算「默认」的还有：**所有内置 / 文件预设句**（节点上 three_view_text 的老默认值
      就是三视图预设句 → 无预设档必须当空白，不能当成用户的「自定义」继续前置）。
    """
    out = []
    for lg in OUTPUT_LANGS:
        t = preset_text_for(preset_mode, lg).strip()
        if t and t not in out:
            out.append(t)
    if normalize_mode(preset_mode) == MODE_TEXT2IMG:
        for texts in PRESET_TEXT.values():
            for t in texts.values():
                t = _as_str(t).strip()
                if t and t not in out:
                    out.append(t)
        try:
            for by_lang in xb_presets.all_preset_texts(PRESET_NODE_NAME).values():
                for t in (by_lang or {}).values():
                    t = _as_str(t).strip()
                    if t and t not in out:
                        out.append(t)
        except Exception:
            pass
    return out


def preset_text_of(preset_mode, output_lang, three_view_text):
    """最终生效的设定词（= 节点「设定词」框里的那段文本）。

    ⚠️ 「预设模式」下拉已取消：设定词完全由用户在面板里写 / 从预设词填入，
       这里原样返回（留空 = 不前置）。`preset_mode` 参数只为兼容旧调用保留。
    """
    return _as_str(three_view_text).strip()


def build_prompt(lang, preset_mode, three_view_text, body):
    """设定词 + 正文，按输出语言使用合适的分句符（Pro 不追加任何模版条款）

    · 正文 = 节点表面提示词框（与面板预览框双向同步）；
    · 设定词 = preset_text_of(...)：改过的用改过的，没改过则用该档默认；
    · 无预设档：设定词恒为空串（只输出正文）。
    """
    core = (body if isinstance(body, str) else "").strip()
    mode = normalize_mode(preset_mode) or MODE_TEXT2IMG
    lg = _pick(OUTPUT_LANGS, lang, LANG_ZH)
    preset = preset_text_of(mode, lg, three_view_text)
    if not preset:
        return core
    if not core:
        return preset
    if lg == OUTPUT_LANGS[1]:
        return preset.rstrip(".").rstrip() + ". " + core
    return preset.rstrip("。．.").rstrip() + "。" + core

DEFAULT_LANG = OUTPUT_LANGS[0]


def _llm_section(manager_settings):
    """从 manager_settings JSON 里取出 LLM 部分（原「提示词增强反推」的配置）"""
    if isinstance(manager_settings, dict):
        data = manager_settings
    elif isinstance(manager_settings, str) and manager_settings.strip():
        try:
            data = json.loads(manager_settings)
        except Exception:
            data = {}
    else:
        data = {}
    if not isinstance(data, dict):
        return {}
    sec = data.get("llm")
    return sec if isinstance(sec, dict) else {}


_REVERSE_SOURCES = ("skill", "preset")


def _reverse_section(manager_settings):
    """「提示词增强 → 设定词来源」（llm.reverse）：
    · skill  = 技能文档（xb_skill/skills）整段当系统提示词
    · preset = 预设词（用「增强预设 + 反推预设」两个下拉）
    缺失 / 非法一律回落 skill（老工作流行为不变）。
    """
    sec = _llm_section(manager_settings)
    raw = sec.get("reverse")
    if not isinstance(raw, dict):
        return {"source": "skill", "label": "", "text": ""}
    src = _as_str(raw.get("source")).strip().lower()
    return {
        "source": src if src in _REVERSE_SOURCES else "skill",
        "label": _as_str(raw.get("label")).strip(),
        "text": raw.get("text") if isinstance(raw.get("text"), str) else "",
    }


def _next_seed(seed, mode):
    """生成后控制：返回「下一次」种子（fixed 返回 None = 不回写）"""
    if mode == "randomize":
        return random.randint(0, _SEED_MAX)
    if mode == "increment":
        return (seed + 1) & _SEED_MAX
    if mode == "decrement":
        return (seed - 1) & _SEED_MAX
    return None


# ── 增强预设 / 反推预设 的文件化编辑 ────────────────────────────────────────
# 面板上「编辑增强预设 / 编辑反推预设」与「编辑预设」共用同一套 txt 目录约定：
#   xb_skill/XB_LLMEnhancerPreset/{ZH,EN}/*.txt   → 「增强预设」下拉可选项
#   xb_skill/XB_LLMTaskPreset/{ZH,EN}/*.txt       → 「反推预设」下拉可选项
# 同名文件优先于内置文案（内置只读，文件可随意改 / 新增 / 删除）。
LLM_ENHANCER_NODE = "XB_LLMEnhancerPreset"
LLM_TASK_NODE = "XB_LLMTaskPreset"


def _file_preset_labels(node_name):
    try:
        return list(xb_presets.preset_labels(node_name))
    except Exception:
        return []


def _file_preset_text(node_name, label, output_lang):
    try:
        return xb_presets.preset_text(node_name, label, preset_lang_folder(output_lang)) or ""
    except Exception:
        return ""


def enhancer_options():
    """「增强预设」下拉选项：内置 + xb_skill/XB_LLMEnhancerPreset 里的文件"""
    base = list(XB_llamaPromptEnhancer.INPUT_TYPES()["required"]["preset"][0])
    for lb in _file_preset_labels(LLM_ENHANCER_NODE):
        if lb not in base:
            base.append(lb)
    return base


def task_options():
    """「反推预设」下拉选项：内置 + xb_skill/XB_LLMTaskPreset 里的文件"""
    base = list(preset_tags)
    for lb in _file_preset_labels(LLM_TASK_NODE):
        if lb not in base:
            base.append(lb)
    return base


def enhancer_text(label, output_lang=None):
    """增强预设全文：文件优先，其次内置（读不到返回空串）"""
    if not label:
        return ""
    txt = _file_preset_text(LLM_ENHANCER_NODE, label, output_lang)
    if txt:
        return txt
    try:
        return XB_llamaPromptEnhancer().main(label)[0] or ""
    except Exception:
        return ""


def task_text(label, output_lang=None):
    """反推预设（任务模板）全文：文件优先，其次内置 preset_prompts"""
    if not label:
        return ""
    txt = _file_preset_text(LLM_TASK_NODE, label, output_lang)
    if txt:
        return txt
    try:
        from .nodes_llama import preset_prompts as _builtin
        return _builtin.get(label, "") or ""
    except Exception:
        return ""


def register_task_preset(label, output_lang=None):
    """把（可能来自文件的）反推预设注册进 llama 的 preset_prompts，供 process() 按名取用"""
    txt = task_text(label, output_lang)
    if not txt:
        return
    try:
        from . import nodes_llama as _nl
        _nl.preset_prompts[label] = txt
    except Exception:
        pass


# 「图 + 文字」时的任务说明：先识图 → 把文字当修改指令执行 → 只输出最终画面提示词
# （用户报障：接了图片 + 写了「把背景换成草地」时，模型输出「原本室内的背景被替换为…」这种描述+修改说明，
#   不能直接拿去文生图。这里把任务顺序与输出荘忌写死，让结果就是一条可直接生图的最终提示词。）
_TASK_IMAGE_EDIT_HINT = (
    "【任务：先识图，再按用户的修改指令改，只输出【修改后的最终画面提示词】】\n"
    "步骤（在内部完成，不要输出过程）：\n"
    "  ① 识别图像中的人物、外貌、服装、姿态、镜头、光线与背景；\n"
    "  ② 把用户给出的文字当作【修改指令】应用到识别结果上；\n"
    "  ③ 输出修改后最终画面的提示词。\n"
    "输出要求（必须遵守）：\n"
    "  · 只输出一段——直接描述【修改后的最终画面】，像一条全新的文生图提示词，可以直接拿去生图；\n"
    "  · 严禁对比式 / 过程式表述：不得出现「原本」「原来」「改在」「改成」「换成」「替换为」「被替换」"
    "「修改后」「而不是」「instead of」「replaced with」「originally」「now」等字样；\n"
    "  · 不得写成「先描述原图 + 再说明改了什么」两段，也不得保留任何关于修改动作的说明；\n"
    "  · 未被指令涉及的部分（人物长相、服装、姿态、镜头、光线）保持识别到的原样，"
    "自然地融进最终描述里，就像画面本来就是这样。"
)
# 只接了图片、没写文字：纯「看图写提示词」
_TASK_IMAGE_ONLY_HINT = (
    "【任务：看图写提示词】\n"
    "先识别画面内容，然后只输出一条可直接生图的最终提示词；"
    "不要输出识别过程、分析步骤、字段清单或任何说明。"
)
_USER_EDIT_PREFIX = "【修改指令（请将下列要求应用到图像上）】\n"
_USER_IMAGE_ONLY = "识别这张图片，直接输出最终画面的提示词。"
# 纯文字且正文为空：给 LLM 一个中性任务描述（绝不用「设定词」当输入，设定词不参与 LLM）
_USER_TEXT_EMPTY_HINT = "请直接输出一条完整、可直接用于文生图的画面提示词。"

# 看图改图任务的验收条件：输出里不得出现「先描述再修改」的对比式说法
_RETRY_REMINDER = (
    "\n\n【上次输出不合格，必须重写】上次出现了「原本 / 换成 / 被替换 / 修改后」这类对比式说明。"
    "请只输出修改后最终画面的直接描述，就像画面本来就是这样，不要提到任何修改动作。"
)
_FORBIDDEN_TALK_RE = re.compile(
    r"原本|原来的|被替换|替换为|替换成|改为|改成|换成|修改后|修改为|"
    r"instead of|replaced (?:with|by)|originally", re.I)


def _leaks_modification_talk(text):
    """输出里是否出现了对比式 / 过程式修改说明（看图改图任务不合格）"""
    return bool(_FORBIDDEN_TALK_RE.search(text or ""))


def _has_images(images):
    """是否真的接了图片 / 视频帧（None / 空张量 / 空列表 均视为没有）"""
    if images is None:
        return False
    try:
        return len(images) > 0
    except Exception:
        return True


def _build_system_prompt(preset, extra, output_lang, preset_text="", task_hint="", skill_text=""):
    """提示词设定 = 设定词来源（skill 文档）+ 增强预设 + 输出语言 + 追加设定
                  + 只输出最终提示词的硬规则 + 任务块

    `skill_text` 放**最前面**当角色与总规则（设定词来源 = skill 时的技能文件）；
    技能文件自带语言决策与输出契约 → 此时**不再叠加**节点的语言提示，避免互相打架。
    `preset` = 增强预设（设定词来源 = 预设词时用；skill 模式传空串 → 不叠加）。
              先读 xb_skill 里的同名预设文件，没有才用内置文案。
    `task_hint`（看图 / 改图任务）放**最末**，优先级最高——决定“先识图再改”还是“纯看图”。
    """
    skill = (skill_text or "").strip()
    parts = []
    if skill:
        parts.append(skill)                           # 反推预设：角色与总规则（自带语言 / 输出契约）
    # 增强预设：设定词来源 = skill 时传空串（技能文档已含完整规则，不叠加）
    preset_body = enhancer_text(preset, output_lang) if preset else ""
    if preset_body:
        parts.append(preset_body)
    if not skill:
        parts.append(_LANG_HINT.get(output_lang, _LANG_HINT[_OUTPUT_LANGS[0]]))
    extra = (extra or "").strip()
    if extra:
        parts.append(extra)
    parts.append(OUTPUT_FORMAT_HINT)                 # 放最后 = 最显眼（用户要求：不要思考过程）
    hint = (task_hint or "").strip()
    if hint:
        parts.append(hint)                            # 任务块更具体 → 又压在最上面
    return "\n\n".join([p for p in parts if p])


def _preset_text_of(preset_mode, output_lang, three_view_text):
    """当前预设模式的设定词（= 节点「设定词」框里的值）。

    · 本节点**固定文生图**：没有图生图那套设定词，也不追加以输入图为准的条款；
    · 用户改过 → 用改过的原文；
    · 没改过（等于任一默认）→ 用该档默认（防老工作流里残留的旧文本被当前置词）；
    · 无预设档：恒为空串（不前置设定词）。
    """
    return preset_text_of(preset_mode, output_lang, three_view_text)
    return str(three_view_text or "").strip() or defaults.get(lang, "") or ""


class XB_ImagePromptPresetPro:
    """生图提示词预设Pro = 生图预设（提示词拼装 + 空latent）+ LLM 提示词增强反推。"""

    _PRESETS = XB_llamaPromptEnhancer.INPUT_TYPES()["required"]["preset"][0]
    _DEFAULT_PRESET = "Z-Image Turbo [ZH]" if "Z-Image Turbo [ZH]" in _PRESETS else _PRESETS[0]
    _DEFAULT_TASK = "Normal - 描述 [ZH]" if "Normal - 描述 [ZH]" in preset_tags else preset_tags[0]

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                # ══ ① 生图预设（顺序与「🖼️ 生图提示词预设」保持一致）══
                "latent_kind": (list(LATENT_KINDS), {
                    "default": DEFAULT_LATENT_KIND,
                    "tooltip": "空latent类型：选你正在用的模型即可（自动适配形状/下采样/步长）",
                }),
                "output_lang": (list(OUTPUT_LANGS), {
                    "default": DEFAULT_LANG,
                    "tooltip": "输出语言：影响预设句、元素拼装分隔符，同时作为 LLM 的输出语言要求",
                }),
                "preset_mode": (preset_modes(), {
                    "default": MODE_TEXT2IMG,
                    "tooltip": "预设模式：无预设=不前置任何设定词，只输出正文；"
                               "其余档位把该档设定词置顶到最终提示词最顶端（选项与「🖼️ 生图提示词预设」同步，来自 xb_skill 预设 txt）",
                }),
                "three_view_text": ("STRING", {
                    "default": THREE_VIEW_TEXT[DEFAULT_LANG], "multiline": True,
                    "tooltip": "设定词：只在最终输出时原封不动加到提示词最上方（**不参与 LLM**）\n"
                               "· 留空 = 不前置；\n"
                               "· 可在「✨ 预设参数 → 设定词」里用「添加预设 / 编辑预设」维护",
                }),
                "skill_mode": (list(SKILL_MODES), {
                    "default": SKILL_MODE_AUTO,
                    "tooltip": "SKILL 模式（面板上不再直接暴露三态）：面板是「不使用 skill ／ 选文档」二选一；"
                               "自动 = 用该档推荐文档（本节点固定 prompt_t2i），手动 = 用选中的那份，不用 = 不生效",
                }),
                "skill_name": (skill_list(), {
                    "default": SKILL_NONE,
                    "tooltip": "SKILL选择：xb_skill/skills 里的 txt，整段作为 LLM 反推的 system prompt（放在最前面当角色与总规则）；"
                               "面板上是「不使用 skill / 选文档」二选一；技能文件自带语言与输出契约，选中后不再叠加节点的语言提示",
                }),
                "aspect_ratio": (list(ASPECT_RATIO_OPTIONS), {
                    "default": "Free",
                    "tooltip": "画幅比例：Free=自由（仅按步长锁定）；固定比例时按较大的一边反算另一边",
                }),
                "width": ("INT", {
                    "default": 1024, "min": SIZE_MIN, "max": MAX_RESOLUTION, "step": SIZE_STEP,
                    "tooltip": "图片宽度（步长按「空latent类型」的官方最小步长 8/16/32）",
                }),
                "height": ("INT", {
                    "default": 1024, "min": SIZE_MIN, "max": MAX_RESOLUTION, "step": SIZE_STEP,
                    "tooltip": "图片高度（步长按「空latent类型」的官方最小步长 8/16/32）",
                }),
                "batch_size": ("INT", {
                    "default": 1, "min": 1, "max": BATCH_MAX,
                    "tooltip": "一次生成的图片数量（空 latent 的 batch 维度）",
                }),
                # ══ ② 提示词增强反推 ══
                "use_llm": ("BOOLEAN", {
                    "default": False,
                    "label_on": "✅ 启用 LLM 反推", "label_off": "⛔ 关闭 LLM 反推",
                    "tooltip": "关（默认）= 只输出拼装好的提示词 + 空latent（不加载模型、不调 API）\n"
                               "开 = 把（外接「提示词」或节点上的提示词）+ 外接「图像」交给 LLM 反推",
                }),
                "backend": (["本地模型", "在线 API"], {
                    "default": "本地模型",
                    "tooltip": "本地模型 = llama-cpp-python；在线 API = 在「🤖 大语言模型配置」弹窗里填服务商/模型/Key/地址",
                }),
                "preset": (enhancer_options(), {
                    "default": ("Z-Image Turbo [ZH]" if "Z-Image Turbo [ZH]" in enhancer_options()
                                else (enhancer_options()[0] if enhancer_options() else "")),
                    "tooltip": "增强预设（= 提示词设定 / system prompt）：可点面板下方「编辑增强预设」改 txt（xb_skill/XB_LLMEnhancerPreset）",
                }),
                "task_preset": (task_options(), {
                    "default": ("Normal - 描述 [ZH]" if "Normal - 描述 [ZH]" in task_options()
                                else (task_options()[0] if task_options() else "")),
                    "tooltip": "反推预设（任务模板）；可点面板下方「编辑反推预设」改 txt（xb_skill/XB_LLMTaskPreset）。带 * 的预设里 * 是必填占位符",
                }),
                "open_api_settings": ("BOOLEAN", {
                    "default": False,
                    "label_on": "⚙️ 打开 API 设置…", "label_off": "⚙️ 打开 API 设置…",
                    "tooltip": "（兼容保留）API 设置已内嵌在「🤖 大语言模型配置」弹窗里，无需单独打开",
                }),
                # ↓ 内部字段：节点表面由前端面板隐藏
                "internal_prompt": ("STRING", {
                    "default": "", "multiline": True,
                    "tooltip": "节点内拼装/编辑的提示词正文（随工作流保存）",
                }),
                "manager_settings": ("STRING", {
                    "default": "", "multiline": True,
                    "tooltip": "本节点配置 JSON：元素面板（elements）+ LLM 反推（llm），随工作流保存",
                }),
            },
            "optional": {
                "text": ("STRING", {
                    "forceInput": True,
                    "tooltip": "外接提示词（优先于节点上的提示词框；接上线后提示词框锁定）",
                }),
                "images": ("IMAGE", {
                    "tooltip": "外接图像 / 视频帧（VLM 反推：图 → 提示词）",
                }),
            },
            "hidden": {
                "unique_id": "UNIQUE_ID",
            },
        }

    RETURN_TYPES = ("STRING", "LATENT", "STRING", "STRING")
    RETURN_NAMES = ("提示词", "空latent", "提示词列表", "提示词设定")
    OUTPUT_IS_LIST = (False, False, True, False)
    FUNCTION = "generate"
    CATEGORY = "XB_ToolBox/Image_Params"
    DESCRIPTION = ("生图提示词预设Pro：生图预设（空latent类型/输出语言/预设模式/画幅参数 + 8 大类元素面板提示词拼装）"
                   "＋ LLM 提示词增强反推（本地模型或在线 API、增强预设、反推预设、追加设定、采样参数、生成后控制）。"
                   "「启用 LLM 反推」关 = 原预设行为；开 = 图/文 → 提示词。输出：提示词 / 空latent / 提示词列表 / 提示词设定。")

    @classmethod
    def IS_CHANGED(cls, manager_settings="", skill_name=SKILL_NONE, skill_mode=SKILL_MODE_AUTO,
                   preset_mode="", **kwargs):
        keys = ("latent_kind", "output_lang", "preset_mode", "three_view_text", "aspect_ratio",
                "width", "height", "batch_size", "use_llm", "backend", "preset", "task_preset",
                "skill_name", "skill_mode", "internal_prompt")
        sig = {k: kwargs.get(k) for k in keys}
        extra = ""
        try:
            from .nodes_llama_prompt_reverse import read_api_settings
            extra = json.dumps(read_api_settings(), sort_keys=True, ensure_ascii=False)
        except Exception:
            extra = ""
        used = effective_skill_name(skill_mode, skill_name, preset_mode)
        return f"{manager_settings}|{extra}|{sig}|{skill_sig(used)}"

    def generate(self, latent_kind, output_lang, preset_mode, three_view_text, aspect_ratio,
                 width, height, batch_size, use_llm, backend, preset, task_preset, open_api_settings,
                 internal_prompt="", manager_settings="", text="", images=None, unique_id=None,
                 skill_name=SKILL_NONE, skill_mode=SKILL_MODE_AUTO):
        # ① 画幅归一 + 空 latent（与「🖼️ 生图提示词预设」逐行一致）
        spec = latent_kind_spec(latent_kind)
        w, h = normalize_size(aspect_ratio, width, height, spec["step"], spec["min"], spec["max"])
        latent = build_empty_latent(latent_kind, w, h, batch_size)

        # ② 拼装提示词（设定词 + 正文）+ 该模式的设定词（用户改过则用改过的；本节点固定文生图）
        has_img = _has_images(images)
        preset_eff = _preset_text_of(preset_mode, output_lang, three_view_text)   # 送模型 / 置顶都用这一份
        # 用户输入的正文（外接「📝 提示词」优先）：接了图片时它是【修改指令】，不是待增强的提示词
        body_in = (text or "").strip() or (internal_prompt or "").strip()
        base_prompt = build_prompt(output_lang, preset_mode, three_view_text, internal_prompt)

        # ③ LLM 反推配置（来自 manager_settings.llm；输出语言复用节点表面参数）
        llm = parse_llm_settings(_llm_section(manager_settings))
        llm["output_lang"] = output_lang if output_lang in _OUTPUT_LANGS else _OUTPUT_LANGS[0]
        # 任务块：有图 + 有文字 = 看图改图；有图无文字 = 看图反推；无图 = 原本文生文增强
        task_hint = ""
        if has_img:
            task_hint = _TASK_IMAGE_EDIT_HINT if body_in else _TASK_IMAGE_ONLY_HINT
        # 设定词来源：skill = 技能文档整段当系统提示词；预设词 = 用「增强预设 + 反推预设」
        reverse = _reverse_section(manager_settings)
        if reverse["source"] == "skill":
            skill_body = effective_skill_text(skill_mode, skill_name, preset_mode)   # 不用/手动/自动
            skill_used = effective_skill_name(skill_mode, skill_name, preset_mode)
            enhancer = ""                       # skill 自带完整规则 → 不叠加增强预设
            task_preset_used = "Empty - Nothing"
        else:
            skill_body, skill_used = "", "（预设词）"
            enhancer = preset                   # 增强预设 = 提示词设定 / system prompt
            task_preset_used = task_preset      # 反推预设 = 任务模板（可能是文件里的）
            register_task_preset(task_preset_used, llm["output_lang"])
        # ⚠️ 设定词**不参与** LLM（只用于最终输出时置顶）：
        #    → 系统提示词里不再塞「设定词参考」；用户正文也不再退化成「设定词+正文」。
        full_system = _build_system_prompt(enhancer, llm["extra_system"], llm["output_lang"],
                                           "", task_hint, skill_body)
        run = llm["run"]
        seed = int(run["seed"])
        next_seed = _next_seed(seed, run["seed_control"])

        prompt_list = []
        if use_llm:
            # ④ 后端选择（与「✨ 提示词增强反推」一致）
            if backend == "在线 API":
                api_cfg = build_api_config()
                print(f"[XB-生图预设Pro] LLM 反推 → 在线 API: {api_cfg['provider']} / {api_cfg['model']}")
                model_or_api = json.dumps(api_cfg, ensure_ascii=False)
            else:
                md = llm["model"]
                if not md["model"]:
                    raise ValueError(
                        "[XB-生图预设Pro] 未选择本地模型\n"
                        "请点节点上的「🤖 大语言模型配置」→ 选好「模型」后保存（或在「LLM 后端」里切到在线API）"
                    )
                local_cfg = {
                    "model": md["model"], "mmproj": md["mmproj"], "chat_handler": md["chat_handler"],
                    "n_ctx": md["n_ctx"], "vram_limit": md["vram_limit"],
                    "image_min_tokens": md["image_min_tokens"], "image_max_tokens": md["image_max_tokens"],
                }
                if not LLAMA_CPP_STORAGE.llm or LLAMA_CPP_STORAGE.current_config != local_cfg:
                    print("[XB-生图预设Pro] LLM 反推 → 加载本地模型...")
                    LLAMA_CPP_STORAGE.load_model(local_cfg)
                model_or_api = local_cfg

            # ④b 交给 LLM 的内容：接了图片时把用户输入包成【修改指令】
            #     （先识图 → 把指令应用到识别结果上 → 只输出修改后的最终画面，避免“先描述再修改”）
            #     ⚠️ 只用「用户输入的正文」；设定词绝不进 LLM（它只在最终输出时置顶）。
            if has_img:
                user_text = (_USER_EDIT_PREFIX + body_in) if body_in else _USER_IMAGE_ONLY
            else:
                user_text = body_in or _USER_TEXT_EMPTY_HINT
            def _ask(custom_prompt, seed_shift=0):
                """调一次 LLM（重试时用 seed_shift 换种子，避免拿到同一份输出）"""
                o1, _o2, _u = XB_llamaInstruct().process(
                    llama_model=model_or_api,
                    preset_prompt=task_preset_used,
                    custom_prompt=custom_prompt,
                    system_prompt=full_system,
                    inference_mode=run["inference_mode"],
                    max_frames=run["max_frames"],
                    max_size=run["max_size"],
                    seed=(seed + seed_shift) & _SEED_MAX,
                    force_offload=run["force_offload"],
                    save_states=run["save_states"],
                    unique_id=str(unique_id or "0"),
                    parameters=dict(llm["params"]),
                    images=images,
                    queue_handler=None,
                )
                return o1 or ""

            def _clean(txt):
                return strip_reasoning(txt) if run.get("strip_thinking", True) else txt

            # ④c 思考过程过滤（模型无视规则、把推理段一起输出时只留最终提示词）
            raw_out = _ask(user_text)
            body_out = _clean(raw_out)
            if body_out != raw_out.strip():
                safe_print(f"[XB-生图预设Pro] 🧠 已过滤思考过程：{len(raw_out)} 字 → {len(body_out)} 字")

            # ④c2 看图改图：若仍写成「原本…被替换为…」的对比式说明 → 自动重试一次
            if has_img and body_in and _leaks_modification_talk(body_out):
                safe_print("[XB-生图预设Pro] ⚠️ 输出含对比式修改说明，自动重试一次…")
                cand = _clean(_ask(user_text + _RETRY_REMINDER, seed_shift=1))
                if cand.strip() and not _leaks_modification_talk(cand):
                    body_out = cand
                    safe_print("[XB-生图预设Pro] ✅ 重试后已得到直接的最终画面描述")
                else:
                    safe_print("[XB-生图预设Pro] ⚠️ 重试仍不合格，保留本次输出")

            # ④d 设定词**原封不动**加在增强结果最顶端（与未启用 LLM 时的成句规则完全一致）
            final_prompt = build_prompt(output_lang, preset_mode, three_view_text, body_out)
        else:
            # 原「🖼️ 生图提示词预设」行为：直接输出拼装好的提示词
            final_prompt = base_prompt
        prompt_list = [line for line in (final_prompt or "").split("\n") if line.strip()]

        # ⑤ 日志
        try:
            shape = tuple(latent.get("samples").shape)
        except Exception:
            shape = ()
        print(f"[XB-生图预设Pro] {spec['label']} 丨 {w}x{h}（{aspect_ratio}·步长 {spec['step']}）"
              f"丨数量 {shape[0] if shape else batch_size}丨空latent {shape}"
              f"丨模式 {preset_mode}丨设定词 {'自定义' if (preset_eff and str(three_view_text or '').strip()) else ('默认' if preset_eff else '无')}"
              f"丨语言 {output_lang}丨任务 {'看图改图' if (has_img and body_in) else ('看图反推' if has_img else '文生文')}"
              f"丨LLM {'启用' if use_llm else '关闭'}（{backend}）丨设定词来源 {'skill' if reverse['source'] == 'skill' else '预设词'}：{skill_used}（{len(skill_body)} 字）"
              f"丨模版 文生图（固定）"
              f"丨提示词 {len(final_prompt)} 字")

        ui = {
            "text": [final_prompt],
            "backend": [backend],
            "system_prompt": [full_system or ""],
        }
        if use_llm and next_seed is not None:
            ui["seed"] = [next_seed]   # 前端回写到 manager_settings.llm.run.seed（仅 LLM 采样时才推进种子）
        return {"ui": ui, "result": (final_prompt, latent, prompt_list, full_system or "")}


NODE_CLASS_MAPPINGS = {
    "XB_ImagePromptPresetPro": XB_ImagePromptPresetPro,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "XB_ImagePromptPresetPro": "XB-BOX - 🖼️ 生图提示词预设Pro",
}


# ── HTTP 路由：面板「编辑增强预设 / 编辑反推预设」读取「内置 + 文件」合并后的清单 ──
# 内置预设写在 nodes_llama.py 里（不是 txt），编辑弹窗要能一起列出来并载入原文；
# 保存时写同名 txt 即可覆盖内置（读取时文件优先）。
try:
    from server import PromptServer  # type: ignore
    from aiohttp import web  # type: ignore

    @PromptServer.instance.routes.get("/xb_toolbox/llm_presets")
    async def xb_llm_presets(request):  # noqa: ANN001
        kind = str(request.rel_url.query.get("kind") or "enhancer").strip().lower()
        lang = str(request.rel_url.query.get("lang") or "")
        if kind == "task":
            labels, getter = task_options(), task_text
        else:
            labels, getter = enhancer_options(), enhancer_text
        texts = {}
        for lb in labels:
            t = getter(lb, lang)
            if t:
                texts[lb] = t
        node_name = LLM_TASK_NODE if kind == "task" else LLM_ENHANCER_NODE
        return web.json_response({"ok": True, "kind": kind, "labels": labels,
                                  "texts": texts,
                                  "lang": preset_lang_folder(lang),
                                  "dir": xb_presets.node_dir(node_name, preset_lang_folder(lang)),
                                  "backup_dir": xb_presets.backup_dir(preset_lang_folder(lang), node_name)})
except Exception:  # pragma: no cover - 仅在没有运行中的 ComfyUI 时走到
    pass
