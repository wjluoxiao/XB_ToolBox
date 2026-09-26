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
import random
import re

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
from .nodes_image_prompt_preset import (
    ASPECT_RATIO_OPTIONS,
    BATCH_MAX,
    DEFAULT_LATENT_KIND,
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
    latent_kind_spec,
    normalize_size,
)

DEFAULT_LANG = OUTPUT_LANGS[0]

# 设定词（预设模式的设定文本）送给 LLM 时的参考说明：它会被节点原样置顶，LLM 只管增强正文
_PRESET_REF_HINT = (
    "【设定词（会被原封不动加在最终提示词的最顶端，此处仅作为增强参考）】\n"
    "{text}\n\n"
    "注意：上面这段设定词由节点自动前置，不要在输出里重复、改写或复述它；"
    "你的任务只是增强「正文」中的画面描述。"
)


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


def _next_seed(seed, mode):
    """生成后控制：返回「下一次」种子（fixed 返回 None = 不回写）"""
    if mode == "randomize":
        return random.randint(0, _SEED_MAX)
    if mode == "increment":
        return (seed + 1) & _SEED_MAX
    if mode == "decrement":
        return (seed - 1) & _SEED_MAX
    return None


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


def _build_system_prompt(preset, extra, output_lang, preset_text="", task_hint=""):
    """提示词设定 = 增强预设 + 输出语言 + 设定词参考 + 追加设定 + 只输出最终提示词的硬规则 + 任务块

    `preset_text`（预设模式的设定词）只作为**增强参考**告诉 LLM：它会被节点原样置顶到最终提示词，
    禁止在正文里重复 / 改写它。
    `task_hint`（看图 / 改图任务）放**最末**，优先级最高——决定“先识图再改”还是“纯看图”。
    """
    parts = [XB_llamaPromptEnhancer().main(preset)[0] or ""]
    parts.append(_LANG_HINT.get(output_lang, _LANG_HINT[_OUTPUT_LANGS[0]]))
    ref = (preset_text or "").strip()
    if ref:
        parts.append(_PRESET_REF_HINT.format(text=ref))
    extra = (extra or "").strip()
    if extra:
        parts.append(extra)
    parts.append(OUTPUT_FORMAT_HINT)                 # 放最后 = 最显眼（用户要求：不要思考过程）
    hint = (task_hint or "").strip()
    if hint:
        parts.append(hint)                            # 任务块更具体 → 又压在最上面
    return "\n\n".join([p for p in parts if p])


def _preset_text_of(preset_mode, output_lang, three_view_text):
    """当前预设模式的设定词（= 节点表面「预设句」框里的值）。

    · 用户改过 → 用改过的原文（含换行，前端按「模式|语言」存在节点里，换模式不丢）；
    · 空 / 未改 → 用「模式 × 输出语言」的默认设定词；
    · 常规文生图等无设定词的模式 → 空串（不前置任何内容）。
    """
    defaults = PRESET_TEXT.get(preset_mode) if isinstance(PRESET_TEXT, dict) else None
    if not defaults:
        return ""
    lang = output_lang if output_lang in OUTPUT_LANGS else DEFAULT_LANG
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
                "preset_mode": (list(PRESET_MODES), {
                    "default": PRESET_MODES[0],
                    "tooltip": "预设模式：常规文生图=只输出正文；人物三视图 / 人物四视图 / 人物五视图 / 背景纯透明 = 自动在正文前加预设句",
                }),
                "three_view_text": ("STRING", {
                    "default": THREE_VIEW_TEXT[DEFAULT_LANG], "multiline": True,
                    "tooltip": "预设模式的设定词（人物三视图 / 人物四视图 / 人物五视图 / 背景纯透明 四个模式生效；常规文生图时自动隐藏）\n"
                               "· 最终提示词输出时它会被【原封不动】加在最顶端；\n"
                               "· 用户改过的设定词按「模式 + 语言」存进本节点（换模式 / 换语言都不会丢）；\n"
                               "· 启用 LLM 时它作为增强参考交给 LLM（LLM 只增强正文，不改写它）",
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
                    "label_on": "✅ 启用 LLM 反推", "label_off": "⛔ 未启用 LLM 反推",
                    "tooltip": "关（默认）= 只输出拼装好的提示词 + 空latent（不加载模型、不调 API）\n"
                               "开 = 把（外接「提示词」或节点上的提示词）+ 外接「图像」交给 LLM 反推",
                }),
                "backend": (["本地模型", "在线 API"], {
                    "default": "本地模型",
                    "tooltip": "本地模型 = llama-cpp-python；在线 API = 在「🤖 大语言模型配置」弹窗里填服务商/模型/Key/地址",
                }),
                "preset": (cls._PRESETS, {
                    "default": cls._DEFAULT_PRESET,
                    "tooltip": "增强预设（= 提示词设定 / system prompt），从「提示词设定」端口原样输出",
                }),
                "task_preset": (preset_tags, {
                    "default": cls._DEFAULT_TASK,
                    "tooltip": "反推预设（原「指令推理」的预设提示词）；带 * 的预设里 * 是必填占位符",
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
    def IS_CHANGED(cls, manager_settings="", **kwargs):
        keys = ("latent_kind", "output_lang", "preset_mode", "three_view_text", "aspect_ratio",
                "width", "height", "batch_size", "use_llm", "backend", "preset", "task_preset",
                "internal_prompt")
        sig = {k: kwargs.get(k) for k in keys}
        extra = ""
        try:
            from .nodes_llama_prompt_reverse import read_api_settings
            extra = json.dumps(read_api_settings(), sort_keys=True, ensure_ascii=False)
        except Exception:
            extra = ""
        return f"{manager_settings}|{extra}|{sig}"

    def generate(self, latent_kind, output_lang, preset_mode, three_view_text, aspect_ratio,
                 width, height, batch_size, use_llm, backend, preset, task_preset, open_api_settings,
                 internal_prompt="", manager_settings="", text="", images=None, unique_id=None):
        # ① 画幅归一 + 空 latent（与「🖼️ 生图提示词预设」逐行一致）
        spec = latent_kind_spec(latent_kind)
        w, h = normalize_size(aspect_ratio, width, height, spec["step"], spec["min"], spec["max"])
        latent = build_empty_latent(latent_kind, w, h, batch_size)

        # ② 拼装提示词（设定词 + 正文）+ 该模式的设定词（用户改过则用改过的）
        base_prompt = build_prompt(output_lang, preset_mode, three_view_text, internal_prompt)
        preset_text = _preset_text_of(preset_mode, output_lang, three_view_text)
        # 用户输入的正文（外接「📝 提示词」优先）：接了图片时它是【修改指令】，不是待增强的提示词
        body_in = (text or "").strip() or (internal_prompt or "").strip()
        has_img = _has_images(images)

        # ③ LLM 反推配置（来自 manager_settings.llm；输出语言复用节点表面参数）
        llm = parse_llm_settings(_llm_section(manager_settings))
        llm["output_lang"] = output_lang if output_lang in _OUTPUT_LANGS else _OUTPUT_LANGS[0]
        # 任务块：有图 + 有文字 = 看图改图；有图无文字 = 看图反推；无图 = 原本文生文增强
        task_hint = ""
        if has_img:
            task_hint = _TASK_IMAGE_EDIT_HINT if body_in else _TASK_IMAGE_ONLY_HINT
        full_system = _build_system_prompt(preset, llm["extra_system"], llm["output_lang"],
                                           preset_text, task_hint)
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
            if has_img:
                user_text = (_USER_EDIT_PREFIX + body_in) if body_in else _USER_IMAGE_ONLY
            else:
                user_text = body_in or base_prompt
            def _ask(custom_prompt, seed_shift=0):
                """调一次 LLM（重试时用 seed_shift 换种子，避免拿到同一份输出）"""
                o1, _o2, _u = XB_llamaInstruct().process(
                    llama_model=model_or_api,
                    preset_prompt=task_preset,
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
                print(f"[XB-生图预设Pro] 🧠 已过滤思考过程：{len(raw_out)} 字 → {len(body_out)} 字")

            # ④c2 看图改图：若仍写成「原本…被替换为…」的对比式说明 → 自动重试一次
            if has_img and body_in and _leaks_modification_talk(body_out):
                print("[XB-生图预设Pro] ⚠️ 输出含对比式修改说明，自动重试一次…")
                cand = _clean(_ask(user_text + _RETRY_REMINDER, seed_shift=1))
                if cand.strip() and not _leaks_modification_talk(cand):
                    body_out = cand
                    print("[XB-生图预设Pro] ✅ 重试后已得到直接的最终画面描述")
                else:
                    print("[XB-生图预设Pro] ⚠️ 重试仍不合格，保留本次输出")

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
              f"丨模式 {preset_mode}丨设定词 {'自定义' if (preset_text and three_view_text and str(three_view_text).strip()) else ('默认' if preset_text else '无')}"
              f"丨语言 {output_lang}丨任务 {'看图改图' if (has_img and body_in) else ('看图反推' if has_img else '文生文')}"
              f"丨LLM {'启用' if use_llm else '关闭'}（{backend}）丨提示词 {len(final_prompt)} 字")

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
