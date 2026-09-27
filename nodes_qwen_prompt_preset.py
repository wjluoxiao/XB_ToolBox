"""
XB-BOX - 🖼️ Qwen2.1提示词预设
==============================
「XB-BOX - 🖼️ 生图提示词预设Pro」的兄弟节点：保留生图预设与元素面板，
把「LLM 反推」换成 **官方 Load CLIP + 官方 Generate Text** 这套纯本地文本生成链路。

① 生图预设
   · 空latent类型（9 种主流模型，逐字段对齐官方 latent_format）
   · 输出语言 / 预设模式 / 设定词（三视图·四视图·五视图·背景纯透明）
   · 画幅比例 / 宽度 / 高度 / 生成数量
   · 元素面板提示词拼装（8 大类词表，前端 js/xb_qwen_prompt_preset.js）

② 文本生成（官方两个节点的参数，逐字对齐；没有开关，执行即生成）
   · 模型选择 = 官方 Load CLIP：clip_name（models/text_encoders）+ type（默认 qwen_image）+ device（默认 default）
   · 参数设置 = 官方 Generate Text 全量参数：
     max_length / sampling_mode（on·off）/ temperature / top_k / top_p / min_p /
     repetition_penalty / presence_penalty / seed / thinking / use_default_template / mtp
   * 入参 prompt = 【参考设定·设定词】+【正文】+【额外要求·追加设定】
   · 出参 = 设定词原封不动置顶 + 生成文本（与「生图提示词预设」的成句规则一致）
   · SKILL选择 = support_llama/skills 里的 txt，整段作为官方 Generate Text 的 system_prompt 送进模型
     （与官方同义：use_default_template = 关时 system_prompt 被忽略）

输出：提示词 / 空latent（只有两路；没有 提示词列表 / 提示词设定）

CATEGORY: XB_ToolBox/Image_Params
"""

import gc
import json

import folder_paths
import torch

import comfy.sd

from .nodes_image_prompt_preset import (
    ASPECT_RATIO_OPTIONS,
    BATCH_MAX,
    DEFAULT_LATENT_KIND,
    IO_MODE_AUTO,
    IO_MODES,
    LATENT_KINDS,
    MAX_RESOLUTION,
    OUTPUT_LANGS,
    PRESET_MODES,
    PRESET_TEXT,
    SIZE_MIN,
    SIZE_STEP,
    THREE_VIEW_TEXT,
    build_empty_latent,
    build_prompt,
    io_mode_of,
    latent_kind_spec,
    mode_needs_image,
    normalize_mode,
    normalize_size,
    preset_text_of,
    resolve_io_mode,
    safe_print,
    skill_mode_of,
)
from .nodes_image_prompt_preset import (SKILL_MODE_AUTO, SKILL_MODES, effective_skill_name, effective_skill_text)

from .nodes_image_prompt_preset import SKILL_MODE_AUTO, SKILL_MODES, effective_skill_name, effective_skill_text
from .xb_skills import SKILL_NONE as _SKILL_NONE
from .xb_skills import skill_list as _skill_lister
from .xb_skills import skill_path as _skill_pather
from .xb_skills import skill_sig as _skill_signer
from .xb_skills import skill_text as _read_skill_text

DEFAULT_LANG = OUTPUT_LANGS[0]
# 用户要求：本节点的空latent类型默认 Qwen-image（与节点定位一致）
DEFAULT_LATENT = "Qwen-image" if "Qwen-image" in LATENT_KINDS else DEFAULT_LATENT_KIND

# ══════════════════════════════════════════════════════════════
#  SKILL（技能文件 = 官方 Generate Text 的 system_prompt）
#  读取器在 xb_skills.py（与「生图提示词预设Pro」共用一份）
# ══════════════════════════════════════════════════════════════

SKILL_NONE = _SKILL_NONE                       # combo 第一项 = 不接技能（与旧工作流行为一致）


def skill_list():
    return _skill_lister()


def _skill_path(name):
    return _skill_pather(name)


def _skill_sig(name):
    return _skill_signer(name)


def _skill_text(name):
    return _read_skill_text(name, "[XB-Qwen提示词预设]")

# ═══════════════════════════════════════════════════════════════
#  官方节点参数表（逐字复制，升级 ComfyUI 后如果官方枚举变了只需改这里）
# ═══════════════════════════════════════════════════════════════

# nodes.py::CLIPLoader 的 type 枚举
CLIP_TYPES = [
    "stable_diffusion", "stable_cascade", "sd3", "stable_audio", "mochi", "ltxv", "pixart",
    "cosmos", "lumina2", "wan", "hidream", "chroma", "ace", "omnigen2", "qwen_image",
    "hunyuan_image", "flux2", "ovis", "longcat_image", "cogvideox", "lens", "pixeldit",
    "ideogram4", "boogu", "krea2", "joyimage", "mage", "minimax", "yue2",
]
DEFAULT_CLIP_TYPE = "qwen_image"     # 用户要求：类型默认 Qwen_image
CLIP_DEVICES = ["default", "cpu"]    # nodes.py::CLIPLoader 的 device 枚举
DEFAULT_DEVICE = "default"           # 用户要求：设备默认 default

# comfy_extras/nodes_textgen.py::TextGenerate 的参数
SAMPLING_MODES = ["on", "off"]
MTP_MODES = ["auto", "off", "2", "3", "4", "5"]
_SEED_MAX = 0xFFFFFFFFFFFFFFFF

# 输出语言提示（拼进送模型的 prompt；本节点不依赖其它模块，自己留一份）
_LANG_HINT = {
    "中文 [ZH]": "【输出语言】请始终使用中文输出。",
    "英文 [EN]": "【Output language】Always respond in English.",
}

_SETTING_KEYS = ("latent_kind", "output_lang", "preset_mode", "io_mode", "three_view_text", "aspect_ratio",
                 "width", "height", "batch_size", "clip_name", "clip_type", "device",
                 "max_length", "sampling_mode", "temperature", "top_k", "top_p", "min_p",
                 "repetition_penalty", "presence_penalty", "seed", "thinking",
                 "use_default_template", "mtp", "skill_name", "skill_mode", "internal_prompt")


def text_encoder_list():
    """官方 Load CLIP 的模型列表（models/text_encoders）"""
    try:
        return folder_paths.get_filename_list("text_encoders")
    except Exception:
        return []


# ═══════════════════════════════════════════════════════════════
#  配置解析（None / 缺失 / 非法一律安全回落）
# ═══════════════════════════════════════════════════════════════

DEFAULT_SETTINGS = {
    "extra_settings": "",                       # 追加设定
}


def parse_settings(raw):
    """manager_settings（JSON 字符串 / 字典 / None）→ 完整配置

    配置段在 `manager_settings.qwen` 下（与前端 xbrParseQwen / xbrSaveJson 对齐）；
    为兼容早期写在顶层的写法，两处都读，qwen 优先。
    ⚠️ `extra_settings`（追加设定）的**面板入口已按用户要求删除**，这里保留读取只为兼容
       旧工作流里已经填过的值（新节点永远是空串，等于不追加【额外要求】）。
    """
    data = {}
    if isinstance(raw, dict):
        data = raw
    elif isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                data = parsed
        except Exception:
            data = {}
    sec = data.get("qwen") if isinstance(data.get("qwen"), dict) else {}
    extra = sec.get("extra_settings")
    if extra is None:
        extra = data.get("extra_settings")      # 兼容：早期版本写在顶层
    return {"extra_settings": str(extra or "")}


def _num(value, default, lo=None, hi=None):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if v != v:      # NaN
        return default
    if lo is not None and v < lo:
        v = lo
    if hi is not None and v > hi:
        v = hi
    return v


def _pick(value, allowed, default):
    return value if value in allowed else default


def _file_sig(name):
    """模型文件的 大小 + 修改时间（换文件即失效，不必手动清缓存）"""
    try:
        path = folder_paths.get_full_path("text_encoders", name)
        if not path:
            return ""
        import os
        st = os.stat(path)
        return f"{st.st_size}:{int(st.st_mtime)}"
    except Exception:
        return ""


# ═══════════════════════════════════════════════════════════════
#  提示词组装（与「生图提示词预设」一致：设定词原封不动置顶）
# ═══════════════════════════════════════════════════════════════

def _preset_text_of(preset_mode, output_lang, three_view_text, io_mode=None, has_image=False):
    """当前预设模式的设定词（按模版分两套）

    · 用户改过 → 用改过的；
    · 没改过（等于任一默认）→ 按当前模版（文生图 / 图生图）取默认，
      避免老工作流把「图生图版」文本（如 360°全景 的「把输入的单视角照片扩展成…」）带进文生图。
    """
    return preset_text_of(preset_mode, output_lang, three_view_text,
                          io_mode=io_mode, has_image=has_image)


def build_model_prompt(body, preset_text, extra_settings, output_lang, with_lang_hint=True):
    """送给 Generate Text 的 prompt：「参考设定 + 正文 + 额外要求」三段式

    `with_lang_hint=False`（选中了 SKILL 时）不叠加语言提示——技能文件自带语言决策，
    再叠一条「始终用中文」会直接违背技能（与「生图提示词预设Pro」的处理一致）。
    """
    parts = []
    ref = (preset_text or "").strip()
    if ref:
        parts.append("【参考设定】\n" + ref
                     + "\n（上面这段设定会被原样加在最终提示词最顶端，不需要你复述或改写它）")
    parts.append("【正文】\n" + ((body or "").strip() or ""))
    extra = (extra_settings or "").strip()
    if extra:
        parts.append("【额外要求】\n" + extra)
    if with_lang_hint:
        parts.append(_LANG_HINT.get(output_lang, _LANG_HINT[DEFAULT_LANG]))
    return "\n\n".join([p for p in parts if p])


# ═══════════════════════════════════════════════════════════════
#  CLIP 加载（逐行对齐官方 nodes.py::CLIPLoader）+ 单条缓存
# ═══════════════════════════════════════════════════════════════

_CLIP_CACHE = {"key": None, "clip": None}


def _load_clip(clip_name, clip_type, device):
    clip_type_value = getattr(comfy.sd.CLIPType, str(clip_type).upper(), comfy.sd.CLIPType.STABLE_DIFFUSION)
    model_options = {}
    if device == "cpu":
        model_options["load_device"] = model_options["offload_device"] = torch.device("cpu")
    clip_path = folder_paths.get_full_path_or_raise("text_encoders", clip_name)
    return comfy.sd.load_clip(
        ckpt_paths=[clip_path],
        embedding_directory=folder_paths.get_folder_paths("embeddings"),
        clip_type=clip_type_value,
        model_options=model_options,
    )


def get_clip(clip_name, clip_type, device):
    """取 CLIP：同参数复用缓存，换参数才重新加载（只留 1 份，避免显存里堆一堆文本编码器）"""
    key = (str(clip_name or ""), str(clip_type or ""), str(device or ""))
    if _CLIP_CACHE["clip"] is not None and _CLIP_CACHE["key"] == key:
        return _CLIP_CACHE["clip"]
    if not key[0]:
        raise ValueError(
            "[XB-Qwen提示词预设] 未找到文本编码器模型\n"
            "请把文本编码器（例如 Qwen-Image 的 text encoder）放进 ComfyUI/models/text_encoders，\n"
            "再点节点上的「🤖 LLM设置」→ 模型选择 里选它。"
        )
    if _CLIP_CACHE["clip"] is not None:
        _CLIP_CACHE["clip"] = None
        gc.collect()
        try:
            import comfy.model_management
            comfy.model_management.soft_empty_cache()
        except Exception:
            pass
    clip = _load_clip(key[0], key[1], key[2])
    _CLIP_CACHE["key"] = key
    _CLIP_CACHE["clip"] = clip
    return clip


# ═══════════════════════════════════════════════════════════════
#  节点
# ═══════════════════════════════════════════════════════════════

class XB_QwenPromptPreset:
    """Qwen2.1提示词预设：生图预设（提示词拼装 + 空latent）+ 官方 Load CLIP + 官方 Generate Text。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                # ══ ① 生图预设（与「🖼️ 生图提示词预设」一致）══
                "latent_kind": (list(LATENT_KINDS), {
                    "default": DEFAULT_LATENT,
                    "tooltip": "空latent类型：选你正在用的模型即可（自动适配形状/下采样/步长）",
                }),
                "output_lang": (list(OUTPUT_LANGS), {
                    "default": DEFAULT_LANG,
                    "tooltip": "输出语言：决定词表与设定词按哪种语言加载、生成文本的语言",
                }),
                "io_mode": (list(IO_MODES), {
                    "default": IO_MODE_AUTO,
                    "tooltip": "模版：自动 = 按有没有接参考图判断；文生图 / 图生图 = 手动指定。"
                               "每个预设模式都有两套设定词，按它自动选用（模板切换会直接把设定词换成对应那套）",
                }),
                "preset_mode": (list(PRESET_MODES), {
                    "default": PRESET_MODES[0],
                    "tooltip": "预设模式：无预设=不前置任何设定词，只输出正文；其余档位把该档设定词置顶到最终提示词最顶端（设定词分文生图 / 图生图两套）",
                }),
                "three_view_text": ("STRING", {
                    "default": THREE_VIEW_TEXT[DEFAULT_LANG], "multiline": True,
                    "tooltip": "设定词：预设模式对应的设定文本；改过的按「模式 + 语言」记进节点，换模式 / 换语言都不会丢",
                }),
                "skill_mode": (list(SKILL_MODES), {
                    "default": SKILL_MODE_AUTO,
                    "tooltip": "SKILL 模式：自动 = 按预设模式适配（图生图档 → prompt_edit，其余 → prompt_t2i）；"
                               "手动 = 用下面选中的那一个；不用 = SKILL 完全不生效（哪怕选了也不生效）",
                }),
                "skill_name": (skill_list(), {
                    "default": SKILL_NONE,
                    "tooltip": "SKILL选择：support_llama/skills 里的 txt，整段作为模型自带的系统提示词（官方 Generate Text 的 system_prompt）；"
                               "仅在「SKILL 模式 = 手动」时生效；「使用内置模板」关闭时也不生效",
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

                # ══ ② 官方 Load CLIP（模型选择）══
                "clip_name": (text_encoder_list(), {
                    "tooltip": "文本编码器（models/text_encoders）。与官方 Load CLIP 同一个列表。",
                }),
                "clip_type": (list(CLIP_TYPES), {
                    "default": DEFAULT_CLIP_TYPE,
                    "tooltip": "类型：与官方 Load CLIP 一致；Qwen-Image 系文本编码器选 qwen_image",
                }),
                "device": (list(CLIP_DEVICES), {
                    "default": DEFAULT_DEVICE,
                    "tooltip": "设备：与官方 Load CLIP 一致；default=自动，cpu=放内存",
                }),

                # ══ ③ 官方 Generate Text（参数设置，全量）══
                "max_length": ("INT", {
                    "default": 512, "min": 1, "max": 32768,
                    "tooltip": "Generate Text · max_length：最大生成长度",
                }),
                "sampling_mode": (list(SAMPLING_MODES), {
                    "default": "on",
                    "tooltip": "Generate Text · Sampling Mode：on=按下面的采样参数生成；off=贪心解码，下面的采样参数不生效",
                }),
                "temperature": ("FLOAT", {
                    "default": 0.7, "min": 0.01, "max": 2.0, "step": 0.000001,
                    "tooltip": "Generate Text · temperature",
                }),
                "top_k": ("INT", {
                    "default": 64, "min": 0, "max": 1000,
                    "tooltip": "Generate Text · top_k",
                }),
                "top_p": ("FLOAT", {
                    "default": 0.95, "min": 0.0, "max": 1.0, "step": 0.01,
                    "tooltip": "Generate Text · top_p",
                }),
                "min_p": ("FLOAT", {
                    "default": 0.05, "min": 0.0, "max": 1.0, "step": 0.01,
                    "tooltip": "Generate Text · min_p",
                }),
                "repetition_penalty": ("FLOAT", {
                    "default": 1.05, "min": 0.0, "max": 5.0, "step": 0.01,
                    "tooltip": "Generate Text · repetition_penalty",
                }),
                "presence_penalty": ("FLOAT", {
                    "default": 0.0, "min": 0.0, "max": 5.0, "step": 0.01,
                    "tooltip": "Generate Text · presence_penalty",
                }),
                "seed": ("INT", {
                    "default": 0, "min": 0, "max": _SEED_MAX,
                    "tooltip": "Generate Text · seed：生成种子（节点表面可点 🔁 切换生成后控制）",
                }),
                "thinking": ("BOOLEAN", {
                    "default": False,
                    "label_on": "🧠 思考模式 开", "label_off": "🧠 思考模式 关",
                    "tooltip": "Generate Text · thinking：模型支持时以思考模式生成（思考内容不会进入输出）",
                }),
                "use_default_template": ("BOOLEAN", {
                    "default": True,
                    "label_on": "使用内置模板", "label_off": "不使用内置模板",
                    "tooltip": "Generate Text · use_default_template：使用模型自带的系统提示词 / 对话模板",
                }),
                "mtp": (list(MTP_MODES), {
                    "default": "auto",
                    "tooltip": "Generate Text · mtp：多 token 预测投机解码；没有 MTP 权重时无效",
                }),

                # ══ ④ 内部字段（节点表面由前端面板隐藏）══
                "internal_prompt": ("STRING", {
                    "default": "", "multiline": True,
                    "tooltip": "节点内拼装/编辑的提示词正文（随工作流保存）",
                }),
                "manager_settings": ("STRING", {
                    "default": "", "multiline": True,
                    "tooltip": "本节点配置 JSON：元素面板 elements + 追加设定 extra_settings + 生成后控制 run",
                }),
            },
            "optional": {
                "text": ("STRING", {
                    "forceInput": True,
                    "tooltip": "外接提示词（优先于节点上的提示词框；接上线后提示词框锁定）",
                }),
                "images": ("IMAGE", {
                    "tooltip": "外接图像：一批图 = N 张参考图（官方图像编辑最多 10 张，提示词里可引用「第 N 张图」）。"
                               "用「📦 批量图像」等多图节点直接接这里即可。",
                }),
            },
            "hidden": {
                "unique_id": "UNIQUE_ID",
            },
        }

    RETURN_TYPES = ("STRING", "LATENT")
    RETURN_NAMES = ("提示词", "空latent")
    OUTPUT_IS_LIST = (False, False)
    FUNCTION = "generate"
    CATEGORY = "XB_ToolBox/Image_Params"
    DESCRIPTION = ("Qwen2.1提示词预设：生图预设（空latent类型/输出语言/预设模式/画幅参数 + 8 大类元素面板拼装）"
                   "＋ 官方 Load CLIP 与官方 Generate Text（纯本地文本生成，无开关，执行即生成）。"
                   "输出：提示词 / 空latent。")

    @classmethod
    def IS_CHANGED(cls, clip_name="", skill_name=SKILL_NONE, skill_mode=SKILL_MODE_AUTO,
                   preset_mode="", **kwargs):
        sig = {k: kwargs.get(k) for k in _SETTING_KEYS}
        used = effective_skill_name(skill_mode, skill_name, preset_mode)
        return f"{json.dumps(sig, sort_keys=True, ensure_ascii=False, default=str)}|{_file_sig(clip_name)}|{_skill_sig(used)}"

    def generate(self, latent_kind, output_lang, preset_mode, three_view_text, aspect_ratio,
                 width, height, batch_size,
                 clip_name, clip_type, device,
                 max_length, sampling_mode, temperature, top_k, top_p, min_p,
                 repetition_penalty, presence_penalty, seed, thinking, use_default_template, mtp,
                 internal_prompt="", manager_settings="", text="", images=None, unique_id=None,
                 skill_name=SKILL_NONE, skill_mode=SKILL_MODE_AUTO, io_mode=IO_MODE_AUTO):
        # ① 画幅归一 + 空 latent（与「🖼️ 生图提示词预设」逐行一致）
        spec = latent_kind_spec(latent_kind)
        w, h = normalize_size(aspect_ratio, width, height, spec["step"], spec["min"], spec["max"])
        latent = build_empty_latent(latent_kind, w, h, batch_size)

        # ② 组装送模型的 prompt（设定词只作参考，输出时节点自己置顶）
        st = parse_settings(manager_settings)
        lang = output_lang if output_lang in OUTPUT_LANGS else DEFAULT_LANG
        # 有没有接输入图 + 模版（自动/文生图/图生图）→ 决定用哪一套设定词
        has_img = False
        try:
            has_img = images is not None and hasattr(images, "shape") and len(images) > 0
        except Exception:
            has_img = False
        io_eff = resolve_io_mode(io_mode, has_img)          # 文生图 / 图生图
        base_prompt = build_prompt(lang, preset_mode, three_view_text, internal_prompt,
                                   has_image=has_img, io_mode=io_mode)
        preset_eff = _preset_text_of(preset_mode, lang, three_view_text,
                                     io_mode=io_mode, has_image=has_img)   # 送模型 / 置顶都用这一份
        body = (text or "").strip() or (internal_prompt or "").strip()
        # SKILL：不用 / 手动 / 自动（默认自动，按预设模式适配）
        skill_text = effective_skill_text(skill_mode, skill_name, preset_mode, use_default_template)
        skill_used = effective_skill_name(skill_mode, skill_name, preset_mode)
        # 选中 SKILL 时不再叠加语言提示（技能自带语言决策，叠加会互相打架）
        model_prompt = build_model_prompt(body or base_prompt, preset_eff, st["extra_settings"], lang,
                                          with_lang_hint=not bool(skill_text))

        # ③ 官方 Load CLIP + 官方 Generate Text（参数与调用方式逐字对齐官方节点）
        clip = get_clip(clip_name, clip_type, device)
        # 官方 image 输入：一批图 = N 张参考图（官方图像编辑最多 10 张，提示词可引用「第 N 张图」）
        # ⚠️ 不能把多帧当 video：Qwen-Image-2.1 的文本编码器链里**没人读 video**
        #    （qwen_image21/qwen3vl/sd1_clip 全程不碰 video，全库只有 gemma4 那个 tokenizer 认），
        #    一旦当成 video 传，图片会被静默丢弃 → 模型只看得到文字。
        image_arg = images if (images is not None and hasattr(images, "shape")) else None
        img_count = 0
        try:
            if image_arg is not None:
                img_count = int(len(image_arg))
        except Exception:
            img_count = 0
        if mode_needs_image(preset_mode) and img_count == 0:
            safe_print(f"[XB-Qwen提示词预设] ⚠️ 当前档位「{preset_mode}」属于图生图，但没有接参考图"
                  f"（🖼️ 图像，多张按批接即可）→ 本次按「文生图」设定词纯文字生成")
        try:                                              # 日志留痕：看得见“到底送了什么给文本编码器”
            print(f"[XB-Qwen提示词预设] 送模型 prompt（{len(model_prompt)} 字）："
                  f"{model_prompt[:120].replace(chr(10), ' / ')}" + ("…" if len(model_prompt) > 120 else ""))
        except Exception:
            pass
        # SKILL 已在上方读入 skill_text，并在那里决定了要不要叠加语言提示
        tokens = clip.tokenize(
            model_prompt,
            image=image_arg,
            skip_template=not bool(use_default_template),
            min_length=1,
            thinking=bool(thinking),
            system_prompt=skill_text,
        )
        _mtp = False if mtp == "off" else (True if mtp == "auto" else int(mtp))
        generated_ids = clip.generate(
            tokens,
            do_sample=(sampling_mode == "on"),
            max_length=int(max_length),
            temperature=float(temperature),
            top_k=int(top_k),
            top_p=float(top_p),
            min_p=float(min_p),
            repetition_penalty=float(repetition_penalty),
            presence_penalty=float(presence_penalty),
            seed=int(seed),
            mtp=_mtp,
        )
        raw = clip.decode(generated_ids) or ""

        # 思考段分离（与官方 TextGenerate 完全一致：不闭合时整段都算正文）
        reasoning, _, gen_text = raw.partition("</think>")
        if not reasoning.lstrip().startswith("<think>") and not model_prompt.rstrip().endswith("<think>"):
            gen_text = raw
        gen_text = gen_text.strip()

        # ④ 设定词原封不动置顶（与未生成时的成句规则一致；t2i/i2i 模版条款同样进最终提示词）
        final_prompt = build_prompt(lang, preset_mode, three_view_text, gen_text,
                                    has_image=has_img, io_mode=io_mode)

        try:
            shape = tuple(latent.get("samples").shape)
        except Exception:
            shape = ()
        print(f"[XB-Qwen提示词预设] {spec['label']} 丨 {w}x{h}（{aspect_ratio}·步长 {spec['step']}）"
              f"丨数量 {shape[0] if shape else batch_size}丨空latent {shape}"
              f"丨CLIP {clip_name}（{clip_type}·{device}）"
              f"丨Text 最大长度 {max_length}·采样 {sampling_mode}·思考 {'开' if thinking else '关'}"
              f"丨SKILL {skill_used}（{len(skill_text)} 字·{skill_mode_of(skill_mode)}）"
              f"丨模式 {preset_mode}丨模版 {io_eff}"
              f"{'（自动' + ('：检测到参考图' if has_img else '：未接参考图') + '）' if io_mode_of(io_mode) == IO_MODE_AUTO else ''}"
              f"丨参考图 {img_count} 张"
              f"丨种子 {seed}丨设定词 {'有' if preset_eff else '无'}丨生成 {len(gen_text)} 字丨输出 {len(final_prompt)} 字")

        ui = {
            "text": [final_prompt],
            "model": [str(clip_name or "-")],
            "gen_len": [len(gen_text)],
        }
        # 种子回写不在后端做：节点上的 seed widget 由 ComfyUI 原生的
        # control_after_generate 机制自动游走（与官方采样节点一致，避免双头写）
        return {"ui": ui, "result": (final_prompt, latent)}


NODE_CLASS_MAPPINGS = {
    "XB_QwenPromptPreset": XB_QwenPromptPreset,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "XB_QwenPromptPreset": "XB-BOX - 🖼️ Qwen2.1提示词预设",
}
