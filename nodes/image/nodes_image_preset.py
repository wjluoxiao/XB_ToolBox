"""XB-BOX - 🖼️ 图像编辑预设 —— 提示词拼装 + 姿态参考图 + 穿搭参考图
=================================================================
完全**继承** nodes_image_prompt_preset.XB_ImagePromptPreset 的参数与拼词逻辑：
· 表面参数 / 8 大元素面板 / 预设文件 / 设定词，一行都不改；
· 只做三件事：
    ① 去掉所有 latent 相关参数（latent类型 / 画幅比例 / 宽度 / 高度 / 生成数量）
       与「空latent」输出端口 —— 本节点只负责提示词与参考图；
    ② 多两个内部字段 pose_ref / outfit_ref（前端隐藏，由「🎬 姿态参考图选择 /
       👚 穿搭参考图选择」按钮写入，值 = JSON {"path": 库内相对路径, "name": 展示名}，
       随工作流保存）；
    ③ 多两个 IMAGE 输出「姿态图 / 穿搭图」，执行时从用户自行绑定的图库读图
       （带素材清单的整套图库或普通图片文件夹都支持，见 xb_gallery.py）。
"""

from ...libs import xb_gallery
from .nodes_image_prompt_preset import (
    LANG_ZH,
    MODE_TEXT2IMG,
    OUTPUT_LANGS,
    PRESET_MODES,
    XB_ImagePromptPreset,
    _norm_combo,
    build_prompt,
)

_REF_TOOLTIP = ("内部字段（节点表面不显示）：由「参考图选择」按钮写入的图库相对路径 JSON；"
                "随工作流保存，换机器 / 换图库后需重新选择。")

# 从父类里摘掉这几个「关于 latent」的输入（顺序保持父类剩余部分不变）
LATENT_FIELDS = ("latent_kind", "aspect_ratio", "width", "height", "batch_size")


class XB_ImagePreset(XB_ImagePromptPreset):
    """图像编辑预设：提示词拼装 + 姿态 / 穿搭参考图输出（无 latent 参数与端口）。"""

    @classmethod
    def INPUT_TYPES(cls):
        data = super().INPUT_TYPES()
        for key in LATENT_FIELDS:
            data["required"].pop(key, None)
        # 追加在 manager_settings 之后 → 不影响老工作流 widgets_values 的顺序
        data["required"]["pose_ref"] = ("STRING", {"default": "", "tooltip": _REF_TOOLTIP})
        data["required"]["outfit_ref"] = ("STRING", {"default": "", "tooltip": _REF_TOOLTIP})
        return data

    RETURN_TYPES = ("STRING", "IMAGE", "IMAGE")
    RETURN_NAMES = ("提示词", "姿态图", "穿搭图")
    FUNCTION = "generate"
    CATEGORY = "XB_ToolBox/Image_Params"
    DESCRIPTION = ("图像编辑预设：输出语言 + 8 大类元素面板拼词 + 预设句 / 预设文件，"
                   "外加「🎬 姿态参考图选择 / 👚 穿搭参考图选择」两个按钮：可绑定带素材清单的整套图库"
                   "（按体系/分类/视角/标签筛选，按姿势编号分组并带视角条）或任意普通图片文件夹（按文件名多宫格）。"
                   "参考图可单独勾选「禁用」：禁用后该输出不做任何输出（等同 mute），下游节点会被跳过。"
                   "不含 latent 参数，也不输出空 latent。输出：①提示词 ②姿态图 ③穿搭图。")

    @classmethod
    def IS_CHANGED(cls, manager_settings="", pose_ref="", outfit_ref="", **kwargs):
        keys = ("output_lang", "preset_mode", "three_view_text", "internal_prompt")
        sig = {k: kwargs.get(k) for k in keys}
        return (f"{manager_settings}|{sig}|{pose_ref}|{outfit_ref}"
                f"|{xb_gallery.fingerprint('pose', pose_ref)}"
                f"|{xb_gallery.fingerprint('costume', outfit_ref)}")

    def generate(self, output_lang, preset_mode, three_view_text,
                 internal_prompt="", manager_settings="", pose_ref="", outfit_ref=""):
        output_lang = _norm_combo(output_lang, OUTPUT_LANGS, LANG_ZH)
        preset_mode = _norm_combo(preset_mode, PRESET_MODES, MODE_TEXT2IMG)

        prompt = build_prompt(output_lang, preset_mode, three_view_text, internal_prompt)

        print(f"[XB-图像编辑预设] 模式 {preset_mode}丨语言 {output_lang}丨提示词 {len(prompt)} 字"
              f"丨姿态图 {'有' if pose_ref else '无'}丨穿搭图 {'有' if outfit_ref else '无'}")

        return (prompt,
                xb_gallery.load_reference("pose", pose_ref),
                xb_gallery.load_reference("costume", outfit_ref))


NODE_CLASS_MAPPINGS = {"XB_ImagePreset": XB_ImagePreset}
NODE_DISPLAY_NAME_MAPPINGS = {"XB_ImagePreset": "XB-BOX - 🖼️ 图像编辑预设"}
